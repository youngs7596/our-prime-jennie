#!/usr/bin/env python3
# Version: v1.0
# 작업 LLM: Claude Sonnet 4.5, Claude Opus 4.5
"""
Scout Job - 종목 발굴 파이프라인

기능:
- 깐깐한 필터링 (기본점수 20, Hunter 통과 60점, Judge 승인 75점)
- 쿼터제: 최종 Watchlist 상위 15개만 저장
- Debate 프롬프트: Bull/Bear 캐릭터 극단적으로 설정
- Redis 상태 저장: Dashboard에서 실시간 파이프라인 진행 상황 확인 가능
- 경쟁사 수혜 점수 반영: 경쟁사 악재 시 Hunter 점수에 가산
"""

import logging
import os
import sys
import time
import re
import threading
import json
import hashlib
import warnings
from typing import Dict, Tuple, List, Optional
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
import redis

# 로깅 설정을 모든 import 보다 먼저 수행
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s] - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger(__name__)

# 공용 라이브러리 임포트를 위한 경로 설정
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # /app
try:
    import shared
except ImportError:
    sys.path.insert(0, PROJECT_ROOT)

import shared.auth as auth
import shared.database as database
from shared.db.connection import session_scope, ensure_engine_initialized
from shared.kis import KISClient as KIS_API
from shared.kis.gateway_client import KISGatewayClient
from shared.llm import JennieBrain
from shared.financial_data_collector import batch_update_watchlist_financial_data

from shared.archivist import Archivist

import chromadb
from langchain_chroma import Chroma

# langchain_google_genai 내부 google.generativeai FutureWarning 무시
warnings.filterwarnings("ignore", category=FutureWarning, module="langchain_google_genai")
warnings.filterwarnings("ignore", category=FutureWarning, module="google.generativeai")
from langchain_google_genai import GoogleGenerativeAIEmbeddings



# Backtest 모듈 (선택적)
try:
    from utilities.backtest import Backtester
    logger.info("✅ Backtester 모듈 임포트 성공")
except ImportError:
    logger.info("ℹ️ Backtester 모듈 없음 - 백테스트 기능 비활성화")
    Backtester = None

# Chroma 서버
CHROMA_SERVER_HOST = os.getenv("CHROMA_SERVER_HOST", "10.178.0.2") 
CHROMA_SERVER_PORT = 8000

# 캐시/상태 관리 함수 (scout_cache.py)
from scout_cache import (
    # 상수
    STATE_PREFIX, CANDIDATE_DIGEST_SUFFIX, CANDIDATE_HASHES_SUFFIX,
    LLM_CACHE_SUFFIX, LLM_LAST_RUN_SUFFIX, ISO_FORMAT_Z,
    REDIS_URL,
    # Redis 함수
    _get_redis, _utcnow, update_pipeline_status, save_pipeline_results,
    # save_hot_watchlist removed from here
    # CONFIG 테이블 함수
    _get_scope, _make_state_key, _load_json_config, _save_json_config,
    _get_last_llm_run_at, _save_last_llm_run_at,
    _load_candidate_state, _save_candidate_state,
    # LLM_EVAL_CACHE 테이블 함수
    _load_llm_cache_from_db, _save_llm_cache_to_db, _save_llm_cache_batch,
    # 캐시 유효성 검사 및 해시 계산
    _is_cache_valid_direct, _get_price_bucket, _get_volume_bucket, _get_foreign_direction,
    _hash_candidate_payload, _compute_candidate_hashes,
    _minutes_since, _parse_int_env, _is_cache_entry_valid,
    _record_to_watchlist_entry, _record_to_cache_payload, _cache_payload_to_record,
)

# 종목 유니버스 관리 (scout_universe.py)
from scout_universe import (
    SECTOR_MAPPING, BLUE_CHIP_STOCKS,

    analyze_sector_momentum, get_hot_sector_stocks,
    get_dynamic_blue_chips, get_momentum_stocks,
    filter_valid_stocks
)
import scout_cache
from shared.watchlist import save_hot_watchlist
# 파이프라인 태스크 (scout_pipeline.py)
from scout_pipeline import (
    is_hybrid_scoring_enabled,
    process_quant_scoring_task,
    process_phase1_hunter_v5_task, process_phase23_judge_v5_task,
    fetch_kis_data_task,
)

_redis_client = None  # scout_cache에서 관리하지만 호환성 유지




def prefetch_all_data(candidate_stocks: Dict[str, Dict], kis_api, vectorstore) -> Tuple[Dict[str, Dict], Dict[str, str]]:
    """
    Phase 1 시작 전에 모든 데이터를 일괄 조회하여 캐시
    
    Returns:
        (snapshot_cache, news_cache) - 종목코드를 키로 하는 dict
    
    효과: 병렬 스레드 안에서 API 호출 제거 → Rate Limit 회피 + 속도 향상
    """
    stock_codes = list(candidate_stocks.keys())
    logger.info(f"   (Prefetch) {len(stock_codes)}개 종목 데이터 사전 조회 시작...")
    
    snapshot_cache: Dict[str, Dict] = {}
    news_cache: Dict[str, str] = {}
    
    prefetch_start = time.time()
    
    # 1. KIS API 스냅샷 병렬 조회 (4개 워커)
    logger.info(f"   (Prefetch) KIS 스냅샷 조회 중...")
    snapshot_start = time.time()
    
    def fetch_snapshot(code):
        try:
            if hasattr(kis_api, 'API_CALL_DELAY'):
                time.sleep(kis_api.API_CALL_DELAY * 0.3)  # 약간의 딜레이
            return code, kis_api.get_stock_snapshot(code)
        except Exception as e:
            logger.debug(f"   ⚠️ [{code}] Snapshot 조회 실패: {e}")
            return code, None
    
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(fetch_snapshot, code) for code in stock_codes]
        for future in as_completed(futures):
            code, snapshot = future.result()
            if snapshot:
                snapshot_cache[code] = snapshot
    
    snapshot_time = time.time() - snapshot_start
    logger.info(f"   (Prefetch) ✅ KIS 스냅샷 {len(snapshot_cache)}/{len(stock_codes)}개 조회 완료 ({snapshot_time:.1f}초)")
    
    # 2. ChromaDB 뉴스 병렬 조회 (8개 워커)
    if vectorstore:
        logger.info(f"   (Prefetch) ChromaDB 뉴스 조회 중...")
        news_start = time.time()
        
        def fetch_news(code_name):
            code, name = code_name
            try:
                news = fetch_stock_news_from_chroma(vectorstore, code, name, k=3)
                return code, news
            except Exception as e:
                logger.debug(f"   ⚠️ [{code}] 뉴스 조회 실패: {e}")
                return code, "뉴스 조회 실패"
        
        code_name_pairs = [(code, info.get('name', '')) for code, info in candidate_stocks.items()]
        
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(fetch_news, pair) for pair in code_name_pairs]
            for future in as_completed(futures):
                code, news = future.result()
                news_cache[code] = news
        
        news_time = time.time() - news_start
        valid_news = sum(1 for n in news_cache.values() if n and n not in ["뉴스 DB 미연결", "최근 관련 뉴스 없음", "뉴스 검색 오류", "뉴스 조회 실패"])
        logger.info(f"   (Prefetch) ✅ ChromaDB 뉴스 {valid_news}/{len(stock_codes)}개 조회 완료 ({news_time:.1f}초)")
    
    total_time = time.time() - prefetch_start
    logger.info(f"   (Prefetch) ✅ 전체 사전 조회 완료 ({total_time:.1f}초)")
    
    return snapshot_cache, news_cache


