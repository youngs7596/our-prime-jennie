
"""
Real Scout Pipeline Backfill Script
===================================
실제 Scout 파이프라인(Hunter->Debate->Judge)을 활용한 과거 데이터 백필 스크립트.
시스템 시간을 속이는 대신, 주요 데이터 Provider 함수들을 Monkey Patching하여
과거 시점의 데이터를 반환하도록 조작합니다.

대상 기간: 2024-01-02 ~ 현재 (필요에 따라 조정)
데이터 소스:
  - 가격/거래량: DB (STOCK_DAILY_PRICES_3Y)
  - 뉴스: DB (NEWS_SENTIMENT)
  - 네이버 크롤링: DB 기반 시총 상위로 대체
"""

import sys
import os
import time
import logging
import hashlib
from datetime import datetime, timedelta, date
from functools import partial
from concurrent.futures import ThreadPoolExecutor

# 프로젝트 루트 경로 설정
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(override=True)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('backfill_scout.log')
    ]
)
logger = logging.getLogger("BackfillScout")

# ============================================================================
# Mock Modules for Backfill Environment
# ============================================================================
from unittest.mock import MagicMock
import types



# 2. Mock 'shared.kis.auth_distributed' (If missing)
mock_auth_dist = types.ModuleType("shared.kis.auth_distributed")
mock_auth_dist.DistributedKISAuth = MagicMock()
sys.modules["shared.kis.auth_distributed"] = mock_auth_dist

# 3. Mock 'shared.fact_checker' (Missing module)
mock_fact_checker = types.ModuleType("shared.fact_checker")
mock_fact_checker.get_fact_checker = MagicMock(return_value=MagicMock(check_facts=MagicMock(return_value={"is_valid": True})))
sys.modules["shared.fact_checker"] = mock_fact_checker

# 4. Mock 'chromadb' (If missing)
mock_chromadb = types.ModuleType("chromadb")
mock_chromadb.HttpClient = MagicMock()
sys.modules["chromadb"] = mock_chromadb

# 5. Mock 'langchain_chroma' (If missing)
mock_lc_chroma = types.ModuleType("langchain_chroma")
mock_lc_chroma.Chroma = MagicMock()
sys.modules["langchain_chroma"] = mock_lc_chroma

# 6. Mock 'langchain_google_genai' (If missing)
mock_lc_genai = types.ModuleType("langchain_google_genai")
mock_lc_genai.GoogleGenerativeAIEmbeddings = MagicMock()
sys.modules["langchain_google_genai"] = mock_lc_genai

# 필수 모듈 로드
import shared.database as database
from shared.db.connection import session_scope, ensure_engine_initialized
from shared.llm import JennieBrain
import pandas as pd # pandas import 추가 (MockKISClient에서 사용)
from shared.database.trading import save_to_watchlist_history
from sqlalchemy import text

# import services.scout_job.scout as scout_main
# import services.scout_job.scout_pipeline as scout_pipeline
# import services.scout_job.scout_universe as scout_universe
# import services.scout_job.scout_cache as scout_cache

# Add services/scout-job to path directly
scout_job_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "services", "scout-job")
sys.path.append(scout_job_path)

import scout as scout_main
import scout_pipeline
import scout_universe
import scout_cache

