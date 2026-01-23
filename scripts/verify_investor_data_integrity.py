import sys
import os
import pandas as pd
from sqlalchemy import text
from datetime import date, timedelta

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.db.connection import init_engine, session_scope

def check_investor_data_integrity():
    print("Checking Investor Data Integrity...")
    
    # Initialize DB
    init_engine()
    
    with session_scope(readonly=True) as session:
        # Check overall stats for last 30 days
        print("\nAnalyzing STOCK_INVESTOR_TRADING table for the last 30 days...")
        
        query = text("""
            SELECT 
                TRADE_DATE,
                COUNT(*) as total_rows,
                SUM(CASE WHEN FOREIGN_NET_BUY = 0 THEN 1 ELSE 0 END) as zero_foreign,
                SUM(CASE WHEN INSTITUTION_NET_BUY = 0 THEN 1 ELSE 0 END) as zero_inst,
                SUM(CASE WHEN FOREIGN_NET_BUY = 0 AND INSTITUTION_NET_BUY = 0 THEN 1 ELSE 0 END) as zero_both
            FROM STOCK_INVESTOR_TRADING
            WHERE TRADE_DATE >= DATE_SUB(CURDATE(), INTERVAL 60 DAY)
            GROUP BY TRADE_DATE
            ORDER BY TRADE_DATE DESC
        """)
        
        try:
            result = session.execute(query)
            rows = result.fetchall()
            
            if not rows:
                print("No data found in STOCK_INVESTOR_TRADING for the last 60 days.")
                return

            print(f"{'Date':<12} | {'Total':<6} | {'Zero Foreign':<12} | {'Zero Inst':<10} | {'Zero Both':<10} | {'% Zero Both'}")
            print("-" * 80)
            
            for row in rows:
                trade_date = row[0]
                total = row[1]
                z_foreign = row[2] or 0
                z_inst = row[3] or 0
                z_both = row[4] or 0
                
                percent_zero = (z_both / total) * 100 if total > 0 else 0
                
                print(f"{str(trade_date):<12} | {total:<6} | {int(z_foreign):<12} | {int(z_inst):<10} | {int(z_both):<10} | {percent_zero:>6.1f}%")
                
        except Exception as e:
            print(f"Error executing query: {e}")

    # Part 2: Check specifically for recent Golden Cross trades
    print("\n" + "="*80)
    print("Checking specific Golden Cross trades...")
    
    with session_scope(readonly=True) as session:
        # Get recent Golden Cross trades
        gc_query = text("""
            SELECT STOCK_CODE, date(TRADE_TIMESTAMP) as t_date
            FROM TRADELOG 
            WHERE STRATEGY_SIGNAL = 'GOLDEN_CROSS' 
            AND TRADE_TIMESTAMP >= '2026-01-01'
            ORDER BY TRADE_TIMESTAMP DESC
        """)
        
        gc_trades = session.execute(gc_query).fetchall()
        
        if not gc_trades:
            print("No Golden Cross trades found since 2026-01-01.")
            return
            
        print(f"Found {len(gc_trades)} Golden Cross trades since Jan 1, 2026. Checking their investor data...")
        print(f"{'Date':<12} | {'Stock':<8} | {'Foreign':<10} | {'Institution':<10} | {'Status'}")
        print("-" * 60)
        
        for trade in gc_trades:
            stock_code = trade[0]
            trade_date = trade[1]
            
            # Query investor data for this stock and date
            inv_query = text("""
                SELECT FOREIGN_NET_BUY, INSTITUTION_NET_BUY
                FROM STOCK_INVESTOR_TRADING
                WHERE STOCK_CODE = :code AND TRADE_DATE = :date
            """)
            
            inv_data = session.execute(inv_query, {"code": stock_code, "date": trade_date}).fetchone()
            
            status = "MISSING"
            f_val = "N/A"
            i_val = "N/A"
            
            if inv_data:
                f_val = inv_data[0]
                i_val = inv_data[1]
                if f_val == 0 and i_val == 0:
                    status = "ALL ZEROS"
                else:
                    status = "OK"
            
            print(f"{str(trade_date):<12} | {stock_code:<8} | {str(f_val):<10} | {str(i_val):<10} | {status}")


if __name__ == "__main__":
    # Ensure env vars are loaded if needed
    if not os.getenv("SECRETS_FILE"):
        possible_secrets = os.path.abspath(os.path.join(os.path.dirname(__file__), "../secrets.json"))
        if os.path.exists(possible_secrets):
            os.environ["SECRETS_FILE"] = possible_secrets
            print(f"Using secrets file: {possible_secrets}")
    
    # Port mapping for local execution if needed
    if not os.getenv("MARIADB_PORT"):
        os.environ["MARIADB_PORT"] = "3307"
        
    check_investor_data_integrity()
