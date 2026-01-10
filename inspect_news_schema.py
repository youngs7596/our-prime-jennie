
from sqlalchemy import create_engine, inspect, text
import os
from dotenv import load_dotenv

load_dotenv()
db_url = f"mysql+pymysql://root:{os.getenv('MARIADB_ROOT_PASSWORD')}@127.0.0.1:3306/stock_db"
engine = create_engine(db_url)

inspector = inspect(engine)
tables = inspector.get_table_names()
print(f"Tables: {[t for t in tables if 'NEWS' in t.upper()]}")

for table in ['NEWS_SENTIMENT', 'STOCK_NEWS_SENTIMENT']:
    if table in tables:
        print(f"\n--- {table} ---")
        for col in inspector.get_columns(table):
            print(f"{col['name']} ({col['type']})")

with engine.connect() as conn:
    print("\n--- SAMPLE DATA (NEWS_SENTIMENT) ---")
    try:
        result = conn.execute(text("SELECT * FROM NEWS_SENTIMENT LIMIT 1"))
        print(result.fetchone())
    except Exception as e:
        print(e)
