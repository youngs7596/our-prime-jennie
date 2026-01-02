#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# crawler_job.py
# Version: v1.0
# 작업 LLM: Claude Opus 4.5
# Crawler Job - Cloud Scheduler(HTTP)에 의해 10분마다 실행되는 스크립트
# KOSPI 200 전체 뉴스 수집 (WatchList 의존성 제거)
# 경쟁사 수혜 분석 연동

from concurrent.futures import ThreadPoolExecutor, as_completed
import time
# import chromadb  # Lazy import로 변경 (초기화 시간 단축)
import sys
import json
import urllib.parse
import feedparser # type: ignore
import logging
import os 
import calendar
import warnings
from dotenv import load_dotenv 
from datetime import datetime, timedelta, timezone

# FinanceDataReader for KOSPI 200 Universe
try:
    import FinanceDataReader as fdr
    FDR_AVAILABLE = True
except ImportError:
    FDR_AVAILABLE = False

# 'youngs75_jennie' 패키지를 찾기 위해 프로젝트 루트 폴더를 Python 경로에 추가
# Dockerfile에서 /app/crawler_job.py로 복사되므로, /app이 프로젝트 루트
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.append(PROJECT_ROOT)

# ==============================================================================
# 로거(Logger) 설정
# ==============================================================================
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

try:
    import shared.auth as auth
    import shared.database as database
    from shared.llm import JennieBrain # 감성 분석을 위한 JennieBrain 임포트
    from shared.db.connection import session_scope, ensure_engine_initialized
    from shared.db.models import WatchList as WatchListModel
    from shared.gemini import ensure_gemini_api_key
    # 경쟁사 수혜 분석 모듈
    from shared.news_classifier import NewsClassifier, get_classifier
    from shared.hybrid_scoring.competitor_analyzer import CompetitorAnalyzer
    logger.info("✅ 'shared' 패키지 모듈 import 성공")
except ImportError as e: # type: ignore
    logger.error(f"🚨 'shared' 공용 패키지를 찾을 수 없습니다! (오류: {e})")
    auth = None
    database = None
    JennieBrain = None
    ensure_gemini_api_key = None
    NewsClassifier = None
    get_classifier = None
    CompetitorAnalyzer = None
except Exception as e:
    logger.error(f"🚨 'shared' 패키지 import 중 예상치 못한 오류 발생: {e}", exc_info=True)
    auth = None
    database = None
    JennieBrain = None
    ensure_gemini_api_key = None
    NewsClassifier = None
    get_classifier = None
    CompetitorAnalyzer = None

from langchain_core.documents import Document
from langchain_chroma import Chroma
# [Cost Optimization] Cloud Embedding -> Local Embedding
# langchain_google_genai -> langchain_huggingface
try:
    from langchain_huggingface import HuggingFaceEmbeddings
    LOCAL_EMBEDDINGS_AVAILABLE = True
except ImportError:
    LOCAL_EMBEDDINGS_AVAILABLE = False
    logger.warning("⚠️ langchain_huggingface not available, falling back to Cloud Embeddings")
    from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

# ==============================================================================
# 1. 전역 설정 (Constants)
# ==============================================================================

# Chroma 서버
CHROMA_SERVER_HOST = os.getenv("CHROMA_SERVER_HOST", "10.178.0.2") 
CHROMA_SERVER_PORT = 8000
COLLECTION_NAME = "rag_stock_data"

# RAG 설정
DATA_TTL_DAYS = 7
VERTEX_AI_BATCH_SIZE = 10
MAX_SENTIMENT_DOCS_PER_RUN = int(os.getenv("MAX_SENTIMENT_DOCS_PER_RUN", "40"))
SENTIMENT_COOLDOWN_SECONDS = float(os.getenv("SENTIMENT_COOLDOWN_SECONDS", "0.2"))

# --- 🔽 '일반 경제' RSS 피드 🔽 ---
GENERAL_RSS_FEEDS = [
    {"source_name": "Maeil Business (Economy)", "url": "https://www.mk.co.kr/rss/50000001/"},
    {"source_name": "Maeil Business (Stock)", "url": "https://www.mk.co.kr/rss/50100001/"},
    {"source_name": "Investing.com (News)", "url": "https://kr.investing.com/rss/news.rss"}
]

