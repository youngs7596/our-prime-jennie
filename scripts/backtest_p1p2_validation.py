"""
P1+P2 패치 검증 백테스트
- Watchlist 4주: 기존 hybrid 점수 vs P1 패치 quant 점수 비교
- P1 패치: Recon Protection 강화, 고점+과열 감점, 수급 반전
- 평가: forward return (D+5, D+10) 과의 IC 비교

접근:
  WATCHLIST_HISTORY에 quant/LLM 분리 점수가 없으므로,
  간이 팩터(backtest_grid.py 방식) + P1 패치 보정으로 quant 재계산.
  stored hybrid vs new_quant vs forward returns IC 비교.

사용법: .venv/bin/python scripts/backtest_p1p2_validation.py
"""
import os
import sys
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from scipy import stats

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from shared.db.connection import init_engine, session_scope
from shared.db.models import (
    StockDailyPrice, StockInvestorTrading, WatchlistHistory,
    StockNewsSentiment, FinancialMetricsQuarterly,
)

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


# ============================================================
# 간이 팩터 계산 (backtest_grid.py 방식)
# ============================================================
def calc_rsi(close_arr, period=14):
    if len(close_arr) < period + 1:
        return None
    deltas = np.diff(close_arr[-(period + 1):])
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains)
    avg_loss = np.mean(losses)
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))


def compute_base_score(closes, volumes, highs, foreign_series, fin, news_5d_val):
    """BASELINE 가중치 기반 간이 팩터 점수 (0~100 스케일)"""
    if len(closes) < 25:
        return None, {}

    # 가중치 (BASELINE)
    weights = {'momentum': 25, 'quality': 20, 'value': 15, 'technical': 10, 'news': 15, 'supply_demand': 15}

    factors = {}

    # Momentum (0~1)
    if len(closes) >= 120:
        ret_6m = closes[-1] / closes[-120] - 1
        factors['momentum'] = np.clip(0.5 + ret_6m, 0, 1)
    else:
        factors['momentum'] = 0.5

    # Quality (0~1)
    if fin and fin.get('roe') is not None:
        factors['quality'] = np.clip(fin['roe'] / 40.0, 0, 1)
    else:
        factors['quality'] = 0.5

    # Value (0~1)
    if fin and fin.get('pbr') is not None and fin['pbr'] > 0:
        factors['value'] = np.clip(1.0 / fin['pbr'] / 3.0, 0, 1)
    elif fin and fin.get('per') is not None and fin['per'] > 0:
        factors['value'] = np.clip(15.0 / fin['per'], 0, 1)
    else:
        factors['value'] = 0.5

    # Technical (0~1): 과매도=높은점수
    rsi = calc_rsi(closes)
    if rsi is not None:
        factors['technical'] = np.clip(1 - rsi / 100, 0, 1)
    else:
        rsi = 50.0
        factors['technical'] = 0.5

    # News (0~1)
    if news_5d_val is not None and not np.isnan(news_5d_val):
        factors['news'] = np.clip((news_5d_val + 100) / 200, 0, 1)
    else:
        factors['news'] = 0.5

    # Supply/Demand (0~1)
    avg_vol = np.mean(volumes[-20:]) if len(volumes) >= 20 else np.mean(volumes) if len(volumes) > 0 else 1
    if foreign_series is not None and len(foreign_series) >= 1:
        foreign_1d = float(foreign_series[-1])
    else:
        foreign_1d = 0
    if avg_vol > 0:
        ratio_1d = foreign_1d / avg_vol
        factors['supply_demand'] = np.clip(0.5 + ratio_1d / 0.10, 0, 1)
    else:
        factors['supply_demand'] = 0.5

    # 기본 점수
    base_score = sum(factors[k] * weights[k] for k in weights)

    # 추가 정보
    mom_1m = (closes[-1] / closes[-20] - 1) * 100 if len(closes) >= 20 else 0
    mom_6m = (closes[-1] / closes[-120] - 1) * 100 if len(closes) >= 120 else 0

    details = {
        'rsi': rsi,
        'mom_1m': mom_1m,
        'mom_6m': mom_6m,
        'base_score': base_score,
        'factors': factors,
    }

    return base_score, details


