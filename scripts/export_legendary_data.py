#!/usr/bin/env python3
"""
scripts/export_legendary_data.py

Exports price and investor data for Samsung Pharmaceutical (001360) 
during the "Legendary Pattern" period (2025-10-01 to 2026-01-01) 
to a JSON structure suitable for LogicVisualization.tsx.
"""

import os
import sys
import json
import pandas as pd
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)

from shared.db.connection import session_scope, ensure_engine_initialized
from shared.database.market import get_daily_prices, get_investor_trading

def main():
    ensure_engine_initialized()
    
    target_code = "001360" # Samsung Pharm
    start_date = "2025-10-15"
    end_date = "2025-12-31"
    
    with session_scope(readonly=True) as session:
        # Load Price Data
        df_price = get_daily_prices(session, target_code, limit=120)
        df_price = df_price.set_index('PRICE_DATE').sort_index()
        df_price = df_price.loc[start_date:end_date]
        
        # Load Investor Data
        df_investor = get_investor_trading(session, target_code, limit=120)
        df_investor = df_investor.set_index('TRADE_DATE').sort_index()
        # Reindexing to match price dates (fill missing with 0)
        df_investor = df_investor.reindex(df_price.index).fillna(0)
        
        # Calculate Indicators for Visualization
        # We need to calculate MA, BB, RSI locally to match the exact values
        
        # Helper for rolling
        close = df_price['CLOSE_PRICE']
        
        # RSI 14
        delta = close.diff()
        up = delta.clip(lower=0)
        down = -delta.clip(upper=0)
        roll_up = up.rolling(14).mean()
        roll_down = down.rolling(14).mean()
        rs = roll_up / roll_down
        rsi = 100 - (100 / (1 + rs))
        
        # MA 5, 20, 60, 120
        ma5 = close.rolling(5).mean()
        ma20 = close.rolling(20).mean()
        ma60 = close.rolling(60).mean()
        ma120 = close.rolling(120).mean() # Might verify if we have enough data history
        
        # BB (20, 2)
        std20 = close.rolling(20).std()
        bb_upper = ma20 + (std20 * 2)
        bb_lower = ma20 - (std20 * 2)
        
        # Construct JSON Objects
        data_points = []
        
        # We need a continuous index 0..N for the x-axis in the chart
        for i, (date, row) in enumerate(df_price.iterrows()):
            date_str = date.strftime('%Y-%m-%d')
            inv_row = df_investor.loc[date]
            
            point = {
                "date": date_str,
                "close": row['CLOSE_PRICE'],
                "open": row['OPEN_PRICE'],
                "high": row['HIGH_PRICE'],
                "low": row['LOW_PRICE'],
                "volume": row['VOLUME'],
                "ma5": ma5.loc[date] if not pd.isna(ma5.loc[date]) else None,
                "ma20": ma20.loc[date] if not pd.isna(ma20.loc[date]) else None,
                "ma60": ma60.loc[date] if not pd.isna(ma60.loc[date]) else None,
                "ma120": ma120.loc[date] if not pd.isna(ma120.loc[date]) else None,
                "bb_upper": bb_upper.loc[date] if not pd.isna(bb_upper.loc[date]) else None,
                "bb_lower": bb_lower.loc[date] if not pd.isna(bb_lower.loc[date]) else None,
                "rsi": rsi.loc[date] if not pd.isna(rsi.loc[date]) else None,
                "foreign_net": inv_row['FOREIGN_NET_BUY'],
                "institution_net": inv_row['INSTITUTION_NET_BUY'],
                "individual_net": inv_row['INDIVIDUAL_NET_BUY'] if 'INDIVIDUAL_NET_BUY' in inv_row else 0,
            }
            data_points.append(point)
            
        # Clean NaNs (replace with null for JSON)
        # However, checking NaNs in Python float is tricky, JSON standard uses null
        
        output = {
            "stock_name": "삼성제약",
            "stock_code": "001360",
            "period": f"{start_date} ~ {end_date}",
            "data": data_points
        }
        
        # Save to file
        output_path = "services/dashboard/frontend/src/assets/legendary_case.json"
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        # Custom encoder for handling NaNs
        class NaNEncoder(json.JSONEncoder):
            def default(self, obj):
                if isinstance(obj, float) and pd.isna(obj):
                    return None
                return super().default(obj)
                
        with open(output_path, "w", encoding='utf-8') as f:
            # Replace NaN with null manually or use correct dumping
            # simpler: convert dataframe to dict with 'records', but we built custom list
            # We iterate and fix
            json_str = json.dumps(output, ensure_ascii=False, indent=2, cls=NaNEncoder)
            # Python's json dump might put NaN unless allow_nan=False (which raises error)
            # Standard JSON doesn't support NaN.
            # Post-process: replace NaN in list?
            # Let's rely on cleaning before appending or simple iteration
            f.write(json_str.replace("NaN", "null"))
            
        print(f"Exported data to {output_path}")

if __name__ == "__main__":
    main()
