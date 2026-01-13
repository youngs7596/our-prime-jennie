# shared/correlation.py
# 포트폴리오 상관관계 분석 모듈
# LLM 호출 없이 순수 데이터 분석으로 분산 효과를 검증합니다.

import logging
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def calculate_correlation(
    prices_a: List[float],
    prices_b: List[float],
    min_periods: int = 20
) -> Optional[float]:
    """
    두 종목의 가격 시계열 간 상관관계를 계산합니다.
    
    Args:
        prices_a: 종목 A의 가격 리스트 (과거→최신 순)
        prices_b: 종목 B의 가격 리스트 (과거→최신 순)
        min_periods: 최소 데이터 수
    
    Returns:
        상관계수 (-1.0 ~ 1.0) 또는 None (데이터 부족 시)
    """
    if len(prices_a) < min_periods or len(prices_b) < min_periods:
        return None
    
    # 길이 맞추기 (더 짧은 쪽 기준)
    min_len = min(len(prices_a), len(prices_b))
    prices_a = prices_a[-min_len:]
    prices_b = prices_b[-min_len:]
    
    try:
        # 수익률 계산 (로그 수익률)
        returns_a = np.diff(np.log(prices_a))
        returns_b = np.diff(np.log(prices_b))
        
        # 상관계수 계산
        correlation = np.corrcoef(returns_a, returns_b)[0, 1]
        
        if np.isnan(correlation):
            return None
        
        return round(correlation, 4)
    except Exception as e:
        logger.warning(f"상관관계 계산 실패: {e}")
        return None


def check_portfolio_correlation(
    new_stock_code: str,
    new_stock_prices: List[float],
    portfolio: List[Dict],
    price_lookup_fn,
    threshold: float = 0.7,
    min_periods: int = 30
) -> Tuple[bool, Optional[str], float]:
    """
    새 종목이 기존 포트폴리오와 높은 상관관계를 가지는지 체크합니다.
    
    Args:
        new_stock_code: 매수 예정 종목 코드
        new_stock_prices: 매수 예정 종목의 가격 시계열
        portfolio: 현재 포트폴리오 리스트 [{'code': ..., 'name': ..., ...}, ...]
        price_lookup_fn: 종목 코드로 가격 시계열을 가져오는 함수
        threshold: 상관관계 경고 임계값 (기본 0.7)
        min_periods: 최소 데이터 수
    
    Returns:
        (통과 여부, 경고 메시지 또는 None, 최대 상관관계 값)
    """
    if not portfolio:
        return True, None, 0.0
    
    max_correlation = 0.0
    high_corr_stock = None
    
    for holding in portfolio:
        holding_code = holding.get('code', holding.get('stock_code'))
        holding_name = holding.get('name', holding.get('stock_name', holding_code))
        
        if not holding_code or holding_code == new_stock_code:
            continue
        
        try:
            # 기존 보유 종목의 가격 조회
            holding_prices = price_lookup_fn(holding_code)
            if not holding_prices or len(holding_prices) < min_periods:
                continue
            
            correlation = calculate_correlation(
                new_stock_prices, 
                holding_prices, 
                min_periods
            )
            
            if correlation is not None:
                abs_corr = abs(correlation)
                if abs_corr > max_correlation:
                    max_correlation = abs_corr
                    high_corr_stock = (holding_code, holding_name, correlation)
        
        except Exception as e:
            logger.warning(f"[{holding_code}] 상관관계 체크 실패: {e}")
            continue
    
    # 임계값 초과 시 경고
    if max_correlation >= threshold and high_corr_stock:
        code, name, corr = high_corr_stock
        warning = f"⚠️ 높은 상관관계: {name}({code})과 {corr:.2f} (임계값: {threshold})"
        return False, warning, max_correlation
    
    return True, None, max_correlation


def get_correlation_risk_adjustment(
    max_correlation: float,
    base_position_pct: float
) -> float:
    """
    상관관계에 따른 포지션 비중 조정을 계산합니다.
    
    상관관계가 높을수록 포지션 비중을 줄입니다.
    
    Args:
        max_correlation: 포트폴리오와의 최대 상관관계 (0~1)
        base_position_pct: 기본 포지션 비중 (%)
    
    Returns:
        조정된 포지션 비중 (%)
    """
    if max_correlation < 0.3:
        # 낮은 상관관계: 조정 없음
        return base_position_pct
    elif max_correlation < 0.5:
        # 중간 상관관계: 10% 축소
        return base_position_pct * 0.9
    elif max_correlation < 0.7:
        # 높은 상관관계: 25% 축소
        return base_position_pct * 0.75
    else:
        # 매우 높은 상관관계: 50% 축소
        return base_position_pct * 0.5

