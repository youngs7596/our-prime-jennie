import sys
import os
import json
from datetime import datetime, timedelta
import pandas as pd
from sqlalchemy import text

# 프로젝트 루트를 sys.path에 추가 (scripts 폴더 상위)
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from shared.db.connection import session_scope, ensure_engine_initialized

def report_performance():
    ensure_engine_initialized()
    
    # 2026-01-09 KST (Jan 9th) or UTC? 
    # Usually we want from Jan 9th morning KST. 
    # Let's just use 2026-01-08 for safety with UTC.
    start_date_str = "2026-01-08" 
    
    print(f"--- Investment Performance Report (Since 2026-01-09) ---")
    
    with session_scope() as session:
        # 1. Fetch STOCK_MASTER for mapping
        master_query = text("SELECT STOCK_CODE, STOCK_NAME FROM STOCK_MASTER")
        master_rows = session.execute(master_query).fetchall()
        master_map = {row[0]: row[1] for row in master_rows}
        
        # 2. Fetch TRADELOG
        query = text("""
            SELECT 
                TRADE_TIMESTAMP,
                STOCK_CODE,
                TRADE_TYPE,
                QUANTITY,
                PRICE,
                KEY_METRICS_JSON
            FROM TRADELOG
            WHERE TRADE_TIMESTAMP >= :start_date
            ORDER BY TRADE_TIMESTAMP ASC
        """)
        
        rows = session.execute(query, {"start_date": start_date_str}).fetchall()
        
        realized_trades = []
        for row in rows:
            timestamp, code, t_type, qty, price, metrics_json = row
            name = master_map.get(code, code)
            
            # KST conversion for display
            kst_time = timestamp + timedelta(hours=9)
            
            pnl = 0.0
            pnl_pct = 0.0
            
            if t_type == 'SELL' and metrics_json:
                try:
                    metrics = json.loads(metrics_json)
                    pnl = float(metrics.get('profit_amount', 0))
                    pnl_pct = float(metrics.get('profit_rate', 0))
                except (json.JSONDecodeError, KeyError, TypeError):
                    pass
            
            realized_trades.append({
                'time': kst_time,
                'name': name,
                'code': code,
                'type': t_type,
                'qty': qty,
                'price': price,
                'pnl': pnl,
                'pnl_pct': pnl_pct
            })
            
        df = pd.DataFrame(realized_trades)
        
        if df.empty:
            print("No trade history found since 2026-01-09.")
        else:
            sell_df = df[df['type'] == 'SELL'].copy()
            
            total_profit = sell_df['pnl'].sum()
            trade_count = len(sell_df)
            win_count = len(sell_df[sell_df['pnl'] > 0])
            win_rate = (win_count / trade_count * 100) if trade_count > 0 else 0
            avg_return = sell_df['pnl_pct'].mean() if trade_count > 0 else 0
            
            print(f"\n[Realized Statistics]")
            print(f"- Total Trades: {trade_count}")
            print(f"- Win Rate: {win_rate:.1f}% ({win_count}/{trade_count})")
            print(f"- Total Realized P&L: {total_profit:,.0f} KRW")
            print(f"- Avg Return Rate: {avg_return:.2f}%")
            
            print(f"\n[Recent Sell History]")
            recent_sells = sell_df.sort_values('time', ascending=False).head(10)
            print(f"{'Date':<12} {'Stock':<10} {'P&L (KRW)':>12} {'Return':>8}")
            print("-" * 50)
            for _, r in recent_sells.iterrows():
                print(f"{r['time'].strftime('%Y-%m-%d'):<12} {r['name'][:8]:<10} {r['pnl']:>12,.0f} {r['pnl_pct']:>7.2f}%")

        # 2. Unrealized P&L (Active Portfolio)
        print(f"\n[Current Active Portfolio]")
        hold_query = text("""
            SELECT STOCK_CODE, STOCK_NAME, QUANTITY, AVERAGE_BUY_PRICE
            FROM ACTIVE_PORTFOLIO
            WHERE QUANTITY > 0
        """)
        holdings = session.execute(hold_query).fetchall()
        
        if holdings:
            # Fetch latest prices for these stocks
            hold_codes = [h[0] for h in holdings]
            placeholders = ','.join([f"'{c}'" for c in hold_codes])
            
            price_query = text(f"""
                SELECT STOCK_CODE, CLOSE_PRICE
                FROM STOCK_DAILY_PRICES_3Y
                WHERE STOCK_CODE IN ({placeholders})
                AND PRICE_DATE = (SELECT MAX(PRICE_DATE) FROM STOCK_DAILY_PRICES_3Y)
            """)
            price_rows = session.execute(price_query).fetchall()
            current_prices = {r[0]: float(r[1]) for r in price_rows}
            
            total_cost = 0
            total_val = 0
            print(f"{'Stock':<10} {'Qty':>5} {'Avg Price':>10} {'Cur Price':>10} {'Est. P&L':>10}")
            print("-" * 55)
            for row in holdings:
                code, name, qty, avg_p = row
                cur_p = current_prices.get(code, avg_p)
                
                cost = qty * avg_p
                val = qty * cur_p
                unrealized = val - cost
                total_cost += cost
                total_val += val
                
                print(f"{name[:8]:<10} {qty:>5} {avg_p:>10,.0f} {cur_p:>10,.0f} {unrealized:>10,.0f}")
            
            total_unrealized = total_val - total_cost
            unrealized_pct = (total_unrealized / total_cost * 100) if total_cost > 0 else 0
            print(f"\n- Unrealized P&L Sum: {total_unrealized:,.0f} KRW ({unrealized_pct:.2f}%)")
        else:
            print("No active holdings.")

if __name__ == "__main__":
    report_performance()