# ============================================================================
# [Mock] KIS API (DB 기반)
# ============================================================================
class MockKISClient:
    def __init__(self, target_date):
        self.target_date = target_date
        self.API_CALL_DELAY = 0.0

    def get_stock_snapshot(self, code):
        """DB에서 해당 날짜의 종가, 시가총액(추정) 등을 반환"""
        original_get_daily_prices = None
        original_get_dynamic = None
        original_analyze_sector = None
        original_fetch_news = None
        try:
            with session_scope() as session:
                # 1. 가격 데이터 조회
                logger.info(f"[DEBUG-KIS] Fetching snapshot for {code} on {self.target_date}")
                df = database.get_daily_prices(session, code, limit=1, end_date=self.target_date)
                if df.empty:
                    logger.warning(f"[DEBUG-KIS] Price df empty for {code} on {self.target_date}")
                    return None
                
                row = df.iloc[0]
                price = float(row['CLOSE_PRICE'])
                
                # 2. 마스터 정보 조회 (이름, 상장주식수 등)
                # 재무제표 테이블 조회 시도
                # STOCK_FUNDAMENTALS (STOCK_CODE, TRADE_DATE, PER, PBR...)
                # [Fix] 백필 초기 구간 데이터 부재 시, 가장 최신(미래) 데이터라도 가져오도록 Fallback
                from sqlalchemy import text
                fund_query = """
                    SELECT PER, PBR, MARKET_CAP, ROE 
                    FROM STOCK_FUNDAMENTALS
                    WHERE STOCK_CODE = :code AND TRADE_DATE <= :date
                    ORDER BY TRADE_DATE DESC LIMIT 1
                """
                fund_res = session.execute(text(fund_query), {"code": code, "date": self.target_date}).fetchone()
                
                # [Fallback] 데이터 없으면 미래 데이터라도 조회 (12/26 데이터 등)
                if not fund_res:
                    fund_fallback_query = """
                        SELECT PER, PBR, MARKET_CAP, ROE 
                        FROM STOCK_FUNDAMENTALS
                        WHERE STOCK_CODE = :code
                        ORDER BY TRADE_DATE DESC LIMIT 1
                    """
                    fund_res = session.execute(text(fund_fallback_query), {"code": code}).fetchone()
                    if fund_res:
                        logger.warning(f"   ⚠️ [Fallback] {code} {self.target_date} 재무 데이터 없음 -> 최신 데이터 사용")
                
                per = float(fund_res[0]) if fund_res and fund_res[0] else 0.0
                pbr = float(fund_res[1]) if fund_res and fund_res[1] else 0.0
                market_cap = int(fund_res[2]) if fund_res and fund_res[2] else 0
                
                if market_cap == 0 and price > 0:
                    # 시총 정보가 없으면 가격만이라도 반환 (크롤링 대체 시 필수)
                    market_cap = price * 1000000 # 임의값 (정렬용)

                # [Fix] 외인순매수 (foreign_net_buy) 추가
                foreign_net_buy = 0.0
                try:
                    inv_query = """
                        SELECT FOREIGN_NET_BUY
                        FROM STOCK_INVESTOR_TRADING
                        WHERE STOCK_CODE = :code AND TRADE_DATE <= :date
                        ORDER BY TRADE_DATE DESC LIMIT 1
                    """
                    inv_res = session.execute(text(inv_query), {"code": code, "date": self.target_date}).fetchone()
                    if inv_res and inv_res[0]:
                        # [Fix] FOREIGN_NET_BUY는 금액(원)이므로, 주 수량으로 변환 (금액 / 주가)
                        # QuantScorer는 주 수량을 기대하고 avg_volume(주)으로 나눠서 비율 계산함
                        net_buy_amount = float(inv_res[0])  # 금액(원)
                        if price > 0:
                            foreign_net_buy = int(net_buy_amount / price)  # 주 수량으로 변환
                        else:
                            foreign_net_buy = 0
                    else:
                         # Fallback for Investor Trading if missing for target date
                        inv_fallback_query = """
                            SELECT FOREIGN_NET_BUY
                            FROM STOCK_INVESTOR_TRADING
                            WHERE STOCK_CODE = :code
                            ORDER BY TRADE_DATE DESC LIMIT 1
                        """
                        inv_fb_res = session.execute(text(inv_fallback_query), {"code": code}).fetchone()
                        if inv_fb_res and inv_fb_res[0]:
                             net_buy_amount = float(inv_fb_res[0])  # 금액(원)
                             if price > 0:
                                 foreign_net_buy = int(net_buy_amount / price)  # 주 수량으로 변환
                             else:
                                 foreign_net_buy = 0
                except Exception as e:
                    logger.warning(f"   ⚠️ [Mock] {code} 외인수급 조회 실패: {e}")

                return {
                    "price": price,
                    "diff": 0.0, # 전일비 계산 생략
                    "rate": 0.0,
                    "vol": int(row['VOLUME']),
                    "per": per,
                    "pbr": pbr,
                    "market_cap": market_cap,
                    "roe": float(fund_res[3]) if fund_res and fund_res[3] else 0.0,
                    "sales_growth": 0.0, # 데이터 없음
                    "eps_growth": 0.0, # 데이터 없음
                    "operating_margin": 0.0, # 데이터 없음
                    "foreign_net_buy": foreign_net_buy, # 추가된 필드
                }
        except Exception as e:
            logger.error(f"[DEBUG-KIS] Start Snapshot Failed for {code}: {e}", exc_info=True)
            return None

    def get_market_data(self):
        return self # Mock self for chaining

    def get_investor_trend(self, code, start_date=None, end_date=None):
        """DB에서 투자자 동향 조회"""
        try:
            # [Fix] STOCK_INVESTOR_TRADING 테이블 직접 조회
            # shared.database.market.get_investor_trading을 쓰지 않고 직접 쿼리 (테이블명 명시)
            from sqlalchemy import text
            trends = []
            
            with session_scope() as session:
                query = text("""
                    SELECT TRADE_DATE, CLOSE_PRICE, FOREIGN_NET_BUY, INSTITUTION_NET_BUY, INDIVIDUAL_NET_BUY
                    FROM STOCK_INVESTOR_TRADING
                    WHERE STOCK_CODE = :code AND TRADE_DATE <= :date
                    ORDER BY TRADE_DATE DESC
                    LIMIT 30
                """)
                rows = session.execute(query, {"code": code, "date": self.target_date}).fetchall()
                
                if not rows:
                    return []
                
                # 날짜 오름차순 정렬을 위해 리스트업
                temp_list = []
                for row in rows:
                    temp_list.append({
                        'date': row[0].strftime('%Y%m%d'),
                        'start_price': 0,
                        'close_price': row[1],
                        'foreigner_net_buy': int(row[2]),
                        'institution_net_buy': int(row[3]),
                        'individual_net_buy': int(row[4]),
                    })
                
                # 역순(최신순)으로 가져왔으므로 다시 오름차순 정렬
                trends = sorted(temp_list, key=lambda x: x['date'])
                return trends
        except Exception as e:
            logger.error(f"[Mock] get_investor_trend failed: {e}")
            return []

