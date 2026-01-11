
import sys
import os
from sqlalchemy import text
from dotenv import load_dotenv

sys.path.append(os.getcwd())
load_dotenv()

from shared.db.connection import session_scope, ensure_engine_initialized

def check_stock_master():
    ensure_engine_initialized()
    print("🔍 STOCK_MASTER 테이블 점검")
    print("=" * 60)
    
    with session_scope() as session:
        # 1. 컬럼 목록 확인
        print("\n1. [스키마] 컬럼 목록 확인")
        try:
            # MariaDB(MySQL) information_schema 조회
            query_cols = text("""
                SELECT COLUMN_NAME 
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_SCHEMA = :db AND TABLE_NAME = 'STOCK_MASTER'
            """)
            # DB 이름은 .env나 기본값에서 유추 필요하나, 여기서는 현재 세션의 DB 사용
            # 간단히 LIMIT 1 쿼리 결과의 keys()로 확인
            query_sample = text("SELECT * FROM STOCK_MASTER LIMIT 1")
            res = session.execute(query_sample)
            columns = res.keys()
            print(f"   - 컬럼: {list(columns)}")
            
            # 2. 펀더멘털 관련 컬럼 데이터 확인 (샘플 5개)
            print("\n2. [데이터] 샘플 데이터 (삼성전자 005930 등)")
            # 주요 예상 컬럼들이 있는지 확인 후 쿼리
            target_cols = ['STOCK_NAME', 'SECTOR', 'INDUSTRY']
            potential_fund_cols = ['PER', 'PBR', 'EPS', 'BPS', 'DIVIDEND_YIELD', 'MARKET_CAP']
            
            existing_cols = [c for c in columns if c in target_cols or c in potential_fund_cols]
            
            if not existing_cols:
                print("   ❌ 펀더멘털 관련 컬럼이 보이지 않습니다.")
            else:
                query_data = text(f"""
                    SELECT STOCK_CODE, {', '.join(existing_cols)}
                    FROM STOCK_MASTER
                    WHERE STOCK_CODE IN ('005930', '000660', '005380', '035420')
                """)
                rows = session.execute(query_data).fetchall()
                for row in rows:
                    print(f"   - {row}")
                    
        except Exception as e:
            print(f"❌ 오류 발생: {e}")

if __name__ == "__main__":
    check_stock_master()
