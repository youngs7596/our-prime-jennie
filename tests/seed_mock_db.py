
import sys
import os
import random
from datetime import datetime, timedelta

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.db import connection, models
from shared.db.connection import ensure_engine_initialized
from sqlalchemy.orm import Session

def seed_mock_data():
    ensure_engine_initialized()
    
    with connection.session_scope() as session:
        # 1. Seed STOCK_MASTER
        stock_code = "005930"
        stock_name = "삼성전자"
        
        master = session.query(models.StockMaster).filter_by(stock_code=stock_code).first()
        if not master:
            master = models.StockMaster(
                stock_code=stock_code,
                stock_name=stock_name,
                market_cap=400000000, # 400조
                sector_kospi200="IT",
                created_at=datetime.utcnow()
            )
            session.add(master)
            print(f"✅ Added {stock_name} to STOCK_MASTER")
        else:
            print(f"ℹ️ {stock_name} already in STOCK_MASTER")

        # 2. Seed STOCK_DAILY_PRICES_3Y (Generate 180 days of history)
        # Create an uptrend then range pattern to ensure momentum is positive
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=180)
        
        current_date = start_date
        base_price = 60000.0
        
        prices_added = 0
        
        while current_date <= end_date:
            # Check existence
            existing = session.query(models.StockDailyPrice).filter_by(
                stock_code=stock_code, 
                price_date=current_date
            ).first()
            
            if not existing:
                # Random walk with slight upward drift
                change = random.uniform(-0.01, 0.012)
                base_price = base_price * (1 + change)
                
                daily_price = models.StockDailyPrice(
                    stock_code=stock_code,
                    price_date=current_date,
                    open_price=base_price * 0.99,
                    close_price=base_price,
                    high_price=base_price * 1.01,
                    low_price=base_price * 0.98,
                    volume=10000000,
                    created_at=datetime.utcnow()
                )
                session.add(daily_price)
                prices_added += 1
            
            current_date += timedelta(days=1)
            
        print(f"✅ added {prices_added} daily price records for {stock_name}")
        
        # 3. KOSPI (0001) Dummy Data for Relative Momentum
        kospi_code = "0001"
        kospi_base = 2500.0
        current_date = start_date
        kospi_added = 0
        
        while current_date <= end_date:
             existing = session.query(models.StockDailyPrice).filter_by(
                stock_code=kospi_code, 
                price_date=current_date
            ).first()
             
             if not existing:
                change = random.uniform(-0.005, 0.005)
                kospi_base = kospi_base * (1 + change)
                
                daily_price = models.StockDailyPrice(
                    stock_code=kospi_code,
                    price_date=current_date,
                    open_price=kospi_base,
                    close_price=kospi_base,
                    high_price=kospi_base,
                    low_price=kospi_base,
                    volume=500000,
                    created_at=datetime.utcnow()
                )
                session.add(daily_price)
                kospi_added += 1
                
             current_date += timedelta(days=1)
        
        print(f"✅ added {kospi_added} daily price records for KOSPI")

if __name__ == "__main__":
    seed_mock_data()
