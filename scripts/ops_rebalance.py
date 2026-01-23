import os
import sys
import json
import time
import argparse
import logging

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)

from shared.kis import KISClient
from shared.db.connection import session_scope
from shared.database.trading import execute_trade_and_log

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def setup_client():
    secrets_path = os.path.join(PROJECT_ROOT, "secrets.json")
    if not os.path.exists(secrets_path):
        print(f"❌ Error: secrets.json not found at {secrets_path}")
        return None

    with open(secrets_path, "r") as f:
        secrets = json.load(f)
    
    kis = KISClient(
        app_key=secrets.get("kis-r-app-key"),
        app_secret=secrets.get("kis-r-app-secret"),
        base_url="https://openapi.koreainvestment.com:9443",
        account_prefix=secrets.get("kis-r-account-no"),
        account_suffix="01",
        token_file_path=os.path.join(PROJECT_ROOT, "tokens", "kis_token.json"),
        trading_mode="REAL"
    )
    
    if not kis.authenticate():
        print("❌ Authentication Failed")
        return None
    
    return kis

def get_holdings(kis):
    print("   [Info] Fetching Account Balance...")
    holdings = kis.trading.get_account_balance()
    return holdings

def identify_sell_targets(holdings, mode, excluded_codes=None):
    if excluded_codes is None:
        excluded_codes = []
    
    targets = []
    print(f"\n   [Analysis] Identifying Sell Targets (Mode: {mode})")
    print(f"   {'Code':<8} {'Name':<20} {'Qty':<5} {'Avg':<10} {'Curr':<10} {'Rtn %':<8} {'Action'}")
    print("   " + "-"*80)
    
    for stock in holdings:
        code = stock['code']
        # Skip if excluded (e.g., the target stock itself)
        if code in excluded_codes:
            continue
            
        name = stock['name']
        qty = stock['quantity']
        avg = stock['avg_price']
        curr = stock['current_price']
        rtn = ((curr - avg) / avg * 100) if avg > 0 else 0
        
        action = "-"
        is_target = False
        
        if mode == 'all':
            is_target = True
            action = "SELL (All)"
        elif mode == 'loss-cut':
            if rtn < -0.1: # Threshold
                is_target = True
                action = "SELL (Loss)"
        
        print(f"   {code:<8} {name[:18]:<20} {qty:<5} {avg:<10,.0f} {curr:<10,.0f} {rtn:<+8.2f} {action}")
        
        if is_target:
            targets.append({
                'code': code, 
                'name': name, 
                'qty': qty,
                'price': 0 # Market order
            })
            
    return targets

