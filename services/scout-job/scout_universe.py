# services/scout-job/scout_universe.py
# Version: v1.0
# Scout Job Universe Selection - 섹터 분석 및 종목 선별 함수
#
# scout.py에서 분리된 종목 유니버스 관리 함수들

import logging
import time
import requests
from bs4 import BeautifulSoup
from typing import Dict, List, Optional

import shared.database as database

logger = logging.getLogger(__name__)

# FinanceDataReader (optional)
try:
    import FinanceDataReader as fdr
    FDR_AVAILABLE = True
except ImportError:
    FDR_AVAILABLE = False
    logger.warning("⚠️ FinanceDataReader 미설치 - 네이버 금융 스크래핑으로 폴백")


# 정적 우량주 목록 (Fallback용)
BLUE_CHIP_STOCKS = [
    {"code": "0001", "name": "KOSPI", "is_tradable": False},
    {"code": "005930", "name": "삼성전자", "is_tradable": True},
    {"code": "000660", "name": "SK하이닉스", "is_tradable": True},
    {"code": "035420", "name": "NAVER", "is_tradable": True},
    {"code": "035720", "name": "카카오", "is_tradable": True},
]


# 섹터 분류 (KOSPI 주요 섹터)
SECTOR_MAPPING = {
    # 1. 반도체/IT/하드웨어
    '005930': '반도체', '000660': '반도체', '005935': '반도체', '042700': '반도체', # 삼성전자, SK하이닉스, 삼성전자우, 한미반도체
    '007660': '반도체', '000990': '반도체', '014680': '반도체', '353200': '반도체', # 이수페타시스, DB하이텍, 한솔케미칼, 대덕전자
    '011070': 'IT/전자', '009150': 'IT/전자', '066570': 'IT/전자', '018260': 'IT/전자', # LG이노텍, 삼성전기, LG전자, 삼성SDS
    
    # 2. 배터리/2차전지/화학
    '373220': '배터리', '006400': '배터리', '051910': '화학', # LG에너지솔루션, 삼성SDI, LG화학
    '096770': '에너지', '010950': '에너지', '003670': '배터리', '361610': '배터리', # SK이노베이션, S-Oil, 포스코퓨처엠, SKIET
    '066970': '배터리', '011790': '배터리', '450080': '배터리', '457190': '배터리', # 엘앤에프, SKC, 에코프로머티, 이수스페셜티케미컬
    '020150': '배터리', '005070': '배터리', '011780': '화학', '011170': '화학', '010060': '화학', # 롯데에너지머티, 코스모신소재, 금호석유, 롯데케미칼, OCI홀딩스
    
    # 3. 자동차/모빌리티
    '005380': '자동차', '000270': '자동차', '012330': '자동차', '005385': '자동차', '005387': '자동차', # 현대차, 기아, 현대모비스
    '204320': '자동차', '005850': '자동차', '011210': '자동차', '073240': '자동차', '007340': '자동차', # HL만도, 에스엘, 현대위아, 금호타이어, DN오토모티브
    '161390': '자동차', '307950': '자동차', # 한국타이어, 현대오토에버
    
    # 4. 조선/기계/방산/우주
    '329180': '조선', '042660': '조선', '010140': '조선', '071970': '조선', '439260': '조선', # HD현대중공업, 한화오션, 삼성중공업, 마린엔진, 대한조선
    '009540': '조선', '097230': '조선', '017960': '조선', '082740': '조선', '077970': '조선', # 한국조선해양 (지주지만 조선분류), HJ중공업, 한국카본, 한화엔진, STX엔진
    '012450': '방산', '064350': '방산', '047810': '방산', '272210': '방산', '079550': '방산', # 한화에어로, 현대로템, KAI, 한화시스템, LIG넥스원
    '103140': '방산', '003570': '방산', # 풍산, SNT다이내믹스
    '241560': '기계', '454910': '기계', '017800': '기계', '267270': '기계', '042670': '기계', # 두산밥캣, 두산로보틱스, 현대엘리베이터, HD현대건설기계, HD현대인프라코어
    
    # 5. 에너지/전력/인프라
    '034020': '에너지', '267260': '에너지', '298040': '에너지', '010120': '에너지', '001440': '에너지', # 두산에너빌리티, HD현대일렉, 효성중공업, LS ELECTRIC, 대한전선
    '062040': '에너지', '036460': '에너지', '052690': '에너지', '103590': '에너지', '051600': '에너지', # 산일전기, 가스공사, 한전기술, 일진전기, 한전KPS
    '018670': '에너지', '336260': '에너지', '112610': '에너지', # SK가스, 두산퓨얼셀, 씨에스윈드
    '015760': '인프라', '088980': '인프라', # 한국전력, 맥쿼리인프라
    
    # 6. 바이오/헬스케어
    '207940': '바이오', '068270': '바이오', '000100': '바이오', '128940': '바이오', '008930': '바이오', # 삼바, 셀트리온, 유한양행, 한미약품, 한미사이언스
    '302440': '바이오', '326030': '바이오', '009420': '바이오', '069620': '바이오', '006280': '바이오', # SK바이오, SK바사, 한올바이오, 대웅제약, 녹십자
    
    # 7. 인터넷/플랫폼/게임/통신
    '035420': '인터넷', '035720': '인터넷', '323410': '인터넷', '377300': '인터넷', # 네이버, 카카오, 카카오뱅크(?), 카카오페이
    '017670': '통신', '030200': '통신', '032640': '통신', # SK텔레콤, KT, LG유플러스
    '259960': '게임', '036570': '게임', '251270': '게임', '462870': '게임', # 크래프톤, 엔씨소프트, 넷마블, 시프트업
    '352820': '엔터', '030000': '엔터', # 하이브, 제일기획(광고)
    '489790': 'IT', '023590': 'IT', '012510': 'IT', '022100': 'IT', # 한화비전, 다우기술, 더존비즈온, 포스코DX
    
    # 8. 금융/지주
    '105560': '금융', '055550': '금융', '086790': '금융', '316140': '금융', '138040': '금융', # KB, 신한, 하나, 우리, 메리츠
    '071050': '금융', '005830': '금융', '039490': '금융', '005940': '금융', '016360': '금융', # 한투, DB손보, 키움, NH, 삼성증권
    '029780': '금융', '138930': '금융', '175330': '금융', '031210': '금융', '088350': '금융', # 삼성카드, BNK, JB, 서울보증, 한화생명
    '001450': '금융', '139130': '금융', '001720': '금융', '003690': '금융', '085620': '금융', # 현대해상, iM뱅크, 신영, 코리안리, 미래에셋생명
    '006800': '금융', '00680K': '금융', '032830': '금융', '024110': '금융', '000810': '금융',
    '395400': '금융', # SK리츠
    '034730': '지주', '003550': '지주', '402340': '지주', '267250': '지주', '000150': '지주', # SK, LG, SK스퀘어, HD현대, 두산
    '000880': '지주', '006260': '지주', '078930': '지주', '001040': '지주', '004990': '지주', # 한화, LS, GS, CJ, 롯데지주
    '009970': '지주', '000240': '지주', '002790': '지주', '004800': '지주', '000155': '지주', # 영원무역홀딩스, 한국앤컴퍼니, 아모레G, 효성, 두산우
    
    # 9. 소비재/유통/운송
    '005900': '소비재', '090430': '소비재', '033780': '소비재', '278470': '소비재', # (오타수정: 051900->LG생건?), 아모레, KT&G, 에이피알
    '051900': '소비재', # LG생활건강
    '003230': '소비재', '271560': '소비재', '097950': '소비재', '383220': '소비재', '026960': '소비재', # 삼양식품, 오리온, CJ제일제당, F&F, 동서
    '081660': '소비재', '004370': '소비재', '483650': '소비재', '006040': '소비재', '192820': '소비재', # 휠라홀딩스(미스토?), 농심, 달바, 동원산업, 코스맥스
    '007310': '소비재', '161890': '소비재', '008770': '소비재', '032350': '소비재', '034230': '소비재', # 오뚜기, 한국콜마, 호텔신라, 롯데관광, 파라다이스
    '111770': '소비재', '035250': '소비재', # 영원무역, 강원랜드
    '004170': '유통', '139480': '유통', '023530': '유통', '069960': '유통', '282330': '유통', # 신세계, 이마트, 롯데쇼핑, 현대백화점, BGF리테일
    '007070': '유통', '047050': '유통', # GS리테일, 포스코인터내셔널
    '011200': '운송', '003490': '운송', '180640': '운송', '000120': '운송', '028670': '운송', # HMM, 대한항공, 한진칼, CJ대한통운, 팬오션
    '020560': '운송', # 아시아나항공
    
    # 10. 철강/소재/건설
    '005490': '철강', '010130': '철강', '004020': '철강', '001430': '철강', # 포스코홀딩스, 고려아연, 현대제철, 세아베스틸
    '028260': '건설', '000720': '건설', '028050': '건설', '002380': '화학', '006360': '건설', # 삼성물산, 현대건설, 삼성E&A, KCC, GS건설
    '375500': '건설', '047040': '건설', '300720': '건설', # DL이앤씨, 대우건설, 한일시멘트
}