def apply_p1_patches(base_score, details, closes, highs, foreign_series):
    """P1 패치를 적용한 점수 계산"""
    rsi = details.get('rsi', 50)
    mom_6m = details.get('mom_6m', 0)
    mom_1m = details.get('mom_1m', 0)
    patches = {'recon': 0.0, 'peak_heat': 0.0, 'flow_reversal': 0.0}

    # P1-2: Recon Protection 해제로 인한 감점
    # RSI 60-70이고 강한 모멘텀인 종목은 기존에 RSI 감점이 면제되었으나 이제는 감점
    if 60 <= rsi <= 70 and mom_6m >= 20:
        patches['recon'] = -1.0
    elif 50 <= rsi < 60 and mom_6m >= 20 and mom_1m <= 0:
        patches['recon'] = -0.5

    # P1-3: 고점 근접 + RSI 과열 감점
    if len(highs) >= 20 and rsi is not None:
        peak_20d = highs[-20:].max()
        current = closes[-1]
        drawdown = (current - peak_20d) / peak_20d * 100

        if drawdown > -3 and rsi > 70:
            patches['peak_heat'] = -1.5
        elif drawdown > -2 and rsi > 65:
            patches['peak_heat'] = -1.0

    # P1-4: 수급 추세 반전
    if foreign_series is not None and len(foreign_series) >= 10:
        prev_5d = foreign_series[-10:-5].sum()
        recent_5d = foreign_series[-5:].sum()

        if prev_5d > 0 and recent_5d < 0:
            patches['flow_reversal'] = -2.0
        elif prev_5d < 0 and recent_5d > 0:
            patches['flow_reversal'] = 1.5

    total_delta = sum(patches.values())
    patched_score = max(0, base_score + total_delta)

    return patched_score, patches, total_delta


# ============================================================
# 데이터 로드
# ============================================================
def load_all_data(session, start_date, end_date):
    data_start = start_date - timedelta(days=180)

    # Watchlist History
    wh_rows = session.query(
        WatchlistHistory.snapshot_date,
        WatchlistHistory.stock_code,
        WatchlistHistory.stock_name,
        WatchlistHistory.llm_score,
        WatchlistHistory.is_tradable,
    ).filter(
        WatchlistHistory.snapshot_date >= start_date,
        WatchlistHistory.snapshot_date <= end_date,
    ).all()

    df_wh = pd.DataFrame(wh_rows, columns=['date', 'code', 'name', 'hybrid_score', 'is_tradable'])
    df_wh['date'] = pd.to_datetime(df_wh['date'])
    df_wh['hybrid_score'] = df_wh['hybrid_score'].astype(float)

    target_codes = set(df_wh['code'].unique())
    print(f"Watchlist: {len(df_wh)}건, {len(target_codes)}개 종목, {df_wh['date'].nunique()}일")

    # 가격 (high 포함)
    prices = session.query(
        StockDailyPrice.stock_code,
        StockDailyPrice.price_date,
        StockDailyPrice.high_price,
        StockDailyPrice.close_price,
        StockDailyPrice.volume,
    ).filter(
        StockDailyPrice.price_date >= data_start,
        StockDailyPrice.stock_code.in_(target_codes),
    ).order_by(
        StockDailyPrice.stock_code, StockDailyPrice.price_date,
    ).all()

    df_price = pd.DataFrame(prices, columns=['code', 'date', 'high', 'close', 'volume'])
    df_price['date'] = pd.to_datetime(df_price['date'])

    # 수급
    inv_rows = session.query(
        StockInvestorTrading.stock_code,
        StockInvestorTrading.trade_date,
        StockInvestorTrading.foreign_net_buy,
    ).filter(
        StockInvestorTrading.trade_date >= data_start,
        StockInvestorTrading.stock_code.in_(target_codes),
    ).all()

    df_inv = pd.DataFrame(inv_rows, columns=['code', 'date', 'foreign_net'])
    df_inv['date'] = pd.to_datetime(df_inv['date'])
    df_inv['foreign_net'] = df_inv['foreign_net'].astype(float)

    # 뉴스
    news_rows = session.query(
        StockNewsSentiment.stock_code,
        StockNewsSentiment.news_date,
        StockNewsSentiment.sentiment_score,
    ).filter(
        StockNewsSentiment.news_date >= data_start,
        StockNewsSentiment.stock_code.in_(target_codes),
    ).all()
    df_news = pd.DataFrame(news_rows, columns=['code', 'date', 'sentiment'])
    df_news['date'] = pd.to_datetime(df_news['date'])
    df_news['sentiment'] = df_news['sentiment'].astype(float)

    # 재무
    fin_rows = session.query(
        FinancialMetricsQuarterly.stock_code,
        FinancialMetricsQuarterly.roe,
        FinancialMetricsQuarterly.per,
        FinancialMetricsQuarterly.pbr,
    ).filter(
        FinancialMetricsQuarterly.stock_code.in_(target_codes),
    ).order_by(
        FinancialMetricsQuarterly.stock_code,
        FinancialMetricsQuarterly.quarter_date.desc(),
    ).all()
    fin_map = {}
    for row in fin_rows:
        if row.stock_code not in fin_map:
            fin_map[row.stock_code] = {
                'roe': float(row.roe) if row.roe is not None else None,
                'per': float(row.per) if row.per is not None else None,
                'pbr': float(row.pbr) if row.pbr is not None else None,
            }

    print(f"가격: {len(df_price):,}건, 수급: {len(df_inv):,}건, 뉴스: {len(df_news):,}건, 재무: {len(fin_map)}개")

    return df_wh, df_price, df_inv, df_news, fin_map


