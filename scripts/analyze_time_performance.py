
import os
import sys
import json
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from urllib.parse import quote_plus
from datetime import datetime, timedelta
from collections import deque

# Add project root to path
sys.path.append(os.getcwd())

def get_db_url_from_secrets():
    try:
        with open("secrets.json", "r") as f:
            secrets = json.load(f)
            user = secrets.get("mariadb-user", "root")
            password = secrets.get("mariadb-password", "")
            host = secrets.get("mariadb-host", "localhost")
            port = secrets.get("mariadb-port", 3306)
            dbname = secrets.get("mariadb-database", "jennie_db")
            
            user_enc = quote_plus(user)
            password_enc = quote_plus(password)
            
            return f"mysql+pymysql://{user_enc}:{password_enc}@{host}:{port}/{dbname}?charset=utf8mb4"
    except Exception as e:
        print(f"Error reading secrets.json: {e}")
        return None

def analyze_time_performance():
    # 1. DB Connection
    DATABASE_URL = get_db_url_from_secrets()
    if not DATABASE_URL:
        print("Failed to get DB URL.")
        return

    engine = create_engine(DATABASE_URL)
    
    # 2. Fetch All Trades
    print("Fetching Trade Logs...")
    sql = text("""
        SELECT STOCK_CODE, TRADE_TYPE, QUANTITY, PRICE, TRADE_TIMESTAMP, REASON, 
               KEY_METRICS_JSON, MARKET_CONTEXT_JSON
        FROM TRADELOG
        WHERE QUANTITY > 0
        ORDER BY TRADE_TIMESTAMP ASC
    """)
    
    with engine.connect() as conn:
        try:
            result = conn.execute(sql).mappings().all()
        except AttributeError:
             result = conn.execute(sql).fetchall()

    trades = [dict(row) for row in result]
    print(f"Total Trade Logs: {len(trades)}")
    
    # 3. FIFO Matching
    holdings = {} 
    closed_trades = [] 
    
    for t in trades:
        code = t['STOCK_CODE']
        side = t['TRADE_TYPE'].upper() # BUY or SELL
        qty = t['QUANTITY']
        price = t['PRICE']
        ts = t['TRADE_TIMESTAMP']
        reason = t.get('REASON', '')
        
        # Parse JSON metrics
        key_metrics = {}
        try:
            if t.get('KEY_METRICS_JSON'):
                key_metrics = json.loads(t['KEY_METRICS_JSON'])
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
            
        if side == 'BUY':
            if code not in holdings:
                holdings[code] = deque()
            holdings[code].append({
                'price': price,
                'qty': qty,
                'ts': ts,
                'reason': reason,
                'metrics': key_metrics
            })
            
        elif side == 'SELL':
            if code not in holdings or not holdings[code]:
                continue
                
            remaining_sell_qty = qty
            
            while remaining_sell_qty > 0 and holdings[code]:
                buy_pos = holdings[code][0] # Peek
                
                match_qty = min(remaining_sell_qty, buy_pos['qty'])
                
                # Calculate PnL for this chunk
                return_pct = (price - buy_pos['price']) / buy_pos['price'] * 100
                
                closed_trades.append({
                    'stock_code': code,
                    'buy_time': buy_pos['ts'],
                    'sell_time': ts,
                    'buy_price': buy_pos['price'],
                    'sell_price': price,
                    'qty': match_qty,
                    'return_pct': return_pct,
                    'buy_reason': buy_pos['reason'],
                    'metrics': buy_pos['metrics']
                })
                
                # Update queues
                buy_pos['qty'] -= match_qty
                remaining_sell_qty -= match_qty
                
                if buy_pos['qty'] <= 0:
                    holdings[code].popleft()
    
    # ... (Group By Logic Skipped for Brevity, assuming it remains similar or I can just focus on the losing trades output) ...
    # Re-implementing the missing parts to ensure the script works completely
    
    print(f"Total Closed Trades Reconstructed: {len(closed_trades)}")
    
    if not closed_trades:
        print("No closed trades found.")
        return

    # 4. Group by Time Buckets
    df = pd.DataFrame(closed_trades)
    
    def floor_30min(dt):
        minute = dt.minute
        if minute < 30:
            minute = 0
        else:
            minute = 30
        return dt.replace(minute=minute, second=0, microsecond=0).strftime('%H:%M')

    df['time_bucket'] = df['buy_time'].apply(floor_30min)
    df['is_win'] = df['return_pct'] > 0
    
    stats = df.groupby('time_bucket').agg(
        total_trades=('stock_code', 'count'),
        win_count=('is_win', 'sum'),
        avg_return=('return_pct', 'mean'),
        median_return=('return_pct', 'median'),
        min_return=('return_pct', 'min'),
        max_return=('return_pct', 'max')
    ).reset_index()
    
    stats['win_rate'] = (stats['win_count'] / stats['total_trades'] * 100).round(1)
    stats['avg_return'] = stats['avg_return'].round(2)
    stats['median_return'] = stats['median_return'].round(2)
    stats['min_return'] = stats['min_return'].round(2)
    stats['max_return'] = stats['max_return'].round(2)
    
    timestamps = [t['buy_time'] for t in closed_trades]
    if timestamps:
        start_date = min(timestamps)
        end_date = max(timestamps)
        duration = end_date - start_date
        print(f"\n=== Data Summary ===")
        print(f"Period: {start_date.date()} ~ {end_date.date()} ({duration.days} days)")
        
    print("\n=== Performance by Entry Time (30-min Buckets) ===")
    print(stats[['time_bucket', 'total_trades', 'win_rate', 'avg_return', 'median_return']].to_string(index=False))
    
    # 5. Detail: Worst Trades with Tech Indicators
    print("\n=== Worst Trades (Return < -3%) Analysis ===")
    worst_df = df[df['return_pct'] < -3.0].sort_values('return_pct')
    
    print(f"{'Time':<20} | {'Code':<8} | {'Return':<7} | {'RSI':<5} | {'GapDev':<6} | {'Reason'}")
    print("-" * 80)
    
    for _, row in worst_df.head(15).iterrows():
        m = row['metrics']
        # Try to extract indicators. Keys might vary based on strategy version.
        # Common keys: 'rsi_14', 'rsi', 'deviation_pct', 'ma_gap', 'score'
        rsi = m.get('rsi_14') or m.get('rsi') or 0
        gap = m.get('deviation_from_ma') or m.get('price_deviation') or 0
        if isinstance(gap, float):
             gap = round(gap, 2)
        
        print(f"{str(row['buy_time']):<20} | {row['stock_code']:<8} | {row['return_pct']:>6.2f}% | {rsi:>5} | {gap:>6} | {row['buy_reason'][:30]}")


if __name__ == "__main__":
    analyze_time_performance()
