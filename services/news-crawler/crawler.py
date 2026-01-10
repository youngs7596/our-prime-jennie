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
    # from shared.news_classifier import NewsClassifier, get_classifier
    # from shared.hybrid_scoring.competitor_analyzer import CompetitorAnalyzer
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

# --- 🔽 네이버 금융 뉴스 크롤링 설정 🔽 ---
# 뉴스 소스 선택: "google" (기존), "naver" (신규), "hybrid" (둘 다)
NEWS_CRAWLER_SOURCE = os.getenv("NEWS_CRAWLER_SOURCE", "naver")
NAVER_FINANCE_NEWS_URL = "https://finance.naver.com/item/news_news.naver?code={code}&page={page}"
NAVER_NEWS_MAX_PAGES = int(os.getenv("NAVER_NEWS_MAX_PAGES", "2"))  # 페이지당 ~15건
NAVER_NEWS_REQUEST_DELAY = float(os.getenv("NAVER_NEWS_REQUEST_DELAY", "0.3"))  # Rate limit 대응

# --- 🔽 '일반 경제' RSS 피드 🔽 ---
GENERAL_RSS_FEEDS = [
    {"source_name": "Hankyung (Finance)", "url": "https://www.hankyung.com/feed/finance"},
    {"source_name": "Hankyung (Economy)", "url": "https://www.hankyung.com/feed/economy"},
    {"source_name": "Maeil Business (Economy)", "url": "https://www.mk.co.kr/rss/50000001/"},
    {"source_name": "Maeil Business (Stock)", "url": "https://www.mk.co.kr/rss/50100001/"},
]

# ==============================================================================
# 뉴스 소스 필터링 설정 (2026-01 현자 3인 피드백 반영)
# ==============================================================================

# Tier 1: 신뢰할 수 있는 경제/금융 전문지 도메인 (hostname suffix 매칭)
TRUSTED_NEWS_DOMAINS = {
    "hankyung.com",      # 한국경제
    "mk.co.kr",          # 매일경제
    "sedaily.com",       # 서울경제
    "mt.co.kr",          # 머니투데이
    "fnnews.com",        # 파이낸셜뉴스
    "thebell.co.kr",     # 더벨 (M&A/IB)
    "newspim.com",       # 뉴스핌
    "edaily.co.kr",      # 이데일리
    "etoday.co.kr",      # 이투데이
    "yna.co.kr",         # 연합뉴스
    "etnews.com",        # 전자신문 (IT/반도체)
    "biz.chosun.com",    # 조선비즈
    "newsis.com",        # 뉴시스
}

# Wrapper 도메인 (포털/구글 - 신뢰 소스로 취급하지 않음)
WRAPPER_DOMAINS = {
    "news.naver.com", "n.news.naver.com",
    "v.daum.net", "news.v.daum.net",
    "news.google.com",
}

# 노이즈 키워드 (제목에 있으면 저품질로 판단하여 제외)
NOISE_KEYWORDS = [
    "특징주", "오전 시황", "장마감", "마감 시황", "급등락",
    "오늘의 증시", "환율", "개장", "출발", "상위 종목",
    "장중 시황", "거래량 상위", "외인 순매수", "기관 순매수",
]

# 신뢰할 수 있는 언론사 이름 (Google News source.title 매칭용)
TRUSTED_SOURCE_NAMES = {
    "한국경제", "한경", "Hankyung",
    "매일경제", "매경", "MK",
    "서울경제",
    "머니투데이",
    "파이낸셜뉴스",
    "더벨", "thebell",
    "뉴스핌",
    "이데일리",
    "이투데이",
    "연합뉴스", "연합뉴스TV",
    "전자신문", "ETNews",
    "조선비즈",
    "뉴시스",
    "헤럴드경제",
    "아시아경제",
    "데일리안",
    "뉴스1",
}

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

