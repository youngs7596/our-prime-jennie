import os
import sys
import logging

# Add project root to path
sys.path.append(os.getcwd())

from shared.db.connection import session_scope, ensure_engine_initialized
from sqlalchemy import text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_migration():
    logger.info("Starting Migration Verification...")
    
    # Force use of new port/host if not set
    if "MARIADB_PORT" not in os.environ:
        os.environ["MARIADB_PORT"] = "3307"
    if "MARIADB_HOST" not in os.environ:
        os.environ["MARIADB_HOST"] = "127.0.0.1"

    logger.info(f"Connecting to {os.environ['MARIADB_HOST']}:{os.environ['MARIADB_PORT']}...")

    try:
        ensure_engine_initialized()
        with session_scope() as session:
            # Check Tables (use correct names from dump/models)
            tables = ["agent_commands", "watchlist", "stock_master", "job_status"]
            for table in tables:
                try:
                    # Case insensitive lookup check
                    count = session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
                    logger.info(f"✅ Table '{table}': {count} rows")
                except Exception as e:
                    logger.warning(f"⚠️ Table '{table}' check failed: {e}")
                    
            logger.info("✅ Database connectivity verified.")
            
    except Exception as e:
        logger.error(f"❌ Verification Failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    verify_migration()
