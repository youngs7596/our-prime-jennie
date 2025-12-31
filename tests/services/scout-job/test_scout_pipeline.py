# tests/services/scout-job/test_scout_pipeline.py

import pytest
from unittest.mock import MagicMock, patch
import pandas as pd
from datetime import datetime, timezone
import sys
import os

# Project root setup
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
sys.path.insert(0, PROJECT_ROOT)

from services.scout_job_module import scout_pipeline
from shared.hybrid_scoring import QuantScoreResult

@pytest.fixture
def mock_quant_scorer():
    return MagicMock()

@pytest.fixture
def mock_db_conn():
    return MagicMock()

@pytest.fixture
def mock_brain():
    return MagicMock()

@pytest.fixture
def mock_archivist():
    return MagicMock()

@pytest.fixture
def sample_stock_info():
    return {
        'code': '005930',
        'info': {
            'name': 'Samsung Electronics',
            'sentiment_score': 80,
            'sector': 'Technology',
            'reasons': ['Good fundamentals']
        },
        'snapshot': {
            'pbr': 1.2,
            'per': 10.5,
            'market_cap': 500000000
        }
    }

class TestProcessQuantScoringTask:
    def test_insufficient_data(self, mock_quant_scorer, mock_db_conn, sample_stock_info):
        """Test handling of insufficient daily price data"""
        with patch('shared.database.get_daily_prices') as mock_get_prices:
            # Return empty DataFrame
            mock_get_prices.return_value = pd.DataFrame()
            
            result = scout_pipeline.process_quant_scoring_task(
                sample_stock_info, mock_quant_scorer, mock_db_conn
            )
            
            assert result.is_valid is False
            assert '데이터 부족' in result.invalid_reason

    def test_successful_scoring(self, mock_quant_scorer, mock_db_conn, sample_stock_info):
        """Test successful quant scoring"""
        with patch('shared.database.get_daily_prices') as mock_get_prices:
            # Mock sufficient data
            mock_get_prices.return_value = pd.DataFrame({'close': range(100)})
            
            # Mock scorer result
            mock_quant_result = QuantScoreResult(
                stock_code='005930', stock_name='Samsung',
                total_score=85.0, momentum_score=20.0, quality_score=15.0,
                value_score=10.0, technical_score=10.0, news_stat_score=15.0,
                supply_demand_score=15.0, matched_conditions=[],
                condition_win_rate=None, condition_sample_count=0,
                condition_confidence='LOW', is_valid=True
            )
            mock_quant_scorer.calculate_total_quant_score.return_value = mock_quant_result
            
            result = scout_pipeline.process_quant_scoring_task(
                sample_stock_info, mock_quant_scorer, mock_db_conn
            )
            
            assert result.is_valid is True
            assert result.total_score == 85.0

class TestSmartSkipFilter:
    def test_skip_low_quant_score(self):
        """Test skipping due to low quant score"""
        quant_result = MagicMock(total_score=20.0)
        should_skip, reason = scout_pipeline.should_skip_hunter(quant_result)
        
        # Uses default config values if not mocked, but let's assume default is > 20
        # Wait, default configs might be loaded from env or defaults.
        # Let's mock ConfigManager to be sure.
        with patch('services.scout_job_module.scout_pipeline._cfg.get_float') as mock_get_float:
            mock_get_float.side_effect = lambda key, default: default
            
            assert should_skip is True
            assert 'Quant점수 낮음' in reason

    def test_skip_high_rsi(self):
        """Test skipping due to high RSI (overbought)"""
        quant_result = MagicMock(total_score=50.0, details={'rsi': 85})
        
        with patch('services.scout_job_module.scout_pipeline._cfg.get_float') as mock_get_float:
            mock_get_float.side_effect = lambda key, default: default
            
            should_skip, reason = scout_pipeline.should_skip_hunter(
                quant_result, news_sentiment=50
            )
            
            # Default smart_skip_rsi_max is 80
            assert should_skip is True
            assert 'RSI 과매수' in reason

    def test_competitor_benefit_override(self):
        """Test that competitor benefit overrides skip logic"""
        quant_result = MagicMock(total_score=10.0) # Very low score
        
        should_skip, reason = scout_pipeline.should_skip_hunter(
            quant_result, competitor_bonus=5.0
        )
        
        assert should_skip is False
        assert reason == ""

