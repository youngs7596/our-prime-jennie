print("SCRIPT START")
import sys
import os
import traceback

try:
    import logging
    import pandas as pd
    import numpy as np

    logging.basicConfig(level=logging.INFO)
    print("Imports done")

    # 프로젝트 루트 경로 추가 (Docker 내부 절대 경로)
    root_path = "/app"
    sys.path.append(root_path)
    print(f"Added to sys.path: {root_path}")

    print("Importing shared...")
    from shared.db.connection import get_session, ensure_engine_initialized
    from shared.analysis.ai_performance import analyze_performance
    print("Shared imported")

    def analyze_insights():
        print("Initializing engine...")
        ensure_engine_initialized()
        print("📊 Fetching and analyzing data...")
        try:
            with get_session() as session:
                # 지난 90일 데이터 분석
                df = analyze_performance(session, lookback_days=90)
        except Exception as e:
            print(f"Error in session/analysis: {e}")
            traceback.print_exc()
            return
        
        if df.empty:
            print("Starting... No data found.")
            return

        print(f"\n✅ Analyzed {len(df)} decisions (BUY/SELL)")

        # 1. Market Regime Performance
        print("\n[ 1. Market Regime Analysis ]")
        regime_stats = df.groupby('market_regime').agg({
            'return_5d': ['count', 'mean', lambda x: (x > 0).mean()]
        })
        regime_stats.columns = ['Count', 'Avg Return 5D', 'Win Rate 5D']
        regime_stats['Avg Return 5D'] = regime_stats['Avg Return 5D'] * 100
        regime_stats['Win Rate 5D'] = regime_stats['Win Rate 5D'] * 100
        print(regime_stats.sort_values('Avg Return 5D', ascending=False))

        # 2. Hunter Score Performance (Bucketized)
        print("\n[ 2. Hunter Score Analysis ]")
        df['score_bucket'] = (df['hunter_score'] // 10) * 10
        score_stats = df.groupby('score_bucket').agg({
            'return_5d': ['count', 'mean', lambda x: (x > 0).mean()]
        })
        score_stats.columns = ['Count', 'Avg Return 5D', 'Win Rate 5D']
        score_stats['Avg Return 5D'] = score_stats['Avg Return 5D'] * 100
        score_stats['Win Rate 5D'] = score_stats['Win Rate 5D'] * 100
        print(score_stats.sort_index(ascending=False))

        # 3. Top Winning Tags
        print("\n[ 3. Top Winning Reasoning Tags ]")
        # 태그 펼치기
        tags_df = df.explode('tags')
        if 'tags' in tags_df.columns:
            tag_stats = tags_df.groupby('tags').agg({
                'return_5d': ['count', 'mean', lambda x: (x > 0).mean()]
            })
            tag_stats.columns = ['Count', 'Avg Return 5D', 'Win Rate 5D']
            tag_stats['Avg Return 5D'] = tag_stats['Avg Return 5D'] * 100
            tag_stats['Win Rate 5D'] = tag_stats['Win Rate 5D'] * 100
            # 최소 5회 이상 등장한 태그만
            tag_stats = tag_stats[tag_stats['Count'] >= 5]
            print(tag_stats.sort_values('Avg Return 5D', ascending=False).head(10))

    if __name__ == "__main__":
        analyze_insights()

except Exception as e:
    print(f"CRITICAL ERROR: {e}")
    traceback.print_exc()