def enrich_candidates_with_market_data(candidate_stocks: Dict[str, Dict], session, vectorstore) -> None:
    """
    후보군에 시장 데이터 추가 (해시 계산용)
    
    해시에 포함될 데이터:
    - price: 최신 종가 (5% 버킷화됨)
    - volume: 최신 거래량 (10만주 버킷화됨)
    - foreign_net: 외국인 순매수 (방향만 - buy/sell/neutral)
    - news_date: 최신 뉴스 날짜 (YYYY-MM-DD)
    """
    if not candidate_stocks:
        return
    
    stock_codes = list(candidate_stocks.keys())
    logger.info(f"   (Hash) {len(stock_codes)}개 종목 시장 데이터 조회 중...")
    
    # 1. DB에서 최신 가격/거래량 데이터 일괄 조회
    try:
        from sqlalchemy import text
        
        placeholders = ','.join([f"'{code}'" for code in stock_codes])
        
        # 최신 날짜의 데이터만 조회 (가격, 거래량)
        query = text(f"""
            SELECT STOCK_CODE, CLOSE_PRICE, VOLUME, PRICE_DATE
            FROM STOCK_DAILY_PRICES_3Y
            WHERE STOCK_CODE IN ({placeholders})
            AND (STOCK_CODE, PRICE_DATE) IN (
                SELECT STOCK_CODE, MAX(PRICE_DATE) 
                FROM STOCK_DAILY_PRICES_3Y
                WHERE STOCK_CODE IN ({placeholders})
                GROUP BY STOCK_CODE
            )
        """)
        rows = session.execute(query).fetchall()
        
        for row in rows:
            code = row[0]
            price = row[1]
            volume = row[2]
            
            if code in candidate_stocks:
                candidate_stocks[code]['price'] = float(price) if price else 0
                candidate_stocks[code]['volume'] = int(volume) if volume else 0
        
        logger.info(f"   (Hash) ✅ DB에서 {len(rows)}개 종목 시장 데이터 로드")
        
        # [Fix] 최신 뉴스 감성 점수 조회 (NEWS_SENTIMENT - Active Table)
        # QuantScorer에 전달하기 위해 여기서 조회
        sent_query = text(f"""
            SELECT STOCK_CODE, SENTIMENT_SCORE 
            FROM NEWS_SENTIMENT
            WHERE STOCK_CODE IN ({placeholders})
            AND PUBLISHED_AT >= DATE_SUB(NOW(), INTERVAL 3 DAY)
            AND (STOCK_CODE, PUBLISHED_AT) IN (
                SELECT STOCK_CODE, MAX(PUBLISHED_AT)
                FROM NEWS_SENTIMENT
                WHERE STOCK_CODE IN ({placeholders})
                GROUP BY STOCK_CODE
            )
        """)
        sent_rows = session.execute(sent_query).fetchall()
        for row in sent_rows:
            code = row[0]
            score = row[1]
            if code in candidate_stocks and score is not None:
                candidate_stocks[code]['sentiment_score'] = float(score)
        
        logger.info(f"   (Hash) ✅ DB에서 {len(sent_rows)}개 종목 뉴스 감성 점수 로드")
    except Exception as e:
        logger.warning(f"   (Hash) ⚠️ DB 시장 데이터 조회 실패: {e}")
    
    # 2. ChromaDB 뉴스 조회 생략 (속도 최적화)
    # 이유: 해시에 오늘 날짜가 포함되어 있어서 매일 재평가 보장됨
    # 뉴스 데이터는 Phase 1 Hunter에서 개별 종목 평가 시 조회함
    logger.info(f"   (Hash) ✅ 뉴스 날짜 조회 생략 (날짜 기반 캐시 무효화로 대체)")


def _get_latest_news_date(vectorstore, stock_code: str, stock_name: str) -> Optional[str]:
    """ChromaDB에서 종목의 최신 뉴스 날짜 조회"""
    try:
        from datetime import datetime, timezone
        
        docs = vectorstore.similarity_search(
            query=f"{stock_name}",
            k=1,
            filter={"stock_code": stock_code}
        )
        if docs and docs[0].metadata:
            # crawler.py는 'created_at_utc' (int timestamp)를 저장함
            # 'date'나 'published_at'은 legacy
            timestamp = docs[0].metadata.get('created_at_utc')
            if timestamp:
                return datetime.fromtimestamp(int(timestamp), tz=timezone.utc).strftime('%Y-%m-%d')

            # Legacy fields fallback
            news_date = docs[0].metadata.get('date') or docs[0].metadata.get('published_at')
            if news_date:
                return str(news_date)[:10]
    except Exception:
        pass
    return None

# ... (skip _record_to_cache_payload, _cache_payload_to_record, etc.)

