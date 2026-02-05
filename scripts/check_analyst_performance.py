
import sys
import os
import pandas as pd
import numpy as np

# Add project root to sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.db.connection import get_session, ensure_engine_initialized
from shared.analysis.ai_performance import analyze_performance
import json

def load_secrets():
    secrets_path = os.path.join(project_root, "secrets.json")
    if os.path.exists(secrets_path):
        with open(secrets_path, "r") as f:
            secrets = json.load(f)
            # Set env vars for DB connection
            os.environ["MARIADB_USER"] = secrets.get("mariadb-user", "root")
            os.environ["MARIADB_PASSWORD"] = secrets.get("mariadb-password", "")
            os.environ["MARIADB_HOST"] = secrets.get("mariadb-host", "localhost")
            os.environ["MARIADB_PORT"] = secrets.get("mariadb-port", "3306")
            os.environ["MARIADB_DBNAME"] = secrets.get("mariadb-dbname", "jennie_db")
            os.environ["DB_TYPE"] = "MARIADB"

def main():
    print("Initializing DB...")
    load_secrets()
    ensure_engine_initialized()
    
    print("Connecting to DB and fetching performance data...")
    with get_session() as session:
        # Fetch data for last 60 days to get a good sample size
        df = analyze_performance(session, lookback_days=60)
        
        if df is None or df.empty:
            print("No performance data found.")
            return

        print(f"\n[Overall Stats] Total Decisions: {len(df)}")
        
        # 1. Overall Win Rates
        if 'return_1d' in df.columns:
            wr_1d = (df['return_1d'] > 0).mean() * 100
            print(f"Win Rate (1D): {wr_1d:.2f}% (Avg Return: {df['return_1d'].mean()*100:.2f}%)")
            
        if 'return_5d' in df.columns and df['return_5d'].count() > 0:
            valid_5d = df.dropna(subset=['return_5d'])
            wr_5d = (valid_5d['return_5d'] > 0).mean() * 100
            print(f"Win Rate (5D): {wr_5d:.2f}% (Avg Return: {valid_5d['return_5d'].mean()*100:.2f}%)")
            
        if 'return_20d' in df.columns and df['return_20d'].count() > 0:
            valid_20d = df.dropna(subset=['return_20d'])
            wr_20d = (valid_20d['return_20d'] > 0).mean() * 100
            print(f"Win Rate (20D): {wr_20d:.2f}% (Avg Return: {valid_20d['return_20d'].mean()*100:.2f}%)")
            
        # 2. Win Rate by Hunter Score Bucket
        print("\n[Win Rate by Hunter Score]")
        bins = [0, 50, 60, 70, 80, 100]
        labels = ['F (0-50)', 'C (50-60)', 'B (60-70)', 'A (70-80)', 'S (80+)']
        df['score_bucket'] = pd.cut(df['hunter_score'], bins=bins, labels=labels)
        
        for bucket in labels:
            subset = df[df['score_bucket'] == bucket]
            count = len(subset)
            if count > 0:
                # Use 5D return as primary metric for win rate
                valid_subset = subset.dropna(subset=['return_5d'])
                if len(valid_subset) > 0:
                    wr = (valid_subset['return_5d'] > 0).mean() * 100
                    avg_ret = valid_subset['return_5d'].mean() * 100
                    print(f"  {bucket}: {wr:.1f}% ({len(valid_subset)}/{count}) - Avg: {avg_ret:.2f}%")
                else:
                    print(f"  {bucket}: {count} samples (No 5D return data yet)")
            else:
                print(f"  {bucket}: No samples")

        # 3. Win Rate by Market Regime
        if 'market_regime' in df.columns:
            print("\n[Win Rate by Market Regime]")
            for regime in df['market_regime'].unique():
                subset = df[df['market_regime'] == regime]
                valid_subset = subset.dropna(subset=['return_5d'])
                if len(valid_subset) > 0:
                    wr = (valid_subset['return_5d'] > 0).mean() * 100
                    avg_ret = valid_subset['return_5d'].mean() * 100
                    print(f"  {regime}: {wr:.1f}% ({len(valid_subset)}) - Avg: {avg_ret:.2f}%")

if __name__ == "__main__":
    main()
