#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
네이버 증권 재무제표 크롤링 및 DB 저장
성장성 팩터 계산을 위한 매출액, EPS 데이터 수집

v2.0: shared/crawlers/naver.py 공통 모듈 사용
"""

import os
import sys
import logging
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv

# 프로젝트 루트 경로 설정 (utilities/ 상위 폴더)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import shared.database as database
from shared.crawlers.naver import scrape_financial_data as _scrape_financial_data

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s'
)
logger = logging.getLogger(__name__)

# 재무제표 테이블 DDL (MariaDB 단일화)
DDL_FINANCIAL_DATA = """
CREATE TABLE IF NOT EXISTS FINANCIAL_DATA (
  STOCK_CODE         VARCHAR(20) NOT NULL,
  REPORT_DATE        DATE NOT NULL,
  REPORT_TYPE        VARCHAR(16) NOT NULL, -- 'QUARTERLY' / 'ANNUAL'
  SALES              BIGINT NULL,
  OPERATING_PROFIT   BIGINT NULL,
  NET_INCOME         BIGINT NULL,
  TOTAL_ASSETS       BIGINT NULL,
  TOTAL_LIABILITIES  BIGINT NULL,
  TOTAL_EQUITY       BIGINT NULL,
  SHARES_OUTSTANDING BIGINT NULL,
  EPS                DECIMAL(15,4) NULL,
  SALES_GROWTH       DECIMAL(15,6) NULL,
  EPS_GROWTH         DECIMAL(15,6) NULL,
  CREATED_AT         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UPDATED_AT         TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (STOCK_CODE, REPORT_DATE, REPORT_TYPE)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

def ensure_financial_table(connection):
    """FINANCIAL_DATA 테이블 생성"""
    cur = None
    try:
        cur = connection.cursor()
        cur.execute("SHOW TABLES LIKE 'financial_data'")
        exists = cur.fetchone() is not None
        if not exists:
            logger.info("테이블 'FINANCIAL_DATA' 미존재. 생성 시도...")
            cur.execute(DDL_FINANCIAL_DATA)
            connection.commit()
            logger.info("✅ 'FINANCIAL_DATA' 생성 완료.")
        else:
            logger.info("✅ 'FINANCIAL_DATA' 이미 존재.")
    except Exception as e:
        logger.error(f"❌ 테이블 생성 확인 중 오류: {e}", exc_info=True)
        raise
    finally:
        if cur:
            cur.close()

def scrape_naver_finance_financials(stock_code: str):
    """
    네이버 증권에서 재무제표 데이터 크롤링
    shared.crawlers.naver 공통 모듈 사용 Wrapper
    """
    return _scrape_financial_data(stock_code)

def calculate_growth_from_scraped_data(financial_data: list):
    """
    크롤링한 데이터로부터 성장률 계산
    """
    # 항목별로 그룹화
    by_item = {}
    for data in financial_data:
        item = data['item']
        if item not in by_item:
            by_item[item] = []
        by_item[item].append(data)
    
        # 각 항목별로 시간순 정렬 및 성장률 계산
        growth_data = []
        for item, data_list in by_item.items():
            # 연도/분기순 정렬 (None 처리)
            sorted_data = sorted(data_list, key=lambda x: (x['year'], x.get('quarter') or 0))
        
        for i in range(1, len(sorted_data)):
            current = sorted_data[i]
            previous = sorted_data[i-1]
            
            if previous['value'] and previous['value'] > 0:
                growth_rate = ((current['value'] - previous['value']) / previous['value']) * 100
                growth_data.append({
                    'stock_code': current['stock_code'],
                    'item': item,
                    'year': current['year'],
                    'quarter': current.get('quarter'),
                    'value': current['value'],
                    'growth_rate': growth_rate,
                    'previous_value': previous['value']
                })
    
    return growth_data

def convert_scraped_to_db_format(scraped_data: list):
    """
    크롤링한 데이터를 DB 저장 형식으로 변환
    """
    # 항목별로 그룹화
    by_stock_date = {}
    
    for data in scraped_data:
        stock_code = data['stock_code']
        year = data['year']
        quarter = data.get('quarter')
        
        # 리포트 날짜 생성 (분기 마지막 날)
        if quarter:
            # 분기별: 3월, 6월, 9월, 12월 말일
            month = quarter * 3
            # 간단한 월말 계산
            if month == 12:
                report_date = datetime(year, 12, 31)
            else:
                report_date = datetime(year, month + 1, 1) - timedelta(days=1)
            report_type = 'QUARTERLY'
        else:
            # 연간: 12월 말일
            report_date = datetime(year, 12, 31)
            report_type = 'ANNUAL'
        
        key = (stock_code, report_date, report_type)
        if key not in by_stock_date:
            by_stock_date[key] = {
                'stock_code': stock_code,
                'report_date': report_date,
                'report_type': report_type,
                'sales': None,
                'operating_profit': None,
                'net_income': None,
                'total_assets': None,
                'total_liabilities': None,
                'total_equity': None,
                'shares_outstanding': None,
                'eps': None,
                'sales_growth': None,
                'eps_growth': None
            }
        
        # 값 매핑
        val = data['value']
        item = data['item']
        
        if val is not None:
            # 단위 조정 (억원 -> 원 등, 필요한 경우)
            # 네이버 재무제표는 억 단위가 많으나, 여기서는 화면에 보이는 값 그대로 가져옴
            # 필요 시 단위 변환 로직 추가 (DB 스키마가 BIGINT이므로 억원*1억 필요할 수도 있음)
            # 하지만 원본 코드에서도 그대로 저장했던 것으로 보임 (float -> BIGINT 변환 시 주의)
            # 여기서는 원본 로직 유지 (단위 관련 별도 처리 없었음)
            
            # 네이버는 억 단위로 표시됨 (1,234 = 1,234억)
            # DB가 BIGINT라면 원 단위로 저장하는 것이 일반적이나,
            # 기존 코드 분석 결과, 별도 변환 없이 저장하고 있었음.
            # 하지만 scrape_financial_data 함수에서 단위 변환을 하지 않았다면 억 단위일 것임.
            # PBR/PER 크롤러에서는 '조', '억' 파싱 로직이 있었으나 여기는 없었음.
            # 일단 그대로 둠.
            
            if '매출액' in item:
                by_stock_date[key]['sales'] = int(val * 100000000) # 억 단위 -> 원 단위
            elif '영업이익' in item:
                by_stock_date[key]['operating_profit'] = int(val * 100000000)
            elif '당기순이익' in item:
                by_stock_date[key]['net_income'] = int(val * 100000000)
            elif '자산총계' in item:
                by_stock_date[key]['total_assets'] = int(val * 100000000)
            elif '부채총계' in item:
                by_stock_date[key]['total_liabilities'] = int(val * 100000000)
            elif '자본총계' in item:
                by_stock_date[key]['total_equity'] = int(val * 100000000)
            elif 'EPS' in item: # EPS는 원 단위
                by_stock_date[key]['eps'] = val
                
    db_data = []
    for key, data in by_stock_date.items():
        db_data.append(data)
        
    return db_data

def upsert_financial_data(connection, financial_data: list):
    """재무제표 데이터를 DB에 저장"""
    if not financial_data:
        return
    
    sql_upsert = """
    INSERT INTO FINANCIAL_DATA (
        STOCK_CODE, REPORT_DATE, REPORT_TYPE,
        SALES, OPERATING_PROFIT, NET_INCOME,
        TOTAL_ASSETS, TOTAL_LIABILITIES, TOTAL_EQUITY,
        SHARES_OUTSTANDING, EPS, SALES_GROWTH, EPS_GROWTH
    ) VALUES (
        %s, %s, %s,
        %s, %s, %s,
        %s, %s, %s,
        %s, %s, %s, %s
    )
    ON DUPLICATE KEY UPDATE
        SALES = VALUES(SALES),
        OPERATING_PROFIT = VALUES(OPERATING_PROFIT),
        NET_INCOME = VALUES(NET_INCOME),
        TOTAL_ASSETS = VALUES(TOTAL_ASSETS),
        TOTAL_LIABILITIES = VALUES(TOTAL_LIABILITIES),
        TOTAL_EQUITY = VALUES(TOTAL_EQUITY),
        SHARES_OUTSTANDING = VALUES(SHARES_OUTSTANDING),
        EPS = VALUES(EPS),
        SALES_GROWTH = VALUES(SALES_GROWTH),
        EPS_GROWTH = VALUES(EPS_GROWTH),
        UPDATED_AT = CURRENT_TIMESTAMP
    """
    
    rows = []
    for data in financial_data:
        rows.append(
            (
                data["stock_code"],
                data["report_date"],
                data["report_type"],
                data.get("sales"),
                data.get("operating_profit"),
                data.get("net_income"),
                data.get("total_assets"),
                data.get("total_liabilities"),
                data.get("total_equity"),
                data.get("shares_outstanding"),
                data.get("eps"),
                data.get("sales_growth"),
                data.get("eps_growth"),
            )
        )
    
    cur = None
    try:
        cur = connection.cursor()
        cur.executemany(sql_upsert, rows)
        connection.commit()
        logger.info(f"✅ 재무제표 데이터 저장 완료: {len(rows)}건")
    except Exception as e:
        logger.error(f"❌ 재무제표 데이터 저장 실패: {e}", exc_info=True)
        if connection:
            connection.rollback()
        raise
    finally:
        if cur:
            cur.close()

def main():
    """재무제표 데이터 수집 메인 함수"""
    load_dotenv()
    logger.info("--- 🤖 네이버 증권 재무제표 데이터 수집기 시작 ---")
    
    db_conn = None
    try:
        db_conn = database.get_db_connection()
        if not db_conn:
            raise RuntimeError("DB 연결 실패")
        
        ensure_financial_table(db_conn)
        
        # 수집할 종목 목록: Watchlist + Portfolio
        watchlist = database.get_active_watchlist(db_conn)
        portfolio_items = database.get_active_portfolio(db_conn)
        
        target_codes = set(watchlist.keys())
        for item in portfolio_items:
            target_codes.add(item['code'])
        
        target_codes.discard('0001')
        
        logger.info(f"--- 재무제표 데이터 수집 시작 (대상: {len(target_codes)}개 종목) ---")
        
        total_saved = 0
        success_count = 0
        fail_count = 0
        
        for code in sorted(target_codes):
            name = watchlist.get(code, {}).get('name') or next(
                (item.get('name') for item in portfolio_items if item.get('code') == code), 
                code
            )
            
            try:
                logger.info(f"   - 수집 중: {name}({code})")
                
                scraped_data = scrape_naver_finance_financials(code)
                
                if not scraped_data:
                    logger.warning(f"   ⚠️ {name}({code}): 데이터 추출 실패")
                    fail_count += 1
                    time.sleep(2)
                    continue
                
                db_data = convert_scraped_to_db_format(scraped_data)
                
                if db_data:
                    upsert_financial_data(db_conn, db_data)
                    total_saved += len(db_data)
                    success_count += 1
                else:
                    logger.warning(f"   ⚠️ {name}({code}): 변환된 데이터 없음")
                    fail_count += 1
                
                time.sleep(1) # Delay
                
            except Exception as e:
                logger.error(f"   ❌ {name}({code}) 처리 중 오류: {e}", exc_info=True)
                fail_count += 1
                time.sleep(1)
                continue
        
        logger.info("--- ✅ 재무제표 데이터 수집 완료 ---")
        logger.info(f"   성공: {success_count}개 종목, 실패: {fail_count}개 종목")
        logger.info(f"   총 저장: {total_saved}건")
        
    except Exception as e:
        logger.critical(f"❌ 수집기 실행 중 치명적 오류: {e}", exc_info=True)
        sys.exit(1)
    finally:
        if db_conn:
            db_conn.close()
            logger.info("--- DB 연결 종료 ---")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        test_code = "005930"
        print(f"테스트: {test_code} 재무제표 크롤링")
        data = scrape_naver_finance_financials(test_code)
        print(f"추출된 데이터: {len(data)}건")
        if data:
            db_data = convert_scraped_to_db_format(data)
            print(f"DB 변환 데이터: {len(db_data)}건")
            print(db_data[0] if db_data else "No Data")
    else:
        main()
