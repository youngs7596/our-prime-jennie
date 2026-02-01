#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest_minute_grid.py
-----------------------

분봉 백테스트 그리드 서치

다양한 파라미터 조합으로 백테스트를 수행하여 최적의 설정을 찾습니다.

Usage:
    python utilities/backtest_minute_grid.py
    python utilities/backtest_minute_grid.py --parallel 4
    python utilities/backtest_minute_grid.py --quick  # 빠른 테스트 (조합 축소)
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import logging
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Any, Optional
from concurrent.futures import ProcessPoolExecutor, as_completed
import copy

# 프로젝트 루트 추가
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# =============================================================================
# 그리드 파라미터 정의
# =============================================================================

@dataclass
class GridParams:
    """그리드 서치 파라미터"""

    # === 진입 관련 ===
    # RSI 과열 차단 임계값 (이 값 초과 시 진입 금지)
    rsi_max_threshold: float = 75.0

    # 골든크로스 최소 거래량 비율
    golden_cross_min_volume: float = 1.5

    # 모멘텀 진입 임계값 (%)
    momentum_threshold: float = 3.0

    # No-Trade Window 종료 시간 (분, 9시 기준)
    no_trade_end_minutes: int = 15  # 09:15

    # Danger Zone 활성화
    danger_zone_enabled: bool = True

    # === 청산 관련 ===
    # 고정 손절 비율 (%)
    fixed_stop_loss_pct: float = -6.0

    # Trailing TP 활성화 비율 (%)
    trailing_activation_pct: float = 5.0

    # Trailing TP 고점 대비 하락 비율 (%)
    trailing_drop_pct: float = 3.5

    # Scale-out 활성화
    scale_out_enabled: bool = True

    # RSI 과매수 매도 임계값
    rsi_overbought_sell: float = 75.0

    # ATR Stop 배수
    atr_multiplier: float = 2.0

    # === 포트폴리오 관련 ===
    # 최대 동시 포지션 수
    max_positions: int = 5

    # 포지션 크기 (%)
    position_size_pct: float = 20.0

    def to_dict(self) -> dict:
        return asdict(self)

    def get_key(self) -> str:
        """고유 키 생성"""
        return (
            f"rsi{self.rsi_max_threshold}_"
            f"gcvol{self.golden_cross_min_volume}_"
            f"mom{self.momentum_threshold}_"
            f"ntw{self.no_trade_end_minutes}_"
            f"dz{int(self.danger_zone_enabled)}_"
            f"sl{abs(self.fixed_stop_loss_pct)}_"
            f"ttp{self.trailing_activation_pct}_"
            f"drop{self.trailing_drop_pct}_"
            f"so{int(self.scale_out_enabled)}_"
            f"rsisell{self.rsi_overbought_sell}_"
            f"atr{self.atr_multiplier}_"
            f"pos{self.max_positions}_"
            f"size{self.position_size_pct}"
        )


# =============================================================================
# 그리드 서치 설정
# =============================================================================

# 전체 그리드 (많은 조합)
FULL_GRID = {
    # 진입 관련
    'rsi_max_threshold': [70, 75, 80],
    'golden_cross_min_volume': [1.0, 1.5, 2.0],
    'momentum_threshold': [2.0, 3.0, 4.0],
    'no_trade_end_minutes': [10, 15, 30],
    'danger_zone_enabled': [True, False],

    # 청산 관련
    'fixed_stop_loss_pct': [-4.0, -5.0, -6.0, -7.0],
    'trailing_activation_pct': [4.0, 5.0, 6.0],
    'trailing_drop_pct': [2.5, 3.0, 3.5],
    'scale_out_enabled': [True, False],
    'rsi_overbought_sell': [70, 75, 80],
    'atr_multiplier': [1.5, 2.0, 2.5],

    # 포트폴리오 관련
    'max_positions': [3, 5, 7],
    'position_size_pct': [15.0, 20.0, 25.0],
}

# 빠른 그리드 (핵심 파라미터만)
QUICK_GRID = {
    # 진입 관련 (가장 영향력 큰 파라미터)
    'rsi_max_threshold': [70, 75, 80],
    'golden_cross_min_volume': [1.0, 1.5],
    'momentum_threshold': [2.0, 3.0],
    'danger_zone_enabled': [True, False],

    # 청산 관련
    'fixed_stop_loss_pct': [-5.0, -6.0, -7.0],
    'trailing_activation_pct': [4.0, 5.0],
    'trailing_drop_pct': [3.0, 3.5],
    'scale_out_enabled': [True],

    # 포트폴리오
    'max_positions': [5],
    'position_size_pct': [20.0],
}

