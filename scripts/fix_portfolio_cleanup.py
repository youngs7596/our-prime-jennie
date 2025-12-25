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

def fix_general_inconsistencies():
    init_engine()
    with session_scope() as session:
        # Find all items that are HOLDING but marked as SOLD
        stmt = select(Portfolio).where(Portfolio.status == 'HOLDING').where(Portfolio.sell_state == 'SOLD')
        rows = session.execute(stmt).scalars().all()
        
        for p in rows:
            print(f"Found inconsistent record: {p.stock_name} ({p.stock_code}) ID {p.id}")
            print(f"  - Status: {p.status}, SellState: {p.sell_state}")
            print(f"  -> Updating Status to CLOSED")
            p.status = 'CLOSED'
            
        print(f"Processed {len(rows)} records.")

if __name__ == "__main__":
    fix_general_inconsistencies()
