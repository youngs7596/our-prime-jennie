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

def inspect_portfolio():
    init_engine()
    with session_scope() as session:
        stmt = select(Portfolio).order_by(Portfolio.stock_code, Portfolio.id)
        rows = session.execute(stmt).scalars().all()
        print(f"{'ID':<5} {'Code':<8} {'Name':<15} {'Status':<10} {'SellState':<15} {'Qty':<5} {'AvgPrice':<12} {'TotalAmount':<15} {'HighPrice':<10} {'Created':<20}")
        print("-" * 120)
        for r in rows:
            qty = r.quantity if r.quantity is not None else 0
            avg_price = r.average_buy_price if r.average_buy_price is not None else 0.0
            total = r.total_buy_amount if r.total_buy_amount is not None else 0.0
            high_price = r.current_high_price if r.current_high_price is not None else 0.0
            created = str(r.created_at) if r.created_at else ""
            
            print(f"{r.id:<5} {r.stock_code:<8} {r.stock_name:<15} {r.status:<10} {str(r.sell_state):<15} {qty:<5} {avg_price:<12.2f} {total:<15.2f} {high_price:<10.2f} {created:<20}")

if __name__ == "__main__":
    inspect_portfolio()
