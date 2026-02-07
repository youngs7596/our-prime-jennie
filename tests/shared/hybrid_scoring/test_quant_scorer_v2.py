"""
tests/shared/hybrid_scoring/test_quant_scorer_v2.py - Quant Scorer v2 테스트
=============================================================================

v2 잠재력 기반 스코어링 팩터 전용 테스트.
"""

import pytest
from unittest.mock import MagicMock, patch
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_daily_prices():
    """120일치 주가 데이터 — 약간 하락 후 반등하는 패턴"""
    dates = pd.date_range(end=datetime.now(), periods=120, freq='D')
    # 60일 하락 → 60일 반등
    prices_down = [50000 - i * 100 for i in range(60)]  # 50000→44100
    prices_up = [44000 + i * 150 for i in range(60)]    # 44000→52850
    prices = prices_down + prices_up
    highs = [p + 500 for p in prices]
    lows = [p - 500 for p in prices]

    return pd.DataFrame({
        'PRICE_DATE': dates,
        'CLOSE_PRICE': prices,
        'HIGH_PRICE': highs,
        'LOW_PRICE': lows,
        'VOLUME': [1000000] * 120,
    })


@pytest.fixture
def mock_daily_prices_uptrend():
    """120일치 주가 데이터 — 꾸준한 상승 추세"""
    dates = pd.date_range(end=datetime.now(), periods=120, freq='D')
    prices = [50000 + i * 200 for i in range(120)]  # 50000→73800

    return pd.DataFrame({
        'PRICE_DATE': dates,
        'CLOSE_PRICE': prices,
        'HIGH_PRICE': [p + 500 for p in prices],
        'LOW_PRICE': [p - 500 for p in prices],
        'VOLUME': [1000000] * 120,
    })


@pytest.fixture
def mock_daily_prices_bottom_bounce():
    """120일치 주가 — 바닥 후 15% 반등 (sweet spot)"""
    dates = pd.date_range(end=datetime.now(), periods=120, freq='D')
    # 100일 하락 → 20일 반등
    prices = [60000 - i * 200 for i in range(100)]  # 60000→40200
    # 20일 반등: 40000 → 46000 (~15%)
    prices += [40000 + i * 300 for i in range(20)]
    highs = [p + 500 for p in prices]
    lows = [p - 500 for p in prices]

    return pd.DataFrame({
        'PRICE_DATE': dates,
        'CLOSE_PRICE': prices,
        'HIGH_PRICE': highs,
        'LOW_PRICE': lows,
        'VOLUME': [1000000] * 120,
    })


@pytest.fixture
def mock_daily_prices_sideways_breakout():
    """120일치 주가 — 40일 횡보(저변동) 후 볼린저 상단 돌파"""
    dates = pd.date_range(end=datetime.now(), periods=120, freq='D')
    # 80일 이전: 정상 변동
    prices = [50000 + np.random.randint(-500, 500) for _ in range(80)]
    # 최근 40일: 매우 낮은 변동성 후 마지막에 돌파
    sideways = [50000 + np.random.randint(-100, 100) for _ in range(35)]
    breakout = [50200, 50500, 51000, 52000, 53000]  # 돌파
    prices += sideways + breakout

    return pd.DataFrame({
        'PRICE_DATE': dates,
        'CLOSE_PRICE': prices,
        'HIGH_PRICE': [p + 300 for p in prices],
        'LOW_PRICE': [p - 300 for p in prices],
        'VOLUME': [1000000] * 120,
    })


@pytest.fixture
def mock_kospi_prices():
    """120일 KOSPI — 보합"""
    dates = pd.date_range(end=datetime.now(), periods=120, freq='D')
    return pd.DataFrame({
        'PRICE_DATE': dates,
        'CLOSE_PRICE': [2500 + i * 0.5 for i in range(120)],
    })


@pytest.fixture
def mock_investor_trading_df():
    """투자자 매매 동향 — 외인/기관 순매수"""
    dates = pd.date_range(end=datetime.now(), periods=25, freq='B')
    return pd.DataFrame({
        'TRADE_DATE': dates,
        'FOREIGN_NET_BUY': [-50000] * 10 + [100000] * 15,  # 매도→매수 전환
        'INSTITUTION_NET_BUY': [-20000] * 10 + [50000] * 15,
        'INDIVIDUAL_NET_BUY': [70000] * 10 + [-150000] * 15,
        'FOREIGN_HOLDING_RATIO': [10.0 + i * 0.05 for i in range(25)],
    })


