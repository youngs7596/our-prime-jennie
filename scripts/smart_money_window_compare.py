"""
Smart Money 윈도우 비교: 3일 vs 5일 vs 10일

factor_alpha_study.py의 IC/IR/Quintile 프레임워크를 활용하여
smart_money (외인+기관 누적 순매수) 최적 윈도우를 탐색.

사용법:
    .venv/bin/python scripts/smart_money_window_compare.py
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
WINDOWS = [3, 5, 10]
FORWARD_DAYS = [5, 10]


def load_data(session):
    """가격 + 수급 데이터 로드"""
    cutoff_date = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).date()

    masters = session.query(
        StockMaster.stock_code, StockMaster.stock_name, StockMaster.market_cap
    ).filter(StockMaster.market_cap >= MIN_MARKET_CAP).all()

    target_codes = {m.stock_code for m in masters}
    name_map = {m.stock_code: m.stock_name for m in masters}
    print(f"📊 시총 ≥ 3,000억: {len(target_codes)}개 종목")

    # 가격
    print("   가격 데이터 로드 중...")
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
        print(f"   비정상 변동 제외: {len(abnormal)}개")

    print(f"   → 가격: {len(df_price):,}건, {df_price['stock_code'].nunique()}개 종목")

    # 수급
    print("   수급 데이터 로드 중...")
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
    print(f"   → 수급: {len(df_inv):,}건")

    return df_price, df_inv, name_map


def compute_factors(df_price, df_inv):
    """3d/5d/10d 윈도우별 smart_money 팩터 + forward returns 계산"""
    pivot_close = df_price.pivot(index='date', columns='stock_code', values='close').sort_index()
    pivot_volume = df_price.pivot(index='date', columns='stock_code', values='volume').sort_index()

    inv_foreign = df_inv.pivot_table(index='date', columns='stock_code', values='foreign_net', aggfunc='sum')
    inv_institution = df_inv.pivot_table(index='date', columns='stock_code', values='institution_net', aggfunc='sum')

    # Forward returns
    fwd_5d = pivot_close.pct_change(5).shift(-5)
    fwd_10d = pivot_close.pct_change(10).shift(-10)

    all_dates = sorted(pivot_close.index)
    # 리밸런싱: 5거래일마다, 워밍업 15일, 끝에서 12일 여유
    rebal_dates = [all_dates[i] for i in range(15, len(all_dates) - 12, 5)]
    stock_codes = pivot_close.columns.tolist()

    print(f"🔄 팩터 계산 중... (리밸런싱 {len(rebal_dates)}회)")

    records = []

    for rdate in rebal_dates:
        loc_idx = pivot_close.index.get_loc(rdate)

        for code in stock_codes:
            close_series = pivot_close[code].iloc[:loc_idx + 1]
            if close_series.isna().iloc[-1] or len(close_series.dropna()) < 15:
                continue

            closes = close_series.dropna().values
            cur_price = closes[-1]

            factors = {}

            # 각 윈도우별 smart_money 계산
            for w in WINDOWS:
                f_sum = 0
                i_sum = 0

                if code in inv_foreign.columns:
                    inv_slice = inv_foreign[code].iloc[max(0, loc_idx - w + 1):loc_idx + 1].dropna()
                    if len(inv_slice) > 0:
                        f_sum = inv_slice.sum()

                if code in inv_institution.columns:
                    inv_slice = inv_institution[code].iloc[max(0, loc_idx - w + 1):loc_idx + 1].dropna()
                    if len(inv_slice) > 0:
                        i_sum = inv_slice.sum()

                sm = f_sum + i_sum
                if sm != 0:
                    factors[f'smart_money_{w}d'] = sm
                    factors[f'foreign_flow_{w}d'] = f_sum
                    factors[f'institution_flow_{w}d'] = i_sum

                    # 거래량 대비 정규화 버전
                    if code in pivot_volume.columns:
                        vol_slice = pivot_volume[code].iloc[max(0, loc_idx - 20):loc_idx + 1].dropna()
                        if len(vol_slice) >= 5:
                            avg_vol = vol_slice.mean()
                            if avg_vol > 0:
                                factors[f'smart_money_{w}d_norm'] = sm / avg_vol

            # Forward returns
            fwd_rets = {}
            if rdate in fwd_5d.index and code in fwd_5d.columns:
                val = fwd_5d.loc[rdate, code]
                if not pd.isna(val):
                    fwd_rets['fwd_5d'] = val * 100
            if rdate in fwd_10d.index and code in fwd_10d.columns:
                val = fwd_10d.loc[rdate, code]
                if not pd.isna(val):
                    fwd_rets['fwd_10d'] = val * 100

            if fwd_rets and factors:
                records.append({
                    'date': rdate,
                    'stock_code': code,
                    **factors,
                    **fwd_rets,
                })

    df = pd.DataFrame(records)
    print(f"✅ 팩터 데이터: {len(df):,}건 ({df['stock_code'].nunique()}개 종목 × {len(rebal_dates)}회)")
    return df


def analyze_ic(df_factors, factor_cols):
    """IC / IR 분석"""
    results = []

    for factor in factor_cols:
        for fwd_col in ['fwd_5d', 'fwd_10d']:
            ics = []
            for date, group in df_factors.groupby('date'):
                valid = group[[factor, fwd_col]].dropna()
                if len(valid) < 10:
                    continue
                ic, _ = stats.spearmanr(valid[factor], valid[fwd_col])
                if not np.isnan(ic):
                    ics.append(ic)

            if len(ics) < 3:
                continue

            ic_mean = np.mean(ics)
            ic_std = np.std(ics)
            ir = ic_mean / ic_std if ic_std > 0 else 0
            ic_positive_pct = sum(1 for x in ics if x > 0) / len(ics) * 100

            results.append({
                'factor': factor,
                'forward': fwd_col,
                'ic_mean': round(ic_mean, 4),
                'ic_std': round(ic_std, 4),
                'ir': round(ir, 3),
                'ic_positive_pct': round(ic_positive_pct, 1),
                'n_periods': len(ics),
            })

    return pd.DataFrame(results)


def analyze_quintiles(df_factors, factor_cols):
    """Quintile spread 분석"""
    results = []

    for factor in factor_cols:
        for fwd_col in ['fwd_5d', 'fwd_10d']:
            top_rets = []
            bot_rets = []

            for date, group in df_factors.groupby('date'):
                valid = group[[factor, fwd_col]].dropna()
                if len(valid) < 10:
                    continue

                q80 = valid[factor].quantile(0.8)
                q20 = valid[factor].quantile(0.2)

                top = valid[valid[factor] >= q80][fwd_col]
                bot = valid[valid[factor] <= q20][fwd_col]

                if len(top) > 0 and len(bot) > 0:
                    top_rets.append(top.mean())
                    bot_rets.append(bot.mean())

            if len(top_rets) < 3:
                continue

            top_avg = np.mean(top_rets)
            bot_avg = np.mean(bot_rets)
            spread = top_avg - bot_avg
            spread_std = np.std([t - b for t, b in zip(top_rets, bot_rets)])
            spread_ir = spread / spread_std if spread_std > 0 else 0

            results.append({
                'factor': factor,
                'forward': fwd_col,
                'top20_avg': round(top_avg, 3),
                'bot20_avg': round(bot_avg, 3),
                'spread': round(spread, 3),
                'spread_ir': round(spread_ir, 3),
                'n_periods': len(top_rets),
            })

    return pd.DataFrame(results)


def main():
    init_engine()

    with session_scope(readonly=True) as session:
        df_price, df_inv, name_map = load_data(session)

    df_factors = compute_factors(df_price, df_inv)

    if df_factors.empty:
        print("❌ 팩터 데이터가 없습니다.")
        return

    # 분석 대상 팩터 목록
    factor_cols = [c for c in df_factors.columns
                   if c.startswith(('smart_money_', 'foreign_flow_', 'institution_flow_'))]
    factor_cols = sorted(factor_cols)

    print(f"\n분석 팩터: {factor_cols}")

    # ============================================================
    # IC / IR 분석
    # ============================================================
    ic_df = analyze_ic(df_factors, factor_cols)

    print("\n" + "=" * 95)
    print("  Part 1: IC / IR 분석 (Spearman Rank Correlation)")
    print("  IC > 0: 팩터 값이 높을수록 향후 수익률 높음")
    print("  |IR| > 0.5: 통계적으로 유의미한 팩터")
    print("=" * 95)

    for fwd_col in ['fwd_5d', 'fwd_10d']:
        days = fwd_col.replace('fwd_', '').replace('d', '')
        sub = ic_df[ic_df['forward'] == fwd_col].sort_values('ir', ascending=False)

        if sub.empty:
            print(f"\n  [Forward {days}D] 데이터 부족")
            continue

        print(f"\n  ┌─ Forward {days}D Returns ─────────────────────────────────────────────────────┐")
        print(f"  │ {'팩터':30s} │ {'IC평균':>7s} │ {'IC표준편차':>8s} │ {'IR':>6s} │ {'IC+비율':>7s} │ {'기간':>4s} │")
        print(f"  ├────────────────────────────────┼─────────┼──────────┼────────┼─────────┼──────┤")

        for _, row in sub.iterrows():
            marker = ""
            if abs(row['ir']) >= 0.5:
                marker = " ★"
            elif abs(row['ir']) >= 0.3:
                marker = " ☆"
            print(f"  │ {row['factor']:30s} │ {row['ic_mean']:>+7.4f} │ {row['ic_std']:>8.4f} │ {row['ir']:>+6.3f} │ {row['ic_positive_pct']:>6.1f}% │ {row['n_periods']:>4d} │{marker}")

        print(f"  └────────────────────────────────┴─────────┴──────────┴────────┴─────────┴──────┘")

    # ============================================================
    # Quintile Spread 분석
    # ============================================================
    q_df = analyze_quintiles(df_factors, factor_cols)

    print("\n" + "=" * 95)
    print("  Part 2: Quintile Spread (상위 20% - 하위 20%)")
    print("  Spread > 0: 팩터 상위 종목이 하위 종목 대비 초과 수익")
    print("=" * 95)

    for fwd_col in ['fwd_5d', 'fwd_10d']:
        days = fwd_col.replace('fwd_', '').replace('d', '')
        sub = q_df[q_df['forward'] == fwd_col].sort_values('spread', ascending=False)

        if sub.empty:
            print(f"\n  [Forward {days}D] 데이터 부족")
            continue

        print(f"\n  ┌─ Forward {days}D Returns ───────────────────────────────────────────────────────────────┐")
        print(f"  │ {'팩터':30s} │ {'Top20%':>7s} │ {'Bot20%':>7s} │ {'Spread':>7s} │ {'SpreadIR':>8s} │ {'기간':>4s} │")
        print(f"  ├────────────────────────────────┼─────────┼─────────┼─────────┼──────────┼──────┤")

        for _, row in sub.iterrows():
            marker = ""
            if abs(row['spread_ir']) >= 0.5:
                marker = " ★"
            elif abs(row['spread_ir']) >= 0.3:
                marker = " ☆"
            print(f"  │ {row['factor']:30s} │ {row['top20_avg']:>+7.3f} │ {row['bot20_avg']:>+7.3f} │ {row['spread']:>+7.3f} │ {row['spread_ir']:>+8.3f} │ {row['n_periods']:>4d} │{marker}")

        print(f"  └────────────────────────────────┴─────────┴─────────┴─────────┴──────────┴──────┘")

    # ============================================================
    # 최종 비교 요약
    # ============================================================
    print("\n" + "=" * 95)
    print("  Part 3: Smart Money 윈도우 비교 요약")
    print("=" * 95)

    sm_factors = [f'smart_money_{w}d' for w in WINDOWS]
    sm_norm_factors = [f'smart_money_{w}d_norm' for w in WINDOWS]

    for label, factors_list in [("절대값 (raw)", sm_factors), ("거래량 정규화 (norm)", sm_norm_factors)]:
        print(f"\n  [{label}]")
        print(f"  {'윈도우':>8s}  {'IC(5D)':>8s}  {'IR(5D)':>8s}  {'IC(10D)':>8s}  {'IR(10D)':>8s}  {'Spread5D':>10s}  {'Spread10D':>10s}  {'SpIR(5D)':>10s}  {'SpIR(10D)':>10s}")
        print("  " + "-" * 96)

        for f in factors_list:
            ic5 = ic_df[(ic_df['factor'] == f) & (ic_df['forward'] == 'fwd_5d')]
            ic10 = ic_df[(ic_df['factor'] == f) & (ic_df['forward'] == 'fwd_10d')]
            q5 = q_df[(q_df['factor'] == f) & (q_df['forward'] == 'fwd_5d')]
            q10 = q_df[(q_df['factor'] == f) & (q_df['forward'] == 'fwd_10d')]

            window = f.replace('smart_money_', '').replace('_norm', '')

            ic5_val = ic5.iloc[0]['ic_mean'] if not ic5.empty else float('nan')
            ir5_val = ic5.iloc[0]['ir'] if not ic5.empty else float('nan')
            ic10_val = ic10.iloc[0]['ic_mean'] if not ic10.empty else float('nan')
            ir10_val = ic10.iloc[0]['ir'] if not ic10.empty else float('nan')
            sp5_val = q5.iloc[0]['spread'] if not q5.empty else float('nan')
            sp10_val = q10.iloc[0]['spread'] if not q10.empty else float('nan')
            spir5_val = q5.iloc[0]['spread_ir'] if not q5.empty else float('nan')
            spir10_val = q10.iloc[0]['spread_ir'] if not q10.empty else float('nan')

            best5 = " ◀" if not np.isnan(ir5_val) and ir5_val == max(
                [ic_df[(ic_df['factor'] == ff) & (ic_df['forward'] == 'fwd_5d')].iloc[0]['ir']
                 for ff in factors_list
                 if not ic_df[(ic_df['factor'] == ff) & (ic_df['forward'] == 'fwd_5d')].empty],
                default=float('-inf')
            ) else ""

            print(f"  {window:>8s}  {ic5_val:>+8.4f}  {ir5_val:>+8.3f}  {ic10_val:>+8.4f}  {ir10_val:>+8.3f}  {sp5_val:>+10.3f}  {sp10_val:>+10.3f}  {spir5_val:>+10.3f}  {spir10_val:>+10.3f}{best5}")

    # 최종 추천
    print(f"\n  💡 해석 가이드:")
    print(f"     IR > +0.5 = 강한 양의 예측력 (높을수록 수익 높음)")
    print(f"     Spread > 0 = 상위 그룹이 하위 대비 초과수익")
    print(f"     SpreadIR > 0.5 = 일관적으로 유의미한 초과수익")
    print("=" * 95)


if __name__ == '__main__':
    main()
