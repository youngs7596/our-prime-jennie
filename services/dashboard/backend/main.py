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
from shared.db.models import WatchList, TradeLog

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

from auth import create_access_token, verify_token, JWT_SECRET, JWT_ALGORITHM, LoginRequest, TokenResponse

# --- 환경 변수 ---
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
KIS_GATEWAY_URL = os.getenv("KIS_GATEWAY_URL", "http://kis-gateway:8080")
JWT_EXPIRATION_HOURS = 24

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

# ... (Previous auth code removed)

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

# --- Redis Subscriber ---
async def redis_subscriber_task(redis_client):
    """Redis Pub/Sub 구독 및 WebSocket 브로드캐스트"""
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("dashboard:stream")
    logger.info("📡 Redis Pub/Sub 구독 시작: dashboard:stream")
    
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    data = json.loads(message["data"])
                    # logger.info(f"   (WS) Relay: {data.get('type')}")
                    await manager.broadcast(data)
                except Exception as e:
                    logger.error(f"메시지 처리 오류: {e}")
    except asyncio.CancelledError:
        logger.info("Redis Subscriber 작업 취소됨")
    except Exception as e:
        logger.error(f"Redis Subscriber 오류: {e}")
    finally:
        await pubsub.close()
        logger.info("Redis Pub/Sub 구독 종료")


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
    r = get_redis()
    
    # [Start] Redis Subscriber Background Task
    subscriber_task = None
    if r:
        try:
            import redis.asyncio as aioredis
            # Force 127.0.0.1 to avoid localhost ambiguity in some environments
            redis_host = os.getenv("REDIS_HOST", "127.0.0.1")
            redis_port = os.getenv("REDIS_PORT", "6379")
            redis_url = f"redis://{redis_host}:{redis_port}/0"
            
            async_redis = aioredis.from_url(redis_url, decode_responses=True)
            subscriber_task = asyncio.create_task(redis_subscriber_task(async_redis))
            logger.info(f"✅ Async Redis Subscriber 시작됨 ({redis_url})")
        except ImportError:
            logger.warning("⚠️ redis.asyncio 모듈 없음 - 실시간 브로드캐스트 비활성화")
        except Exception as e:
            logger.error(f"❌ Async Redis 초기화 실패: {e}")

    yield
    
    # [Cleanup]
    if subscriber_task:
        subscriber_task.cancel()
        try:
            await subscriber_task
        except asyncio.CancelledError:
            pass
            
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
# 라우터 등록
from routers import factors, llm, configs, scheduler, system, performance, portfolio, market, airflow, logs, logic
app.include_router(factors.router) # Factor settings router
app.include_router(llm.router) # LLM settings & stats router
app.include_router(configs.router) # Config registry/API router
app.include_router(scheduler.router) # Scheduler proxy router
app.include_router(system.router) # System status router (Cached)
app.include_router(performance.router) # Performance analytics router
app.include_router(portfolio.router) # Portfolio router
app.include_router(market.router) # Market router
app.include_router(airflow.router) # Airflow router
app.include_router(logs.router) # Logs router
app.include_router(logic.router) # Logic Observability router

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

# Portfolio API moved to routers/portfolio.py

# =============================================================================
# Watchlist API
# =============================================================================