def initialize_services():
    """
    LangChain 및 ChromaDB 서비스를 초기화합니다.
    run_collection_job() 실행 시에만 호출됩니다.
    """
    global embeddings, text_splitter, db_client, vectorstore, jennie_brain
    
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
    
    Fallback 순서:
    1. FinanceDataReader API
    2. 네이버 금융 시총 스크래핑
    3. DB WatchList (최후의 수단)
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
    
    # 2. Fallback: 네이버 금융 시총 스크래핑
    universe = _scrape_naver_finance_top_stocks(universe_size)
    if universe:
        return universe
    
    # 3. 최후 Fallback: DB의 WatchList 사용
    logger.info("  (1/6) 최후 Fallback: DB WatchList 조회 중...")
    return get_watchlist_from_db()


def _scrape_naver_finance_top_stocks(limit: int = 200) -> list:
    """
    네이버 금융에서 KOSPI 시총 상위 종목을 스크래핑합니다.
    FDR API 장애 시 Fallback으로 사용.
    """
    import requests
    from bs4 import BeautifulSoup
    
    logger.info("  (1/6) 네이버 금융 시총 스크래핑 시도 중...")
    
    universe = []
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    try:
        # KOSPI 시총 상위 (페이지당 50개, 최대 4페이지 = 200개)
        pages_needed = (limit // 50) + 1
        
        for page in range(1, pages_needed + 1):
            if len(universe) >= limit:
                break
                
            url = f'https://finance.naver.com/sise/sise_market_sum.naver?sosok=0&page={page}'
            resp = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            rows = soup.select('table.type_2 tbody tr')
            for row in rows:
                if len(universe) >= limit:
                    break
                    
                cells = row.select('td')
                if len(cells) >= 2:
                    link = cells[1].select_one('a')
                    if link:
                        name = link.text.strip()
                        href = link.get('href', '')
                        code = href.split('code=')[-1][:6] if 'code=' in href else ''
                        if code and len(code) == 6 and code.isdigit():
                            universe.append({"code": code, "name": name})
        
        if universe:
            logger.info(f"✅ (1/6) 네이버 금융 스크래핑으로 {len(universe)}개 종목 로드 완료!")
            return universe
        else:
            logger.warning("⚠️ (1/6) 네이버 금융 스크래핑 결과 없음")
            
    except Exception as e:
        logger.warning(f"⚠️ (1/6) 네이버 금융 스크래핑 실패: {e}")
    
    return []


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

# ==============================================================================
# 뉴스 소스 필터링 유틸 함수 (Phase 1,2,3)
# ==============================================================================

def get_hostname(url: str) -> str:
    """URL에서 hostname 추출"""
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower().strip(".")
    except Exception:
        return ""

def is_trusted_hostname(host: str) -> bool:
    """hostname이 신뢰 도메인인지 확인 (suffix 매칭)"""
    return any(host == d or host.endswith("." + d) for d in TRUSTED_NEWS_DOMAINS)

def is_wrapper_domain(host: str) -> bool:
    """hostname이 wrapper 도메인(포털/구글)인지 확인"""
    return any(host == d or host.endswith("." + d) for d in WRAPPER_DOMAINS)

def extract_date_from_url(url: str):
    """
    URL 패턴에서 발행일 추출 (예: /20250102...)
    한경, 매경 등 대부분의 국내 언론사 지원
    """
    import re
    from datetime import date as date_class
    match = re.search(r'/(\d{4})(\d{2})(\d{2})\d+', url)
    if match:
        try:
            return date_class(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
    return None

def is_noise_title(title: str) -> bool:
    """제목이 노이즈(저품질) 뉴스인지 확인"""
    for noise in NOISE_KEYWORDS:
        if noise in title:
            return True
    return False

def is_trusted_source_name(source_name: str) -> bool:
    """Google News의 source.title이 신뢰 언론사인지 확인"""
    if not source_name:
        return False
    for trusted in TRUSTED_SOURCE_NAMES:
        if trusted in source_name:
            return True
    return False

def compute_news_hash(title: str) -> str:
    """제목 기반 중복 체크용 해시"""
    import hashlib
    import re as re_module
    # 특수문자, 공백 정규화 후 해싱
    normalized = re_module.sub(r'[^\w]', '', title.lower())
    return hashlib.md5(normalized.encode()).hexdigest()[:12]

# 세션 내 중복 제거용 캐시
_seen_news_hashes = set()

def crawl_naver_finance_news(stock_code: str, stock_name: str, max_pages: int = None) -> list:
    """
    네이버 금융에서 특정 종목의 뉴스를 직접 크롤링합니다.
    [2026-01-03] Google News RSS 대신/보조로 사용.
    
    Args:
        stock_code: 종목 코드 (예: "005930")
        stock_name: 종목명 (예: "삼성전자")
        max_pages: 수집할 최대 페이지 수 (기본값: NAVER_NEWS_MAX_PAGES 환경변수)
    
    Returns:
        Document 리스트 (기존 crawl_news_for_stock과 동일한 형식)
    """
    import requests
    from bs4 import BeautifulSoup
    from datetime import date as date_class
    
    if max_pages is None:
        max_pages = NAVER_NEWS_MAX_PAGES
    
    logger.info(f"  (2/6) [Naver Finance] '{stock_name}({stock_code})' 뉴스 크롤링 시작 (max_pages={max_pages})")
    documents = []
    
    # 필터링 통계
    stats = {"total": 0, "noise": 0, "old": 0, "dup": 0, "accepted": 0}
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': f'https://finance.naver.com/item/news.naver?code={stock_code}'
    }
    
    for page in range(1, max_pages + 1):
        try:
            url = NAVER_FINANCE_NEWS_URL.format(code=stock_code, page=page)
            resp = requests.get(url, headers=headers, timeout=10)
            resp.encoding = 'euc-kr'
            
            if resp.status_code != 200:
                logger.warning(f"  [Naver Finance] HTTP {resp.status_code} for {stock_code} page {page}")
                continue
            
            soup = BeautifulSoup(resp.text, 'html.parser')
            news_table = soup.select_one('table.type5')
            
            if not news_table:
                logger.debug(f"  [Naver Finance] 뉴스 테이블 없음 - {stock_code} page {page}")
                break  # 더 이상 페이지 없음
            
            rows = news_table.select('tr')
            page_news_count = 0
            
            for row in rows:
                title_td = row.select_one('td.title')
                if not title_td:
                    continue
                
                link = title_td.select_one('a')
                if not link:
                    continue
                
                info_td = row.select_one('td.info')  # 언론사
                date_td = row.select_one('td.date')  # 날짜
                
                title = link.text.strip()
                href = link.get('href', '')
                source = info_td.text.strip() if info_td else 'N/A'
                date_str = date_td.text.strip() if date_td else ''
                
                if not title:
                    continue
                
                stats["total"] += 1
                
                # 1. 노이즈 필터링
                if is_noise_title(title):
                    stats["noise"] += 1
                    continue
                
                # 2. 날짜 필터링 (7일 이내)
                if date_str:
                    try:
                        # 형식: "2026.01.03 08:54"
                        date_part = date_str.split()[0]  # "2026.01.03"
                        parts = date_part.split('.')
                        if len(parts) == 3:
                            article_date = date_class(int(parts[0]), int(parts[1]), int(parts[2]))
                            days_old = (date_class.today() - article_date).days
                            if days_old > 7:
                                stats["old"] += 1
                                continue
                    except (ValueError, IndexError):
                        pass  # 파싱 실패 시 일단 포함
                
                # 3. 중복 체크
                news_hash = compute_news_hash(title)
                if news_hash in _seen_news_hashes:
                    stats["dup"] += 1
                    continue
                _seen_news_hashes.add(news_hash)
                
                # 모든 필터 통과 -> 수집
                stats["accepted"] += 1
                page_news_count += 1
                
                # 링크 정규화
                if href.startswith('/'):
                    full_link = 'https://finance.naver.com' + href
                else:
                    full_link = href
                
                # 타임스탬프 생성 (날짜 문자열 기반)
                published_timestamp = int(datetime.now(timezone.utc).timestamp())
                if date_str:
                    try:
                        dt = datetime.strptime(date_str, '%Y.%m.%d %H:%M')
                        dt = dt.replace(tzinfo=timezone(timedelta(hours=9)))  # KST
                        published_timestamp = int(dt.timestamp())
                    except ValueError:
                        pass
                
                doc = Document(
                    page_content=f"뉴스 제목: {title}\n링크: {full_link}",
                    metadata={
                        "stock_code": stock_code,
                        "stock_name": stock_name,
                        "source": f"Naver Finance ({source})",
                        "source_url": full_link,
                        "created_at_utc": published_timestamp
                    }
                )
                documents.append(doc)
            
            logger.debug(f"  [Naver Finance] {stock_code} page {page}: {page_news_count}건 수집")
            
            # Rate limit 대응
            if page < max_pages:
                time.sleep(NAVER_NEWS_REQUEST_DELAY)
                
        except Exception as e:
            logger.exception(f"🔥 [Naver Finance] {stock_code} page {page} 크롤링 오류: {e}")
    
    # 필터링 통계 로그
    if stats["total"] > 0:
        logger.info(f"  (2/6) [{stock_name}] Naver 필터링: 총{stats['total']} → noise:{stats['noise']} old:{stats['old']} dup:{stats['dup']} → 수집:{stats['accepted']}")
    else:
        logger.info(f"  (2/6) [{stock_name}] Naver 뉴스 없음")
    
    return documents


def crawl_stock_news_with_fallback(stock_code: str, stock_name: str) -> list:
    """
    종목 뉴스 크롤링 (Naver 우선, Google Fallback)
    
    1. 네이버 금융에서 먼저 크롤링 시도
    2. 실패하거나 결과가 없으면 Google News RSS로 Fallback
    
    Args:
        stock_code: 종목 코드
        stock_name: 종목명
    
    Returns:
        Document 리스트
    """
    # 1차: 네이버 금융 시도
    try:
        naver_docs = crawl_naver_finance_news(stock_code, stock_name)
        if naver_docs:
            return naver_docs
        else:
            # 네이버에서 뉴스가 없으면 Google Fallback
            logger.info(f"  [Fallback] {stock_name}: Naver 뉴스 0건 → Google News 시도")
    except Exception as e:
        logger.warning(f"  [Fallback] {stock_name}: Naver 크롤링 오류 ({e}) → Google News 시도")
    
    # 2차: Google News Fallback
    try:
        google_docs = crawl_news_for_stock(stock_code, stock_name)
        if google_docs:
            logger.info(f"  [Fallback] {stock_name}: Google News에서 {len(google_docs)}건 수집")
        return google_docs
    except Exception as e:
        logger.error(f"🔥 [Fallback] {stock_name}: Google News도 실패 - {e}")
        return []


def crawl_news_for_stock(stock_code, stock_name):
    """
    Google News RSS를 사용하여 특정 종목의 뉴스를 수집합니다.
    [2026-01 개선] 신뢰 소스 필터링 + 노이즈 키워드 제외 + 중복 제거
    """
    logger.info(f"  (2/6) [App 5] '{stock_name}({stock_code})' Google News RSS 피드 수집 중...")
    documents = []
    
    # 필터링 통계
    stats = {"total": 0, "wrapper": 0, "untrusted": 0, "noise": 0, "old": 0, "dup": 0, "accepted": 0}
    
    try:
        query = f'"{stock_name}" OR "{stock_code}"'
        encoded_query = urllib.parse.quote(query)
        rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"
        feed = feedparser.parse(rss_url)
        
        if not feed.entries:
            logger.info(f"  (2/6) '{stock_name}' 관련 신규 뉴스가 없습니다. (Skip)")
            return []

        for entry in feed.entries:
            stats["total"] += 1
            
            # 1. 소스 검증 (Google wrapper vs 직접 URL)
            host = get_hostname(entry.link)
            source_title = entry.get('source', {}).get('title', '')
            
            if is_wrapper_domain(host):
                # Google/포털 wrapper인 경우 -> source.title로 신뢰 검증
                if not is_trusted_source_name(source_title):
                    stats["untrusted"] += 1
                    continue
                # 신뢰 언론사면 wrapper여도 통과
            else:
                # 직접 URL인 경우 -> hostname으로 신뢰 검증
                if not is_trusted_hostname(host):
                    stats["untrusted"] += 1
                    continue
            
            # 3. 노이즈 키워드 체크
            if is_noise_title(entry.title):
                stats["noise"] += 1
                continue
            
            # 4. 날짜 필터링 (URL 패턴 우선, fallback은 RSS)
            article_date = extract_date_from_url(entry.link)
            if article_date:
                from datetime import date as date_class
                days_old = (date_class.today() - article_date).days
                if days_old > 7:
                    stats["old"] += 1
                    continue
            else:
                # fallback: RSS published 날짜
                published_timestamp = get_numeric_timestamp(entry)
                if datetime.fromtimestamp(published_timestamp, tz=timezone.utc) < datetime.now(timezone.utc) - timedelta(days=7):
                    stats["old"] += 1
                    continue
            
            # 5. 중복 체크 (제목 해시)
            news_hash = compute_news_hash(entry.title)
            if news_hash in _seen_news_hashes:
                stats["dup"] += 1
                continue
            _seen_news_hashes.add(news_hash)
            
            # 모든 필터 통과 -> 수집
            stats["accepted"] += 1
            published_timestamp = get_numeric_timestamp(entry)
            
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
    
    # 필터링 통계 로그
    if stats["total"] > 0:
        logger.info(f"  (2/6) [{stock_name}] 필터링: 총{stats['total']} → wrapper:{stats['wrapper']} untrusted:{stats['untrusted']} noise:{stats['noise']} old:{stats['old']} dup:{stats['dup']} → 수집:{stats['accepted']}")
    
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

def process_unified_analysis(documents):
    """
    [2026-01 Optimized] 통합 뉴스 분석 (감성 + 경쟁사 리스크)
    Single-Pass LLM Call로 두 가지 분석을 동시에 수행합니다.
    - 감성 분석: Redis & MariaDB 저장
    - 리스크 탐지: 경쟁사 수혜 이벤트 생성
    """
    if not jennie_brain or not documents:
        return

    logger.info("="*60)
    # [Fix] Log actual model name from Env (since JennieBrain doesn't expose it directly)
    model_name = os.getenv("LOCAL_MODEL_FAST", "gemma3:27b")
    logger.info(f"🚀 [Unified] 통합 뉴스 분석 시작 - Ollama ({model_name})")
    logger.info("🚀 [Unified] Single-Pass LLM Call (Sentiment + Risk) - 비용/시간 최적화")
    logger.info("="*60)
    
    # stock_code가 있는 문서만 분석 대상
    stock_docs = [doc for doc in documents if doc.metadata.get("stock_code")]
    logger.info(f"  [Unified] 대상 종목 뉴스 {len(stock_docs)}개 / 전체 {len(documents)}개")
    
    if not stock_docs:
        return

    # 배치 준비
    batch_items = []
    doc_map = {}
    
    for idx, doc in enumerate(stock_docs):
        content_lines = doc.page_content.split('\n')
        news_title = content_lines[0].replace("뉴스 제목: ", "") if len(content_lines) > 0 else "제목 없음"
        
        batch_items.append({
            "id": idx,
            "title": news_title,
            "summary": news_title 
        })
        doc_map[idx] = doc
    
    # 배치 분석 실행 (Sequential Batch Processing - Best Performance for Local LLM)
    BATCH_SIZE = 5
    batches = [batch_items[i:i + BATCH_SIZE] for i in range(0, len(batch_items), BATCH_SIZE)]
    all_results = []
    
    logger.info(f"  [Unified] 총 {len(batches)}개 배치 순차 분석 시작 (Single Thread)...")
    
    for i, batch in enumerate(batches):
        try:
            results = jennie_brain.analyze_news_unified(batch)
            all_results.extend(results)
            logger.info(f"  [Unified] 배치 {i+1}/{len(batches)} 분석 완료 ({len(results)}건)")
        except Exception as e:
            logger.warning(f"⚠️ [Unified] 배치 {i+1} 분석 실패: {e}")
            # Fallback handled inside analyze_news_unified usually using get_unified_fallback_response

    # 결과 처리 (병렬 저장)
    logger.info(f"  [Unified] {len(all_results)}건 결과 처리 시작 (병렬 저장/이벤트 생성)...")
    
    # DB 작업이 혼합되어 있으므로 안전하게 처리
    _process_unified_results_parallel(all_results, doc_map)


def _process_unified_results_parallel(results, doc_map):
    """
    통합 분석 결과를 병렬로 처리합니다.
    1. 감성 분석 결과 저장 (Redis/DB)
    2. 리스크 탐지 시 경쟁사 수혜 이벤트 생성
    """
    MAX_WORKERS = 5 # DB Pool 고려
    processed_count = 0
    risk_event_count = 0
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = []
        for res in results:
            futures.append(executor.submit(_handle_single_unified_result, res, doc_map))
            
        for future in as_completed(futures):
            try:
                success, is_risk = future.result()
                if success: processed_count += 1
                if is_risk: risk_event_count += 1
            except Exception as e:
                logger.error(f"❌ [Unified] 결과 처리 중 오류: {e}")
                
    logger.info(f"✅ [Unified] 완료: 감성분석 {processed_count}건 저장, 리스크 이벤트 {risk_event_count}건 생성.")


def _handle_single_unified_result(result, doc_map):
    """개별 통합 결과 처리 핸들러"""
    idx = result.get('id')
    doc = doc_map.get(idx)
    if not doc: return False, False
    
    # 1. 감성 분석 저장
    sentiment = result.get('sentiment', {})
    score = sentiment.get('score', 50)
    reason = sentiment.get('reason', 'N/A')
    
    # (기존 _save_single_sentiment_result 로직 인라인 or 재사용)
    # 여기서는 로직을 단순화하여 직접 호출
    save_success = _save_sentiment_to_db(doc, score, reason)
    
    # 2. 경쟁사 리스크 이벤트 처리
    risk = result.get('competitor_risk', {})
    is_risk = risk.get('is_detected', False)
    
    if is_risk:
        _create_competitor_event(doc, risk)
        
    return save_success, is_risk


def _save_sentiment_to_db(doc, score, reason):
    """감성 점수 저장 로직 (Redis + MariaDB)"""
    stock_code = doc.metadata.get("stock_code")
    stock_name = doc.metadata.get("stock_name")
    content_lines = doc.page_content.split('\n')
    news_title = content_lines[0].replace("뉴스 제목: ", "") if len(content_lines) > 0 else "제목 없음"
    news_link = doc.metadata.get("source_url")
    published_at = doc.metadata.get("created_at_utc")
    
    news_date_str = None
    if published_at:
        try:
            news_date_str = datetime.fromtimestamp(published_at, tz=timezone.utc).strftime('%Y-%m-%d')
        except Exception: pass
        
    # Redis
    try:
        database.set_sentiment_score(stock_code, score, reason, source_url=news_link, stock_name=stock_name, news_title=news_title, news_date=news_date_str)
    except Exception: pass
    
    # DB
    import random
    for attempt in range(3):
        try:
            with session_scope() as session:
                database.save_news_sentiment(session, stock_code, news_title, score, reason, news_link, published_at)
            return True
        except Exception as e:
            if "Deadlock" in str(e) and attempt < 2:
                time.sleep(random.uniform(0.1, 0.5))
                continue
            return False
    return False


def _create_competitor_event(doc, risk_data):
    """경쟁사 수혜 이벤트 생성 로직"""
    stock_code = doc.metadata.get("stock_code")
    content_lines = doc.page_content.split('\n')
    news_title = content_lines[0].replace("뉴스 제목: ", "") if len(content_lines) > 0 else "제목 없음"
    news_link = doc.metadata.get("source_url")
    
    event_type = risk_data.get('type', 'OTHER')
    benefit_score = risk_data.get('benefit_score', 0)
    
    logger.info(f"  🔴 [Risk Detected] {stock_code} - {event_type} (Benefit Score: {benefit_score})")

    from shared.db.models import IndustryCompetitors, CompetitorBenefitEvents
    
    try:
        with session_scope() as session:
            # 1. 섹터 확인
            affected_stock = session.query(IndustryCompetitors).filter(IndustryCompetitors.stock_code == stock_code).first()
            if not affected_stock: return
            
            # 2. 경쟁사 조회
            competitors = session.query(IndustryCompetitors).filter(
                IndustryCompetitors.sector_code == affected_stock.sector_code,
                IndustryCompetitors.stock_code != stock_code,
                IndustryCompetitors.is_active == 1
            ).all()
            
            if not competitors: return
            
            # 3. 이벤트 생성
            duration_days = 30 if event_type in ['FIRE', 'RECALL', 'SECURITY', 'OWNER_RISK'] else 7
            expires_at = datetime.now(timezone.utc) + timedelta(days=duration_days)
            
            for comp in competitors:
                # 중복 체크
                existing = session.query(CompetitorBenefitEvents).filter(
                    CompetitorBenefitEvents.affected_stock_code == stock_code,
                    CompetitorBenefitEvents.beneficiary_stock_code == comp.stock_code,
                    CompetitorBenefitEvents.event_type == event_type,
                    CompetitorBenefitEvents.detected_at >= datetime.now(timezone.utc) - timedelta(hours=24)
                ).first()
                
                if existing: continue
                
                # 이벤트 등록
                event = CompetitorBenefitEvents(
                    affected_stock_code=stock_code,
                    affected_stock_name=affected_stock.stock_name,
                    event_type=event_type,
                    event_title=news_title[:1000],
                    event_severity=-10, # 기본값
                    source_url=news_link,
                    beneficiary_stock_code=comp.stock_code,
                    beneficiary_stock_name=comp.stock_name,
                    benefit_score=benefit_score,
                    sector_code=affected_stock.sector_code,
                    sector_name=affected_stock.sector_name,
                    status='ACTIVE',
                    expires_at=expires_at
                )
                session.add(event)
                
                # Redis 업데이트 (Optional) - try-catch
                try:
                    database.set_competitor_benefit_score(
                        comp.stock_code, benefit_score, 
                        f"경쟁사 {affected_stock.stock_name} {event_type} 발생 (Unified Analysis)",
                        stock_code, event_type, ttl=duration_days*86400
                    )
                except: pass
                
                logger.info(f"  ✅ [수혜 등록] {comp.stock_name} +{benefit_score}점 (by {event_type})")

    except Exception as e:
        logger.error(f"❌ [Event Creation] 실패: {e}")


                    
                    # 동일 섹터 경쟁사 조회




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
            future_to_stock = {executor.submit(crawl_stock_news_with_fallback, stock["code"], stock["name"]): stock for stock in universe}
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
            # [2026-01 Optimized] Unified Analysis (Sentiment + Risk)
            process_unified_analysis(new_documents_to_add)
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