# ==============================================================================
# LangChain, Chroma 클라이언트 초기화
# ==============================================================================

# ==============================================================================
# 전역 변수 (지연 초기화)
# ==============================================================================

# 환경 변수 로드 (모듈 임포트 시)
load_dotenv()

GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID")
# Oracle/OCI 관련 설정은 더 이상 사용하지 않습니다. (MariaDB + SQLAlchemy 단일화)

# 지연 초기화를 위한 전역 변수 (None으로 시작)
embeddings = None
text_splitter = None
db_client = None
vectorstore = None
jennie_brain = None # JennieBrain 인스턴스
classifier = None # NewsClassifier 인스턴스 (Cost saving)

def initialize_services():
    """
    LangChain 및 ChromaDB 서비스를 초기화합니다.
    run_collection_job() 실행 시에만 호출됩니다.
    """
    global embeddings, text_splitter, db_client, vectorstore, jennie_brain, classifier
    
    # SQLAlchemy 엔진 초기화 (session_scope 사용 전에 필수)
    try:
        ensure_engine_initialized()
        logger.info("✅ SQLAlchemy 엔진 초기화 완료")
    except Exception as e:
        logger.warning(f"⚠️ SQLAlchemy 엔진 초기화 실패: {e}")
    
    logger.info("... [RAG Crawler v10.0] LangChain 및 AI 컴포넌트 초기화 시작 ...")
    try:
        # [Cost Optimization] Local Embeddings 사용 (Cloud API 비용 ₩0)
        if LOCAL_EMBEDDINGS_AVAILABLE:
            logger.info("="*60)
            logger.info("🏠 [LOCAL] Embedding 모델 로딩 중 (jhgan/ko-sroberta-multitask)")
            logger.info("🏠 [LOCAL] Cloud API 호출 없음 - 비용: ₩0")
            logger.info("="*60)
            embeddings = HuggingFaceEmbeddings(
                model_name="jhgan/ko-sroberta-multitask",  # 한국어 최적화 모델
                model_kwargs={"device": "cpu"},
                encode_kwargs={"normalize_embeddings": True}
            )
            logger.info("✅ [LOCAL] Embedding 모델 로딩 완료! (비용: ₩0)")
        else:
            # Fallback: Cloud Embeddings (비용 발생)
            logger.error("="*60)
            logger.error("🚨 [CLOUD] Cloud Embedding 사용 중! - 비용 발생!")
            logger.error("🚨 [CLOUD] langchain-huggingface 설치 필요!")
            logger.error("="*60)
            api_key = ensure_gemini_api_key()
            embeddings = GoogleGenerativeAIEmbeddings(
                model="models/text-embedding-004",
                google_api_key=api_key,
            )
        
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
        logger.info("✅ LangChain 컴포넌트(Embedding, Splitter) 초기화 성공.")
        
        # JennieBrain 초기화 (감성 분석용)
        try:
            jennie_brain = JennieBrain(
                project_id=GCP_PROJECT_ID,
                gemini_api_key_secret=os.getenv("SECRET_ID_GEMINI_API_KEY")
            )
            logger.info("✅ JennieBrain (감성 분석기) 초기화 성공.")
        except Exception as e:
            logger.warning(f"⚠️ JennieBrain 초기화 실패 (감성 분석 Skip): {e}")
            jennie_brain = None

        # [Cost Optimization] NewsClassifier 초기화
        global classifier
        if get_classifier:
            classifier = get_classifier()
            logger.info("✅ NewsClassifier 초기화 성공 (비용 최적화 필터 가동).")
        else:
            classifier = None


    except Exception as e:
        logger.exception("🔥 LangChain 컴포넌트 초기화 실패!")
        raise
    
    logger.info(f"... [RAG Crawler v8.1] Chroma 서버 ({CHROMA_SERVER_HOST}:{CHROMA_SERVER_PORT}) 연결 시도 ...")
    try:
        # Lazy import: chromadb는 실제 사용 시점에만 import
        import chromadb
        
        db_client = chromadb.HttpClient(host=CHROMA_SERVER_HOST, port=CHROMA_SERVER_PORT)
        vectorstore = Chroma(client=db_client, collection_name=COLLECTION_NAME, embedding_function=embeddings)
        db_client.heartbeat() 
        logger.info(f"✅ Chroma 서버 ({CHROMA_SERVER_HOST}) 연결 성공!")
    except Exception as e:
        logger.exception(f"🔥 Chroma 서버 ({CHROMA_SERVER_HOST}) 연결 실패!")
        raise