# ============================================================================
# [Mock] Universe Selection (DB 기반)
# ============================================================================
def mock_get_dynamic_blue_chips(limit=200, target_date=None, session=None):
    """
    과거 시점의 시가총액 상위 종목을 DB에서 조회
    (FUNDAMENTALS 테이블 활용)
    """
    if not session or not target_date:
        return []
        
    from sqlalchemy import text
    try:
        # 해당 날짜(또는 직전)의 시총 상위 조회
        # 1. Try Fundamentals First
        universe_query = """
            SELECT F.STOCK_CODE, M.STOCK_NAME, F.MARKET_CAP
            FROM STOCK_FUNDAMENTALS F
            JOIN STOCK_MASTER M ON F.STOCK_CODE = M.STOCK_CODE COLLATE utf8mb4_general_ci
            WHERE F.TRADE_DATE = (
                SELECT MAX(TRADE_DATE) 
                FROM STOCK_FUNDAMENTALS sub
                WHERE sub.STOCK_CODE = F.STOCK_CODE AND sub.TRADE_DATE <= :date
            )
            ORDER BY F.MARKET_CAP DESC
            LIMIT :limit
        """
        # [Fix] 위 쿼리에서 결과가 없으면(초기 데이터 부재), 미래 데이터(전체 Max)라도 써서 유니버스 구성
        # 이를 위해 Python 레벨에서 로직 분기
        rows = session.execute(text(universe_query), {"date": target_date, "limit": limit}).fetchall()
        
        # [Fix 2] 데이터가 아예 없거나, 너무 적으면(50% 미만) Fallback 트리거
        if not rows or len(rows) < limit * 0.5:
            logger.info(f"   ⚠️ {target_date} 유니버스 데이터 부족({len(rows)}개) -> 최신(미래) 펀더멘털로 Fallback")
            fallback_univ_query = """
                SELECT F.STOCK_CODE, M.STOCK_NAME, F.MARKET_CAP
                FROM STOCK_FUNDAMENTALS F
                JOIN STOCK_MASTER M ON F.STOCK_CODE = M.STOCK_CODE COLLATE utf8mb4_general_ci
                WHERE F.TRADE_DATE = (
                    SELECT MAX(TRADE_DATE) 
                    FROM STOCK_FUNDAMENTALS sub 
                    WHERE sub.STOCK_CODE = F.STOCK_CODE
                )
                ORDER BY F.MARKET_CAP DESC
                LIMIT :limit
            """
            rows = session.execute(text(fallback_univ_query), {"limit": limit}).fetchall()
        
        # 2. Fallback to Price * Shares if no fundamentals OR still insufficient
        if not rows or len(rows) < limit * 0.5:
            logger.info(f"   (Mock) Fundamentals insufficient ({len(rows) if rows else 0}개) for {target_date}, trying fallback (Price * Shares)...")
            # 3. Prices Range
            min_p = session.execute(text("SELECT MIN(PRICE_DATE) FROM STOCK_DAILY_PRICES_3Y")).scalar()
            max_p = session.execute(text("SELECT MAX(PRICE_DATE) FROM STOCK_DAILY_PRICES_3Y")).scalar()
            logger.info(f"[DEBUG] STOCK_DAILY_PRICES_3Y Range: {min_p} ~ {max_p}")

            min_p_main = session.execute(text("SELECT MIN(PRICE_DATE) FROM STOCK_DAILY_PRICES")).scalar()
            max_p_main = session.execute(text("SELECT MAX(PRICE_DATE) FROM STOCK_DAILY_PRICES")).scalar()
            logger.info(f"[DEBUG] STOCK_DAILY_PRICES (Main) Range: {min_p_main} ~ {max_p_main}")
            fallback_query = """
                SELECT P.STOCK_CODE, M.STOCK_NAME, (P.CLOSE_PRICE * M.LISTED_SHARES) as VAL_MCAP
                FROM STOCK_DAILY_PRICES_3Y P
                JOIN STOCK_MASTER M ON P.STOCK_CODE = M.STOCK_CODE COLLATE utf8mb4_general_ci
                WHERE P.PRICE_DATE = :date
                AND M.LISTED_SHARES > 0
                ORDER BY VAL_MCAP DESC
                LIMIT :limit
            """
            rows = session.execute(text(fallback_query), {"date": target_date, "limit": limit}).fetchall()

        result = []
        for i, row in enumerate(rows):
            result.append({
                "code": row[0],
                "name": row[1],
                "price": 0, # 가격 조회 비용 절감을 위해 0 처리 (필요시 별도 조회)
                "change_pct": 0,
                "sector": "KOSPI", # Default sector as M.SECTOR is removed
                "market_cap": row[2],
                "rank": i + 1
            })
        if result:
            logger.info(f"   (Mock) Selected {len(result)} stocks from Mock Universe.")
        return result
    except Exception as e:
        logger.warning(f"Mock BlueChips Failed: {e}")
        return []

