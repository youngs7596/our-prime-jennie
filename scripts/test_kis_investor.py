import os
import sys
import logging
import json

# Set up project root
PROJECT_ROOT = '/app'
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from shared.kis.gateway_client import KISGatewayClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_investor_trend():
    client = KISGatewayClient()
    code = '000270' # Kia
    print(f"Testing Investor Trend for {code}...")
    
    # Use the proxy client to hit the gateway
    trends = client.get_market_data().get_investor_trend(code)
    
    if trends:
        print(f"✅ Found {len(trends)} trend records")
        print("Sample record:", json.dumps(trends[-1], indent=2))
    else:
        print("❌ No trend data returned")

if __name__ == "__main__":
    test_investor_trend()
