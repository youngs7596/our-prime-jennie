
import unittest
from unittest.mock import MagicMock, patch
import json
from datetime import datetime


# Import target class
import sys
import os

# Add project root and service dir to path
PROJECT_ROOT = os.getcwd()
SERVICE_DIR = os.path.join(PROJECT_ROOT, 'services/buy-scanner')
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, SERVICE_DIR)

# Import module directly (since 'buy-scanner' has a hyphen)
import opportunity_watcher
from opportunity_watcher import OpportunityWatcher

class TestRiskInjection(unittest.TestCase):
    # Patch the function imported inside opportunity_watcher module
    @patch('opportunity_watcher.get_enhanced_trading_context')
    def test_publish_signal_injects_risk_setting(self, mock_get_context):
        # 1. Setup Mock Context
        mock_ctx = MagicMock()
        mock_ctx.stop_loss_multiplier = 1.5
        mock_ctx.risk_off_level = 2
        mock_ctx.vix_regime = "HIGH_VOLATILITY"
        mock_ctx.position_size_pct = 50 # Multiplier should be 0.5
        mock_ctx.strategies_to_avoid = []
         # to avoid issues if attribute access
        
        # Mock get_enhanced_trading_context to return our mock context
        mock_get_context.return_value = mock_ctx

        # 2. Initialize Watcher with Mock Publisher
        mock_publisher = MagicMock()
        mock_config = MagicMock()
        
        watcher = OpportunityWatcher(mock_config, mock_publisher)
        watcher.market_regime = "BEAR"
        
        # Override _get_position_multiplier logic for test simplicity or rely on it using context
        # The actual code calls self._get_position_multiplier(). 
        # Let's inspect _get_position_multiplier implementation or mock it? 
        # Looking at previous view_file, _get_position_multiplier uses _get_trading_context.
        # So mocking get_enhanced_trading_context is sufficient.

        # 3. Simulate Signal
        signal = {
            'stock_code': '005930',
            'stock_name': 'Samsung',
            'signal_type': 'TEST_SIGNAL',
            'signal_reason': 'Test Reason',
            'current_price': 70000,
            'llm_score': 85,
            'market_regime': 'BEAR',
            'timestamp': datetime.now().isoformat()
        }

        # 4. Execute
        watcher.publish_signal(signal)

        # 5. Verify Payload
        self.assertTrue(mock_publisher.publish.called)
        call_args = mock_publisher.publish.call_args
        payload = call_args[0][0] # First arg of first call

        print("\n=== Generated Payload ===")
        print(json.dumps(payload, indent=2, default=str))

        # Check Candidate Risk Setting
        candidate = payload['candidates'][0]
        self.assertIn('risk_setting', candidate, "risk_setting missing in candidate")
        
        risk_setting = candidate['risk_setting']
        
        # Position Multiplier Verification: 
        # If context.position_size_pct is 50, _get_position_multiplier should return 0.5
        # (Assuming _get_position_multiplier logic works as seen in files)
        
        self.assertEqual(risk_setting['vix_regime'], "HIGH_VOLATILITY")
        self.assertEqual(risk_setting['risk_off_level'], 2)
        self.assertEqual(risk_setting['stop_loss_multiplier'], 1.5)
        
        # Stop Loss Pct Check: -0.05 * 1.5 = -0.075
        expected_sl = -0.05 * 1.5
        self.assertAlmostEqual(risk_setting['stop_loss_pct'], expected_sl)
        
        print("\n✅ Risk Setting Injection Verified!")

if __name__ == '__main__':
    unittest.main()
