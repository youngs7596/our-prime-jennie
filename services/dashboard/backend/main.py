#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dashboard Backend - FastAPI
JWT 인증, WebSocket 실시간 업데이트, REST API
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional
from contextlib import asynccontextmanager
import asyncio
import json
import logging

from fastapi import FastAPI, HTTPException, Depends, WebSocket, WebSocketDisconnect, status, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import jwt
import redis
import httpx

# --- shared 패키지 임포트 ---
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.db.connection import get_session, get_engine, ensure_engine_initialized
from shared.db.repository import (
    get_portfolio_summary,
    get_portfolio_with_current_prices,
    get_watchlist_all,
    get_recent_trades,
    get_scheduler_jobs,
)
from shared.db.models import Portfolio, WatchList, TradeLog

# --- 로깅 설정 (가장 먼저!) ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("dashboard")

# --- secrets.json 로드 및 DB 설정 ---
def load_secrets():
    """secrets.json 파일에서 시크릿 로드"""
    secrets_path = os.getenv("SECRETS_FILE", "/app/config/secrets.json")
    try:
        with open(secrets_path, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"secrets.json 로드 실패: {e}")
        return {}

def setup_db_credentials():
    """MariaDB 자격 증명을 환경 변수로 설정"""
    secrets = load_secrets()
    
    # MariaDB 사용 설정
    if not os.getenv("DB_TYPE"):
        os.environ["DB_TYPE"] = "MARIADB"
        logger.info("✅ DB_TYPE=MARIADB 설정")
    
    # MariaDB 자격 증명 (secrets.json 또는 기본값)
    if not os.getenv("MARIADB_USER"):
        os.environ["MARIADB_USER"] = secrets.get("mariadb-user", "root")
    if not os.getenv("MARIADB_PASSWORD"):
        os.environ["MARIADB_PASSWORD"] = secrets.get("mariadb-password", "your-db-password")
    if not os.getenv("MARIADB_HOST"):
        # Docker 컨테이너에서 Windows MariaDB 접근: host-gateway 사용
        os.environ["MARIADB_HOST"] = secrets.get("mariadb-host", "127.0.0.1")
    if not os.getenv("MARIADB_PORT"):
        os.environ["MARIADB_PORT"] = secrets.get("mariadb-port", "3306")
    if not os.getenv("MARIADB_DBNAME"):
        os.environ["MARIADB_DBNAME"] = secrets.get("mariadb-dbname", "jennie_db")
    
    logger.info(f"✅ MariaDB 설정: {os.getenv('MARIADB_HOST')}:{os.getenv('MARIADB_PORT')}/{os.getenv('MARIADB_DBNAME')}")

# 앱 시작 전에 DB 자격 증명 설정
setup_db_credentials()

# --- 환경 변수 ---
JWT_SECRET = os.getenv("JWT_SECRET", "your-jwt-secret-here")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24 * 7  # 7일
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
KIS_GATEWAY_URL = os.getenv("KIS_GATEWAY_URL", "http://kis-gateway:8080")

# --- Pydantic 모델 ---
class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict

class PortfolioSummary(BaseModel):
    total_value: float
    total_invested: float
    total_profit: float
    profit_rate: float
    cash_balance: float
    positions_count: int

class Position(BaseModel):
    stock_code: str
    stock_name: str
    quantity: int
    avg_price: float
    current_price: float
    profit: float
    profit_rate: float
    weight: float

class WatchlistItem(BaseModel):
    stock_code: str
    stock_name: str
    llm_score: Optional[float]
    per: Optional[float]
    pbr: Optional[float]
    is_tradable: Optional[bool]

class TradeRecord(BaseModel):
    id: int
    stock_code: str
    stock_name: Optional[str]
    trade_type: str
    quantity: int
    price: float
    total_amount: float
    traded_at: datetime
    profit: Optional[float]

class SystemStatus(BaseModel):
    service_name: str
    status: str
    last_run: Optional[datetime]
    next_run: Optional[datetime]
    message: Optional[str]

class ScoutPipelineStatus(BaseModel):
    phase: int
    phase_name: str
    status: str
    progress: float
    current_stock: Optional[str]
    results: Optional[dict]

# --- Redis 연결 ---
redis_client = None

def get_redis():
    global redis_client
    if redis_client is None:
        try:
            redis_client = redis.from_url(REDIS_URL, decode_responses=True)
            redis_client.ping()
            logger.info("✅ Redis 연결 성공")
        except Exception as e:
            logger.warning(f"⚠️ Redis 연결 실패: {e}")
            redis_client = None
    return redis_client

