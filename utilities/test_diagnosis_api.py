import requests
import json
import time

url = 'http://localhost:8091/api/diagnose'

print(f"Checking {url}...")
# 서비스 시작 대기
max_retries = 10
for i in range(max_retries):
    try:
        response = requests.get(url, timeout=30)
        print(f"Status Code: {response.status_code}")
        print("Response JSON:")
        print(json.dumps(response.json(), indent=2, ensure_ascii=False))
        
        if response.status_code == 200:
            print("\n✅ Verification Successful!")
            report = response.json().get('report', '')
            if "FAIL" in report or "ERROR" in report:
                print("⚠️ Report contains FAIL or ERROR. Please check the content.")
            else:
                print("👍 System Report looks healthy.")
            break
        else:
            print(f"Failed with status {response.status_code}")
            
    except Exception as e:
        print(f"Attempt {i+1}/{max_retries} failed: {e}")
        time.sleep(2)
    
    if i == max_retries - 1:
        print("\n❌ Verification Failed after all retries.")