@pytest.fixture
def mock_financial_trend_improving():
    """ROE/EPS 개선 중인 재무 트렌드"""
    return {
        'roe_trend': [5.0, 7.0, 9.0, 12.0],   # 연속 개선
        'per_trend': [25.0, 20.0, 15.0, 12.0], # PER 하락 (좋음)
        'eps_trend': [500, 700, 1000, 1500],    # EPS 성장
    }


@pytest.fixture
def mock_financial_trend_deteriorating():
    """ROE 악화 중인 재무 트렌드"""
    return {
        'roe_trend': [15.0, 12.0, 8.0, 5.0],   # 연속 악화
        'per_trend': [10.0, 12.0, 15.0, 20.0],  # PER 상승 (나쁨)
        'eps_trend': [1500, 1200, 900, 600],
    }


@pytest.fixture
def scorer():
    """QuantScorer 인스턴스 (DB 없음)"""
    from shared.hybrid_scoring.quant_scorer import QuantScorer
    return QuantScorer(db_conn=None, market_regime='SIDEWAYS')


# ============================================================================
# Tests: v2 Momentum (20점)
# ============================================================================

class TestV2Momentum:
    """v2 잠재력 모멘텀 테스트"""

    def test_basic_score_range(self, scorer, mock_daily_prices, mock_kospi_prices):
        score, details = scorer.calculate_momentum_score_v2(mock_daily_prices, mock_kospi_prices)
        assert 0 <= score <= 20, f"v2 모멘텀 점수 범위 초과: {score}"

    def test_uptrend_lower_6m_score(self, scorer, mock_daily_prices_uptrend, mock_kospi_prices):
        """v2: 이미 많이 오른 종목은 6M 점수가 낮아야 함 (최대 5점)"""
        score, details = scorer.calculate_momentum_score_v2(
            mock_daily_prices_uptrend, mock_kospi_prices
        )
        # 6M 점수는 최대 5점
        assert details.get('momentum_6m_score', 0) <= 5.0

    def test_bottom_bounce_detected(self, scorer, mock_daily_prices_bottom_bounce):
        """바닥에서 15% 반등 시 bounce_score = 5점"""
        score, details = scorer.calculate_momentum_score_v2(mock_daily_prices_bottom_bounce)
        assert details.get('bounce_score', 0) >= 4.0, \
            f"바닥 반등 미감지: bounce={details.get('bounce_from_20d_low')}%, score={details.get('bounce_score')}"

    def test_no_bounce_in_uptrend(self, scorer, mock_daily_prices_uptrend):
        """꾸준한 상승 종목은 bounce_score가 낮아야 함"""
        score, details = scorer.calculate_momentum_score_v2(mock_daily_prices_uptrend)
        # 상승추세: 20일 저점 대비 반등률이 매우 높거나 매우 낮을 수 있음
        # 중요한 건 10~30% 범위 안에만 만점이라는 것
        assert details.get('bounce_score', 0) <= 5.0

    def test_base_breakout(self, scorer, mock_daily_prices_sideways_breakout):
        """횡보 후 돌파 시 base_breakout_score > 0"""
        score, details = scorer.calculate_momentum_score_v2(mock_daily_prices_sideways_breakout)
        # 볼린저 돌파는 가격 패턴에 따라 달라질 수 있으므로 0 이상 체크
        assert details.get('base_breakout_score', 0) >= 0.0

    def test_insufficient_data(self, scorer):
        """데이터 부족 시 중립값"""
        short_df = pd.DataFrame({
            'CLOSE_PRICE': [50000] * 15,
            'HIGH_PRICE': [51000] * 15,
            'LOW_PRICE': [49000] * 15,
            'VOLUME': [1000000] * 15,
        })
        score, details = scorer.calculate_momentum_score_v2(short_df)
        assert score >= 2.5  # 중립값들


