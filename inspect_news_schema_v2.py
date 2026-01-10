
import sys
import os
from sqlalchemy import inspect, text

# Add project root to path
sys.path.insert(0, os.getcwd())

from shared.db.connection import session_scope, ensure_engine_initialized, get_engine
from dotenv import load_dotenv

load_dotenv(override=True)
ensure_engine_initialized()

engine = get_engine()
inspector = inspect(engine)
tables = inspector.get_table_names()

print(f"Tables found: {[t for t in tables if 'NEWS' in t.upper()]}")

target_tables = [t for t in tables if 'NEWS' in t.upper()]

for table in target_tables:
    print(f"\n--- {table} Schema ---")
    for col in inspector.get_columns(table):
        print(f"{col['name']} ({col['type']})")

with session_scope() as session:
    print("\n--- SAMPLE DATA (NEWS_SENTIMENT) ---")
    try:
        # Try finding a table that actually exists from the list above
        if 'NEWS_SENTIMENT' in tables:
            result = session.execute(text("SELECT * FROM NEWS_SENTIMENT ORDER BY PUBLISHED_AT DESC LIMIT 1"))
            row = result.fetchone()
            print(row)
        elif 'STOCK_NEWS_SENTIMENT' in tables:
            result = session.execute(text("SELECT * FROM STOCK_NEWS_SENTIMENT ORDER BY PUBLISHED_AT DESC LIMIT 1"))
            row = result.fetchone()
            print(row)
    except Exception as e:
        print(f"Error fetching sample: {e}")
