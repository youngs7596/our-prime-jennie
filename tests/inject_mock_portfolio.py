
import sys
import os
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


from shared.db import connection, models
from shared.db.connection import ensure_engine_initialized
from sqlalchemy import select

def inject_mock_holding():
    ensure_engine_initialized()
    with connection.session_scope() as session:

        stock_code = "005930"
        
        # Check if already exists
        stmt = select(models.ActivePortfolio).where(models.ActivePortfolio.stock_code == stock_code)
        existing = session.execute(stmt).scalars().first()
        
        if existing:
            print(f"Holding for {stock_code} already exists.")
            return

        mock_holding = models.ActivePortfolio(
            stock_code=stock_code,
            stock_name="삼성전자",
            quantity=10,
            average_buy_price=60000.0,
            total_buy_amount=600000.0,
            current_high_price=72000.0,
            stop_loss_price=57000.0,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        session.add(mock_holding)
        print(f"✅ Injected mock holding: {stock_code} (10 shares @ 60,000)")

if __name__ == "__main__":
    inject_mock_holding()
