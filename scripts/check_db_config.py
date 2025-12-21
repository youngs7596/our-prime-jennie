import os
import sys
from sqlalchemy import create_engine, text

sys.path.append(os.getcwd())
from shared.db.connection import init_engine, session_scope

def check_config():
    if "MARIADB_PORT" not in os.environ:
        os.environ["MARIADB_PORT"] = "3307"
    if "MARIADB_HOST" not in os.environ:
        os.environ["MARIADB_HOST"] = "127.0.0.1"

    print(f"Connecting to {os.environ['MARIADB_HOST']}:{os.environ['MARIADB_PORT']}...")
    try:
        init_engine(None, None, None, None)
        with session_scope() as session:
            # Check lower_case_table_names
            res = session.execute(text("SHOW VARIABLES LIKE 'lower_case_table_names'")).fetchone()
            print(f"Variable {res[0]}: {res[1]}")
            
            # Check table count in jennie_db
            res = session.execute(text("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='jennie_db'")).scalar()
            print(f"Tables in jennie_db: {res}")
            
            # List some tables
            res = session.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema='jennie_db' LIMIT 5")).fetchall()
            print("Sample tables:", [r[0] for r in res])

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_config()