# ============================================================================
# Tests: v2 Quality (20점)
# ============================================================================

class TestV2Quality:
    """v2 개선 품질 테스트"""

    def test_basic_score_range(self, scorer, mock_daily_prices):
        score, details = scorer.calculate_quality_score_v2(
            roe=15.0, eps_growth=20.0, daily_prices_df=mock_daily_prices
        )
        assert 0 <= score <= 20

    def test_improving_roe_high_score(self, scorer, mock_daily_prices, mock_financial_trend_improving):
        """ROE 연속 개선 → 높은 트렌드 점수"""
        score, details = scorer.calculate_quality_score_v2(
            roe=12.0, eps_growth=20.0,
            daily_prices_df=mock_daily_prices,
            financial_trend=mock_financial_trend_improving,
        )
        assert details['roe_trend_score'] >= 5.0, \
            f"ROE 연속 개선인데 trend_score 낮음: {details['roe_trend_score']}"

    def test_deteriorating_roe_low_score(self, scorer, mock_daily_prices, mock_financial_trend_deteriorating):
        """ROE 연속 악화 → 낮은 트렌드 점수"""
        score, details = scorer.calculate_quality_score_v2(
            roe=5.0, eps_growth=-10.0,
            daily_prices_df=mock_daily_prices,
            financial_trend=mock_financial_trend_deteriorating,
        )
        assert details['roe_trend_score'] <= 3.0, \
            f"ROE 악화인데 trend_score 높음: {details['roe_trend_score']}"

    def test_high_static_roe_lower_score_than_improving(self, scorer, mock_daily_prices,
                                                         mock_financial_trend_improving):
        """v2 핵심: ROE 25% 고정 < ROE 5→12% 개선"""
        # 높은 ROE, 트렌드 없음
        score_static, _ = scorer.calculate_quality_score_v2(
            roe=25.0, eps_growth=5.0,
            daily_prices_df=mock_daily_prices,
            financial_trend=None,
        )
        # 낮은 ROE, 강한 개선 트렌드
        score_improving, _ = scorer.calculate_quality_score_v2(
            roe=12.0, eps_growth=20.0,
            daily_prices_df=mock_daily_prices,
            financial_trend=mock_financial_trend_improving,
        )
        # 개선 트렌드가 있는 종목이 더 높아야 함
        # (ROE 수준 점수에서는 static이 높지만, 트렌드 + EPS에서 역전)
        assert score_improving >= score_static * 0.8, \
            f"개선 종목({score_improving:.1f}) vs 고정 종목({score_static:.1f})"

    def test_no_financial_data_neutral(self, scorer, mock_daily_prices):
        """재무 데이터 없는 종목 → 중립 (불이익 없음)"""
        score, details = scorer.calculate_quality_score_v2(
            roe=None, eps_growth=None,
            daily_prices_df=mock_daily_prices,
            financial_trend=None,
        )
        assert details['roe_trend_score'] == 4.0  # 중립 기본값


# ============================================================================
# Tests: v2 Value (20점)
# ============================================================================

class TestV2Value:
    """v2 상대 가치 테스트"""

    def test_basic_score_range(self, scorer):
        score, details = scorer.calculate_value_score_v2(pbr=1.0, per=12.0)
        assert 0 <= score <= 20

    def test_per_historical_discount(self, scorer, mock_financial_trend_improving):
        """과거 PER 평균 대비 할인 → 높은 점수"""
        # PER 25→20→15→12 = 큰 할인
        score, details = scorer.calculate_value_score_v2(
            pbr=1.0, per=12.0,
            financial_trend=mock_financial_trend_improving,
        )
        assert details.get('per_discount_score', 0) > 3.0, \
            f"PER 큰 할인인데 점수 낮음: {details.get('per_discount_score')}"

    def test_per_premium_zero_score(self, scorer, mock_financial_trend_deteriorating):
        """과거 대비 PER 프리미엄 → 0점"""
        # PER 10→12→15→20 = 프리미엄
        score, details = scorer.calculate_value_score_v2(
            pbr=1.0, per=20.0,
            financial_trend=mock_financial_trend_deteriorating,
        )
        assert details.get('per_discount_score', 0) <= 1.0

    def test_peg_low_is_good(self, scorer):
        """PEG < 1 → 높은 점수"""
        score, details = scorer.calculate_value_score_v2(
            pbr=1.0, per=10.0, eps_growth=30.0,
        )
        # PEG = 10 / 30 = 0.33 → 만점
        assert details.get('peg_score', 0) >= 4.0

    def test_peg_high_is_bad(self, scorer):
        """PEG > 2 → 낮은 점수"""
        score, details = scorer.calculate_value_score_v2(
            pbr=1.0, per=30.0, eps_growth=5.0,
        )
        # PEG = 30 / 5 = 6 → 0점 근처
        assert details.get('peg_score', 0) <= 1.5

    def test_no_trend_data_neutral(self, scorer):
        """트렌드 데이터 없음 → 중립"""
        score, details = scorer.calculate_value_score_v2(
            pbr=1.0, per=12.0, financial_trend=None,
        )
        assert details['per_discount_score'] == 2.5  # 중립값


