

import logging
import sys
from unittest.mock import MagicMock

# Mocking database modules to avoid import errors
sys.modules['sqlalchemy'] = MagicMock()
sys.modules['sqlalchemy.orm'] = MagicMock()
sys.modules['sqlalchemy.ext.declarative'] = MagicMock()
sys.modules['shared.database'] = MagicMock()
sys.modules['shared.db'] = MagicMock()
sys.modules['shared.db.connection'] = MagicMock()
sys.modules['shared.db.models'] = MagicMock()
sys.modules['shared.auth'] = MagicMock()

# Now import JennieBrain
from shared.llm import JennieBrain

# Logging Setup
logging.basicConfig(level=logging.INFO)

import time

def test_competitor_benefit_analysis():
    print("=== Initializing JennieBrain ===")
    try:
        brain = JennieBrain()
    except Exception as e:
        print(f"Failed to init JennieBrain: {e}")
        return

    test_cases = [
        # ... same cases ...
        "Samsung Fire Bluefangs lost 3 consecutive games against Hyundai Capital",
        "Samsung Fire Data Center caught fire, service disrupted for 3 hours",
        "Samsung Fire stock price drops 1% amid market volatility",
    ]
    
    print("\n=== Testing LLM-First Competitor Analysis (Unified Qwen3:32B) ===")
    
    for i, news in enumerate(test_cases):
        print(f"\n[{i+1}/{len(test_cases)}] 📰 Input: {news[:60]}...")
        start_time = time.time()
        try:
            # First request might be slow (model load)
            result = brain.analyze_competitor_benefit(news)
            duration = time.time() - start_time
            
            is_risk = result.get('is_risk')
            event_type = result.get('event_type')
            reason = result.get('reason')
            score = result.get('competitor_benefit_score')
            
            status = "🔴 RISK DETECTED" if is_risk else "🟢 IGNORED (Safe)"
            print(f"   -> Result: {status} ({duration:.2f}s)")
            print(f"      Event: {event_type} (Score: {score})")
            print(f"      Reason: {reason}")
            
        except Exception as e:
            print(f"   -> Error: {e}")

if __name__ == "__main__":
    test_competitor_benefit_analysis()


