
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
from opportunity_watcher import BuyOpportunityWatcher

class TestRiskInjection(unittest.TestCase):
    def test_publish_signal_injects_risk_setting(self):
        # 1. Setup Mock Context
        mock_ctx = MagicMock()
        mock_ctx.stop_loss_multiplier = 1.5
        mock_ctx.risk_off_level = 2
        mock_ctx.vix_regime = "HIGH_VOLATILITY"
        mock_ctx.position_multiplier = 0.5  # Correct attribute name
        mock_ctx.strategies_to_avoid = []
        
        # 2. Initialize Watcher with Mock Publisher
        mock_publisher = MagicMock()
        mock_config = MagicMock()
        
        # Mock Redis connection to avoid connection errors during init
        with patch('opportunity_watcher.redis.from_url') as mock_redis:
            mock_redis.return_value.ping.return_value = True
            watcher = BuyOpportunityWatcher(mock_config, mock_publisher)
        
        # Inject Mock Context directly
        watcher._trading_context = mock_ctx
        watcher.market_regime = "BEAR"

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
        
        self.assertEqual(risk_setting['vix_regime'], "HIGH_VOLATILITY")
        self.assertEqual(risk_setting['risk_off_level'], 2)
        self.assertEqual(risk_setting['stop_loss_multiplier'], 1.5)
        self.assertEqual(risk_setting['position_size_ratio'], 0.5)
        
        # Stop Loss Pct Check: -0.05 * 1.5 = -0.075
        expected_sl = -0.05 * 1.5
        self.assertAlmostEqual(risk_setting['stop_loss_pct'], expected_sl)
        
        print("\n✅ Risk Setting Injection Verified!")

if __name__ == '__main__':
    unittest.main()
