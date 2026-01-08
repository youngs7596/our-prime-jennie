#!/usr/bin/env python3
"""
scripts/verify_ideal_pattern.py

Goal: "이상형 패턴(Ideal Pattern)"의 실존 여부와 수익성을 과거 3년 데이터로 과학적 검증.

Pattern Definition:
1. Trigger (Day T):
   - RSI(14) <= 30
   - Foreign Net Buy > 0
   - Foreign Net Buy >= 20-day Avg Volume * 5% (Significant Accumulation)
2. Confirmation (Day T+1 ~ T+20):
   - Golden Cross (MA5 crosses above MA20)

Metrics:
- Count: 발생 횟수
- Success Rate: 골든크로스 발생 후 20일 내 최고가 수익률 > 5% (Example)
"""

import os
import sys
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)

from shared.db.connection import session_scope, ensure_engine_initialized
from shared.database.market import get_all_stock_codes, get_daily_prices, get_investor_trading

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def calculate_indicators(df):
    """Calculate RSI, MA5, MA20, AvgVolume20"""
    df = df.sort_index() # Ensure date asc
    
    # RSI
    delta = df['CLOSE_PRICE'].diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    roll_up = up.rolling(window=14).mean()
    roll_down = down.rolling(window=14).mean()
    rs = roll_up / roll_down
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # MAs
    df['MA5'] = df['CLOSE_PRICE'].rolling(window=5).mean()
    df['MA20'] = df['CLOSE_PRICE'].rolling(window=20).mean()
    
    # Volume MA
    df['VOL_MA20'] = df['VOLUME'].rolling(window=20).mean()
    
    return df

def analyze_stock(stock_code, session):
    try:
        # 1. Load Data
        # Optimize: 2 years of data is enough for recent trend, let's take 3 years as requested
        df_price = get_daily_prices(session, stock_code, limit=750) # ~3 years
        if df_price.empty or len(df_price) < 60:
            return []
            
        df_price = df_price.set_index('PRICE_DATE').sort_index()
        
        # 2. Calculate Indicators
        df_price = calculate_indicators(df_price)
        
        # 3. Identify Pattern Candidates (Trigger Day)
        # Condition: RSI <= 30
        oversold_days = df_price[df_price['RSI'] <= 30]
        
        if oversold_days.empty:
            return []
            
        # Load Investor Data only if RSI condition met (Optimization)
        # But we need to check foreign buy on the specific dates.
        # Fetching all investor data for the stock might be cleaner than point queries if there are many oversold days.
        df_investor = get_investor_trading(session, stock_code, limit=750)
        if df_investor.empty:
            return []
            
        df_investor = df_investor.set_index('TRADE_DATE').sort_index()
        
        # Merge Price and Investor data
        # Use inner join to ensure we have both
        df_merged = df_price.join(df_investor[['FOREIGN_NET_BUY']], how='inner')
        
        events = []
        
        # Scan for Trigger
        # Condition A: RSI <= 30 (Already filtered in index logic, but let's iterate properly)
        # We iterate through the merged dataframe to respect filtering
        
        # Get indices where conditions meet
        # 1. RSI <= 30
        # 2. Foreign Buy > 0
        # 3. Foreign Buy >= VOL_MA20 * 0.05
        
        cond_rsi = df_merged['RSI'] <= 30
        cond_foreign_buy = df_merged['FOREIGN_NET_BUY'] > 0
        cond_strength = df_merged['FOREIGN_NET_BUY'] >= (df_merged['VOL_MA20'] * 0.05)
        
        trigger_mask = cond_rsi & cond_foreign_buy & cond_strength
        trigger_dates = df_merged.index[trigger_mask]
        
        for t_date in trigger_dates:
            # Look forward 20 days for Confirmation
            # Get slice from T+1
            idx_loc = df_merged.index.get_loc(t_date)
            # Check bounds
            if idx_loc + 21 >= len(df_merged):
                continue
                
            future_slice = df_merged.iloc[idx_loc+1 : idx_loc+21]
            
            # Check for Golden Cross in future_slice
            # GC: MA5 crosses above MA20
            # Logic: Yesterday (MA5 < MA20) AND Today (MA5 > MA20)
            
            gc_mask = (future_slice['MA5'] > future_slice['MA20']) & \
                      (future_slice['MA5'].shift(1) <= future_slice['MA20'].shift(1))
            
            gc_dates = future_slice.index[gc_mask]
            
            has_gc = not gc_dates.empty
            gc_date = gc_dates[0] if has_gc else None
            
            # Performance Calc
            # If GC happens, return from GC date to T+20 (from GC)
            # If no GC, return from Trigger T+20
            
            entry_price = df_merged.loc[t_date]['CLOSE_PRICE']
            max_return = 0.0
            avg_return_5d = 0.0
            
            # Simple outcome: Max price in next 20 days vs Entry
            future_prices = future_slice['HIGH_PRICE']
            if not future_prices.empty:
                max_price = future_prices.max()
                max_return = (max_price - entry_price) / entry_price * 100
                
            events.append({
                'stock_code': stock_code,
                'trigger_date': t_date.strftime('%Y-%m-%d'),
                'trigger_rsi': df_merged.loc[t_date]['RSI'],
                'foreign_net_buy': df_merged.loc[t_date]['FOREIGN_NET_BUY'],
                'vol_ma20': df_merged.loc[t_date]['VOL_MA20'],
                'has_golden_cross': has_gc,
                'gc_date': gc_date.strftime('%Y-%m-%d') if gc_date else None,
                'max_return_20d': max_return
            })
            
        return events
        
    except Exception as e:
        logger.error(f"Error analyzing {stock_code}: {e}")
        return []

