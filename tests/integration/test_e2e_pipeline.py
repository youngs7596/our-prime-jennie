import pytest
from datetime import datetime, timezone
from shared.db import repository as repo
from shared.config import ConfigManager

class TestE2EPipeline:
    
    @pytest.fixture
    def setup_config(self):
        config = ConfigManager()
        # Mock configuration if needed
        # config.set('TRADING_MODE', 'MOCK')
        return config

    def test_buy_and_sell_flow(self, mock_kis, patch_session_scope, setup_config, BuyExecutorClass, SellExecutorClass, monkeypatch):
        """
        Verify the full trading lifecycle:
        1. Buy Signal -> Buy Executor -> DB (Portfolio)
        2. Sell (Stop Loss) -> Sell Executor -> DB (Portfolio Cleared)
        """
        # SellExecutor uses KIS API only in REAL mode; in MOCK mode it queries DB for prices (which is empty here).
        monkeypatch.setenv("TRADING_MODE", "REAL")
        
        import shared.redis_cache
        print(f"\n[DEBUG] shared.redis_cache.get_redis_connection: {shared.redis_cache.get_redis_connection}")
        r = shared.redis_cache.get_redis_connection()
        print(f"[DEBUG] r: {r}")
        print(f"[DEBUG] r.set('test', '1'): {r.set('test', '1')}")
        
        session = patch_session_scope
        
        # --- 1. Buy Execution ---
        executor = BuyExecutorClass(kis=mock_kis, config=setup_config, gemini_api_key="test_key")
        
        # Mock Scan Result (Input from Buy Scanner)
        scan_result = {
            'candidates': [{
                'stock_code': '005930',
                'stock_name': '삼성전자',
                'llm_score': 85.0,
                'is_tradable': True,
                'trade_tier': 'TIER1',
                'buy_signal_type': 'GOLDEN_CROSS',
                'current_price': 70000,
                'llm_reason': 'Good fundamentals'
            }],
            'market_regime': 'BULL',
            'strategy_preset': {'name': 'TEST_PRESET', 'params': {}}
        }
        
        # Execute Buy (Process Signal)
        result = executor.process_buy_signal(scan_result, dry_run=False)
        
        # Verification
        assert result['status'] == 'success'
        assert result['stock_code'] == '005930'
        assert result['order_no'] == 'BUY_12345'
        
        # Check KIS Call
        mock_kis.place_buy_order.assert_called_once()
        args, kwargs = mock_kis.place_buy_order.call_args
        assert kwargs['stock_code'] == '005930'
        
        # Check DB (Portfolio)
        portfolio = repo.get_active_portfolio(session)
        assert len(portfolio) == 1
        assert portfolio[0]['code'] == '005930'
        assert portfolio[0]['quantity'] > 0
        original_qty = portfolio[0]['quantity']
        
        # Check DB (TradeLog - Buy)
        # Assuming you have a way to query trade logs, or check repo
        # Here we trust execute_trade_and_log worked if portfolio is updated (since they are in same transaction logic typically)
        
        print(f"\n[Buy Verified] Purchased {original_qty} shares of 005930.")
        
        # --- 2. Sell Execution (Stop Loss Simulation) ---
        sell_executor = SellExecutorClass(kis=mock_kis, config=setup_config)
        
        # Simulate Price Drop (Stop Loss Trigger)
        # Buy Price was ~70000 (from snapshot in mock_kis or current_price in payload)
        # Let's say price drops to 60000
        mock_kis.get_stock_snapshot.return_value = {
            'price': 60000,
            'high': 61000,
            'low': 59000, 'volume': 500000, 'open': 61000
        }
        
        # Manually trigger sell order (simulating Price Monitor or Sell Scanner)
        sell_result = sell_executor.execute_sell_order(
            stock_code='005930',
            stock_name='삼성전자',
            quantity=original_qty,
            sell_reason='Stop Loss Triggered',
            dry_run=False
        )
        
        # Verification
        assert sell_result['status'] == 'success'
        assert sell_result['order_no'] == 'SELL_67890'
        
        # Check KIS Call
        mock_kis.place_sell_order.assert_called_once()
        args, kwargs = mock_kis.place_sell_order.call_args
        assert kwargs['stock_code'] == '005930'
        assert kwargs['quantity'] == original_qty
        
        # Check DB (Portfolio) - Should be empty or quantity 0
        portfolio_after = repo.get_active_portfolio(session)
        # If get_active_portfolio filters out sold items (quantity=0 or status logic), it should be empty.
        # Impl: repo.get_active_portfolio typically queries where quantity > 0 ??
        # Let's verify based on our knowledge of repository.py implementation 
        # Usually selling updates the record or marks it as closed.
        
        # Assuming get_active_portfolio returns only active holdings
        # If it returns empty list, that means it's sold.
        # If it returns item with 0 quantity, that's also valid for "sold".
        active_items = [p for p in portfolio_after if p['quantity'] > 0]
        assert len(active_items) == 0
        
        print(f"[Sell Verified] Sold {original_qty} shares. Portfolio is empty.")

