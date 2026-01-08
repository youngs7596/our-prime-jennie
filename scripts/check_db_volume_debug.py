from sqlalchemy import create_engine, text
import os

DB_USER = 'jennie'
DB_PASSWORD = 'q1w2e3R$'
DB_HOST = '127.0.0.1'
DB_PORT = '3307'
DB_NAME = 'jennie_db'

DB_URL = f"mysql+mysqlconnector://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

def check_volume():
    print(f"Connecting to: {DB_URL}")
    try:
        engine = create_engine(DB_URL)
        with engine.connect() as conn:
            # Check STOCK_CODE format
            row = conn.execute(text("SELECT STOCK_CODE FROM STOCK_DAILY_PRICES_3Y LIMIT 1")).fetchone()
            if row:
                print(f"Sample STOCK_CODE: '{row[0]}' (length: {len(row[0])})")
            
            # Check Kia specifically
            row_kia = conn.execute(text("SELECT STOCK_CODE FROM STOCK_DAILY_PRICES_3Y WHERE STOCK_CODE = '000270' LIMIT 1")).fetchone()
            if row_kia:
                print(f"Kia found with '000270': '{row_kia[0]}'")
            else:
                print("Kia NOT found with '000270' - checking with LIKE")
                row_kia_like = conn.execute(text("SELECT STOCK_CODE FROM STOCK_DAILY_PRICES_3Y WHERE STOCK_CODE LIKE '%000270%' LIMIT 1")).fetchone()
                if row_kia_like:
                    print(f"Kia found with LIKE: '{row_kia_like[0]}'")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_volume()