# --- JWT 인증 ---
security = HTTPBearer()

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(hours=JWT_EXPIRATION_HOURS))
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

# --- WebSocket 연결 관리 ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket 연결: {len(self.active_connections)}개 활성")
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"WebSocket 해제: {len(self.active_connections)}개 활성")
    
    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass

manager = ConnectionManager()

# --- Lifespan 이벤트 ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Dashboard Backend 시작")
    # DB 엔진 초기화
    try:
        ensure_engine_initialized()
        
        # [Enhancement] Fresh Install Support: 데이터베이스 스키마 자동 생성
        # 테이블이 없을 경우에만 생성하므로 안전함 (CheckIfExists)
        from shared.db.models import Base
        Base.metadata.create_all(get_engine())
        
        logger.info("✅ DB 엔진 초기화 및 스키마 검증(Auto-Create) 완료")
    except Exception as e:
        logger.error(f"❌ DB 엔진 초기화 실패: {e}")
    # Redis 연결
    get_redis()
    yield
    logger.info("👋 Dashboard Backend 종료")

from shared.version import PROJECT_NAME, VERSION, get_service_title

# --- FastAPI 앱 ---
app = FastAPI(
    title=get_service_title("Dashboard API"),
    description="AI 자율 트레이딩 시스템 대시보드 API",
    version=VERSION,
    lifespan=lifespan,
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
from routers import factors
app.include_router(factors.router) # Factor settings router

# =============================================================================
# 인증 API
# =============================================================================

@app.post("/api/auth/login", response_model=TokenResponse)
async def login(request: LoginRequest):
    """로그인 및 JWT 토큰 발급"""
    # 환경 변수 또는 secrets.json에서 비밀번호 확인
    secrets = load_secrets()
    valid_password = secrets.get("dashboard-password", os.getenv("DASHBOARD_PASSWORD", "!fpdlwl94A#"))
    valid_username = secrets.get("dashboard-username", os.getenv("DASHBOARD_USERNAME", "admin"))
    
    if request.username != valid_username or request.password != valid_password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    access_token = create_access_token(
        data={"sub": request.username, "role": "admin"}
    )
    
    return TokenResponse(
        access_token=access_token,
        expires_in=JWT_EXPIRATION_HOURS * 3600,
        user={"username": request.username, "role": "admin"}
    )

@app.get("/api/auth/me")
async def get_current_user(payload: dict = Depends(verify_token)):
    """현재 로그인한 사용자 정보"""
    return {
        "username": payload.get("sub"),
        "role": payload.get("role"),
        "exp": payload.get("exp"),
    }

@app.post("/api/auth/refresh", response_model=TokenResponse)
async def refresh_token(payload: dict = Depends(verify_token)):
    """토큰 갱신"""
    access_token = create_access_token(
        data={"sub": payload.get("sub"), "role": payload.get("role")}
    )
    return TokenResponse(
        access_token=access_token,
        expires_in=JWT_EXPIRATION_HOURS * 3600,
        user={"username": payload.get("sub"), "role": payload.get("role")}
    )

# =============================================================================
# 포트폴리오 API
# =============================================================================

@app.get("/api/portfolio/summary", response_model=PortfolioSummary)
async def get_portfolio_summary_api(payload: dict = Depends(verify_token)):
    """포트폴리오 요약 정보"""
    try:
        with get_session() as session:
            summary = get_portfolio_summary(session)
            return PortfolioSummary(
                total_value=summary.get("total_value", 0),
                total_invested=summary.get("total_invested", 0),
                total_profit=summary.get("total_profit", 0),
                profit_rate=summary.get("profit_rate", 0),
                cash_balance=summary.get("cash_balance", 0),
                positions_count=summary.get("positions_count", 0),
            )
    except Exception as e:
        logger.error(f"포트폴리오 요약 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/portfolio/positions", response_model=list[Position])
async def get_positions_api(payload: dict = Depends(verify_token)):
    """보유 종목 목록 (실시간 가격 포함)"""
    try:
        with get_session() as session:
            positions = get_portfolio_with_current_prices(session)
            return [
                Position(
                    stock_code=p["stock_code"],
                    stock_name=p["stock_name"],
                    quantity=p["quantity"],
                    avg_price=p["avg_price"],
                    current_price=p.get("current_price", p["avg_price"]),
                    profit=p.get("profit", 0),
                    profit_rate=p.get("profit_rate", 0),
                    weight=p.get("weight", 0),
                )
                for p in positions
            ]
    except Exception as e:
        logger.error(f"보유 종목 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =============================================================================
# Watchlist API
# =============================================================================

@app.get("/api/watchlist", response_model=list[WatchlistItem])
async def get_watchlist_api(
    limit: int = Query(50, ge=1, le=200),
    payload: dict = Depends(verify_token)
):
    """관심 종목 목록"""
    try:
        with get_session() as session:
            items = get_watchlist_all(session, limit=limit)
            return [
                WatchlistItem(
                    stock_code=item.stock_code,
                    stock_name=item.stock_name,
                    llm_score=item.llm_score,
                    per=item.per,
                    pbr=item.pbr,
                    is_tradable=item.is_tradable,
                )
                for item in items
            ]
    except Exception as e:
        logger.error(f"Watchlist 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =============================================================================
# 거래 내역 API
# =============================================================================

@app.get("/api/trades", response_model=list[TradeRecord])
async def get_trades_api(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    payload: dict = Depends(verify_token)
):
    """거래 내역"""
    try:
        with get_session() as session:
            trades = get_recent_trades(session, limit=limit, offset=offset)
            return [
                TradeRecord(
                    id=t.log_id,
                    stock_code=t.stock_code,
                    stock_name=None,  # TradeLog에는 stock_name이 없음
                    trade_type=t.trade_type,
                    quantity=t.quantity or 0,
                    price=t.price or 0,
                    total_amount=(t.quantity or 0) * (t.price or 0),
                    traded_at=t.trade_timestamp,
                    profit=None,
                )
                for t in trades
            ]
    except Exception as e:
        logger.error(f"거래 내역 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =============================================================================
# 시스템 상태 API
# =============================================================================

@app.get("/api/system/status", response_model=list[SystemStatus])
async def get_system_status_api(payload: dict = Depends(verify_token)):
    """시스템 서비스 상태 (Docker 컨테이너 기반)"""
    try:
        with get_session() as session:
            jobs = get_scheduler_jobs(session)
            return [
                SystemStatus(
                    service_name=job.get("job_id", "unknown"),
                    status="active" if job.get("enabled") else "inactive",
                    last_run=job.get("last_run_at"),
                    next_run=job.get("next_due_at"),
                    message=f"Queue: {job.get('queue', 'N/A')}",
                )
                for job in jobs
            ]
    except Exception as e:
        logger.error(f"시스템 상태 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/system/docker")
async def get_docker_status_api(payload: dict = Depends(verify_token)):
    """Docker 컨테이너 상태 (WSL2 환경) - Docker Socket API 사용"""
    try:
        # httpx 동기 클라이언트로 Unix 소켓 통신
        transport = httpx.HTTPTransport(uds="/var/run/docker.sock")
        with httpx.Client(transport=transport, base_url="http://localhost") as client:
            response = client.get("/containers/json")
            containers_raw = response.json()
            
            containers = []
            for c in containers_raw:
                containers.append({
                    "ID": c.get("Id", "")[:12],
                    "Names": c.get("Names", [""])[0].lstrip("/"),
                    "Image": c.get("Image", ""),
                    "Status": c.get("Status", ""),
                    "State": c.get("State", ""),
                })
            return {"containers": containers, "count": len(containers)}
        
    except Exception as e:
        logger.error(f"Docker 상태 조회 실패: {e}")
        return {"containers": [], "count": 0, "error": str(e)}

@app.get("/api/system/rabbitmq")
async def get_rabbitmq_status_api(payload: dict = Depends(verify_token)):
    """RabbitMQ 큐 상태 - Management API 사용"""
    try:
        # RabbitMQ Management API (기본 포트 15672)
        rabbitmq_url = os.getenv("RABBITMQ_MANAGEMENT_URL", "http://127.0.0.1:15672")
        rabbitmq_user = os.getenv("RABBITMQ_USER", "guest")
        rabbitmq_pass = os.getenv("RABBITMQ_PASS", "guest")
        
        import base64
        auth = base64.b64encode(f"{rabbitmq_user}:{rabbitmq_pass}".encode()).decode()
        
        async with httpx.AsyncClient() as client:
            # 큐 목록 조회
            response = await client.get(
                f"{rabbitmq_url}/api/queues",
                headers={"Authorization": f"Basic {auth}"},
                timeout=10.0
            )
            
            if response.status_code == 200:
                queues_raw = response.json()
                queues = []
                for q in queues_raw:
                    queues.append({
                        "name": q.get("name", ""),
                        "messages": q.get("messages", 0),
                        "messages_ready": q.get("messages_ready", 0),
                        "messages_unacknowledged": q.get("messages_unacknowledged", 0),
                        "consumers": q.get("consumers", 0),
                        "state": q.get("state", "unknown")
                    })
                return {"queues": queues, "count": len(queues)}
            else:
                return {"queues": [], "error": f"HTTP {response.status_code}"}
                
    except Exception as e:
        logger.error(f"RabbitMQ 상태 조회 실패: {e}")
        return {"queues": [], "error": str(e)}

@app.get("/api/system/scheduler")
async def get_scheduler_jobs_api(payload: dict = Depends(verify_token)):
    """Scheduler Jobs 상태 - DB에서 조회"""
    try:
        from sqlalchemy import text
        with get_session() as session:
            # scheduler.jobs 테이블에서 작업 목록 조회
            result = session.execute(text("""
                SELECT 
                    job_id,
                    queue,
                    cron_expr,
                    interval_seconds,
                    enabled,
                    last_run_at,
                    last_status,
                    description,
                    created_at
                FROM jobs
                ORDER BY job_id
            """))
            
            jobs = []
            for row in result:
                # interval_seconds를 사람이 읽기 쉬운 형태로 변환
                interval = row.interval_seconds or 0
                if interval >= 3600:
                    interval_str = f"{interval // 3600}시간"
                elif interval >= 60:
                    interval_str = f"{interval // 60}분"
                elif interval > 0:
                    interval_str = f"{interval}초"
                else:
                    interval_str = row.cron_expr or "N/A"
                
                jobs.append({
                    "name": row.job_id,
                    "queue": row.queue,
                    "interval": interval_str,
                    "interval_seconds": interval,
                    "cron": row.cron_expr,
                    "is_active": row.enabled,
                    "last_run": row.last_run_at.isoformat() if row.last_run_at else None,
                    "last_status": row.last_status or "unknown",
                    "description": row.description,
                    "created_at": row.created_at.isoformat() if row.created_at else None
                })
            
            return {"jobs": jobs, "count": len(jobs)}
            
    except Exception as e:
        logger.error(f"Scheduler Jobs 조회 실패: {e}")
        return {"jobs": [], "error": str(e)}

@app.get("/api/system/logs/{container_name}")
async def get_container_logs_api(
    container_name: str,
    limit: int = 100,
    since: str = "1h",
    payload: dict = Depends(verify_token)
):
    """Loki에서 컨테이너 로그 조회"""
    try:
        loki_url = os.getenv("LOKI_URL", "http://127.0.0.1:3100")
        
        # Loki 쿼리 - container 라벨로 필터링 (Promtail 설정에 따라 다름)
        query = f'{{container="{container_name}"}}'
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{loki_url}/loki/api/v1/query_range",
                params={
                    "query": query,
                    "limit": limit,
                    "since": since,
                },
                timeout=30.0
            )
            
            if response.status_code == 200:
                data = response.json()
                logs = []
                
                # Loki 응답 파싱
                results = data.get("data", {}).get("result", [])
                for stream in results:
                    for value in stream.get("values", []):
                        timestamp, log_line = value
                        # 타임스탬프를 사람이 읽기 쉬운 형태로 변환
                        from datetime import datetime
                        ts = datetime.fromtimestamp(int(timestamp) / 1e9)
                        logs.append({
                            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
                            "message": log_line
                        })
                
                # 시간순 정렬 (최신이 아래로)
                logs.sort(key=lambda x: x["timestamp"])
                
                return {
                    "container": container_name,
                    "logs": logs[-limit:],  # 최신 limit개만
                    "count": len(logs)
                }
            else:
                return {
                    "container": container_name,
                    "logs": [],
                    "error": f"Loki HTTP {response.status_code}"
                }
                
    except Exception as e:
        logger.error(f"로그 조회 실패 ({container_name}): {e}")
        return {
            "container": container_name,
            "logs": [],
            "error": str(e)
        }

# =============================================================================
# Scout Pipeline API
# =============================================================================

@app.get("/api/scout/status")
async def get_scout_status_api(payload: dict = Depends(verify_token)):
    """Scout Pipeline 현재 상태"""
    r = get_redis()
    if not r:
        return {"status": "unknown", "message": "Redis 연결 실패"}
    
    try:
        status = r.hgetall("scout:pipeline:status")
        return {
            "phase": int(status.get("phase", 0)),
            "phase_name": status.get("phase_name", "대기"),
            "status": status.get("status", "idle"),
            "progress": float(status.get("progress", 0)),
            "current_stock": status.get("current_stock"),
            "total_candidates": int(status.get("total_candidates", 0)),
            "passed_phase1": int(status.get("passed_phase1", 0)),
            "passed_phase2": int(status.get("passed_phase2", 0)),
            "final_selected": int(status.get("final_selected", 0)),
            "last_updated": status.get("last_updated"),
        }
    except Exception as e:
        logger.error(f"Scout 상태 조회 실패: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/scout/results")
async def get_scout_results_api(payload: dict = Depends(verify_token)):
    """Scout Pipeline 최근 결과"""
    r = get_redis()
    if not r:
        return {"results": [], "message": "Redis 연결 실패"}
    
    try:
        results_json = r.get("scout:pipeline:results")
        if results_json:
            return {"results": json.loads(results_json)}
        return {"results": []}
    except Exception as e:
        logger.error(f"Scout 결과 조회 실패: {e}")
        return {"results": [], "error": str(e)}

# =============================================================================
# 뉴스 & 감성 API
# =============================================================================

@app.get("/api/news/sentiment")
async def get_news_sentiment_api(
    stock_code: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    payload: dict = Depends(verify_token)
):
    """뉴스 감성 점수 (shared/database.py의 sentiment:{code} 키 사용)"""
    r = get_redis()
    if not r:
        return {"items": [], "message": "Redis 연결 실패"}
    
    try:
        if stock_code:
            # 특정 종목의 감성 점수
            data = r.get(f"sentiment:{stock_code}")
            if data:
                import json
                parsed = json.loads(data)
                return {
                    "stock_code": stock_code,
                    "stock_name": parsed.get("stock_name"),
                    "sentiment_score": parsed.get("score"),
                    "reason": parsed.get("reason"),
                    "source_url": parsed.get("source_url"),
                    "updated_at": parsed.get("updated_at"),
                }
            return {
                "stock_code": stock_code,
                "stock_name": None,
                "sentiment_score": None,
                "reason": "데이터 없음",
                "source_url": None,
            }
        else:
            # 전체 감성 점수 (상위 N개) - sentiment:* 키 조회
            keys = r.keys("sentiment:*")
            items = []
            import json
            
            # [Fix] 종목명 매핑을 위해 WatchList 조회 (Redis에 없을 경우 대비)
            stock_names_map = {}
            try:
                with get_session() as session:
                    # 간단히 모든 최근 종목 이름을 가져옴 (혹은 필요한 것만 in 절로 최적화 가능하지만 여기서 간단히)
                    # 성능 이슈가 있다면 keys에서 code 추출 후 IN 쿼리 사용 권장
                    w_list = session.query(WatchList.stock_code, WatchList.stock_name).all()
                    for w in w_list:
                        stock_names_map[w.stock_code] = w.stock_name
            except Exception as e:
                logger.warning(f"종목명 매핑 조회 실패: {e}")

            for key in keys[:limit*2]: # Limit보다 넉넉히 조회 후 정렬
                code = key.split(":")[-1] if isinstance(key, str) else key.decode().split(":")[-1]
                data = r.get(key)
                if data:
                    parsed = json.loads(data) if isinstance(data, str) else json.loads(data.decode())
                    
                    # Redis에 저장된 이름 사용, 없으면 DB 매핑 사용, 없으면 코드 사용
                    s_name = parsed.get("stock_name") or stock_names_map.get(code) or code
                    
                    items.append({
                        "stock_code": code,
                        "stock_name": s_name,
                        "sentiment_score": parsed.get("score"),
                        "reason": parsed.get("reason"),
                        "source_url": parsed.get("source_url"),
                        "updated_at": parsed.get("updated_at")
                    })
            items.sort(key=lambda x: x["sentiment_score"] or 0, reverse=True)
            return {"items": items[:limit]}
    except Exception as e:
        logger.error(f"뉴스 감성 조회 실패: {e}")
        return {"items": [], "error": str(e)}

# =============================================================================
# WebSocket 실시간 업데이트
# =============================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """실시간 업데이트 WebSocket"""
    await manager.connect(websocket)
    try:
        while True:
            # 클라이언트로부터 메시지 수신 (ping/pong)
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# =============================================================================
# Daily Briefing API (NEW)
# =============================================================================

@app.get("/api/briefing/latest")
async def get_daily_briefing_api(payload: dict = Depends(verify_token)):
    """최신 Daily Briefing 조회"""
    r = get_redis()
    
    try:
        # Redis에서 가장 최근 briefing 조회
        briefing_json = r.get("daily:briefing:latest") if r else None
        
        if briefing_json:
            briefing = json.loads(briefing_json)
            return {
                "date": briefing.get("date"),
                "content": briefing.get("content"),
                "market_summary": briefing.get("market_summary"),
                "trades_summary": briefing.get("trades_summary"),
                "generated_at": briefing.get("generated_at"),
            }
        
        # Redis에 없으면 DB에서 조회 시도
        from sqlalchemy import text
        with get_session() as session:
            result = session.execute(text("""
                SELECT report_date, content, created_at
                FROM DAILY_BRIEFING_LOG
                ORDER BY report_date DESC
                LIMIT 1
            """))
            row = result.fetchone()
            if row:
                return {
                    "date": row.report_date.isoformat() if row.report_date else None,
                    "content": row.content,
                    "market_summary": None,
                    "trades_summary": None,
                    "generated_at": row.created_at.isoformat() if row.created_at else None,
                }
        
        return {"content": "아직 생성된 브리핑이 없습니다.", "date": None}
        
    except Exception as e:
        logger.error(f"Daily Briefing 조회 실패: {e}")
        return {"content": f"조회 실패: {e}", "date": None, "error": str(e)}

# =============================================================================
# Market Regime API (NEW)
# =============================================================================

@app.get("/api/market/regime")
async def get_market_regime_api(payload: dict = Depends(verify_token)):
    """Market Regime (Bull/Bear/Sideways) API"""
    try:
        from shared.market_regime import MarketRegimeManager
        
        # Instantiate Manager (it uses valid_sectors from scout_universe inside, or we can mock/ignore if just reading DB/Redis)
        # For simple reading, let's just query Redis or DB as Manager might be heavy or require dependencies.
        # Actually, MarketRegimeManager.analyze_market_regime updates DB. We just want to READ.
        # Let's check shared.db.models.MarketRegime
        
        with get_session() as session:
            from shared.db.models import MarketRegime
            # Get latest
            latest = session.query(MarketRegime).order_by(MarketRegime.date.desc()).first()
            if latest:
                return {
                    "date": latest.date.isoformat(),
                    "regime": latest.regime,
                    "confidence": latest.confidence,
                    "kospi_200_return": latest.kospi_200_return_3m,
                    "adv_dec_ratio": latest.ad_ratio,
                    "description": latest.description
                }
            else:
                return {"regime": "UNKNOWN", "message": "No data"}
                
    except Exception as e:
        logger.error(f"Market Regime 조회 실패: {e}")
        return {"error": str(e)}


# =============================================================================
# Analyst Performance API (NEW)
# =============================================================================

@app.get("/api/analyst/performance")
async def get_analyst_performance_api(payload: dict = Depends(verify_token)):
    """AI Analyst 성과 분석 데이터"""
    try:
        from shared.analysis.ai_performance import analyze_performance
        import pandas as pd
        import numpy as np
        
        with get_session() as session:
            df = analyze_performance(session)
            
            if df is None or df.empty:
                return {
                    "overall": None,
                    "by_regime": [],
                    "by_score": [],
                    "recent_decisions": []
                }
            
            # Helper to safely serialize numpy/pandas types to Python native types
            def safe_serialize(obj):
                if pd.isna(obj):
                    return None
                if isinstance(obj, (np.integer, int)):
                    return int(obj)
                if isinstance(obj, (np.floating, float)):
                    return float(obj)
                if isinstance(obj, (np.bool_, bool)):
                    return bool(obj)
                return obj

            # 1. Overall stats (T+5)
            valid_5d = df.dropna(subset=['return_5d'])
            overall = {}
            if not valid_5d.empty:
                overall = {
                    "win_rate_5d": safe_serialize((valid_5d['return_5d'] > 0).mean() * 100),
                    "avg_return_5d": safe_serialize(valid_5d['return_5d'].mean() * 100),
                    "total_decisions": len(valid_5d)
                }
            else:
                overall = {
                    "win_rate_5d": 0.0,
                    "avg_return_5d": 0.0,
                    "total_decisions": 0
                }
            
            # 2. By Regime
            by_regime = []
            if 'market_regime' in df.columns:
                regime_groups = df.groupby('market_regime')['return_5d']
                for regime, group in regime_groups:
                    valid_group = group.dropna()
                    if len(valid_group) > 0:
                        by_regime.append({
                            "regime": regime,
                            "count": int(len(valid_group)),
                            "win_rate": safe_serialize((valid_group > 0).mean() * 100),
                            "avg_return": safe_serialize(valid_group.mean() * 100)
                        })
            
            # 3. By Hunter Score
            by_score = []
            bins = [0, 40, 60, 80, 100]
            labels = ['F (0-40)', 'C/D (40-60)', 'B/A (60-80)', 'S (80-100)']
            # Avoid SettingWithCopyWarning by working on copy or direct assignment
            df_score = df.copy()
            df_score['score_bucket'] = pd.cut(df_score['hunter_score'], bins=bins, labels=labels)
            
            score_groups = df_score.groupby('score_bucket', observed=False)['return_5d']
            for bucket, group in score_groups:
                valid_group = group.dropna()
                if len(valid_group) > 0: # Show only if data exists
                    by_score.append({
                        "bucket": str(bucket),
                        "count": int(len(valid_group)),
                        "win_rate": safe_serialize((valid_group > 0).mean() * 100),
                        "avg_return": safe_serialize(valid_group.mean() * 100)
                    })
            
            # 4. Recent Decisions (limit 20)
            recent = []
            # Sort by timestamp desc
            for _, row in df.sort_values(by='timestamp', ascending=False).head(20).iterrows():
                recent.append({
                    "timestamp": row['timestamp'].isoformat() if row['timestamp'] else None,
                    "stock_name": row['stock_name'],
                    "stock_code": row['stock_code'],
                    "decision": row['decision'],
                    "hunter_score": safe_serialize(row['hunter_score']),
                    "market_regime": row['market_regime'],
                    "return_5d": safe_serialize(row['return_5d'] * 100) if pd.notnull(row['return_5d']) else None
                })

            return {
                "overall": overall,
                "by_regime": by_regime,
                "by_score": by_score,
                "recent_decisions": recent
            }
            
    except Exception as e:
        logger.error(f"Analyst Performance 조회 실패: {e}")
        # traceback for debugging
        import traceback
        logger.error(traceback.format_exc())
        return {"error": str(e)}

    """현재 시장 국면 조회"""
    r = get_redis()
    
    try:
        if r:
            # Redis에서 시장 국면 조회
            regime = r.get("market:regime")
            regime_data = r.get("market:regime:data")
            
            if regime_data:
                data = json.loads(regime_data)
                return {
                    "regime": data.get("regime", regime or "UNKNOWN"),
                    "confidence": data.get("confidence", 0),
                    "kospi_change": data.get("kospi_change"),
                    "kosdaq_change": data.get("kosdaq_change"),
                    "volatility": data.get("volatility"),
                    "updated_at": data.get("updated_at"),
                }
            elif regime:
                return {"regime": regime, "confidence": None, "updated_at": None}
        
        return {"regime": "UNKNOWN", "confidence": None, "message": "데이터 없음"}
        
    except Exception as e:
        logger.error(f"Market Regime 조회 실패: {e}")
        return {"regime": "ERROR", "error": str(e)}

# =============================================================================
# LLM Stats API (NEW)
# =============================================================================

@app.get("/api/llm/stats")
async def get_llm_stats_api(payload: dict = Depends(verify_token)):
    """LLM 서비스별 사용 통계 (v1.2 - 새로운 키 구조 지원)"""
    r = get_redis()
    
    try:
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        
        # 서비스별 통계 조회 (v1.2 새 구조)
        stats = {
            "news_analysis": {"calls": 0, "tokens": 0},
            "scout": {"calls": 0, "tokens": 0},
            "briefing": {"calls": 0, "tokens": 0},
            # Legacy 호환성 유지
            "fast": {"calls": 0, "tokens": 0, "cost": 0},
            "reasoning": {"calls": 0, "tokens": 0, "cost": 0},
            "thinking": {"calls": 0, "tokens": 0, "cost": 0},
            "total_calls": 0,
            "total_cost": 0,
            "period": "today",
        }
        
        if r:
            # 새로운 서비스별 키 구조 조회
            for service in ["news_analysis", "scout", "briefing"]:
                key = f"llm:stats:{today}:{service}"
                data = r.hgetall(key)
                if data:
                    calls = int(data.get("calls", 0))
                    tokens_in = int(data.get("tokens_in", 0))
                    tokens_out = int(data.get("tokens_out", 0))
                    stats[service] = {
                        "calls": calls,
                        "tokens": tokens_in + tokens_out,
                    }
                    stats["total_calls"] += calls
            
            # [Legacy] 기존 키 구조도 지원 (하위 호환)
            for tier in ["fast", "reasoning", "thinking"]:
                calls = r.get(f"llm:stats:{tier}:calls") or 0
                tokens = r.get(f"llm:stats:{tier}:tokens") or 0
                cost = r.get(f"llm:stats:{tier}:cost") or 0
                stats[tier] = {
                    "calls": int(calls),
                    "tokens": int(tokens),
                    "cost": float(cost),
                }
        
        # DB에서 오늘의 LLM Decision Ledger 통계 조회
        try:
            from sqlalchemy import text
            with get_session() as session:
                result = session.execute(text("""
                    SELECT 
                        COUNT(*) as total_decisions,
                        SUM(CASE WHEN final_decision = 'BUY' THEN 1 ELSE 0 END) as buy_decisions,
                        SUM(CASE WHEN final_decision = 'REJECT' THEN 1 ELSE 0 END) as reject_decisions
                    FROM LLM_DECISION_LEDGER
                    WHERE DATE(created_at) = CURDATE()
                """))
                row = result.fetchone()
                if row:
                    stats["decisions_today"] = {
                        "total": row.total_decisions or 0,
                        "buy": row.buy_decisions or 0,
                        "reject": row.reject_decisions or 0,
                    }
        except Exception as db_e:
            logger.warning(f"LLM Decision Ledger 조회 실패: {db_e}")
            stats["decisions_today"] = None
        
        return stats
        
    except Exception as e:
        logger.error(f"LLM Stats 조회 실패: {e}")
        return {"error": str(e)}

# =============================================================================
# 3 Sages Daily Review API (NEW) - Daily Council Feature
# =============================================================================

class SageReview(BaseModel):
    sage_name: str  # Jennie, Minji, Junho
    role: str
    perspective: str
    summary: str
    recommendations: list[str]
    confidence: float

@app.get("/api/council/daily-review")
async def get_three_sages_review_api(payload: dict = Depends(verify_token)):
    """3현자 데일리 리뷰 - Jennie, Minji, Junho의 시스템 검토"""
    r = get_redis()
    
    try:
        # Redis에서 최신 3현자 리뷰 조회
        if r:
            review_json = r.get("council:daily:review")
            if review_json:
                review = json.loads(review_json)
                return review
        
        # DB에서 조회 시도
        try:
            from sqlalchemy import text
            with get_session() as session:
                result = session.execute(text("""
                    SELECT review_date, jennie_review, minji_review, junho_review, 
                           consensus, action_items, created_at
                    FROM DAILY_COUNCIL_LOG
                    ORDER BY review_date DESC
                    LIMIT 1
                """))
                row = result.fetchone()
                if row:
                    return {
                        "date": row.review_date.isoformat() if row.review_date else None,
                        "sages": [
                            {
                                "name": "Jennie",
                                "role": "수석 심판 (Chief Judge)",
                                "icon": "👑",
                                "review": row.jennie_review or "리뷰 없음",
                            },
                            {
                                "name": "Minji", 
                                "role": "리스크 분석가 (Risk Analyst)",
                                "icon": "🔍",
                                "review": row.minji_review or "리뷰 없음",
                            },
                            {
                                "name": "Junho",
                                "role": "전략가 (Strategist)",
                                "icon": "📈",
                                "review": row.junho_review or "리뷰 없음",
                            },
                        ],
                        "consensus": row.consensus,
                        "action_items": json.loads(row.action_items) if row.action_items else [],
                        "generated_at": row.created_at.isoformat() if row.created_at else None,
                    }
        except Exception as db_e:
            logger.warning(f"Daily Council Log 조회 실패: {db_e}")
        
        # 데이터가 없을 경우 기본 응답
        return {
            "date": None,
            "sages": [
                {
                    "name": "Jennie",
                    "role": "수석 심판 (Chief Judge)",
                    "icon": "👑",
                    "review": "오늘의 리뷰가 아직 생성되지 않았습니다.",
                },
                {
                    "name": "Minji",
                    "role": "리스크 분석가 (Risk Analyst)", 
                    "icon": "🔍",
                    "review": "시스템 분석을 기다리고 있습니다.",
                },
                {
                    "name": "Junho",
                    "role": "전략가 (Strategist)",
                    "icon": "📈",
                    "review": "전략 검토를 준비 중입니다.",
                },
            ],
            "consensus": None,
            "action_items": [],
            "message": "Daily Council 리뷰가 아직 생성되지 않았습니다. 매일 시장 마감 후 자동으로 생성됩니다.",
        }
        
    except Exception as e:
        logger.error(f"3현자 리뷰 조회 실패: {e}")
        return {"error": str(e), "sages": []}

# =============================================================================
# 헬스 체크
# =============================================================================

@app.get("/health")
async def health_check():
    """헬스 체크"""
    return {
        "status": "healthy",
        "service": "dashboard-backend",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

@app.get("/")
async def root():
    """루트 엔드포인트"""
    return {
        "service": get_service_title("Dashboard API"),
        "version": "1.0.0",
        "docs": "/docs",
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8090)