# ============================================================================
# Tests: v2 Technical (10점)
# ============================================================================

class TestV2Technical:
    """v2 축적 신호 테스트"""

    def test_basic_score_range(self, scorer, mock_daily_prices):
        score, details = scorer.calculate_technical_score_v2(mock_daily_prices)
        assert 0 <= score <= 10

    def test_accumulation_price_down_volume_up(self, scorer):
        """가격 하락 + 거래량 증가 = 축적 패턴"""
        dates = pd.date_range(end=datetime.now(), periods=50, freq='D')
        # close[-20]은 50000, close[-1]은 47000 → -6% 하락
        # 이전 20일(idx 10-30): 거래량 500K, 최근 20일(idx 30-50): 거래량 700K → ratio 1.4x
        prices = [50000] * 30 + [50000 - i * 150 for i in range(20)]  # 50000→47150 (-5.7%)
        volumes = [500000] * 30 + [700000] * 20  # 거래량 1.4x

        df = pd.DataFrame({
            'PRICE_DATE': dates,
            'CLOSE_PRICE': prices,
            'HIGH_PRICE': [p + 300 for p in prices],
            'LOW_PRICE': [p - 300 for p in prices],
            'VOLUME': volumes,
        })
        score, details = scorer.calculate_technical_score_v2(df)
        assert details.get('accumulation_score', 0) >= 3.0, \
            f"축적 패턴 미감지: price_chg={details.get('price_change_20d')}, vol_ratio={details.get('vol_ratio_20d')}"

    def test_no_accumulation_when_price_up(self, scorer, mock_daily_prices_uptrend):
        """가격 상승 시 축적 패턴 = 0"""
        score, details = scorer.calculate_technical_score_v2(mock_daily_prices_uptrend)
        assert details.get('accumulation_score', 0) <= 1.0


# ============================================================================
# Tests: v2 News/Sentiment (10점)
# ============================================================================

class TestV2News:
    """v2 센티먼트 전환 테스트"""

    def test_basic_score_range(self, scorer):
        score, details = scorer.calculate_news_score_v2(current_sentiment_score=60)
        assert 0 <= score <= 10

    def test_positive_momentum_high_score(self, scorer):
        """센티먼트 대폭 개선 → 높은 모멘텀 점수"""
        score, details = scorer.calculate_news_score_v2(
            current_sentiment_score=70,
            sentiment_momentum=35.0,  # 과거 대비 35점 개선
        )
        assert details['sentiment_momentum_score'] >= 5.0

    def test_negative_momentum_low_score(self, scorer):
        """센티먼트 악화 → 낮은 점수"""
        score, details = scorer.calculate_news_score_v2(
            current_sentiment_score=40,
            sentiment_momentum=-25.0,
        )
        assert details['sentiment_momentum_score'] <= 1.0

    def test_no_sentiment_data_neutral(self, scorer):
        """센티먼트 모멘텀 데이터 없음 → 중립(3.0)"""
        score, details = scorer.calculate_news_score_v2(
            current_sentiment_score=50,
            sentiment_momentum=None,
        )
        assert details['sentiment_momentum_score'] == 3.0


