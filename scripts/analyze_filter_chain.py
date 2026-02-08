"""
Scout → Buy 필터 체인 종합 분석

WATCHLIST_HISTORY의 llm_metadata를 활용하여:
1. 점수 분포 분석 (hybrid_score, quant_score, llm_score)
2. Hot Watchlist 커트라인별 D+5 수익률/Hit Rate
3. MAX_WATCHLIST_SIZE 제한 영향 분석
4. trade_tier별 수익률 분석
5. 최적 커트라인 제안

사용법:
    .venv/bin/python scripts/analyze_filter_chain.py
    .venv/bin/python scripts/analyze_filter_chain.py --days 60
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import argparse
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from scipy import stats
from sqlalchemy import text

from shared.db.connection import init_engine, session_scope


def load_watchlist_with_metadata(session, start_date, end_date):
    """WATCHLIST_HISTORY에서 llm_metadata 포함 전체 조회"""
    result = session.execute(text("""
        SELECT SNAPSHOT_DATE, STOCK_CODE, STOCK_NAME, IS_TRADABLE, LLM_SCORE, LLM_REASON
        FROM WATCHLIST_HISTORY
        WHERE SNAPSHOT_DATE BETWEEN :start AND :end
          AND STOCK_CODE != '0001'
        ORDER BY SNAPSHOT_DATE, LLM_SCORE DESC
    """), {"start": start_date, "end": end_date})

    rows = []
    for row in result.fetchall():
        snapshot_date, code, name, is_tradable, llm_score, llm_reason = row

        # llm_metadata 추출
        metadata = {}
        if llm_reason and '[LLM_METADATA]' in llm_reason:
            try:
                meta_str = llm_reason.split('[LLM_METADATA]')[1]
                metadata = json.loads(meta_str)
            except (json.JSONDecodeError, IndexError):
                pass

        rows.append({
            'snapshot_date': snapshot_date,
            'stock_code': code,
            'stock_name': name,
            'is_tradable': is_tradable,
            'hybrid_score': llm_score,  # llm_score 컬럼에 저장된 값 = hybrid_score
            'quant_score': metadata.get('quant_score'),
            'llm_raw_score': metadata.get('llm_raw_score'),
            'llm_clamped_score': metadata.get('llm_clamped_score'),
            'trade_tier': metadata.get('trade_tier'),
            'risk_tag': metadata.get('risk_tag'),
            'source': metadata.get('source'),
        })

    return pd.DataFrame(rows)


def load_forward_returns(session, stock_codes, start_date, end_date):
    """종목별 일별 종가 → D+1/D+3/D+5/D+10 Forward Return 계산"""
    if not stock_codes:
        return pd.DataFrame()

    # 날짜 범위 확장 (forward return 계산용)
    extended_end = end_date + timedelta(days=25)

    placeholders = ', '.join([f':code_{i}' for i in range(len(stock_codes))])
    params = {f'code_{i}': code for i, code in enumerate(stock_codes)}
    params['start'] = start_date - timedelta(days=5)
    params['end'] = extended_end

    result = session.execute(text(f"""
        SELECT STOCK_CODE, PRICE_DATE, CLOSE_PRICE
        FROM STOCK_DAILY_PRICES_3Y
        WHERE STOCK_CODE IN ({placeholders})
          AND PRICE_DATE BETWEEN :start AND :end
        ORDER BY STOCK_CODE, PRICE_DATE
    """), params)

    price_data = {}
    for row in result.fetchall():
        code, price_date, close_price = row
        # PRICE_DATE가 datetime일 수 있으므로 date로 변환
        if hasattr(price_date, 'date'):
            price_date = price_date.date()
        if code not in price_data:
            price_data[code] = {}
        price_data[code][price_date] = close_price

    return price_data


def calculate_forward_return(price_data, stock_code, snapshot_date, days_forward):
    """특정 종목의 D+N 수익률 계산"""
    if stock_code not in price_data:
        return None

    prices = price_data[stock_code]
    sorted_dates = sorted(prices.keys())

    # snapshot_date 이후 첫 거래일 찾기
    entry_dates = [d for d in sorted_dates if d >= snapshot_date]
    if len(entry_dates) < 2:
        return None

    # D+0 = snapshot_date 이후 첫 거래일 (당일 또는 다음 거래일)
    entry_price = prices[entry_dates[0]]

    # D+N 거래일
    if len(entry_dates) <= days_forward:
        return None

    exit_price = prices[entry_dates[days_forward]]

    if entry_price <= 0:
        return None

    return (exit_price - entry_price) / entry_price * 100


def analyze_score_distribution(df):
    """점수 분포 분석"""
    print("\n" + "=" * 70)
    print("1. 점수 분포 분석")
    print("=" * 70)

    for score_col in ['hybrid_score', 'quant_score', 'llm_clamped_score']:
        valid = df[score_col].dropna()
        if len(valid) == 0:
            continue
        print(f"\n  [{score_col}] (n={len(valid)})")
        print(f"    평균: {valid.mean():.1f}, 중앙값: {valid.median():.1f}")
        print(f"    std: {valid.std():.1f}")
        print(f"    min: {valid.min():.1f}, max: {valid.max():.1f}")
        print(f"    25%: {valid.quantile(0.25):.1f}, 75%: {valid.quantile(0.75):.1f}")

    # 점수 구간별 종목 수
    print(f"\n  [hybrid_score 구간별 분포]")
    bins = [0, 40, 50, 55, 58, 62, 65, 70, 75, 80, 100]
    labels = ['<40', '40-50', '50-55', '55-58', '58-62', '62-65', '65-70', '70-75', '75-80', '80+']
    df['score_bin'] = pd.cut(df['hybrid_score'], bins=bins, labels=labels, right=False)
    dist = df['score_bin'].value_counts().sort_index()
    total = len(df)
    for label, count in dist.items():
        pct = count / total * 100
        bar = '█' * int(pct / 2)
        print(f"    {label:>6}: {count:>4} ({pct:>5.1f}%) {bar}")


def analyze_cutoff_returns(df, price_data):
    """커트라인별 D+5 수익률 분석"""
    print("\n" + "=" * 70)
    print("2. Hot Watchlist 커트라인별 수익률 분석")
    print("=" * 70)

    # Forward return 계산
    returns = {}
    for horizon in [1, 3, 5, 10]:
        col = f'fwd_{horizon}d'
        df[col] = df.apply(
            lambda r: calculate_forward_return(
                price_data, r['stock_code'], r['snapshot_date'], horizon
            ), axis=1
        )
        returns[horizon] = col

    # 커트라인 후보
    cutoffs = [0, 45, 50, 55, 58, 60, 62, 65, 68, 70, 75]

    print(f"\n  {'커트라인':>8} | {'종목수':>6} | {'D+1 평균':>8} | {'D+5 평균':>8} | {'D+5 Hit':>7} | {'D+10 평균':>9} | {'D+5 IC':>7}")
    print(f"  {'-'*8} | {'-'*6} | {'-'*8} | {'-'*8} | {'-'*7} | {'-'*9} | {'-'*7}")

    for cutoff in cutoffs:
        subset = df[df['hybrid_score'] >= cutoff]
        n = len(subset)
        if n < 5:
            continue

        d1 = subset['fwd_1d'].dropna()
        d5 = subset['fwd_5d'].dropna()
        d10 = subset['fwd_10d'].dropna()

        d1_mean = d1.mean() if len(d1) > 0 else float('nan')
        d5_mean = d5.mean() if len(d5) > 0 else float('nan')
        d5_hit = (d5 > 0).mean() * 100 if len(d5) > 0 else float('nan')
        d10_mean = d10.mean() if len(d10) > 0 else float('nan')

        # IC (Rank Correlation between score and D+5 return)
        valid_ic = subset[['hybrid_score', 'fwd_5d']].dropna()
        if len(valid_ic) >= 10:
            ic, _ = stats.spearmanr(valid_ic['hybrid_score'], valid_ic['fwd_5d'])
        else:
            ic = float('nan')

        print(f"  >= {cutoff:>4} | {n:>6} | {d1_mean:>+7.2f}% | {d5_mean:>+7.2f}% | {d5_hit:>5.1f}% | {d10_mean:>+8.2f}% | {ic:>+6.3f}")

    # 날짜별 평균 통과 종목수 (현재 커트라인)
    print(f"\n  [날짜별 Hot Watchlist 진입 종목수 (현재 커트라인 62/BULL)]")
    for cutoff in [58, 62, 65, 70]:
        by_date = df[df['hybrid_score'] >= cutoff].groupby('snapshot_date').size()
        if len(by_date) > 0:
            print(f"    >= {cutoff}: 날짜당 평균 {by_date.mean():.1f}개, 최소 {by_date.min()}, 최대 {by_date.max()}")


def analyze_watchlist_size_impact(df, price_data):
    """MAX_WATCHLIST_SIZE 제한 영향 분석"""
    print("\n" + "=" * 70)
    print("3. MAX_WATCHLIST_SIZE 제한 영향 분석")
    print("=" * 70)

    # 날짜별로 상위 N개 vs 전체의 수익률 비교
    sizes = [10, 15, 20, 25, 30, 999]

    print(f"\n  {'Watchlist크기':>14} | {'날짜당평균':>10} | {'D+5 평균':>8} | {'D+5 Hit':>7} | {'탈락종목 D+5':>12}")
    print(f"  {'-'*14} | {'-'*10} | {'-'*8} | {'-'*7} | {'-'*12}")

    for max_size in sizes:
        included = []
        excluded = []

        for date, group in df.groupby('snapshot_date'):
            approved = group[group['hybrid_score'] >= 50].sort_values('hybrid_score', ascending=False)

            top = approved.head(max_size)
            rest = approved.iloc[max_size:]

            included.append(top)
            if len(rest) > 0:
                excluded.append(rest)

        inc_df = pd.concat(included) if included else pd.DataFrame()
        exc_df = pd.concat(excluded) if excluded else pd.DataFrame()

        # Forward returns
        inc_d5 = inc_df['fwd_5d'].dropna() if 'fwd_5d' in inc_df.columns else pd.Series()
        exc_d5 = exc_df['fwd_5d'].dropna() if 'fwd_5d' in exc_df.columns and len(exc_df) > 0 else pd.Series()

        inc_mean = inc_d5.mean() if len(inc_d5) > 0 else float('nan')
        inc_hit = (inc_d5 > 0).mean() * 100 if len(inc_d5) > 0 else float('nan')
        exc_mean = exc_d5.mean() if len(exc_d5) > 0 else float('nan')

        avg_per_date = inc_df.groupby('snapshot_date').size().mean() if len(inc_df) > 0 else 0
        label = f"Top {max_size}" if max_size < 999 else "전체(제한없음)"

        exc_str = f"{exc_mean:>+7.2f}%" if not np.isnan(exc_mean) else "     N/A"
        print(f"  {label:>14} | {avg_per_date:>9.1f} | {inc_mean:>+7.2f}% | {inc_hit:>5.1f}% | {exc_str}")


def analyze_trade_tier_returns(df, price_data):
    """trade_tier별 수익률 분석"""
    print("\n" + "=" * 70)
    print("4. Trade Tier별 수익률 분석")
    print("=" * 70)

    for tier in ['TIER1', 'RECON', 'BLOCKED']:
        subset = df[df['trade_tier'] == tier]
        if len(subset) == 0:
            continue

        d5 = subset['fwd_5d'].dropna()
        d10 = subset['fwd_10d'].dropna()

        d5_mean = d5.mean() if len(d5) > 0 else float('nan')
        d5_hit = (d5 > 0).mean() * 100 if len(d5) > 0 else float('nan')
        d10_mean = d10.mean() if len(d10) > 0 else float('nan')

        print(f"\n  [{tier}] (n={len(subset)}, D+5 데이터={len(d5)})")
        print(f"    hybrid_score 평균: {subset['hybrid_score'].mean():.1f}")
        print(f"    D+5 평균수익률: {d5_mean:>+.2f}%, Hit Rate: {d5_hit:.1f}%")
        print(f"    D+10 평균수익률: {d10_mean:>+.2f}%")

    # risk_tag별 분석
    print(f"\n  [Risk Tag별]")
    for tag in ['BULLISH', 'NEUTRAL', 'CAUTION', 'DISTRIBUTION_RISK']:
        subset = df[df['risk_tag'] == tag]
        if len(subset) < 3:
            continue
        d5 = subset['fwd_5d'].dropna()
        d5_mean = d5.mean() if len(d5) > 0 else float('nan')
        d5_hit = (d5 > 0).mean() * 100 if len(d5) > 0 else float('nan')
        print(f"    {tag:>20}: n={len(subset):>3}, D+5={d5_mean:>+.2f}%, Hit={d5_hit:.1f}%")


def analyze_redundant_filters(df):
    """이중 필터 분석: Hot Watchlist 커트라인 vs Executor 커트라인"""
    print("\n" + "=" * 70)
    print("5. 이중 필터 분석 (Scout Hot WL vs Executor 최소 점수)")
    print("=" * 70)

    # Executor에서의 recon_score_by_regime와 scout의 hot watchlist 커트라인이 동일
    # 즉, hot watchlist에 들어간 종목은 executor의 점수 체크를 무조건 통과
    cutoff = 62  # BULL 기준

    approved = df[df['hybrid_score'] >= 50]  # watchlist 진입
    hot = approved[approved['hybrid_score'] >= cutoff]  # hot watchlist 진입
    blocked_by_hot = approved[approved['hybrid_score'] < cutoff]  # hot에서 탈락

    print(f"\n  BULL 시장 기준 (커트라인 62):")
    print(f"    Watchlist 진입 (hybrid >= 50): {len(approved)}개")
    print(f"    Hot Watchlist 진입 (hybrid >= 62): {len(hot)}개")
    print(f"    Hot WL에서 탈락 (50 <= hybrid < 62): {len(blocked_by_hot)}개")

    if 'fwd_5d' in df.columns:
        hot_d5 = hot['fwd_5d'].dropna()
        blocked_d5 = blocked_by_hot['fwd_5d'].dropna()

        if len(hot_d5) > 0 and len(blocked_d5) > 0:
            print(f"\n    Hot WL 진입 종목 D+5: {hot_d5.mean():>+.2f}% (Hit: {(hot_d5>0).mean()*100:.1f}%)")
            print(f"    Hot WL 탈락 종목 D+5: {blocked_d5.mean():>+.2f}% (Hit: {(blocked_d5>0).mean()*100:.1f}%)")
            print(f"    → 탈락 종목이 {'더 나쁨' if blocked_d5.mean() < hot_d5.mean() else '오히려 더 나음 (커트라인이 기회 차단!)'}")


def print_recommendations(df):
    """최적값 제안"""
    print("\n" + "=" * 70)
    print("6. 종합 제안")
    print("=" * 70)

    if 'fwd_5d' not in df.columns:
        print("  Forward return 데이터 없음 - 제안 불가")
        return

    # 최적 커트라인 찾기: D+5 평균 * Hit Rate 복합 점수
    cutoffs = range(45, 76)
    best_score = -999
    best_cutoff = 50

    for c in cutoffs:
        subset = df[df['hybrid_score'] >= c]
        d5 = subset['fwd_5d'].dropna()
        if len(d5) < 10:
            continue
        composite = d5.mean() * (d5 > 0).mean()
        if composite > best_score:
            best_score = composite
            best_cutoff = c

    print(f"\n  최적 Hot Watchlist 커트라인 (D+5 평균×Hit Rate 기준): {best_cutoff}")
    print(f"  현재 BULL 커트라인: 62 → {'유지' if best_cutoff == 62 else f'{best_cutoff}으로 변경 권장'}")


def main():
    parser = argparse.ArgumentParser(description="Scout→Buy 필터 체인 종합 분석")
    parser.add_argument('--days', type=int, default=30, help='분석 기간 (일)')
    args = parser.parse_args()

    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=args.days)

    print(f"📊 Scout → Buy 필터 체인 종합 분석")
    print(f"   기간: {start_date} ~ {end_date} ({args.days}일)")

    init_engine()

    with session_scope() as session:
        # 1. 데이터 로딩
        print(f"\n🔄 데이터 로딩 중...")
        df = load_watchlist_with_metadata(session, start_date, end_date)

        if len(df) == 0:
            print("❌ WATCHLIST_HISTORY 데이터 없음!")
            return

        n_dates = df['snapshot_date'].nunique()
        print(f"   Watchlist 히스토리: {len(df)}건, {n_dates}일")

        # metadata 존재 비율
        has_meta = df['quant_score'].notna().sum()
        print(f"   llm_metadata 포함: {has_meta}/{len(df)} ({has_meta/len(df)*100:.0f}%)")

        # 2. Forward returns 로딩
        stock_codes = df['stock_code'].unique().tolist()
        print(f"   종목수: {len(stock_codes)}개, Forward return 계산 중...")
        price_data = load_forward_returns(session, stock_codes, start_date, end_date)

        # Forward return 컬럼 추가
        for horizon in [1, 3, 5, 10]:
            df[f'fwd_{horizon}d'] = df.apply(
                lambda r: calculate_forward_return(
                    price_data, r['stock_code'], r['snapshot_date'], horizon
                ), axis=1
            )

        fwd5_count = df['fwd_5d'].notna().sum()
        print(f"   D+5 return 계산 완료: {fwd5_count}/{len(df)}")

        # 3. 분석 실행
        analyze_score_distribution(df)
        analyze_cutoff_returns(df, price_data)
        analyze_watchlist_size_impact(df, price_data)
        analyze_trade_tier_returns(df, price_data)
        analyze_redundant_filters(df)
        print_recommendations(df)

        print(f"\n{'='*70}")
        print(f"분석 완료!")


if __name__ == "__main__":
    main()