def fetch_stock_news_from_chroma(vectorstore, stock_code: str, stock_name: str, k: int = 3) -> str:
    """
    ChromaDB에서 종목별 최신 뉴스 검색
    
    Args:
        vectorstore: ChromaDB vectorstore 인스턴스
        stock_code: 종목 코드
        stock_name: 종목명
        k: 가져올 뉴스 개수
        
    Returns:
        뉴스 요약 문자열 (없으면 "최근 관련 뉴스 없음")
    """
    if not vectorstore:
        return "뉴스 DB 미연결"
    
    try:
        from datetime import datetime, timedelta, timezone
        
        # 최신 7일 이내 뉴스 필터
        recency_timestamp = int((datetime.now(timezone.utc) - timedelta(days=7)).timestamp())
        
        # 종목 코드로 필터링된 뉴스 검색 시도
        try:
            # 날짜 필터($gte) 추가하여 오래된 뉴스(2020년 등) 방지
            docs = vectorstore.similarity_search(
                query=f"{stock_name} 실적 수주 호재",
                k=k,
                filter={
                    "$and": [
                        {"stock_code": stock_code},
                        {"created_at_utc": {"$gte": recency_timestamp}}
                    ]
                }
            )
            # logger.debug(f"   (D) [{stock_code}] 필터 검색 결과: {len(docs)}건")
        except Exception:
            # 필터 실패시 종목명으로 검색
            docs = vectorstore.similarity_search(
                query=f"{stock_name} 주식 뉴스",
                k=k
            )
            logger.debug(f"   (D) [{stock_code}] 종목명 검색(Fallback): {len(docs)}건")
            # 종목 관련 뉴스만 필터링
            docs = [d for d in docs if stock_name in d.page_content or stock_code in str(d.metadata)]
        
        if docs:
            news_items = []
            for i, doc in enumerate(docs[:k], 1):
                content = doc.page_content[:100].strip()
                if content:
                    news_items.append(f"[뉴스{i}] {content}")
            
            if news_items:
                return " | ".join(news_items)
        
        return "최근 관련 뉴스 없음"
        
    except Exception as e:
        logger.debug(f"   ⚠️ [{stock_code}] ChromaDB 뉴스 검색 오류: {e}")
        return "뉴스 검색 오류"


# 파이프라인 태스크 함수 (scout_pipeline.py)
# - is_hybrid_scoring_enabled, process_quant_scoring_task
# - process_phase1_hunter_v5_task, process_phase23_judge_v5_task
# - process_phase1_hunter_task, process_phase23_debate_judge_task
# - process_llm_decision_task, fetch_kis_data_task