# 핵심 파라미터만 (최소 조합)
MINIMAL_GRID = {
    'rsi_max_threshold': [70, 75, 80],
    'fixed_stop_loss_pct': [-5.0, -6.0, -7.0],
    'trailing_activation_pct': [4.0, 5.0, 6.0],
    'danger_zone_enabled': [True, False],
}


def generate_param_combinations(grid: Dict[str, List]) -> List[GridParams]:
    """파라미터 조합 생성"""
    keys = list(grid.keys())
    values = list(grid.values())

    combinations = []
    for combo in itertools.product(*values):
        params_dict = dict(zip(keys, combo))
        params = GridParams(**params_dict)
        combinations.append(params)

    return combinations


# =============================================================================
# 백테스트 실행 (단일)
# =============================================================================

def run_single_backtest(
    params: GridParams,
    start_date: str,
    end_date: str,
    initial_capital: float,
    use_watchlist: bool,
) -> Dict[str, Any]:
    """단일 파라미터 조합으로 백테스트 실행"""

    # 여기서 import해야 멀티프로세싱에서 동작
    from utilities.backtest_minute_realistic import (
        MinuteRealisticBacktester,
        EntrySignalChecker,
        BacktestBarAggregator,
        MIN_BARS_REQUIRED,
    )
    from utilities.sell_logic_unified import SellConfig
    from shared import database
    from datetime import datetime as dt

    # 파라미터 키
    param_key = params.get_key()

    try:
        # DB 연결
        connection = database.get_db_connection()
        if not connection:
            return {
                'params': params.to_dict(),
                'param_key': param_key,
                'error': 'DB 연결 실패',
            }

        try:
            # 백테스터 생성 (커스텀 설정 적용)
            backtester = MinuteRealisticBacktester(
                initial_capital=initial_capital,
                max_positions=params.max_positions,
                position_size_pct=params.position_size_pct,
                verbose=False,
            )

            # === 진입 로직 파라미터 오버라이드 ===
            # EntrySignalChecker 내부 상수 대체를 위해 monkey-patching
            import utilities.backtest_minute_realistic as bt_module

            # 원본 값 백업
            orig_rsi_max = bt_module.RSI_MAX_THRESHOLD
            orig_gc_vol = bt_module.GOLDEN_CROSS_MIN_VOLUME_RATIO
            orig_no_trade_end = bt_module.NO_TRADE_END
            orig_danger_start = bt_module.DANGER_ZONE_START
            orig_danger_end = bt_module.DANGER_ZONE_END

            # 파라미터 적용
            bt_module.RSI_MAX_THRESHOLD = params.rsi_max_threshold
            bt_module.GOLDEN_CROSS_MIN_VOLUME_RATIO = params.golden_cross_min_volume

            from datetime import time as dt_time
            bt_module.NO_TRADE_END = dt_time(9, params.no_trade_end_minutes)

            if not params.danger_zone_enabled:
                # Danger Zone 비활성화: 시작=종료로 설정
                bt_module.DANGER_ZONE_START = dt_time(15, 0)
                bt_module.DANGER_ZONE_END = dt_time(15, 0)

            # EntrySignalChecker 재생성
            backtester.entry_checker = EntrySignalChecker()

            # 모멘텀 임계값은 _check_momentum 메서드 내부에서 사용
            # 클래스 속성으로 추가
            backtester.entry_checker._momentum_threshold = params.momentum_threshold

            # _check_momentum 메서드 오버라이드
            original_check_momentum = backtester.entry_checker._check_momentum
            def patched_check_momentum(bars):
                from typing import List, Tuple, Optional
                closes = [b.close for b in bars]
                threshold = params.momentum_threshold
                if len(closes) < 2:
                    return None
                if closes[0] <= 0:
                    return None
                momentum = ((closes[-1] - closes[0]) / closes[0]) * 100
                if momentum >= threshold:
                    reason = f"Momentum={momentum:.1f}% >= {threshold}%"
                    return ("MOMENTUM", reason)
                return None

            backtester.entry_checker._check_momentum = patched_check_momentum

            # === 청산 로직 파라미터 오버라이드 ===
            backtester.sell_config.fixed_stop_loss_pct = params.fixed_stop_loss_pct
            backtester.sell_config.trailing_activation_pct = params.trailing_activation_pct
            backtester.sell_config.trailing_drop_from_high_pct = params.trailing_drop_pct
            backtester.sell_config.scale_out_enabled = params.scale_out_enabled
            backtester.sell_config.rsi_overbought_threshold = params.rsi_overbought_sell
            backtester.sell_config.atr_multiplier = params.atr_multiplier

            # 데이터 로드
            start_dt = dt.strptime(start_date, "%Y-%m-%d")
            end_dt = dt.strptime(end_date, "%Y-%m-%d")

            success = backtester.load_data(
                connection=connection,
                start_date=start_dt,
                end_date=end_dt,
                stock_codes=None,
                use_watchlist_history=use_watchlist,
            )

            if not success:
                # 원본 값 복원
                bt_module.RSI_MAX_THRESHOLD = orig_rsi_max
                bt_module.GOLDEN_CROSS_MIN_VOLUME_RATIO = orig_gc_vol
                bt_module.NO_TRADE_END = orig_no_trade_end
                bt_module.DANGER_ZONE_START = orig_danger_start
                bt_module.DANGER_ZONE_END = orig_danger_end

                return {
                    'params': params.to_dict(),
                    'param_key': param_key,
                    'error': '데이터 로드 실패',
                }

            # 백테스트 실행
            results = backtester.run()

            # 원본 값 복원
            bt_module.RSI_MAX_THRESHOLD = orig_rsi_max
            bt_module.GOLDEN_CROSS_MIN_VOLUME_RATIO = orig_gc_vol
            bt_module.NO_TRADE_END = orig_no_trade_end
            bt_module.DANGER_ZONE_START = orig_danger_start
            bt_module.DANGER_ZONE_END = orig_danger_end

            # 결과 정리
            summary = results.get('summary', {})

            return {
                'params': params.to_dict(),
                'param_key': param_key,
                'total_trades': summary.get('total_trades', 0),
                'win_rate': summary.get('win_rate', 0),
                'total_pnl': summary.get('total_pnl', 0),
                'total_return_pct': summary.get('total_return_pct', 0),
                'mdd_pct': summary.get('mdd_pct', 0),
                'avg_holding_minutes': summary.get('avg_holding_minutes', 0),
                'final_capital': summary.get('final_capital', 0),
                'sharpe_ratio': _calculate_sharpe(results.get('daily_equity', [])),
                'profit_factor': _calculate_profit_factor(results.get('trades', [])),
                'error': None,
            }

        finally:
            connection.close()

    except Exception as e:
        return {
            'params': params.to_dict(),
            'param_key': param_key,
            'error': str(e),
        }


