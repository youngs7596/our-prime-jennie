"""
Smart Money 5D 백테스트: 기존(1D 수급) vs 신규(5D smart money) 비교

Factor Alpha Study에서 발견한 smart_money_5d (IR=4.1)가
실제 scout 점수에서 승자 종목을 더 잘 선별하는지 검증.

사용법:
    .venv/bin/python scripts/backtest_smart_money.py
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from sqlalchemy import func as sa_func
from shared.db.connection import init_engine, session_scope
from shared.db.models import StockDailyPrice, StockMaster, StockInvestorTrading


# ============================================================================
# 설정
# ============================================================================
MIN_MARKET_CAP = 3000_0000_0000  # 3,000억 원
MIN_GAIN_PCT = 20.0
WINDOW = 20
LOOKBACK_DAYS = 90
ABNORMAL_DAILY_CHANGE_PCT = 50.0
BACKTEST_RANGE = 5  # 매수일 기준 ±5일 범위


def find_winner_stocks(session, df_prices, name_map, market_cap_map):
    """승자 종목 발굴 (analyze_winners.py와 동일 로직)"""
    winners = []
    stock_codes = df_prices['stock_code'].unique()

    for code in stock_codes:
        cap = market_cap_map.get(code, 0) or 0
        if cap < MIN_MARKET_CAP:
            continue

        sdf = df_prices[df_prices['stock_code'] == code].reset_index(drop=True)
        if len(sdf) < WINDOW:
            continue

        closes = sdf['close'].values
        daily_returns = np.diff(closes) / closes[:-1] * 100
        if np.any(np.abs(daily_returns) > ABNORMAL_DAILY_CHANGE_PCT):
            continue

        dates = sdf['price_date'].values
        best_gain = 0
        best_buy_idx = 0

        for i in range(len(closes) - 1):
            end_idx = min(i + WINDOW, len(closes))
            future_prices = closes[i+1:end_idx]
            if len(future_prices) == 0:
                continue
            max_future = np.max(future_prices)
            gain = (max_future - closes[i]) / closes[i] * 100
            if gain > best_gain:
                best_gain = gain
                best_buy_idx = i

        if best_gain >= MIN_GAIN_PCT:
            winners.append({
                'stock_code': code,
                'stock_name': name_map.get(code, code),
                'best_gain_pct': round(best_gain, 2),
                'buy_date': pd.Timestamp(dates[best_buy_idx]),
            })

    return pd.DataFrame(winners)


def find_loser_stocks(session, df_prices, name_map, market_cap_map, n_losers=100):
    """비승자(하락) 종목 발굴 — 대조군용"""
    losers = []
    stock_codes = df_prices['stock_code'].unique()

    for code in stock_codes:
        cap = market_cap_map.get(code, 0) or 0
        if cap < MIN_MARKET_CAP:
            continue

        sdf = df_prices[df_prices['stock_code'] == code].reset_index(drop=True)
        if len(sdf) < WINDOW:
            continue

        closes = sdf['close'].values
        daily_returns = np.diff(closes) / closes[:-1] * 100
        if np.any(np.abs(daily_returns) > ABNORMAL_DAILY_CHANGE_PCT):
            continue

        # 전체 기간 수익률
        total_return = (closes[-1] / closes[0] - 1) * 100

        if total_return < -5:  # 5% 이상 하락 종목
            dates = sdf['price_date'].values
            mid_idx = len(dates) // 2
            losers.append({
                'stock_code': code,
                'stock_name': name_map.get(code, code),
                'total_return_pct': round(total_return, 2),
                'buy_date': pd.Timestamp(dates[mid_idx]),  # 중간 시점을 기준일로
            })

    df = pd.DataFrame(losers)
    if not df.empty:
        df = df.sort_values('total_return_pct').head(n_losers).reset_index(drop=True)
    return df


def simulate_supply_demand_score_old(foreign_1d, institution_1d, avg_volume, holding_ratio):
    """기존 수급 점수 (1일, 15점 만점)"""
    score = 0.0

    # 외국인 1일 (7점)
    if foreign_1d is not None and avg_volume and avg_volume > 0:
        ratio = foreign_1d / avg_volume
        score += max(0, min(7, 3.5 + ratio / 0.05 * 3.5))
    else:
        score += 3.5

    # 기관 1일 (5점)
    if institution_1d is not None and avg_volume and avg_volume > 0:
        ratio = institution_1d / avg_volume
        score += max(0, min(5, 2.5 + ratio / 0.03 * 2.5))
    else:
        score += 2.5

    # 보유비중 (3점)
    if holding_ratio is not None:
        score += min(3, holding_ratio / 50 * 3)
    else:
        score += 1.5

    return score


def simulate_supply_demand_score_new(
    foreign_1d, institution_1d, avg_volume, holding_ratio,
    foreign_5d_sum, institution_5d_sum
):
    """신규 수급 점수 (5D smart money, 25점 만점)"""
    score = 0.0

    # 1. Smart Money 5D (12점)
    smart_money_5d = (foreign_5d_sum or 0) + (institution_5d_sum or 0)
    if avg_volume and avg_volume > 0:
        sm_ratio = smart_money_5d / avg_volume
        score += max(0, min(12, 6.0 + sm_ratio / 0.05 * 6.0))
    else:
        score += max(0, min(12, 6.0 + smart_money_5d / 5_000_000 * 6.0))

    # 2. 외국인 1일 (5점)
    if foreign_1d is not None and avg_volume and avg_volume > 0:
        ratio = foreign_1d / avg_volume
        score += max(0, min(5, 2.5 + ratio / 0.05 * 2.5))
    else:
        score += 2.5

    # 3. 기관 1일 (4점)
    if institution_1d is not None and avg_volume and avg_volume > 0:
        ratio = institution_1d / avg_volume
        score += max(0, min(4, 2.0 + ratio / 0.03 * 2.0))
    else:
        score += 2.0

    # 4. 보유비중 (4점)
    if holding_ratio is not None:
        score += min(4, holding_ratio / 50 * 4)
    else:
        score += 2.0

    return score


def get_stock_data_around_date(session, stock_code, target_date, range_days=BACKTEST_RANGE):
    """매수일 기준 과거/미래 데이터 조회 (수익률 계산용으로 미래 30일 포함)"""
    start = target_date - timedelta(days=range_days * 2)  # 영업일 감안 여유
    end = target_date + timedelta(days=45)  # D+20 영업일 ≈ 30 calendar days + 여유

    # 일봉 데이터
    prices = session.query(
        StockDailyPrice.price_date,
        StockDailyPrice.close_price,
        StockDailyPrice.volume,
    ).filter(
        StockDailyPrice.stock_code == stock_code,
        StockDailyPrice.price_date >= start,
        StockDailyPrice.price_date <= end,
    ).order_by(StockDailyPrice.price_date).all()

    # 수급 데이터 (FOREIGN_HOLDING_RATIO는 실제 테이블에 없을 수 있음)
    investor = session.query(
        StockInvestorTrading.trade_date,
        StockInvestorTrading.foreign_net_buy,
        StockInvestorTrading.institution_net_buy,
    ).filter(
        StockInvestorTrading.stock_code == stock_code,
        StockInvestorTrading.trade_date >= start,
        StockInvestorTrading.trade_date <= end,
    ).order_by(StockInvestorTrading.trade_date).all()

    return prices, investor


def backtest_stock(session, stock_code, target_date):
    """단일 종목의 기존 vs 신규 수급 점수 비교"""
    prices, investor_data = get_stock_data_around_date(session, stock_code, target_date)

    if not prices or not investor_data:
        return None

    # DataFrames 구성
    df_prices = pd.DataFrame(prices, columns=['date', 'close', 'volume'])
    df_inv = pd.DataFrame(investor_data, columns=['date', 'foreign_net', 'inst_net'])

    if df_prices.empty or df_inv.empty:
        return None

    # 평균 거래량
    avg_volume = df_prices['volume'].mean() if not df_prices['volume'].isna().all() else None

    # 타겟 날짜에 가장 가까운 거래일 찾기
    target_ts = pd.Timestamp(target_date)
    df_prices['date'] = pd.to_datetime(df_prices['date'])
    df_inv['date'] = pd.to_datetime(df_inv['date'])

    # 수급 데이터에서 타겟일 기준 최근 값
    inv_before_target = df_inv[df_inv['date'] <= target_ts]
    if inv_before_target.empty:
        return None

    latest_inv = inv_before_target.iloc[-1]
    foreign_1d = float(latest_inv['foreign_net']) if pd.notna(latest_inv['foreign_net']) else None
    institution_1d = float(latest_inv['inst_net']) if pd.notna(latest_inv['inst_net']) else None
    holding_ratio = None  # 별도 테이블이므로 여기서는 생략

    # 5일 누적
    recent_5d = inv_before_target.tail(5)
    foreign_5d = recent_5d['foreign_net'].sum() if len(recent_5d) >= 3 else None
    institution_5d = recent_5d['inst_net'].sum() if len(recent_5d) >= 3 else None

    # 기존 점수 (15점 만점 → 100점 스케일)
    old_score = simulate_supply_demand_score_old(
        foreign_1d, institution_1d, avg_volume, holding_ratio
    )
    old_score_100 = old_score / 15 * 100

    # 신규 점수 (25점 만점 → 100점 스케일)
    new_score = simulate_supply_demand_score_new(
        foreign_1d, institution_1d, avg_volume, holding_ratio,
        foreign_5d, institution_5d,
    )
    new_score_100 = new_score / 25 * 100

    # ============================================================
    # 미래 수익률 계산 (D+5, D+10, D+20)
    # ============================================================
    prices_after = df_prices[df_prices['date'] > target_ts].sort_values('date')
    buy_price_row = df_prices[df_prices['date'] <= target_ts].sort_values('date')

    if buy_price_row.empty:
        return None

    buy_price = float(buy_price_row.iloc[-1]['close'])
    ret_5d = ret_10d = ret_20d = max_ret = None

    if len(prices_after) >= 5:
        ret_5d = (float(prices_after.iloc[4]['close']) - buy_price) / buy_price * 100
    if len(prices_after) >= 10:
        ret_10d = (float(prices_after.iloc[9]['close']) - buy_price) / buy_price * 100
    if len(prices_after) >= 20:
        ret_20d = (float(prices_after.iloc[19]['close']) - buy_price) / buy_price * 100

    # 20일 내 최대 수익률
    if len(prices_after) >= 1:
        future_window = prices_after.head(20)
        max_price = future_window['close'].max()
        max_ret = (float(max_price) - buy_price) / buy_price * 100

    return {
        'old_score_raw': round(old_score, 2),
        'new_score_raw': round(new_score, 2),
        'old_score_100': round(old_score_100, 2),
        'new_score_100': round(new_score_100, 2),
        'foreign_1d': foreign_1d,
        'institution_1d': institution_1d,
        'foreign_5d': foreign_5d,
        'institution_5d': institution_5d,
        'avg_volume': avg_volume,
        'buy_price': buy_price,
        'ret_5d': round(ret_5d, 2) if ret_5d is not None else None,
        'ret_10d': round(ret_10d, 2) if ret_10d is not None else None,
        'ret_20d': round(ret_20d, 2) if ret_20d is not None else None,
        'max_ret_20d': round(max_ret, 2) if max_ret is not None else None,
    }


def run_backtest():
    """메인 백테스트 실행"""
    init_engine()

    with session_scope(readonly=True) as session:
        # 가격 데이터 로드
        cutoff_date = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).date()

        print(f"📊 최근 {LOOKBACK_DAYS}일 데이터 로드 중...")
        prices = session.query(
            StockDailyPrice.stock_code,
            StockDailyPrice.price_date,
            StockDailyPrice.close_price,
            StockDailyPrice.volume,
        ).filter(
            StockDailyPrice.price_date >= cutoff_date
        ).order_by(
            StockDailyPrice.stock_code,
            StockDailyPrice.price_date,
        ).all()

        if not prices:
            print("❌ 가격 데이터가 없습니다.")
            return

        df_prices = pd.DataFrame(prices, columns=['stock_code', 'price_date', 'close', 'volume'])
        print(f"   → {len(df_prices):,}건 ({df_prices['stock_code'].nunique():,}개 종목)")

        masters = session.query(
            StockMaster.stock_code, StockMaster.stock_name, StockMaster.market_cap
        ).all()
        name_map = {m.stock_code: m.stock_name for m in masters}
        cap_map = {m.stock_code: float(m.market_cap) if m.market_cap else 0 for m in masters}

        # 승자/비승자 종목 발굴
        print("\n🏆 승자 종목 발굴 중...")
        winners = find_winner_stocks(session, df_prices, name_map, cap_map)
        print(f"   → 승자 {len(winners)}개")

        print("📉 비승자 종목 발굴 중...")
        losers = find_loser_stocks(session, df_prices, name_map, cap_map, n_losers=len(winners))
        print(f"   → 비승자 {len(losers)}개")

        if winners.empty:
            print("❌ 승자 종목이 없습니다.")
            return

        # 백테스트 실행
        print(f"\n🔄 백테스트 실행 중...")

        winner_results = []
        for _, row in winners.iterrows():
            result = backtest_stock(session, row['stock_code'], row['buy_date'].date())
            if result:
                result['stock_code'] = row['stock_code']
                result['stock_name'] = row['stock_name']
                result['group'] = 'winner'
                winner_results.append(result)

        loser_results = []
        for _, row in losers.iterrows():
            result = backtest_stock(session, row['stock_code'], row['buy_date'].date())
            if result:
                result['stock_code'] = row['stock_code']
                result['stock_name'] = row['stock_name']
                result['group'] = 'loser'
                loser_results.append(result)

        # 결과 분석
        df_winners = pd.DataFrame(winner_results)
        df_losers = pd.DataFrame(loser_results)

        print("\n" + "=" * 70)
        print("=== Smart Money 5D 백테스트 결과 ===")
        print("=" * 70)

        if df_winners.empty:
            print("❌ 수급 데이터가 있는 승자 종목이 없습니다.")
            return

        # Hit Rate 계산 (100점 스케일 기준 60점 이상)
        HIT_THRESHOLD = 60

        w_old_hit = (df_winners['old_score_100'] >= HIT_THRESHOLD).mean() * 100
        w_new_hit = (df_winners['new_score_100'] >= HIT_THRESHOLD).mean() * 100

        w_old_avg = df_winners['old_score_100'].mean()
        w_new_avg = df_winners['new_score_100'].mean()

        print(f"\n📊 승자 종목 (n={len(df_winners)})")
        print(f"  [기존 1D 수급] Hit Rate(≥{HIT_THRESHOLD}점): {w_old_hit:.1f}%, Avg Score: {w_old_avg:.1f}")
        print(f"  [신규 5D 수급] Hit Rate(≥{HIT_THRESHOLD}점): {w_new_hit:.1f}%, Avg Score: {w_new_avg:.1f}")

        if not df_losers.empty:
            l_old_avg = df_losers['old_score_100'].mean()
            l_new_avg = df_losers['new_score_100'].mean()

            print(f"\n📊 비승자 종목 (n={len(df_losers)})")
            print(f"  [기존 1D 수급] Avg Score: {l_old_avg:.1f}")
            print(f"  [신규 5D 수급] Avg Score: {l_new_avg:.1f}")

            old_gap = w_old_avg - l_old_avg
            new_gap = w_new_avg - l_new_avg

            print(f"\n📊 Score Gap (승자 - 비승자)")
            print(f"  [기존 1D 수급] Gap: {old_gap:+.1f}점")
            print(f"  [신규 5D 수급] Gap: {new_gap:+.1f}점")

            print(f"\n🎯 개선폭")
            print(f"  Hit Rate: {w_new_hit - w_old_hit:+.1f}%p")
            print(f"  Score Gap: {new_gap - old_gap:+.1f}점")

        # ==============================================================
        # 수익률 분석: 수급 점수 상위 vs 하위 그룹 실제 수익률 비교
        # ==============================================================
        all_results = pd.concat([df_winners, df_losers], ignore_index=True) if not df_losers.empty else df_winners.copy()

        # 수익률 데이터가 있는 종목만
        has_ret = all_results['ret_5d'].notna()
        df_ret = all_results[has_ret].copy()

        if len(df_ret) < 4:
            print(f"\n⚠️ 수익률 데이터 부족 ({len(df_ret)}개)")
            print("=" * 80)
            return

        print(f"\n{'='*80}")
        print("=== 수급 점수 기준 수익률 분석 (전체 {0}개 종목) ===".format(len(df_ret)))
        print(f"{'='*80}")

        # --- 1) 신규 5D 점수 기준 Quintile 분석 ---
        df_ret['new_quintile'] = pd.qcut(df_ret['new_score_100'], q=min(5, len(df_ret)//2), labels=False, duplicates='drop')
        df_ret['old_quintile'] = pd.qcut(df_ret['old_score_100'], q=min(5, len(df_ret)//2), labels=False, duplicates='drop')

        print(f"\n📈 [신규 5D Smart Money] Quintile별 수익률")
        print(f"  {'Quintile':>10s}  {'종목수':>6s}  {'Avg점수':>8s}  {'D+5':>8s}  {'D+10':>8s}  {'D+20':>8s}  {'Max20D':>8s}")
        print("  " + "-" * 64)
        for q in sorted(df_ret['new_quintile'].unique()):
            grp = df_ret[df_ret['new_quintile'] == q]
            n = len(grp)
            avg_sc = grp['new_score_100'].mean()
            r5 = grp['ret_5d'].mean() if grp['ret_5d'].notna().any() else float('nan')
            r10 = grp['ret_10d'].mean() if grp['ret_10d'].notna().any() else float('nan')
            r20 = grp['ret_20d'].mean() if grp['ret_20d'].notna().any() else float('nan')
            mx = grp['max_ret_20d'].mean() if grp['max_ret_20d'].notna().any() else float('nan')
            label = "하위" if q == 0 else ("상위" if q == df_ret['new_quintile'].max() else f"  Q{q}")
            print(f"  {label:>10s}  {n:>6d}  {avg_sc:>8.1f}  {r5:>+7.1f}%  {r10:>+7.1f}%  {r20:>+7.1f}%  {mx:>+7.1f}%")

        print(f"\n📈 [기존 1D 수급] Quintile별 수익률")
        print(f"  {'Quintile':>10s}  {'종목수':>6s}  {'Avg점수':>8s}  {'D+5':>8s}  {'D+10':>8s}  {'D+20':>8s}  {'Max20D':>8s}")
        print("  " + "-" * 64)
        for q in sorted(df_ret['old_quintile'].unique()):
            grp = df_ret[df_ret['old_quintile'] == q]
            n = len(grp)
            avg_sc = grp['old_score_100'].mean()
            r5 = grp['ret_5d'].mean() if grp['ret_5d'].notna().any() else float('nan')
            r10 = grp['ret_10d'].mean() if grp['ret_10d'].notna().any() else float('nan')
            r20 = grp['ret_20d'].mean() if grp['ret_20d'].notna().any() else float('nan')
            mx = grp['max_ret_20d'].mean() if grp['max_ret_20d'].notna().any() else float('nan')
            label = "하위" if q == 0 else ("상위" if q == df_ret['old_quintile'].max() else f"  Q{q}")
            print(f"  {label:>10s}  {n:>6d}  {avg_sc:>8.1f}  {r5:>+7.1f}%  {r10:>+7.1f}%  {r20:>+7.1f}%  {mx:>+7.1f}%")

        # --- 2) 상위/하위 Spread ---
        new_top = df_ret[df_ret['new_quintile'] == df_ret['new_quintile'].max()]
        new_bot = df_ret[df_ret['new_quintile'] == 0]
        old_top = df_ret[df_ret['old_quintile'] == df_ret['old_quintile'].max()]
        old_bot = df_ret[df_ret['old_quintile'] == 0]

        print(f"\n📊 Quintile Spread (상위 - 하위)")
        print(f"  {'':>14s}  {'D+5':>8s}  {'D+10':>8s}  {'D+20':>8s}  {'Max20D':>8s}")
        print("  " + "-" * 48)

        for label, top, bot in [("[신규 5D]", new_top, new_bot), ("[기존 1D]", old_top, old_bot)]:
            s5 = top['ret_5d'].mean() - bot['ret_5d'].mean() if top['ret_5d'].notna().any() and bot['ret_5d'].notna().any() else float('nan')
            s10 = top['ret_10d'].mean() - bot['ret_10d'].mean() if top['ret_10d'].notna().any() and bot['ret_10d'].notna().any() else float('nan')
            s20 = top['ret_20d'].mean() - bot['ret_20d'].mean() if top['ret_20d'].notna().any() and bot['ret_20d'].notna().any() else float('nan')
            smx = top['max_ret_20d'].mean() - bot['max_ret_20d'].mean() if top['max_ret_20d'].notna().any() and bot['max_ret_20d'].notna().any() else float('nan')
            print(f"  {label:>14s}  {s5:>+7.1f}%  {s10:>+7.1f}%  {s20:>+7.1f}%  {smx:>+7.1f}%")

        # --- 3) 60점 이상 필터링 시 수익률 ---
        print(f"\n📊 60점 이상 필터링 시 평균 수익률")
        for label, col in [("[신규 5D]", 'new_score_100'), ("[기존 1D]", 'old_score_100')]:
            above = df_ret[df_ret[col] >= 60]
            below = df_ret[df_ret[col] < 60]
            if not above.empty and not below.empty:
                a5 = above['ret_5d'].mean() if above['ret_5d'].notna().any() else float('nan')
                a10 = above['ret_10d'].mean() if above['ret_10d'].notna().any() else float('nan')
                a20 = above['ret_20d'].mean() if above['ret_20d'].notna().any() else float('nan')
                amx = above['max_ret_20d'].mean() if above['max_ret_20d'].notna().any() else float('nan')
                b5 = below['ret_5d'].mean() if below['ret_5d'].notna().any() else float('nan')
                print(f"  {label} ≥60점 (n={len(above):>3d}): D+5 {a5:>+6.1f}%, D+10 {a10:>+6.1f}%, D+20 {a20:>+6.1f}%, Max {amx:>+6.1f}%")
                print(f"  {label} <60점 (n={len(below):>3d}): D+5 {b5:>+6.1f}%")
            else:
                cnt = len(above) if not above.empty else 0
                print(f"  {label} ≥60점: {cnt}개 (비교 불가)")

        # --- 4) 종목 상세 (상위 15) ---
        print(f"\n📋 종목 상세 (5D점수 상위 15)")
        print(f"  {'종목명':>12s}  {'5D점수':>6s}  {'1D점수':>6s}  {'D+5':>7s}  {'D+10':>7s}  {'D+20':>7s}  {'Max20D':>7s}")
        print("  " + "-" * 68)

        top15 = df_ret.sort_values('new_score_100', ascending=False).head(15)
        for _, r in top15.iterrows():
            r5 = f"{r['ret_5d']:>+6.1f}%" if pd.notna(r['ret_5d']) else "   N/A"
            r10 = f"{r['ret_10d']:>+6.1f}%" if pd.notna(r['ret_10d']) else "   N/A"
            r20 = f"{r['ret_20d']:>+6.1f}%" if pd.notna(r['ret_20d']) else "   N/A"
            mx = f"{r['max_ret_20d']:>+6.1f}%" if pd.notna(r['max_ret_20d']) else "   N/A"
            print(f"  {r['stock_name']:>12s}  {r['new_score_100']:>6.1f}  {r['old_score_100']:>6.1f}  {r5}  {r10}  {r20}  {mx}")

        print(f"{'='*80}")


if __name__ == '__main__':
    run_backtest()