def _resolve_sector(row, code):
    """FDR Sector와 Mapping을 통해 섹터를 결정합니다."""
    sector = row.get('Sector')
    if not sector or str(sector) == 'nan':
        sector = SECTOR_MAPPING.get(code, '기타')
    return sector

def analyze_sector_momentum(kis_api, db_conn, watchlist_snapshot=None):
    """
    섹터별 모멘텀 분석
    각 섹터의 평균 수익률을 계산하여 핫 섹터를 식별합니다.
    
    Returns:
        dict: {섹터명: {'momentum': float, 'stocks': list, 'avg_return': float}}
    """
    logger.info("   (E) 섹터별 모멘텀 분석 시작...")
    
    sector_data = {}
    
    try:
        # KOSPI 200 종목 가져오기
        if FDR_AVAILABLE:
            df_kospi = fdr.StockListing('KOSPI')
            top_200 = df_kospi.head(200) if len(df_kospi) > 200 else df_kospi
            
            for _, row in top_200.iterrows():
                code = str(row.get('Code', row.get('Symbol', ''))).zfill(6)
                name = row.get('Name', row.get('종목명', ''))
                
                # 섹터 분류 (Helper 사용)
                sector = _resolve_sector(row, code)
                
                if sector not in sector_data:
                    sector_data[sector] = {'stocks': [], 'returns': []}
                
                # 최근 수익률 계산 (변동률 % 사용)
                try:
                    change_pct = row.get('ChagesRatio') or row.get('ChangesRatio') or row.get('ChangeRatio')
                    
                    if change_pct is None:
                        changes = float(row.get('Changes', 0))
                        close = float(row.get('Close', row.get('Price', 1)))
                        if close > 0:
                            change_pct = (changes / close) * 100
                        else:
                            change_pct = 0
                    else:
                        change_pct = float(change_pct)
                    
                    if abs(change_pct) > 50:
                        continue
                    
                    sector_data[sector]['stocks'].append({'code': code, 'name': name})
                    sector_data[sector]['returns'].append(change_pct)
                except (ValueError, TypeError):
                    continue
        
        # 섹터별 평균 수익률 계산
        hot_sectors = {}
        for sector, data in sector_data.items():
            if data['returns']:
                avg_return = sum(data['returns']) / len(data['returns'])
                hot_sectors[sector] = {
                    'avg_return': avg_return,
                    'stock_count': len(data['stocks']),
                    'stocks': data['stocks'][:5],
                }
        
        sorted_sectors = sorted(hot_sectors.items(), key=lambda x: x[1]['avg_return'], reverse=True)
        
        logger.info(f"   (E) ✅ 섹터 분석 완료. 핫 섹터 TOP 3:")
        for i, (sector, info) in enumerate(sorted_sectors[:3]):
            logger.info(f"       {i+1}. {sector}: 평균 수익률 {info['avg_return']:.2f}%")
        
        return dict(sorted_sectors)
        
    except Exception as e:
        logger.warning(f"   (E) ⚠️ 섹터 분석 실패: {e}")
        return {}


