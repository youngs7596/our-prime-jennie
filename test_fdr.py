
import FinanceDataReader as fdr
import logging
import sys

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    print("Testing fdr.StockListing('KOSPI')...")
    df = fdr.StockListing('KOSPI')
    print(f"Successfully retrieved {len(df)} records.")
    print(df.head())
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
