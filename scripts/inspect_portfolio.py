
import sys
import os

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from shared.db.connection import session_scope, init_engine
from shared.db.repository import get_active_portfolio, get_config, set_config
from shared.db import models

def inspect_and_update():
    init_engine()
    with session_scope() as session:
        # 1. Check and Update Config
        current_limit = get_config(session, 'MAX_PORTFOLIO_SIZE')
        print(f"Current MAX_PORTFOLIO_SIZE in DB: {current_limit}")
        
        if current_limit != '30':
            print("Updating MAX_PORTFOLIO_SIZE to 30...")
            set_config(session, 'MAX_PORTFOLIO_SIZE', '30', 'Portfolio size limit increased by user request')
            print("Update complete.")
        
        # 2. Inspect Active Portfolio
        portfolio = get_active_portfolio(session)
        print(f"\nActive Portfolio Count: {len(portfolio)}")
        print("-" * 60)
        print(f"{'ID':<5} {'Code':<10} {'Name':<20} {'Quantity':<10} {'Status'}")
        print("-" * 60)
        
        ids = [p['id'] for p in portfolio]
        
        # get_active_portfolio returns dicts, need to query DB to get status if not in dict
        # Actually get_active_portfolio only returns HOLDING/PARTIAL.
        # Let's verify what they are.
        
        for p in portfolio:
            print(f"{p['id']:<5} {p['code']:<10} {p['name']:<20} {p['quantity']:<10} HOLDING/PARTIAL")

if __name__ == "__main__":
    inspect_and_update()
