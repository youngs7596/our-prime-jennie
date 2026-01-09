# tests/shared/test_portfolio_diversification.py
# 포트폴리오 분산 검증 모듈 유닛 테스트
# 작업 LLM: Claude Opus 4

"""
DiversificationChecker 클래스의 핵심 기능을 테스트합니다.

테스트 범위:
- check_diversification: 분산 투자 원칙 검증
- 섹터 비중 초과 케이스
- 단일 종목 비중 초과 케이스
- 정상 통과 케이스
- 엣지 케이스 (빈 포트폴리오, 0 자산 등)
"""

import pytest
from unittest.mock import MagicMock
import sys
import os

# 프로젝트 루트 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from shared.portfolio_diversification import DiversificationChecker


class MockConfig:
    """테스트용 ConfigManager Mock"""
    def __init__(self, overrides: dict = None):
        self._values = {
            'MAX_SECTOR_PCT': 30.0,
            'MAX_POSITION_VALUE_PCT': 10.0,
        }
        if overrides:
            self._values.update(overrides)
    
    def get_float(self, key, default=0.0):
        return float(self._values.get(key, default))


class MockSectorClassifier:
    """테스트용 SectorClassifier Mock"""
    def __init__(self, sector_map: dict = None):
        self._sector_map = sector_map or {}
    
    def get_sector(self, code: str, name: str) -> str:
        return self._sector_map.get(code, "UNKNOWN")


@pytest.fixture
def mock_config():
    return MockConfig()


@pytest.fixture
def mock_sector_classifier():
    return MockSectorClassifier({
        '005930': 'IT',           # 삼성전자
        '000660': 'IT',           # SK하이닉스
        '035720': 'Communication', # 카카오
        '005380': 'Industrials',  # 현대차
        '051910': 'Materials',    # LG화학
        '068270': 'Healthcare',   # 셀트리온
    })


@pytest.fixture
def diversification_checker(mock_config, mock_sector_classifier):
    return DiversificationChecker(mock_config, mock_sector_classifier)


class TestBasicDiversification:
    """기본 분산 검증 테스트"""
    
    def test_empty_portfolio_passes(self, diversification_checker):
        """빈 포트폴리오에서 매수 시 통과"""
        candidate = {
            'code': '005930',
            'name': '삼성전자',
            'price': 70000,
            'quantity': 10
        }
        
        result = diversification_checker.check_diversification(
            candidate_stock=candidate,
            portfolio_cache={},
            account_balance=10_000_000
        )
        
        assert result['approved'] == True
        assert 'concentration_risk' in result
        assert result['concentration_risk'] == 'LOW'
    
    def test_small_position_passes(self, diversification_checker):
        """작은 포지션은 통과"""
        candidate = {
            'code': '005930',
            'name': '삼성전자',
            'price': 70000,
            'quantity': 1  # 70,000원 = 0.7% of 10M
        }
        
        result = diversification_checker.check_diversification(
            candidate_stock=candidate,
            portfolio_cache={},
            account_balance=10_000_000
        )
        
        assert result['approved'] == True
    
    def test_zero_total_assets_passes(self, diversification_checker):
        """총 자산이 0일 때 통과 처리"""
        candidate = {
            'code': '005930',
            'name': '삼성전자',
            'price': 70000,
            'quantity': 10
        }
        
        result = diversification_checker.check_diversification(
            candidate_stock=candidate,
            portfolio_cache={},
            account_balance=0
        )
        
        assert result['approved'] == True
        assert '총 자산이 0' in result['reason']
        assert result['concentration_risk'] == 'UNKNOWN'


