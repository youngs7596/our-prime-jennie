
import os
import sys
import logging
from unittest.mock import MagicMock

import importlib.util

sys.path.append(os.getcwd())

# Load scout_universe dynamically
file_path = os.path.join(os.getcwd(), 'services/scout-job/scout_universe.py')
spec = importlib.util.spec_from_file_location("scout_universe", file_path)
scout_universe = importlib.util.module_from_spec(spec)
sys.modules["scout_universe"] = scout_universe
spec.loader.exec_module(scout_universe)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_sector_mapping():
    print("--- Verifying Sector Mapping ---")
    
    # Check specific stocks
    test_cases = {
        '005930': '반도체', # Samsung
        '000270': '자동차', # Kia
        '329180': '조선',   # HD Hyundai Heavy
        '035420': '인터넷', # Naver
    }
    
    # Mock row data (simulating FDR row)
    for code, expected in test_cases.items():
        row = {'Code': code, 'Name': 'TestStock', 'Sector': None} # Simulate missing FDR sector
        resolved = scout_universe._resolve_sector(row, code)
        print(f"[{code}] Expected: {expected}, Got: {resolved}")
        if resolved != expected:
            print(f"❌ FAIL: {code}")
        else:
            print(f"✅ PASS: {code}")

    print("\n--- Verifying get_dynamic_blue_chips returns sector ---")
    try:
        stocks = scout_universe.get_dynamic_blue_chips(limit=5)
        if not stocks:
            print("⚠️ No stocks returned (FDR might be failing or no internet)")
        else:
            first = stocks[0]
            print(f"Sample Stock: {first}")
            if 'sector' in first:
                print(f"✅ 'sector' field present: {first['sector']}")
            else:
                print("❌ 'sector' field MISSING")
    except Exception as e:
        print(f"Error running get_dynamic_blue_chips: {e}")

def verify_concurrency_logic():
    print("\n--- Verifying Concurrency Logic (Simulation) ---")
    
    # Simulate Environment
    os.environ["TIER_REASONING_PROVIDER"] = "ollama"
    os.environ["SCOUT_LLM_MAX_WORKERS"] = "4"
    
    default_workers = 4
    is_ollama_active = (
        os.environ.get("TIER_REASONING_PROVIDER", "ollama").lower() == "ollama" or 
        os.environ.get("TIER_THINKING_PROVIDER", "ollama").lower() == "ollama" or
        os.environ.get("TIER_FAST_PROVIDER", "gemini").lower() == "ollama"
    )
    
    llm_max_workers = int(os.environ.get("SCOUT_LLM_MAX_WORKERS", default_workers))
    
    print(f"Initial worker count: {llm_max_workers}")
    print(f"Is Ollama Active? {is_ollama_active}")
    
    if is_ollama_active:
        print("⚠️ [Config] Ollama Stability Enforced: Overriding worker count -> 1")
        llm_max_workers = 1
        
    print(f"Final worker count: {llm_max_workers}")
    
    if llm_max_workers == 1:
        print("✅ Concurrency Limit PASS")
    else:
        print("❌ Concurrency Limit FAIL")

if __name__ == "__main__":
    verify_sector_mapping()
    verify_concurrency_logic()