# ============================================================
# 메인
# ============================================================
def main():
    start_date = datetime(2026, 1, 11).date()
    end_date = datetime(2026, 2, 7).date()

    print(f"\n{'='*100}")
    print(f"  P1+P2 패치 검증 백테스트 ({start_date} ~ {end_date})")
    print(f"{'='*100}")

    init_engine()

    with session_scope(readonly=True) as session:
        df_wh, df_price, df_inv, df_news, fin_map = load_all_data(
            session, start_date, end_date
        )

    # Pivot tables
    pivot_close = df_price.pivot_table(index='date', columns='code', values='close', aggfunc='last').sort_index()
    pivot_high = df_price.pivot_table(index='date', columns='code', values='high', aggfunc='max').sort_index()
    pivot_volume = df_price.pivot_table(index='date', columns='code', values='volume', aggfunc='sum').sort_index()
    inv_foreign = df_inv.pivot_table(index='date', columns='code', values='foreign_net', aggfunc='sum')

    if len(df_news) > 0:
        news_pivot = df_news.pivot_table(index='date', columns='code', values='sentiment', aggfunc='mean')
        news_5d = news_pivot.rolling(5, min_periods=1).mean()
    else:
        news_5d = pd.DataFrame()

    # Forward returns
    fwd_5d = pivot_close.pct_change(5).shift(-5) * 100
    fwd_10d = pivot_close.pct_change(10).shift(-10) * 100

    # 각 watchlist 항목에 대해 점수 계산
    results = []

    for _, row in df_wh.iterrows():
        code = row['code']
        as_of = row['date']

        if code not in pivot_close.columns:
            continue

        # as_of 이전 데이터
        mask = pivot_close.index <= as_of
        close_series = pivot_close.loc[mask, code].dropna()
        if len(close_series) < 25:
            continue

        closes = close_series.values.astype(float)
        high_series = pivot_high.loc[mask, code].dropna() if code in pivot_high.columns else pd.Series(dtype=float)
        highs = high_series.values.astype(float) if len(high_series) > 0 else closes
        vol_series = pivot_volume.loc[mask, code].dropna() if code in pivot_volume.columns else pd.Series(dtype=float)
        volumes = vol_series.values.astype(float) if len(vol_series) > 0 else np.ones(len(closes))

        # 외인 수급
        foreign = None
        if code in inv_foreign.columns:
            f_mask = inv_foreign.index <= as_of
            f_series = inv_foreign.loc[f_mask, code].dropna()
            if len(f_series) > 0:
                foreign = f_series.values.astype(float)

        # 뉴스 감성
        ns5d = None
        if len(news_5d) > 0 and code in news_5d.columns and as_of in news_5d.index:
            v = news_5d.loc[as_of, code]
            if not pd.isna(v):
                ns5d = float(v)

        fin = fin_map.get(code)

        # 기본 팩터 점수 (P1 전)
        base_score, details = compute_base_score(closes, volumes, highs, foreign, fin, ns5d)
        if base_score is None:
            continue

        # P1 패치 적용
        patched_score, patches, p1_delta = apply_p1_patches(
            base_score, details, closes, highs, foreign
        )

        # Forward returns
        f5, f10 = None, None
        # as_of와 가장 가까운 거래일
        matched = fwd_5d.index[fwd_5d.index >= as_of]
        if len(matched) > 0 and code in fwd_5d.columns:
            base_td = matched[0]
            v5 = fwd_5d.loc[base_td, code]
            if not pd.isna(v5):
                f5 = float(v5)
            if code in fwd_10d.columns and base_td in fwd_10d.index:
                v10 = fwd_10d.loc[base_td, code]
                if not pd.isna(v10):
                    f10 = float(v10)

        results.append({
            'date': as_of,
            'code': code,
            'name': row['name'],
            'stored_hybrid': row['hybrid_score'],
            'is_tradable_stored': int(row.get('is_tradable', 0)),
            'quant_base': base_score,
            'quant_patched': patched_score,
            'p1_recon': patches['recon'],
            'p1_peak_heat': patches['peak_heat'],
            'p1_flow': patches['flow_reversal'],
            'p1_total': p1_delta,
            'rsi': details.get('rsi'),
            'mom_1m': details.get('mom_1m'),
            'mom_6m': details.get('mom_6m'),
            'fwd_5d': f5,
            'fwd_10d': f10,
        })

    df = pd.DataFrame(results)
    df_eval = df[df['fwd_5d'].notna()].copy()

    print(f"\n분석 대상: {len(df_eval)}건 (fwd 있음) / {len(df)}건 (전체)")

    if len(df_eval) < 5:
        print("분석 대상이 너무 적습니다.")
        return

    # ============================================================
    # 결과 출력
    # ============================================================

    # A. 점수 분포
    print(f"\n{'='*100}")
    print("  [A] 점수 분포 비교")
    print(f"{'='*100}")
    print(f"  {'':20s} {'평균':>8s} {'중앙값':>8s} {'Std':>8s} {'Min':>8s} {'Max':>8s}")
    print(f"  {'─'*55}")
    for label, col in [('Stored Hybrid', 'stored_hybrid'), ('Quant Base', 'quant_base'), ('Quant Patched', 'quant_patched')]:
        s = df_eval[col]
        print(f"  {label:20s} {s.mean():>8.1f} {s.median():>8.1f} {s.std():>8.1f} {s.min():>8.1f} {s.max():>8.1f}")

    # B. P1 패치 영향
    print(f"\n{'='*100}")
    print("  [B] P1 패치 영향")
    print(f"{'='*100}")
    patched_count = (df_eval['p1_total'] != 0).sum()
    print(f"  P1 패치 적용: {patched_count}/{len(df_eval)}건 ({patched_count/len(df_eval)*100:.0f}%)")
    print(f"  평균 델타: {df_eval['p1_total'].mean():+.3f}점")

    for label, col in [('Recon 해제', 'p1_recon'), ('Peak+Heat', 'p1_peak_heat'), ('Flow Reversal', 'p1_flow')]:
        affected = (df_eval[col] != 0).sum()
        if affected > 0:
            avg = df_eval[df_eval[col] != 0][col].mean()
            # 이 패치가 적용된 종목의 D+5
            sub = df_eval[df_eval[col] != 0]
            fwd_avg = sub['fwd_5d'].mean()
            print(f"    {label:15s}: {affected}건, 평균 {avg:+.2f}점 → 대상 종목 D+5: {fwd_avg:+.2f}%")
        else:
            print(f"    {label:15s}: 0건")

    # P1 패치 방향 검증: 감점 적용된 종목이 실제로 하락했는가?
    p1_negative = df_eval[df_eval['p1_total'] < 0]
    p1_positive = df_eval[df_eval['p1_total'] > 0]
    if len(p1_negative) > 0:
        print(f"\n  ★ 감점 종목(P1<0) D+5: 평균 {p1_negative['fwd_5d'].mean():+.2f}% (N={len(p1_negative)})")
        print(f"    히트율: {(p1_negative['fwd_5d'] > 0).mean():.1%}")
    if len(p1_positive) > 0:
        print(f"  ★ 가점 종목(P1>0) D+5: 평균 {p1_positive['fwd_5d'].mean():+.2f}% (N={len(p1_positive)})")
        print(f"    히트율: {(p1_positive['fwd_5d'] > 0).mean():.1%}")
    p1_zero = df_eval[df_eval['p1_total'] == 0]
    if len(p1_zero) > 0:
        print(f"  ★ 무변동 종목(P1=0) D+5: 평균 {p1_zero['fwd_5d'].mean():+.2f}% (N={len(p1_zero)})")

    # C. IC 비교
    print(f"\n{'='*100}")
    print("  [C] 예측력 비교 (IC = Spearman Rank Correlation)")
    print(f"{'='*100}")

    for horizon, col in [('D+5', 'fwd_5d'), ('D+10', 'fwd_10d')]:
        valid = df_eval[['stored_hybrid', 'quant_base', 'quant_patched', col]].dropna()
        if len(valid) < 10:
            print(f"  {horizon}: 데이터 부족 ({len(valid)}건)")
            continue

        ic_hybrid, p_h = stats.spearmanr(valid['stored_hybrid'], valid[col])
        ic_base, p_b = stats.spearmanr(valid['quant_base'], valid[col])
        ic_patched, p_p = stats.spearmanr(valid['quant_patched'], valid[col])

        print(f"\n  [{horizon}] N={len(valid)}")
        print(f"  {'Score':20s} {'IC':>8s} {'p-value':>10s}")
        print(f"  {'─'*40}")
        print(f"  {'Stored Hybrid':20s} {ic_hybrid:>+8.4f} {p_h:>10.4f}")
        print(f"  {'Quant Base':20s} {ic_base:>+8.4f} {p_b:>10.4f}")
        print(f"  {'Quant Patched(P1)':20s} {ic_patched:>+8.4f} {p_p:>10.4f}")

        improve = ic_patched - ic_base
        vs_hybrid = ic_patched - ic_hybrid
        print(f"  → P1 패치 효과: {improve:+.4f} (base 대비)")
        print(f"  → Stored Hybrid 대비: {vs_hybrid:+.4f}")

    # D. 날짜별 IC 추이
    print(f"\n{'='*100}")
    print("  [D] 날짜별 IC 추이 (D+5)")
    print(f"{'='*100}")

    daily_ics = []
    for date, group in df_eval.groupby('date'):
        valid = group[['stored_hybrid', 'quant_base', 'quant_patched', 'fwd_5d']].dropna()
        if len(valid) < 5:
            continue
        ic_h, _ = stats.spearmanr(valid['stored_hybrid'], valid['fwd_5d'])
        ic_b, _ = stats.spearmanr(valid['quant_base'], valid['fwd_5d'])
        ic_p, _ = stats.spearmanr(valid['quant_patched'], valid['fwd_5d'])
        daily_ics.append({'date': date, 'ic_hybrid': ic_h, 'ic_base': ic_b, 'ic_patched': ic_p, 'n': len(valid)})

    if daily_ics:
        df_ic = pd.DataFrame(daily_ics)
        print(f"  {'날짜':>12s} {'IC(Hybrid)':>10s} {'IC(Base)':>10s} {'IC(Patched)':>11s} {'P1효과':>8s} {'N':>4s}")
        print(f"  {'─'*60}")
        for _, r in df_ic.iterrows():
            diff = r['ic_patched'] - r['ic_base']
            print(f"  {r['date'].strftime('%Y-%m-%d'):>12s} {r['ic_hybrid']:>+10.4f} {r['ic_base']:>+10.4f} {r['ic_patched']:>+10.4f} {diff:>+8.4f} {r['n']:>4.0f}")

        print(f"\n  평균 IC: Hybrid={df_ic['ic_hybrid'].mean():+.4f}, Base={df_ic['ic_base'].mean():+.4f}, Patched={df_ic['ic_patched'].mean():+.4f}")
        better = (df_ic['ic_patched'] > df_ic['ic_base']).sum()
        print(f"  P1 개선일: {better}/{len(df_ic)}일")

    # E. 구간별 수익률
    print(f"\n{'='*100}")
    print("  [E] 점수 상위/하위 종목 D+5 수익률")
    print(f"{'='*100}")

    for label, col in [('Stored Hybrid', 'stored_hybrid'), ('Quant Patched', 'quant_patched')]:
        valid = df_eval[[col, 'fwd_5d']].dropna()
        if len(valid) < 10:
            continue

        q75 = valid[col].quantile(0.75)
        q25 = valid[col].quantile(0.25)
        top = valid[valid[col] >= q75]['fwd_5d']
        bot = valid[valid[col] <= q25]['fwd_5d']

        print(f"\n  [{label}]")
        print(f"    상위 25% (>={q75:.1f}): 평균 {top.mean():+.2f}%, 히트율 {(top > 0).mean():.1%} (N={len(top)})")
        print(f"    하위 25% (<={q25:.1f}): 평균 {bot.mean():+.2f}%, 히트율 {(bot > 0).mean():.1%} (N={len(bot)})")
        print(f"    Spread: {top.mean() - bot.mean():+.2f}%p")

    # F. 가장 큰 패치 영향 종목 (D+5 포함)
    print(f"\n{'='*100}")
    print("  [F] P1 패치 영향 상위 종목 상세")
    print(f"{'='*100}")

    df_patched = df_eval[df_eval['p1_total'] != 0].sort_values('p1_total')
    if len(df_patched) > 0:
        print(f"  {'날짜':>10s} {'종목':>12s} {'RSI':>5s} {'Base':>6s} {'Patched':>7s} {'P1':>6s} {'구분':>12s} {'D+5':>7s}")
        print(f"  {'─'*75}")
        for _, r in df_patched.head(20).iterrows():
            parts = []
            if r['p1_recon'] != 0: parts.append(f"Recon{r['p1_recon']:+.1f}")
            if r['p1_peak_heat'] != 0: parts.append(f"PH{r['p1_peak_heat']:+.1f}")
            if r['p1_flow'] != 0: parts.append(f"Flow{r['p1_flow']:+.1f}")
            patch_detail = ','.join(parts)

            fwd_str = f"{r['fwd_5d']:+.1f}%" if not pd.isna(r['fwd_5d']) else "N/A"
            print(f"  {r['date'].strftime('%m-%d'):>10s} {r['name'][:12]:>12s} {r['rsi']:>5.0f} "
                  f"{r['quant_base']:>6.1f} {r['quant_patched']:>7.1f} {r['p1_total']:>+5.1f} "
                  f"{patch_detail:>12s} {fwd_str:>7s}")

    # G. 요약
    print(f"\n{'='*100}")
    print("  [G] 종합 결론")
    print(f"{'='*100}")

    # 전체 IC 비교
    valid_all = df_eval[['stored_hybrid', 'quant_base', 'quant_patched', 'fwd_5d']].dropna()
    if len(valid_all) >= 10:
        ic_h, _ = stats.spearmanr(valid_all['stored_hybrid'], valid_all['fwd_5d'])
        ic_b, _ = stats.spearmanr(valid_all['quant_base'], valid_all['fwd_5d'])
        ic_p, _ = stats.spearmanr(valid_all['quant_patched'], valid_all['fwd_5d'])

        print(f"  전체 IC(D+5): Stored Hybrid={ic_h:+.4f}, Quant Base={ic_b:+.4f}, Quant Patched={ic_p:+.4f}")
        if ic_p > ic_b:
            print(f"  → P1 패치가 quant 예측력을 {ic_p - ic_b:+.4f} 개선")
        else:
            print(f"  → P1 패치 효과 미미 또는 악화 ({ic_p - ic_b:+.4f})")

        # 감점 종목의 적중률
        neg = df_eval[df_eval['p1_total'] < 0]
        if len(neg) >= 3:
            neg_hit = (neg['fwd_5d'] < 0).mean()
            print(f"  → P1 감점 종목 중 실제 하락: {neg_hit:.1%} (N={len(neg)}) — 50% 초과면 효과적")

    # CSV 저장
    output_dir = os.path.join(os.path.dirname(__file__), 'output')
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M')
    csv_path = os.path.join(output_dir, f'backtest_p1p2_validation_{ts}.csv')
    df.to_csv(csv_path, index=False, encoding='utf-8-sig')
    print(f"\n  CSV: {csv_path}")


if __name__ == '__main__':
    main()
