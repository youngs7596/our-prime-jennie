
import logging
import http.client as http_client
import FinanceDataReader as fdr

# Enable HTTP connection debugging
http_client.HTTPConnection.debuglevel = 1

# Initialize logging
logging.basicConfig()
logging.getLogger().setLevel(logging.DEBUG)
requests_log = logging.getLogger("requests.packages.urllib3")
requests_log.setLevel(logging.DEBUG)
requests_log.propagate = True

print("--- Starting FDR Debug ---")
try:
    # This call is known to fail
    df = fdr.StockListing('KOSPI')
    print("Success")
except Exception as e:
    print(f"\n--- Exception Caught ---\n{e}")
