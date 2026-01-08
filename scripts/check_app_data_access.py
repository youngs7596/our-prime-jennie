import os
import sys
import logging

# Set up project root
PROJECT_ROOT = '/app'
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from shared.db.connection import session_scope, ensure_engine_initialized
import shared.database as database

logging.basicConfig(level=logging.INFO)

def test_data_access():
    ensure_engine_initialized()
    with session_scope() as session:
        # Test Kia
        code = '000270'
        df = database.get_daily_prices(session, code, limit=150)
        print(f"Stock {code}: Found {len(df)} rows")
        if not df.empty:
            print(f"Latest date in DF: {df.index[-1] if hasattr(df.index, 'date') else 'N/A'}")
            print(df.tail(3))
        
        # Test Samsung
        code = '005930'
        df = database.get_daily_prices(session, code, limit=150)
        print(f"Stock {code}: Found {len(df)} rows")

if __name__ == "__main__":
    test_data_access()
