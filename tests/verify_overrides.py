
import sys
import os
import json
import logging

# Add project root to sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.config import get_float_for_symbol

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("VerifyOverrides")

def main():
    overrides_path = os.path.join(project_root, "config", "symbol_overrides.json")
    
    if not os.path.exists(overrides_path):
        logger.error(f"Overrides file not found: {overrides_path}")
        sys.exit(1)
        
    with open(overrides_path, 'r') as f:
        data = json.load(f)
        
    if not data or "symbols" not in data:
        logger.warning("Overrides file is empty or missing 'symbols' key.")
        return

    symbols_map = data["symbols"]
    if not symbols_map:
        logger.warning("No symbols found in overrides.")
        return

    # Pick first symbol
    symbol = list(symbols_map.keys())[0]
    overrides = symbols_map[symbol]
    
    logger.info(f"Testing overrides for symbol: {symbol}")
    
    # Test key: TIER2_VOLUME_MULTIPLIER (present in the json)
    test_key = "TIER2_VOLUME_MULTIPLIER"
    default_val = 1.0
    
    if test_key in overrides:
        expected_val = float(overrides[test_key])
        actual_val = get_float_for_symbol(symbol, test_key, default_val)
        
        logger.info(f"Key: {test_key}")
        logger.info(f"  Expected (JSON): {expected_val}")
        logger.info(f"  Actual (Config): {actual_val}")
        
        if abs(expected_val - actual_val) < 0.001:
            logger.info("✅ Verification Passed: Value matches override.")
        else:
            logger.error("❌ Verification Failed: Value mismatch.")
            sys.exit(1)
    else:
        logger.warning(f"Key {test_key} not found in overrides for {symbol}. Skipping verification.")

    # Test Default Fallback
    dummy_symbol = "999999"
    actual_default = get_float_for_symbol(dummy_symbol, test_key, default_val)
    if abs(actual_default - default_val) < 0.001:
        logger.info("✅ Verification Passed: Default fallback works.")
    else:
         logger.error(f"❌ Verification Failed: Default fallback expected {default_val}, got {actual_default}")

if __name__ == "__main__":
    main()
