import pytest
from unittest.mock import MagicMock, patch, ANY
import sys
import os
import pandas as pd
from datetime import datetime
import importlib.util

# Project Root Setup
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Removed global import logic
# from scanner import BuyScanner # Removed top-level import
from shared.market_regime import MarketRegimeDetector, StrategySelector

@pytest.fixture
def scanner_module_setup():
    """Setup scanner module and clean up after test"""
    # Dynamic import for scanner
    spec = importlib.util.spec_from_file_location(
        "scanner", 
        os.path.join(PROJECT_ROOT, "services/buy-scanner/scanner.py")
    )
    scanner_module = importlib.util.module_from_spec(spec)
    
    # Patch sys.modules safely
    with patch.dict(sys.modules, {"scanner": scanner_module}):
        spec.loader.exec_module(scanner_module)
        yield scanner_module

@pytest.fixture
def BuyScanner(scanner_module_setup):
    """Get BuyScanner class from the loaded module"""
    return scanner_module_setup.BuyScanner

@pytest.fixture
def mock_kis():
    return MagicMock()

@pytest.fixture
def mock_config():
    config = MagicMock()
    config.get_int.return_value = 20 # Default period
    config.get_float.return_value = 0.5
    config.get.return_value = "MOCK"
    config.get_bool.return_value = False
    return config

@pytest.fixture
def mock_db_session():
    return MagicMock()

@pytest.fixture
def scanner_instance(BuyScanner, mock_kis, mock_config):
    with patch("scanner.MarketRegimeDetector") as mock_detector_cls, \
         patch("scanner.StrategySelector") as mock_selector_cls, \
         patch("scanner.FactorScorer") as mock_scorer_cls:
        
        scanner = BuyScanner(mock_kis, mock_config)
        scanner.regime_detector = mock_detector_cls.return_value
        scanner.strategy_selector = mock_selector_cls.return_value
        scanner.factor_scorer = mock_scorer_cls.return_value
        # Default mock behavior for instance methods to avoid side effects in unit tests unless specified
        return scanner

