import os
import sys
import json

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)

from shared.kis import KISClient
from dotenv import load_dotenv

def check_balance():
    # Force REAL mode
    trading_mode = "REAL" 
    print(f"Trading Mode: {trading_mode}")
    
    # Load secrets.json
    secrets_path = os.path.join(PROJECT_ROOT, "secrets.json")
    if not os.path.exists(secrets_path):
        print(f"Error: secrets.json not found at {secrets_path}")
        return

    with open(secrets_path, "r") as f:
        secrets = json.load(f)
    
    # Map keys
    app_key = secrets.get("kis-r-app-key")
    app_secret = secrets.get("kis-r-app-secret")
    account_prefix = secrets.get("kis-r-account-no")
    
    if not all([app_key, app_secret, account_prefix]):
        print("Error: Missing keys in secrets.json for REAL mode")
        return

    # Initialize KIS API
    kis = KISClient(
        app_key=app_key,
        app_secret=app_secret,
        base_url="https://openapi.koreainvestment.com:9443", # REAL URL
        account_prefix=account_prefix,
        account_suffix="01",
        token_file_path="./tokens/kis_token.json",
        trading_mode=trading_mode
    )
    
    if not kis.authenticate():
        print("Authentication failed")
        return

    summary = kis.trading.get_asset_summary()
    holdings = kis.trading.get_account_balance()
    cash = kis.trading.get_cash_balance()
    
    print("-" * 50)
    print(f"Total Asset: {summary.get('total_asset', 0):,} KRW")
    print(f"Cash Balance (Orderable): {cash:,} KRW")
    print("-" * 50)
    
    print("\nCurrent Holdings:")
    for stock in holdings:
        print(f"[{stock['code']}] {stock['name']} : {stock['quantity']} shares @ {stock['current_price']} KRW")

    print("-" * 50)
    # Target Stocks Check
    targets = ["161390", "086280", "025560", "005380"]
    print("Target Status:")
    for t_code in targets:
        found = False
        for stock in holdings:
            if stock['code'] == t_code:
                print(f"  FOUND {t_code} ({stock['name']}): {stock['quantity']} shares")
                found = True
                break
        if not found:
            print(f"  NOT FOUND {t_code}")

if __name__ == "__main__":
    check_balance()