def _calculate_sharpe(daily_equity: List[dict], risk_free_rate: float = 0.035) -> float:
    """샤프 비율 계산 (연율화)"""
    if len(daily_equity) < 2:
        return 0.0

    equities = [d['equity'] for d in daily_equity]
    returns = []
    for i in range(1, len(equities)):
        if equities[i-1] > 0:
            daily_return = (equities[i] - equities[i-1]) / equities[i-1]
            returns.append(daily_return)

    if not returns:
        return 0.0

    import numpy as np
    mean_return = np.mean(returns)
    std_return = np.std(returns)

    if std_return == 0:
        return 0.0

    # 연율화 (252 거래일 기준)
    annual_return = mean_return * 252
    annual_std = std_return * np.sqrt(252)

    sharpe = (annual_return - risk_free_rate) / annual_std
    return round(sharpe, 3)


def _calculate_profit_factor(trades: List[dict]) -> float:
    """Profit Factor 계산 (총 이익 / 총 손실)"""
    if not trades:
        return 0.0

    total_profit = sum(t['pnl'] for t in trades if t['pnl'] > 0)
    total_loss = abs(sum(t['pnl'] for t in trades if t['pnl'] < 0))

    if total_loss == 0:
        return float('inf') if total_profit > 0 else 0.0

    return round(total_profit / total_loss, 3)


# =============================================================================
# 그리드 서치 실행
# =============================================================================

