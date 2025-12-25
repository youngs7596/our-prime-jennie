import sys
import os
sys.path.append(os.getcwd())
try:
    from shared.db.connection import init_engine, session_scope
    from shared.db.models import Portfolio
    from sqlalchemy import select
except ImportError:
    # If shared package not found (not running from root)
    print("Please run from project root")
    sys.exit(1)

def fix_portfolio():
    init_engine()
    with session_scope() as session:
        # 1. Soft Delete duplicate Hyundai (ID 69)
        # Instead of DELETE, set status to CLOSED so it doesn't show in HOLDING queries
        stmt = select(Portfolio).where(Portfolio.id == 69)
        p69 = session.execute(stmt).scalar_one_or_none()
        if p69 and p69.stock_code == '005380':
            print(f"Soft-deleting duplicate Hyundai ID {p69.id} (Status: {p69.status} -> CLOSED)")
            p69.status = 'CLOSED'
        else:
            print("ID 69 not found or not Hyundai.")

        # 2. Update all HOLDING items recalculating total_buy_amount
        stmt = select(Portfolio).where(Portfolio.status == 'HOLDING')
        holdings = session.execute(stmt).scalars().all()
        
        for p in holdings:
            if p.id == 69: continue # Just in case
            
            # Recalculate Total Buy Amount
            old_total = p.total_buy_amount or 0
            if p.quantity and p.average_buy_price:
                new_total = float(p.quantity) * float(p.average_buy_price)
                
                # Update if different (allow small float diff)
                if abs(old_total - new_total) > 100.0:
                    print(f"Updated {p.stock_name} ({p.stock_code}) ID {p.id}: Total {old_total:,.0f} -> {new_total:,.0f}")
                    p.total_buy_amount = new_total
            
            # Fix High Price
            current_high = p.current_high_price if p.current_high_price is not None else 0.0
            avg_price = p.average_buy_price or 0.0
            if current_high < avg_price:
                 print(f"  - Resetting High Price {current_high:,.0f} -> {avg_price:,.0f} (was lower than avg)")
                 p.current_high_price = avg_price

        print("Committing changes...")

if __name__ == "__main__":
    fix_portfolio()
