from shared.db.connection import session_scope, ensure_engine_initialized
from sqlalchemy import text

def check_impact():
    ensure_engine_initialized()
    
    with session_scope() as session:
        print("--- Junk Stock Filter Impact Analysis ---")
        
        # 1. Check Total Universe (Stock Master - excluding ETFs)
        master_query = text("SELECT COUNT(*) FROM STOCK_MASTER WHERE IS_ETF = 0 AND IS_SPAC = 0")
        total_universe = session.execute(master_query).scalar()
        print(f"Total Universe (excluding ETF/SPAC): {total_universe}")
        
        # 2. Check Data Availability in STOCK_FUNDAMENTALS (Latest Date)
        # Using a subquery to get max date
        fund_query = text("""
            SELECT COUNT(*) 
            FROM STOCK_FUNDAMENTALS 
            WHERE TRADE_DATE = (SELECT MAX(TRADE_DATE) FROM STOCK_FUNDAMENTALS)
        """)
        fund_count = session.execute(fund_query).scalar()
        print(f"Stocks with Fundamental Data: {fund_count}")
        
        # 3. Check Filter Impact (Market Cap < 50B KRW)
        # Unit: Million KRW. 50B = 50,000 Million.
        threshold = 50000 
        
        junk_query = text(f"""
            SELECT COUNT(*) 
            FROM STOCK_FUNDAMENTALS 
            WHERE TRADE_DATE = (SELECT MAX(TRADE_DATE) FROM STOCK_FUNDAMENTALS)
            AND MARKET_CAP < {threshold}
        """)
        junk_count = session.execute(junk_query).scalar()
        
        # 4. Check "Penny Stock" Impact (Price < 1000 KRW)
        # Need to join with Price or assume we can check current price snapshot if available?
        # STOCK_FUNDAMENTALS doesn't have price. 
        # Let's check DAILY_PRICES for the same set.
        
        penny_query = text(f"""
            SELECT COUNT(DISTINCT f.STOCK_CODE)
            FROM STOCK_FUNDAMENTALS f
            JOIN STOCK_DAILY_PRICES_3Y p ON f.STOCK_CODE = p.STOCK_CODE
            WHERE f.TRADE_DATE = (SELECT MAX(TRADE_DATE) FROM STOCK_FUNDAMENTALS)
            AND p.PRICE_DATE = (SELECT MAX(PRICE_DATE) FROM STOCK_DAILY_PRICES_3Y)
            AND p.CLOSE_PRICE < 1000
        """)
        # 4. Check "Penny Stock" Impact (Price < 1000 KRW)
        # Fetch latest prices for all stocks
        price_query = text("""
            SELECT STOCK_CODE, CLOSE_PRICE
            FROM STOCK_DAILY_PRICES_3Y
            WHERE PRICE_DATE = (SELECT MAX(PRICE_DATE) FROM STOCK_DAILY_PRICES_3Y)
        """)
        price_rows = session.execute(price_query).fetchall()
        price_map = {row[0]: float(row[1]) for row in price_rows}
        
        # Fetch fundamental stock codes
        fund_data_query = text("""
            SELECT STOCK_CODE, MARKET_CAP 
            FROM STOCK_FUNDAMENTALS 
            WHERE TRADE_DATE = (SELECT MAX(TRADE_DATE) FROM STOCK_FUNDAMENTALS)
        """)
        fund_rows = session.execute(fund_data_query).fetchall()
        fund_map = {row[0]: float(row[1]) for row in fund_rows}
        
        # Calculate in Python
        penny_stocks = 0
        market_cap_filtered = 0
        total_filtered = 0
        
        # We only care about stocks that exist in FUNDAMENTALS (our target set)
        valid_count = 0
        
        for code, mcap in fund_map.items():
            valid_count += 1
            is_junk_cap = mcap < threshold
            is_penny = False
            
            # Check price
            if code in price_map and price_map[code] < 1000:
                is_penny = True
                
            if is_junk_cap:
                market_cap_filtered += 1
            if is_penny:
                penny_stocks += 1
                
            if is_junk_cap or is_penny:
                total_filtered += 1

        print(f"\n[Filtering Criteria]")
        print(f"- Market Cap < 50 Billion KRW (Unit: {threshold})")
        print(f"- Price < 1,000 KRW")
        
        print(f"\n[Impact on Current Data Set ({valid_count} stocks)]")
        print(f"- Market Cap < 50B: {market_cap_filtered} stocks ({market_cap_filtered/valid_count*100:.1f}%)")
        print(f"- Penny Stocks (<1000): {penny_stocks} stocks ({penny_stocks/valid_count*100:.1f}%)")
        print(f"- Total Filtered (Union): {total_filtered} stocks ({total_filtered/valid_count*100:.1f}%)")

if __name__ == "__main__":
    check_impact()