# ==============================================================================
# 핵심 함수 정의
# ==============================================================================

def get_kospi_200_universe():
    """
    KOSPI 시가총액 상위 200개 종목을 가져옵니다.
    Scout와 동일한 Universe를 사용하여 뉴스를 수집합니다.
    """
    universe_size = int(os.getenv("SCOUT_UNIVERSE_SIZE", "200"))
    logger.info(f"  (1/6) KOSPI 시총 상위 {universe_size}개 종목 로드 중...")
    
    # 1. FinanceDataReader 시도
    if FDR_AVAILABLE:
        try:
            logger.info("  (1/6) FinanceDataReader로 KOSPI 종목 조회 중...")
            df = fdr.StockListing('KOSPI')
            
            if df is not None and not df.empty:
                # 시가총액 기준 정렬 (Marcap 또는 Market Cap 컬럼)
                cap_col = None
                for col in ['Marcap', 'MarCap', 'Market Cap', 'marcap']:
                    if col in df.columns:
                        cap_col = col
                        break
                
                if cap_col:
                    df = df.sort_values(by=cap_col, ascending=False)
                
                # 상위 N개 추출
                top_stocks = df.head(universe_size)
                
                # Code, Name 컬럼 찾기
                code_col = 'Code' if 'Code' in top_stocks.columns else 'Symbol'
                name_col = 'Name' if 'Name' in top_stocks.columns else 'name'
                
                universe = []
                for _, row in top_stocks.iterrows():
                    code = str(row.get(code_col, '')).zfill(6)
                    name = row.get(name_col, f'종목_{code}')
                    if code and len(code) == 6:
                        universe.append({"code": code, "name": name})
                
                if universe:
                    logger.info(f"✅ (1/6) FinanceDataReader로 {len(universe)}개 종목 로드 완료!")
                    return universe
        except Exception as e:
            logger.warning(f"⚠️ (1/6) FinanceDataReader 실패: {e}")
    
    # 2. Fallback: DB의 WatchList 사용
    logger.info("  (1/6) Fallback: DB WatchList 조회 중...")
    return get_watchlist_from_db()


def get_watchlist_from_db():
    """
    DB에서 WatchList를 조회합니다 (Fallback용).
    MariaDB 사용 (pymysql 직접 연결).
    """
    try:
        with session_scope(readonly=True) as session:
            rows = session.query(WatchListModel.stock_code, WatchListModel.stock_name).all()
        
        watchlist = []
        for row in rows:
            watchlist.append({"code": row[0], "name": row[1]})
 
        logger.info(f"✅ (1/6) 'WatchList' {len(watchlist)}개 로드 성공.")
        return watchlist
        
    except Exception as e:
        logger.error(f"🔥 (1/6) DB 'get_watchlist_from_db' 함수 실행 중 오류 발생: {e}")
        return []

def get_numeric_timestamp(feed_entry):
    """
    feed_entry에서 '발행 시간'을 UTC 기준 숫자 타임스탬프로 변환합니다.
    """
    if hasattr(feed_entry, 'published_parsed') and feed_entry.published_parsed:
        try:
            # feedparser가 반환하는 time.struct_time은 timezone 정보가 없을 수 있음
            # calendar.timegm은 이를 UTC로 간주하여 timestamp를 생성
            # 이것이 UTC 기준 시간을 보장하는 가장 안전한 방법
            utc_timestamp = calendar.timegm(feed_entry.published_parsed)
            return int(utc_timestamp)
        except Exception:
            return int(datetime.now(timezone.utc).timestamp())
    else:
        return int(datetime.now(timezone.utc).timestamp())

