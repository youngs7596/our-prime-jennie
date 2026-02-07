#!/usr/bin/env python3
"""
Unified Analyst 모니터링 스크립트

WATCHLIST_HISTORY에 저장된 unified analyst 결과의 성과를 분석합니다.
- 소스별 비교 (unified_analyst vs hybrid_scorer_v5)
- risk_tag 유효성 검증
- 가드레일(클램핑) 효과 분석
- Veto 분석 (차단 종목의 forward return)
- Score 구간별 Hit Rate

Usage:
    .venv/bin/python scripts/monitor_unified_analyst.py [--days 30]
"""

import sys
import os
import argparse
import json
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.db.connection import ensure_engine_initialized, session_scope
from shared.db.models import WatchlistHistory, StockDailyPrice
from shared.db.repository import _parse_llm_reason


def load_secrets():
    secrets_path = os.path.join(project_root, "secrets.json")
    if os.path.exists(secrets_path):
        with open(secrets_path, "r") as f:
            secrets = json.load(f)
            os.environ["MARIADB_USER"] = secrets.get("mariadb-user", "root")
            os.environ["MARIADB_PASSWORD"] = secrets.get("mariadb-password", "")
            os.environ["MARIADB_HOST"] = secrets.get("mariadb-host", "localhost")
            os.environ["MARIADB_PORT"] = secrets.get("mariadb-port", "3306")
            os.environ["MARIADB_DBNAME"] = secrets.get("mariadb-dbname", "jennie_db")
            os.environ["DB_TYPE"] = "MARIADB"


def load_data(session, lookback_days: int):
    """WATCHLIST_HISTORY + STOCK_DAILY_PRICES_3Y 로드 및 forward return 계산"""
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=lookback_days + 20)  # 여유분

    # 1. Watchlist History
    wh_rows = session.query(
        WatchlistHistory.snapshot_date,
        WatchlistHistory.stock_code,
        WatchlistHistory.stock_name,
        WatchlistHistory.llm_score,
        WatchlistHistory.is_tradable,
        WatchlistHistory.llm_reason,
    ).filter(
        WatchlistHistory.snapshot_date >= start_date,
        WatchlistHistory.snapshot_date <= end_date,
    ).all()

    if not wh_rows:
        return None, None

    df_wh = pd.DataFrame(wh_rows, columns=['date', 'code', 'name', 'hybrid_score', 'is_tradable', 'llm_reason'])

    # 메타데이터 파싱
    meta_records = []
    for _, row in df_wh.iterrows():
        reason_text, metadata = _parse_llm_reason(row['llm_reason'] or "")
        meta_records.append({
            'source': metadata.get('source', 'unknown'),
            'quant_score': metadata.get('quant_score'),
            'llm_raw_score': metadata.get('llm_raw_score'),
            'llm_clamped_score': metadata.get('llm_clamped_score'),
            'risk_tag': metadata.get('risk_tag'),
            'trade_tier': metadata.get('trade_tier'),
            'veto_applied': metadata.get('veto_applied', False),
        })
    df_meta = pd.DataFrame(meta_records)
    df_wh = pd.concat([df_wh.reset_index(drop=True), df_meta], axis=1)
    df_wh.drop(columns=['llm_reason'], inplace=True)

    # 2. Prices
    stock_codes = df_wh['code'].unique().tolist()
    price_start = start_date - timedelta(days=5)
    price_end = end_date + timedelta(days=25)  # forward return용

    prices = session.query(
        StockDailyPrice.stock_code,
        StockDailyPrice.price_date,
        StockDailyPrice.close_price,
    ).filter(
        StockDailyPrice.stock_code.in_(stock_codes),
        StockDailyPrice.price_date >= price_start,
        StockDailyPrice.price_date <= price_end,
    ).all()

    df_price = pd.DataFrame(prices, columns=['code', 'date', 'close'])
    df_price['date'] = pd.to_datetime(df_price['date']).dt.date

    # 3. Forward return 계산
    pivot = df_price.pivot_table(index='date', columns='code', values='close', aggfunc='last').sort_index()
    fwd_5d = pivot.pct_change(5, fill_method=None).shift(-5) * 100
    fwd_10d = pivot.pct_change(10, fill_method=None).shift(-10) * 100

    # Watchlist에 forward return 매핑
    fwd5_map = fwd_5d.stack().reset_index()
    fwd5_map.columns = ['date', 'code', 'fwd_5d']
    fwd10_map = fwd_10d.stack().reset_index()
    fwd10_map.columns = ['date', 'code', 'fwd_10d']

    df_wh['date'] = pd.to_datetime(df_wh['date']).dt.date
    df_wh = df_wh.merge(fwd5_map, on=['date', 'code'], how='left')
    df_wh = df_wh.merge(fwd10_map, on=['date', 'code'], how='left')

    return df_wh, pivot