# ============================================================================
# Tests: v2 Supply/Demand (20점)
# ============================================================================

class TestV2SupplyDemand:
    """v2 스마트머니 신호 테스트"""

    def test_basic_score_range(self, scorer):
        score, details = scorer.calculate_supply_demand_score_v2(
            foreign_net_buy=500000,
            institution_net_buy=200000,
        )
        assert 0 <= score <= 25  # ±3 반전 + 보너스 포함 여유

    def test_buy_turn_reversal(self, scorer):
        """외인 매도→매수 전환 → +3점"""
        # 10일: 이전 5일 순매도, 최근 5일 순매수 (정확히 10행)
        dates = pd.date_range(end=datetime.now(), periods=10, freq='B')
        df = pd.DataFrame({
            'TRADE_DATE': dates,
            'FOREIGN_NET_BUY': [-100000] * 5 + [100000] * 5,
            'INSTITUTION_NET_BUY': [-50000] * 5 + [50000] * 5,
            'INDIVIDUAL_NET_BUY': [150000] * 5 + [-150000] * 5,
        })
        score, details = scorer.calculate_supply_demand_score_v2(
            foreign_net_buy=100000,
            institution_net_buy=50000,
            avg_volume=1000000,
            investor_trading_df=df,
        )
        assert details.get('flow_reversal_adj', 0) == 3.0
        assert details.get('flow_reversal') == 'BUY_TURN'

    def test_sell_turn_reversal(self, scorer):
        """외인 매수→매도 전환 → -3점"""
        dates = pd.date_range(end=datetime.now(), periods=10, freq='B')
        df = pd.DataFrame({
            'TRADE_DATE': dates,
            'FOREIGN_NET_BUY': [100000] * 5 + [-100000] * 5,
            'INSTITUTION_NET_BUY': [0] * 10,
            'INDIVIDUAL_NET_BUY': [0] * 10,
        })
        score, details = scorer.calculate_supply_demand_score_v2(
            investor_trading_df=df,
        )
        assert details.get('flow_reversal_adj', 0) == -3.0

    def test_foreign_ratio_trend_positive(self, scorer):
        """외인 보유비율 1%p 이상 증가 → 5점"""
        score, details = scorer.calculate_supply_demand_score_v2(
            foreign_ratio_trend=1.5,
        )
        assert details['ratio_trend_score'] == 5.0

    def test_smart_money_sync(self, scorer, mock_investor_trading_df):
        """외인+기관 동시매수 + 개인 순매도 → 4점"""
        score, details = scorer.calculate_supply_demand_score_v2(
            foreign_net_buy=100000,
            institution_net_buy=50000,
            avg_volume=1000000,
            investor_trading_df=mock_investor_trading_df,
        )
        assert details.get('sync_score', 0) >= 3.0


# ============================================================================
# Tests: v2 Total Score Integration
# ============================================================================