class TestSectorConcentration:
    """섹터 집중도 검증 테스트"""
    
    def test_sector_limit_exceeded(self, mock_config, mock_sector_classifier):
        """섹터 비중 초과 시 거부"""
        checker = DiversificationChecker(mock_config, mock_sector_classifier)
        
        # 기존 포트폴리오: IT 섹터에 25% 보유
        portfolio = {
            '005930': {
                'code': '005930',
                'name': '삼성전자',
                'quantity': 35,  # 35 * 70000 = 2,450,000 (24.5%)
                'avg_price': 70000,
                'current_price': 70000
            }
        }
        
        # 추가 매수 시도: IT 섹터에 10% 추가 (총 34.5% > 30%)
        candidate = {
            'code': '000660',
            'name': 'SK하이닉스',
            'price': 180000,
            'quantity': 6  # 6 * 180000 = 1,080,000 (10.8%)
        }
        
        result = checker.check_diversification(
            candidate_stock=candidate,
            portfolio_cache=portfolio,
            account_balance=7_550_000  # 총 자산 10M
        )
        
        assert result['approved'] == False
        assert '섹터' in result['reason']
        assert '비중 초과' in result['reason']
        assert result['concentration_risk'] == 'HIGH'
    
    def test_sector_limit_at_boundary(self, mock_config, mock_sector_classifier):
        """섹터 비중이 정확히 한도일 때 통과"""
        checker = DiversificationChecker(mock_config, mock_sector_classifier)
        
        # 기존 포트폴리오: IT 섹터에 20% 보유
        portfolio = {
            '005930': {
                'code': '005930',
                'name': '삼성전자',
                'quantity': 28,  # 28 * 70000 = 1,960,000 (19.6%)
                'avg_price': 70000,
                'current_price': 70000
            }
        }
        
        # 추가 매수: IT 섹터에 10% 추가 (총 ~30%)
        candidate = {
            'code': '000660',
            'name': 'SK하이닉스',
            'price': 180000,
            'quantity': 5  # 5 * 180000 = 900,000 (9%)
        }
        
        result = checker.check_diversification(
            candidate_stock=candidate,
            portfolio_cache=portfolio,
            account_balance=8_040_000  # 총 자산 10M
        )
        
        # 29.6% < 30% 이므로 통과
        assert result['approved'] == True
    
    def test_different_sector_passes(self, mock_config, mock_sector_classifier):
        """다른 섹터 종목은 IT 비중과 무관하게 통과"""
        checker = DiversificationChecker(mock_config, mock_sector_classifier)
        
        # 기존 포트폴리오: IT 섹터에 25% 보유
        portfolio = {
            '005930': {
                'code': '005930',
                'name': '삼성전자',
                'quantity': 35,
                'avg_price': 70000,
                'current_price': 70000
            }
        }
        
        # 다른 섹터(Industrials) 매수
        candidate = {
            'code': '005380',
            'name': '현대차',
            'price': 200000,
            'quantity': 3  # 600,000원 (6%)
        }
        
        result = checker.check_diversification(
            candidate_stock=candidate,
            portfolio_cache=portfolio,
            account_balance=6_950_000  # 총 자산 ~10M
        )
        
        assert result['approved'] == True


class TestStockConcentration:
    """단일 종목 집중도 검증 테스트"""
    
    def test_stock_limit_exceeded(self, mock_config, mock_sector_classifier):
        """단일 종목 비중 초과 시 거부"""
        checker = DiversificationChecker(mock_config, mock_sector_classifier)
        
        # 빈 포트폴리오에서 11% 매수 시도
        candidate = {
            'code': '005930',
            'name': '삼성전자',
            'price': 70000,
            'quantity': 16  # 16 * 70000 = 1,120,000 (11.2% of 10M)
        }
        
        result = checker.check_diversification(
            candidate_stock=candidate,
            portfolio_cache={},
            account_balance=10_000_000
        )
        
        assert result['approved'] == False
        assert '단일 종목' in result['reason']
        assert '비중 초과' in result['reason']
        assert result['concentration_risk'] == 'HIGH'
    
    def test_stock_limit_at_boundary(self, mock_config, mock_sector_classifier):
        """단일 종목 비중이 정확히 10%일 때 통과"""
        checker = DiversificationChecker(mock_config, mock_sector_classifier)
        
        # 정확히 10% 매수
        candidate = {
            'code': '005930',
            'name': '삼성전자',
            'price': 100000,
            'quantity': 10  # 10 * 100000 = 1,000,000 (10% of 10M)
        }
        
        result = checker.check_diversification(
            candidate_stock=candidate,
            portfolio_cache={},
            account_balance=10_000_000
        )
        
        # 정확히 10%는 통과 (> 조건이므로)
        assert result['approved'] == True


