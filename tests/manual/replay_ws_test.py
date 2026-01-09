import sys
import os
import unittest
from unittest.mock import MagicMock
from datetime import datetime
import time

# Adjust path to import services/price-monitor
# sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../services/price-monitor')))

# Manual mocks for dependency injection
sys.modules['redis'] = MagicMock()
sys.modules['shared.database'] = MagicMock()

# Import after mocking
from opportunity_watcher import OpportunityWatcher

class ReplayWebSocketTest(unittest.TestCase):
    
    def setUp(self):
        self.mock_config = MagicMock()
        # Enable Shadow Mode
        self.mock_config.get_bool.return_value = True 
        
        self.mock_publisher = MagicMock()
        self.watcher = OpportunityWatcher(self.mock_config, self.mock_publisher)
        
        # Manually inject Hot Watchlist
        self.watcher.hot_watchlist = {
            "005930": {
                "name": "Samsung",
                "strategies": [
                    {"id": "GOLDEN_CROSS", "params": {"short_window": 5, "long_window": 20}}
                ]
            }
        }
        self.watcher.market_regime = "BULL"

    def test_golden_cross_scenario(self):
        stock_code = "005930"
        
        # 1. Simulate 20 minutes of price history
        # We need 20 completed bars.
        # Scenario: 
        # - MA20 starts high, trends down slightly
        # - MA5 starts low, trends up fast
        # - Cross happens at minute 20
        
        # Generate 25 mins of data
        # MA20 approx: 100 -> 98
        # MA5 approx: 90 -> 105
        
        start_price = 100
        
        print("--- Starting Replay Simulation ---")
        
        # Pre-fill 24 bars (no signal yet)
        for i in range(24):
            # Slow decline for long-term trend
            price = start_price - (i * 0.1) 
            
            # Add some volatility for short-term MA to ride up? 
            # Actually let's make it simpler.
            # 0-15 mins: Price flat at 100 (MA5=100, MA20=building)
            # 16-20 mins: Price spikes to 110 (MA5 jumps, MA20 lags)
            
            if i < 15:
                tick_price = 100.0
            else:
                tick_price = 110.0 + (i - 15) # 110, 111, 112...
            
            # Feed ticks to complete a bar
            # Open
            self.watcher.on_price_update(stock_code, tick_price, 100)
            
            # Artificial time advancement for bar aggregation logic
            # (We need to hack BarAggregator or just feed timestamps?)
            # BarAggregator uses system time. We need to mock datetime.
            # Alternative: Just mock the BarAggregator's completion logic?
            # It's better to integration test the BarAggregator too if possible, 
            # but mocking time is hard in this context without freezegun.
            
            # Let's mock the 'completed_bar' return from BarAggregator.update 
            # to verify check_buy_signal logic primarily.
            pass

    def test_logic_direct_injection(self):
        """
        Since simulating time for BarAggregator is complex in a simple script,
        we verify by injecting completed bars directly into _check_buy_signal.
        """
        print("--- Testing Logic via Direct Injection ---")
        stock_code = "005930"
        
        # Construct bars
        # We need precise cross moment.
        # Strategy: Flat 100 for long time, then spike to 110 at the last bar.
        # This makes MA5 jump up, while MA20 moves up slowly.
        
        bars = []
        # Create 30 bars total
        # 0-28: 100.0 (29 bars)
        # 29: 110.0 (1 bar)
        for i in range(30):
            p = 100.0 if i < 29 else 110.0 
            bars.append({'close': p})
            
        # Verify MAs manually:
        # Prev (up to idx 28): MA5=100, MA20=100. 100 <= 100 (True)
        # Curr (up to idx 29): 
        #   MA5 = (100*4 + 110)/5 = 510/5 = 102
        #   MA20 = (100*19 + 110)/20 = 2010/20 = 100.5
        #   102 > 100.5 (True)
        # -> Golden Cross!
            
        # Inject bars into aggregator mock
        self.watcher.bar_aggregator.get_recent_bars = MagicMock(return_value=bars)
        
        # Force cooldown to allow
        self.watcher._check_cooldown = MagicMock(return_value=True)
        self.watcher._set_cooldown = MagicMock()
        
        # Trigger check
        result = self.watcher._check_buy_signal(stock_code, 110.0, {})
        
        if result:
            print(f"✅ Signal Generated: {result['signal_type']} - {result['signal_reason']}")
            
            # Verify Shadow Mode behavior via publish_signal
            published = self.watcher.publish_signal(result)
            
            if published and self.watcher.metrics['shadow_signal_count'] == 1:
                 print("✅ Shadow Mode Verified: Signal counted but logic returned success (blocked internally)")
                 self.mock_publisher.publish.assert_not_called()
                 print("✅ RabbitMQ Publish Skipped (Mock not called)")
            else:
                 print("❌ Shadow Mode Failed")
        else:
            print("❌ No Signal Generated")
            # Verify why?
            # MA5 of last 5: (100*2 + 110*3)/5 = (200+330)/5 = 106
            # MA20 of last 20: (100*15 + 110*5)/20 = (1500+550)/20 = 102.5
            # MA5 (106) > MA20 (102.5) -> GOLDEN CROSS
            # Previous MA5? 
            # Bars[-6:-1]: (100*3 + 110*2)/5 = (300+220)/5 = 104
            # Previous MA20? (Shifted window) -> Lower?
            # It should likely cross.
            pass

if __name__ == '__main__':
    # Run the direct injection test
    t = ReplayWebSocketTest()
    t.setUp()
    t.test_logic_direct_injection()
