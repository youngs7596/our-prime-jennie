#!/usr/bin/env python3
"""
CSC v1.0 Data Analyst - AI Performance Analyzer
-----------------------------------------------
This script analyzes the 'realized performance' of AI decisions stored in LLM_DECISION_LEDGER.
It compares the decision timestamp with subsequent market price movements to calculate:
- Win Rate
- Average Return
- Performance by Market Regime
- Performance by Hunter Score

Output: generates docs/performance_report_v1.0.md
"""

import os
import sys
import logging
import pandas as pd
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from shared.db.models import LLMDecisionLedger, StockDailyPrice
from shared.db.connection import ensure_engine_initialized, get_session

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)



from shared.analysis.ai_performance import analyze_performance

def get_db_session():
    """Create a database session."""
    load_dotenv()
    ensure_engine_initialized()
    return get_session()



def generate_report(df):
    """Generate Markdown report from analysis results."""
    if df is None or df.empty:
        return "# CSC v1.0 AI Performance Report\n\nNo data available to analyze."
    
    # Fill NaN with 0 for calculation (or drop?) - Let's keep NaN as is but handle in aggregation
    
    # 1. Overall Win Rate (T+5 based)
    valid_5d = df.dropna(subset=['return_5d'])
    if not valid_5d.empty:
        win_rate_5d = (valid_5d['return_5d'] > 0).mean() * 100
        avg_return_5d = valid_5d['return_5d'].mean() * 100
    else:
        win_rate_5d = 0.0
        avg_return_5d = 0.0

    report = f"""# CSC v1.0 AI Performance Report
Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 1. Overall Performance (T+5 Benchmark)
- **Total Decisions Analyzed**: {len(valid_5d)} (valid T+5 data)
- **Win Rate**: {win_rate_5d:.2f}%
- **Average Return**: {avg_return_5d:.2f}%

## 2. Performance by Market Regime
"""
    
    # Group by Market Regime
    if 'market_regime' in df.columns:
        regime_stats = df.groupby('market_regime')['return_5d'].agg(['count', 'mean', lambda x: (x>0).mean()*100])
        regime_stats.columns = ['Count', 'Avg Return', 'Win Rate']
        report += "\n" + regime_stats.to_markdown() + "\n"
        
    report += "\n## 3. Performance by Hunter Score Bucket\n"
    
    # Group by Hunter Score (Bins: 0-40, 40-60, 60-80, 80-100)
    bins = [0, 40, 60, 80, 100]
    labels = ['F (0-40)', 'C/D (40-60)', 'B/A (60-80)', 'S (80-100)']
    df['score_bucket'] = pd.cut(df['hunter_score'], bins=bins, labels=labels)
    
    score_stats = df.groupby('score_bucket', observed=False)['return_5d'].agg(['count', 'mean', lambda x: (x>0).mean()*100])
    score_stats.columns = ['Count', 'Avg Return', 'Win Rate']
    report += "\n" + score_stats.to_markdown() + "\n"
    
    report += "\n## 4. Top 10 Best Decisions (T+5 Return)\n"
    top_10 = df.sort_values(by='return_5d', ascending=False).head(10)
    top_10_display = top_10[['stock_name', 'decision', 'hunter_score', 'market_regime', 'return_5d']].copy()
    top_10_display['return_5d'] = top_10_display['return_5d'].apply(lambda x: f"{x*100:.2f}%" if pd.notnull(x) else "N/A")
    report += "\n" + top_10_display.to_markdown(index=False) + "\n"

    return report

def main():
    session = get_db_session()
    try:
        df = analyze_performance(session)
        report_content = generate_report(df)
        
        output_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "performance_report_v1.0.md")
        with open(output_path, "w") as f:
            f.write(report_content)
            
        logger.info(f"✅ Report generated at: {output_path}")
        print(report_content) # Print to stdout for immediate view
        
    except Exception as e:
        logger.error(f"❌ Analysis failed: {e}", exc_info=True)
    finally:
        session.close()

if __name__ == "__main__":
    main()
