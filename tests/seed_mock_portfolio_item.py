
import os
import sys
from sqlalchemy import select

# Add project root to path
sys.path.append(os.getcwd())

from shared.db.connection import init_engine, session_scope, dispose_engine
from shared.db import models

def seed_mock_portfolio():
    os.environ['TRADING_MODE'] = 'MOCK'
    os.environ['MARIADB_PORT'] = '3307' # Force port
    
    dispose_engine()
    init_engine()
    
    with session_scope() as session:
        # Check if already exists
        from sqlalchemy import text
        result = session.execute(text("SELECT QUANTITY FROM ACTIVE_PORTFOLIO_MOCK WHERE STOCK_CODE = '005930'")).fetchone()
        
        if result:
            print(f"Already exists in MOCK: 005930, Qty={result[0]}")
        else:
            print("Seeding 005930 (Samsung Electronics) into ACTIVE_PORTFOLIO_MOCK...")
            # Use raw SQL to avoid ORM confusion if any
            session.execute(text("""
                INSERT INTO ACTIVE_PORTFOLIO_MOCK (STOCK_CODE, STOCK_NAME, QUANTITY, AVERAGE_BUY_PRICE, CREATED_AT)
                VALUES ('005930', '삼성전자', 10, 60000, NOW())
            """))
            print("Seeded.")
            
if __name__ == "__main__":
    seed_mock_portfolio()
