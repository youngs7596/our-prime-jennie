
import os
import sys
import json
import pandas as pd
from sqlalchemy import create_engine, text
from urllib.parse import quote_plus
from datetime import datetime

# Add project root to path
sys.path.append(os.getcwd())

def get_db_url_from_secrets():
    try:
        with open("secrets.json", "r") as f:
            secrets = json.load(f)
            user = secrets.get("mariadb-user", "root")
            password = secrets.get("mariadb-password", "")
            host = secrets.get("mariadb-host", "localhost")
            port = secrets.get("mariadb-port", 3306)
            dbname = secrets.get("mariadb-database", "jennie_db")
            
            user_enc = quote_plus(user)
            password_enc = quote_plus(password)
            
            return f"mysql+pymysql://{user_enc}:{password_enc}@{host}:{port}/{dbname}?charset=utf8mb4"
    except Exception as e:
        print(f"Error reading secrets.json: {e}")
        return None

def analyze_portfolio():
    DATABASE_URL = get_db_url_from_secrets()
    if not DATABASE_URL:
        print("Failed to get DB URL.")
        return

    engine = create_engine(DATABASE_URL)
    
    print("Fetching Active Portfolio...")
    # Join with STOCK_MASTER to get names if possible, or just fetch raw
    sql = text("""
        SELECT STOCK_CODE, STOCK_NAME, QUANTITY, AVERAGE_BUY_PRICE
        FROM ACTIVE_PORTFOLIO
        WHERE QUANTITY > 0
    """)
    
    with engine.connect() as conn:
        try:
            result = conn.execute(sql).mappings().all()
        except AttributeError:
             result = conn.execute(sql).fetchall()

    portfolio = [dict(row) for row in result]
    print(f"Total Positions: {len(portfolio)}")
    
    if not portfolio:
        print("Portfolio is empty.")
        return

    df = pd.DataFrame(portfolio)
    # Use Cost Basis for analysis
    df['market_value'] = df['QUANTITY'] * df['AVERAGE_BUY_PRICE']
    df['current_qty'] = df['QUANTITY']
    df['return_pct'] = 0.0 # Cannot calculate without real-time price, assume 0 for weight calc
    
    total_value = df['market_value'].sum()
    df['weight'] = (df['market_value'] / total_value) * 100
    
    print(f"\nTotal Portfolio Value: {total_value:,.0f} KRW")
    
    # Sector Classification (Simple keyword based for now + Known Codes)
    # 005380: Hyundai Motor
    # 000270: Kia
    # 012330: Hyundai Mobis
    # 011210: Hyundai Wia
    # 003620: KG Mobility
    # Others?
    
    auto_codes = ['005380', '000270', '012330', '011210', '003620', '204320', '047040'] # Added Mando, etc if needed
    auto_keywords = ['현대', '기아', '모비스', '위아', '타이어', '에스엘', '성우하이텍', '차']
    
    def get_sector(row):
        code = row['STOCK_CODE']
        name = row['STOCK_NAME']
        
        if code in auto_codes:
            return "Automotive"
        
        for kw in auto_keywords:
            if kw in name:
                return "Automotive"
                
        return "Others"

    df['sector'] = df.apply(get_sector, axis=1)
    
    grouped = df.groupby('sector')['market_value'].sum().reset_index()
    grouped['weight'] = (grouped['market_value'] / total_value) * 100
    
    print("\n=== Sector Allocation ===")
    print(grouped.to_string(index=False))
    
    print("\n=== Automotive Holdings ===")
    auto_df = df[df['sector'] == "Automotive"].sort_values('weight', ascending=False)
    if not auto_df.empty:
        print(auto_df[['STOCK_NAME', 'STOCK_CODE', 'current_qty', 'return_pct', 'weight']].to_string(index=False))
    else:
        print("No Automotive stocks found.")

    print("\n=== Top 5 Holdings ===")
    print(df.sort_values('weight', ascending=False).head(5)[['STOCK_NAME', 'STOCK_CODE', 'weight']].to_string(index=False))

if __name__ == "__main__":
    analyze_portfolio()