def print_source_comparison(df: pd.DataFrame):
    """소스별 비교: unified_analyst vs hybrid_scorer_v5"""
    print("\n" + "=" * 70)
    print("1. 소스별 성과 비교")
    print("=" * 70)

    try:
        from scipy.stats import spearmanr
    except ImportError:
        spearmanr = None

    for source in sorted(df['source'].unique()):
        subset = df[df['source'] == source]
        valid_5d = subset.dropna(subset=['fwd_5d'])
        valid_10d = subset.dropna(subset=['fwd_10d'])

        print(f"\n  [{source}] (총 {len(subset)}건)")

        if len(valid_5d) > 0:
            wr_5d = (valid_5d['fwd_5d'] > 0).mean() * 100
            avg_5d = valid_5d['fwd_5d'].mean()
            print(f"    D+5  Win Rate: {wr_5d:.1f}%  Avg: {avg_5d:+.2f}%  (n={len(valid_5d)})")

            if spearmanr and len(valid_5d) >= 5:
                score_col = 'hybrid_score'
                valid_ic = valid_5d.dropna(subset=[score_col])
                if len(valid_ic) >= 5:
                    ic, p = spearmanr(valid_ic[score_col], valid_ic['fwd_5d'])
                    sig = "*" if p < 0.05 else ""
                    print(f"    D+5  IC(Spearman): {ic:+.3f} (p={p:.3f}){sig}")
        else:
            print("    D+5  데이터 부족 (아직 5영업일 미경과)")

        if len(valid_10d) > 0:
            wr_10d = (valid_10d['fwd_10d'] > 0).mean() * 100
            avg_10d = valid_10d['fwd_10d'].mean()
            print(f"    D+10 Win Rate: {wr_10d:.1f}%  Avg: {avg_10d:+.2f}%  (n={len(valid_10d)})")


def print_risk_tag_analysis(df: pd.DataFrame):
    """risk_tag별 실제 forward return"""
    print("\n" + "=" * 70)
    print("2. Risk Tag 유효성 분석")
    print("=" * 70)

    tagged = df[df['risk_tag'].notna()]
    if tagged.empty:
        print("  risk_tag 데이터 없음 (unified_analyst 데이터 부족)")
        return

    for tag in ['BULLISH', 'NEUTRAL', 'CAUTION', 'DISTRIBUTION_RISK']:
        subset = tagged[tagged['risk_tag'] == tag]
        valid = subset.dropna(subset=['fwd_5d'])
        if len(valid) > 0:
            wr = (valid['fwd_5d'] > 0).mean() * 100
            avg = valid['fwd_5d'].mean()
            med = valid['fwd_5d'].median()
            print(f"  {tag:22s}  n={len(valid):3d}  WR={wr:.1f}%  Avg={avg:+.2f}%  Med={med:+.2f}%")
        else:
            count = len(subset)
            if count > 0:
                print(f"  {tag:22s}  n={count:3d}  (forward return 미산출)")
            else:
                print(f"  {tag:22s}  해당 없음")


def print_guardrail_analysis(df: pd.DataFrame):
    """가드레일(클램핑) 효과: raw vs clamped 차이"""
    print("\n" + "=" * 70)
    print("3. 가드레일(클램핑) 효과 분석")
    print("=" * 70)

    clamped = df.dropna(subset=['llm_raw_score', 'llm_clamped_score'])
    if clamped.empty:
        print("  클램핑 데이터 없음")
        return

    clamped = clamped.copy()
    clamped['clamp_diff'] = clamped['llm_clamped_score'] - clamped['llm_raw_score']

    # 클램핑된 건 vs 안 된 건
    was_clamped = clamped[clamped['clamp_diff'].abs() > 0.5]
    not_clamped = clamped[clamped['clamp_diff'].abs() <= 0.5]

    print(f"  전체: {len(clamped)}건, 클램핑 적용: {len(was_clamped)}건 ({len(was_clamped)/len(clamped)*100:.1f}%)")

    if len(was_clamped) > 0:
        print(f"  클램핑 차이 분포: mean={was_clamped['clamp_diff'].mean():+.1f}  "
              f"std={was_clamped['clamp_diff'].std():.1f}  "
              f"min={was_clamped['clamp_diff'].min():+.1f}  "
              f"max={was_clamped['clamp_diff'].max():+.1f}")

        # 클램핑된 건의 forward return
        valid_c = was_clamped.dropna(subset=['fwd_5d'])
        valid_nc = not_clamped.dropna(subset=['fwd_5d'])

        if len(valid_c) > 0 and len(valid_nc) > 0:
            print(f"\n  클램핑 적용  D+5: WR={((valid_c['fwd_5d']>0).mean()*100):.1f}%  "
                  f"Avg={valid_c['fwd_5d'].mean():+.2f}%  (n={len(valid_c)})")
            print(f"  클램핑 미적용 D+5: WR={((valid_nc['fwd_5d']>0).mean()*100):.1f}%  "
                  f"Avg={valid_nc['fwd_5d'].mean():+.2f}%  (n={len(valid_nc)})")

        # 상향 클램핑 vs 하향 클램핑
        clamped_up = was_clamped[was_clamped['clamp_diff'] > 0]
        clamped_down = was_clamped[was_clamped['clamp_diff'] < 0]
        if len(clamped_up) > 0:
            v = clamped_up.dropna(subset=['fwd_5d'])
            if len(v) > 0:
                print(f"  상향 클램핑(LLM↑) D+5: Avg={v['fwd_5d'].mean():+.2f}%  (n={len(v)})")
        if len(clamped_down) > 0:
            v = clamped_down.dropna(subset=['fwd_5d'])
            if len(v) > 0:
                print(f"  하향 클램핑(LLM↓) D+5: Avg={v['fwd_5d'].mean():+.2f}%  (n={len(v)})")