class TestPhase1HunterV5Task:
    @patch('shared.database.get_competitor_benefit_score')
    @patch('shared.hybrid_scoring.format_quant_score_for_prompt')
    def test_hunter_pass(self, mock_fmt_quant, mock_get_benefit, 
                         sample_stock_info, mock_brain, mock_archivist):
        """Test Hunter Phase successfully passing"""
        mock_get_benefit.return_value = {'score': 0, 'reason': ''}
        mock_fmt_quant.return_value = "Quant Context"
        
        # FIX: Set float values for all score attributes used in logging
        quant_result = MagicMock()
        quant_result.total_score = 60.0
        quant_result.momentum_score = 15.0
        quant_result.quality_score = 10.0
        quant_result.value_score = 10.0
        quant_result.technical_score = 5.0
        quant_result.news_stat_score = 10.0
        quant_result.supply_demand_score = 10.0
        quant_result.details = {}
        quant_result.condition_win_rate = 0.6
        
        snapshot_cache = {'005930': {'per': 10, 'pbr': 1}}
        news_cache = {'005930': "Good News"}
        
        # Mock Brain response
        mock_brain.get_jennies_analysis_score_v5.return_value = {
            'score': 80, 'reason': 'Strong Buy'
        }
        
        result = scout_pipeline.process_phase1_hunter_v5_task(
            sample_stock_info, mock_brain, quant_result, 
            snapshot_cache, news_cache, mock_archivist
        )
        
        assert result['passed'] is True
        assert result['hunter_score'] == 80
        assert result['code'] == '005930'

    @patch('shared.database.get_competitor_benefit_score')
    @patch('shared.hybrid_scoring.format_quant_score_for_prompt')
    def test_hunter_fail_and_shadow_log(self, mock_fmt_quant, mock_get_benefit,
                                        sample_stock_info, mock_brain, mock_archivist):
        """Test Hunter Phase failing and logging to Shadow Radar"""
        mock_get_benefit.return_value = {'score': 0}
        mock_fmt_quant.return_value = "Quant Context"
        
        # FIX: Set float values for all score attributes used in logging
        quant_result = MagicMock()
        quant_result.total_score = 60.0
        quant_result.momentum_score = 15.0
        quant_result.quality_score = 10.0
        quant_result.value_score = 10.0
        quant_result.technical_score = 5.0
        quant_result.news_stat_score = 10.0
        quant_result.supply_demand_score = 10.0
        quant_result.details = {}
        
        # FIX: Ensure snapshot is truthy (not empty) to bypass early return check "if not snapshot:"
        snapshot_cache = {'005930': {'per': 10}}
        
        # Mock Brain response (Low Score)
        mock_brain.get_jennies_analysis_score_v5.return_value = {
            'score': 40, 'reason': 'Weak'
        }
        
        result = scout_pipeline.process_phase1_hunter_v5_task(
            sample_stock_info, mock_brain, quant_result, 
            snapshot_cache, {}, mock_archivist
        )
        
        print(f"\nDEBUG: result={result}")
        print(f"DEBUG: passed={result.get('passed')}")
        print(f"DEBUG: hunter_score={result.get('hunter_score')}")
        print(f"DEBUG: call_count={mock_archivist.log_shadow_radar.call_count}")
        
        assert result['passed'] is False
        # Verify Shadow Radar Logging called
        mock_archivist.log_shadow_radar.assert_called_once()
        args = mock_archivist.log_shadow_radar.call_args[0][0]
        assert args['rejection_stage'] == 'HUNTER'
        assert args['stock_code'] == '005930'

class TestPhase23JudgeV5Task:
    @patch('shared.hybrid_scoring.format_quant_score_for_prompt')
    def test_judge_approval(self, mock_fmt_quant, 
                           sample_stock_info, mock_brain, mock_archivist):
        """Test Judge Phase approval"""
        mock_fmt_quant.return_value = "Quant Context"
        
        phase1_result = {
            'code': '005930',
            'info': sample_stock_info['info'],
            'decision_info': {},
            'quant_result': MagicMock(total_score=70.0, condition_win_rate=0.6, details={}),
            'hunter_score': 80,
            'snapshot': {'per': 10}
        }
        
        # Mock Brain
        mock_brain.run_debate_session.return_value = "Debate Log"
        mock_brain.run_judge_scoring_v5.return_value = {
            'score': 85, 'grade': 'A', 'reason': 'Excellent'
        }
        
        # 70(Quant) * 0.6 + 85(LLM) * 0.4 = 42 + 34 = 76 (Hybrid)
        # 76 >= 75 -> Tradable
        
        result = scout_pipeline.process_phase23_judge_v5_task(
            phase1_result, mock_brain, mock_archivist
        )
        
        assert result['approved'] is True
        assert result['is_tradable'] is True
        assert result['trade_tier'] == 'TIER1'
        mock_archivist.log_decision_ledger.assert_called_once()

    @patch('shared.hybrid_scoring.format_quant_score_for_prompt')
    def test_judge_reject_safety_lock(self, mock_fmt_quant, 
                                     sample_stock_info, mock_brain, mock_archivist):
        """Test Judge Phase rejection due to Safety Lock (Large Score Diff)"""
        mock_fmt_quant.return_value = "Quant Context"
        
        phase1_result = {
            'code': '005930',
            'info': sample_stock_info['info'],
            'decision_info': {},
            'quant_result': MagicMock(total_score=30.0, condition_win_rate=None, details={}), # Low Quant
            'hunter_score': 80,
            'snapshot': {}
        }
        
        mock_brain.run_debate_session.return_value = "Debate Log"
        # LLM gives high score (Hallucination check)
        mock_brain.run_judge_scoring_v5.return_value = {
            'score': 90, 'grade': 'S', 'reason': 'Superb'
        }
        
        # Diff |30 - 90| = 60 >= 30 (Safety Lock Triggered)
        # Quant < LLM: 0.75 * 30 + 0.25 * 90 = 22.5 + 22.5 = 45.0
        # Hybrid 45 < 50 -> Approved=False
        
        result = scout_pipeline.process_phase23_judge_v5_task(
            phase1_result, mock_brain, mock_archivist
        )
        
        assert result['approved'] is False
        assert result['llm_score'] == 45.0
        mock_archivist.log_shadow_radar.assert_called() # Log rejection
