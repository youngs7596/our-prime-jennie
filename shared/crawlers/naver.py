#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shared/crawlers/naver.py
------------------------
네이버 금융 크롤링 공통 모듈

이 모듈은 네이버 금융에서 데이터를 수집하는 모든 함수를 통합합니다:
- 종목 뉴스 크롤링 (news_news.naver) - EUC-KR
- 시총 상위 종목 조회 (sise_market_sum.naver) - EUC-KR
- 재무제표/투자지표 크롤링 (main.naver) - UTF-8

사용 예:
    from shared.crawlers.naver import crawl_stock_news, get_kospi_top_stocks
    
    news = crawl_stock_news("005930", "삼성전자", max_pages=2)
    stocks = get_kospi_top_stocks(limit=200)
"""

import logging
import time
import hashlib
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ==============================================================================
# 공통 상수
# ==============================================================================

NAVER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

NOISE_KEYWORDS = [
    "특징주", "오전 시황", "장마감", "마감 시황", "급등락",
    "오늘의 증시", "환율", "개장", "출발", "상위 종목",
    "단독", "인포", "증권리포트", "NEW", "장중시황", 
    "[이슈종합]", "인기 기업", "한줄리포트", "이 시각 증권"
]

# 내부 중복 체크용 (모듈 레벨)
_seen_news_hashes: set = set()


# ==============================================================================
# 유틸리티 함수
# ==============================================================================

def _compute_news_hash(title: str) -> str:
    """뉴스 제목으로 중복 체크용 해시 생성"""
    normalized = re.sub(r'[^\w]', '', title.lower())
    return hashlib.md5(normalized.encode()).hexdigest()[:12]


def _is_noise_title(title: str) -> bool:
    """노이즈 뉴스인지 확인"""
    for noise in NOISE_KEYWORDS:
        if noise in title:
            return True
    return False


def clear_news_hash_cache():
    """뉴스 중복 체크 캐시 초기화 (테스트용)"""
    global _seen_news_hashes
    _seen_news_hashes.clear()


# ==============================================================================
# 뉴스 크롤링 (news_news.naver) - EUC-KR 인코딩
# ==============================================================================

def crawl_stock_news(
    stock_code: str, 
    stock_name: str, 
    max_pages: int = 2,
    request_delay: float = 0.3,
    deduplicate: bool = True
) -> List[Dict[str, Any]]:
    """
    네이버 금융 종목 뉴스 크롤링
    
    Args:
        stock_code: 종목 코드 (6자리)
        stock_name: 종목명
        max_pages: 최대 페이지 수 (기본 2)
        request_delay: 요청 간 지연 시간 (초)
        deduplicate: 중복 제거 여부 (모듈 레벨 캐시 사용)
    
    Returns:
        뉴스 문서 리스트:
        [{
            "page_content": "뉴스 제목: ...\n링크: ...",
            "metadata": {
                "stock_code": "005930",
                "stock_name": "삼성전자",
                "source": "Naver Finance",
                "source_url": "https://...",
                "created_at_utc": 1234567890
            }
        }, ...]
    """
    global _seen_news_hashes
    
    documents = []
    headers = {
        **NAVER_HEADERS,
        'Referer': f'https://finance.naver.com/item/news.naver?code={stock_code}'
    }
    
    for page in range(1, max_pages + 1):
        try:
            url = f"https://finance.naver.com/item/news_news.naver?code={stock_code}&page={page}"
            resp = requests.get(url, headers=headers, timeout=10)
            resp.encoding = 'euc-kr'  # 중요: 네이버 금융 뉴스는 EUC-KR!
            
            soup = BeautifulSoup(resp.text, 'html.parser')
            news_table = soup.select_one('table.type5')
            
            if not news_table:
                logger.debug(f"[Naver News] 뉴스 테이블 없음 - {stock_code} page {page}")
                break
            
            rows = news_table.select('tr')  # tbody 사용 금지 (없음)
            page_count = 0
            
            for row in rows:
                # td.title 찾기 (셀렉터 주의)
                title_td = row.select_one('td.title')
                if not title_td:
                    continue
                
                link_tag = title_td.select_one('a')
                if not link_tag:
                    continue
                
                title = link_tag.text.strip()
                href = link_tag.get('href', '')
                
                if not title:
                    continue
                
                # 노이즈 필터링
                if _is_noise_title(title):
                    continue
                
                # 중복 체크
                if deduplicate:
                    news_hash = _compute_news_hash(title)
                    if news_hash in _seen_news_hashes:
                        continue
                    _seen_news_hashes.add(news_hash)
                
                # 상대 URL 처리
                if href.startswith('/'):
                    href = f"https://finance.naver.com{href}"
                
                # 날짜 파싱
                date_td = row.select_one('td.date')
                date_str = date_td.text.strip() if date_td else ""
                try:
                    if date_str:
                        pub_date = datetime.strptime(date_str, "%Y.%m.%d %H:%M")
                        pub_timestamp = int(pub_date.replace(tzinfo=timezone.utc).timestamp())
                    else:
                        pub_timestamp = int(datetime.now(timezone.utc).timestamp())
                except Exception:
                    pub_timestamp = int(datetime.now(timezone.utc).timestamp())
                
                # Phase 1C: 메타데이터 강화 - 종목명/코드/출처/날짜를 page_content에 포함
                pub_date_str = datetime.fromtimestamp(pub_timestamp, tz=timezone.utc).strftime('%Y-%m-%d')
                documents.append({
                    "page_content": f"[{stock_name}({stock_code})] {title} | 출처: Naver Finance | 날짜: {pub_date_str}",
                    "metadata": {
                        "stock_code": stock_code,
                        "stock_name": stock_name,
                        "source": "Naver Finance",
                        "source_url": href,
                        "created_at_utc": pub_timestamp,
                    }
                })
                page_count += 1
            
            logger.debug(f"[Naver News] {stock_code} page {page}: {page_count}건")
            
            if page < max_pages:
                time.sleep(request_delay)
        
        except Exception as e:
            logger.warning(f"[Naver News] 크롤링 오류 ({stock_code} page {page}): {e}")
            break
    
    return documents


# ==============================================================================
# 시총 상위 종목 (sise_market_sum.naver) - EUC-KR 인코딩
# ==============================================================================

def get_kospi_top_stocks(limit: int = 200) -> List[Dict[str, Any]]:
    """
    네이버 금융에서 KOSPI 시총 상위 종목 조회
    
    Args:
        limit: 가져올 종목 수 (기본 200)
    
    Returns:
        종목 리스트:
        [{
            "code": "005930",
            "name": "삼성전자",
            "price": 87000.0,
            "change_pct": 1.5,
            "rank": 1
        }, ...]
    """
    return _get_market_cap_stocks(market="kospi", limit=limit)


def get_kosdaq_top_stocks(limit: int = 100) -> List[Dict[str, Any]]:
    """
    네이버 금융에서 KOSDAQ 시총 상위 종목 조회
    
    Args:
        limit: 가져올 종목 수 (기본 100)
    
    Returns:
        종목 리스트 (get_kospi_top_stocks와 동일 형식)
    """
    return _get_market_cap_stocks(market="kosdaq", limit=limit)


def _get_market_cap_stocks(market: str, limit: int) -> List[Dict[str, Any]]:
    """시총 상위 종목 내부 구현"""
    universe = []
    
    # sosok: 0=KOSPI, 1=KOSDAQ
    sosok = "0" if market == "kospi" else "1"
    
    try:
        pages_needed = (limit // 50) + 1
        current_rank = 0
        
        for page in range(1, pages_needed + 1):
            if len(universe) >= limit:
                break
            
            url = f'https://finance.naver.com/sise/sise_market_sum.naver?sosok={sosok}&page={page}'
            resp = requests.get(url, headers=NAVER_HEADERS, timeout=10)
            resp.encoding = 'euc-kr'  # 중요: EUC-KR 인코딩
            
            soup = BeautifulSoup(resp.text, 'html.parser')
            rows = soup.select('table.type_2 tbody tr')
            
            for row in rows:
                if len(universe) >= limit:
                    break
                
                cells = row.select('td')
                if len(cells) < 10:
                    continue
                
                try:
                    # 2번째 TD에 링크와 종목명
                    name_cell = cells[1]
                    link = name_cell.select_one('a')
                    if not link:
                        continue
                    
                    name = link.text.strip()
                    href = link.get('href', '')
                    code = href.split('code=')[1] if 'code=' in href else ''
                    
                    if not (code and len(code) == 6 and code.isdigit()):
                        continue
                    
                    current_rank += 1
                    
                    # 현재가
                    price_str = cells[2].text.strip().replace(',', '')
                    price = float(price_str) if price_str else 0
                    
                    # 등락률 (5번째 컬럼)
                    rate_txt = cells[4].text.strip().replace('%', '').replace(',', '')
                    change_pct = float(rate_txt) if rate_txt else 0.0
                    
                    universe.append({
                        "code": code,
                        "name": name,
                        "price": price,
                        "change_pct": change_pct,
                        "rank": current_rank
                    })
                    
                except (ValueError, IndexError):
                    continue
        
        if universe:
            logger.info(f"[Naver Stock] {market.upper()} 시총 상위 {len(universe)}개 종목 로드 완료")
        
    except Exception as e:
        logger.warning(f"[Naver Stock] {market.upper()} 종목 스크래핑 실패: {e}")
    
    return universe


# ==============================================================================
# 재무제표 크롤링 (main.naver) - UTF-8 인코딩
# ==============================================================================

def scrape_financial_data(stock_code: str) -> List[Dict[str, Any]]:
    """
    네이버 증권에서 재무제표 데이터 크롤링
    
    Args:
        stock_code: 종목 코드 (6자리)
    
    Returns:
        재무제표 데이터 리스트:
        [{
            'stock_code': '005930',
            'year': 2024,
            'quarter': 4,
            'item': '매출액',
            'value': 123456789.0,
            'date_raw': '2024.12'
        }, ...]
    """
    url = f"https://finance.naver.com/item/main.naver?code={stock_code}"
    financial_data = []
    
    try:
        response = requests.get(url, headers=NAVER_HEADERS, timeout=10)
        # main.naver는 UTF-8 응답 (encoding 설정 불필요)
        
        if response.status_code != 200:
            logger.warning(f"[Naver Financial] {stock_code} 페이지 접근 실패: {response.status_code}")
            return financial_data
        
        soup = BeautifulSoup(response.text, 'html.parser')
        tables = soup.find_all('table', class_='tb_type1')
        
        for table in tables:
            rows = table.find_all('tr')
            
            # 헤더 행 찾기
            header_row = None
            for row in rows:
                cells = row.find_all(['th', 'td'])
                if len(cells) > 5:
                    header_text = ' '.join([cell.get_text(strip=True) for cell in cells])
                    if any(keyword in header_text for keyword in ['2024', '2023', '2022', '분기']):
                        header_row = cells
                        break
            
            if not header_row:
                continue
            
            # 헤더에서 날짜 정보 추출
            dates = []
            for cell in header_row[1:]:
                date_text = cell.get_text(strip=True)
                date_match = re.search(r'(\d{4})[./년\s]+(\d{1,2})', date_text)
                if date_match:
                    year = int(date_match.group(1))
                    quarter_or_month = int(date_match.group(2))
                    dates.append({
                        'year': year,
                        'quarter': quarter_or_month if quarter_or_month <= 4 else None,
                        'raw': date_text
                    })
            
            # 데이터 행 파싱
            for row in rows:
                cells = row.find_all(['td', 'th'])
                if len(cells) < 2:
                    continue
                
                row_label = cells[0].get_text(strip=True)
                
                if '매출액' in row_label or '영업이익' in row_label or '당기순이익' in row_label:
                    values = []
                    for cell in cells[1:]:
                        value_text = cell.get_text(strip=True).replace(',', '')
                        try:
                            value = float(value_text) if value_text else None
                            values.append(value)
                        except:
                            values.append(None)
                    
                    for i, date_info in enumerate(dates):
                        if i < len(values) and values[i] is not None:
                            financial_data.append({
                                'stock_code': stock_code,
                                'year': date_info['year'],
                                'quarter': date_info.get('quarter'),
                                'item': row_label,
                                'value': values[i],
                                'date_raw': date_info['raw']
                            })
        
        logger.debug(f"[Naver Financial] {stock_code} 재무제표 {len(financial_data)}건 추출")
        
    except Exception as e:
        logger.error(f"[Naver Financial] {stock_code} 크롤링 오류: {e}")
    
    return financial_data


def scrape_pbr_per_roe(
    stock_code: str, 
    max_retries: int = 3,
    debug: bool = False
) -> Tuple[Optional[float], Optional[float], Optional[float], List[Dict], Optional[float]]:
    """
    네이버 증권에서 PBR, PER, ROE, EPS, 시가총액 크롤링
    
    Args:
        stock_code: 종목 코드 (6자리)
        max_retries: 최대 재시도 횟수
        debug: 디버그 로그 출력 여부
    
    Returns:
        tuple: (PBR, PER, ROE, EPS리스트, 시가총액)
        - EPS리스트: [{'year': 2023, 'eps': 2131.0}, {'year': 2024, 'eps': 4950.0}]
        - 실패 시: (None, None, None, [], None)
    """
    url = f"https://finance.naver.com/item/main.naver?code={stock_code}"
    
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                wait_time = attempt * 2
                if debug:
                    logger.info(f"[Naver PBR/PER] {stock_code} 재시도 {attempt+1}/{max_retries}")
                time.sleep(wait_time)
            
            response = requests.get(url, headers=NAVER_HEADERS, timeout=15)
            
            if response.status_code != 200:
                if debug:
                    logger.warning(f"[Naver PBR/PER] {stock_code} HTTP {response.status_code}")
                continue
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            pbr, per, roe = None, None, None
            eps_list = []
            market_cap = None
            
            tables = soup.find_all('table')
            
            # PER, PBR 찾기
            for table in tables:
                rows = table.find_all('tr')
                for row in rows:
                    cells = row.find_all(['th', 'td'])
                    for i, cell in enumerate(cells):
                        text = cell.get_text(strip=True)
                        
                        if text.startswith('PER') and 'EPS' in text:
                            if i + 1 < len(cells):
                                value_text = cells[i + 1].get_text(strip=True)
                                if '배' in value_text:
                                    try:
                                        per = float(value_text.split('배')[0].replace(',', ''))
                                    except:
                                        pass
                        
                        if text.startswith('PBR') and 'BPS' in text:
                            if i + 1 < len(cells):
                                value_text = cells[i + 1].get_text(strip=True)
                                if '배' in value_text:
                                    try:
                                        pbr = float(value_text.split('배')[0].replace(',', ''))
                                    except:
                                        pass
            
            # ROE, EPS 찾기 (주요재무정보 테이블)
            for table in tables:
                table_text = table.get_text()
                if '주요재무정보' in table_text or 'tb_type1_ifrs' in table.get('class', []):
                    rows = table.find_all('tr')
                    for row in rows:
                        cells = row.find_all(['th', 'td'])
                        if len(cells) > 0:
                            first_cell = cells[0].get_text(strip=True)
                            
                            if 'ROE' in first_cell and '지배' in first_cell:
                                if len(cells) > 3:
                                    try:
                                        roe_text = cells[3].get_text(strip=True).replace(',', '')
                                        if roe_text:
                                            roe = float(roe_text)
                                    except:
                                        pass
                            
                            if 'EPS' in first_cell and '원' in first_cell:
                                for data_idx, year in [(2, 2023), (3, 2024)]:
                                    if len(cells) > data_idx:
                                        try:
                                            eps_text = cells[data_idx].get_text(strip=True).replace(',', '')
                                            if eps_text:
                                                eps_list.append({'year': year, 'eps': float(eps_text)})
                                        except:
                                            pass
                    break
            
            # 시가총액 찾기
            market_cap_elem = soup.find('em', string=lambda x: x and '시가총액' in x)
            if market_cap_elem:
                next_elem = market_cap_elem.find_next('em')
                if next_elem:
                    mc_text = next_elem.get_text(strip=True).replace(',', '')
                    try:
                        if '조' in mc_text:
                            parts = mc_text.split('조')
                            trillion = float(parts[0])
                            billion = 0
                            if len(parts) > 1 and '억' in parts[1]:
                                billion = float(parts[1].replace('억', '').strip())
                            market_cap = trillion * 1000000 + billion * 100
                        elif '억' in mc_text:
                            market_cap = float(mc_text.replace('억', '').strip()) * 100
                    except:
                        pass
            
            if debug:
                logger.info(f"[Naver PBR/PER] {stock_code}: PBR={pbr}, PER={per}, ROE={roe}, EPS={len(eps_list)}개")
            
            return pbr, per, roe, eps_list, market_cap
        
        except requests.exceptions.Timeout:
            if debug:
                logger.warning(f"[Naver PBR/PER] {stock_code} 타임아웃")
        except requests.exceptions.RequestException as e:
            if debug:
                logger.warning(f"[Naver PBR/PER] {stock_code} 네트워크 오류: {e}")
        except Exception as e:
            if debug:
                logger.error(f"[Naver PBR/PER] {stock_code} 크롤링 실패: {e}")
    
    logger.warning(f"[Naver PBR/PER] {stock_code} 최종 실패 ({max_retries}회 시도)")
    return None, None, None, [], None


# ==============================================================================
# 업종(섹터) 크롤링 (sise_group.naver) - EUC-KR 인코딩
# ==============================================================================

def get_naver_sector_list() -> List[Dict[str, Any]]:
    """
    네이버 금융 업종 목록 조회

    URL: https://finance.naver.com/sise/sise_group.naver?type=upjong

    Returns:
        업종 리스트:
        [{"sector_no": "261", "sector_name": "반도체", "change_pct": 1.2}, ...]
    """
    url = "https://finance.naver.com/sise/sise_group.naver?type=upjong"
    sectors = []

    try:
        resp = requests.get(url, headers=NAVER_HEADERS, timeout=10)
        resp.encoding = 'euc-kr'

        soup = BeautifulSoup(resp.text, 'html.parser')
        rows = soup.select('table.type_1 tr')

        for row in rows:
            link = row.select_one('td a')
            if not link:
                continue

            href = link.get('href', '')
            name = link.text.strip()

            if not name or 'no=' not in href:
                continue

            # URL에서 업종 번호 추출
            sector_no = href.split('no=')[-1].split('&')[0]

            # 등락률 (3번째 td)
            cells = row.select('td')
            change_pct = 0.0
            if len(cells) >= 3:
                pct_text = cells[2].text.strip().replace('%', '').replace(',', '')
                try:
                    change_pct = float(pct_text) if pct_text else 0.0
                except ValueError:
                    change_pct = 0.0

            sectors.append({
                'sector_no': sector_no,
                'sector_name': name,
                'change_pct': change_pct,
            })

        logger.info(f"[Naver Sector] {len(sectors)}개 업종 목록 로드 완료")

    except Exception as e:
        logger.warning(f"[Naver Sector] 업종 목록 크롤링 실패: {e}")

    return sectors


def get_naver_sector_stocks(sector_no: str) -> List[Dict[str, str]]:
    """
    특정 업종의 소속 종목 목록 조회

    URL: https://finance.naver.com/sise/sise_group_detail.naver?type=upjong&no={sector_no}

    Args:
        sector_no: 업종 번호 (예: "261")

    Returns:
        종목 리스트:
        [{"code": "005930", "name": "삼성전자"}, ...]
    """
    url = f"https://finance.naver.com/sise/sise_group_detail.naver?type=upjong&no={sector_no}"
    stocks = []

    try:
        resp = requests.get(url, headers=NAVER_HEADERS, timeout=10)
        resp.encoding = 'euc-kr'

        soup = BeautifulSoup(resp.text, 'html.parser')
        rows = soup.select('table.type_5 tr')

        for row in rows:
            link = row.select_one('td a')
            if not link:
                continue

            href = link.get('href', '')
            name = link.text.strip()

            if not name or 'code=' not in href:
                continue

            code = href.split('code=')[-1].split('&')[0]
            if code and len(code) == 6 and code.isdigit():
                stocks.append({'code': code, 'name': name})

    except Exception as e:
        logger.warning(f"[Naver Sector] 업종 {sector_no} 종목 크롤링 실패: {e}")

    return stocks


def build_naver_sector_mapping(request_delay: float = 0.3) -> Dict[str, str]:
    """
    전체 종목→업종 매핑 구축 (모든 업종 순회)

    Args:
        request_delay: 업종별 요청 간 지연(초). 기본 0.3초.

    Returns:
        종목코드→업종명 매핑:
        {"005930": "반도체", "000660": "반도체", "005380": "자동차", ...}
        약 40회 요청, delay 0.3초 기준 ~12초 소요
    """
    mapping: Dict[str, str] = {}

    sectors = get_naver_sector_list()
    if not sectors:
        logger.warning("[Naver Sector] 업종 목록이 비어 있어 매핑 구축 불가")
        return mapping

    logger.info(f"[Naver Sector] {len(sectors)}개 업종 순회하여 종목 매핑 구축 시작...")

    for i, sector in enumerate(sectors):
        sector_no = sector['sector_no']
        sector_name = sector['sector_name']

        stocks = get_naver_sector_stocks(sector_no)
        for stock in stocks:
            # 첫 등장 업종을 사용 (중복 종목은 무시)
            if stock['code'] not in mapping:
                mapping[stock['code']] = sector_name

        if i < len(sectors) - 1:
            time.sleep(request_delay)

    logger.info(f"[Naver Sector] 매핑 구축 완료: {len(mapping)}개 종목")
    return mapping