class TestBuyScanner:
    def test_detect_signals_golden_cross(self, scanner_instance):
        """Test Golden Cross signal detection"""
        # Mock strategy.check_golden_cross
        with patch("scanner.strategy.check_golden_cross", return_value=True):
            # Setup inputs
            daily_prices = pd.DataFrame({'CLOSE_PRICE': [100]*20})
            last_price = 100
            rsi = 50
            regime = MarketRegimeDetector.REGIME_BULL
            active_strategies = [StrategySelector.STRATEGY_TREND_FOLLOWING]
            
            signal_type, metrics = scanner_instance._detect_signals(
                "005930", daily_prices, last_price, rsi, regime, active_strategies, kospi_prices_df=None
            )
            
            assert signal_type == 'GOLDEN_CROSS'
            assert metrics['signal'] == 'GOLDEN_CROSS_5_20'

    def test_detect_signals_rsi_oversold(self, scanner_instance):
        """Test RSI Oversold signal detection"""
        # Mock RSI calculation is done by caller, passed as arg
        rsi = 10 # Below mocked threshold (20)
        
        # Setup inputs
        daily_prices = pd.DataFrame({'CLOSE_PRICE': [100]*20})
        last_price = 100
        regime = MarketRegimeDetector.REGIME_SIDEWAYS
        active_strategies = [StrategySelector.STRATEGY_MEAN_REVERSION]
        
        # Mock bollinger bands to avoid calculation error or return 0
        with patch("scanner.strategy.calculate_bollinger_bands", return_value=80): 
            signal_type, metrics = scanner_instance._detect_signals(
                "005930", daily_prices, last_price, rsi, regime, active_strategies, kospi_prices_df=None
            )
        
        assert signal_type == 'RSI_OVERSOLD'
        assert metrics['rsi'] == 10

    def test_scan_stocks_parallel_flow(self, scanner_instance):
        """Test parallel scanning flow"""
        # Mock dependencies
        watchlist = {'005930': {'name': 'Samsung', 'trade_tier': 'TIER1'}}
        owned_codes = set()
        daily_prices_batch = {'005930': pd.DataFrame({'CLOSE_PRICE': [100]*20})}
        
        # Mock database calls within method
        with patch("scanner.get_recently_traded_stocks_batch", return_value=[]), \
             patch("scanner.database.get_daily_prices_batch", return_value=daily_prices_batch), \
             patch("scanner.database.get_daily_prices", return_value=pd.DataFrame()), \
             patch("scanner.session_scope"):
             
            # Mock _analyze_stock to return a dummy candidate
            scanner_instance._analyze_stock = MagicMock(return_value={'code': '005930', 'factor_score': 10})
            
            candidates = scanner_instance._scan_stocks_parallel(
                watchlist, owned_codes, MarketRegimeDetector.REGIME_BULL, 
                ['TREND_FOLLOWING'], MagicMock()
            )
            
            assert len(candidates) == 1
            assert candidates[0]['code'] == '005930'

    def test_tier2_safety_check_pass(self, scanner_instance):
        """Test Tier2 safety check passing"""
        # Mock inputs
        daily_prices = pd.DataFrame({
            'VOLUME': [100]*19 + [200], # Spillke in volume
            'PRICE_DATE': pd.date_range(end='2025-01-01', periods=20, freq='D')
        })
        current_price = 100
        rsi = 50 # 40~70
        regime = MarketRegimeDetector.REGIME_SIDEWAYS # Not Bear
        
        # Make sure current price > 120 MA (Simulated by mocking if needed, but logic is inside)
        # Actually _check_tier2_conditions checks 120MA if data available.
        # Let's mock dataframe with enough data
        prices_long = pd.DataFrame({
            'VOLUME': [100]*119 + [200],
            'CLOSE_PRICE': [90]*120,
            'PRICE_DATE': pd.date_range(end='2025-01-01', periods=120, freq='D')
        })
        # Current price 100 > MA120 (90)
        
        result = scanner_instance._check_tier2_conditions(
            "005930", prices_long, 100, 50, regime
        )
        
        # We need to verify passed logic. 
        # Logic: 
        # 1. Volume: 200 >= 100 * 1.2 (True)
        # 2. RSI: 40 <= 50 <= 70 (True)
        # 3. Regime: !Bear (True)
        # 4. Price >= 120MA (100 >= 90) (True)
        # All 4 met -> passed
        
        assert result['passed'] is True
        assert result['met_count'] >= 3

    def test_analyze_market_regime_success(self, scanner_instance):
        """Test market regime analysis with successful dependencies"""
        # Mock Redis cache to return None (miss)
        with patch("scanner.database.get_market_regime_cache", return_value=None), \
             patch("scanner.database.get_daily_prices", return_value=pd.DataFrame({'CLOSE_PRICE': [100]*20})), \
             patch("scanner.database.set_market_regime_cache") as mock_set_cache:
            
            # Mock internal components
            scanner_instance.regime_detector.detect_regime.return_value = (
                MarketRegimeDetector.REGIME_BULL, {'metric': 'value'}
            )
            scanner_instance.strategy_selector.select_strategies.return_value = ['TREND_FOLLOWING']
            scanner_instance.regime_detector.get_dynamic_risk_setting.return_value = {'risk': 'low'}
            
            # Mock KIS for KOSPI snapshot (TRADING_MODE != MOCK in config mock default is MOCK)
            # Default config mock returns "MOCK", so it uses daily_prices last row.
            
            result = scanner_instance._analyze_market_regime(MagicMock())
            
            assert result['regime'] == MarketRegimeDetector.REGIME_BULL
            assert result['active_strategies'] == ['TREND_FOLLOWING']
            assert scanner_instance._market_analysis_cache is not None
            mock_set_cache.assert_called_once()

    def test_scan_buy_opportunities_full_flow(self, scanner_instance):
        """Test the main orchestrator scan_buy_opportunities"""
        # Prepare Mocks
        mock_regime_result = {
            'regime': MarketRegimeDetector.REGIME_BULL,
            'active_strategies': ['TREND_FOLLOWING'],
            'market_context_dict': {},
            'risk_setting': {},
            'strategy_preset': {'name': 'test', 'params': {}}
        }
        
        scanner_instance._analyze_market_regime = MagicMock(return_value=mock_regime_result)
        scanner_instance._scan_stocks_parallel = MagicMock(return_value=[
            {'code': '005930', 'name': 'Samsung', 'factor_score': 90},
            {'code': '000660', 'name': 'SK Hynix', 'factor_score': 80}
        ])
        
        # Mock database calls
        with patch("scanner.session_scope"), \
             patch("scanner.get_active_watchlist", return_value={'005930': {}, '000660': {}}), \
             patch("scanner.get_active_portfolio", return_value=[]), \
             patch("scanner.database.get_redis_connection") as mock_redis_conn:
            
            # Mock Redis Lock
            mock_redis = MagicMock()
            mock_redis_conn.return_value = mock_redis
            mock_redis.set.return_value = True # Lock acquired
            
            scanner_instance.kis.get_cash_balance.return_value = 10000000
            
            result = scanner_instance.scan_buy_opportunities()
            
            assert result is not None
            assert len(result['candidates']) == 2
            assert result['candidates'][0]['code'] == '005930'
            assert result['market_regime'] == MarketRegimeDetector.REGIME_BULL

    def test_analyze_stock_realtime_update(self, scanner_instance):
        """Test [Fast Hands] functionality: realtime price update (New Row)"""
        # Setup yesterday's data - use pd.date_range to avoid MagicMock issues
        daily_prices = pd.DataFrame({
            'PRICE_DATE': pd.date_range(end='2024-12-31', periods=1), 
            'CLOSE_PRICE': [100.0],
            'HIGH_PRICE': [105.0],
            'LOW_PRICE': [95.0],
            'OPEN_PRICE': [98.0],
            'VOLUME': [1000.0]
        })
        
        # Mock KIS snapshot with today's price (higher)
        scanner_instance.kis.get_stock_snapshot.return_value = {
            'price': 110, # New price
            'high': 112,
            'low': 99,
            'volume': 2000
        }
        
        scanner_instance.config.get_int.return_value = 1 # Small requirement
        
        # Mock scoring
        scanner_instance._calculate_factor_score = MagicMock(return_value=(80, {}))
        
        # Mock signal detection to rely on updated price
        # We'll check if daily_prices_df passed to _detect_signals has the new row
        mock_detect = MagicMock(return_value=('GOLDEN_CROSS', {}))
        scanner_instance._detect_signals = mock_detect
        
        # Mock database Sentiment
        with patch("scanner.database.get_sentiment_score", return_value={'score': 50}):
             scanner_instance._analyze_stock(
                "005930", {}, daily_prices, 
                MarketRegimeDetector.REGIME_BULL, [], None
             )
             
             # Verify _detect_signals called with updated dataframe
             # The dataframe should now have 2 rows (yesterday + today, or updated last row if same date)
             # Since we used yesterday, it should append or update. Logic says if last != today, append.
             args, _ = mock_detect.call_args
             passed_df = args[1]
             # Check if last row has new price
             assert passed_df.iloc[-1]['CLOSE_PRICE'] == 110.0
             assert passed_df.iloc[-1]['VOLUME'] == 2000

    def test_detect_signals_momentum(self, scanner_instance):
        """Test Momentum strategy signal"""
        # Mock momentum calc
        with patch("scanner.strategy.calculate_momentum", return_value=5.0): # > threshold 3.0
            signal, metrics = scanner_instance._detect_signals(
                "005930", pd.DataFrame(), 100, 50, 
                MarketRegimeDetector.REGIME_BULL, 
                [StrategySelector.STRATEGY_MOMENTUM], 
                None
            )
            assert signal == 'MOMENTUM'
            assert metrics['momentum_pct'] == 5.0

    def test_detect_signals_relative_strength(self, scanner_instance):
        """Test Relative Strength strategy signal"""
        with patch("scanner.strategy.calculate_relative_strength", return_value=3.0): # > threshold 2.0
            signal, metrics = scanner_instance._detect_signals(
                "005930", pd.DataFrame(), 100, 50, 
                MarketRegimeDetector.REGIME_BULL, 
                [StrategySelector.STRATEGY_RELATIVE_STRENGTH], 
                pd.DataFrame({'CLOSE_PRICE': [100]*20})
            )
            assert signal == 'RELATIVE_STRENGTH'
            assert metrics['relative_strength_pct'] == 3.0

    def test_calculate_factor_score(self, scanner_instance):
        """Test factor score calculation"""
        # Mock factor scorer methods
        scanner_instance.factor_scorer.calculate_momentum_score.return_value = (80, {})
        scanner_instance.factor_scorer.calculate_quality_score.return_value = (70, {})
        scanner_instance.factor_scorer.calculate_value_score.return_value = (60, {})
        scanner_instance.factor_scorer.calculate_technical_score.return_value = (90, {})
        scanner_instance.factor_scorer.calculate_final_score.return_value = (75, {'applied_weights': {}})
        
        score, summary = scanner_instance._calculate_factor_score(
            "005930", {'roe': 10}, pd.DataFrame(), pd.DataFrame(), 
            MarketRegimeDetector.REGIME_BULL
        )
        
        assert score == 75
        assert summary['momentum_score'] == 80
        assert summary['final_score'] == 75

    def test_serialize_candidate(self, scanner_instance):
        """Test candidate serialization"""
        candidate = {
            'code': '005930',
            'name': 'Samsung', 
            'daily_prices_df': pd.DataFrame(), 
            'stock_info': {'name': 'Samsung', 'roe': 15, 'extra': 'remove'},
            'factor_score': 90
        }
        
        serialized = scanner_instance._serialize_candidate(candidate)
        
        assert 'daily_prices_df' not in serialized
        assert serialized['stock_info']['name'] == 'Samsung'
        assert serialized['stock_info']['roe'] == 15
        assert 'extra' not in serialized['stock_info']

    def test_analyze_stock_reverse_signal(self, scanner_instance):
        """Test reverse signal penalty for specific news categories"""
        daily_prices = pd.DataFrame({
            'CLOSE_PRICE': [100.0]*20, 
            'HIGH_PRICE': [105.0]*20,
            'LOW_PRICE': [95.0]*20,
            'OPEN_PRICE': [100.0]*20,
            'VOLUME': [1000.0]*20,
            'PRICE_DATE': pd.date_range(end='2025-01-01', periods=20, freq='D')
        })
        
        scanner_instance.kis.get_stock_snapshot.return_value = None

        scanner_instance._detect_signals = MagicMock(return_value=('GOLDEN_CROSS', {'trade_tier': 'TIER1'}))
        scanner_instance._calculate_factor_score = MagicMock(return_value=(80.0, {}))
        
        with patch("scanner.database.get_sentiment_score", return_value={
            'score': 80, 'category': '수주', 'reason': 'test'
        }):
             result = scanner_instance._analyze_stock(
                "005930", {'name': 'Samsung'}, daily_prices, 
                MarketRegimeDetector.REGIME_BULL, [], None
             )
             
             assert result is not None
             assert result['factor_score'] == 64.0
             assert result['factors']['reverse_signal_category'] == '수주'
             assert result['factors']['reverse_signal_warning'] is True

    def test_analyze_stock_realtime_update_existing_row(self, scanner_instance):
        """Test [Fast Hands] updating existing today's row"""
        # Use pd.date_range to avoid MagicMock issues
        daily_prices = pd.DataFrame({
            'PRICE_DATE': pd.date_range(start='2025-01-01', periods=1), 
            'CLOSE_PRICE': [100.0],
            'HIGH_PRICE': [105.0],
            'LOW_PRICE': [95.0],
            'VOLUME': [1000.0]
        })
        
        scanner_instance.kis.get_stock_snapshot.return_value = {
            'price': 110.0, 
            'high': 105.0, 
            'low': 95.0, 
            'volume': 2000.0 
        }
        
        scanner_instance.config.get_int.return_value = 1
        scanner_instance._calculate_factor_score = MagicMock(return_value=(80, {}))
        mock_detect = MagicMock(return_value=('GOLDEN_CROSS', {}))
        scanner_instance._detect_signals = mock_detect
        
        # Patch datetime.now() to return the same date as our test data
        with patch("scanner.database.get_sentiment_score", return_value={'score': 50}), \
             patch("scanner.datetime") as mock_datetime:
            # Make datetime.now() return our fixed date (2025-01-01)
            from datetime import datetime as real_datetime
            fixed_dt = real_datetime(2025, 1, 1)
            mock_datetime.now.return_value = fixed_dt
            # Preserve other datetime behavior
            mock_datetime.side_effect = lambda *args, **kw: real_datetime(*args, **kw) if args else mock_datetime
            
            scanner_instance._analyze_stock(
                "005930", {}, daily_prices, 
                MarketRegimeDetector.REGIME_BULL, [], None
            )
             
            args, _ = mock_detect.call_args
            passed_df = args[1]
            # Should still be 1 row, updated
            assert len(passed_df) == 1
            assert passed_df.iloc[-1]['CLOSE_PRICE'] == 110.0
            assert passed_df.iloc[-1]['VOLUME'] == 2000.0

    def test_scan_buy_opportunities_bear_market(self, scanner_instance):
        """Test scanning behavior in Bear Market (Restricted)"""
        # Mock Bear Regime
        mock_regime_result = {
            'regime': MarketRegimeDetector.REGIME_BEAR,
            'active_strategies': [],
            'market_context_dict': {'regime': 'BEAR'},
            'risk_setting': {},
            'strategy_preset': {'name': 'bear_preset', 'params': {}}
        }
        scanner_instance._analyze_market_regime = MagicMock(return_value=mock_regime_result)
        
        # Scenario 1: ALLOW_BEAR_TRADING = False (Default)
        # Should only scan RECON tier or return empty if no RECON
        scanner_instance.config.get_bool.return_value = False 
        
        with patch("scanner.session_scope"), \
             patch("scanner.get_active_watchlist", return_value={'005930': {'trade_tier': 'TIER1'}, '000660': {'trade_tier': 'RECON'}}), \
             patch("scanner.get_active_portfolio", return_value=[]), \
             patch("scanner.database.get_redis_connection"):
            
            # Mock _scan_stocks_parallel
            scanner_instance._scan_stocks_parallel = MagicMock(return_value=[])
            
            result = scanner_instance.scan_buy_opportunities()
            
            # result might be empty if _scan_stocks_parallel returns empty, but we check if it was called with correct filter.
            assert scanner_instance._scan_stocks_parallel.called
            # Verify watchlist passed to scan contains only RECON
            args, _ = scanner_instance._scan_stocks_parallel.call_args
            passed_watchlist = args[0]
            assert '000660' in passed_watchlist
            assert '005930' not in passed_watchlist

    def test_analyze_stock_bear_strategies(self, scanner_instance):
        """Test specific Bear strategies (Snipe Dip)"""
        # Provide complete DataFrame to avoid KeyError in _analyze_stock (Fast Hands update logic)
        daily_prices = pd.DataFrame({
            'CLOSE_PRICE': [100.0]*30,
            'HIGH_PRICE': [105.0]*30,
            'LOW_PRICE': [95.0]*30,
            'OPEN_PRICE': [100.0]*30,
            'VOLUME': [1000.0]*30,
            'PRICE_DATE': pd.date_range(end='2025-01-01', periods=30, freq='D')
        })
        current_price = 100.0
        
        # Mock KIS snapshot to None to skip Fast Hands internal update logic
        scanner_instance.kis.get_stock_snapshot.return_value = None
        
        # Mock bear context
        bear_context = {'bear_mode': True}
        stock_info = {
            'bear_strategy': {
                'market_regime_strategy': {'strategy_type': 'BEAR_SNIPE_DIP'}
            }
        }
        
        # Mock StrategySelector mapping
        scanner_instance.strategy_selector.map_llm_strategy.return_value = StrategySelector.STRATEGY_BEAR_SNIPE_DIP
        
        # Mock bear strategy evaluation
        # Mock factor scorer and sentiment to allow completion
        scanner_instance._calculate_factor_score = MagicMock(return_value=(80.0, {}))
        
        with patch("scanner.bear_strategies.evaluate_snipe_dip", return_value={'signal': 'BEAR_DIP_BUY', 'key_metrics': {}}) as mock_eval, \
             patch("scanner.database.get_sentiment_score", return_value={'score': 50}):
            
            result = scanner_instance._analyze_stock(
                "005930", stock_info, daily_prices, 
                MarketRegimeDetector.REGIME_BEAR, [], None,
                bear_context=bear_context
            )
            
            assert result is not None
            assert result['buy_signal_type'] == 'BEAR_DIP_BUY'
            mock_eval.assert_called_once()
    
    def test_scan_redis_lock_failure(self, scanner_instance):
        """Test behavior when Redis lock acquisition fails (Ghost Trade Prevention)"""
        # Mock Bull Regime
        scanner_instance._analyze_market_regime = MagicMock(return_value={
            'regime': MarketRegimeDetector.REGIME_BULL,
            'active_strategies': [],
            'market_context_dict': {},
            'risk_setting': {}
        })
        
        # Return 1 candidate
        scanner_instance._scan_stocks_parallel = MagicMock(return_value=[
            {'code': '005930', 'name': 'Samsung', 'factor_score': 90}
        ])
        
        with patch("scanner.session_scope"), \
             patch("scanner.get_active_watchlist", return_value={'005930': {}}), \
             patch("scanner.get_active_portfolio", return_value=[]), \
             patch("scanner.database.get_redis_connection") as mock_redis_conn:
            
            mock_redis = MagicMock()
            mock_redis_conn.return_value = mock_redis
            # Lock acquisition fails (already locked)
            mock_redis.set.return_value = False 
            
            scanner_instance.kis.get_cash_balance.return_value = 10000000
            
            result = scanner_instance.scan_buy_opportunities()
            
            # Since lock failed, candidate list should be empty
            assert len(result['candidates']) == 0