def mock_analyze_sector_momentum(kis_api, session, watchlist_snapshot=None):
    """
    DB 데이터를 이용하여 섹터 모멘텀 계산
    (단순하게 해당 일자의 Top Stocks 등락률 평균으로 계산)
    """
    return {} # 일단 비워둠 (복잡도 감소)

# ============================================================================
# [Mock] News Provider (DB 기반)
# ============================================================================
def mock_fetch_stock_news(vectorstore, stock_code, stock_name, k=3, target_date=None, session=None):
    """
    DB (NEWS_SENTIMENT)에서 해당 날짜 이전의 최신 뉴스를 조회
    """
    if not session or not target_date:
        return "뉴스 데이터 없음"
        
    from sqlalchemy import text
    try:
        # 해당 종목의 target_date 및 그 전 3일치 뉴스 조회
        start_date = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=3)).strftime("%Y-%m-%d")
        
        query = text("""
            SELECT NEWS_TITLE, PUBLISHED_AT
            FROM NEWS_SENTIMENT
            WHERE STOCK_CODE = :code 
              AND PUBLISHED_AT BETWEEN :start_date AND :end_date
            ORDER BY PUBLISHED_AT DESC
            LIMIT :k
        """)
        rows = session.execute(query, {
            "code": stock_code, 
            "start_date": start_date, 
            "end_date": target_date + " 23:59:59",
            "k": k
        }).fetchall()
        
        if not rows:
            return "최근 관련 뉴스 없음"
            
        news_items = []
        for i, row in enumerate(rows, 1):
            title = row[0]
            # date_str = row[1].strftime("%Y-%m-%d")
            news_items.append(f"[뉴스{i}] {title}")
            
        return " | ".join(news_items)
        
    except Exception as e:
        return f"뉴스 조회 오류: {str(e)}"