class TestOverrideParameters:
    """Override 파라미터 테스트"""
    
    def test_override_max_sector_pct(self, mock_config, mock_sector_classifier):
        """섹터 비중 한도 override"""
        checker = DiversificationChecker(mock_config, mock_sector_classifier)
        
        # 기존 포트폴리오: IT 40%
        portfolio = {
            '005930': {
                'code': '005930',
                'name': '삼성전자',
                'quantity': 40,
                'avg_price': 100000,
                'current_price': 100000
            }
        }
        
        # IT 추가 매수 (기본 30% 한도면 실패, 50% 한도면 성공)
        candidate = {
            'code': '000660',
            'name': 'SK하이닉스',
            'price': 100000,
            'quantity': 5  # 5%
        }
        
        # 기본 한도(30%)로는 실패
        result_default = checker.check_diversification(
            candidate_stock=candidate,
            portfolio_cache=portfolio,
            account_balance=5_500_000  # 총 10M
        )
        assert result_default['approved'] == False
        
        # 50% 한도 override로는 성공
        result_override = checker.check_diversification(
            candidate_stock=candidate,
            portfolio_cache=portfolio,
            account_balance=5_500_000,
            override_max_sector_pct=50.0
        )
        assert result_override['approved'] == True
    
    def test_override_max_stock_pct(self, mock_config, mock_sector_classifier):
        """종목 비중 한도 override"""
        checker = DiversificationChecker(mock_config, mock_sector_classifier)
        
        # 15% 매수 시도
        candidate = {
            'code': '005930',
            'name': '삼성전자',
            'price': 100000,
            'quantity': 15  # 15%
        }
        
        # 기본 한도(10%)로는 실패
        result_default = checker.check_diversification(
            candidate_stock=candidate,
            portfolio_cache={},
            account_balance=10_000_000
        )
        assert result_default['approved'] == False
        
        # 20% 한도 override로는 성공
        result_override = checker.check_diversification(
            candidate_stock=candidate,
            portfolio_cache={},
            account_balance=10_000_000,
            override_max_stock_pct=20.0
        )
        assert result_override['approved'] == True


class TestSectorExposureCalculation:
    """섹터 비중 계산 테스트"""
    
    def test_sector_exposure_returned(self, diversification_checker):
        """섹터 비중 정보가 결과에 포함"""
        candidate = {
            'code': '005930',
            'name': '삼성전자',
            'price': 70000,
            'quantity': 5
        }
        
        result = diversification_checker.check_diversification(
            candidate_stock=candidate,
            portfolio_cache={},
            account_balance=10_000_000
        )
        
        assert 'sector_exposure' in result
        assert isinstance(result['sector_exposure'], dict)
    
    def test_multiple_sectors_calculated(self, mock_config, mock_sector_classifier):
        """여러 섹터 비중 정확히 계산"""
        checker = DiversificationChecker(mock_config, mock_sector_classifier)
        
        # 다양한 섹터 포트폴리오
        portfolio = {
            '005930': {  # IT
                'code': '005930',
                'name': '삼성전자',
                'quantity': 10,
                'avg_price': 100000,
                'current_price': 100000
            },
            '005380': {  # Industrials
                'code': '005380',
                'name': '현대차',
                'quantity': 5,
                'avg_price': 200000,
                'current_price': 200000
            }
        }
        
        # Communication 섹터 추가
        candidate = {
            'code': '035720',
            'name': '카카오',
            'price': 50000,
            'quantity': 10  # 500,000원
        }
        
        result = checker.check_diversification(
            candidate_stock=candidate,
            portfolio_cache=portfolio,
            account_balance=7_500_000  # 총 10M
        )
        
        sector_exposure = result['sector_exposure']
        
        # IT: 1M / 10M ≈ 10%
        assert 'IT' in sector_exposure
        assert abs(sector_exposure['IT'] - 10.0) < 1.0  # 10% ± 1%
        
        # Industrials: 1M / 10M ≈ 10%
        assert 'Industrials' in sector_exposure
        assert abs(sector_exposure['Industrials'] - 10.0) < 1.0
        
        # Communication: 500K / 10M ≈ 5%
        assert 'Communication' in sector_exposure
        assert abs(sector_exposure['Communication'] - 5.0) < 1.0


class TestCurrentSectorExposure:
    """매수 전 섹터 비중 계산 테스트"""
    
    def test_current_sector_exposure_calculated(self, mock_config, mock_sector_classifier):
        """현재(매수 전) 섹터 비중이 결과에 포함"""
        checker = DiversificationChecker(mock_config, mock_sector_classifier)
        
        # 기존 IT 20%
        portfolio = {
            '005930': {
                'code': '005930',
                'name': '삼성전자',
                'quantity': 20,
                'avg_price': 100000,
                'current_price': 100000
            }
        }
        
        # IT 추가 5%
        candidate = {
            'code': '000660',
            'name': 'SK하이닉스',
            'price': 100000,
            'quantity': 5
        }
        
        result = checker.check_diversification(
            candidate_stock=candidate,
            portfolio_cache=portfolio,
            account_balance=7_500_000  # 총 10M
        )
        
        # 매수 전 IT 비중 ≈ 20%
        assert 'current_sector_exposure' in result
        assert abs(result['current_sector_exposure'] - 20.0) < 2.0  # 20% ± 2%


