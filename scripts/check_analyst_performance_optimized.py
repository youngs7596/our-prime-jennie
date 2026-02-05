
import sys
import os
import pandas as pd
import json
from sqlalchemy import select
from datetime import datetime, timedelta, timezone

# Add project root to sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.db.connection import get_session, ensure_engine_initialized
from shared.db.models import LLMDecisionLedger, StockDailyPrice

def load_secrets():
    secrets_path = os.path.join(project_root, "secrets.json")
    if os.path.exists(secrets_path):
        with open(secrets_path, "r") as f:
            secrets = json.load(f)
            os.environ["MARIADB_USER"] = secrets.get("mariadb-user", "root")
            os.environ["MARIADB_PASSWORD"] = secrets.get("mariadb-password", "")
            os.environ["MARIADB_HOST"] = secrets.get("mariadb-host", "localhost")
            os.environ["MARIADB_PORT"] = secrets.get("mariadb-port", "3306")
            os.environ["MARIADB_DBNAME"] = secrets.get("mariadb-dbname", "jennie_db")
            os.environ["DB_TYPE"] = "MARIADB"

def fetch_price_history_optimized(session, stock_code, start_date):
    """Fetch daily price history for a stock starting from a specific date."""
    stmt = select(StockDailyPrice).where(
        StockDailyPrice.stock_code == stock_code,
        StockDailyPrice.price_date >= start_date
    ).order_by(StockDailyPrice.price_date.asc()).limit(30) # Limit to enough days for 20D return

    prices = pd.read_sql(stmt, session.bind)
    prices.columns = [c.lower() for c in prices.columns]
    return prices

def main():
    print("Initializing DB...")
    load_secrets()
    ensure_engine_initialized()
    
    print("Connecting to DB...")
    with get_session() as session:
        # Fetch only last 300 decisions
        print("Fetching latest 300 decisions...")
        stmt = select(LLMDecisionLedger).where(
            LLMDecisionLedger.final_decision.in_(['BUY', 'SELL'])
        ).order_by(LLMDecisionLedger.timestamp.desc()).limit(300)
        
        decisions = pd.read_sql(stmt, session.bind)
        decisions.columns = [c.lower() for c in decisions.columns]
        
        if decisions.empty:
            print("No decisions found.")
            return

        print(f"Analyzing {len(decisions)} decisions...")
        
        results = []
        for i, row in decisions.iterrows():
            if i % 50 == 0:
                print(f"  Processing {i}/{len(decisions)}...")
                
            stock_code = row['stock_code']
            decision_date = row['timestamp']
            decision_type = row['final_decision']
            
            prices = fetch_price_history_optimized(session, stock_code, decision_date.date())
            
            # Normalize column names in price df
            if not prices.empty:
                prices.columns = [c.lower() for c in prices.columns]
            
            entry_price = None
            if not prices.empty:
                if 'close_price' in prices.columns:
                    entry_price = prices.iloc[0]['close_price']
                elif 'price' in prices.columns: # fallback if column name differs
                    entry_price = prices.iloc[0]['price']
            
            performance = {
                'hunter_score': row['hunter_score'],
                'market_regime': row['market_regime'],
                'return_1d': None,
                'return_5d': None,
                'return_20d': None
            }
            
            if entry_price and entry_price > 0:
                if len(prices) > 1:
                    price_1d = prices.iloc[1]['close_price']
                    ret_1d = (price_1d - entry_price) / entry_price
                    performance['return_1d'] = ret_1d if decision_type == 'BUY' else -ret_1d
                    
                if len(prices) > 5:
                    price_5d = prices.iloc[5]['close_price']
                    ret_5d = (price_5d - entry_price) / entry_price
                    performance['return_5d'] = ret_5d if decision_type == 'BUY' else -ret_5d  

                if len(prices) > 20:
                    price_20d = prices.iloc[20]['close_price']
                    ret_20d = (price_20d - entry_price) / entry_price
                    performance['return_20d'] = ret_20d if decision_type == 'BUY' else -ret_20d

            results.append(performance)
            
        df = pd.DataFrame(results)
        
        # --- Analysis Report ---
        print("\n" + "="*50)
        print(" ANALYST PERFORMANCE REPORT (Last 300 Decisions)")
        print("="*50)
        
        # 1. Overall
        if 'return_1d' in df.columns:
            wr_1d = (df['return_1d'] > 0).mean() * 100
            print(f"Overall Win Rate (1D): {wr_1d:.2f}%")
        if 'return_5d' in df.columns:
            valid_5d = df.dropna(subset=['return_5d'])
            if len(valid_5d) > 0:
                wr_5d = (valid_5d['return_5d'] > 0).mean() * 100
                avg_5d = valid_5d['return_5d'].mean() * 100
                print(f"Overall Win Rate (5D): {wr_5d:.2f}% (Avg: {avg_5d:.2f}%) [{len(valid_5d)} samples]")
            else:
                print("Overall Win Rate (5D): Not enough data")
                
        # 2. By Hunter Score
        print("\n[Win Rate by Hunter Score (5D)]")
        bins = [0, 50, 60, 70, 80, 100]
        labels = ['F (0-50)', 'C (50-60)', 'B (60-70)', 'A (70-80)', 'S (80+)']
        df['score_bucket'] = pd.cut(df['hunter_score'], bins=bins, labels=labels)
        
        for bucket in labels:
            subset = df[df['score_bucket'] == bucket]
            valid_subset = subset.dropna(subset=['return_5d'])
            count = len(valid_subset)
            if count > 0:
                wr = (valid_subset['return_5d'] > 0).mean() * 100
                avg_ret = valid_subset['return_5d'].mean() * 100
                print(f"  {bucket}: {wr:.1f}% Win Rate | Avg: {avg_ret:.2f}% | Samples: {count}")
            else:
                print(f"  {bucket}: No valid samples")
                
        # 3. By Market Regime
        print("\n[Win Rate by Market Regime (5D)]")
        if 'market_regime' in df.columns:
            for regime in df['market_regime'].unique():
                subset = df[df['market_regime'] == regime]
                valid_subset = subset.dropna(subset=['return_5d'])
                if len(valid_subset) > 0:
                    wr = (valid_subset['return_5d'] > 0).mean() * 100
                    print(f"  {regime}: {wr:.1f}% ({len(valid_subset)})")

if __name__ == "__main__":
    main()
