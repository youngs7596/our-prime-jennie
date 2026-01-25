
import redis
import json
import time

REDIS_URL = "redis://127.0.0.1:6379/0"

def inject_watchlist():
    r = redis.from_url(REDIS_URL, decode_responses=True)
    
    version_key = f"hot_watchlist:vMock_{int(time.time())}"
    
    payload = {
        "market_regime": "BULL",
        "score_threshold": 65,
        "stocks": [
            {
                "code": "005930",
                "name": "삼성전자",
                "llm_score": 85,
                "rank": 1,
                "is_tradable": True,
                "strategies": [],
                "trade_tier": "TIER1"
            }
        ]
    }
    
    r.set(version_key, json.dumps(payload))
    r.set("hot_watchlist:active", version_key)
    
    print(f"✅ Injected mock watchlist: {version_key}")
    print(f"Payload: {json.dumps(payload, indent=2, ensure_ascii=False)}")

if __name__ == "__main__":
    inject_watchlist()
