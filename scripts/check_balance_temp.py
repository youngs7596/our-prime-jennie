import os
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.kis import KISClient
from shared.auth import get_secret
from dotenv import load_dotenv

def check_balance():
    load_dotenv(override=True)
    
    trading_mode = os.getenv("TRADING_MODE", "REAL")
    print(f"Trading Mode: {trading_mode}")
    
    # Initialize KIS API
    kis = KISClient(
        app_key=get_secret(os.getenv(f"{trading_mode}_SECRET_ID_APP_KEY")),
        app_secret=get_secret(os.getenv(f"{trading_mode}_SECRET_ID_APP_SECRET")),
        base_url=os.getenv(f"KIS_BASE_URL_{trading_mode}"),
        account_prefix=get_secret(os.getenv(f"{trading_mode}_SECRET_ID_ACCOUNT_PREFIX")),
        account_suffix=os.getenv("KIS_ACCOUNT_SUFFIX"),
        token_file_path="./tokens/kis_token.json",
        trading_mode=trading_mode
    )
    
    if not kis.authenticate():
        print("Authentication failed")
        return

    balance = kis.get_balance()
    print(f"Total Asset: {balance.get('total_asset_amount', 0)}")
    print(f"Cash Balance: {balance.get('deposit', 0)}")
    
    print("\nCurrent Holdings:")
    for stock in balance.get('holdings', []):
        print(f"Code: {stock['code']}, Name: {stock['name']}, Qty: {stock['quantity']}, Current Price: {stock['current_price']}")

if __name__ == "__main__":
    check_balance()