def run_grid_search(
    grid: Dict[str, List],
    start_date: str,
    end_date: str,
    initial_capital: float,
    use_watchlist: bool,
    parallel: int = 1,
    output_dir: str = "logs/backtest/grid",
) -> List[Dict[str, Any]]:
    """그리드 서치 실행"""

    # 파라미터 조합 생성
    combinations = generate_param_combinations(grid)
    total_combos = len(combinations)

    logger.info(f"📊 그리드 서치 시작")
    logger.info(f"   총 조합 수: {total_combos}")
    logger.info(f"   병렬 처리: {parallel}개 프로세스")

    results = []

    if parallel > 1:
        # 병렬 실행
        with ProcessPoolExecutor(max_workers=parallel) as executor:
            futures = {
                executor.submit(
                    run_single_backtest,
                    params,
                    start_date,
                    end_date,
                    initial_capital,
                    use_watchlist,
                ): params
                for params in combinations
            }

            completed = 0
            for future in as_completed(futures):
                completed += 1
                result = future.result()
                results.append(result)

                if result.get('error'):
                    logger.warning(f"   [{completed}/{total_combos}] 오류: {result['error']}")
                else:
                    logger.info(
                        f"   [{completed}/{total_combos}] "
                        f"수익률: {result['total_return_pct']:.2f}%, "
                        f"승률: {result['win_rate']:.1f}%, "
                        f"MDD: {result['mdd_pct']:.2f}%"
                    )
    else:
        # 순차 실행
        for idx, params in enumerate(combinations, 1):
            result = run_single_backtest(
                params,
                start_date,
                end_date,
                initial_capital,
                use_watchlist,
            )
            results.append(result)

            if result.get('error'):
                logger.warning(f"   [{idx}/{total_combos}] 오류: {result['error']}")
            else:
                logger.info(
                    f"   [{idx}/{total_combos}] "
                    f"수익률: {result['total_return_pct']:.2f}%, "
                    f"승률: {result['win_rate']:.1f}%, "
                    f"MDD: {result['mdd_pct']:.2f}%"
                )

    return results


def analyze_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """결과 분석"""

    # 오류 제외
    valid_results = [r for r in results if not r.get('error')]

    if not valid_results:
        return {'error': '유효한 결과 없음'}

    # 정렬 기준별 Top 5
    analysis = {
        'total_combinations': len(results),
        'valid_combinations': len(valid_results),
        'error_count': len(results) - len(valid_results),
    }

    # 수익률 기준 Top 5
    by_return = sorted(valid_results, key=lambda x: x['total_return_pct'], reverse=True)
    analysis['top5_by_return'] = by_return[:5]

    # 승률 기준 Top 5
    by_winrate = sorted(valid_results, key=lambda x: x['win_rate'], reverse=True)
    analysis['top5_by_winrate'] = by_winrate[:5]

    # 샤프 비율 기준 Top 5
    by_sharpe = sorted(valid_results, key=lambda x: x.get('sharpe_ratio', 0), reverse=True)
    analysis['top5_by_sharpe'] = by_sharpe[:5]

    # MDD 기준 Top 5 (낮을수록 좋음)
    by_mdd = sorted(valid_results, key=lambda x: x['mdd_pct'])
    analysis['top5_by_low_mdd'] = by_mdd[:5]

    # Profit Factor 기준 Top 5
    by_pf = sorted(valid_results, key=lambda x: x.get('profit_factor', 0), reverse=True)
    analysis['top5_by_profit_factor'] = by_pf[:5]

    # 종합 점수 (수익률 * 승률 / MDD)
    for r in valid_results:
        mdd = max(r['mdd_pct'], 0.01)  # 0 방지
        r['composite_score'] = (r['total_return_pct'] * r['win_rate']) / mdd

    by_composite = sorted(valid_results, key=lambda x: x['composite_score'], reverse=True)
    analysis['top5_by_composite'] = by_composite[:5]

    # 파라미터별 영향 분석
    analysis['param_impact'] = _analyze_param_impact(valid_results)

    return analysis


