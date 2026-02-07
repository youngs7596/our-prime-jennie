"""
Grid Backtest: 6개 팩터 가중치 × SM보너스 × RSI × Compound 보너스 그리드 탐색

4차원 그리드 (총 216조합):
  - Dim 1: 팩터 가중치 프로필 (8가지, 합계=100)
  - Dim 2: Smart Money 5D 보너스 (3가지: OFF / CURRENT / AGGRESSIVE)
  - Dim 3: RSI 과매도 기준 (3가지: 25 / 30 / 35)
  - Dim 4: Compound Bonus RSI+외인 (3가지: OFF / CURRENT / STRONG)

Phase 1: 전종목 2개월 (2025-12-01 ~ 2026-02-06)
Phase 2: Watchlist 4주 (2026-01-11 ~ 2026-02-06)

사용법:
    .venv/bin/python scripts/backtest_grid.py --phase 1
    .venv/bin/python scripts/backtest_grid.py --phase 2
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import argparse
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from itertools import product
from scipy import stats

from shared.db.connection import init_engine, session_scope
from shared.db.models import (
    StockDailyPrice, StockMaster, StockInvestorTrading,
    StockNewsSentiment, WatchlistHistory, FinancialMetricsQuarterly,
)

# ============================================================
# 상수
# ============================================================
MIN_MARKET_CAP = 3000_0000_0000  # 3,000억
ABNORMAL_DAILY_CHANGE_PCT = 50.0
REBAL_INTERVAL = 5  # 5거래일 리밸런싱

# ============================================================
# Dim 1: 팩터 가중치 프로필 (합계=100)
# ============================================================
WEIGHT_PROFILES = {
    'BASELINE':      {'momentum': 25, 'quality': 20, 'value': 15, 'technical': 10, 'news': 15, 'supply_demand': 15},
    'SUPPLY_HEAVY':  {'momentum': 15, 'quality': 15, 'value': 10, 'technical': 10, 'news': 10, 'supply_demand': 40},
    'QUALITY_VALUE': {'momentum': 15, 'quality': 30, 'value': 25, 'technical': 10, 'news': 10, 'supply_demand': 10},
    'TECH_MOMENTUM': {'momentum': 35, 'quality': 10, 'value': 10, 'technical': 25, 'news': 10, 'supply_demand': 10},
    'NEWS_DRIVEN':   {'momentum': 15, 'quality': 15, 'value': 10, 'technical': 10, 'news': 35, 'supply_demand': 15},
    'BALANCED':      {'momentum': 17, 'quality': 17, 'value': 17, 'technical': 17, 'news': 16, 'supply_demand': 16},
    'MINIMAL_6':     {'momentum':  5, 'quality':  5, 'value':  5, 'technical': 35, 'news': 10, 'supply_demand': 40},
    'TOP3_EQUAL':    {'momentum': 30, 'quality':  5, 'value':  5, 'technical':  5, 'news': 25, 'supply_demand': 30},
}

# Dim 2: Smart Money 5D 보너스
SM_BONUS_CONFIGS = {
    'OFF':        {'threshold': None, 'max_bonus': 0},
    'CURRENT':    {'threshold': 0.02, 'max_bonus': 3},
    'AGGRESSIVE': {'threshold': 0.01, 'max_bonus': 5},
}

# Dim 3: RSI 과매도 기준
RSI_THRESHOLDS = [25, 30, 35]

# Dim 4: Compound Bonus (RSI 과매도 + 외인 순매수)
COMPOUND_CONFIGS = {
    'OFF':     0,
    'CURRENT': 5,
    'STRONG':  8,
}


# ============================================================
# 데이터 로드
# ============================================================
def load_phase1_data(session, start_date, end_date):
    """Phase 1: 전종목 가격 + 수급 + 뉴스 + 재무 데이터 로드"""
    # 팩터 계산 워밍업을 위해 데이터를 start_date 보다 120일 전부터 로드
    data_start = start_date - timedelta(days=180)

    # 종목 마스터
    masters = session.query(
        StockMaster.stock_code, StockMaster.stock_name, StockMaster.market_cap
    ).filter(StockMaster.market_cap >= MIN_MARKET_CAP).all()
    target_codes = {m.stock_code for m in masters}
    name_map = {m.stock_code: m.stock_name for m in masters}
    print(f"시총 >= 3,000억: {len(target_codes)}개 종목")

    # 가격
    prices = session.query(
        StockDailyPrice.stock_code,
        StockDailyPrice.price_date,
        StockDailyPrice.close_price,
        StockDailyPrice.volume,
    ).filter(
        StockDailyPrice.price_date >= data_start,
        StockDailyPrice.stock_code.in_(target_codes),
    ).order_by(
        StockDailyPrice.stock_code, StockDailyPrice.price_date,
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
        print(f"비정상 변동 제외: {len(abnormal)}개")

    print(f"가격: {len(df_price):,}건, {df_price['stock_code'].nunique()}개 종목")

    # 수급
    inv_rows = session.query(
        StockInvestorTrading.stock_code,
        StockInvestorTrading.trade_date,
        StockInvestorTrading.foreign_net_buy,
        StockInvestorTrading.institution_net_buy,
    ).filter(
        StockInvestorTrading.trade_date >= data_start,
        StockInvestorTrading.stock_code.in_(target_codes),
    ).all()

    df_inv = pd.DataFrame(inv_rows, columns=['stock_code', 'date', 'foreign_net', 'institution_net'])
    df_inv['date'] = pd.to_datetime(df_inv['date'])
    df_inv['foreign_net'] = df_inv['foreign_net'].astype(float)
    df_inv['institution_net'] = df_inv['institution_net'].astype(float)
    print(f"수급: {len(df_inv):,}건")

    # 뉴스 감성
    news_rows = session.query(
        StockNewsSentiment.stock_code,
        StockNewsSentiment.news_date,
        StockNewsSentiment.sentiment_score,
    ).filter(
        StockNewsSentiment.news_date >= data_start,
        StockNewsSentiment.stock_code.in_(target_codes),
    ).all()

    df_news = pd.DataFrame(news_rows, columns=['stock_code', 'date', 'sentiment'])
    df_news['date'] = pd.to_datetime(df_news['date'])
    df_news['sentiment'] = df_news['sentiment'].astype(float)
    print(f"뉴스: {len(df_news):,}건")

    # 재무 (최신 ROE, PER, PBR)
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

    # 종목당 최신 재무 데이터만 사용
    fin_map = {}
    for row in fin_rows:
        if row.stock_code not in fin_map:
            fin_map[row.stock_code] = {
                'roe': float(row.roe) if row.roe is not None else None,
                'per': float(row.per) if row.per is not None else None,
                'pbr': float(row.pbr) if row.pbr is not None else None,
            }
    print(f"재무: {len(fin_map)}개 종목")

    return df_price, df_inv, df_news, fin_map, name_map


def load_phase2_data(session, start_date, end_date):
    """Phase 2: Watchlist 종목만 로드"""
    data_start = start_date - timedelta(days=180)

    # Watchlist History
    wh_rows = session.query(
        WatchlistHistory.snapshot_date,
        WatchlistHistory.stock_code,
        WatchlistHistory.stock_name,
        WatchlistHistory.llm_score,
    ).filter(
        WatchlistHistory.snapshot_date >= start_date,
        WatchlistHistory.snapshot_date <= end_date,
    ).all()

    df_wh = pd.DataFrame(wh_rows, columns=['date', 'stock_code', 'stock_name', 'llm_score'])
    df_wh['date'] = pd.to_datetime(df_wh['date'])
    df_wh['llm_score'] = df_wh['llm_score'].astype(float)

    target_codes = set(df_wh['stock_code'].unique())
    name_map = dict(zip(df_wh['stock_code'], df_wh['stock_name']))
    print(f"Watchlist 종목: {len(target_codes)}개, 기간별 {len(df_wh):,}건")

    # 가격
    prices = session.query(
        StockDailyPrice.stock_code,
        StockDailyPrice.price_date,
        StockDailyPrice.close_price,
        StockDailyPrice.volume,
    ).filter(
        StockDailyPrice.price_date >= data_start,
        StockDailyPrice.stock_code.in_(target_codes),
    ).order_by(
        StockDailyPrice.stock_code, StockDailyPrice.price_date,
    ).all()

    df_price = pd.DataFrame(prices, columns=['stock_code', 'date', 'close', 'volume'])
    df_price['date'] = pd.to_datetime(df_price['date'])

    # 수급
    inv_rows = session.query(
        StockInvestorTrading.stock_code,
        StockInvestorTrading.trade_date,
        StockInvestorTrading.foreign_net_buy,
        StockInvestorTrading.institution_net_buy,
    ).filter(
        StockInvestorTrading.trade_date >= data_start,
        StockInvestorTrading.stock_code.in_(target_codes),
    ).all()

    df_inv = pd.DataFrame(inv_rows, columns=['stock_code', 'date', 'foreign_net', 'institution_net'])
    df_inv['date'] = pd.to_datetime(df_inv['date'])
    df_inv['foreign_net'] = df_inv['foreign_net'].astype(float)
    df_inv['institution_net'] = df_inv['institution_net'].astype(float)

    # 뉴스
    news_rows = session.query(
        StockNewsSentiment.stock_code,
        StockNewsSentiment.news_date,
        StockNewsSentiment.sentiment_score,
    ).filter(
        StockNewsSentiment.news_date >= data_start,
        StockNewsSentiment.stock_code.in_(target_codes),
    ).all()

    df_news = pd.DataFrame(news_rows, columns=['stock_code', 'date', 'sentiment'])
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

    print(f"가격: {len(df_price):,}건, 수급: {len(df_inv):,}건, 뉴스: {len(df_news):,}건")

    return df_price, df_inv, df_news, fin_map, name_map, df_wh


# ============================================================
# 팩터 계산 (종목/날짜별 1회, 모든 조합에서 재사용)
# ============================================================
def compute_factors_for_date(
    code, loc_idx, pivot_close, pivot_volume,
    inv_foreign, inv_institution, news_sentiment_5d,
    fin_map,
):
    """종목/날짜에 대한 간이 팩터 계산 (0~1 정규화). RSI 원값도 반환."""
    factors = {}

    close_series = pivot_close[code].iloc[:loc_idx + 1].dropna()
    if len(close_series) < 25:
        return None

    closes = close_series.values
    vol_series = pivot_volume[code].iloc[:loc_idx + 1].dropna()
    volumes = vol_series.values if len(vol_series) > 0 else np.array([1])

    # --- Momentum (0~1): 6M 수익률 기반 ---
    if len(closes) >= 120:
        ret_6m = closes[-1] / closes[-120] - 1
        factors['momentum'] = np.clip(0.5 + ret_6m, 0, 1)
    else:
        factors['momentum'] = 0.5

    # --- Quality (0~1): ROE 기반 ---
    fin = fin_map.get(code)
    if fin and fin.get('roe') is not None:
        factors['quality'] = np.clip(fin['roe'] / 40.0, 0, 1)
    else:
        factors['quality'] = 0.5

    # --- Value (0~1): PBR/PER 역수 기반 ---
    if fin and fin.get('pbr') is not None and fin['pbr'] > 0:
        # 낮은 PBR = 높은 가치 점수
        factors['value'] = np.clip(1.0 / fin['pbr'] / 3.0, 0, 1)
    elif fin and fin.get('per') is not None and fin['per'] > 0:
        factors['value'] = np.clip(15.0 / fin['per'], 0, 1)
    else:
        factors['value'] = 0.5

    # --- Technical (0~1): RSI 기반 — 과매도=높은점수 ---
    rsi_raw = 50.0  # default
    if len(closes) >= 15:
        deltas = np.diff(closes[-15:])
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)
        if avg_loss > 0:
            rsi_raw = 100 - (100 / (1 + avg_gain / avg_loss))
        else:
            rsi_raw = 100.0
        factors['technical'] = np.clip(1 - rsi_raw / 100, 0, 1)
    else:
        factors['technical'] = 0.5

    # --- News (0~1): 최근 5일 평균 감성 ---
    if news_sentiment_5d is not None and not np.isnan(news_sentiment_5d):
        # sentiment_score: -100 ~ +100 → 0~1
        factors['news'] = np.clip((news_sentiment_5d + 100) / 200, 0, 1)
    else:
        factors['news'] = 0.5

    # --- Supply/Demand (0~1): 1D (외인+기관)/avg_volume ---
    avg_vol = np.mean(volumes[-20:]) if len(volumes) >= 20 else (np.mean(volumes) if len(volumes) > 0 else None)

    inv_f_series = inv_foreign[code].iloc[:loc_idx + 1].dropna() if code in inv_foreign.columns else None
    inv_i_series = inv_institution[code].iloc[:loc_idx + 1].dropna() if code in inv_institution.columns else None

    foreign_1d = 0
    if inv_f_series is not None and len(inv_f_series) >= 1:
        foreign_1d = float(inv_f_series.iloc[-1])
    institution_1d = 0
    if inv_i_series is not None and len(inv_i_series) >= 1:
        institution_1d = float(inv_i_series.iloc[-1])

    net_1d = foreign_1d + institution_1d
    if avg_vol and avg_vol > 0:
        ratio_1d = net_1d / avg_vol
        factors['supply_demand'] = np.clip(0.5 + ratio_1d / 0.10, 0, 1)
    else:
        factors['supply_demand'] = np.clip(0.5 + net_1d / 10_000_000, 0, 1)

    # --- Smart Money 5D 누적 (보너스 계산용, 정규화하지 않음) ---
    sm_5d_ratio = 0.0
    if inv_f_series is not None and len(inv_f_series) >= 3:
        tail = min(5, len(inv_f_series))
        f_5d = float(inv_f_series.iloc[-tail:].sum())
        i_5d = float(inv_i_series.iloc[-tail:].sum()) if inv_i_series is not None and len(inv_i_series) >= tail else 0
        sm_5d = f_5d + i_5d
        if avg_vol and avg_vol > 0:
            sm_5d_ratio = sm_5d / avg_vol
        else:
            sm_5d_ratio = sm_5d / 50_000_000 if sm_5d != 0 else 0

    factors['_rsi_raw'] = rsi_raw
    factors['_sm_5d_ratio'] = sm_5d_ratio
    factors['_foreign_1d'] = foreign_1d

    return factors


# ============================================================
# 점수 계산 (조합별)
# ============================================================
def score_combination(factors, weight_profile, sm_config, rsi_threshold, compound_bonus_val):
    """하나의 조합에 대한 점수 계산"""
    weights = WEIGHT_PROFILES[weight_profile]

    # 기본 점수 = 가중합
    base_score = 0
    for key in ['momentum', 'quality', 'value', 'technical', 'news', 'supply_demand']:
        base_score += factors[key] * weights[key]

    # Smart Money 5D 보너스
    sm_bonus = 0
    sm_cfg = SM_BONUS_CONFIGS[sm_config]
    if sm_cfg['threshold'] is not None:
        sm_ratio = factors['_sm_5d_ratio']
        if sm_ratio > sm_cfg['threshold']:
            sm_bonus = min(sm_cfg['max_bonus'], sm_ratio / sm_cfg['threshold'] * sm_cfg['max_bonus'] / 2)
            sm_bonus = min(sm_bonus, sm_cfg['max_bonus'])

    # Compound 보너스: RSI 과매도 + 외인 순매수
    comp_bonus = 0
    if compound_bonus_val > 0:
        rsi_raw = factors['_rsi_raw']
        foreign_1d = factors['_foreign_1d']
        if rsi_raw < rsi_threshold and foreign_1d > 0:
            comp_bonus = compound_bonus_val

    return base_score + sm_bonus + comp_bonus


# ============================================================
# 모든 조합 생성
# ============================================================
def generate_all_combinations():
    """4차원 그리드의 모든 조합 생성"""
    combos = []
    for wp, sm, rsi, comp in product(
        WEIGHT_PROFILES.keys(),
        SM_BONUS_CONFIGS.keys(),
        RSI_THRESHOLDS,
        COMPOUND_CONFIGS.keys(),
    ):
        combos.append({
            'weight_profile': wp,
            'sm_bonus': sm,
            'rsi_threshold': rsi,
            'compound': comp,
            'label': f"{wp}|SM={sm}|RSI<{rsi}|CB={comp}",
        })
    return combos


# ============================================================
# Phase 1: 전종목 백테스트
# ============================================================
def run_phase1():
    """Phase 1: 전종목 2개월 그리드 백테스트"""
    start_date = datetime(2025, 12, 1).date()
    end_date = datetime(2026, 2, 6).date()

    print(f"\n{'='*100}")
    print(f"  Phase 1: 전종목 Grid Backtest ({start_date} ~ {end_date})")
    print(f"{'='*100}")

    init_engine()
    with session_scope(readonly=True) as session:
        df_price, df_inv, df_news, fin_map, name_map = load_phase1_data(
            session, start_date, end_date
        )

    # Pivot tables
    pivot_close = df_price.pivot(index='date', columns='stock_code', values='close').sort_index()
    pivot_volume = df_price.pivot(index='date', columns='stock_code', values='volume').sort_index()
    inv_foreign = df_inv.pivot_table(index='date', columns='stock_code', values='foreign_net', aggfunc='sum')
    inv_institution = df_inv.pivot_table(index='date', columns='stock_code', values='institution_net', aggfunc='sum')

    # 뉴스 감성: 종목/날짜별 5일 이동평균
    if len(df_news) > 0:
        news_pivot = df_news.pivot_table(index='date', columns='stock_code', values='sentiment', aggfunc='mean')
        news_5d = news_pivot.rolling(5, min_periods=1).mean()
    else:
        news_5d = pd.DataFrame()

    # Forward returns
    fwd_5d = pivot_close.pct_change(5).shift(-5) * 100
    fwd_10d = pivot_close.pct_change(10).shift(-10) * 100
    fwd_20d = pivot_close.pct_change(20).shift(-20) * 100

    # 리밸런싱 날짜: start_date 이후, end_date-20일 이전
    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date) - pd.Timedelta(days=0)
    all_dates = sorted(pivot_close.index)
    valid_dates = [d for d in all_dates if d >= start_ts]
    rebal_dates = [valid_dates[i] for i in range(0, len(valid_dates), REBAL_INTERVAL)
                   if valid_dates[i] <= end_ts]

    print(f"리밸런싱: {len(rebal_dates)}회 ({rebal_dates[0].date()} ~ {rebal_dates[-1].date()})")

    # 팩터 사전 계산
    print("팩터 사전 계산 중...")
    factor_cache = {}  # (date, code) -> factors dict
    stock_fwd_cache = {}  # (date, code) -> {fwd_5d, fwd_10d, fwd_20d}

    for rdate in rebal_dates:
        loc_idx = pivot_close.index.get_loc(rdate)

        for code in pivot_close.columns:
            # 뉴스 5일 평균
            ns5d = None
            if len(news_5d) > 0 and code in news_5d.columns and rdate in news_5d.index:
                v = news_5d.loc[rdate, code]
                if not pd.isna(v):
                    ns5d = v

            factors = compute_factors_for_date(
                code, loc_idx, pivot_close, pivot_volume,
                inv_foreign, inv_institution, ns5d, fin_map,
            )
            if factors is None:
                continue

            # Forward returns
            fwd = {}
            for fname, fdf in [('fwd_5d', fwd_5d), ('fwd_10d', fwd_10d), ('fwd_20d', fwd_20d)]:
                if rdate in fdf.index and code in fdf.columns:
                    v = fdf.loc[rdate, code]
                    if not pd.isna(v):
                        fwd[fname] = v

            if not fwd:
                continue

            factor_cache[(rdate, code)] = factors
            stock_fwd_cache[(rdate, code)] = fwd

    print(f"팩터 캐시: {len(factor_cache):,}건 (종목×날짜)")

    # 조합 생성
    combos = generate_all_combinations()
    print(f"그리드 조합: {len(combos)}개")

    # 각 조합별 점수 → IC/Quintile 계산
    print("216개 조합별 성과 측정 중...")
    results = []

    for ci, combo in enumerate(combos):
        if (ci + 1) % 50 == 0:
            print(f"  진행: {ci + 1}/{len(combos)}")

        # 날짜별 (score, fwd) 수집
        daily_scores = {}  # date -> [(score, fwd_5d, fwd_10d, fwd_20d)]

        for (rdate, code), factors in factor_cache.items():
            score = score_combination(
                factors,
                combo['weight_profile'],
                combo['sm_bonus'],
                combo['rsi_threshold'],
                COMPOUND_CONFIGS[combo['compound']],
            )
            fwd = stock_fwd_cache[(rdate, code)]
            if rdate not in daily_scores:
                daily_scores[rdate] = []
            daily_scores[rdate].append({
                'score': score,
                'fwd_5d': fwd.get('fwd_5d'),
                'fwd_10d': fwd.get('fwd_10d'),
                'fwd_20d': fwd.get('fwd_20d'),
            })

        # IC/IR 계산
        metrics = compute_metrics(daily_scores)
        metrics['label'] = combo['label']
        metrics['weight_profile'] = combo['weight_profile']
        metrics['sm_bonus'] = combo['sm_bonus']
        metrics['rsi_threshold'] = combo['rsi_threshold']
        metrics['compound'] = combo['compound']
        results.append(metrics)

    df_results = pd.DataFrame(results)

    # 출력 & 저장
    print_phase1_results(df_results)
    save_csv(df_results, 1)

    return df_results


def compute_metrics(daily_scores):
    """날짜별 (score, fwd) 데이터에서 IC/IR/Quintile/HitRate 계산"""
    ics_5d, ics_10d, ics_20d = [], [], []
    top_5d, bot_5d = [], []
    top_10d, bot_10d = [], []
    top_20d, bot_20d = [], []
    top_hits_5d = []
    n_periods = 0

    for date, items in daily_scores.items():
        df = pd.DataFrame(items)

        # IC (5D)
        valid5 = df[['score', 'fwd_5d']].dropna()
        if len(valid5) >= 10:
            ic, _ = stats.spearmanr(valid5['score'], valid5['fwd_5d'])
            if not np.isnan(ic):
                ics_5d.append(ic)
                n_periods += 1

            # Quintile
            q80 = valid5['score'].quantile(0.8)
            q20 = valid5['score'].quantile(0.2)
            top = valid5[valid5['score'] >= q80]
            bot = valid5[valid5['score'] <= q20]
            if len(top) > 0 and len(bot) > 0:
                top_5d.append(top['fwd_5d'].mean())
                bot_5d.append(bot['fwd_5d'].mean())
                # Hit rate: 상위 20% 중 양수 수익률 비율
                top_hits_5d.append((top['fwd_5d'] > 0).mean())

        # IC (10D)
        valid10 = df[['score', 'fwd_10d']].dropna()
        if len(valid10) >= 10:
            ic10, _ = stats.spearmanr(valid10['score'], valid10['fwd_10d'])
            if not np.isnan(ic10):
                ics_10d.append(ic10)
            q80 = valid10['score'].quantile(0.8)
            q20 = valid10['score'].quantile(0.2)
            top10 = valid10[valid10['score'] >= q80]
            bot10 = valid10[valid10['score'] <= q20]
            if len(top10) > 0 and len(bot10) > 0:
                top_10d.append(top10['fwd_10d'].mean())
                bot_10d.append(bot10['fwd_10d'].mean())

        # IC (20D)
        valid20 = df[['score', 'fwd_20d']].dropna()
        if len(valid20) >= 10:
            ic20, _ = stats.spearmanr(valid20['score'], valid20['fwd_20d'])
            if not np.isnan(ic20):
                ics_20d.append(ic20)
            q80 = valid20['score'].quantile(0.8)
            q20 = valid20['score'].quantile(0.2)
            top20 = valid20[valid20['score'] >= q80]
            bot20 = valid20[valid20['score'] <= q20]
            if len(top20) > 0 and len(bot20) > 0:
                top_20d.append(top20['fwd_20d'].mean())
                bot_20d.append(bot20['fwd_20d'].mean())

    def _safe_mean(lst):
        return np.mean(lst) if lst else float('nan')

    def _safe_ir(lst):
        if not lst:
            return float('nan')
        m, s = np.mean(lst), np.std(lst)
        return m / s if s > 0 else 0

    return {
        'ic_5d': _safe_mean(ics_5d),
        'ir_5d': _safe_ir(ics_5d),
        'ic_10d': _safe_mean(ics_10d),
        'ir_10d': _safe_ir(ics_10d),
        'ic_20d': _safe_mean(ics_20d),
        'ir_20d': _safe_ir(ics_20d),
        'top_5d': _safe_mean(top_5d),
        'bot_5d': _safe_mean(bot_5d),
        'spread_5d': _safe_mean(top_5d) - _safe_mean(bot_5d) if top_5d and bot_5d else float('nan'),
        'top_10d': _safe_mean(top_10d),
        'bot_10d': _safe_mean(bot_10d),
        'spread_10d': _safe_mean(top_10d) - _safe_mean(bot_10d) if top_10d and bot_10d else float('nan'),
        'top_20d': _safe_mean(top_20d),
        'bot_20d': _safe_mean(bot_20d),
        'spread_20d': _safe_mean(top_20d) - _safe_mean(bot_20d) if top_20d and bot_20d else float('nan'),
        'hit_rate_5d': _safe_mean(top_hits_5d),
        'n_periods': n_periods,
    }


# ============================================================
# Phase 2: Watchlist 백테스트
# ============================================================
def run_phase2():
    """Phase 2: Watchlist 4주 그리드 백테스트"""
    start_date = datetime(2026, 1, 11).date()
    end_date = datetime(2026, 2, 6).date()

    print(f"\n{'='*100}")
    print(f"  Phase 2: Watchlist Grid Backtest ({start_date} ~ {end_date})")
    print(f"{'='*100}")

    init_engine()
    with session_scope(readonly=True) as session:
        df_price, df_inv, df_news, fin_map, name_map, df_wh = load_phase2_data(
            session, start_date, end_date
        )

    # Pivot tables
    pivot_close = df_price.pivot(index='date', columns='stock_code', values='close').sort_index()
    pivot_volume = df_price.pivot(index='date', columns='stock_code', values='volume').sort_index()
    inv_foreign = df_inv.pivot_table(index='date', columns='stock_code', values='foreign_net', aggfunc='sum')
    inv_institution = df_inv.pivot_table(index='date', columns='stock_code', values='institution_net', aggfunc='sum')

    if len(df_news) > 0:
        news_pivot = df_news.pivot_table(index='date', columns='stock_code', values='sentiment', aggfunc='mean')
        news_5d = news_pivot.rolling(5, min_periods=1).mean()
    else:
        news_5d = pd.DataFrame()

    fwd_5d = pivot_close.pct_change(5).shift(-5) * 100
    fwd_10d = pivot_close.pct_change(10).shift(-10) * 100
    fwd_20d = pivot_close.pct_change(20).shift(-20) * 100

    # Watchlist 날짜를 리밸런싱 날짜로 사용
    wh_dates = sorted(df_wh['date'].unique())
    # 실제 거래일과 매칭
    all_trade_dates = sorted(pivot_close.index)
    rebal_dates = []
    for wd in wh_dates:
        matched = [td for td in all_trade_dates if td >= wd]
        if matched:
            rebal_dates.append(matched[0])
    rebal_dates = sorted(set(rebal_dates))

    print(f"Watchlist 리밸런싱: {len(rebal_dates)}회")

    # 팩터 사전 계산 (watchlist 종목만)
    print("팩터 사전 계산 중...")
    factor_cache = {}
    stock_fwd_cache = {}
    llm_score_cache = {}  # (date, code) -> llm_score

    for rdate in rebal_dates:
        if rdate not in pivot_close.index:
            continue
        loc_idx = pivot_close.index.get_loc(rdate)

        # 해당 날짜의 watchlist 종목
        wh_day = df_wh[df_wh['date'] <= rdate].sort_values('date', ascending=False)
        latest_wh_date = wh_day['date'].max()
        wh_codes = set(wh_day[wh_day['date'] == latest_wh_date]['stock_code'])

        for code in wh_codes:
            if code not in pivot_close.columns:
                continue

            ns5d = None
            if len(news_5d) > 0 and code in news_5d.columns and rdate in news_5d.index:
                v = news_5d.loc[rdate, code]
                if not pd.isna(v):
                    ns5d = v

            factors = compute_factors_for_date(
                code, loc_idx, pivot_close, pivot_volume,
                inv_foreign, inv_institution, ns5d, fin_map,
            )
            if factors is None:
                continue

            fwd = {}
            for fname, fdf in [('fwd_5d', fwd_5d), ('fwd_10d', fwd_10d), ('fwd_20d', fwd_20d)]:
                if rdate in fdf.index and code in fdf.columns:
                    v = fdf.loc[rdate, code]
                    if not pd.isna(v):
                        fwd[fname] = v

            if not fwd:
                continue

            factor_cache[(rdate, code)] = factors
            stock_fwd_cache[(rdate, code)] = fwd

            # LLM 점수
            llm_row = wh_day[(wh_day['stock_code'] == code) & (wh_day['date'] == latest_wh_date)]
            if len(llm_row) > 0:
                llm_score_cache[(rdate, code)] = float(llm_row.iloc[0]['llm_score'])

    print(f"팩터 캐시: {len(factor_cache):,}건")

    combos = generate_all_combinations()
    print(f"그리드 조합: {len(combos)}개")

    print("216개 조합별 성과 측정 중...")
    results = []

    for ci, combo in enumerate(combos):
        if (ci + 1) % 50 == 0:
            print(f"  진행: {ci + 1}/{len(combos)}")

        daily_scores = {}
        all_scores_fwd = []

        for (rdate, code), factors in factor_cache.items():
            score = score_combination(
                factors,
                combo['weight_profile'],
                combo['sm_bonus'],
                combo['rsi_threshold'],
                COMPOUND_CONFIGS[combo['compound']],
            )
            fwd = stock_fwd_cache[(rdate, code)]

            if rdate not in daily_scores:
                daily_scores[rdate] = []
            daily_scores[rdate].append({
                'score': score,
                'fwd_5d': fwd.get('fwd_5d'),
                'fwd_10d': fwd.get('fwd_10d'),
                'fwd_20d': fwd.get('fwd_20d'),
            })

            all_scores_fwd.append({
                'score': score,
                'llm_score': llm_score_cache.get((rdate, code)),
                **fwd,
            })

        # Phase 2 고유 지표: 평균 수익률, hit rate, LLM 상관
        df_sf = pd.DataFrame(all_scores_fwd)

        # 기본 메트릭도 계산
        metrics = compute_metrics(daily_scores)

        # Phase 2 추가 지표
        if 'fwd_5d' in df_sf.columns:
            valid5 = df_sf[['score', 'fwd_5d']].dropna()
            metrics['avg_return_5d'] = valid5['fwd_5d'].mean() if len(valid5) > 0 else float('nan')
            metrics['median_return_5d'] = valid5['fwd_5d'].median() if len(valid5) > 0 else float('nan')
            metrics['overall_hit_5d'] = (valid5['fwd_5d'] > 0).mean() if len(valid5) > 0 else float('nan')

        if 'fwd_10d' in df_sf.columns:
            valid10 = df_sf[['score', 'fwd_10d']].dropna()
            metrics['avg_return_10d'] = valid10['fwd_10d'].mean() if len(valid10) > 0 else float('nan')

        # LLM 점수와의 상관
        if 'llm_score' in df_sf.columns and 'fwd_5d' in df_sf.columns:
            valid_llm = df_sf[['score', 'llm_score', 'fwd_5d']].dropna()
            if len(valid_llm) >= 5:
                corr_quant_llm, _ = stats.spearmanr(valid_llm['score'], valid_llm['llm_score'])
                metrics['corr_quant_llm'] = corr_quant_llm
            else:
                metrics['corr_quant_llm'] = float('nan')

        metrics['label'] = combo['label']
        metrics['weight_profile'] = combo['weight_profile']
        metrics['sm_bonus'] = combo['sm_bonus']
        metrics['rsi_threshold'] = combo['rsi_threshold']
        metrics['compound'] = combo['compound']
        results.append(metrics)

    df_results = pd.DataFrame(results)

    print_phase2_results(df_results)
    save_csv(df_results, 2)

    return df_results


# ============================================================
# 출력
# ============================================================
def print_phase1_results(df):
    """Phase 1 결과 출력"""
    # 상위 10개 (IR 5D 기준)
    sort_col = 'ir_5d'
    if df[sort_col].isna().all():
        sort_col = 'spread_5d'

    top10 = df.nlargest(10, sort_col)

    print(f"\n{'='*120}")
    print(f"  상위 10개 조합 (정렬: {sort_col})")
    print(f"{'='*120}")
    print(f"  {'순위':>4s}  {'프로필':>14s} {'SM':>5s} {'RSI':>3s} {'CB':>4s} │ "
          f"{'IC(5D)':>7s} {'IR(5D)':>7s} │ {'IC(10D)':>7s} {'IR(10D)':>7s} │ "
          f"{'Spread5D':>8s} {'Spread10D':>9s} {'HitRate':>7s} │ {'N':>3s}")
    print("  " + "─" * 115)

    for rank, (_, row) in enumerate(top10.iterrows(), 1):
        print(f"  {rank:>4d}  {row['weight_profile']:>14s} {row['sm_bonus']:>5s} {row['rsi_threshold']:>3d} {row['compound']:>4s} │ "
              f"{row['ic_5d']:>+7.4f} {row['ir_5d']:>+7.3f} │ {row['ic_10d']:>+7.4f} {row['ir_10d']:>+7.3f} │ "
              f"{row['spread_5d']:>+8.2f}% {row['spread_10d']:>+8.2f}% {row['hit_rate_5d']:>6.1%} │ {row['n_periods']:>3.0f}")

    # 차원별 평균 성과 분석
    print(f"\n{'='*120}")
    print(f"  차원별 평균 성과 (독립 효과)")
    print(f"{'='*120}")

    # Dim 1: Weight Profile
    print(f"\n  [Dim 1] 가중치 프로필별 평균:")
    print(f"  {'프로필':>14s} │ {'IC(5D)':>7s} {'IR(5D)':>7s} │ {'Spread5D':>8s} {'HitRate':>7s}")
    print("  " + "─" * 55)
    for wp in WEIGHT_PROFILES:
        sub = df[df['weight_profile'] == wp]
        print(f"  {wp:>14s} │ {sub['ic_5d'].mean():>+7.4f} {sub['ir_5d'].mean():>+7.3f} │ "
              f"{sub['spread_5d'].mean():>+8.2f}% {sub['hit_rate_5d'].mean():>6.1%}")

    # Dim 2: SM Bonus
    print(f"\n  [Dim 2] Smart Money 보너스별 평균:")
    print(f"  {'SM Config':>10s} │ {'IC(5D)':>7s} {'IR(5D)':>7s} │ {'Spread5D':>8s} {'HitRate':>7s}")
    print("  " + "─" * 55)
    for sm in SM_BONUS_CONFIGS:
        sub = df[df['sm_bonus'] == sm]
        print(f"  {sm:>10s} │ {sub['ic_5d'].mean():>+7.4f} {sub['ir_5d'].mean():>+7.3f} │ "
              f"{sub['spread_5d'].mean():>+8.2f}% {sub['hit_rate_5d'].mean():>6.1%}")

    # Dim 3: RSI Threshold
    print(f"\n  [Dim 3] RSI 과매도 기준별 평균:")
    print(f"  {'RSI<':>5s} │ {'IC(5D)':>7s} {'IR(5D)':>7s} │ {'Spread5D':>8s} {'HitRate':>7s}")
    print("  " + "─" * 55)
    for rsi in RSI_THRESHOLDS:
        sub = df[df['rsi_threshold'] == rsi]
        print(f"  {rsi:>5d} │ {sub['ic_5d'].mean():>+7.4f} {sub['ir_5d'].mean():>+7.3f} │ "
              f"{sub['spread_5d'].mean():>+8.2f}% {sub['hit_rate_5d'].mean():>6.1%}")

    # Dim 4: Compound
    print(f"\n  [Dim 4] Compound Bonus별 평균:")
    print(f"  {'CB':>7s} │ {'IC(5D)':>7s} {'IR(5D)':>7s} │ {'Spread5D':>8s} {'HitRate':>7s}")
    print("  " + "─" * 55)
    for comp in COMPOUND_CONFIGS:
        sub = df[df['compound'] == comp]
        print(f"  {comp:>7s} │ {sub['ic_5d'].mean():>+7.4f} {sub['ir_5d'].mean():>+7.3f} │ "
              f"{sub['spread_5d'].mean():>+8.2f}% {sub['hit_rate_5d'].mean():>6.1%}")

    print()


def print_phase2_results(df):
    """Phase 2 결과 출력"""
    sort_col = 'avg_return_5d' if 'avg_return_5d' in df.columns and not df['avg_return_5d'].isna().all() else 'ir_5d'

    top10 = df.nlargest(10, sort_col)

    print(f"\n{'='*130}")
    print(f"  Phase 2 상위 10개 조합 (정렬: {sort_col})")
    print(f"{'='*130}")
    print(f"  {'순위':>4s}  {'프로필':>14s} {'SM':>5s} {'RSI':>3s} {'CB':>4s} │ "
          f"{'AvgRet5D':>8s} {'MedRet5D':>8s} {'HitRate':>7s} │ "
          f"{'IC(5D)':>7s} {'IR(5D)':>7s} │ {'Corr_LLM':>8s}")
    print("  " + "─" * 120)

    for rank, (_, row) in enumerate(top10.iterrows(), 1):
        avg_r = f"{row.get('avg_return_5d', float('nan')):>+7.2f}%" if not pd.isna(row.get('avg_return_5d')) else "    N/A "
        med_r = f"{row.get('median_return_5d', float('nan')):>+7.2f}%" if not pd.isna(row.get('median_return_5d')) else "    N/A "
        hit = f"{row.get('overall_hit_5d', float('nan')):>6.1%}" if not pd.isna(row.get('overall_hit_5d')) else "   N/A "
        corr = f"{row.get('corr_quant_llm', float('nan')):>+7.3f}" if not pd.isna(row.get('corr_quant_llm')) else "    N/A"

        print(f"  {rank:>4d}  {row['weight_profile']:>14s} {row['sm_bonus']:>5s} {row['rsi_threshold']:>3.0f} {row['compound']:>4s} │ "
              f"{avg_r} {med_r} {hit} │ "
              f"{row['ic_5d']:>+7.4f} {row['ir_5d']:>+7.3f} │ {corr}")

    # 차원별 분석
    print(f"\n{'='*130}")
    print(f"  Phase 2 차원별 평균 성과")
    print(f"{'='*130}")

    for dim_name, dim_col, dim_values in [
        ('가중치 프로필', 'weight_profile', list(WEIGHT_PROFILES.keys())),
        ('SM 보너스', 'sm_bonus', list(SM_BONUS_CONFIGS.keys())),
        ('RSI 기준', 'rsi_threshold', RSI_THRESHOLDS),
        ('Compound', 'compound', list(COMPOUND_CONFIGS.keys())),
    ]:
        print(f"\n  [{dim_name}]")
        print(f"  {'값':>14s} │ {'AvgRet5D':>8s} {'HitRate':>7s} │ {'IC(5D)':>7s} {'IR(5D)':>7s} │ {'Corr_LLM':>8s}")
        print("  " + "─" * 65)
        for val in dim_values:
            sub = df[df[dim_col] == val]
            avg_r = sub.get('avg_return_5d', pd.Series([float('nan')])).mean()
            hit = sub.get('overall_hit_5d', pd.Series([float('nan')])).mean()
            corr = sub.get('corr_quant_llm', pd.Series([float('nan')])).mean()
            print(f"  {str(val):>14s} │ {avg_r:>+7.2f}% {hit:>6.1%} │ "
                  f"{sub['ic_5d'].mean():>+7.4f} {sub['ir_5d'].mean():>+7.3f} │ {corr:>+7.3f}")

    print()


# ============================================================
# CSV 저장
# ============================================================
def save_csv(df, phase):
    """결과를 CSV로 저장"""
    output_dir = os.path.join(os.path.dirname(__file__), 'output')
    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"backtest_grid_phase{phase}_{timestamp}.csv"
    filepath = os.path.join(output_dir, filename)

    df.to_csv(filepath, index=False, float_format='%.4f')
    print(f"CSV 저장: {filepath}")
    print(f"  총 {len(df)}개 조합")


# ============================================================
# Main
# ============================================================
def main():
    parser = argparse.ArgumentParser(description='Grid Backtest for Quant Scorer')
    parser.add_argument('--phase', type=int, choices=[1, 2], default=1,
                        help='Phase 1: 전종목 2개월, Phase 2: Watchlist 4주')
    args = parser.parse_args()

    if args.phase == 1:
        run_phase1()
    else:
        run_phase2()


if __name__ == '__main__':
    main()
