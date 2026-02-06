"""
가중치 배분별 백테스트: supply_demand 비중 최적화

시나리오:
  A) 기존: supply_demand 15점 (1일만, smart_money 없음)
  B) 적극: supply_demand 25점 (smart_money_5d 12점)
  C) 타협: supply_demand 20점 (smart_money_5d 8점)
  D) 보수: supply_demand 18점 (smart_money_5d 5점)

각 시나리오에서 종합 quant score를 시뮬레이션하고,
점수 상위 그룹의 실제 수익률을 비교.

사용법:
    .venv/bin/python scripts/backtest_weight_allocation.py
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from scipy import stats

from sqlalchemy import func as sa_func
from shared.db.connection import init_engine, session_scope
from shared.db.models import StockDailyPrice, StockMaster, StockInvestorTrading

MIN_MARKET_CAP = 3000_0000_0000
LOOKBACK_DAYS = 120
ABNORMAL_DAILY_CHANGE_PCT = 50.0

# ============================================================
# 가중치 시나리오
# ============================================================
SCENARIOS = {
    'A_기존_15점': {
        'momentum': 25, 'quality': 20, 'value': 15,
        'technical': 10, 'news': 15,
        'sd_1d': 15, 'sd_5d': 0,  # smart_money 없음
    },
    'B_적극_25점': {
        'momentum': 20, 'quality': 20, 'value': 10,
        'technical': 10, 'news': 15,
        'sd_1d': 13, 'sd_5d': 12,  # smart_money 12점
    },
    'C_타협_20점': {
        'momentum': 22, 'quality': 20, 'value': 13,
        'technical': 10, 'news': 15,
        'sd_1d': 12, 'sd_5d': 8,  # smart_money 8점
    },
    'D_보수_18점': {
        'momentum': 24, 'quality': 20, 'value': 13,
        'technical': 10, 'news': 15,
        'sd_1d': 13, 'sd_5d': 5,  # smart_money 5점
    },
}


def load_data(session):
    """가격 + 수급 데이터 로드"""
    cutoff_date = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).date()

    masters = session.query(
        StockMaster.stock_code, StockMaster.stock_name, StockMaster.market_cap
    ).filter(StockMaster.market_cap >= MIN_MARKET_CAP).all()
    target_codes = {m.stock_code for m in masters}
    name_map = {m.stock_code: m.stock_name for m in masters}
    cap_map = {m.stock_code: float(m.market_cap) if m.market_cap else 0 for m in masters}

    print(f"시총 ≥ 3,000억: {len(target_codes)}개 종목")

    # 가격
    prices = session.query(
        StockDailyPrice.stock_code,
        StockDailyPrice.price_date,
        StockDailyPrice.close_price,
        StockDailyPrice.volume,
    ).filter(
        StockDailyPrice.price_date >= cutoff_date,
        StockDailyPrice.stock_code.in_(target_codes),
    ).order_by(
        StockDailyPrice.stock_code,
        StockDailyPrice.price_date,
    ).all()

    df_price = pd.DataFrame(prices, columns=['stock_code', 'date', 'close', 'volume'])
    df_price['date'] = pd.to_datetime(df_price['date'])

    # 비정상 변동 제거
    abnormal = set()
    for code in df_price['stock_code'].unique():
        sdf = df_price[df_price['stock_code'] == code].sort_values('date')
        rets = sdf['close'].pct_change().abs() * 100
        if rets.max() > ABNORMAL_DAILY_CHANGE_PCT:
            abnormal.add(code)
    if abnormal:
        df_price = df_price[~df_price['stock_code'].isin(abnormal)]

    print(f"가격: {len(df_price):,}건, {df_price['stock_code'].nunique()}개 종목")

    # 수급
    inv_rows = session.query(
        StockInvestorTrading.stock_code,
        StockInvestorTrading.trade_date,
        StockInvestorTrading.foreign_net_buy,
        StockInvestorTrading.institution_net_buy,
    ).filter(
        StockInvestorTrading.trade_date >= cutoff_date,
        StockInvestorTrading.stock_code.in_(target_codes),
    ).all()

    df_inv = pd.DataFrame(inv_rows, columns=['stock_code', 'date', 'foreign_net', 'institution_net'])
    df_inv['date'] = pd.to_datetime(df_inv['date'])
    df_inv['foreign_net'] = df_inv['foreign_net'].astype(float)
    df_inv['institution_net'] = df_inv['institution_net'].astype(float)
    print(f"수급: {len(df_inv):,}건")

    return df_price, df_inv, name_map, cap_map


def compute_stock_factors(closes, volumes, inv_foreign_series, inv_institution_series, loc_idx, window_5d=5):
    """단일 종목/날짜의 간이 팩터 점수 계산 (0~1 정규화)"""
    factors = {}

    cur_price = closes[-1]

    # 모멘텀 (0~1): 6개월 수익률 기반
    if len(closes) >= 120:
        ret_6m = cur_price / closes[-120] - 1
        factors['momentum'] = np.clip(0.5 + ret_6m, 0, 1)
    else:
        factors['momentum'] = 0.5

    # 기술적 (0~1): RSI 기반 — 과매도일수록 높음
    if len(closes) >= 15:
        deltas = np.diff(closes[-15:])
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)
        rsi = 100 - (100 / (1 + avg_gain / avg_loss)) if avg_loss > 0 else 100
        # 과매도(RSI낮음) = 기회 → 높은 점수
        factors['technical'] = np.clip(1 - rsi / 100, 0, 1)
    else:
        factors['technical'] = 0.5

    # 품질/가치/뉴스는 DB 없이 중립
    factors['quality'] = 0.5
    factors['value'] = 0.5
    factors['news'] = 0.5

    # 수급 1D (0~1)
    avg_vol = np.mean(volumes[-20:]) if len(volumes) >= 20 else None
    if inv_foreign_series is not None and len(inv_foreign_series) >= 1:
        f_1d = inv_foreign_series.iloc[-1]
        i_1d = inv_institution_series.iloc[-1] if inv_institution_series is not None and len(inv_institution_series) >= 1 else 0
        net_1d = f_1d + i_1d
        if avg_vol and avg_vol > 0:
            ratio_1d = net_1d / avg_vol
            factors['sd_1d'] = np.clip(0.5 + ratio_1d / 0.10, 0, 1)
        else:
            factors['sd_1d'] = np.clip(0.5 + net_1d / 10_000_000, 0, 1)
    else:
        factors['sd_1d'] = 0.5

    # 수급 5D smart money (0~1)
    if inv_foreign_series is not None and len(inv_foreign_series) >= 3:
        tail = min(window_5d, len(inv_foreign_series))
        f_nd = inv_foreign_series.iloc[-tail:].sum()
        i_nd = inv_institution_series.iloc[-tail:].sum() if inv_institution_series is not None and len(inv_institution_series) >= tail else 0
        sm_nd = f_nd + i_nd
        if avg_vol and avg_vol > 0:
            ratio_nd = sm_nd / avg_vol
            factors['sd_5d'] = np.clip(0.5 + ratio_nd / 0.10, 0, 1)
        else:
            factors['sd_5d'] = np.clip(0.5 + sm_nd / 50_000_000, 0, 1)
    else:
        factors['sd_5d'] = 0.5

    return factors


def score_with_weights(factors, weights):
    """가중치 시나리오로 종합 점수 계산 (100점 만점)"""
    total = 0
    for key in ['momentum', 'quality', 'value', 'technical', 'news', 'sd_1d', 'sd_5d']:
        w = weights.get(key, 0)
        f = factors.get(key, 0.5)
        total += f * w
    return total


def run_backtest():
    init_engine()

    with session_scope(readonly=True) as session:
        df_price, df_inv, name_map, cap_map = load_data(session)

    pivot_close = df_price.pivot(index='date', columns='stock_code', values='close').sort_index()
    pivot_volume = df_price.pivot(index='date', columns='stock_code', values='volume').sort_index()

    inv_foreign = df_inv.pivot_table(index='date', columns='stock_code', values='foreign_net', aggfunc='sum')
    inv_institution = df_inv.pivot_table(index='date', columns='stock_code', values='institution_net', aggfunc='sum')

    # Forward returns
    fwd_5d = pivot_close.pct_change(5).shift(-5)
    fwd_10d = pivot_close.pct_change(10).shift(-10)
    fwd_20d = pivot_close.pct_change(20).shift(-20)

    all_dates = sorted(pivot_close.index)
    rebal_dates = [all_dates[i] for i in range(25, len(all_dates) - 22, 5)]

    print(f"\n리밸런싱: {len(rebal_dates)}회 ({rebal_dates[0].date()} ~ {rebal_dates[-1].date()})")
    print(f"시나리오: {list(SCENARIOS.keys())}")

    # 각 리밸런싱일마다 모든 종목 점수 계산
    all_records = []

    for rdate in rebal_dates:
        loc_idx = pivot_close.index.get_loc(rdate)

        for code in pivot_close.columns:
            close_series = pivot_close[code].iloc[:loc_idx + 1].dropna()
            if len(close_series) < 25:
                continue

            closes = close_series.values
            vol_series = pivot_volume[code].iloc[:loc_idx + 1].dropna()
            volumes = vol_series.values if len(vol_series) > 0 else np.array([1])

            # 수급 시계열
            inv_f = inv_foreign[code].iloc[:loc_idx + 1].dropna() if code in inv_foreign.columns else None
            inv_i = inv_institution[code].iloc[:loc_idx + 1].dropna() if code in inv_institution.columns else None

            factors = compute_stock_factors(closes, volumes, inv_f, inv_i, loc_idx)

            # Forward returns
            fwd = {}
            if rdate in fwd_5d.index and code in fwd_5d.columns:
                v5 = fwd_5d.loc[rdate, code]
                if not pd.isna(v5):
                    fwd['fwd_5d'] = v5 * 100
            if rdate in fwd_10d.index and code in fwd_10d.columns:
                v10 = fwd_10d.loc[rdate, code]
                if not pd.isna(v10):
                    fwd['fwd_10d'] = v10 * 100
            if rdate in fwd_20d.index and code in fwd_20d.columns:
                v20 = fwd_20d.loc[rdate, code]
                if not pd.isna(v20):
                    fwd['fwd_20d'] = v20 * 100

            if not fwd:
                continue

            rec = {
                'date': rdate,
                'stock_code': code,
                'stock_name': name_map.get(code, code),
                **factors,
                **fwd,
            }

            # 각 시나리오별 점수
            for scenario_name, weights in SCENARIOS.items():
                rec[f'score_{scenario_name}'] = round(score_with_weights(factors, weights), 2)

            all_records.append(rec)

    df = pd.DataFrame(all_records)
    print(f"\n총 데이터: {len(df):,}건 ({df['stock_code'].nunique()}개 종목 × {len(rebal_dates)}회)")

    # ============================================================
    # 분석: 각 시나리오별 Quintile 수익률
    # ============================================================
    print("\n" + "=" * 100)
    print("  가중치 시나리오별 Quintile 수익률 비교")
    print("  (각 리밸런싱일에 점수 상위 20% 매수 → D+5/10/20 수익률)")
    print("=" * 100)

    scenario_results = {}

    for scenario_name in SCENARIOS:
        score_col = f'score_{scenario_name}'

        top_5d, bot_5d = [], []
        top_10d, bot_10d = [], []
        top_20d, bot_20d = [], []

        for date, group in df.groupby('date'):
            valid = group[[score_col, 'fwd_5d']].dropna()
            if len(valid) < 10:
                continue

            q80 = valid[score_col].quantile(0.8)
            q20 = valid[score_col].quantile(0.2)

            top = valid[valid[score_col] >= q80]
            bot = valid[valid[score_col] <= q20]

            if len(top) > 0 and len(bot) > 0:
                top_5d.append(top['fwd_5d'].mean())
                bot_5d.append(bot['fwd_5d'].mean())

            valid10 = group[[score_col, 'fwd_10d']].dropna()
            if len(valid10) >= 10:
                top10 = valid10[valid10[score_col] >= valid10[score_col].quantile(0.8)]
                bot10 = valid10[valid10[score_col] <= valid10[score_col].quantile(0.2)]
                if len(top10) > 0 and len(bot10) > 0:
                    top_10d.append(top10['fwd_10d'].mean())
                    bot_10d.append(bot10['fwd_10d'].mean())

            valid20 = group[[score_col, 'fwd_20d']].dropna()
            if len(valid20) >= 10:
                top20 = valid20[valid20[score_col] >= valid20[score_col].quantile(0.8)]
                bot20 = valid20[valid20[score_col] <= valid20[score_col].quantile(0.2)]
                if len(top20) > 0 and len(bot20) > 0:
                    top_20d.append(top20['fwd_20d'].mean())
                    bot_20d.append(bot20['fwd_20d'].mean())

        scenario_results[scenario_name] = {
            'top_5d': np.mean(top_5d) if top_5d else float('nan'),
            'bot_5d': np.mean(bot_5d) if bot_5d else float('nan'),
            'spread_5d': np.mean(top_5d) - np.mean(bot_5d) if top_5d and bot_5d else float('nan'),
            'top_10d': np.mean(top_10d) if top_10d else float('nan'),
            'bot_10d': np.mean(bot_10d) if bot_10d else float('nan'),
            'spread_10d': np.mean(top_10d) - np.mean(bot_10d) if top_10d and bot_10d else float('nan'),
            'top_20d': np.mean(top_20d) if top_20d else float('nan'),
            'bot_20d': np.mean(bot_20d) if bot_20d else float('nan'),
            'spread_20d': np.mean(top_20d) - np.mean(bot_20d) if top_20d and bot_20d else float('nan'),
            'n_periods': len(top_5d),
        }

    # 테이블 출력
    print(f"\n  {'시나리오':>16s}  │ {'Top20%':>7s} {'Bot20%':>7s} {'Spread':>8s} │ {'Top20%':>7s} {'Bot20%':>7s} {'Spread':>8s} │ {'Top20%':>7s} {'Bot20%':>7s} {'Spread':>8s} │ {'기간':>4s}")
    print(f"  {'':>16s}  │ {'────── D+5 ──────':^24s} │ {'───── D+10 ──────':^24s} │ {'───── D+20 ──────':^24s} │")
    print("  " + "─" * 16 + "──┼" + "─" * 25 + "┼" + "─" * 25 + "┼" + "─" * 25 + "┼" + "─" * 5)

    best_spread_5d = max(r['spread_5d'] for r in scenario_results.values() if not np.isnan(r['spread_5d']))
    best_spread_10d = max(r['spread_10d'] for r in scenario_results.values() if not np.isnan(r['spread_10d']))
    best_spread_20d = max((r['spread_20d'] for r in scenario_results.values() if not np.isnan(r['spread_20d'])), default=float('nan'))

    for name, r in scenario_results.items():
        mark5 = " ◀" if r['spread_5d'] == best_spread_5d else ""
        mark10 = " ◀" if r['spread_10d'] == best_spread_10d else ""
        mark20 = " ◀" if not np.isnan(best_spread_20d) and r['spread_20d'] == best_spread_20d else ""

        print(f"  {name:>16s}  │ {r['top_5d']:>+6.2f}% {r['bot_5d']:>+6.2f}% {r['spread_5d']:>+7.2f}%{mark5:2s} │ "
              f"{r['top_10d']:>+6.2f}% {r['bot_10d']:>+6.2f}% {r['spread_10d']:>+7.2f}%{mark10:2s} │ "
              f"{r['top_20d']:>+6.2f}% {r['bot_20d']:>+6.2f}% {r['spread_20d']:>+7.2f}%{mark20:2s} │ {r['n_periods']:>4d}")

    # ============================================================
    # IC/IR 비교
    # ============================================================
    print(f"\n{'='*100}")
    print("  시나리오별 IC / IR (종합 점수 vs 향후 수익률)")
    print(f"{'='*100}")

    print(f"\n  {'시나리오':>16s}  │ {'IC(5D)':>8s}  {'IR(5D)':>8s}  │ {'IC(10D)':>8s}  {'IR(10D)':>8s}  │ {'IC(20D)':>8s}  {'IR(20D)':>8s}")
    print("  " + "─" * 16 + "──┼" + "─" * 20 + "──┼" + "─" * 20 + "──┼" + "─" * 20)

    for scenario_name in SCENARIOS:
        score_col = f'score_{scenario_name}'
        line = f"  {scenario_name:>16s}  │"

        for fwd_col in ['fwd_5d', 'fwd_10d', 'fwd_20d']:
            ics = []
            for date, group in df.groupby('date'):
                valid = group[[score_col, fwd_col]].dropna()
                if len(valid) < 10:
                    continue
                ic, _ = stats.spearmanr(valid[score_col], valid[fwd_col])
                if not np.isnan(ic):
                    ics.append(ic)

            if ics:
                ic_mean = np.mean(ics)
                ic_std = np.std(ics)
                ir = ic_mean / ic_std if ic_std > 0 else 0
                line += f" {ic_mean:>+8.4f}  {ir:>+8.3f}  │"
            else:
                line += f" {'N/A':>8s}  {'N/A':>8s}  │"

        print(line)

    # ============================================================
    # 가중치 구성 요약
    # ============================================================
    print(f"\n{'='*100}")
    print("  가중치 배분 요약")
    print(f"{'='*100}")
    print(f"  {'시나리오':>16s}  │ {'모멘텀':>6s} {'품질':>4s} {'가치':>4s} {'기술':>4s} {'뉴스':>4s} │ {'1D수급':>6s} {'5D_SM':>6s} │ {'수급합':>6s} │ {'합계':>4s}")
    print("  " + "─" * 16 + "──┼" + "─" * 28 + "──┼" + "─" * 15 + "──┼" + "─" * 8 + "──┼" + "─" * 5)

    for name, w in SCENARIOS.items():
        sd_total = w['sd_1d'] + w['sd_5d']
        total = w['momentum'] + w['quality'] + w['value'] + w['technical'] + w['news'] + sd_total
        print(f"  {name:>16s}  │ {w['momentum']:>6d} {w['quality']:>4d} {w['value']:>4d} {w['technical']:>4d} {w['news']:>4d} │ "
              f"{w['sd_1d']:>6d} {w['sd_5d']:>6d} │ {sd_total:>6d} │ {total:>4d}")

    print(f"{'='*100}")


if __name__ == '__main__':
    run_backtest()