def print_veto_analysis(df: pd.DataFrame):
    """Veto(차단) 종목의 forward return 분석"""
    print("\n" + "=" * 70)
    print("4. Veto(차단) 분석")
    print("=" * 70)

    vetoed = df[df['veto_applied'] == True]
    not_vetoed = df[df['veto_applied'] == False]

    print(f"  전체: {len(df)}건, Veto 적용: {len(vetoed)}건")

    if len(vetoed) == 0:
        print("  Veto 적용 종목 없음")
        return

    valid_v = vetoed.dropna(subset=['fwd_5d'])
    valid_nv = not_vetoed.dropna(subset=['fwd_5d'])

    if len(valid_v) > 0:
        avg_v = valid_v['fwd_5d'].mean()
        wr_v = (valid_v['fwd_5d'] > 0).mean() * 100
        print(f"  Veto 적용   D+5: WR={wr_v:.1f}%  Avg={avg_v:+.2f}%  (n={len(valid_v)})")
        if avg_v < 0:
            print(f"  → Veto가 올바른 판단 (차단 종목 평균 {avg_v:+.2f}% 하락)")
        else:
            print(f"  → Veto 재검토 필요 (차단 종목 평균 {avg_v:+.2f}% 상승)")

    if len(valid_nv) > 0:
        avg_nv = valid_nv['fwd_5d'].mean()
        wr_nv = (valid_nv['fwd_5d'] > 0).mean() * 100
        print(f"  Veto 미적용 D+5: WR={wr_nv:.1f}%  Avg={avg_nv:+.2f}%  (n={len(valid_nv)})")


def print_score_bucket_analysis(df: pd.DataFrame):
    """Score 구간별 Hit Rate"""
    print("\n" + "=" * 70)
    print("5. Score 구간별 Hit Rate")
    print("=" * 70)

    valid = df.dropna(subset=['hybrid_score', 'fwd_5d'])
    if valid.empty:
        print("  데이터 부족")
        return

    bins = [0, 50, 60, 70, 80, 101]
    labels = ['<50', '50-59', '60-69', '70-79', '80+']
    valid = valid.copy()
    valid['bucket'] = pd.cut(valid['hybrid_score'], bins=bins, labels=labels, right=False)

    print(f"  {'구간':>8s}  {'n':>5s}  {'WR(D+5)':>8s}  {'Avg':>8s}  {'Med':>8s}")
    print(f"  {'-'*8}  {'-'*5}  {'-'*8}  {'-'*8}  {'-'*8}")

    for bucket in labels:
        subset = valid[valid['bucket'] == bucket]
        if len(subset) > 0:
            wr = (subset['fwd_5d'] > 0).mean() * 100
            avg = subset['fwd_5d'].mean()
            med = subset['fwd_5d'].median()
            print(f"  {bucket:>8s}  {len(subset):5d}  {wr:7.1f}%  {avg:+7.2f}%  {med:+7.2f}%")
        else:
            print(f"  {bucket:>8s}      0        -         -         -")


def main():
    parser = argparse.ArgumentParser(description="Unified Analyst 성과 모니터링")
    parser.add_argument("--days", type=int, default=30, help="분석 기간 (일)")
    args = parser.parse_args()

    print(f"Unified Analyst 모니터링 (최근 {args.days}일)")
    print("=" * 70)

    load_secrets()
    ensure_engine_initialized()

    with session_scope(readonly=True) as session:
        df, pivot = load_data(session, args.days)

        if df is None or df.empty:
            print("WATCHLIST_HISTORY 데이터가 없습니다.")
            return

        total = len(df)
        sources = df['source'].value_counts()
        print(f"  총 데이터: {total}건")
        for src, cnt in sources.items():
            print(f"    - {src}: {cnt}건")

        has_fwd = df['fwd_5d'].notna().sum()
        if has_fwd == 0:
            print(f"\n  Forward return 산출 가능 데이터 0건.")
            print(f"  최소 5영업일 경과 후 재실행하세요.")
            min_date = df['date'].min()
            print(f"  (가장 오래된 데이터: {min_date})")
            return

        print(f"  Forward return 산출: {has_fwd}건 / {total}건")

        print_source_comparison(df)
        print_risk_tag_analysis(df)
        print_guardrail_analysis(df)
        print_veto_analysis(df)
        print_score_bucket_analysis(df)

    print("\n" + "=" * 70)
    print("분석 완료")


if __name__ == "__main__":
    main()