def crawl_news_for_stock(stock_code, stock_name):
    """
    Google News RSS를 사용하여 특정 종목의 뉴스를 수집합니다.
    """
    logger.info(f"  (2/6) [App 5] '{stock_name}({stock_code})' Google News RSS 피드 수집 중...")
    documents = []
    try:
        query = f'"{stock_name}" OR "{stock_code}"'
        encoded_query = urllib.parse.quote(query)
        rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"
        feed = feedparser.parse(rss_url)
        
        if not feed.entries:
            logger.info(f"  (2/6) '{stock_name}' 관련 신규 뉴스가 없습니다. (Skip)")
            return []

        for entry in feed.entries:
            # 7일이 지난 뉴스는 수집 단계에서 제외
            published_timestamp = get_numeric_timestamp(entry)
            if datetime.fromtimestamp(published_timestamp, tz=timezone.utc) < datetime.now(timezone.utc) - timedelta(days=7):
                logger.debug(f"  (2/6) 오래된 뉴스 제외: {entry.title[:30]}...")
                continue

            doc = Document(
                page_content=f"뉴스 제목: {entry.title}\n링크: {entry.link}",
                metadata={
                    "stock_code": stock_code,
                    "stock_name": stock_name,
                    "source": f"Google News RSS ({entry.get('source', {}).get('title', 'N/A')})",
                    "source_url": entry.link, 
                    "created_at_utc": published_timestamp
                }
            )
            documents.append(doc)
    except Exception as e:
        logger.exception(f"🔥 (2/6) '{stock_name}' 뉴스 수집 중 오류 발생")
    return documents

def crawl_general_news():
    """
    미리 정의된 'GENERAL_RSS_FEEDS' 목록의 일반 경제 뉴스를 수집합니다.
    """
    logger.info(f"  (3/6) [App 5] '일반 경제' RSS {len(GENERAL_RSS_FEEDS)}개 피드 수집 중...")
    documents = []
    
    for feed_info in GENERAL_RSS_FEEDS:
        source = feed_info["source_name"]
        url = feed_info["url"]
        logger.info(f"  (3/6) ... '{source}' 수집 중 ...")
        try:
            feed = feedparser.parse(url)
            if not feed.entries:
                logger.info(f"  (3/6) '{source}'에 신규 뉴스가 없습니다. (Skip)")
                continue

            for entry in feed.entries:
                # 7일이 지난 뉴스는 수집 단계에서 제외
                published_timestamp = get_numeric_timestamp(entry)
                if datetime.fromtimestamp(published_timestamp, tz=timezone.utc) < datetime.now(timezone.utc) - timedelta(days=7):
                    logger.debug(f"  (3/6) 오래된 뉴스 제외: {entry.title[:30]}...")
                    continue

                doc = Document(
                    page_content=f"뉴스 제목: {entry.title}\n링크: {entry.link}",
                    metadata={
                        "source": source,
                        "source_url": entry.link, 
                        "created_at_utc": published_timestamp
                    }
                )
                documents.append(doc)
        except Exception as e:
            logger.exception(f"🔥 (3/6) '{source}' 뉴스 수집 중 오류 발생")
            
    logger.info(f"✅ (3/6) '일반 경제' 뉴스 총 {len(documents)}개 수집 완료.")
    return documents

def filter_new_documents(documents):
    """
    ChromaDB에 'source_url'이 이미 존재하는지 확인하여 새로운 문서만 필터링합니다.
    """
    step_id = "(4/6)"
    logger.info(f"  {step_id} [App 5] 수집된 문서 {len(documents)}개 일괄 중복 검사 시작...")
    if not documents:
        return []

    urls_to_check = list(set([doc.metadata["source_url"] for doc in documents if "source_url" in doc.metadata]))
    if not urls_to_check:
        return documents

    existing_results = vectorstore.get(where={"source_url": {"$in": urls_to_check}})
    existing_urls = set(item['source_url'] for item in existing_results.get('metadatas', []))
    new_docs = [doc for doc in documents if doc.metadata.get("source_url") not in existing_urls]

    logger.info(f"✅ {step_id} 중복 검사 완료. 새로운 문서 {len(new_docs)}개 발견.")
    return new_docs

