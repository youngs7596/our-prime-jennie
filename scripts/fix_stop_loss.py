import sys
import os
sys.path.append(os.getcwd())
try:
    from shared.db.connection import init_engine, session_scope
    from shared.db.models import Portfolio
    from sqlalchemy import select
except ImportError:
    print("Please run from project root")
    sys.exit(1)

def fix_missing_stop_loss():
    init_engine()
    with session_scope() as session:
        # Find HOLDING items with missing or zero stop loss price
        stmt = select(Portfolio).where(Portfolio.status == 'HOLDING')
        rows = session.execute(stmt).scalars().all()
        
        updated_count = 0
        for p in rows:
            sl = p.stop_loss_price if p.stop_loss_price is not None else 0.0
            
            if sl <= 1.0: # Almost zero
                # Default Stop Loss: -5% from Avg Price
                avg_price = p.average_buy_price or 0.0
                if avg_price > 0:
                    new_sl = avg_price * 0.95
                    print(f"Update {p.stock_name} ({p.stock_code}) Stop Loss: {sl} -> {new_sl:,.0f} (Avg: {avg_price:,.0f})")
                    p.stop_loss_price = new_sl
                    updated_count += 1
                else:
                     print(f"Skipping {p.stock_name} ({p.stock_code}) - Avg Price is 0")

        print(f"Committed updates for {updated_count} records.")

if __name__ == "__main__":
    fix_missing_stop_loss()
