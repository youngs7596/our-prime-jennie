"""
통합 매도 로직 모듈
- monitor.py의 실제 매도 조건을 백테스트에서도 동일하게 사용
- 순수 함수로 추출하여 재사용성 확보
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Tuple
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class SellCheckResult:
    """매도 조건 체크 결과"""
    should_sell: bool = False
    reason: str = ""
    quantity_pct: float = 100.0  # 매도 비율 (100=전량, 50=반, 25=1/4)

    # 디버그/분석용 정보
    profit_pct: float = 0.0
    high_profit_pct: float = 0.0
    stop_loss_price: float = 0.0
    trailing_stop_price: float = 0.0
    profit_floor_price: float = 0.0
    rsi: Optional[float] = None
    atr: Optional[float] = None
    warnings: List[str] = field(default_factory=list)


@dataclass
class PositionState:
    """포지션 상태 (Redis 캐시 대체)"""
    high_price: float = 0.0
    scale_out_level: int = 0
    rsi_overbought_sold: bool = False
    profit_floor: Optional[float] = None  # 퍼센트 (예: 10.0)

    def update_high_price(self, current_price: float) -> float:
        if current_price > self.high_price:
            self.high_price = current_price
        return self.high_price


@dataclass
class SellConfig:
    """매도 설정 (ConfigManager 대체)"""
    # ATR Stop
    atr_multiplier: float = 2.0

    # Fixed Stop
    fixed_stop_loss_pct: float = -6.0

    # Trailing Take Profit
    trailing_enabled: bool = True
    trailing_activation_pct: float = 5.0
    trailing_min_profit_pct: float = 3.0
    trailing_drop_from_high_pct: float = 3.5

    # Scale-out
    scale_out_enabled: bool = True

    # RSI
    rsi_overbought_threshold: float = 75.0
    rsi_min_profit_pct: float = 3.0

    # Target Profit (Trailing 비활성화 시)
    target_profit_pct: float = 10.0

    # Max Holding
    max_holding_days: int = 30

    # Profit Floor
    profit_floor_activation: float = 15.0
    profit_floor_level: float = 10.0

    # Profit Lock (ATR 기반 동적)
    profit_lock_l1_mult: float = 1.5  # ATR * 1.5
    profit_lock_l1_min: float = 1.5   # 최소 1.5%
    profit_lock_l1_max: float = 3.0   # 최대 3%
    profit_lock_l1_floor: float = 0.2 # 보장 수익

    profit_lock_l2_mult: float = 2.5
    profit_lock_l2_min: float = 3.0
    profit_lock_l2_max: float = 5.0
    profit_lock_l2_floor: float = 1.0

    # Scale-out 레벨 (시장 국면별)
    scale_out_levels_bull: List[Tuple[float, float]] = field(default_factory=lambda: [(3.0, 25.0), (7.0, 25.0), (15.0, 25.0), (25.0, 15.0)])
    scale_out_levels_bear: List[Tuple[float, float]] = field(default_factory=lambda: [(2.0, 25.0), (5.0, 25.0), (8.0, 25.0), (12.0, 15.0)])
    scale_out_levels_sideways: List[Tuple[float, float]] = field(default_factory=lambda: [(3.0, 25.0), (7.0, 25.0), (12.0, 25.0), (18.0, 15.0)])

    # 최소 거래 가드
    min_transaction_amount: float = 500_000
    min_sell_quantity: int = 50


def calculate_indicators(daily_prices: pd.DataFrame, current_price: float) -> Dict[str, Any]:
    """기술적 지표 계산"""
    import shared.strategy as strategy

    result = {
        'atr': None,
        'rsi': None,
        'macd_bearish': False,
        'death_cross': False,
    }

    if daily_prices.empty or len(daily_prices) < 15:
        return result

    # ATR
    result['atr'] = strategy.calculate_atr(daily_prices, period=14)

    # RSI
    prices = daily_prices['CLOSE_PRICE'].tolist() + [current_price]
    result['rsi'] = strategy.calculate_rsi(prices[::-1], period=14)

    # MACD Divergence
    if len(daily_prices) >= 36:
        try:
            macd_div = strategy.check_macd_divergence(daily_prices)
            if macd_div and macd_div.get('bearish_divergence'):
                result['macd_bearish'] = True
        except Exception:
            pass

    # Death Cross
    if len(daily_prices) >= 20:
        try:
            new_row = pd.DataFrame([{
                'PRICE_DATE': daily_prices['PRICE_DATE'].max(),
                'CLOSE_PRICE': current_price,
                'OPEN_PRICE': current_price,
                'HIGH_PRICE': current_price,
                'LOW_PRICE': current_price
            }])
            df = pd.concat([daily_prices, new_row], ignore_index=True)
            result['death_cross'] = strategy.check_death_cross(df)
        except Exception:
            pass

    return result


def check_chart_phase(daily_prices: pd.DataFrame) -> Dict[str, Any]:
    """Chart Phase 분석 (Prime Council)"""
    result = {
        'warning': False,
        'stage': 0,
        'exhaustion': 0.0,
    }

    if daily_prices.empty or len(daily_prices) < 125:
        return result

    try:
        from shared.hybrid_scoring.chart_phase import ChartPhaseAnalyzer
        analyzer = ChartPhaseAnalyzer()
        phase = analyzer.analyze(daily_prices)

        result['stage'] = phase.stage
        result['exhaustion'] = phase.exhaustion_score
        result['warning'] = (phase.stage == 3 or phase.exhaustion_score > 40)
    except ImportError:
        pass
    except Exception:
        pass

    return result


def check_sell_conditions(
    stock_code: str,
    buy_price: float,
    current_price: float,
    quantity: int,
    buy_date: str,  # YYYYMMDD
    daily_prices: pd.DataFrame,
    position_state: PositionState,
    config: SellConfig,
    market_regime: str = "SIDEWAYS",
    current_date: str = None,  # YYYYMMDD
) -> SellCheckResult:
    """
    통합 매도 조건 체크 (monitor.py 로직 동일)

    Returns:
        SellCheckResult: 매도 여부 및 상세 정보
    """
    from datetime import datetime

    result = SellCheckResult()

    # 0. 기본 계산
    profit_pct = ((current_price - buy_price) / buy_price) * 100 if buy_price > 0 else 0
    result.profit_pct = profit_pct

    # High Price 업데이트
    position_state.update_high_price(current_price)
    high_price = position_state.high_price
    high_profit_pct = ((high_price - buy_price) / buy_price) * 100 if buy_price > 0 else 0
    result.high_profit_pct = high_profit_pct

    # 지표 계산
    indicators = calculate_indicators(daily_prices, current_price)
    atr = indicators['atr']
    rsi = indicators['rsi']
    macd_bearish = indicators['macd_bearish']
    death_cross = indicators['death_cross']

    result.atr = atr
    result.rsi = rsi

    if macd_bearish:
        result.warnings.append("MACD_BEARISH")

    # Chart Phase 분석
    chart_phase = check_chart_phase(daily_prices)
    if chart_phase['warning']:
        result.warnings.append(f"CHART_PHASE_S{chart_phase['stage']}")

    # =========================================================================
    # 0. Profit Floor Protection
    # =========================================================================
    if profit_pct >= config.profit_floor_activation:
        if position_state.profit_floor is None:
            position_state.profit_floor = config.profit_floor_level

    if position_state.profit_floor is not None:
        floor_price = buy_price * (1 + position_state.profit_floor / 100.0)
        result.profit_floor_price = floor_price

        if profit_pct < position_state.profit_floor:
            result.should_sell = True
            result.reason = f"PROFIT_FLOOR ({profit_pct:.1f}% < Floor {position_state.profit_floor}%)"
            result.quantity_pct = 100.0
            return result

    # =========================================================================
    # 0.1 Profit Lock (ATR 기반 동적)
    # =========================================================================
    atr_pct = (atr / buy_price) * 100 if (atr and buy_price > 0) else 2.0

    profit_lock_l1_trigger = max(config.profit_lock_l1_min, min(config.profit_lock_l1_max, atr_pct * config.profit_lock_l1_mult))
    profit_lock_l2_trigger = max(config.profit_lock_l2_min, min(config.profit_lock_l2_max, atr_pct * config.profit_lock_l2_mult))

    # L2: 고점이 L2 트리거 이상이었는데, 현재 수익이 1.0% 미만
    if high_profit_pct >= profit_lock_l2_trigger and profit_pct < config.profit_lock_l2_floor:
        result.should_sell = True
        result.reason = f"PROFIT_LOCK_L2 (High {high_profit_pct:.1f}% >= {profit_lock_l2_trigger:.1f}%, Now {profit_pct:.1f}%)"
        result.quantity_pct = 100.0
        return result

    # L1: 고점이 L1 트리거 이상이었는데, 현재 수익이 0.2% 미만
    if high_profit_pct >= profit_lock_l1_trigger and profit_pct < config.profit_lock_l1_floor:
        result.should_sell = True
        result.reason = f"PROFIT_LOCK_L1 (High {high_profit_pct:.1f}% >= {profit_lock_l1_trigger:.1f}%, Now {profit_pct:.1f}%)"
        result.quantity_pct = 100.0
        return result

    # =========================================================================
    # 1. ATR Stop
    # =========================================================================
    if atr:
        mult = config.atr_multiplier

        # MACD/ChartPhase 경고 시 조정
        if macd_bearish:
            mult = mult * 0.75
        if chart_phase['warning']:
            mult = mult * 0.8

        stop_price = buy_price - (mult * atr)
        result.stop_loss_price = stop_price

        if current_price < stop_price:
            result.should_sell = True
            result.reason = f"ATR_STOP ({current_price:,.0f} < {stop_price:,.0f})"
            result.quantity_pct = 100.0
            return result

    # =========================================================================
    # 1.2 Fixed Stop Loss
    # =========================================================================
    stop_loss = config.fixed_stop_loss_pct
    if stop_loss > 0:
        stop_loss = -stop_loss

    if profit_pct <= stop_loss:
        result.should_sell = True
        result.reason = f"FIXED_STOP ({profit_pct:.2f}% <= {stop_loss}%)"
        result.quantity_pct = 100.0

        # Fixed Stop이 ATR Stop보다 높으면 업데이트
        fixed_stop_price = buy_price * (1 + stop_loss / 100.0)
        if result.stop_loss_price == 0 or fixed_stop_price > result.stop_loss_price:
            result.stop_loss_price = fixed_stop_price

        return result

    # =========================================================================
    # 2. Trailing Take Profit
    # =========================================================================
    if config.trailing_enabled:
        activation_pct = config.trailing_activation_pct
        min_profit = config.trailing_min_profit_pct
        drop_pct = config.trailing_drop_from_high_pct

        # MACD/ChartPhase 경고 시 조정
        if macd_bearish:
            activation_pct = activation_pct * 0.8
        if chart_phase['warning']:
            activation_pct = activation_pct * 0.7
            drop_pct = drop_pct * 0.7

        if high_profit_pct >= activation_pct:
            trailing_stop_price = high_price * (1 - drop_pct / 100)
            result.trailing_stop_price = trailing_stop_price

            if current_price <= trailing_stop_price and profit_pct >= min_profit:
                result.should_sell = True
                result.reason = f"TRAILING_TP (High {high_price:,.0f} ->{drop_pct:.1f}% Stop, Profit {profit_pct:.1f}%)"
                result.quantity_pct = 100.0
                return result

    # =========================================================================
    # 3. Scale-out (시장 국면별)
    # =========================================================================
    if config.scale_out_enabled and profit_pct > 0:
        if market_regime == "BULL":
            levels = config.scale_out_levels_bull
        elif market_regime == "BEAR":
            levels = config.scale_out_levels_bear
        else:
            levels = config.scale_out_levels_sideways

        current_level = position_state.scale_out_level

        for level_idx, (target_pct, sell_pct) in enumerate(levels, start=1):
            if current_level < level_idx and profit_pct >= target_pct:
                sell_qty = int(quantity * (sell_pct / 100.0)) or 1
                sell_amount = sell_qty * current_price

                # 최소 거래 가드
                if sell_amount < config.min_transaction_amount or sell_qty < config.min_sell_quantity:
                    if level_idx == 4:  # 마지막 레벨이면 전량 청산
                        position_state.scale_out_level = level_idx
                        result.should_sell = True
                        result.reason = f"SCALE_OUT_L{level_idx}_FORCE (+{profit_pct:.1f}% [{market_regime}])"
                        result.quantity_pct = 100.0
                        return result
                    else:
                        continue  # 스킵
                else:
                    position_state.scale_out_level = level_idx
                    result.should_sell = True
                    result.reason = f"SCALE_OUT_L{level_idx} (+{profit_pct:.1f}% >= +{target_pct}% [{market_regime}])"
                    result.quantity_pct = sell_pct
                    return result

    # =========================================================================
    # 4. RSI Overbought
    # =========================================================================
    if rsi and rsi >= config.rsi_overbought_threshold:
        if profit_pct >= config.rsi_min_profit_pct and not position_state.rsi_overbought_sold:
            position_state.rsi_overbought_sold = True
            result.should_sell = True
            result.reason = f"RSI_OVERBOUGHT (RSI {rsi:.1f}, Profit {profit_pct:.1f}%)"
            result.quantity_pct = 50.0  # 50% 분할 매도
            return result

    # =========================================================================
    # 5. Target Profit (Trailing 비활성화 시)
    # =========================================================================
    if not config.trailing_enabled:
        if profit_pct >= config.target_profit_pct:
            result.should_sell = True
            result.reason = f"TARGET_PROFIT ({profit_pct:.2f}%)"
            result.quantity_pct = 100.0
            return result

    # =========================================================================
    # 6. Death Cross
    # =========================================================================
    if death_cross:
        result.should_sell = True
        result.reason = "DEATH_CROSS"
        result.quantity_pct = 100.0
        return result

    # =========================================================================
    # 7. Max Holding Days
    # =========================================================================
    if buy_date and current_date:
        try:
            buy_dt = datetime.strptime(buy_date, '%Y%m%d')
            curr_dt = datetime.strptime(current_date, '%Y%m%d')
            holding_days = (curr_dt - buy_dt).days

            if holding_days >= config.max_holding_days:
                result.should_sell = True
                result.reason = f"MAX_HOLDING_DAYS ({holding_days}d)"
                result.quantity_pct = 100.0
                return result
        except Exception:
            pass

    return result


# 테스트용
if __name__ == "__main__":
    import sys
    sys.path.insert(0, '/home/youngs75/projects/my-prime-jennie')

    config = SellConfig()
    state = PositionState(high_price=10500)

    result = check_sell_conditions(
        stock_code="005930",
        buy_price=10000,
        current_price=10200,
        quantity=100,
        buy_date="20260101",
        daily_prices=pd.DataFrame(),
        position_state=state,
        config=config,
        market_regime="BULL",
        current_date="20260115",
    )

    print(f"Should Sell: {result.should_sell}")
    print(f"Reason: {result.reason}")
    print(f"Profit: {result.profit_pct:.2f}%")