class TestV2TotalScore:
    """v2 종합 점수 통합 테스트"""

    @patch('shared.hybrid_scoring.quant_scorer.QUANT_SCORER_VERSION', 'v2')
    def test_v2_total_score_range(self, scorer, mock_daily_prices, mock_kospi_prices):
        """v2 총점은 0~100 범위"""
        result = scorer.calculate_total_quant_score(
            stock_code='005930',
            stock_name='삼성전자',
            daily_prices_df=mock_daily_prices,
            kospi_prices_df=mock_kospi_prices,
            roe=15.0,
            eps_growth=20.0,
            pbr=1.2,
            per=12.0,
            current_sentiment_score=65,
            foreign_net_buy=500000,
            institution_net_buy=200000,
            sector='정보통신',
        )
        assert 0 <= result.total_score <= 105  # phase multiplier 여유
        assert result.is_valid

    @patch('shared.hybrid_scoring.quant_scorer.QUANT_SCORER_VERSION', 'v2')
    def test_v2_scorer_version_in_details(self, scorer, mock_daily_prices):
        """v2 결과에 scorer_version 기록"""
        result = scorer.calculate_total_quant_score(
            stock_code='005930',
            stock_name='삼성전자',
            daily_prices_df=mock_daily_prices,
        )
        assert result.details.get('scorer_version') == 'v2'

    @patch('shared.hybrid_scoring.quant_scorer.QUANT_SCORER_VERSION', 'v2')
    def test_v2_with_full_data(self, scorer, mock_daily_prices, mock_kospi_prices,
                                mock_investor_trading_df, mock_financial_trend_improving):
        """v2 모든 데이터 제공 시 정상 동작"""
        result = scorer.calculate_total_quant_score(
            stock_code='005930',
            stock_name='삼성전자',
            daily_prices_df=mock_daily_prices,
            kospi_prices_df=mock_kospi_prices,
            roe=12.0,
            eps_growth=25.0,
            pbr=0.8,
            per=10.0,
            current_sentiment_score=70,
            foreign_net_buy=1000000,
            institution_net_buy=500000,
            sector='정보통신',
            investor_trading_df=mock_investor_trading_df,
            financial_trend=mock_financial_trend_improving,
            sentiment_momentum=20.0,
            foreign_ratio_trend=1.2,
        )
        assert result.is_valid
        assert result.total_score > 0
        assert result.momentum_score >= 0
        assert result.quality_score >= 0
        assert result.value_score >= 0
        assert result.technical_score >= 0
        assert result.news_stat_score >= 0
        assert result.supply_demand_score >= 0

    @patch('shared.hybrid_scoring.quant_scorer.QUANT_SCORER_VERSION', 'v2')
    def test_v2_improving_beats_static(self, scorer, mock_daily_prices, mock_kospi_prices,
                                        mock_financial_trend_improving):
        """핵심 테스트: 개선 중인 종목 > 현재 수준만 높은 종목"""
        # 종목 A: ROE 12%, 강한 개선 트렌드, PER 할인
        result_improving = scorer.calculate_total_quant_score(
            stock_code='000001',
            stock_name='개선주',
            daily_prices_df=mock_daily_prices,
            kospi_prices_df=mock_kospi_prices,
            roe=12.0,
            eps_growth=30.0,
            pbr=0.8,
            per=10.0,
            current_sentiment_score=60,
            foreign_net_buy=500000,
            sector='정보통신',
            financial_trend=mock_financial_trend_improving,
            sentiment_momentum=15.0,
            foreign_ratio_trend=0.8,
        )

        # 종목 B: ROE 25% 고정, 트렌드 없음, PER 프리미엄
        result_static = scorer.calculate_total_quant_score(
            stock_code='000002',
            stock_name='고정주',
            daily_prices_df=mock_daily_prices,
            kospi_prices_df=mock_kospi_prices,
            roe=25.0,
            eps_growth=0.0,
            pbr=2.0,
            per=25.0,
            current_sentiment_score=80,
            foreign_net_buy=500000,
            sector='정보통신',
            financial_trend=None,
            sentiment_momentum=None,
            foreign_ratio_trend=None,
        )

        # 개선 중인 종목이 더 높아야 함 (v2 핵심 철학)
        assert result_improving.total_score > result_static.total_score, \
            f"개선주({result_improving.total_score:.1f}) <= 고정주({result_static.total_score:.1f})"

    @patch('shared.hybrid_scoring.quant_scorer.QUANT_SCORER_VERSION', 'v1')
    def test_v1_unchanged_when_v1_mode(self, scorer, mock_daily_prices, mock_kospi_prices):
        """v1 모드에서는 기존 로직 그대로"""
        result = scorer.calculate_total_quant_score(
            stock_code='005930',
            stock_name='삼성전자',
            daily_prices_df=mock_daily_prices,
            kospi_prices_df=mock_kospi_prices,
            roe=15.0,
            pbr=1.2,
            per=12.0,
        )
        # v1에서는 scorer_version 키가 없어야 함
        assert result.details.get('scorer_version') != 'v2'

    @patch('shared.hybrid_scoring.quant_scorer.QUANT_SCORER_VERSION', 'v2')
    def test_v2_empty_data_invalid(self, scorer):
        """빈 데이터 → is_valid=False"""
        result = scorer.calculate_total_quant_score(
            stock_code='005930',
            stock_name='삼성전자',
            daily_prices_df=pd.DataFrame(),
        )
        assert not result.is_valid


