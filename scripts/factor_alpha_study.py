"""
Alpha Factor Study: 전통적 퀀트 방법론으로 팩터별 수익 예측력 분석

방법론:
  1. 매주 금요일(리밸런싱일)마다 각 팩터로 종목 랭킹
  2. 랭킹과 향후 5일/10일 수익률의 상관관계(IC) 측정
  3. 상위 20% vs 하위 20% 수익률 비교 (Long-Short)
  4. IC의 평균, 표준편차, IR(Information Ratio) 계산

사용법:
    .venv/bin/python scripts/factor_alpha_study.py
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
from shared.db.models import StockDailyPrice, StockMaster, StockInvestorTrading, NewsSentiment

MIN_MARKET_CAP = 3000_0000_0000  # 3,000억
LOOKBACK_DAYS = 120  # 팩터 계산용 여유 데이터 확보 (90일 분석 + 20일 워밍업)
FORWARD_DAYS = [5, 10]  # 수익률 측정 기간
ABNORMAL_DAILY_CHANGE_PCT = 50.0


# ============================================================
# 데이터 로드
# ============================================================

def load_all_data(session):
    """분석에 필요한 모든 데이터 로드"""
    cutoff_date = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).date()

    # 1) 시총 대형주 필터
    masters = session.query(
        StockMaster.stock_code, StockMaster.stock_name, StockMaster.market_cap
    ).filter(StockMaster.market_cap >= MIN_MARKET_CAP).all()

    target_codes = {m.stock_code for m in masters}
    name_map = {m.stock_code: m.stock_name for m in masters}
    cap_map = {m.stock_code: float(m.market_cap) if m.market_cap else 0 for m in masters}
    print(f"📊 시총 ≥ 3,000억 대상: {len(target_codes)}개 종목")

    # 2) 일봉 가격
    print("   가격 데이터 로드 중...")
    prices = session.query(
        StockDailyPrice.stock_code,
        StockDailyPrice.price_date,
        StockDailyPrice.open_price,
        StockDailyPrice.close_price,
        StockDailyPrice.high_price,
        StockDailyPrice.low_price,
        StockDailyPrice.volume,
    ).filter(
        StockDailyPrice.price_date >= cutoff_date,
        StockDailyPrice.stock_code.in_(target_codes),
    ).order_by(
        StockDailyPrice.stock_code,
        StockDailyPrice.price_date,
    ).all()

    df_price = pd.DataFrame(prices, columns=[
        'stock_code', 'date', 'open', 'close', 'high', 'low', 'volume'
    ])
    df_price['date'] = pd.to_datetime(df_price['date'])

    # 비정상 변동 종목 제거
    abnormal_codes = set()
    for code in df_price['stock_code'].unique():
        sdf = df_price[df_price['stock_code'] == code].sort_values('date')
        rets = sdf['close'].pct_change().abs() * 100
        if rets.max() > ABNORMAL_DAILY_CHANGE_PCT:
            abnormal_codes.add(code)
    if abnormal_codes:
        df_price = df_price[~df_price['stock_code'].isin(abnormal_codes)]
        print(f"   비정상 변동 제외: {len(abnormal_codes)}개")

    print(f"   → 가격: {len(df_price):,}건, {df_price['stock_code'].nunique()}개 종목, "
          f"{df_price['date'].min().date()} ~ {df_price['date'].max().date()}")

    # 3) 수급 데이터
    print("   수급 데이터 로드 중...")
    inv_rows = session.query(
        StockInvestorTrading.stock_code,
        StockInvestorTrading.trade_date,
        StockInvestorTrading.foreign_net_buy,
        StockInvestorTrading.institution_net_buy,
        StockInvestorTrading.individual_net_buy,
    ).filter(
        StockInvestorTrading.trade_date >= cutoff_date,
        StockInvestorTrading.stock_code.in_(target_codes),
    ).all()

    df_inv = pd.DataFrame(inv_rows, columns=[
        'stock_code', 'date', 'foreign_net', 'institution_net', 'individual_net'
    ])
    df_inv['date'] = pd.to_datetime(df_inv['date'])
    for col in ['foreign_net', 'institution_net', 'individual_net']:
        df_inv[col] = df_inv[col].astype(float)
    print(f"   → 수급: {len(df_inv):,}건")

    # 4) 뉴스 감성
    print("   뉴스 감성 로드 중...")
    news_rows = session.query(
        NewsSentiment.stock_code,
        NewsSentiment.created_at,
        NewsSentiment.sentiment_score,
    ).filter(
        NewsSentiment.created_at >= cutoff_date,
        NewsSentiment.stock_code.in_(target_codes),
    ).all()

    df_news = pd.DataFrame(news_rows, columns=['stock_code', 'date', 'sentiment'])
    if not df_news.empty:
        df_news['date'] = pd.to_datetime(df_news['date']).dt.normalize()
        df_news['sentiment'] = df_news['sentiment'].astype(float)
    print(f"   → 뉴스: {len(df_news):,}건")

    return df_price, df_inv, df_news, name_map, cap_map


# ============================================================
# 팩터 계산
# ============================================================

def compute_all_factors(df_price, df_inv, df_news, cap_map):
    """
    각 종목/날짜별로 팩터 값 + 향후 수익률을 계산
    리밸런싱 주기: 매주 (5거래일마다)
    """
    all_dates = sorted(df_price['date'].unique())
    stock_codes = sorted(df_price['stock_code'].unique())

    # 종목별 시계열 피벗
    pivot_close = df_price.pivot(index='date', columns='stock_code', values='close').sort_index()
    pivot_high = df_price.pivot(index='date', columns='stock_code', values='high').sort_index()
    pivot_low = df_price.pivot(index='date', columns='stock_code', values='low').sort_index()
    pivot_volume = df_price.pivot(index='date', columns='stock_code', values='volume').sort_index()

    # 수급 피벗
    inv_foreign = df_inv.pivot_table(index='date', columns='stock_code', values='foreign_net', aggfunc='sum')
    inv_institution = df_inv.pivot_table(index='date', columns='stock_code', values='institution_net', aggfunc='sum')

    # 뉴스 감성 피벗 (일별 평균)
    if not df_news.empty:
        news_pivot = df_news.pivot_table(index='date', columns='stock_code', values='sentiment', aggfunc='mean')
    else:
        news_pivot = pd.DataFrame()

    # 수익률 계산
    returns_1d = pivot_close.pct_change(1)
    returns_5d = pivot_close.pct_change(5)
    returns_10d = pivot_close.pct_change(10)
    returns_20d = pivot_close.pct_change(20)

    # 향후 수익률 (forward returns)
    fwd_5d = pivot_close.pct_change(5).shift(-5)
    fwd_10d = pivot_close.pct_change(10).shift(-10)

    # 리밸런싱 날짜 (5거래일마다)
    rebal_dates = [all_dates[i] for i in range(25, len(all_dates) - 12, 5)]
    # 워밍업 25일(RSI 등 계산), 앞으로 12일(fwd_10d+여유) 필요

    print(f"\n📅 리밸런싱 날짜: {len(rebal_dates)}회 ({pd.Timestamp(rebal_dates[0]).date()} ~ {pd.Timestamp(rebal_dates[-1]).date()})")

    records = []

    for rdate in rebal_dates:
        # 해당 날짜까지의 데이터로 팩터 계산
        loc_idx = pivot_close.index.get_loc(rdate)

        for code in stock_codes:
            if code not in pivot_close.columns:
                continue

            close_series = pivot_close[code].iloc[:loc_idx + 1]
            if close_series.isna().iloc[-1] or len(close_series.dropna()) < 25:
                continue

            closes = close_series.dropna().values
            cur_price = closes[-1]

            # --- 팩터 계산 ---
            factors = {}

            # [1] 모멘텀 팩터
            if len(closes) >= 6:
                factors['momentum_5d'] = (cur_price / closes[-6] - 1) * 100
            if len(closes) >= 11:
                factors['momentum_10d'] = (cur_price / closes[-11] - 1) * 100
            if len(closes) >= 21:
                factors['momentum_20d'] = (cur_price / closes[-21] - 1) * 100

            # [2] 단기 반전 (Short-term Reversal)
            if len(closes) >= 4:
                factors['reversal_3d'] = -(cur_price / closes[-4] - 1) * 100  # 부호 반전: 하락 많을수록 높은 값

            # [3] RSI (14일)
            if len(closes) >= 15:
                deltas = np.diff(closes[-15:])
                gains = np.where(deltas > 0, deltas, 0)
                losses = np.where(deltas < 0, -deltas, 0)
                avg_gain = np.mean(gains)
                avg_loss = np.mean(losses)
                if avg_loss > 0:
                    rs = avg_gain / avg_loss
                    factors['rsi_14'] = 100 - (100 / (1 + rs))
                else:
                    factors['rsi_14'] = 100.0

            # [4] 과매도 반전 시그널 (RSI < 40이면 높은 값)
            if 'rsi_14' in factors:
                factors['oversold_signal'] = max(0, 50 - factors['rsi_14'])  # RSI 30이면 20, RSI 50이면 0

            # [5] 변동성 (20일 실현 변동성)
            if len(closes) >= 21:
                daily_rets = np.diff(np.log(closes[-21:]))
                factors['volatility_20d'] = np.std(daily_rets) * np.sqrt(252) * 100

            # [6] 저변동성 팩터 (변동성 역수 — 저변동성 프리미엄)
            if 'volatility_20d' in factors and factors['volatility_20d'] > 0:
                factors['low_vol'] = -factors['volatility_20d']

            # [7] 거래량 비율
            if code in pivot_volume.columns:
                vol_series = pivot_volume[code].iloc[max(0, loc_idx - 20):loc_idx + 1].dropna()
                if len(vol_series) >= 20:
                    avg_vol_20 = vol_series.iloc[:-1].mean()
                    if avg_vol_20 > 0:
                        factors['volume_ratio'] = vol_series.iloc[-1] / avg_vol_20
                        factors['volume_trend_5d'] = vol_series.iloc[-5:].mean() / avg_vol_20

            # [8] 거래량 급증 (당일 거래량 > 2x 평균)
            if 'volume_ratio' in factors:
                factors['volume_surge'] = max(0, factors['volume_ratio'] - 1.5)

            # [9] MA20 이격도
            if len(closes) >= 20:
                ma20 = np.mean(closes[-20:])
                factors['ma20_deviation'] = (cur_price / ma20 - 1) * 100

            # [10] 고점 대비 하락률 (Drawdown from 20d high)
            if len(closes) >= 20:
                high_20d = np.max(closes[-20:])
                factors['drawdown_20d'] = (cur_price / high_20d - 1) * 100

            # [11] 눌림목 반등 시그널 (고점 대비 -10~-25% 하락)
            if 'drawdown_20d' in factors:
                dd = factors['drawdown_20d']
                if -25 <= dd <= -10:
                    factors['pullback_signal'] = abs(dd)  # 하락 깊을수록 강한 신호
                else:
                    factors['pullback_signal'] = 0

            # [12] 볼린저밴드 위치
            if len(closes) >= 20:
                bb_mid = np.mean(closes[-20:])
                bb_std = np.std(closes[-20:])
                if bb_std > 0:
                    factors['bb_position'] = (cur_price - bb_mid) / (2 * bb_std)

            # [13] 볼린저밴드 하단 근접 시그널
            if 'bb_position' in factors:
                factors['bb_lower_signal'] = max(0, -factors['bb_position'] - 0.3)  # BB 하단 이하일수록 강한 신호

            # [14] 시총 (Size factor — 소형주 프리미엄)
            factors['size'] = -np.log(cap_map.get(code, 1e12))  # 작을수록 높은 값

            # [15] 수급 팩터
            if code in (inv_foreign.columns if not inv_foreign.empty else []):
                inv_slice = inv_foreign[code].iloc[max(0, loc_idx - 5):loc_idx + 1].dropna()
                if len(inv_slice) > 0:
                    factors['foreign_flow_5d'] = inv_slice.sum()

            if code in (inv_institution.columns if not inv_institution.empty else []):
                inv_slice = inv_institution[code].iloc[max(0, loc_idx - 5):loc_idx + 1].dropna()
                if len(inv_slice) > 0:
                    factors['institution_flow_5d'] = inv_slice.sum()

            # [16] 스마트 머니 (외인+기관 합산)
            f_flow = factors.get('foreign_flow_5d', 0) or 0
            i_flow = factors.get('institution_flow_5d', 0) or 0
            if f_flow != 0 or i_flow != 0:
                factors['smart_money_5d'] = f_flow + i_flow

            # [17] 뉴스 감성
            if code in (news_pivot.columns if not news_pivot.empty else []):
                news_slice = news_pivot[code].iloc[max(0, loc_idx - 5):loc_idx + 1].dropna()
                if len(news_slice) > 0:
                    factors['news_sentiment_5d'] = news_slice.mean()

            # --- 향후 수익률 ---
            fwd_rets = {}
            if rdate in fwd_5d.index and code in fwd_5d.columns:
                val = fwd_5d.loc[rdate, code]
                if not pd.isna(val):
                    fwd_rets['fwd_5d'] = val * 100
            if rdate in fwd_10d.index and code in fwd_10d.columns:
                val = fwd_10d.loc[rdate, code]
                if not pd.isna(val):
                    fwd_rets['fwd_10d'] = val * 100

            if fwd_rets:
                records.append({
                    'date': rdate,
                    'stock_code': code,
                    **factors,
                    **fwd_rets,
                })

    df_factors = pd.DataFrame(records)
    print(f"✅ 팩터 데이터: {len(df_factors):,}건 ({df_factors['stock_code'].nunique()}개 종목 × {len(rebal_dates)}회)")
    return df_factors


# ============================================================
# IC 분석 (Information Coefficient)
# ============================================================

def analyze_ic(df_factors):
    """각 팩터의 IC(Spearman rank correlation with forward returns) 계산"""

    factor_cols = [c for c in df_factors.columns
                   if c not in ('date', 'stock_code', 'fwd_5d', 'fwd_10d')]

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
            ir = ic_mean / ic_std if ic_std > 0 else 0  # Information Ratio
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


# ============================================================
# Quintile 분석 (상위/하위 20% 수익률 비교)
# ============================================================

def analyze_quintiles(df_factors):
    """팩터 상위 20% vs 하위 20% 향후 수익률 비교"""

    factor_cols = [c for c in df_factors.columns
                   if c not in ('date', 'stock_code', 'fwd_5d', 'fwd_10d')]

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
                'top20_ret': round(top_avg, 2),
                'bot20_ret': round(bot_avg, 2),
                'spread': round(spread, 2),
                'spread_ir': round(spread_ir, 3),
                'n_periods': len(top_rets),
            })

    return pd.DataFrame(results)


# ============================================================
# 메인
# ============================================================

def main():
    init_engine()

    with session_scope(readonly=True) as session:
        df_price, df_inv, df_news, name_map, cap_map = load_all_data(session)

    # 팩터 계산
    df_factors = compute_all_factors(df_price, df_inv, df_news, cap_map)

    if df_factors.empty:
        print("❌ 팩터 데이터가 없습니다.")
        return

    # IC 분석
    print("\n" + "=" * 90)
    print("📊 Factor IC Analysis (Spearman Rank Correlation with Forward Returns)")
    print("=" * 90)
    print("  IC > 0: 팩터 값이 높을수록 향후 수익률 높음")
    print("  |IR| > 0.5: 일반적으로 유의미한 팩터")
    print("  IC Positive %: IC가 양수인 기간 비율 (>50% = 일관성)")
    print()

    ic_results = analyze_ic(df_factors)

    for fwd_col in ['fwd_5d', 'fwd_10d']:
        subset = ic_results[ic_results['forward'] == fwd_col].sort_values('ir', ascending=False)
        days = fwd_col.replace('fwd_', '').replace('d', '')

        print(f"  ┌─ Forward {days}D Returns ──────────────────────────────────────────────────┐")
        print(f"  │ {'팩터':26s} │ {'IC평균':>7s} │ {'IC표준편차':>8s} │ {'IR':>6s} │ {'IC+비율':>7s} │ {'기간':>4s} │")
        print(f"  ├────────────────────────────┼─────────┼──────────┼────────┼─────────┼──────┤")

        for _, row in subset.iterrows():
            marker = ""
            if abs(row['ir']) >= 0.5:
                marker = " ★"
            elif abs(row['ir']) >= 0.3:
                marker = " ☆"
            print(f"  │ {row['factor']:26s} │ {row['ic_mean']:>+7.4f} │ {row['ic_std']:>8.4f} │ {row['ir']:>+6.3f} │ {row['ic_positive_pct']:>6.1f}% │ {row['n_periods']:>4d} │{marker}")

        print(f"  └────────────────────────────┴─────────┴──────────┴────────┴─────────┴──────┘")
        print()

    # Quintile 분석
    print("=" * 90)
    print("📊 Quintile Analysis (Top 20% vs Bottom 20% Average Forward Return)")
    print("=" * 90)
    print("  Spread > 0: 팩터 상위 종목이 하위 종목 대비 초과 수익")
    print("  |Spread IR| > 0.5: 일관적으로 유의미한 Long-Short 수익")
    print()

    q_results = analyze_quintiles(df_factors)

    for fwd_col in ['fwd_5d', 'fwd_10d']:
        subset = q_results[q_results['forward'] == fwd_col].sort_values('spread', ascending=False)
        days = fwd_col.replace('fwd_', '').replace('d', '')

        print(f"  ┌─ Forward {days}D Returns ──────────────────────────────────────────────────────────┐")
        print(f"  │ {'팩터':26s} │ {'Top20%':>7s} │ {'Bot20%':>7s} │ {'Spread':>7s} │ {'SpreadIR':>8s} │ {'기간':>4s} │")
        print(f"  ├────────────────────────────┼─────────┼─────────┼─────────┼──────────┼──────┤")

        for _, row in subset.iterrows():
            marker = ""
            if abs(row['spread_ir']) >= 0.5:
                marker = " ★"
            elif abs(row['spread_ir']) >= 0.3:
                marker = " ☆"
            print(f"  │ {row['factor']:26s} │ {row['top20_ret']:>+6.2f}% │ {row['bot20_ret']:>+6.2f}% │ {row['spread']:>+6.2f}% │ {row['spread_ir']:>+8.3f} │ {row['n_periods']:>4d} │{marker}")

        print(f"  └────────────────────────────┴─────────┴─────────┴─────────┴──────────┴──────┘")
        print()

    # ============================================================
    # 핵심 인사이트
    # ============================================================
    print("=" * 90)
    print("💡 알파 팩터 인사이트 요약")
    print("=" * 90)

    # IC 기준 상위 팩터
    for fwd_col in ['fwd_5d', 'fwd_10d']:
        days = fwd_col.replace('fwd_', '').replace('d', '')
        subset = ic_results[ic_results['forward'] == fwd_col].sort_values('ir', ascending=False)
        strong = subset[subset['ir'].abs() >= 0.3]

        if not strong.empty:
            print(f"\n  [Forward {days}D] 유의미한 팩터 (|IR| ≥ 0.3):")
            for _, row in strong.iterrows():
                direction = "높을수록 ↑" if row['ic_mean'] > 0 else "낮을수록 ↑"
                print(f"    • {row['factor']:25s}  IC={row['ic_mean']:+.4f}  IR={row['ir']:+.3f}  ({direction})")
        else:
            print(f"\n  [Forward {days}D] |IR| ≥ 0.3인 팩터 없음 (데이터 기간 짧음)")

    # Long-Short 기준 상위 팩터
    print()
    for fwd_col in ['fwd_5d', 'fwd_10d']:
        days = fwd_col.replace('fwd_', '').replace('d', '')
        subset = q_results[q_results['forward'] == fwd_col].sort_values('spread', ascending=False)
        top3 = subset.head(3)

        if not top3.empty:
            print(f"  [Forward {days}D] Long-Short Spread 상위 3개:")
            for _, row in top3.iterrows():
                print(f"    • {row['factor']:25s}  Top20%={row['top20_ret']:+.2f}%  Bot20%={row['bot20_ret']:+.2f}%  "
                      f"Spread={row['spread']:+.2f}%")

    print()


if __name__ == '__main__':
    main()