@app.get("/api/watchlist", response_model=list[WatchlistItem])
async def get_watchlist_api(
    limit: int = Query(50, ge=1, le=200),
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

# System Status API moved to routers/system.py

# =============================================================================
# Scout Pipeline API
# =============================================================================

@app.get("/api/scout/status")
async def get_scout_status_api():
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
async def get_scout_results_api():
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
            # [최적화] KEYS → SCAN 패턴 변경 (Redis 블로킹 방지)
            import json

            # scan_iter는 커서 기반으로 비블로킹 조회
            target_keys = []
            max_keys = limit * 2  # 필요한 만큼만 수집
            for key in r.scan_iter(match="sentiment:*", count=100):
                target_keys.append(key)
                if len(target_keys) >= max_keys:
                    break

            if not target_keys:
                return {"items": []}

            # 키에서 종목 코드 추출
            stock_codes_needed = set()
            key_code_map = {}  # key -> code 매핑
            for key in target_keys:
                code = key.split(":")[-1] if isinstance(key, str) else key.decode().split(":")[-1]
                stock_codes_needed.add(code)
                key_code_map[key if isinstance(key, str) else key.decode()] = code

            # [최적화] 필요한 종목만 IN 쿼리로 조회 (N+1 문제 해결)
            stock_names_map = {}
            if stock_codes_needed:
                try:
                    from sqlalchemy import select
                    with get_session() as session:
                        stmt = select(WatchList.stock_code, WatchList.stock_name).where(
                            WatchList.stock_code.in_(list(stock_codes_needed))
                        )
                        w_list = session.execute(stmt).all()
                        for w in w_list:
                            stock_names_map[w[0]] = w[1]
                except Exception as e:
                    logger.warning(f"종목명 매핑 조회 실패: {e}")

            # [최적화] MGET으로 한 번에 조회 (N+1 → 1 요청)
            values = r.mget(target_keys)
            items = []
            for key, data in zip(target_keys, values):
                if not data:
                    continue
                key_str = key if isinstance(key, str) else key.decode()
                code = key_code_map.get(key_str, key_str.split(":")[-1])
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
async def get_daily_briefing_api():
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

# Market Regime API moved to routers/market.py


# =============================================================================
# Analyst Performance API (NEW)
# =============================================================================

@app.get("/api/analyst/performance")
async def get_analyst_performance_api(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    lookback_days: int = Query(30, ge=7, le=90),
):
    """AI Analyst 성과 분석 데이터 (페이징 지원)"""
    try:
        from shared.analysis.ai_performance import analyze_performance
        import pandas as pd
        import numpy as np
        
        with get_session() as session:
            df = analyze_performance(session, lookback_days=lookback_days)
            
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
            
            # 4. Recent Decisions (페이징 지원) - 다기간 수익률 포함 (퀀트 트레이딩용)
            recent = []
            total_decisions_count = len(df)
            # Sort by timestamp desc and apply pagination
            sorted_df = df.sort_values(by='timestamp', ascending=False)
            paginated_df = sorted_df.iloc[offset:offset + limit]
            for _, row in paginated_df.iterrows():
                recent.append({
                    "timestamp": row['timestamp'].isoformat() if row['timestamp'] else None,
                    "stock_name": row['stock_name'],
                    "stock_code": row['stock_code'],
                    "decision": row['decision'],
                    "hunter_score": safe_serialize(row['hunter_score']),
                    "market_regime": row['market_regime'],
                    "return_1d": safe_serialize(row['return_1d'] * 100) if pd.notnull(row.get('return_1d')) else None,
                    "return_5d": safe_serialize(row['return_5d'] * 100) if pd.notnull(row.get('return_5d')) else None,
                    "return_20d": safe_serialize(row['return_20d'] * 100) if pd.notnull(row.get('return_20d')) else None,
                    "tags": row.get('tags', []),
                    "score_history": row.get('score_history', [])
                })

            return {
                "overall": overall,
                "by_regime": by_regime,
                "by_score": by_score,
                "recent_decisions": recent,
                "total_count": total_decisions_count,
                "limit": limit,
                "offset": offset
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
async def get_llm_stats_api():
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
async def get_three_sages_review_api():
    """3현자 데일리 리뷰 - Jennie, Minji, Junho의 시스템 검토"""
    r = get_redis()
    
    try:
        # Redis에서 최신 3현자 리뷰 조회
        if r:
            review_json = r.get("council:daily:review")
            if review_json:
                review = json.loads(review_json)
                return review
        
        # DAILY_MACRO_INSIGHT에서 RAW_COUNCIL_OUTPUT 조회
        try:
            from sqlalchemy import text
            with get_session() as session:
                result = session.execute(text("""
                    SELECT INSIGHT_DATE, RAW_COUNCIL_OUTPUT, TRADING_REASONING,
                           STRATEGIES_TO_FAVOR, STRATEGIES_TO_AVOID,
                           SECTORS_TO_FAVOR, SECTORS_TO_AVOID,
                           POLITICAL_RISK_LEVEL, POLITICAL_RISK_SUMMARY,
                           CREATED_AT
                    FROM DAILY_MACRO_INSIGHT
                    ORDER BY INSIGHT_DATE DESC
                    LIMIT 1
                """))
                row = result.fetchone()
                if row and row.RAW_COUNCIL_OUTPUT:
                    council_data = json.loads(row.RAW_COUNCIL_OUTPUT) if isinstance(row.RAW_COUNCIL_OUTPUT, str) else row.RAW_COUNCIL_OUTPUT
                    report_content = council_data.get("report_content", "")
                    
                    # 트레이딩 근거와 전략을 파싱
                    trading_reasoning = row.TRADING_REASONING or ""
                    strategies_favor = json.loads(row.STRATEGIES_TO_FAVOR) if row.STRATEGIES_TO_FAVOR else []
                    strategies_avoid = json.loads(row.STRATEGIES_TO_AVOID) if row.STRATEGIES_TO_AVOID else []
                    sectors_favor = json.loads(row.SECTORS_TO_FAVOR) if row.SECTORS_TO_FAVOR else []
                    sectors_avoid = json.loads(row.SECTORS_TO_AVOID) if row.SECTORS_TO_AVOID else []
                    
                    # 정치 리스크 정보
                    pol_level = row.POLITICAL_RISK_LEVEL or "low"
                    pol_summary = row.POLITICAL_RISK_SUMMARY or ""
                    
                    # 3현자 리뷰 생성 (Council 리포트 기반)
                    sages = [
                        {
                            "name": "Jennie",
                            "role": "수석 심판 (Chief Judge)",
                            "icon": "👑",
                            "review": trading_reasoning[:300] + "..." if len(trading_reasoning) > 300 else trading_reasoning or "트레이딩 전략 근거를 분석 중입니다.",
                        },
                        {
                            "name": "Minji",
                            "role": "리스크 분석가 (Risk Analyst)",
                            "icon": "🔍",
                            "review": f"정치적 리스크 수준: {pol_level.upper()}. {pol_summary[:200]}..." if pol_summary else "리스크 분석을 수행 중입니다.",
                        },
                        {
                            "name": "Junho",
                            "role": "전략가 (Strategist)",
                            "icon": "📈",
                            "review": f"유망 전략: {', '.join(strategies_favor[:3]) if strategies_favor else '분석 중'}. 회피 전략: {', '.join(strategies_avoid[:2]) if strategies_avoid else '없음'}. 유망 섹터: {', '.join(sectors_favor[:3]) if sectors_favor else '분석 중'}.",
                        },
                    ]
                    
                    # 합의 사항 생성
                    consensus_parts = []
                    if strategies_favor:
                        consensus_parts.append(f"유망 전략으로 {', '.join(strategies_favor[:2])}를 권장")
                    if sectors_favor:
                        consensus_parts.append(f"{', '.join(sectors_favor[:2])} 섹터에 주목")
                    if pol_level in ("high", "critical"):
                        consensus_parts.append(f"정치적 리스크({pol_level}) 주의 필요")
                    
                    return {
                        "date": row.INSIGHT_DATE.isoformat() if row.INSIGHT_DATE else None,
                        "sages": sages,
                        "consensus": ". ".join(consensus_parts) + "." if consensus_parts else None,
                        "action_items": strategies_favor[:5] if strategies_favor else [],
                        "generated_at": row.CREATED_AT.isoformat() if row.CREATED_AT else None,
                    }
        except Exception as db_e:
            logger.warning(f"DAILY_MACRO_INSIGHT Council 조회 실패: {db_e}")
        
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
# Macro Insight API - DAILY_MACRO_INSIGHT 조회
# =============================================================================

@app.get("/api/macro/dates")
async def get_macro_insight_dates():
    """매크로 인사이트 날짜 목록 조회 (최근 30일)"""
    try:
        from sqlalchemy import text
        with get_session() as session:
            result = session.execute(text("""
                SELECT INSIGHT_DATE
                FROM DAILY_MACRO_INSIGHT
                ORDER BY INSIGHT_DATE DESC
                LIMIT 30
            """))
            rows = result.fetchall()
            dates = [row.INSIGHT_DATE.isoformat() for row in rows if row.INSIGHT_DATE]
            return {"dates": dates}
    except Exception as e:
        logger.error(f"매크로 날짜 목록 조회 실패: {e}")
        return {"dates": [], "error": str(e)}


@app.get("/api/macro/insight")
async def get_macro_insight_api(
    date: Optional[str] = Query(None, description="조회할 날짜 (YYYY-MM-DD)"),
):
    """매크로 인사이트 조회 - Council 분석 결과"""
    r = get_redis()

    try:
        # 날짜 지정 없으면 캐시 확인 (최신 데이터)
        if not date and r:
            cached = r.get("macro:daily_insight")
            if cached:
                try:
                    return json.loads(cached)
                except json.JSONDecodeError:
                    pass

        # DB에서 조회
        from sqlalchemy import text
        with get_session() as session:
            if date:
                # 특정 날짜 조회
                result = session.execute(text("""
                    SELECT
                        INSIGHT_DATE, SOURCE_CHANNEL, SOURCE_ANALYST,
                        SENTIMENT, SENTIMENT_SCORE, REGIME_HINT,
                        SECTOR_SIGNALS, KEY_THEMES, RISK_FACTORS,
                        OPPORTUNITY_FACTORS, KEY_STOCKS,
                        RISK_STOCKS, OPPORTUNITY_STOCKS,
                        POSITION_SIZE_PCT, STOP_LOSS_ADJUST_PCT,
                        STRATEGIES_TO_FAVOR, STRATEGIES_TO_AVOID,
                        SECTORS_TO_FAVOR, SECTORS_TO_AVOID,
                        TRADING_REASONING,
                        POLITICAL_RISK_LEVEL, POLITICAL_RISK_SUMMARY,
                        VIX_VALUE, VIX_REGIME, USD_KRW, KOSPI_INDEX, KOSDAQ_INDEX,
                        KOSPI_FOREIGN_NET, KOSDAQ_FOREIGN_NET,
                        KOSPI_INSTITUTIONAL_NET, KOSPI_RETAIL_NET,
                        DATA_COMPLETENESS_PCT,
                        COUNCIL_COST_USD, CREATED_AT
                    FROM DAILY_MACRO_INSIGHT
                    WHERE INSIGHT_DATE = :target_date
                    LIMIT 1
                """), {"target_date": date})
            else:
                # 최신 1건
                result = session.execute(text("""
                    SELECT
                        INSIGHT_DATE, SOURCE_CHANNEL, SOURCE_ANALYST,
                        SENTIMENT, SENTIMENT_SCORE, REGIME_HINT,
                        SECTOR_SIGNALS, KEY_THEMES, RISK_FACTORS,
                        OPPORTUNITY_FACTORS, KEY_STOCKS,
                        RISK_STOCKS, OPPORTUNITY_STOCKS,
                        POSITION_SIZE_PCT, STOP_LOSS_ADJUST_PCT,
                        STRATEGIES_TO_FAVOR, STRATEGIES_TO_AVOID,
                        SECTORS_TO_FAVOR, SECTORS_TO_AVOID,
                        TRADING_REASONING,
                        POLITICAL_RISK_LEVEL, POLITICAL_RISK_SUMMARY,
                        VIX_VALUE, VIX_REGIME, USD_KRW, KOSPI_INDEX, KOSDAQ_INDEX,
                        KOSPI_FOREIGN_NET, KOSDAQ_FOREIGN_NET,
                        KOSPI_INSTITUTIONAL_NET, KOSPI_RETAIL_NET,
                        DATA_COMPLETENESS_PCT,
                        COUNCIL_COST_USD, CREATED_AT
                    FROM DAILY_MACRO_INSIGHT
                    ORDER BY INSIGHT_DATE DESC
                    LIMIT 1
                """))
            row = result.fetchone()

            if row:
                # JSON 필드 파싱 헬퍼
                def parse_json_field(val, default=None):
                    if val is None:
                        return default if default is not None else []
                    if isinstance(val, (list, dict)):
                        return val
                    try:
                        return json.loads(val)
                    except (json.JSONDecodeError, TypeError):
                        return default if default is not None else []

                risk_stocks = parse_json_field(getattr(row, 'RISK_STOCKS', None))
                opportunity_stocks = parse_json_field(getattr(row, 'OPPORTUNITY_STOCKS', None))
                key_stocks_raw = parse_json_field(row.KEY_STOCKS)

                insight = {
                    "insight_date": row.INSIGHT_DATE.isoformat() if row.INSIGHT_DATE else None,
                    "source_channel": row.SOURCE_CHANNEL,
                    "source_analyst": row.SOURCE_ANALYST,

                    # Sentiment & Regime
                    "sentiment": row.SENTIMENT,
                    "sentiment_score": row.SENTIMENT_SCORE,
                    "regime_hint": row.REGIME_HINT,

                    # Trading Recommendations
                    "position_size_pct": row.POSITION_SIZE_PCT or 100,
                    "stop_loss_adjust_pct": row.STOP_LOSS_ADJUST_PCT or 100,
                    "strategies_to_favor": parse_json_field(row.STRATEGIES_TO_FAVOR),
                    "strategies_to_avoid": parse_json_field(row.STRATEGIES_TO_AVOID),
                    "sectors_to_favor": parse_json_field(row.SECTORS_TO_FAVOR),
                    "sectors_to_avoid": parse_json_field(row.SECTORS_TO_AVOID),
                    "trading_reasoning": row.TRADING_REASONING,

                    # Political Risk
                    "political_risk_level": row.POLITICAL_RISK_LEVEL or "low",
                    "political_risk_summary": row.POLITICAL_RISK_SUMMARY,

                    # Market Data
                    "vix_value": row.VIX_VALUE,
                    "vix_regime": row.VIX_REGIME,
                    "usd_krw": row.USD_KRW,
                    "kospi_index": row.KOSPI_INDEX,
                    "kosdaq_index": row.KOSDAQ_INDEX,

                    # Investor Trading
                    "kospi_foreign_net": row.KOSPI_FOREIGN_NET,
                    "kosdaq_foreign_net": row.KOSDAQ_FOREIGN_NET,
                    "kospi_institutional_net": row.KOSPI_INSTITUTIONAL_NET,
                    "kospi_retail_net": row.KOSPI_RETAIL_NET,

                    # Analysis
                    "sector_signals": parse_json_field(row.SECTOR_SIGNALS, {}),
                    "key_themes": parse_json_field(row.KEY_THEMES),
                    "risk_factors": parse_json_field(row.RISK_FACTORS),
                    "opportunity_factors": parse_json_field(row.OPPORTUNITY_FACTORS),
                    "key_stocks": key_stocks_raw,
                    "risk_stocks": risk_stocks,
                    "opportunity_stocks": opportunity_stocks,

                    # Meta
                    "data_completeness_pct": row.DATA_COMPLETENESS_PCT,
                    "council_cost_usd": row.COUNCIL_COST_USD,
                    "created_at": row.CREATED_AT.isoformat() if row.CREATED_AT else None,
                }

                # Redis 캐시 (5분)
                if r:
                    try:
                        r.setex("macro:daily_insight", 300, json.dumps(insight, default=str))
                    except Exception:
                        pass

                return insight

        # 데이터 없음
        return {
            "insight_date": None,
            "message": "매크로 인사이트가 아직 생성되지 않았습니다. 매일 07:30 KST에 자동 생성됩니다.",
            "sentiment": None,
            "sentiment_score": None,
            "position_size_pct": 100,
            "stop_loss_adjust_pct": 100,
            "political_risk_level": "unknown",
        }

    except Exception as e:
        logger.error(f"매크로 인사이트 조회 실패: {e}")
        return {"error": str(e), "insight_date": None}

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

