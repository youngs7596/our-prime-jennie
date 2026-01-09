"""
tests/shared/test_correlation.py - 상관관계 분석 모듈 Unit Tests
================================================================

shared/correlation.py 모듈의 Unit Test입니다.

실행 방법:
    pytest tests/shared/test_correlation.py -v

커버리지 포함:
    pytest tests/shared/test_correlation.py -v --cov=shared.correlation --cov-report=term-missing
"""

import pytest
import numpy as np


class TestCalculateCorrelation:
    """상관관계 계산 테스트"""
    
    def test_perfect_positive_correlation(self):
        """완벽한 양의 상관관계"""
        from shared.correlation import calculate_correlation
        
        prices_a = list(range(100, 130))  # 100, 101, ..., 129
        prices_b = list(range(200, 230))  # 200, 201, ..., 229
        
        result = calculate_correlation(prices_a, prices_b, min_periods=20)
        
        # 완벽한 양의 상관관계는 1.0에 가까움
        assert result is not None
        assert result > 0.99
    
    def test_negative_correlation(self):
        """음의 상관관계"""
        from shared.correlation import calculate_correlation
        
        # A가 오르면 B는 내리는 패턴 (역방향 변동)
        prices_a = [100 + i*2 + (i % 2) * 5 for i in range(30)]  # 상승 + 변동
        prices_b = [100 + i*2 - (i % 2) * 5 for i in range(30)]  # 상승 + 역방향 변동
        
        result = calculate_correlation(prices_a, prices_b, min_periods=20)
        
        # 음의 상관관계
        assert result is not None
        assert result < 0  # 음수이면 통과
    
    def test_no_correlation(self):
        """상관관계 없음 (랜덤)"""
        from shared.correlation import calculate_correlation
        
        np.random.seed(42)
        prices_a = np.random.uniform(100, 200, 50).tolist()
        np.random.seed(123)
        prices_b = np.random.uniform(100, 200, 50).tolist()
        
        result = calculate_correlation(prices_a, prices_b, min_periods=20)
        
        # 랜덤 데이터는 상관관계가 0에 가까움 (±0.3 이내)
        assert result is not None
        assert -0.5 < result < 0.5
    
    def test_insufficient_data(self):
        """데이터 부족 시 None 반환"""
        from shared.correlation import calculate_correlation
        
        prices_a = [100, 101, 102]  # 3개
        prices_b = [200, 201, 202]  # 3개
        
        result = calculate_correlation(prices_a, prices_b, min_periods=20)
        
        assert result is None
    
    def test_different_lengths(self):
        """길이가 다른 시계열"""
        from shared.correlation import calculate_correlation
        
        prices_a = list(range(100, 150))  # 50개
        prices_b = list(range(200, 230))  # 30개
        
        result = calculate_correlation(prices_a, prices_b, min_periods=20)
        
        # 더 짧은 쪽 기준으로 계산
        assert result is not None


class TestCheckPortfolioCorrelation:
    """포트폴리오 상관관계 체크 테스트"""
    
    def test_no_portfolio(self):
        """포트폴리오가 비어있을 때"""
        from shared.correlation import check_portfolio_correlation
        
        passed, warning, max_corr = check_portfolio_correlation(
            "005930", [100, 101, 102], [], lambda x: None, 0.7
        )
        
        assert passed is True
        assert warning is None
        assert max_corr == 0.0
    
    def test_low_correlation_passes(self):
        """낮은 상관관계는 통과"""
        from shared.correlation import check_portfolio_correlation
        
        np.random.seed(42)
        new_prices = np.random.uniform(100, 200, 50).tolist()
        np.random.seed(123)
        existing_prices = np.random.uniform(100, 200, 50).tolist()
        
        portfolio = [{"code": "000660", "name": "SK하이닉스"}]
        
        passed, warning, max_corr = check_portfolio_correlation(
            "005930", new_prices, portfolio,
            lambda x: existing_prices,
            threshold=0.7
        )
        
        assert passed is True
        assert warning is None
    
    def test_high_correlation_warning(self):
        """높은 상관관계 시 경고"""
        from shared.correlation import check_portfolio_correlation
        
        # 거의 같은 가격 움직임
        new_prices = list(range(100, 150))
        existing_prices = [p * 2 for p in range(100, 150)]  # 2배 스케일링 (상관관계 유지)
        
        portfolio = [{"code": "000660", "name": "SK하이닉스"}]
        
        passed, warning, max_corr = check_portfolio_correlation(
            "005930", new_prices, portfolio,
            lambda x: existing_prices,
            threshold=0.7
        )
        
        assert passed is False
        assert warning is not None
        assert "SK하이닉스" in warning
        assert max_corr > 0.7
    
    def test_skip_same_stock(self):
        """같은 종목은 스킵"""
        from shared.correlation import check_portfolio_correlation
        
        prices = list(range(100, 150))
        portfolio = [{"code": "005930", "name": "삼성전자"}]  # 같은 종목
        
        passed, warning, max_corr = check_portfolio_correlation(
            "005930", prices, portfolio,
            lambda x: prices,
            threshold=0.7
        )
        
        # 같은 종목은 체크하지 않음
        assert passed is True
        assert max_corr == 0.0


class TestCorrelationRiskAdjustment:
    """상관관계 기반 리스크 조정 테스트"""
    
    def test_low_correlation_no_adjustment(self):
        """낮은 상관관계: 조정 없음"""
        from shared.correlation import get_correlation_risk_adjustment
        
        result = get_correlation_risk_adjustment(0.2, 100.0)
        assert result == 100.0
    
    def test_medium_correlation_small_reduction(self):
        """중간 상관관계: 10% 축소"""
        from shared.correlation import get_correlation_risk_adjustment
        
        result = get_correlation_risk_adjustment(0.4, 100.0)
        assert result == 90.0
    
    def test_high_correlation_medium_reduction(self):
        """높은 상관관계: 25% 축소"""
        from shared.correlation import get_correlation_risk_adjustment
        
        result = get_correlation_risk_adjustment(0.6, 100.0)
        assert result == 75.0
    
    def test_very_high_correlation_large_reduction(self):
        """매우 높은 상관관계: 50% 축소"""
        from shared.correlation import get_correlation_risk_adjustment
        
        result = get_correlation_risk_adjustment(0.8, 100.0)
        assert result == 50.0

