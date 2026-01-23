import os
import sys
import json
import time
import math

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)

from shared.kis import KISClient

def execute_rebalance():
    print("=" * 60)
    print("🚀 STARTING PORTFOLIO REBALANCING")
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

    # 2. Confirm Holdings & Sell Targets
    print("\n[Step 1] Confirming Holdings...")
    holdings = kis.trading.get_account_balance()
    
    targets_to_sell = [
        {"code": "161390", "name": "Hankook Tire", "qty": 0},
        {"code": "086280", "name": "Hyundai Glovis", "qty": 0},
        {"code": "025560", "name": "Mirae Industries", "qty": 0}
    ]
    
    for h in holdings:
        for t in targets_to_sell:
            if h['code'] == t['code']:
                t['qty'] = h['quantity']
                print(f"  ✅ Holding Found: {t['name']} ({t['code']}) - {t['qty']} shares")

    # 3. Execute Sell Orders
    print("\n[Step 2] Executing Sell Orders...")
    total_sell_count = 0
    for t in targets_to_sell:
        if t['qty'] > 0:
            print(f"  📉 Selling {t['qty']} shares of {t['name']} ({t['code']})...")
            # Market Price (price=0)
            order_no = kis.trading.place_sell_order(t['code'], t['qty'], 0)
            if order_no:
                print(f"     ✅ Order Placed: {order_no}")
                # Wait for fill
                time.sleep(1)
                kis.trading.check_order_status(order_no)
                total_sell_count += 1
            else:
                print(f"     ❌ Order Failed for {t['name']}")
        else:
            print(f"  ℹ️ Skipping {t['name']} (0 shares)")

    if total_sell_count > 0:
        print("\n⏳ Waiting 3 seconds for settlement reflection...")
        time.sleep(3)
    
    # 4. Check Cash & Buy Hyundai Motor
    print("\n[Step 3] Preparing Buy Order for Hyundai Motor (005380)...")
    
    cash = kis.trading.get_cash_balance()
    print(f"  💰 Orderable Cash: {cash:,.0f} KRW")
    
    if cash < 50000: # Min buffer
        print("  ❌ Insufficient cash to buy anything.")
        return

    # Get Current Price of Hyundai Motor
    snapshot = kis.market_data.get_stock_snapshot("005380")
    if not snapshot:
        print("  ❌ Failed to get price for Hyundai Motor (005380)")
        return
        
    current_price = float(snapshot.get('price', 0))
    print(f"  📊 Current Price of Hyundai Motor: {current_price:,.0f} KRW")
    
    if current_price <= 0:
        print("  ❌ Invalid price.")
        return
        
    # Calculate Max Quantity
    # Buffer: 98% of cash to cover slippage/fees if market order price fluctuates up
    safe_cash = cash * 0.98 
    buy_qty = int(safe_cash / current_price)
    
    print(f"  🧮 Max Buy Quantity: {buy_qty} shares (Est. {buy_qty * current_price:,.0f} KRW)")
    
    if buy_qty > 0:
        print(f"  📈 Buying {buy_qty} shares of Hyundai Motor...")
        # Market Price (price=0)
        order_no = kis.trading.place_buy_order("005380", buy_qty, 0)
        if order_no:
            print(f"     ✅ Order Placed: {order_no}")
            time.sleep(1)
            kis.trading.check_order_status(order_no)
        else:
            print("     ❌ Buy Order Failed")
    else:
        print("  ℹ️ Quantity is 0. Cannot buy.")

    print("\n" + "=" * 60)
    print("✅ REBALANCING COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    execute_rebalance()
