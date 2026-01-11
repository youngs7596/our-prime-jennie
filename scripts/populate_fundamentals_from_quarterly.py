
import logging
import pandas as pd
from sqlalchemy import text
from shared.db.connection import ensure_engine_initialized, session_scope

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def populate_fundamentals_pandas():
    """
    Pandas를 사용하여 메모리 내에서 데이터 결합 및 계산을 수행합니다.
    Collation 충돌을 피하고 로직을 단순화합니다.
    """
    ensure_engine_initialized()
    
    START_DATE = '2024-01-01'
    END_DATE = '2026-01-10'
    
    logger.info(f"🚀 재무 데이터 복구 (Pandas) 시작 ({START_DATE} ~ {END_DATE})")
    
    with session_scope() as session:
        # 1. 재무 데이터 (ESP, BPS) 로드
        logger.info("📥 재무 데이터 로드 중...")
        fin_query = text("""
            SELECT STOCK_CODE, QUARTER_DATE, EPS, BPS, ROE 
            FROM FINANCIAL_METRICS_QUARTERLY 
            WHERE EPS > 0 AND BPS > 0
        """)
        fin_df = pd.read_sql(fin_query, session.bind)
        fin_df['QUARTER_DATE'] = pd.to_datetime(fin_df['QUARTER_DATE'])
        fin_df = fin_df.sort_values(['STOCK_CODE', 'QUARTER_DATE'])
        logger.info(f"   - {len(fin_df)}개 분기 재무 데이터 로드 완료")
        
        # 2. 상장 주식 수 로드
        logger.info("📥 상장 주식 수 로드 중...")
        master_query = text("SELECT STOCK_CODE, LISTED_SHARES FROM STOCK_MASTER")
        master_df = pd.read_sql(master_query, session.bind)
        shares_map = master_df.set_index('STOCK_CODE')['LISTED_SHARES'].to_dict()
        
        # 3. 대상 종목 조회 (재무 데이터가 있는 종목만)
        target_stocks = fin_df['STOCK_CODE'].unique()
        logger.info(f"📊 대상 종목: {len(target_stocks)}개")
        
        # 4. 가격 데이터 로드 및 처리 (메모리 절약을 위해 종목별 처리)
        total_inserted = 0
        
        for i, code in enumerate(target_stocks):
            try:
                # 해당 종목의 가격 데이터 조회
                price_query = text("""
                    SELECT STOCK_CODE, PRICE_DATE, CLOSE_PRICE
                    FROM STOCK_DAILY_PRICES_3Y
                    WHERE STOCK_CODE = :code 
                      AND PRICE_DATE BETWEEN :start AND :end
                """)
                price_df = pd.read_sql(price_query, session.bind, params={'code': code, 'start': START_DATE, 'end': END_DATE})
                
                if price_df.empty:
                    continue
                    
                price_df['PRICE_DATE'] = pd.to_datetime(price_df['PRICE_DATE'])
                
                # 해당 종목의 재무 데이터
                stock_fin = fin_df[fin_df['STOCK_CODE'] == code].copy()
                
                if stock_fin.empty:
                    continue
                
                # asof merge를 위해 정렬
                price_df = price_df.sort_values('PRICE_DATE')
                
                # backward search (가장 최근 과거 분기 데이터 매칭)
                merged = pd.merge_asof(
                    price_df, 
                    stock_fin, 
                    left_on='PRICE_DATE', 
                    right_on='QUARTER_DATE', 
                    by='STOCK_CODE',
                    direction='backward'
                )
                
                # 계산 (PER, PBR, Market Cap)
                # EPS, BPS가 없는 경우(NaN) 제외
                merged = merged.dropna(subset=['EPS', 'BPS'])
                
                if merged.empty:
                    continue
                    
                merged['PER'] = (merged['CLOSE_PRICE'] / merged['EPS']).round(2)
                merged['PBR'] = (merged['CLOSE_PRICE'] / merged['BPS']).round(2)
                merged['MARKET_CAP'] = (merged['CLOSE_PRICE'] * shares_map.get(code, 0)).astype(int)
                merged['ROE'] = merged['ROE'].fillna(0)
                
                # DB Insert를 위한 데이터 준비
                records = []
                for _, row in merged.iterrows():
                    records.append({
                        'code': row['STOCK_CODE'],
                        'date': row['PRICE_DATE'].strftime('%Y-%m-%d'),
                        'per': float(row['PER']),
                        'pbr': float(row['PBR']),
                        'roe': float(row['ROE']),
                        'mcap': int(row['MARKET_CAP'])
                    })
                
                # Bulk Insert (ON DUPLICATE KEY UPDATE)
                if records:
                    stmt = text("""
                        INSERT INTO STOCK_FUNDAMENTALS (STOCK_CODE, TRADE_DATE, PER, PBR, ROE, MARKET_CAP, CREATED_AT, UPDATED_AT)
                        VALUES (:code, :date, :per, :pbr, :roe, :mcap, NOW(), NOW())
                        ON DUPLICATE KEY UPDATE
                            PER = VALUES(PER),
                            PBR = VALUES(PBR),
                            ROE = VALUES(ROE),
                            MARKET_CAP = VALUES(MARKET_CAP),
                            UPDATED_AT = NOW()
                    """)
                    session.execute(stmt, records)
                    total_inserted += len(records)
                    
                if (i + 1) % 10 == 0:
                    session.commit()
                    logger.info(f"   [{i+1}/{len(target_stocks)}] {code}: {len(records)}건 처리됨")
                    
            except Exception as e:
                logger.error(f"❌ {code} 처리 중 오류: {e}")
                
        session.commit()
        logger.info(f"✅ 전체 완료! 총 {total_inserted}건 삽입됨")

if __name__ == "__main__":
    populate_fundamentals_pandas()