class TestExceptionHandling:
    """예외 처리 테스트"""
    
    def test_exception_returns_approved(self, mock_config):
        """예외 발생 시 보수적으로 통과 처리"""
        # get_sector에서 예외 발생하는 Mock
        bad_classifier = MagicMock()
        bad_classifier.get_sector.side_effect = Exception("Sector lookup failed")
        
        checker = DiversificationChecker(mock_config, bad_classifier)
        
        candidate = {
            'code': '005930',
            'name': '삼성전자',
            'price': 70000,
            'quantity': 10
        }
        
        result = checker.check_diversification(
            candidate_stock=candidate,
            portfolio_cache={},
            account_balance=10_000_000
        )
        
        # 오류 시 통과 처리 (보수적)
        assert result['approved'] == True
        assert '검증 오류' in result['reason']
        assert result['concentration_risk'] == 'UNKNOWN'


class TestEdgeCases:
    """엣지 케이스 테스트"""
    
    def test_very_small_position(self, diversification_checker):
        """매우 작은 포지션 (0.01%)"""
        candidate = {
            'code': '005930',
            'name': '삼성전자',
            'price': 1000,
            'quantity': 1  # 1000원 = 0.01% of 10M
        }
        
        result = diversification_checker.check_diversification(
            candidate_stock=candidate,
            portfolio_cache={},
            account_balance=10_000_000
        )
        
        assert result['approved'] == True
    
    def test_large_existing_portfolio(self, mock_config, mock_sector_classifier):
        """큰 기존 포트폴리오"""
        checker = DiversificationChecker(mock_config, mock_sector_classifier)
        
        # 5개 종목 보유
        portfolio = {
            '005930': {
                'code': '005930',
                'name': '삼성전자',
                'quantity': 10,
                'avg_price': 100000,
                'current_price': 100000
            },
            '000660': {
                'code': '000660',
                'name': 'SK하이닉스',
                'quantity': 5,
                'avg_price': 200000,
                'current_price': 200000
            },
            '035720': {
                'code': '035720',
                'name': '카카오',
                'quantity': 20,
                'avg_price': 50000,
                'current_price': 50000
            },
            '005380': {
                'code': '005380',
                'name': '현대차',
                'quantity': 5,
                'avg_price': 200000,
                'current_price': 200000
            },
            '051910': {
                'code': '051910',
                'name': 'LG화학',
                'quantity': 2,
                'avg_price': 500000,
                'current_price': 500000
            }
        }
        # 포트폴리오 가치: 1M + 1M + 1M + 1M + 1M = 5M
        
        # 새 종목 (Healthcare) 추가
        candidate = {
            'code': '068270',
            'name': '셀트리온',
            'price': 150000,
            'quantity': 3  # 450,000원 (4.5%)
        }
        
        result = checker.check_diversification(
            candidate_stock=candidate,
            portfolio_cache=portfolio,
            account_balance=4_550_000  # 총 10M
        )
        
        assert result['approved'] == True
        assert len(result['sector_exposure']) >= 5  # 5개 이상 섹터
    
    def test_current_price_fallback_to_avg_price(self, mock_config, mock_sector_classifier):
        """current_price 없을 때 avg_price 사용"""
        checker = DiversificationChecker(mock_config, mock_sector_classifier)
        
        # current_price 없는 포트폴리오
        portfolio = {
            '005930': {
                'code': '005930',
                'name': '삼성전자',
                'quantity': 10,
                'avg_price': 100000
                # current_price 없음
            }
        }
        
        candidate = {
            'code': '035720',
            'name': '카카오',
            'price': 50000,
            'quantity': 5
        }
        
        result = checker.check_diversification(
            candidate_stock=candidate,
            portfolio_cache=portfolio,
            account_balance=8_750_000  # 총 10M
        )
        
        # avg_price로 계산되어 정상 동작
        assert result['approved'] == True


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