# ============================================================================
# Main Execution Logic
# ============================================================================

def _force_local_llm_gateway():
    """백필 비용 절감을 위해 Ollama Gateway 강제 사용 설정"""
    os.environ["TIER_FAST_PROVIDER"] = "ollama"
    os.environ["TIER_REASONING_PROVIDER"] = "ollama"
    os.environ["TIER_THINKING_PROVIDER"] = "ollama"
    
    # 모델 설정 (Gateway에 등록된 모델명 확인 필요, 여기선 gpt-oss:20b 등 사용 가정)
    # 실제 Gateway가 라우팅하므로 내부 모델명은 Gateway 설정에 따름
    os.environ["LOCAL_MODEL_REASONING"] = "gpt-oss:20b" 
    
    os.environ["USE_OLLAMA_GATEWAY"] = "true"
    os.environ["OLLAMA_GATEWAY_URL"] = "http://localhost:11500"
    logger.info("🔧 [Config] Ollama Gateway 강제 설정 완료 (비용 0원 모드)")

def _load_trading_days(session, start_date: date, end_date: date) -> list[date]:
    rows = session.execute(
        text(
            """
            SELECT DISTINCT PRICE_DATE
            FROM STOCK_DAILY_PRICES_3Y
            WHERE PRICE_DATE BETWEEN :start AND :end
            ORDER BY PRICE_DATE ASC
            """
        ),
        {"start": start_date, "end": end_date},
    ).fetchall()
    days = []
    for row in rows:
        value = row[0]
        if isinstance(value, datetime):
            days.append(value.date())
        else:
            days.append(pd.to_datetime(value).date())
    return days


def _watchlist_exists(session, target_date: str) -> bool:
    row = session.execute(
        text("SELECT 1 FROM WATCHLIST_HISTORY WHERE SNAPSHOT_DATE = :date LIMIT 1"),
        {"date": target_date},
    ).fetchone()
    return bool(row)