def process_sentiment_analysis(documents):
    """
    [2026-01 Optimized] 수집된 뉴스 중 종목 뉴스에 대해 실시간 감성 분석을 수행합니다.
    배치 처리(Batch Processing) 도입으로 ~70% 속도 향상
    분석 결과는 Redis 및 MariaDB에 저장됩니다.
    """
    if not jennie_brain or not documents:
        return

    logger.info("="*60)
    logger.info("🏠 [LOCAL] 감성 분석 시작 - Ollama (gpt-oss:20b) 사용")
    logger.info("🏠 [LOCAL] 배치 처리 최적화 - 비용: ₩0")
    logger.info("="*60)
    
    # stock_code가 있는 문서만 분석 대상
    stock_docs = [doc for doc in documents if doc.metadata.get("stock_code")]
    logger.info(f"  [Sentiment] 종목 뉴스 {len(stock_docs)}개 / 전체 {len(documents)}개")
    
    if not stock_docs:
        return

    # 배치 준비: 문서를 (id, title, summary, metadata) 형태로 변환
    batch_items = []
    doc_map = {}  # id -> doc 매핑 (나중에 저장용)
    
    for idx, doc in enumerate(stock_docs):
        content_lines = doc.page_content.split('\n')
        news_title = content_lines[0].replace("뉴스 제목: ", "") if len(content_lines) > 0 else "제목 없음"
        
        batch_items.append({
            "id": idx,
            "title": news_title,
            "summary": news_title  # 제목만 사용 (현재 로직과 동일)
        })
        doc_map[idx] = doc
    
    # 배치 단위로 분석 (BATCH_SIZE=5)
    BATCH_SIZE = 5
    all_results = []
    
    for i in range(0, len(batch_items), BATCH_SIZE):
        batch = batch_items[i:i + BATCH_SIZE]
        logger.info(f"  [Sentiment] 배치 {i//BATCH_SIZE + 1}/{(len(batch_items) + BATCH_SIZE - 1)//BATCH_SIZE} 분석 중...")
        
        try:
            results = jennie_brain.analyze_news_sentiment_batch(batch)
            all_results.extend(results)
        except Exception as e:
            logger.warning(f"⚠️ [Sentiment] 배치 분석 오류: {e}")
            # Fallback: 기본값 추가
            for item in batch:
                all_results.append({'id': item['id'], 'score': 50, 'reason': '배치 분석 실패'})
    
    # 결과 저장
    processed_count = 0
    for result in all_results:
        idx = result.get('id')
        if idx is None or idx not in doc_map:
            continue
            
        doc = doc_map[idx]
        score = result.get('score', 50)
        reason = result.get('reason', '분석 불가')
        
        stock_code = doc.metadata.get("stock_code")
        stock_name = doc.metadata.get("stock_name")
        content_lines = doc.page_content.split('\n')
        news_title = content_lines[0].replace("뉴스 제목: ", "") if len(content_lines) > 0 else "제목 없음"
        news_link = doc.metadata.get("source_url")
        published_at = doc.metadata.get("created_at_utc")
        
        # 뉴스 날짜 추출
        news_date_str = None
        if published_at:
            try:
                news_date_str = datetime.fromtimestamp(published_at, tz=timezone.utc).strftime('%Y-%m-%d')
            except Exception:
                pass
        
        # Redis 저장
        try:
            database.set_sentiment_score(
                stock_code, score, reason, 
                source_url=news_link, 
                stock_name=stock_name,
                news_title=news_title,
                news_date=news_date_str
            )
        except Exception as e:
            logger.warning(f"⚠️ [Sentiment] Redis 저장 실패 (Skip): {e}")
        
        # DB 저장 (Deadlock 재시도)
        import random
        max_retries = 3
        for attempt in range(max_retries):
            try:
                with session_scope() as session:
                    database.save_news_sentiment(session, stock_code, news_title, score, reason, news_link, published_at)
                processed_count += 1
                break
            except Exception as e:
                error_str = str(e)
                is_deadlock = "1213" in error_str or "Deadlock" in error_str
                
                if is_deadlock and attempt < max_retries - 1:
                    wait_time = random.uniform(0.1, 0.5) * (attempt + 1)
                    logger.info(f"🔄 [Sentiment] Deadlock 감지, {wait_time:.2f}초 후 재시도...")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.warning(f"⚠️ [Sentiment] DB 저장 실패 (Skip): {e}")
                    break

    logger.info(f"✅ [Sentiment] 종목 뉴스 {processed_count}건 감성 분석 및 저장 완료.")




