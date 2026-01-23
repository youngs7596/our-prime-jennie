import os
import sys
import json
import time

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)

from shared.kis import KISClient

def retry_buy():
    print("=" * 60)
    print("🚀 RETRYING BUY ORDER: HYUNDAI MOTOR (LIMIT ORDER)")
    print("=" * 60)
    
    # 1. Initialize Authentication (REAL Mode)
    secrets_path = os.path.join(PROJECT_ROOT, "secrets.json")
    with open(secrets_path, "r") as f:
        secrets = json.load(f)
    
    kis = KISClient(
        app_key=secrets.get("kis-r-app-key"),
        app_secret=secrets.get("kis-r-app-secret"),
        base_url="https://openapi.koreainvestment.com:9443",
        account_prefix=secrets.get("kis-r-account-no"),
        account_suffix="01",
        token_file_path="./tokens/kis_token.json",
        trading_mode="REAL"
    )
    
    if not kis.authenticate():
        print("❌ Authentication Failed")
        return

    # 4. Check Cash & Buy Hyundai Motor
    print("\n[Step 1] Checking Cash & Price...")
    
    # Refresh cash balance
    cash = kis.trading.get_cash_balance()
    print(f"  💰 Orderable Cash: {cash:,.0f} KRW")
    
    if cash < 50000: # Min buffer
        print("  ❌ Insufficient cash.")
        return

    # Get Current Price of Hyundai Motor
    snapshot = kis.market_data.get_stock_snapshot("005380")
    if not snapshot:
        print("  ❌ Failed to get price snapshot.")
        return
        
    current_price = float(snapshot.get('price', 0))
    print(f"  📊 Current Price of Hyundai Motor: {current_price:,.0f} KRW")
    
    if current_price <= 0:
        print("  ❌ Invalid price.")
        return
        
    # Calculate Max Quantity for Limit Order
    # Fee buffer is small for limit order (0.015% usually included or separate)
    # Safely use 99.5% of cash
    safe_cash = cash * 0.995
    buy_qty = int(safe_cash / current_price)
    
    print(f"  🧮 Buy Quantity (Limit Order): {buy_qty} shares @ {current_price:,.0f} KRW")
    print(f"     Est. Total: {buy_qty * current_price:,.0f} KRW")
    
    if buy_qty > 0:
        print(f"  📈 Buying {buy_qty} shares of Hyundai Motor (Limit Order)...")
        # Limit Order (price=current_price)
        order_no = kis.trading.place_buy_order("005380", buy_qty, int(current_price))
        if order_no:
            print(f"     ✅ Order Placed: {order_no}")
            time.sleep(1)
            kis.trading.check_order_status(order_no)
        else:
            print("     ❌ Buy Order Failed")
    else:
        print("  ℹ️ Quantity is 0. Cannot buy.")

    print("\n" + "=" * 60)
    print("✅ RETRY COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    retry_buy()