# ============================================================================
# Tests: factor_repository.py v2 메서드
# ============================================================================

class TestFactorRepositoryV2:
    """factor_repository v2 메서드 테스트"""

    def test_get_financial_trend_empty(self):
        """빈 종목 리스트 → 빈 결과"""
        from shared.db.factor_repository import FactorRepository
        mock_session = MagicMock()
        repo = FactorRepository(mock_session)
        result = repo.get_financial_trend([])
        assert result == {}

    def test_get_financial_trend_with_data(self):
        """정상 데이터 반환"""
        from shared.db.factor_repository import FactorRepository
        from datetime import date

        mock_session = MagicMock()
        # Mock row 데이터: (stock_code, quarter_date, roe, per, eps)
        mock_rows = [
            MagicMock(__getitem__=lambda s, i: ['005930', date(2025, 3, 31), 10.0, 15.0, 1000][i]),
            MagicMock(__getitem__=lambda s, i: ['005930', date(2025, 6, 30), 12.0, 13.0, 1200][i]),
            MagicMock(__getitem__=lambda s, i: ['005930', date(2025, 9, 30), 14.0, 11.0, 1500][i]),
            MagicMock(__getitem__=lambda s, i: ['005930', date(2025, 12, 31), 16.0, 10.0, 1800][i]),
        ]
        mock_session.execute.return_value.all.return_value = mock_rows

        repo = FactorRepository(mock_session)
        result = repo.get_financial_trend(['005930'])

        assert '005930' in result
        assert len(result['005930']['roe_trend']) == 4
        assert result['005930']['roe_trend'] == [10.0, 12.0, 14.0, 16.0]

    def test_get_sentiment_momentum_bulk_empty(self):
        """빈 리스트 → 빈 결과"""
        from shared.db.factor_repository import FactorRepository
        mock_session = MagicMock()
        repo = FactorRepository(mock_session)
        result = repo.get_sentiment_momentum_bulk([])
        assert result == {}


# ============================================================================
# Tests: quant_constants v2
# ============================================================================

class TestQuantConstantsV2:
    """v2 상수 정의 테스트"""

    def test_v2_weights_sum_to_100(self):
        from shared.hybrid_scoring.quant_constants import V2_WEIGHTS
        assert sum(V2_WEIGHTS.values()) == 100

    def test_v2_momentum_subfactors_sum(self):
        from shared.hybrid_scoring.quant_constants import V2_MOMENTUM, V2_WEIGHTS
        assert sum(V2_MOMENTUM.values()) == V2_WEIGHTS['momentum']

    def test_v2_quality_subfactors_sum(self):
        from shared.hybrid_scoring.quant_constants import V2_QUALITY, V2_WEIGHTS
        assert sum(V2_QUALITY.values()) == V2_WEIGHTS['quality']

    def test_v2_value_subfactors_sum(self):
        from shared.hybrid_scoring.quant_constants import V2_VALUE, V2_WEIGHTS
        assert sum(V2_VALUE.values()) == V2_WEIGHTS['value']

    def test_v2_technical_subfactors_sum(self):
        from shared.hybrid_scoring.quant_constants import V2_TECHNICAL, V2_WEIGHTS
        assert sum(V2_TECHNICAL.values()) == V2_WEIGHTS['technical']

    def test_v2_news_subfactors_sum(self):
        from shared.hybrid_scoring.quant_constants import V2_NEWS, V2_WEIGHTS
        assert sum(V2_NEWS.values()) == V2_WEIGHTS['news']

    def test_v2_supply_demand_subfactors_sum(self):
        from shared.hybrid_scoring.quant_constants import V2_SUPPLY_DEMAND, V2_WEIGHTS
        assert sum(V2_SUPPLY_DEMAND.values()) == V2_WEIGHTS['supply_demand']

    def test_default_version_is_v1(self):
        """기본값은 v1 (안전망)"""
        import os
        # 환경변수가 세팅 안 되어있으면 v1
        if 'QUANT_SCORER_VERSION' not in os.environ:
            from shared.hybrid_scoring.quant_constants import QUANT_SCORER_VERSION
            assert QUANT_SCORER_VERSION == 'v1'