def main():
    ensure_engine_initialized()
    
    with session_scope() as session:
        # Get all stocks
        # For testing speed, maybe limit or shuffle? No, user wants full scan.
        # But single threaded full scan is slow. Use ThreadPool.
        all_codes = get_all_stock_codes(session)
        logger.info(f"Loaded {len(all_codes)} stock codes.")
        
        results = []
        
        # Batch processing not easy with complex logic per stock, stick to parallel tasks
        # Limit concurrency to avoid DB overload if necessary, but reading is usually fine.
        max_workers = 10
        
        # Use session factory for threads or scoped session? 
        # get_daily_prices uses raw connection or session. 
        # Better to pass session_maker or create session inside thread?
        # Creating session inside thread is safer for SQLAlchemy.
        
        # from shared.db.connection import get_db_session -> Use session_scope directly
        
        def process_one(code):
            try:
                # Use session_scope for thread-local session
                # Since we are only reading, readonly=True is good practice
                with session_scope(readonly=True) as local_session:
                    return analyze_stock(code, local_session)
            except Exception as e:
                logger.error(f"Thread error for {code}: {e}")
                return []

        count = 0
        total = len(all_codes)
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(process_one, code) for code in all_codes]
            
            for future in as_completed(futures):
                res = future.result()
                if res:
                    results.extend(res)
                count += 1
                if count % 100 == 0:
                    logger.info(f"Progress: {count}/{total} stocks processed. Found {len(results)} patterns so far.")

    # Save Results
    df_res = pd.DataFrame(results)
    if not df_res.empty:
        df_res = df_res.sort_values('trigger_date', ascending=False)
        output_file = "analysis/ideal_pattern_results.csv"
        os.makedirs("analysis", exist_ok=True)
        df_res.to_csv(output_file, index=False)
        logger.info(f"Saved {len(df_res)} events to {output_file}")
        
        # Summary Report
        total_patterns = len(df_res)
        gc_patterns = df_res[df_res['has_golden_cross']]
        gc_rate = len(gc_patterns) / total_patterns * 100 if total_patterns > 0 else 0
        avg_max_return = df_res['max_return_20d'].mean()
        gc_max_return = gc_patterns['max_return_20d'].mean() if not gc_patterns.empty else 0
        
        report = f"""
# Ideal Pattern Verification Report

**Conditions**:
- RSI <= 30
- Foreign Net Buy >= 5% of 20-day Avg Vol
- Golden Cross within 20 days

**Summary Metrics**:
- Total Triggers Found (Last 3 Years): **{total_patterns}**
- Patterns Leading to Golden Cross: **{len(gc_patterns)}** ({gc_rate:.1f}%)
- Avg Max Return (All Triggers, 20d): **{avg_max_return:.1f}%**
- Avg Max Return (Confirmed GC, 20d): **{gc_max_return:.1f}%**

**Recent Examples (Confirmed GC)**:
"""
        # Add top 5 recent GC examples
        recent_gc = gc_patterns.head(10)
        for _, row in recent_gc.iterrows():
            report += f"- **{row['stock_code']}** (Trigger: {row['trigger_date']}, GC: {row['gc_date']}) | Max Return: {row['max_return_20d']:.1f}%\n"
            
        report_file = "analysis/ideal_pattern_report.md"
        with open(report_file, "w") as f:
            f.write(report)
        logger.info(f"Report saved to {report_file}")
        
        # Console output for user
        print(report)

    else:
        logger.info("No patterns found matching criteria.")

if __name__ == "__main__":
    main()