def execute_rebalance(target_code, mode='loss-cut', dry_run=False):
    print("=" * 60)
    print(f"🚀 OPS: PORTFOLIO REBALANCING (Target: {target_code}, Mode: {mode})")
    if dry_run:
        print("⚠️  DRY RUN MODE - No actual orders will be placed.")
    print("=" * 60)
    
    kis = setup_client()
    if not kis: return

    # 1. Identify Sell Targets
    holdings = get_holdings(kis)
    # Exclude the buy target from selling
    sell_targets = identify_sell_targets(holdings, mode, excluded_codes=[target_code])
    
    if not sell_targets:
        print("\n✅ No stocks identified for selling. Skipping sell step.")
    else:
        print(f"\n📉 Executing Sell Orders ({len(sell_targets)} stocks)...")
        for t in sell_targets:
            print(f"   Selling {t['qty']} shares of {t['name']} ({t['code']})...")
            if not dry_run:
                order_no = kis.trading.place_sell_order(t['code'], t['qty'], 0)
                if order_no:
                    print(f"     ✅ Order Placed: {order_no}")
                    
                    # DB 업데이트: TRADELOG + ACTIVE_PORTFOLIO
                    try:
                        # 현재가 조회 (매도 가격)
                        snapshot = kis.market_data.get_stock_snapshot(t['code'])
                        sell_price = float(snapshot.get('price', 0)) if snapshot else 0
                        
                        with session_scope() as session:
                            stock_info = {'code': t['code'], 'name': t['name']}
                            execute_trade_and_log(
                                session, 
                                trade_type="SELL",
                                stock_info=stock_info,
                                quantity=t['qty'],
                                price=sell_price,
                                llm_decision={"reason": f"REBALANCE_TO: 리밸런싱 매도 (Target: {target_code})"},
                                strategy_signal="REBALANCE_TO"
                            )
                        print(f"     ✅ DB Updated (TRADELOG + ACTIVE_PORTFOLIO)")
                    except Exception as e:
                        logger.error(f"DB 업데이트 실패: {e}")
                        print(f"     ⚠️ DB Update Failed: {e}")
                    
                    time.sleep(0.3) # Rate limit
                else:
                    print(f"     ❌ Order Failed")
            else:
                print(f"     [DryRun] Would sell {t['qty']} shares (Market Order)")

    # Wait for settlement if not dry run and sold something
    if not dry_run and sell_targets:
        print("\n⏳ Waiting 5 seconds for settlement reflection...")
        time.sleep(5)

    # 2. Buy Target
    print(f"\n📈 Preparing Buy Order for Target: {target_code}...")
    
    # Refresh Cash
    if not dry_run:
        cash = kis.trading.get_cash_balance()
    else:
        cash = 1000000 # Dummy cash
        
    print(f"   💰 Available Cash: {cash:,.0f} KRW")
    
    if cash < 50000:
        print("   ❌ Insufficient cash (< 50,000 KRW). Stopping.")
        return

    # Get Price
    snapshot = kis.market_data.get_stock_snapshot(target_code)
    if not snapshot:
        print(f"   ❌ Failed to get snapshot for {target_code}")
        return
        
    curr_price = float(snapshot.get('price', 0))
    name = snapshot.get('name', target_code)
    print(f"   📊 Target Price ({name}): {curr_price:,.0f} KRW")
    
    if curr_price <= 0: return

    # Calc Qty (99% of cash for Limit Order)
    limit_buffer = 0.99
    buy_qty = int((cash * limit_buffer) / curr_price)
    
    print(f"   🧮 Buy Quantity: {buy_qty} shares (Est: {buy_qty * curr_price:,.0f} KRW)")
    
    if buy_qty > 0:
        if not dry_run:
            print(f"   🚀 Placing Limit Buy Order...")
            order_no = kis.trading.place_buy_order(target_code, buy_qty, int(curr_price))
            if order_no:
                print(f"     ✅ Order Placed: {order_no}")
                
                # DB 업데이트: TRADELOG + ACTIVE_PORTFOLIO
                try:
                    with session_scope() as session:
                        stock_info = {'code': target_code, 'name': name}
                        execute_trade_and_log(
                            session, 
                            trade_type="BUY",
                            stock_info=stock_info,
                            quantity=buy_qty,
                            price=curr_price,
                            llm_decision={"reason": f"REBALANCE_TO: 리밸런싱 집중 매수"},
                            strategy_signal="REBALANCE_TO"
                        )
                    print(f"     ✅ DB Updated (TRADELOG + ACTIVE_PORTFOLIO)")
                except Exception as e:
                    logger.error(f"DB 업데이트 실패: {e}")
                    print(f"     ⚠️ DB Update Failed: {e}")
            else:
                print(f"     ❌ Order Failed")
        else:
            print(f"     [DryRun] Would buy {buy_qty} shares @ {curr_price:,.0f} KRW")
    else:
        print("   ℹ️ Qty is 0.")

    print("\n✅ Rebalancing Logic Complete.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True, help="Target stock code to buy (e.g. 005380)")
    parser.add_argument("--mode", default="loss-cut", choices=["loss-cut", "all"], help="Sell mode")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without trading")
    
    args = parser.parse_args()
    
    execute_rebalance(args.target, args.mode, args.dry_run)
