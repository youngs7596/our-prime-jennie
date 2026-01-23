import os
import sys
import json
import time

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)

from shared.kis import KISClient

def execute_loss_cut_rebalance():
    print("=" * 60)
    print("🚀 STARTING PORTFOLIO REBALANCING (LOSS CUT -> HYUNDAI MOTOR)")
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

    # 2. Identify Losing Positions
    print("\n[Step 1] Identifying Losing Positions...")
    holdings = kis.trading.get_account_balance()
    
    losing_stocks = []
    
    print(f"{'Code':<8} {'Name':<20} {'Qty':<5} {'Avg Price':<12} {'Curr Price':<12} {'Return %':<10}")
    print("-" * 80)
    
    for stock in holdings:
        code = stock['code']
        name = stock['name']
        qty = stock['quantity']
        avg_price = stock['avg_price']
        curr_price = stock['current_price']
        
        if avg_price > 0:
            return_pct = (curr_price - avg_price) / avg_price * 100
        else:
            return_pct = 0.0
            
        print(f"{code:<8} {name[:18]:<20} {qty:<5} {avg_price:,.0f}       {curr_price:,.0f}       {return_pct:+.2f}%")
        
        # Check if losing (Return < 0)
        # Using a small threshold (-0.1%) to avoid noise if flat
        if return_pct < -0.1:
            losing_stocks.append({
                "code": code,
                "name": name,
                "qty": qty,
                "return_pct": return_pct
            })

    print("-" * 80)
    print(f"📉 Identified {len(losing_stocks)} losing positions.")

    # 3. Execute Sell Orders
    print("\n[Step 2] Executing Sell Orders...")
    total_sell_count = 0
    
    if not losing_stocks:
        print("  ✅ No losing stocks found. Skipping sell step.")
    else:
        for t in losing_stocks:
            print(f"  📉 Selling {t['qty']} shares of {t['name']} ({t['code']}) | Return: {t['return_pct']:.2f}%")
            # Market Price (price=0)
            order_no = kis.trading.place_sell_order(t['code'], t['qty'], 0)
            if order_no:
                print(f"     ✅ Order Placed: {order_no}")
                total_sell_count += 1
                time.sleep(0.5) # Avoid rate limit
            else:
                print(f"     ❌ Order Failed for {t['name']}")

    if total_sell_count > 0:
        print("\n⏳ Waiting 5 seconds for settlement reflection...")
        time.sleep(5)
        # Re-check cash just in case
        
    # 4. Check Cash & Buy Hyundai Motor
    print("\n[Step 3] Preparing Buy Order for Hyundai Motor (005380)...")
    
    # Refresh cash balance
    cash = kis.trading.get_cash_balance()
    print(f"  💰 Orderable Cash: {cash:,.0f} KRW")
    
    if cash < 50000: # Min buffer
        print("  ❌ Insufficient cash to buy anything.")
        return

    # Get Current Price of Hyundai Motor
    snapshot = kis.market_data.get_stock_snapshot("005380")
    if not snapshot:
        # Fallback if snapshot fails (rare)
        print("  ⚠️ Failed to get price snapshot. Assuming manual check needed.")
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
    print("✅ LOSS-CUT REBALANCING COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    execute_loss_cut_rebalance()
