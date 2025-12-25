
import os
import sys
from sqlalchemy import text
from dotenv import load_dotenv

# Add project root to path
sys.path.append('/home/youngs75/projects/my-prime-jennie')

# Load env vars
load_dotenv(override=True)
os.environ["MARIADB_PORT"] = "3307"

from shared.db.connection import session_scope, ensure_engine_initialized

def query_history(stock_code):
    ensure_engine_initialized()
    with session_scope() as session:
        print(f"--- Checking DAILY_QUANT_SCORE for {stock_code} ---")
        query = text("""
            SELECT SCORE_DATE, TOTAL_QUANT_SCORE, IS_PASSED_FILTER, LLM_SCORE, HYBRID_SCORE, IS_FINAL_SELECTED
            FROM DAILY_QUANT_SCORE
            WHERE STOCK_CODE = :code
            ORDER BY SCORE_DATE DESC
            LIMIT 20
        """)
        rows = session.execute(query, {"code": stock_code}).fetchall()
        print(f"{'Date':<15} {'Quant':<10} {'Passed':<10} {'LLM':<10} {'Hybrid':<10} {'Selected':<10}")
        print("-" * 75)
        for r in rows:
            print(f"{str(r[0]):<15} {str(r[1]):<10} {str(r[2]):<10} {str(r[3]):<10} {str(r[4]):<10} {str(r[5]):<10}")

        print(f"\n--- Checking LLM_DECISION_LEDGER for {stock_code} ---")
        query = text("""
            SELECT TIMESTAMP, HUNTER_SCORE, FINAL_DECISION, FINAL_REASON
            FROM LLM_DECISION_LEDGER
            WHERE STOCK_CODE = :code
            ORDER BY TIMESTAMP DESC
            LIMIT 10
        """)
        rows = session.execute(query, {"code": stock_code}).fetchall()
        print(f"{'Timestamp':<25} {'Hunter':<10} {'Decision':<15} {'Reason'}")
        print("-" * 100)
        for r in rows:
            reason = (r[3][:60] + '...') if r[3] else ''
            print(f"{str(r[0]):<25} {str(r[1]):<10} {str(r[2]):<15} {reason}")

        print(f"\n--- Checking SHADOW_RADAR_LOG for {stock_code} ---")
        query = text("""
            SELECT TIMESTAMP, REJECTION_STAGE, REJECTION_REASON, HUNTER_SCORE_AT_TIME
            FROM SHADOW_RADAR_LOG
            WHERE STOCK_CODE = :code
            ORDER BY TIMESTAMP DESC
            LIMIT 10
        """)
        rows = session.execute(query, {"code": stock_code}).fetchall()
        print(f"{'Timestamp':<25} {'Stage':<15} {'Hunter':<10} {'Reason'}")
        print("-" * 100)
        for r in rows:
            print(f"{str(r[0]):<25} {str(r[1]):<15} {str(r[3]):<10} {r[2]}")


        print(f"\n--- Checking TRADELOG for {stock_code} ---")
        query = text("""
            SELECT TRADE_TIMESTAMP, TRADE_TYPE, QUANTITY, PRICE, REASON, STRATEGY_SIGNAL
            FROM TRADELOG
            WHERE STOCK_CODE = :code
            ORDER BY TRADE_TIMESTAMP DESC
            LIMIT 5
        """)
        rows = session.execute(query, {"code": stock_code}).fetchall()

        print(f"{'Timestamp':<25} {'Type':<10} {'Qty':<10} {'Price':<10} {'Reason'}")
        print("-" * 100)
        for r in rows:
            print(f"{str(r[0]):<25} {str(r[1]):<10} {str(r[2]):<10} {str(r[3]):<10} {r[4]}")
            
        print("\n--- Checking CONFIG Table ---")
        query = text("SELECT config_key, config_value FROM CONFIG WHERE config_key IN ('MIN_LLM_SCORE', 'SCOUT_UNIVERSE_SIZE', 'STRATEGY_PRESET', 'ACTIVE_STRATEGY_PRESET')")
        rows = session.execute(query).fetchall()
        print(f"{'Key':<30} {'Value'}")
        print("-" * 50)
        for r in rows:
            print(f"{r[0]:<30} {r[1]}")

if __name__ == "__main__":
    query_history("085620")
