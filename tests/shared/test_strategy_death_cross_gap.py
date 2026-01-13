import pytest
import pandas as pd
from shared import strategy

class TestDeathCrossGap:
    """데드 크로스 이격률(Gap) 테스트"""

    @pytest.fixture
    def base_df(self):
        """기본 DataFrame (20일치 이상)"""
        return pd.DataFrame({
            'CLOSE_PRICE': [100.0] * 30
        })

    def test_death_cross_with_sufficient_gap(self):
        """이격이 충분한(>=0.2%) 데드 크로스 -> True"""
        # 어제: 5일선(100) >= 20일선(100) (동일하거나 5일선 위)
        # 오늘: 5일선이 20일선 아래로 내려가고, 격차가 0.3% 발생
        
        # 시나리오 구성:
        # 20일 이동평균을 100으로 고정한다고 가정 (대략적으로)
        # 어제까지는 100 유지
        # 오늘 가격이 급락하여 5일 평균이 떨어짐
        
        prices = [100.0] * 19 + [100.0] # 어제까지 20일간 100
        # 이평선 계산을 위해 단순화:
        # strategy.check_death_cross는 pandas rolling을 사용함.
        
        # 어제(index -2) 시점:
        # Short MA(5) = 100
        # Long MA(20) = 100
        # => Cross Condition 1: 100 >= 100 (True)
        
        # 오늘(index -1) 시점:
        # Long MA가 대략 100 유지되도록 하고
        # Short MA가 0.2% 이상 하락하도록 (gap >= 0.002)
        # target gap = 0.002
        # (100 - short_ma) / 100 >= 0.002
        # 100 - short_ma >= 0.2
        # short_ma <= 99.8
        
        # 오늘 가격을 낮춰서 short_ma를 99.7로 만듦
        # 4일간 100, 오늘 X
        # (400 + X) / 5 = 99.7
        # 400 + X = 498.5
        # X = 98.5
        
        prices = [100.0] * 25
        # index 23 (어제): 100
        # index 24 (오늘): 98.5 로 설정하면 5일평균 뚝 떨어짐
        prices[-1] = 98.5 
        
        df = pd.DataFrame({'CLOSE_PRICE': prices})
        
        # gap_threshold = 0.002 (0.2%)
        result = strategy.check_death_cross(df, gap_threshold=0.002)
        
        assert result is True

    def test_death_cross_with_insufficient_gap(self):
        """이격이 불충분한(<0.2%) 데드 크로스 -> False"""
        # target gap = 0.001 (0.1%)
        # (100 - short_ma) / 100 = 0.001
        # 100 - short_ma = 0.1
        # short_ma = 99.9
        
        # (400 + X) / 5 = 99.9
        # 400 + X = 499.5
        # X = 99.5
        
        prices = [100.0] * 25
        prices[-1] = 99.5
        
        df = pd.DataFrame({'CLOSE_PRICE': prices})
        
        # gap_threshold = 0.002
        result = strategy.check_death_cross(df, gap_threshold=0.002)
        
        assert result is False

    def test_no_cross(self):
        """크로스 자체가 없는 경우 -> False"""
        prices = [100.0] * 25
        df = pd.DataFrame({'CLOSE_PRICE': prices})
        result = strategy.check_death_cross(df)
        assert result is False