def process_competitor_benefit_analysis(documents):
    """
    뉴스에서 경쟁사 수혜 기회를 분석합니다.
    LLM-First Analysis (JennieBrain Reasoning Tier)
    ThreadPoolExecutor를 사용한 병렬 처리 도입 (Cloud LLM 속도 활용)
    """
    if not jennie_brain or not CompetitorAnalyzer or not documents:
        return
    
    logger.info(f"  [경쟁사 수혜] 신규 문서 {len(documents)}개 경쟁사 수혜 분석 시작 (병렬 처리)...")
    
    from shared.db.connection import get_session, session_scope # ensure import
    from shared.db.models import IndustryCompetitors, CompetitorBenefitEvents
    
    MAX_WORKERS = 3
    
    def _analyze_single_competitor_benefit(doc):
        # 문서 정보 추출
        stock_code = doc.metadata.get("stock_code")
        if not stock_code:
            return 0
        
        content_lines = doc.page_content.split('\n')
        news_title = content_lines[0].replace("뉴스 제목: ", "") if len(content_lines) > 0 else "제목 없음"
        news_link = doc.metadata.get("source_url")
        
        events_created = 0

        # 1. LLM 심층 분석
        try:
            analysis_result = jennie_brain.analyze_competitor_benefit(news_title)
        except Exception as e:
            logger.warning(f"⚠️ [경쟁사 수혜] LLM 분석 오류 '{news_title[:20]}...': {e}")
            return 0

        # 2. 리스크 아니면 Skip
        if not analysis_result.get('is_risk'):
            return 0
        
        event_type = analysis_result.get('event_type', 'OTHER')
        benefit_score = analysis_result.get('competitor_benefit_score', 0)
        
        logger.info(f"  🔴 [악재 감지/LLM] {stock_code} - {event_type}: {news_title[:50]}... (Score: {benefit_score})")

        # 3. DB 로직 (Thread-Safe하게 내부에서 세션 생성) - Deadlock 재시도
        import random
        max_retries = 3
        for attempt in range(max_retries):
            try:
                with session_scope() as session:
                    # 해당 종목의 섹터 확인
                    affected_stock = session.query(IndustryCompetitors).filter(
                        IndustryCompetitors.stock_code == stock_code
                    ).first()
                    
                    if not affected_stock:
                        return 0
                    
                    sector_code = affected_stock.sector_code
                    sector_name = affected_stock.sector_name
                    affected_name = affected_stock.stock_name
                    
                    # 동일 섹터 경쟁사 조회
                    competitors = session.query(IndustryCompetitors).filter(
                        IndustryCompetitors.sector_code == sector_code,
                        IndustryCompetitors.stock_code != stock_code,
                        IndustryCompetitors.is_active == 1
                    ).all()
                    
                    if not competitors:
                        return 0
                    
                    # 이벤트 생성
                    duration_days = 7
                    if event_type in ['FIRE', 'RECALL', 'SECURITY', 'OWNER_RISK']:
                        duration_days = 30
                    expires_at = datetime.now(timezone.utc) + timedelta(days=duration_days)
                    
                    for competitor in competitors:
                        # 중복 조회
                        existing = session.query(CompetitorBenefitEvents).filter(
                            CompetitorBenefitEvents.affected_stock_code == stock_code,
                            CompetitorBenefitEvents.beneficiary_stock_code == competitor.stock_code,
                            CompetitorBenefitEvents.event_type == event_type,
                            CompetitorBenefitEvents.detected_at >= datetime.now(timezone.utc) - timedelta(hours=24)
                        ).first()
                        
                        if existing:
                            continue
                        
                        # 새로운 이벤트 추가
                        benefit_event = CompetitorBenefitEvents(
                            affected_stock_code=stock_code,
                            affected_stock_name=affected_name,
                            event_type=event_type,
                            event_title=news_title[:1000],
                            event_severity=-10,
                            source_url=news_link,
                            beneficiary_stock_code=competitor.stock_code,
                            beneficiary_stock_name=competitor.stock_name,
                            benefit_score=benefit_score,
                            sector_code=sector_code,
                            sector_name=sector_name,
                            status='ACTIVE',
                            expires_at=expires_at
                        )
                        session.add(benefit_event)
                        events_created += 1
                        
                        # Redis 저장 (Loop 안에서 호출하되, 에러나도 진행)
                        try:
                            database.set_competitor_benefit_score(
                                stock_code=competitor.stock_code,
                                score=benefit_score,
                                reason=f"경쟁사 {affected_name}의 {event_type} 악재로 인한 수혜 (LLM Analysis)",
                                affected_stock=stock_code,
                                event_type=event_type,
                                ttl=duration_days * 86400
                            )
                        except Exception as e:
                            logger.warning(f"⚠️ [경쟁사 수혜] Redis 저장 실패: {e}")

                        logger.info(
                            f"  ✅ [수혜 등록] {competitor.stock_name}({competitor.stock_code}) "
                            f"+{benefit_score}점 ← {affected_name} {event_type}"
                        )
                    
                    # session_scope exit -> commit
                    return events_created
                    
            except Exception as e:
                error_str = str(e)
                is_deadlock = "1213" in error_str or "Deadlock" in error_str
                
                if is_deadlock and attempt < max_retries - 1:
                    wait_time = random.uniform(0.1, 0.5) * (attempt + 1)
                    logger.info(f"🔄 [경쟁사 수혜] Deadlock 감지, {wait_time:.2f}초 후 재시도 ({attempt + 1}/{max_retries})...")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"❌ [경쟁사 수혜] DB 처리 중 오류: {e}")
                    return 0

    total_events_created = 0
    futures = []
    
    # [Local LLM] 제한 없이 모든 종목 뉴스 분석 (비용 ₩0)
    # stock_code가 있는 문서만 분석 대상
    stock_docs = [doc for doc in documents if doc.metadata.get("stock_code")]
    logger.info(f"  [경쟁사 수혜] 종목 뉴스 {len(stock_docs)}개 / 전체 {len(documents)}개")
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for doc in stock_docs:
            futures.append(executor.submit(_analyze_single_competitor_benefit, doc))
            
        for future in as_completed(futures):
            try:
                total_events_created += future.result()
            except Exception as e:
                logger.error(f"❌ [경쟁사 수혜] 스레드 실행 중 오류: {e}")

    logger.info(f"✅ [경쟁사 수혜] 수혜 이벤트 {total_events_created}건 생성 완료 (병렬 처리)")



