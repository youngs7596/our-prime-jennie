
from shared.db.connection import session_scope
from sqlalchemy import text
import sys

# MariaDB: table names are case sensitive on Linux usually, but check core.py logic
# core.py usually maps "Portfolio" to "Portfolio" (or "Portfolio_mock")
# We'll just try SQL directly.

with session_scope() as s:
    try:
        # Check Portfolio
        rows = s.execute(text("SELECT STOCK_CODE, STOCK_NAME, STATUS, QUANTITY FROM Portfolio WHERE STOCK_CODE='005930'")).fetchall()
        print(f"Rows found: {rows}")
        
        # If it was marked SOLD (quantity=0), let's reset it to verify our PROTECTION logic works
        # If we leave it as SOLD, the reporter loop won't even try to delete it (since it's not in db_holdings or status!=HOLDING)
        # So we must set it to HOLDING to prove our new code PROTECTS it from being sold.
        
        if not rows or rows[0][2] == 'SOLD':
            print("Restoring 005930 to HOLDING for test...")
            s.execute(text("INSERT INTO Portfolio (STOCK_CODE, STOCK_NAME, STATUS, QUANTITY, AVERAGE_BUY_PRICE, CREATED_AT) VALUES ('005930', '삼성전자', 'HOLDING', 10, 70000, NOW()) ON DUPLICATE KEY UPDATE STATUS='HOLDING', QUANTITY=10"))
    except Exception as e:
        print(e)