def run_backfill(
    start_date_str,
    end_date_str,
    use_local_llm=True,
    *,
    universe_size=200,
    quant_cutoff_ratio=0.6,
    max_llm_candidates=50,
    max_workers=1,
    sleep_seconds=1.0,
    skip_existing=False,
):
    """백필 메인 루프"""
    ensure_engine_initialized()
    
    # Remove Debug Block
    
    # 로컬 LLM 강제 설정
    if use_local_llm:
        _force_local_llm_gateway()
        
        # [Strict Mode] Cloud Fallback 원천 차단 (Monkey Patch)
        # JennieBrain의 Fallback 로직이 있는 메서드들을 덮어씌움
        logger.info("🔒 [Strict] Cloud Fallback 차단 패치 적용 (JennieBrain)")
        
        def safe_run_debate_session(self, stock_info, analysis_context="", hunter_score=0):
            # Fallback 없는 버전
            from shared.llm import LLMTier
            from shared.llm_prompts import build_debate_prompt
            
            provider = self._get_provider(LLMTier.REASONING)
            if provider is None: return "Debate Skipped (Model Error)"
            try:
                keywords = stock_info.get('dominant_keywords', [])
                prompt = build_debate_prompt(stock_info, hunter_score, keywords)
                chat_history = [{"role": "user", "content": prompt}]
                logger.info(f"[DEBUG] Starting Debate with provider: {provider}")
                result = provider.generate_chat(chat_history, temperature=0.7)
                if isinstance(result, dict):
                    return result.get('text') or result.get('content') or str(result)
                return str(result)
            except Exception as e:
                logger.error(f"❌ [Debate] Local LLM Failed (Fallback Blocked): {e}")
                return f"Debate Error: {e}"

        def safe_run_judge_scoring_v5(self, stock_info, debate_log, quant_context=None, feedback_context=None):
            # Fallback 없는 버전
            from shared.llm import LLMTier
            from shared.llm_prompts import build_judge_prompt_v5
            from shared.llm_constants import ANALYSIS_RESPONSE_SCHEMA

            # 1. Strategy Gate Check
            hunter_score = stock_info.get('hunter_score', 0)
            JUDGE_THRESHOLD = 70
            if hunter_score < JUDGE_THRESHOLD:
                # logger.info(f"🚫 [Gatekeeper] Judge Skipped. Hunter Score {hunter_score} < {JUDGE_THRESHOLD}")
                return {
                    'score': hunter_score, 
                    'grade': self._calculate_grade(hunter_score), 
                    'reason': f"Hunter({hunter_score}점) < TIER1 기준({JUDGE_THRESHOLD})"
                }

            provider = self._get_provider(LLMTier.THINKING)
            if provider is None: return {'score': 0, 'grade': 'D', 'reason': 'Provider Error'}
            try:
                prompt = build_judge_prompt_v5(stock_info, debate_log, quant_context, feedback_context)
                logger.info(f"[DEBUG] Judge Scoring with provider: {provider}")
                result = provider.generate_json(prompt, ANALYSIS_RESPONSE_SCHEMA, temperature=0.1)
                
                # 등급 강제 산정
                raw_score = result.get('score', 0)
                calculated_grade = self._calculate_grade(raw_score)
                result['grade'] = calculated_grade
                
                return result
            except Exception as e:
                logger.error(f"❌ [Judge] Local LLM Failed (Fallback Blocked): {e}")
                return {'score': 0, 'grade': 'D', 'reason': f"오류: {e}"}

        def safe_get_jennies_analysis_score_v5(self, stock_info, quant_context=None, feedback_context=None):
            # Fallback 없는 버전
            from shared.llm import LLMTier # ensure import
            provider = self._get_provider(LLMTier.REASONING)
            if provider is None: 
                logger.error(f"❌ [Hunter] Provider is None for TIER {LLMTier.REASONING}")
                return {'score': 0, 'grade': 'D', 'reason': 'Provider Error'}
            try:
                # prompt = scout_main.build_hunter_prompt_v5(stock_info, quant_context, feedback_context)
                from shared.llm_prompts import build_hunter_prompt_v5
                from shared.llm_constants import ANALYSIS_RESPONSE_SCHEMA
                
                prompt = build_hunter_prompt_v5(stock_info, quant_context, feedback_context)
                logger.info(f"[DEBUG] Generating JSON with provider: {provider}")
                result = provider.generate_json(prompt, ANALYSIS_RESPONSE_SCHEMA, temperature=0.2)
                return result
            except Exception as e:
                logger.error(f"❌ [Hunter] Local LLM Failed (Fallback Blocked): {e}")
                return {'score': 0, 'grade': 'F', 'reason': f"Local Error: {e}"}

        # Apply Patches
        JennieBrain.run_debate_session = safe_run_debate_session
        JennieBrain.run_judge_scoring_v5 = safe_run_judge_scoring_v5
        JennieBrain.get_jennies_analysis_score_v5 = safe_get_jennies_analysis_score_v5
    
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
    
    brain = JennieBrain(project_id="local", gemini_api_key_secret="SECRET_ID_GEMINI_API_KEY")
    with session_scope() as session:
        trading_days = _load_trading_days(session, start_date, end_date)

    for current_date in trading_days:
        target_date_str = current_date.strftime("%Y-%m-%d")
        logger.info(f"\n{'='*60}\n🚀 Backfill Step: {target_date_str}\n{'='*60}")

        original_get_daily_prices = None
        original_get_dynamic = None
        original_analyze_sector = None
        original_fetch_news = None

        try:
            with session_scope() as session:
                if skip_existing and _watchlist_exists(session, target_date_str):
                    logger.info(f"⏭️ {target_date_str}: 이미 백필됨 (스킵)")
                    continue

                # 1. Environment & Mock Setup
                kis_api = MockKISClient(target_date_str)
                
                # Monkey Patching
                original_get_daily_prices = database.get_daily_prices
                original_get_dynamic = scout_universe.get_dynamic_blue_chips
                original_analyze_sector = scout_universe.analyze_sector_momentum
                original_fetch_news = scout_main.fetch_stock_news_from_chroma
                
                # Apply Patches
                database.get_daily_prices = partial(original_get_daily_prices, end_date=target_date_str)
                scout_universe.get_dynamic_blue_chips = partial(mock_get_dynamic_blue_chips, target_date=target_date_str, session=session)
                scout_universe.analyze_sector_momentum = partial(mock_analyze_sector_momentum)
                scout_main.fetch_stock_news_from_chroma = partial(mock_fetch_stock_news, target_date=target_date_str, session=session)
                
                # Force Skip Disabled
                scout_pipeline.should_skip_hunter = MagicMock(return_value=False)

                # --- Scout Main Logic Simulation (Simplified) ---
                
                # 1. Candidate Selection using Mocked Universe
                candidate_stocks = {}
                for stock in scout_universe.get_dynamic_blue_chips(limit=universe_size):
                    candidate_stocks[stock['code']] = {
                        'name': stock['name'],
                        'sector': stock.get('sector'),
                        'reasons': ['KOSPI 시총 상위']
                    }
                    
                # 2. Enrich & Prefetch
                # Mock snapshot logic needs to be manually injected here because scout.py uses kis_api directly
                # scout.py's prefetch_all_data uses the kis_api defined in main() so we pass our mock
                snapshot_cache, news_cache = scout_main.prefetch_all_data(candidate_stocks, kis_api, vectorstore=None)

                # 3. Pipeline Execution (Phase 1 -> Phase 2)
                # Quant Scoring
                from shared.hybrid_scoring import QuantScorer
                # 시장 레짐 계산 (KOSPI 기준)
                from shared.market_regime import MarketRegimeDetector
                regime_detector = MarketRegimeDetector()
                kospi_prices = database.get_daily_prices(session, "0001", limit=60)
                market_regime = "SIDEWAYS"
                if not kospi_prices.empty:
                    close_df = kospi_prices[["CLOSE_PRICE"]]
                    current_price = float(close_df["CLOSE_PRICE"].iloc[-1])
                    market_regime, _ = regime_detector.detect_regime(close_df, current_price, quiet=True)

                quant_scorer = QuantScorer(session, market_regime=market_regime)
                
                quant_results = {}
                kospi_prices = database.get_daily_prices(session, "0001", limit=60)
                
                for code, info in candidate_stocks.items():
                    stock_info = {'code': code, 'info': info, 'snapshot': snapshot_cache.get(code)}
                    quant_results[code] = scout_pipeline.process_quant_scoring_task(
                        stock_info, quant_scorer, session, kospi_prices
                    )
                    
                # Filter (Top 40%)
                filtered_results = quant_scorer.filter_candidates(
                    list(quant_results.values()),
                    cutoff_ratio=quant_cutoff_ratio,
                )
                filtered_results = sorted(filtered_results, key=lambda r: r.total_score, reverse=True)
                if max_llm_candidates and len(filtered_results) > max_llm_candidates:
                    filtered_results = filtered_results[:max_llm_candidates]
                filtered_codes = [r.stock_code for r in filtered_results]

                # LLM Analysis
                final_candidates = []
                logger.info(f"[DEBUG] Starting LLM Phase for {len(filtered_codes)} candidates")

                # Batch processing to prevent OOM
                # Use ThreadPool with Mock objects
                def process_llm(code):
                    try:
                        logger.info(f"[DEBUG] Processing {code}...")
                        info = candidate_stocks[code]
                        quant_result = quant_results[code]

                        # Phase 1 Hunter
                        p1_res = scout_pipeline.process_phase1_hunter_v5_task(
                            {'code': code, 'info': info}, brain, quant_result, snapshot_cache, news_cache, archivist=None
                        )
                        logger.info(f"[DEBUG] {code} Phase 1 Result: {p1_res.get('passed')}")

                        if p1_res['passed']:
                            # Phase 2 Debate/Judge
                            p2_res = scout_pipeline.process_phase23_judge_v5_task(
                                p1_res, brain, archivist=None
                            )
                            return p2_res
                        return None
                    except Exception as e:
                        logger.error(f"[DEBUG] process_llm failed for {code}: {e}", exc_info=True)
                        return None

                # Limit concurrency for LLM stability
                if max_workers <= 1:
                    for code in filtered_codes:
                        res = process_llm(code)
                        if res:
                            final_candidates.append(res)
                else:
                    with ThreadPoolExecutor(max_workers=max_workers) as executor:
                        futures = [executor.submit(process_llm, code) for code in filtered_codes]
                        for future in futures:
                            res = future.result()
                            if res:
                                final_candidates.append(res)
                                
                    # 4. Save to History
                    if final_candidates:
                        save_to_watchlist_history(session, final_candidates, snapshot_date=target_date_str)
                        logger.info(f"💾 {target_date_str}: {len(final_candidates)}개 종목 히스토리 저장 완료")
                    else:
                        logger.info(f"ℹ️ {target_date_str}: 선정된 종목 없음")

        except Exception as e:
            logger.error(f"❌ {target_date_str} 처리 중 오류: {e}", exc_info=True)
        finally:
            # Restore Patches (only if patched)
            if original_get_daily_prices:
                database.get_daily_prices = original_get_daily_prices
            if original_get_dynamic:
                scout_universe.get_dynamic_blue_chips = original_get_dynamic
            if original_analyze_sector:
                scout_universe.analyze_sector_momentum = original_analyze_sector
            if original_fetch_news:
                scout_main.fetch_stock_news_from_chroma = original_fetch_news

        time.sleep(sleep_seconds) # Cool down

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=str, required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--cloud", action="store_true", help="Use Cloud LLM instead of Local Gateway")
    parser.add_argument("--universe", type=int, default=200, help="Universe size (default: 200)")
    parser.add_argument("--quant-cutoff", type=float, default=0.6, help="Quant cutoff ratio (default: 0.6)")
    parser.add_argument("--max-llm-candidates", type=int, default=50, help="Max LLM candidates per day")
    parser.add_argument("--max-workers", type=int, default=1, help="LLM parallel workers (default: 1)")
    parser.add_argument("--sleep", type=float, default=1.0, help="Sleep seconds between days")
    parser.add_argument("--skip-existing", action="store_true", help="Skip dates already in WATCHLIST_HISTORY")
    args = parser.parse_args()
    
    run_backfill(
        args.start,
        args.end,
        use_local_llm=not args.cloud,
        universe_size=args.universe,
        quant_cutoff_ratio=args.quant_cutoff,
        max_llm_candidates=args.max_llm_candidates,
        max_workers=args.max_workers,
        sleep_seconds=args.sleep,
        skip_existing=args.skip_existing,
    )