def add_documents_to_chroma(documents):
    """
    새로운 Document 리스트를 분할(Chunking) 후 벡터로 변환하여 ChromaDB에 저장합니다.
    """
    step_id = "(5/6)"
    if not documents:
        logger.info(f"  {step_id} [App 5] Chroma에 저장할 새로운 문서가 없습니다. (Skip Write)")
        return

    logger.info(f"  {step_id} [App 5] '새' 문서 {len(documents)}개 텍스트 분할 및 임베딩 중...")
    try:
        # Local Embedding 사용 - 필터링 없이 모든 문서 임베딩 (비용 ₩0)
        splitted_docs = text_splitter.split_documents(documents)
        
        for i in range(0, len(splitted_docs), VERTEX_AI_BATCH_SIZE): # type: ignore
            batch_docs = splitted_docs[i : i + VERTEX_AI_BATCH_SIZE]
            logger.info(f"  {step_id} [App 4] '새' 청크 {i+1} ~ {i+len(batch_docs)}번 (총 {len(batch_docs)}개) 저장 시도...")
            vectorstore.add_documents(
                batch_docs
            )
        
        logger.info("="*60)
        logger.info("🏠 [LOCAL] 임베딩 완료 - HuggingFace (ko-sroberta) 사용")
        logger.info("🏠 [LOCAL] Cloud API 호출 없음 - 비용: ₩0")
        logger.info("="*60)
        logger.info(f"✅ {step_id} Chroma 서버에 '새' 청크 총 {len(splitted_docs)}개 저장 완료!")
    except Exception as e:
        logger.exception(f"🔥 {step_id} [App 4] Chroma 서버에 'Write' 중 심각한 오류 발생")