def main():
    start_time = time.time()
    
    logger.info("--- 🤖 'Scout Job' 실행 시작 ---")
    
    kis_api = None
    brain = None

    try:
        logger.info("--- [Init] 환경 변수 로드 및 KIS API 연결 시작 ---")
        load_dotenv(override=True)
        
        trading_mode = os.getenv("TRADING_MODE", "REAL")
        use_gateway = os.getenv("USE_KIS_GATEWAY", "true").lower() == "true"
        
        if use_gateway:
            kis_api = KISGatewayClient()
            logger.info("✅ KIS Gateway Client 초기화 완료")
        else:
            kis_api = KIS_API(
                app_key=auth.get_secret(os.getenv(f"{trading_mode}_SECRET_ID_APP_KEY")),
                app_secret=auth.get_secret(os.getenv(f"{trading_mode}_SECRET_ID_APP_SECRET")),
                base_url=os.getenv(f"KIS_BASE_URL_{trading_mode}"),
                account_prefix=auth.get_secret(os.getenv(f"{trading_mode}_SECRET_ID_ACCOUNT_PREFIX")),
                account_suffix=os.getenv("KIS_ACCOUNT_SUFFIX"),
                token_file_path="/app/tokens/kis_token_scout.json",
                trading_mode=trading_mode
            )
            if not kis_api.authenticate():
                raise Exception("KIS API 인증에 실패했습니다.")
        
        # [Check] 실행 시간 제한 (07:00 ~ 16:00)
        # 테스트/Mock 모드이거나 강제 실행 설정이 아니면 시간 체크 수행
        disable_check = os.getenv("DISABLE_MARKET_OPEN_CHECK", "false").lower() in {"1", "true", "yes", "on"}
        
        if not disable_check and trading_mode.lower() != "mock":
            import pytz
            kst = pytz.timezone('Asia/Seoul')
            now_kst = datetime.now(kst)

            # 주말 체크 (토=5, 일=6)
            if now_kst.weekday() >= 5:
                logger.info(f"🛑 [Check] 오늘은 주말({now_kst.strftime('%A')})이므로 실행하지 않습니다. (Scout 종료)")
                return
            
            if 7 <= now_kst.hour < 16:
                logger.info(f"📅 [Check] 현재 시간({now_kst.strftime('%H:%M')})은 실행 허용 시간(07:00~16:00)입니다.")
            else:
                logger.info(f"🛑 [Check] 현재 시간({now_kst.strftime('%H:%M')})은 실행 허용 시간이 아닙니다. (Scout 종료)")
                return
        else:
            logger.info("⏩ 시간/장운영 체크를 건너뜁니다 (mock/test 모드 또는 DISABLE_MARKET_OPEN_CHECK=true).")
        
        brain = JennieBrain(
            project_id=os.getenv("GCP_PROJECT_ID", "local"),
            gemini_api_key_secret=os.getenv("SECRET_ID_GEMINI_API_KEY")
        )
        
        # SQLAlchemy 세션 초기화 (session_scope 사용 전에 호출 필수)
        ensure_engine_initialized()
        
        # SQLAlchemy 세션 사용
        with session_scope() as session:
            watchlist_snapshot = database.get_active_watchlist(session)
            
            vectorstore = None
            # RAG 활성화 여부 확인 (기본값: True)
            enable_rag = os.getenv("ENABLE_RAG", "true").lower() == "true"
            rag_provider = os.getenv("RAG_EMBEDDING_PROVIDER", "local").lower()  # 기본값 local (비용 절감)

            if not enable_rag:
                logger.info("⏩ [Config] RAG 기능이 비활성화되어 있습니다 (ENABLE_RAG=false).")
                vectorstore = None
            else:
                try:
                    embeddings = None
                    if rag_provider == "local":
                        # Local Embedding (HuggingFace)
                        logger.info("   ... ChromaDB 클라이언트 연결 시도 (Local Embeddings: jhgan/ko-sroberta-multitask) ...")
                        try:
                            from langchain_huggingface import HuggingFaceEmbeddings
                            embeddings = HuggingFaceEmbeddings(
                                model_name="jhgan/ko-sroberta-multitask",
                                model_kwargs={"device": "cpu"},
                                encode_kwargs={"normalize_embeddings": True}
                            )
                        except ImportError:
                            logger.error("🚨 langchain_huggingface 모듈이 설치되지 않았습니다. RAG를 사용할 수 없습니다.")
                            raise

                    else:
                        # Cloud Embedding (Gemini)
                        logger.info("   ... ChromaDB 클라이언트 연결 시도 (Gemini Embeddings) ...")
                        api_key = auth.get_secret("gemini-api-key")
                        if not api_key:
                             raise ValueError("Gemini API Key not found")
                        embeddings = GoogleGenerativeAIEmbeddings(
                            model="models/gemini-embedding-001", 
                            google_api_key=api_key
                        )
                    
                    chroma_client = chromadb.HttpClient( # noqa
                        host=CHROMA_SERVER_HOST, 
                        port=CHROMA_SERVER_PORT
                    )
                    vectorstore = Chroma(
                        client=chroma_client, 
                        collection_name="rag_stock_data", 
                        embedding_function=embeddings
                    )
                    logger.info(f"✅ LLM 및 ChromaDB 클라이언트 초기화 완료 (Provider: {rag_provider}).")
                except Exception as e:
                    logger.warning(f"⚠️ ChromaDB 초기화 실패 (RAG 기능 비활성화): {e}")
                    vectorstore = None

            # Phase 1: 트리플 소스 후보 발굴 (v3.8: 섹터 분석 추가)
            logger.info("--- [Phase 1] 트리플 소스 후보 발굴 시작 ---")
            update_pipeline_status(phase=1, phase_name="Hunter Scout", status="running", progress=0)
            candidate_stocks = {}

            # A: 동적 우량주 (KOSPI 200 기준)
            universe_size = int(os.getenv("SCOUT_UNIVERSE_SIZE", "200"))
            for stock in get_dynamic_blue_chips(limit=universe_size):
                candidate_stocks[stock['code']] = {
                    'name': stock['name'], 
                    'sector': stock.get('sector'),
                    'reasons': ['KOSPI 시총 상위']
                }
            
            # E: 섹터 모멘텀 분석 (v3.8 신규)
            sector_analysis = analyze_sector_momentum(kis_api, session, watchlist_snapshot)
            hot_sector_stocks = get_hot_sector_stocks(sector_analysis, top_n=30)
            for stock in hot_sector_stocks:
                if stock['code'] not in candidate_stocks:
                    candidate_stocks[stock['code']] = {
                        'name': stock['name'], 
                        'sector': stock.get('sector'),
                        'reasons': [f"핫 섹터 ({stock['sector']}, +{stock['sector_momentum']:.1f}%)"]
                    }
                else:
                    candidate_stocks[stock['code']]['reasons'].append(
                        f"핫 섹터 ({stock['sector']}, +{stock['sector_momentum']:.1f}%)"
                    )

            # B: 정적 우량주
            for stock in BLUE_CHIP_STOCKS:
                if stock['code'] not in candidate_stocks:
                    candidate_stocks[stock['code']] = {'name': stock['name'], 'reasons': ['정적 우량주']}

            # C: RAG
            if vectorstore:
                try:
                    logger.info("   (C) RAG 기반 후보 발굴 중...")
                    rag_results = vectorstore.similarity_search(query="실적 호재 계약 수주", k=50)
                    for doc in rag_results:
                        stock_code = doc.metadata.get('stock_code')
                        stock_name = doc.metadata.get('stock_name')
                        if stock_code and stock_name:
                            if stock_code not in candidate_stocks:
                                candidate_stocks[stock_code] = {'name': stock_name, 'reasons': []}
                            candidate_stocks[stock_code]['reasons'].append("RAG 기반 호재 검색")
                except Exception as e:
                    logger.warning(f"   (C) RAG 후보 발굴 실패: {e}")

            # NEW: Filter against STOCK_MASTER (Remove ETFs and unregistered stocks)
            candidate_stocks = filter_valid_stocks(candidate_stocks, session)

            # D: 모멘텀
            logger.info("   (D) 모멘텀 팩터 기반 종목 발굴 중...")
            momentum_stocks = get_momentum_stocks(
                    kis_api,
                    session,
                period_months=6,
                top_n=30,
                watchlist_snapshot=watchlist_snapshot
            )
            for stock in momentum_stocks:
                if stock['code'] not in candidate_stocks:
                    candidate_stocks[stock['code']] = {
                        'name': stock['name'], 
                        'reasons': [f'모멘텀 ({stock["momentum"]:.1f}%)']
                    }
            
            logger.info(f"   ✅ 후보군 {len(candidate_stocks)}개 발굴 완료.")
            
            # [Filter] 제외 종목 필터링 (v1.1)
            excluded_stocks = [s.strip() for s in os.getenv("EXCLUDED_STOCKS", "").split(",") if s.strip()]
            if excluded_stocks:
                logger.info(f"   🚫 제외 종목 필터 적용: {excluded_stocks}")
                for ex_code in excluded_stocks:
                    if ex_code in candidate_stocks:
                        del candidate_stocks[ex_code]
                        logger.info(f"      - {ex_code} 제외됨 (사용자 설정)")
            
            # [DEBUG] Truncate for Judge Phase Verification - Removed
            # candidate_stocks = dict(list(candidate_stocks.items())[:3])

            # 해시 계산 전에 시장 데이터 추가 (가격, 거래량)
            logger.info("--- [Phase 1.5] 시장 데이터 기반 해시 계산 ---")
            enrich_candidates_with_market_data(candidate_stocks, session, vectorstore)
            
    # Phase 1 시작 전에 모든 데이터 일괄 조회 (병렬 스레드 안 API 호출 제거)
            logger.info("--- [Phase 1.6] 데이터 사전 조회 (스냅샷/뉴스) ---")
            snapshot_cache, news_cache = prefetch_all_data(candidate_stocks, kis_api, vectorstore)

            # [Filter] 잡주 필터링 (Junk Stock Filter) - 시총/주가 기준
            # Config: JUNK_FILTER_MIN_CAP_BILLION (기본 500억), JUNK_FILTER_MIN_PRICE (기본 1000원)
            min_cap_billion = _parse_int_env(os.getenv("JUNK_FILTER_MIN_CAP_BILLION"), 50) # 500억 (단위: 억 아님. input int 50 -> 500억?)
            # Wait, DB unit is Million. 50B = 50,000 Million.
            # User expectation: 500억. 
            # Let's align with ENV var naming. 
            # If ENV is "50", it might mean 50 Billion?
            # Let's set default code constant to 50000 (Million KRW) for safety and clarity.
            
            junk_min_cap_unit = _parse_int_env(os.getenv("MIN_MARKET_CAP_INT"), 50000) # Default 500억 (50000 백만)
            junk_min_price = _parse_int_env(os.getenv("MIN_PRICE_INT"), 1000)

            junk_dropped = 0
            junk_codes = []
            
            for code in list(candidate_stocks.keys()):
                if code == '0001': continue # 지수는 제외
                
                # Check 1: Penny Stock
                price = candidate_stocks[code].get('price', 0)
                # Check 2: Small Cap (Use Snapshot)
                snapshot = snapshot_cache.get(code)
                market_cap = snapshot.get('market_cap', 0) if snapshot else 0
                
                is_penny = price < junk_min_price
                is_small_cap = market_cap < junk_min_cap_unit
                
                if is_penny or is_small_cap:
                    reason = []
                    if is_penny: reason.append(f"동전주({price:,.0f}원)")
                    if is_small_cap: reason.append(f"초소형주({market_cap//100:,.0f}억)")
                    
                    logger.info(f"      🗑️ [JunkFilter] {candidate_stocks[code]['name']}({code}) 제외: {', '.join(reason)}")
                    del candidate_stocks[code]
                    if snapshot_cache.get(code): del snapshot_cache[code] # Clean cache too
                    if news_cache.get(code): del news_cache[code]
                    junk_dropped += 1
                    junk_codes.append(code)
            
            if junk_dropped > 0:
                logger.info(f"   (Filter) 🚫 잡주 필터링: {junk_dropped}개 종목 제외 완료")

            # [NEW] Phase 1.7: 스냅샷에서 재무지표(PER/PBR) 추출 → STOCK_FUNDAMENTALS 저장
            # 이유: 전체 200개 종목의 재무 데이터를 일일 단위로 축적하여 백테스트 정확도 향상
            logger.info("--- [Phase 1.7] 재무지표 저장 (STOCK_FUNDAMENTALS) ---")
            from datetime import date
            fundamentals_to_save = []
            today = date.today()
            for code, snapshot in snapshot_cache.items():
                if snapshot and (snapshot.get('per') or snapshot.get('pbr')):
                    fundamentals_to_save.append({
                        'stock_code': code,
                        'trade_date': today,
                        'per': snapshot.get('per'),
                        'pbr': snapshot.get('pbr'),
                        'roe': None,  # KIS API 스냅샷에는 ROE가 없음
                        'market_cap': snapshot.get('market_cap')
                    })
            if fundamentals_to_save:
                database.update_all_stock_fundamentals(session, fundamentals_to_save)
                logger.info(f"   (DB) ✅ 재무지표 {len(fundamentals_to_save)}개 종목 저장 완료")

            # 뉴스 해시를 candidate_stocks에 반영 (해시 계산에 포함)
            # 뉴스 내용이 바뀌면 해시가 달라져 LLM 재호출됨
            news_hash_count = 0
            for code, news in news_cache.items():
                if code in candidate_stocks and news and news not in [
                    "뉴스 DB 미연결", "최근 관련 뉴스 없음", "뉴스 검색 오류", 
                    "뉴스 조회 실패", "뉴스 캐시 없음"
                ]:
                    # 뉴스 내용의 MD5 해시 (시간 정보 포함되어 있음)
                    candidate_stocks[code]['news_hash'] = hashlib.md5(news.encode()).hexdigest()[:16]
                    news_hash_count += 1
            logger.info(f"   (Hash) ✅ 뉴스 해시 {news_hash_count}개 반영 완료")

            # Phase 1.8: 수급 데이터(Market Flow) 분석 및 기록
            logger.info("--- [Phase 1.8] 수급 데이터(Market Flow) 분석 (Foreign/Institution) ---")
            
            # [Optimization] 병렬로 투자자 동향 조회
            investor_flow_cache = {}
            
            # Archivist 초기화 (여기서도 사용)
            if 'archivist' not in locals():
                archivist = Archivist(session_scope)
                
            def process_flow_data(code):
                try:
                    # [Tier 1] KIS API via gateway.market_data
                    try:
                        trends = kis_api.get_market_data().get_investor_trend(code, start_date=None, end_date=None)
                    except (AttributeError, Exception):
                        # [Tier 2] KIS API Direct (If method is missing or fails)
                        try:
                            trends = kis_api.get_investor_trend(code, start_date=None, end_date=None)
                        except Exception:
                            trends = None
                    
                    if trends:
                        # 가장 최근 데이터 (오늘)
                        return code, trends[-1]
                    
                    # [Tier 3] DB Fallback (Historical Data)
                    try:
                        from shared.database.market import get_investor_trading
                        df = get_investor_trading(session, code, limit=1)
                        if not df.empty:
                            row = df.iloc[-1]
                            return code, {
                                'date': row['TRADE_DATE'].strftime('%Y%m%d'),
                                'foreigner_net_buy': int(row['FOREIGN_NET_BUY']),
                                'institution_net_buy': int(row['INSTITUTION_NET_BUY']),
                                'individual_net_buy': int(row['INDIVIDUAL_NET_BUY']),
                                'price': float(row['CLOSE_PRICE'])
                            }
                    except Exception as e:
                        logger.debug(f"   ⚠️ [{code}] DB 수급 조회 실패: {e}")
                        
                    return code, None
                except Exception as e:
                    return code, None

            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = [executor.submit(process_flow_data, code) for code in candidate_stocks.keys()]
                for future in as_completed(futures):
                    code, flow_data = future.result()
                    if flow_data:
                        investor_flow_cache[code] = flow_data
                        
                        # 후보군 정보에 수급 데이터 추가 (LLM 프롬프트용)
                        candidate_stocks[code]['market_flow'] = {
                            'foreign_net_buy': flow_data['foreigner_net_buy'],
                            'institution_net_buy': flow_data['institution_net_buy'],
                            'individual_net_buy': flow_data['individual_net_buy']
                        }
                        
                        # Archivist에 기록 (Market Flow Snapshot)
                        try:
                            # flow_data는 dict 형태 (date, price, foreign..., institution...)
                            # Archivist.log_market_flow_snapshot은 stock_code를 포함한 dict를 기대함
                            log_payload = flow_data.copy()
                            log_payload['stock_code'] = code
                            # volume 필드가 get_investor_trend 결과에 없으므로 (필요시) 보완
                            # log_payload['volume'] = ... 
                            
                            archivist.log_market_flow_snapshot(log_payload)
                        except Exception as log_e:
                            logger.warning(f"Failed to log market flow for {code}: {log_e}")

            logger.info(f"   (Flow) ✅ 수급 데이터 {len(investor_flow_cache)}개 종목 분석 및 기록 완료")

            # Phase 2: LLM 최종 선정
            logger.info("--- [Phase 2] LLM 기반 최종 Watchlist 선정 시작 ---")
            update_pipeline_status(
                phase=1, phase_name="Hunter Scout", status="running", 
                total_candidates=len(candidate_stocks)
            )
            
            # 하이브리드 스코어링 모드 분기
            if is_hybrid_scoring_enabled():
                logger.info("=" * 60)
                logger.info("   🚀 Scout v5 Hybrid Scoring Mode 활성화!")
                logger.info("=" * 60)
                
                # Analyst Feedback Load
                feedback_context = None
                try:
                    redis_conn = _get_redis()
                    feedback_data = redis_conn.get("analyst:feedback:summary")
                    if feedback_data:
                        # redis-py가 decode_responses=True이면 이미 str 반환
                        feedback_context = feedback_data if isinstance(feedback_data, str) else feedback_data.decode('utf-8')
                        logger.info(f"   🧠 [Feedback] Analyst 전략 교훈 로드 완료 ({len(feedback_context)} chars)")
                    else:
                        logger.info("   🧠 [Feedback] 저장된 전략 교훈이 없습니다.")
                except Exception as e:
                    logger.warning(f"   ⚠️ [Feedback] 로드 실패: {e}")
                
                try:
                    from shared.hybrid_scoring import (
                        QuantScorer, HybridScorer, 
                        create_hybrid_scoring_tables,
                        format_quant_score_for_prompt,
                    )
                    from shared.market_regime import MarketRegimeDetector
                    
                    # DB 테이블 생성 확인
                    create_hybrid_scoring_tables(session)
                    
                    # 시장 국면 감지
                    kospi_prices = database.get_daily_prices(session, "0001", limit=60)
                    if not kospi_prices.empty:
                        # [Fix] 실시간 코스피 지수 조회 (장중 변동성 즉각 반영)
                        kospi_current = None
                        try:
                            kospi_snapshot = kis_api.get_stock_snapshot("0001", is_index=True)
                            if kospi_snapshot:
                                kospi_current = float(kospi_snapshot['price'])
                                logger.info(f"   (Market) 📡 실시간 KOSPI 지수: {kospi_current:.2f}")
                        except Exception as e:
                            logger.warning(f"   (Market) ⚠️ 실시간 KOSPI 조회 실패 (어제 종가 사용): {e}")

                        # 실시간 조회 실패 시, DB의 마지막 종가(어제) 사용
                        if kospi_current is None:
                            kospi_current = float(kospi_prices['CLOSE_PRICE'].iloc[-1])

                        detector = MarketRegimeDetector()
                        current_regime, _ = detector.detect_regime(kospi_prices, kospi_current, quiet=True)
                    else:
                        current_regime = "SIDEWAYS"
                    
                    logger.info(f"   현재 시장 국면: {current_regime}")

                    # [NEW] Dashboard 표시를 위해 Redis에 저장
                    try:
                        redis_conn = _get_redis()
                        if redis_conn:
                            regime_data = {
                                "regime": current_regime,
                                "confidence": 0.8, # TODO: Detector에서 confidence 반환하도록 개선 필요
                                "updated_at": datetime.now().isoformat(),
                                "description": f"KOSPI Analysis Based on {len(kospi_prices)} days"
                            }
                            redis_conn.set("market:regime:data", json.dumps(regime_data))
                            logger.info("   (Redis) Market Regime 데이터 저장 완료")
                    except Exception as re:
                        logger.warning(f"   (Redis) Market Regime 저장 실패: {re}")
                    
                    # QuantScorer 초기화
                    quant_scorer = QuantScorer(session, market_regime=current_regime)
                    
                    # Step 1: 정량 점수 계산 (LLM 호출 없음, 비용 0원)
                    logger.info(f"\n   [Step 1] 정량 점수 계산 ({len(candidate_stocks)}개 종목) - 비용 0원")
                    quant_results = {}
                    
                    for code, info in candidate_stocks.items():
                        if code == '0001':
                            continue
                        stock_info = {
                            'code': code,
                            'info': info,
                            'snapshot': snapshot_cache.get(code),
                        }
                        quant_results[code] = process_quant_scoring_task(
                            stock_info, quant_scorer, session, kospi_prices
                        )
                    
                    # Step 2: 정량 기반 1차 필터링 (하위 60% 탈락 → 상위 40% 통과)
                    logger.info(f"\n   [Step 2] 정량 기반 1차 필터링 (상위 40% 통과)")
                    quant_result_list = list(quant_results.values())
                    filtered_results = quant_scorer.filter_candidates(quant_result_list, cutoff_ratio=0.6)
                    
                    filtered_codes = {r.stock_code for r in filtered_results}
                    logger.info(f"   ✅ 정량 필터 통과: {len(filtered_codes)}개 (평균 점수: {sum(r.total_score for r in filtered_results)/len(filtered_results):.1f}점)")
                    
                    # Step 3: LLM 정성 분석 (통과 종목만)
                    logger.info(f"\n   [Step 3] LLM 정성 분석 (통계 컨텍스트 포함)")
                    
                    final_approved_list: List[Dict] = []
                    if '0001' in candidate_stocks:
                        final_approved_list.append({'code': '0001', 'name': 'KOSPI', 'is_tradable': False})
                    
                    llm_decision_records: Dict[str, Dict] = {}
                    
                    # 2025-12-24: Cloud vs Ollama 병렬 처리 차등 적용
                    # Cloud (OpenAI, Gemini, Claude): 8개 병렬 (Rate Limit 내에서 문제없음)
                    # Ollama (로컬): Hunter 4, Judge 1 (GPU 부하/안정성)
                    is_ollama_active = (
                        os.getenv("TIER_REASONING_PROVIDER", "ollama").lower() == "ollama" or 
                        os.getenv("TIER_THINKING_PROVIDER", "ollama").lower() == "ollama"
                    )
                    
                    if is_ollama_active:
                        # Ollama 로컬 모드: 보수적 병렬 처리
                        hunter_max_workers = _parse_int_env(os.getenv("SCOUT_HUNTER_MAX_WORKERS"), 4)
                        judge_max_workers = _parse_int_env(os.getenv("SCOUT_JUDGE_MAX_WORKERS"), 1)
                        logger.info(f"   (Config) 🐢 Ollama Mode - Hunter: {hunter_max_workers}, Judge: {judge_max_workers}")
                    else:
                        # Cloud 모드: 풀 병렬 처리
                        hunter_max_workers = _parse_int_env(os.getenv("SCOUT_HUNTER_MAX_WORKERS"), 8)
                        judge_max_workers = _parse_int_env(os.getenv("SCOUT_JUDGE_MAX_WORKERS"), 8)
                        logger.info(f"   (Config) ☁️ Cloud Mode - Hunter: {hunter_max_workers}, Judge: {judge_max_workers}")
                    
                    # Phase 1: Hunter (통계 컨텍스트 포함)
                    phase1_results = []
                    # Archivist 초기화 (Phase 1/2 공용)
                    archivist = Archivist(session_scope)

                    # Smart Skip Filter - LLM 호출 전 사전 필터링
                    from scout_pipeline import should_skip_hunter
                    
                    llm_candidates = []
                    smart_skipped = []
                    skip_reasons_count = {}
                    
                    # LLM 캐시 로드 (이전 Hunter 점수 참조용)
                    try:
                        db_conn = session.connection().connection
                    except Exception:
                        db_conn = None
                    llm_cache = _load_llm_cache_from_db(db_conn) if db_conn else {}
                    
                    for code in filtered_codes:
                        info = candidate_stocks[code]
                        quant_result = quant_results[code]
                        
                        # 경쟁사 수혜 점수 조회
                        competitor_benefit = database.get_competitor_benefit_score(code)
                        competitor_bonus = competitor_benefit.get('score', 0)
                        
                        # 이전 캐시에서 Hunter 점수 조회
                        cached = llm_cache.get(code)
                        cached_hunter = cached.get('hunter_score') if cached else None
                        
                        # 뉴스 감성 점수 (info에서 가져오기)
                        news_sentiment = info.get('sentiment_score')
                        
                        # Smart Skip 체크
                        should_skip, reason = should_skip_hunter(
                            quant_result, cached_hunter, news_sentiment, competitor_bonus
                        )
                        
                        if should_skip:
                            smart_skipped.append((code, info['name'], reason))
                            # Skip 사유별 카운트
                            reason_key = reason.split('(')[0].strip()
                            skip_reasons_count[reason_key] = skip_reasons_count.get(reason_key, 0) + 1
                        else:
                            llm_candidates.append(code)
                    
                    logger.info(f"   🚀 [Smart Skip] {len(smart_skipped)}개 스킵 → LLM Hunter 대상: {len(llm_candidates)}/{len(filtered_codes)}개")
                    if skip_reasons_count:
                        logger.info(f"      Skip 사유: {skip_reasons_count}")
                    
                    # =============================================================
                    # Phase 1: Hunter LLM 호출 (Smart Skip 통과 종목만)
                    # =============================================================
                    with ThreadPoolExecutor(max_workers=hunter_max_workers) as executor:
                        future_to_code = {}
                        for code in llm_candidates:
                            info = candidate_stocks[code]
                            quant_result = quant_results[code]
                            payload = {'code': code, 'info': info}
                            future = executor.submit(
                                process_phase1_hunter_v5_task, 
                                payload, brain, quant_result, snapshot_cache, news_cache, archivist, feedback_context
                            )
                            future_to_code[future] = code
                        
                        for future in as_completed(future_to_code):
                            result = future.result()
                            if result:
                                phase1_results.append(result)
                                if not result['passed']:
                                    llm_decision_records[result['code']] = {
                                        'code': result['code'],
                                        'name': result['name'],
                                        'llm_score': result['hunter_score'],
                                        'llm_reason': result['hunter_reason'],
                                        'is_tradable': False,
                                        'approved': False,
                                        'hunter_score': result['hunter_score'],
                                        'llm_metadata': {'llm_grade': 'D', 'source': 'v5_hunter_reject'}
                                    }
                    
                    phase1_passed = [r for r in phase1_results if r['passed']]
                    logger.info(f"   ✅ v5 Hunter 통과: {len(phase1_passed)}/{len(llm_candidates)}개 (전체 대비 {len(phase1_passed)}/{len(filtered_codes)})")
                    
                    # Phase 2-3: Debate + Judge (상위 종목만)
                    PHASE2_MAX = int(os.getenv("SCOUT_PHASE2_MAX_ENTRIES", "50"))
                    if len(phase1_passed) > PHASE2_MAX:
                        phase1_passed_sorted = sorted(phase1_passed, key=lambda x: x['hunter_score'], reverse=True)
                        phase1_passed = phase1_passed_sorted[:PHASE2_MAX]
                    
                    if phase1_passed:
                        logger.info(f"\n   [Step 4] Debate + Judge (하이브리드 점수 결합)")
                        
                        with ThreadPoolExecutor(max_workers=judge_max_workers) as executor:
                            future_to_code = {}
                            
                            # Archivist 사용 (위에서 초기화됨)

                            for p1_result in phase1_passed:
                                future = executor.submit(
                                    process_phase23_judge_v5_task, 
                                    p1_result, brain, archivist, current_regime, feedback_context
                                )
                                future_to_code[future] = p1_result['code']
                            
                            for future in as_completed(future_to_code):
                                record = future.result()
                                if record:
                                    llm_decision_records[record['code']] = record
                                    if record.get('approved'):
                                        final_approved_list.append(_record_to_watchlist_entry(record))
                    
                    logger.info(f"   ✅ v5 최종 승인: {len([r for r in llm_decision_records.values() if r.get('approved')])}개")
                    
                    # 쿼터제 적용
                    MAX_WATCHLIST_SIZE = 15
                    if len(final_approved_list) > MAX_WATCHLIST_SIZE:
                        final_approved_list_sorted = sorted(
                            final_approved_list,
                            key=lambda x: x.get('llm_score', 0),
                            reverse=True
                        )
                        final_approved_list = final_approved_list_sorted[:MAX_WATCHLIST_SIZE]
                    
                    logger.info(f"\n   🏁 Scout v1.0 완료: {len(final_approved_list)}개 종목 선정")
                    
                except Exception as e:
                    logger.error(f"❌ Scout v1.0 실행 오류: {e}", exc_info=True)
                    # v5 실패 시 빈 리스트로 계속 진행 (v4 폴백 제거됨)
                    final_approved_list = []
                    if '0001' in candidate_stocks:
                        final_approved_list.append({'code': '0001', 'name': 'KOSPI', 'is_tradable': False})
            else:
                # 하이브리드 스코어링 비활성화 시 기본 처리
                logger.warning("⚠️ Hybrid Scoring 비활성화됨. 기본 Watchlist만 저장합니다.")
                final_approved_list = []
                if '0001' in candidate_stocks:
                    final_approved_list.append({'code': '0001', 'name': 'KOSPI', 'is_tradable': False})
            
            # 공통 Phase 3: 최종 Watchlist 저장
            logger.info(f"--- [Phase 3] 최종 Watchlist {len(final_approved_list)}개 저장 ---")
            database.save_to_watchlist(session, final_approved_list)
            # Watchlist 히스토리 저장 (백테스트 재현용 스냅샷)
            snapshot_date = datetime.now().strftime('%Y-%m-%d')
            database.save_to_watchlist_history(session, final_approved_list, snapshot_date=snapshot_date)
            
            # Hot Watchlist 저장 (Price Monitor WebSocket 구독용)
            # 시장 국면별 score_threshold 계산
            recon_score_by_regime = {
                "STRONG_BULL": 58,
                "BULL": 62,
                "SIDEWAYS": 65,
                "BEAR": 70,
            }
            hot_score_threshold = recon_score_by_regime.get(
                current_regime if 'current_regime' in locals() else 'SIDEWAYS', 
                65
            )
            hot_regime = current_regime if 'current_regime' in locals() else 'UNKNOWN'
            
            # LLM Score 기준 이상인 종목만 Hot Watchlist로 저장
            hot_candidates = [
                s for s in final_approved_list 
                if s.get('llm_score', 0) >= hot_score_threshold and s.get('code') != '0001'
            ]
            # LLM Score 내림차순 정렬 + 상위 15개 제한
            hot_candidates = sorted(hot_candidates, key=lambda x: x.get('llm_score', 0), reverse=True)[:15]
            
            save_hot_watchlist(
                stocks=hot_candidates,
                market_regime=hot_regime,
                score_threshold=hot_score_threshold
            )
            
            with ThreadPoolExecutor(max_workers=10) as executor:
                if hasattr(kis_api, 'API_CALL_DELAY'):
                    future_to_data = {
                        executor.submit(fetch_kis_data_task, s, kis_api): (time.sleep(kis_api.API_CALL_DELAY), s)[1]
                        for s in final_approved_list 
                    }
                else:
                    future_to_data = {
                        executor.submit(fetch_kis_data_task, s, kis_api): s
                        for s in final_approved_list 
                    }
                
                all_daily = []
                all_fund = []
                for future in as_completed(future_to_data):
                    d, f = future.result()
                    if d: all_daily.extend(d)
                    if f: all_fund.append(f)
            
            if all_daily: database.save_all_daily_prices(session, all_daily)
            if all_fund: database.update_all_stock_fundamentals(session, all_fund)
            
            # Phase 3-A: 재무 데이터 (네이버 크롤링)
            tradable_codes = [s['code'] for s in final_approved_list if s.get('is_tradable', True)]
            if tradable_codes:
                batch_update_watchlist_financial_data(session, tradable_codes)
            
            # Redis 최종 상태 업데이트 - 완료
            update_pipeline_status(
                phase=3, phase_name="Final Judge", status="completed",
                progress=100,
                total_candidates=len(candidate_stocks) if 'candidate_stocks' in locals() else 0,
                passed_phase1=len(phase1_passed) if 'phase1_passed' in locals() else 0,
                passed_phase2=len(phase1_passed) if 'phase1_passed' in locals() else 0,
                final_selected=len(final_approved_list)
            )
            
            # Redis 결과 저장 (Dashboard에서 조회용)
            pipeline_results = [
                {
                    "stock_code": s.get('code'),
                    "stock_name": s.get('name'),
                    "grade": s.get('llm_metadata', {}).get('llm_grade', 'C'),
                    "final_score": s.get('llm_score', 0),
                    "selected": s.get('approved', False),
                    "judge_reason": s.get('llm_reason', ''),
                }
                for s in final_approved_list
            ]
            save_pipeline_results(pipeline_results)
            logger.info(f"   (Redis) Dashboard용 결과 저장 완료 ({len(pipeline_results)}개)")

    except Exception as e:
        logger.critical(f"❌ 'Scout Job' 실행 중 오류: {e}", exc_info=True)
        # 오류 시 Redis 상태 업데이트
        update_pipeline_status(phase=0, phase_name="Error", status="error")
            
    logger.info(f"--- 🤖 'Scout Job' 종료 (소요: {time.time() - start_time:.2f}초) ---")

if __name__ == "__main__":
    main()