def get_hot_sector_stocks(sector_analysis, top_n=30):
    """
    핫 섹터의 종목들을 우선 후보로 반환
    상위 3개 섹터의 종목들을 반환합니다.
    """
    if not sector_analysis:
        return []
    
    hot_stocks = []
    sorted_sectors = list(sector_analysis.items())[:3]
    
    for sector, info in sorted_sectors:
        for stock in info.get('stocks', []):
            hot_stocks.append({
                'code': stock['code'],
                'name': stock['name'],
                'sector': sector,
                'sector_momentum': info['avg_return'],
            })
    
    return hot_stocks[:top_n]


def get_dynamic_blue_chips(limit=200):
    """
    KOSPI 시가총액 상위 종목을 수집합니다. (KOSPI 200 기준)
    
    1차: FinanceDataReader 사용 (안정적, 시가총액 순 정렬)
    2차: 네이버 금융 스크래핑 (폴백)
    
    Args:
        limit: 수집할 종목 수 (기본값: 200, KOSPI 200 기준)
    """
    # 1차 시도: FinanceDataReader (권장)
    if FDR_AVAILABLE:
        try:
            logger.info(f"   (A) FinanceDataReader로 KOSPI 시총 상위 {limit}개 조회 중...")
            
            df_kospi = fdr.StockListing('KOSPI')
            
            if 'Marcap' in df_kospi.columns:
                df_sorted = df_kospi.sort_values('Marcap', ascending=False).head(limit)
            elif 'Market' in df_kospi.columns:
                df_sorted = df_kospi.head(limit)
            else:
                df_sorted = df_kospi.head(limit)
            
            dynamic_list = []
            for _, row in df_sorted.iterrows():
                code = str(row.get('Code', row.get('Symbol', ''))).zfill(6)
                name = row.get('Name', row.get('종목명', ''))
                
                # 섹터 정보 추가
                sector = _resolve_sector(row, code)
                
                if code and name:
                    dynamic_list.append({
                        'code': code, 
                        'name': name,
                        'sector': sector  # 섹터 정보 추가
                    })
            
            logger.info(f"   (A) ✅ FinanceDataReader로 {len(dynamic_list)}개 종목 로드 완료. (KOSPI 시총 상위)")
            return dynamic_list
            
        except Exception as e:
            logger.warning(f"   (A) ⚠️ FinanceDataReader 실패, 네이버 금융으로 폴백: {e}")
    
    # 2차 시도: 네이버 금융 스크래핑 (폴백)
    logger.info(f"   (A) 네이버 금융에서 KOSPI 시가총액 상위 {limit}개 스크래핑 시도...")
    dynamic_list = []
    seen_codes = set()
    
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        base_url = "https://finance.naver.com/sise/sise_market_sum.naver?sosok=0"
        
        pages_needed = (limit + 49) // 50
        
        for page in range(1, pages_needed + 1):
            if len(dynamic_list) >= limit:
                break
                
            url = f"{base_url}&page={page}"
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            table = soup.find('table', class_='type_2')
            if not table:
                logger.warning(f"   (A) ⚠️ 페이지 {page} 테이블을 찾지 못했습니다.")
                continue
                
            rows = table.find_all('tr')
            page_count = 0
            for row in rows:
                if len(dynamic_list) >= limit:
                    break
                
                cols = row.find_all('td')
                if len(cols) > 1 and cols[0].text.strip().isdigit():
                    a_tag = cols[1].find('a')
                    if a_tag and 'href' in a_tag.attrs and 'code=' in a_tag['href']:
                        code = a_tag['href'].split('code=')[1]
                        name = a_tag.text.strip()
                        
                        if code not in seen_codes:
                            seen_codes.add(code)
                            dynamic_list.append({'code': code, 'name': name})
                            page_count += 1
            
            logger.debug(f"   (A) 페이지 {page}: {page_count}개 추가 (누적: {len(dynamic_list)}개)")
            
            if page < pages_needed:
                time.sleep(0.3)
        
        logger.info(f"   (A) ✅ 네이버 금융에서 {len(dynamic_list)}개 스크래핑 완료.")
    except Exception as e:
        logger.error(f"   (A) ❌ 동적 우량주 스크래핑 중 오류 발생: {e}")
    
    return dynamic_list