def cleanup_old_data_job():
    """
    DATA_TTL_DAYS(7일)가 지난 오래된 뉴스 데이터를 ChromaDB에서 삭제합니다.
    """
    logger.info(f"\n[데이터 정리] {DATA_TTL_DAYS}일 경과한 오래된 RAG 데이터 삭제 시작...")
    try:
        ttl_limit_timestamp = int((datetime.now(timezone.utc) - timedelta(days=DATA_TTL_DAYS)).timestamp())
        collection = vectorstore._collection
        
        logger.info(f"... [데이터 정리] created_at_utc < {ttl_limit_timestamp} 데이터 삭제 중 ...")
        collection.delete(where={"created_at_utc": {"$lt": ttl_limit_timestamp}})
        
        logger.info("✅ [데이터 정리] 오래된 데이터 삭제 완료.")
    except Exception as e:
        logger.warning(f"⚠️ [데이터 정리] 데이터 삭제 중 오류 발생: {e}")

# ==============================================================================
# 메인 작업 실행 함수
# ==============================================================================

def run_collection_job():
    """
    뉴스 수집 및 저장을 위한 메인 태스크.
    이 함수가 스크립트의 '진입점(Entrypoint)'이 됩니다.
    KOSPI 200 전체 뉴스 수집 (Scout Universe와 동일)
    """
    logger.info(f"\n--- [RAG 수집 봇 v9.0] 작업 시작 ---")
    
    # [Operating Hours Check] — mock/test에서는 스킵 가능
    disable_market_open_check = os.getenv("DISABLE_MARKET_OPEN_CHECK", "false").lower() in {"1", "true", "yes", "on"}
    if not disable_market_open_check:
        from shared.utils import is_operating_hours
        if not is_operating_hours():
            logger.info("🕒 현재 운영 시간이 아닙니다. (운영 시간: 평일 07:00 ~ 17:00) 작업을 건너뜁니다.")
            return
    
    # 서비스 초기화 (지연 초기화)
    try:
        initialize_services()
    except Exception as e:
        logger.error(f"🔥 서비스 초기화 실패: {e}")
        return
    
    try:
        all_fetched_documents = []

        # 1. '일반 경제' RSS 수집
        general_news_docs = crawl_general_news()
        all_fetched_documents.extend(general_news_docs)

        # 2. KOSPI 200 Universe 로드 (Scout와 동일)
        universe = get_kospi_200_universe()
        logger.info(f"  (2/6) KOSPI Universe {len(universe)}개 종목 뉴스 수집 시작...")

        # 3. 각 종목별 뉴스 크롤링을 병렬로 실행
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_stock = {executor.submit(crawl_news_for_stock, stock["code"], stock["name"]): stock for stock in universe}
            for future in as_completed(future_to_stock):
                stock = future_to_stock[future]
                try:
                    fetched_docs = future.result()
                    all_fetched_documents.extend(fetched_docs)
                except Exception as exc:
                    logger.error(f"🔥 '{stock['name']}' 뉴스 수집 스레드에서 오류 발생: {exc}")

        # 4. '새로운' 문서만 필터링 (Deduplication)
        new_documents_to_add = filter_new_documents(all_fetched_documents)
        
        # [New] 4-1. 새로운 문서 감성 분석 및 저장
        if os.getenv("ENABLE_NEWS_ANALYSIS", "true").lower() == "true":
            process_sentiment_analysis(new_documents_to_add)
        
            # 4-2. 경쟁사 수혜 분석 및 저장
            process_competitor_benefit_analysis(new_documents_to_add)
        else:
            logger.info("⚠️ [Config] 'ENABLE_NEWS_ANALYSIS=false' 설정으로 인해 분석 단계 생략.")
        
        # 5. '새로운' 문서만 Chroma 서버에 저장 (Write)
        add_documents_to_chroma(new_documents_to_add)
        
        # 6. 오래된 데이터 정리
        cleanup_old_data_job()
        
        logger.info(f"--- [RAG 수집 봇 v9.1] 작업 완료 ---")
        
    except Exception as e:
        logger.exception(f"🔥 [RAG 수집 봇 v9.0] 메인 작업 중 심각한 오류 발생")

# =============================================================================
# 메인 실행 블록
# =============================================================================

if __name__ == "__main__":
    
    start_time = time.time()

    # 메인 작업 실행
    try:
        run_collection_job()
    except Exception as e:
        logger.critical(f"❌ [RAG Crawler v8.1] 'run_collection_job' 실행 중 알 수 없는 오류: {e}")
        
    end_time = time.time()
    logger.info(f"--- [RAG 수집 봇 v8.1] 스크립트 종료 (총 소요시간: {end_time - start_time:.2f}초) ---")