def _analyze_param_impact(results: List[Dict[str, Any]]) -> Dict[str, Dict]:
    """파라미터별 영향 분석"""
    import numpy as np

    impact = {}

    # 각 파라미터별로 그룹화하여 평균 수익률 비교
    param_names = [
        'rsi_max_threshold', 'golden_cross_min_volume', 'momentum_threshold',
        'no_trade_end_minutes', 'danger_zone_enabled', 'fixed_stop_loss_pct',
        'trailing_activation_pct', 'trailing_drop_pct', 'scale_out_enabled',
        'rsi_overbought_sell', 'atr_multiplier', 'max_positions', 'position_size_pct'
    ]

    for param_name in param_names:
        # 파라미터 값별 그룹화
        groups = {}
        for r in results:
            param_value = r['params'].get(param_name)
            if param_value is not None:
                key = str(param_value)
                if key not in groups:
                    groups[key] = []
                groups[key].append(r['total_return_pct'])

        if groups:
            # 각 그룹의 평균 수익률
            group_stats = {}
            for value, returns in groups.items():
                group_stats[value] = {
                    'mean_return': round(np.mean(returns), 3),
                    'count': len(returns),
                }

            impact[param_name] = group_stats

    return impact


def print_analysis(analysis: Dict[str, Any]):
    """분석 결과 출력"""

    print("\n" + "=" * 70)
    print("📊 그리드 서치 분석 결과")
    print("=" * 70)

    print(f"\n총 조합: {analysis['total_combinations']}개")
    print(f"유효 결과: {analysis['valid_combinations']}개")
    print(f"오류: {analysis['error_count']}개")

    # Top 5 by Return
    print("\n" + "-" * 70)
    print("🏆 수익률 Top 5")
    print("-" * 70)
    for i, r in enumerate(analysis.get('top5_by_return', []), 1):
        print(f"  {i}. 수익률: {r['total_return_pct']:+.2f}%, "
              f"승률: {r['win_rate']:.1f}%, "
              f"MDD: {r['mdd_pct']:.2f}%, "
              f"거래: {r['total_trades']}건")
        _print_key_params(r['params'])

    # Top 5 by Composite Score
    print("\n" + "-" * 70)
    print("🎯 종합 점수 Top 5 (수익률 × 승률 / MDD)")
    print("-" * 70)
    for i, r in enumerate(analysis.get('top5_by_composite', []), 1):
        print(f"  {i}. 종합: {r['composite_score']:.2f}, "
              f"수익률: {r['total_return_pct']:+.2f}%, "
              f"승률: {r['win_rate']:.1f}%, "
              f"MDD: {r['mdd_pct']:.2f}%")
        _print_key_params(r['params'])

    # Top 5 by Sharpe
    print("\n" + "-" * 70)
    print("📈 샤프 비율 Top 5")
    print("-" * 70)
    for i, r in enumerate(analysis.get('top5_by_sharpe', []), 1):
        print(f"  {i}. Sharpe: {r.get('sharpe_ratio', 0):.3f}, "
              f"수익률: {r['total_return_pct']:+.2f}%, "
              f"MDD: {r['mdd_pct']:.2f}%")

    # 파라미터 영향 분석
    print("\n" + "-" * 70)
    print("🔍 파라미터별 평균 수익률")
    print("-" * 70)

    param_impact = analysis.get('param_impact', {})
    for param_name, stats in param_impact.items():
        print(f"\n  {param_name}:")
        sorted_stats = sorted(stats.items(), key=lambda x: x[1]['mean_return'], reverse=True)
        for value, s in sorted_stats:
            print(f"    {value}: {s['mean_return']:+.2f}% (n={s['count']})")


def _print_key_params(params: dict):
    """핵심 파라미터 출력"""
    print(f"      RSI차단={params.get('rsi_max_threshold')}, "
          f"손절={params.get('fixed_stop_loss_pct')}%, "
          f"TTP활성={params.get('trailing_activation_pct')}%, "
          f"DangerZone={params.get('danger_zone_enabled')}")


# =============================================================================
# CLI
# =============================================================================

def parse_args():
    parser = argparse.ArgumentParser(description="분봉 백테스트 그리드 서치")

    parser.add_argument(
        "--start-date",
        type=str,
        default="2025-12-17",
        help="시작일 (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="종료일 (YYYY-MM-DD, 기본: 오늘)",
    )
    parser.add_argument(
        "--initial-capital",
        type=float,
        default=210_000_000,
        help="초기 자본금 (기본: 2.1억)",
    )
    parser.add_argument(
        "--parallel", "-p",
        type=int,
        default=1,
        help="병렬 처리 프로세스 수 (기본: 1)",
    )
    parser.add_argument(
        "--quick", "-q",
        action="store_true",
        help="빠른 테스트 (핵심 파라미터만)",
    )
    parser.add_argument(
        "--minimal", "-m",
        action="store_true",
        help="최소 테스트 (가장 핵심만)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="logs/backtest/grid",
        help="결과 저장 디렉토리",
    )

    return parser.parse_args()