def get_momentum_stocks(kis_api, db_conn, period_months=6, top_n=30, watchlist_snapshot=None):
    """
    모멘텀 팩터 기반 종목 선별
    """
    logger.info(f"   (D) 모멘텀 팩터 계산 중 (기간: {period_months}개월, 상위 {top_n}개)...")
    momentum_scores = []
    
    try:
        # 1. KOSPI 수익률 계산
        kospi_code = "0001"
        period_days = period_months * 30
        kospi_prices = database.get_daily_prices(db_conn, kospi_code, limit=period_days)
        
        if kospi_prices.empty or len(kospi_prices) < period_days * 0.8:
            logger.warning(f"   (D) ⚠️ KOSPI 데이터 부족 ({len(kospi_prices)}일). 모멘텀 계산 건너뜀.")
            return []
        
        kospi_start_price = float(kospi_prices['CLOSE_PRICE'].iloc[0])
        kospi_end_price = float(kospi_prices['CLOSE_PRICE'].iloc[-1])
        kospi_return = (kospi_end_price / kospi_start_price - 1) * 100
        
        # 2. 전체 종목 또는 Watchlist에서 가져오기
        all_codes = database.get_all_stock_codes(db_conn)
        
        if not all_codes:
            watchlist = watchlist_snapshot or database.get_active_watchlist(db_conn)
            if not watchlist:
                stocks_to_check = [s for s in BLUE_CHIP_STOCKS if s.get('is_tradable', True)]
            else:
                stocks_to_check = [{'code': code, 'name': info.get('name', code)} for code, info in watchlist.items() if info.get('is_tradable', True)]
        else:
            stocks_to_check = [{'code': code, 'name': code} for code in all_codes]

        logger.info(f"   (D) {len(stocks_to_check)}개 종목의 모멘텀 계산 중... (전체 대상)")
        
        # 3. 각 종목의 모멘텀 계산
        for stock in stocks_to_check:
            try:
                code = stock['code']
                name = stock.get('name', code)
                
                stock_prices = database.get_daily_prices(db_conn, code, limit=period_days)
                
                if stock_prices.empty or len(stock_prices) < period_days * 0.8:
                    continue
                
                stock_start_price = float(stock_prices['CLOSE_PRICE'].iloc[0])
                stock_end_price = float(stock_prices['CLOSE_PRICE'].iloc[-1])
                stock_return = (stock_end_price / stock_start_price - 1) * 100
                
                relative_momentum = stock_return - kospi_return
                
                momentum_scores.append({
                    'code': code,
                    'name': name,
                    'momentum': relative_momentum,
                    'absolute_return': stock_return,
                    'kospi_return': kospi_return
                })
                
                if hasattr(kis_api, 'API_CALL_DELAY'):
                    time.sleep(kis_api.API_CALL_DELAY * 0.1)
                
            except Exception as e:
                logger.debug(f"   (D) {stock.get('name', stock.get('code'))} 모멘텀 계산 오류: {e}")
                continue
        
        momentum_scores.sort(key=lambda x: x['momentum'], reverse=True)
        
        logger.info(f"   (D) ✅ 모멘텀 계산 완료. 상위 {min(top_n, len(momentum_scores))}개 반환")
        return momentum_scores[:top_n]
        
    except Exception as e:
        logger.error(f"   (D) ❌ 모멘텀 팩터 계산 중 오류 발생: {e}", exc_info=True)
        return []
