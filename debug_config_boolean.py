
import sys
import os
import logging

# Add project root to path
sys.path.insert(0, os.getcwd())

from shared.config import ConfigManager
from shared.db.connection import get_session, ensure_engine_initialized
from shared.db import repository

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("debug")

def test_bool_config():
    # Initialize DB (Essential!)
    ensure_engine_initialized()
    
    key = "DISABLE_MARKET_OPEN_CHECK"
    cfg = ConfigManager()
    
    # 1. Verify Default
    print("\n[1] Checking Default Config Registry")
    if key in cfg._defaults:
        entry = cfg._defaults[key]
        print(f"Key Found: {key}")
        print(f"Entry: {entry}")
        val = entry["value"] if isinstance(entry, dict) else entry
        print(f"Default Value: {val} (Type: {type(val)})")
    else:
        print(f"Key {key} NOT FOUND in defaults!")
        return

    # 2. Simulate Save (False)
    print("\n[2] Simulating Save (False)")
    val_to_save = False
    str_val = str(val_to_save)
    print(f"Saving '{str_val}' to DB...")
    
    with get_session() as session:
        repository.set_config(session, key, str_val, "Debug Test")
        session.commit() # Ensure commit
        
        # Verify raw DB value
        raw_db_val = repository.get_config(session, key, silent=True)
        print(f"Raw DB Reading: '{raw_db_val}' (Type: {type(raw_db_val)})")
        
        # Verify ConfigManager conversion
        # Clear cache to force DB read
        cfg.clear_cache(key)
        
        converted_val = cfg.get(key)
        print(f"ConfigManager.get(): {converted_val} (Type: {type(converted_val)})")
        
        if converted_val is False:
             print("SUCCESS: False converted correctly")
        else:
             print(f"FAILURE: Expected False, got {converted_val}")

    # 3. Simulate Save (True)
    print("\n[3] Simulating Save (True)")
    val_to_save = False
    str_val = str(val_to_save)
    print(f"Saving '{str_val}' to DB...")

    with get_session() as session:
        repository.set_config(session, key, str_val, "Debug Test")
        session.commit()
        
        # Verify raw DB value
        raw_db_val = repository.get_config(session, key, silent=True)
        print(f"Raw DB Reading: '{raw_db_val}' (Type: {type(raw_db_val)})")
        
        cfg.clear_cache(key)
        converted_val = cfg.get(key)
        print(f"ConfigManager.get(): {converted_val} (Type: {type(converted_val)})")
        
        if converted_val is True:
             print("SUCCESS: True converted correctly")
        else:
             print(f"FAILURE: Expected True, got {converted_val}")
    
    # 4. Check Env Override
    env_val = os.getenv(key)
    print(f"\n[4] Environment Variable Check: {env_val}")

if __name__ == "__main__":
    test_bool_config()