def main():
    args = parse_args()

    # 종료일 기본값
    if args.end_date:
        end_date = args.end_date
    else:
        end_date = datetime.now().strftime("%Y-%m-%d")

    # 그리드 선택
    if args.minimal:
        grid = MINIMAL_GRID
        grid_name = "MINIMAL"
    elif args.quick:
        grid = QUICK_GRID
        grid_name = "QUICK"
    else:
        grid = FULL_GRID
        grid_name = "FULL"

    # 조합 수 계산
    total_combos = 1
    for values in grid.values():
        total_combos *= len(values)

    logger.info("=" * 70)
    logger.info("📊 분봉 백테스트 그리드 서치")
    logger.info("=" * 70)
    logger.info(f"   그리드 모드: {grid_name}")
    logger.info(f"   기간: {args.start_date} ~ {end_date}")
    logger.info(f"   초기 자본: {args.initial_capital:,.0f}원")
    logger.info(f"   총 조합 수: {total_combos}개")
    logger.info(f"   병렬 처리: {args.parallel}개 프로세스")

    # 예상 시간 (조합당 ~40초 가정)
    est_time = total_combos * 40 / max(args.parallel, 1)
    logger.info(f"   예상 소요 시간: ~{est_time/60:.0f}분")

    # 그리드 서치 실행
    results = run_grid_search(
        grid=grid,
        start_date=args.start_date,
        end_date=end_date,
        initial_capital=args.initial_capital,
        use_watchlist=True,
        parallel=args.parallel,
        output_dir=args.output_dir,
    )

    # 결과 분석
    analysis = analyze_results(results)

    # 결과 출력
    print_analysis(analysis)

    # 결과 저장
    os.makedirs(args.output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 전체 결과 JSON
    results_path = os.path.join(args.output_dir, f"grid_results_{timestamp}.json")
    with open(results_path, 'w', encoding='utf-8') as f:
        json.dump({
            'config': {
                'grid_mode': grid_name,
                'start_date': args.start_date,
                'end_date': end_date,
                'initial_capital': args.initial_capital,
                'total_combinations': total_combos,
            },
            'results': results,
            'analysis': {
                k: v for k, v in analysis.items()
                if k not in ['top5_by_return', 'top5_by_winrate', 'top5_by_sharpe',
                            'top5_by_low_mdd', 'top5_by_profit_factor', 'top5_by_composite']
            },
            'top_results': {
                'by_return': analysis.get('top5_by_return', []),
                'by_composite': analysis.get('top5_by_composite', []),
                'by_sharpe': analysis.get('top5_by_sharpe', []),
            },
        }, f, ensure_ascii=False, indent=2)

    logger.info(f"\n📁 결과 저장: {results_path}")

    # CSV 요약
    csv_path = os.path.join(args.output_dir, f"grid_summary_{timestamp}.csv")
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        if results:
            # 유효한 결과만 필터링
            valid_results = [r for r in results if not r.get('error')]
            if valid_results:
                # 동적으로 모든 파라미터 포함
                all_param_keys = set()
                for r in valid_results:
                    all_param_keys.update(r['params'].keys())

                fieldnames = [
                    'total_return_pct', 'win_rate', 'mdd_pct', 'total_trades',
                    'sharpe_ratio', 'profit_factor', 'final_capital',
                ] + sorted(all_param_keys)

                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
                writer.writeheader()

                for r in sorted(valid_results, key=lambda x: x['total_return_pct'], reverse=True):
                    row = {
                        'total_return_pct': r['total_return_pct'],
                        'win_rate': r['win_rate'],
                        'mdd_pct': r['mdd_pct'],
                        'total_trades': r['total_trades'],
                        'sharpe_ratio': r.get('sharpe_ratio', 0),
                        'profit_factor': r.get('profit_factor', 0),
                        'final_capital': r['final_capital'],
                        **r['params'],
                    }
                    writer.writerow(row)

    logger.info(f"📁 CSV 요약: {csv_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
