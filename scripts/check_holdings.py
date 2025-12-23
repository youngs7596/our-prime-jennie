import requests
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_holdings():
    # KIS Gateway Mock URL (mapped to 9080)
    url = "http://localhost:9080/api/account/balance"
    try:
        response = requests.post(url, json={})
        if response.status_code == 200:
            data = response.json()
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            print(f"Error: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    check_holdings()
