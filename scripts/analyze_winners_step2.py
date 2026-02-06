"""
승자 종목 분석 (Step 2): 최적 매수 시점에 어떤 신호가 있었는지 분석

- 매수 직전 5일간의 기술적 지표, 수급, 뉴스 감성을 수집
- "좋은 매수 타이밍"의 공통 패턴을 도출

사용법:
    .venv/bin/python scripts/analyze_winners_step2.py
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict

from sqlalchemy import func as sa_func, and_
from shared.db.connection import init_engine, session_scope
from shared.db.models import (
    StockDailyPrice, StockMaster, StockInvestorTrading, NewsSentiment,
)

# Step 1과 동일한 설정
MIN_MARKET_CAP = 3000_0000_0000
MIN_GAIN_PCT = 20.0
WINDOW = 20
LOOKBACK_DAYS = 90
ABNORMAL_DAILY_CHANGE_PCT = 50.0

# 매수 전 분석 기간 (영업일 기준)
PRE_BUY_DAYS = 5


def compute_rsi(closes, period=14):
    """RSI 계산"""
    if len(closes) < period + 1:
        return None
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def compute_signals_at_buy(stock_prices_df, buy_idx):
    """
    매수 시점(buy_idx)에서의 기술적 신호 계산
    stock_prices_df: 해당 종목의 전체 가격 DataFrame (date순 정렬)
    buy_idx: 매수일의 인덱스
    """
    signals = {}
    closes = stock_prices_df['close'].values
    volumes = stock_prices_df['volume'].values
    highs = stock_prices_df['high'].values
    lows = stock_prices_df['low'].values

    buy_price = closes[buy_idx]

    # --- RSI (매수일 기준) ---
    if buy_idx >= 14:
        signals['rsi'] = compute_rsi(closes[:buy_idx + 1], period=14)
    else:
        signals['rsi'] = None

    # --- 이동평균 대비 위치 ---
    if buy_idx >= 20:
        ma20 = np.mean(closes[buy_idx - 19:buy_idx + 1])
        signals['price_vs_ma20_pct'] = round((buy_price - ma20) / ma20 * 100, 2)
    else:
        signals['price_vs_ma20_pct'] = None

    if buy_idx >= 5:
        ma5 = np.mean(closes[buy_idx - 4:buy_idx + 1])
        signals['price_vs_ma5_pct'] = round((buy_price - ma5) / ma5 * 100, 2)
    else:
        signals['price_vs_ma5_pct'] = None

    # --- 거래량 비율 (당일 vs 20일 평균) ---
    if buy_idx >= 20:
        avg_vol_20 = np.mean(volumes[buy_idx - 20:buy_idx])
        if avg_vol_20 > 0:
            signals['volume_ratio'] = round(volumes[buy_idx] / avg_vol_20, 2)
        else:
            signals['volume_ratio'] = None
    else:
        signals['volume_ratio'] = None

    # --- 최근 5일 거래량 추세 (5일 평균 / 20일 평균) ---
    if buy_idx >= 20:
        avg_vol_5 = np.mean(volumes[buy_idx - 4:buy_idx + 1])
        avg_vol_20 = np.mean(volumes[buy_idx - 20:buy_idx])
        if avg_vol_20 > 0:
            signals['vol_trend_5d_vs_20d'] = round(avg_vol_5 / avg_vol_20, 2)
        else:
            signals['vol_trend_5d_vs_20d'] = None
    else:
        signals['vol_trend_5d_vs_20d'] = None

    # --- 최근 고점 대비 하락폭 (pullback depth) ---
    if buy_idx >= 10:
        recent_high = np.max(highs[max(0, buy_idx - 20):buy_idx])
        signals['pullback_from_high_pct'] = round((buy_price - recent_high) / recent_high * 100, 2)
    else:
        signals['pullback_from_high_pct'] = None

    # --- 최근 5일 수익률 (매수 전 모멘텀) ---
    if buy_idx >= 5:
        price_5d_ago = closes[buy_idx - 5]
        signals['return_5d_before'] = round((buy_price - price_5d_ago) / price_5d_ago * 100, 2)
    else:
        signals['return_5d_before'] = None

    # --- 최근 10일 수익률 ---
    if buy_idx >= 10:
        price_10d_ago = closes[buy_idx - 10]
        signals['return_10d_before'] = round((buy_price - price_10d_ago) / price_10d_ago * 100, 2)
    else:
        signals['return_10d_before'] = None

    # --- 볼린저밴드 위치 (20일, 2σ) ---
    if buy_idx >= 20:
        window_closes = closes[buy_idx - 19:buy_idx + 1]
        bb_mid = np.mean(window_closes)
        bb_std = np.std(window_closes)
        if bb_std > 0:
            signals['bb_position'] = round((buy_price - bb_mid) / (2 * bb_std), 2)  # -1~+1 범위
        else:
            signals['bb_position'] = None
    else:
        signals['bb_position'] = None

    return signals


def analyze_investor_signals(session, stock_code, buy_date, pre_days=5):
    """매수 전 수급 신호 분석"""
    # buy_date 기준 이전 pre_days 거래일 데이터
    start_date = buy_date - timedelta(days=pre_days * 2)  # 주말/공휴일 여유

    rows = session.query(
        StockInvestorTrading.trade_date,
        StockInvestorTrading.foreign_net_buy,
        StockInvestorTrading.institution_net_buy,
        StockInvestorTrading.individual_net_buy,
    ).filter(
        StockInvestorTrading.stock_code == stock_code,
        StockInvestorTrading.trade_date >= start_date,
        StockInvestorTrading.trade_date <= buy_date,
    ).order_by(StockInvestorTrading.trade_date).all()

    signals = {
        'foreign_net_5d': None,
        'institution_net_5d': None,
        'individual_net_5d': None,
        'investor_data_count': len(rows),
    }

    if not rows:
        return signals

    # 최근 5일 합산
    recent = rows[-pre_days:] if len(rows) >= pre_days else rows
    signals['foreign_net_5d'] = sum(float(r.foreign_net_buy or 0) for r in recent)
    signals['institution_net_5d'] = sum(float(r.institution_net_buy or 0) for r in recent)
    signals['individual_net_5d'] = sum(float(r.individual_net_buy or 0) for r in recent)

    return signals


def analyze_news_signals(session, stock_code, buy_date, pre_days=5):
    """매수 전 뉴스 감성 신호 분석"""
    start_date = buy_date - timedelta(days=pre_days * 2)

    rows = session.query(
        NewsSentiment.sentiment_score,
        NewsSentiment.created_at,
    ).filter(
        NewsSentiment.stock_code == stock_code,
        NewsSentiment.created_at >= start_date,
        NewsSentiment.created_at <= buy_date + timedelta(days=1),
    ).all()

    signals = {
        'news_count': len(rows),
        'news_avg_sentiment': None,
        'news_positive_ratio': None,
    }

    if not rows:
        return signals

    scores = [float(r.sentiment_score) for r in rows if r.sentiment_score is not None]
    if scores:
        signals['news_avg_sentiment'] = round(np.mean(scores), 1)
        signals['news_positive_ratio'] = round(sum(1 for s in scores if s >= 60) / len(scores) * 100, 1)

    return signals


def main():
    init_engine()

    with session_scope(readonly=True) as session:
        # Step 1 재실행: 승자 종목 + 매수일 식별
        from analyze_winners import load_price_data, find_winner_stocks
        df_prices, name_map, cap_map = load_price_data(session)
        if df_prices.empty:
            return

        winners = find_winner_stocks(session, df_prices, name_map, cap_map)
        if winners.empty:
            print("❌ 승자 종목 없음")
            return

        print(f"\n🔬 Step 2: {len(winners)}개 승자 종목의 매수 시점 신호 분석 시작...\n")

        all_signals = []

        for idx, row in winners.iterrows():
            code = row['stock_code']
            raw_buy_date = row['buy_date']
            buy_date_ts = pd.Timestamp(raw_buy_date)

            # 기술적 신호
            sdf = df_prices[df_prices['stock_code'] == code].reset_index(drop=True)
            # buy_date에 해당하는 인덱스 찾기
            sdf['_ts'] = sdf['price_date'].apply(lambda x: pd.Timestamp(x).normalize())
            buy_idx = sdf.index[sdf['_ts'] == buy_date_ts.normalize()].tolist()
            buy_idx = buy_idx[0] if buy_idx else None

            if buy_idx is None or buy_idx < 14:
                continue

            buy_date = buy_date_ts.date()

            tech_signals = compute_signals_at_buy(sdf, buy_idx)

            # 수급 신호
            investor_signals = analyze_investor_signals(session, code, buy_date)

            # 뉴스 감성 신호
            news_signals = analyze_news_signals(session, code, buy_date)

            combined = {
                'stock_code': code,
                'stock_name': row['stock_name'],
                'gain_pct': row['best_gain_pct'],
                'buy_date': str(buy_date),
                'holding_days': row['holding_days'],
                **tech_signals,
                **investor_signals,
                **news_signals,
            }
            all_signals.append(combined)

            if (idx + 1) % 20 == 0:
                print(f"   ... {idx + 1}/{len(winners)} 처리 완료")

        print(f"   ✅ {len(all_signals)}개 종목 신호 수집 완료\n")

        if not all_signals:
            print("❌ 분석 가능한 데이터가 없습니다.")
            return

        df_signals = pd.DataFrame(all_signals)

        # ============================================================
        # 패턴 분석 리포트
        # ============================================================
        print("=" * 80)
        print("📊 최적 매수 시점의 공통 신호 패턴")
        print("=" * 80)

        # 1. 기술적 지표 통계
        print("\n[1] 기술적 지표 (매수일 기준)")
        print("-" * 50)
        tech_cols = [
            ('rsi', 'RSI(14)'),
            ('price_vs_ma20_pct', '종가 vs MA20 (%)'),
            ('price_vs_ma5_pct', '종가 vs MA5 (%)'),
            ('volume_ratio', '거래량 비율 (당일/20일평균)'),
            ('vol_trend_5d_vs_20d', '거래량 추세 (5일/20일)'),
            ('pullback_from_high_pct', '고점 대비 하락폭 (%)'),
            ('return_5d_before', '직전 5일 수익률 (%)'),
            ('return_10d_before', '직전 10일 수익률 (%)'),
            ('bb_position', '볼린저밴드 위치 (-1~+1)'),
        ]
        for col, label in tech_cols:
            vals = df_signals[col].dropna()
            if len(vals) > 0:
                print(f"  {label:30s}  중간값: {vals.median():>7.1f}  평균: {vals.mean():>7.1f}  "
                      f"[{vals.quantile(0.25):>6.1f} ~ {vals.quantile(0.75):>6.1f}]")

        # 2. 수급 신호
        print(f"\n[2] 수급 신호 (매수 전 5일 합산)")
        print("-" * 50)
        for col, label in [
            ('foreign_net_5d', '외국인 순매수 (억)'),
            ('institution_net_5d', '기관 순매수 (억)'),
            ('individual_net_5d', '개인 순매수 (억)'),
        ]:
            vals = df_signals[col].dropna()
            if len(vals) > 0:
                # 억 단위로 변환
                vals_b = vals / 1e8
                positive_ratio = (vals > 0).sum() / len(vals) * 100
                print(f"  {label:30s}  중간값: {vals_b.median():>8.1f}억  "
                      f"순매수 비율: {positive_ratio:>5.1f}%  "
                      f"[{vals_b.quantile(0.25):>7.1f} ~ {vals_b.quantile(0.75):>7.1f}]")

        # 3. 뉴스 감성
        print(f"\n[3] 뉴스 감성 (매수 전 5일)")
        print("-" * 50)
        for col, label in [
            ('news_count', '뉴스 건수'),
            ('news_avg_sentiment', '평균 감성 점수 (0~100)'),
            ('news_positive_ratio', '긍정 뉴스 비율 (%)'),
        ]:
            vals = df_signals[col].dropna()
            if len(vals) > 0:
                print(f"  {label:30s}  중간값: {vals.median():>7.1f}  평균: {vals.mean():>7.1f}  "
                      f"[{vals.quantile(0.25):>6.1f} ~ {vals.quantile(0.75):>6.1f}]")

        # ============================================================
        # 상위 vs 하위 비교 (상승률 기준)
        # ============================================================
        print("\n" + "=" * 80)
        print("📊 상승률 상위 30% vs 하위 30% 비교")
        print("=" * 80)

        top_cutoff = df_signals['gain_pct'].quantile(0.7)
        bottom_cutoff = df_signals['gain_pct'].quantile(0.3)

        top = df_signals[df_signals['gain_pct'] >= top_cutoff]
        bottom = df_signals[df_signals['gain_pct'] <= bottom_cutoff]

        print(f"  상위 그룹: {len(top)}개 (≥+{top_cutoff:.0f}%), 하위 그룹: {len(bottom)}개 (≤+{bottom_cutoff:.0f}%)")
        print()

        compare_cols = [
            ('rsi', 'RSI(14)'),
            ('price_vs_ma20_pct', '종가 vs MA20 (%)'),
            ('volume_ratio', '거래량 비율'),
            ('vol_trend_5d_vs_20d', '거래량 추세'),
            ('pullback_from_high_pct', '고점대비 하락 (%)'),
            ('return_5d_before', '직전5일 수익률 (%)'),
            ('bb_position', '볼린저 위치'),
            ('news_avg_sentiment', '뉴스 감성'),
            ('news_positive_ratio', '긍정뉴스 비율 (%)'),
        ]

        print(f"  {'지표':25s}  {'상위30% 중간값':>14s}  {'하위30% 중간값':>14s}  {'차이':>8s}")
        print("  " + "-" * 70)
        for col, label in compare_cols:
            top_vals = top[col].dropna()
            bot_vals = bottom[col].dropna()
            if len(top_vals) > 0 and len(bot_vals) > 0:
                t_med = top_vals.median()
                b_med = bot_vals.median()
                diff = t_med - b_med
                marker = " ⬆️" if abs(diff) > 2 else ""
                print(f"  {label:25s}  {t_med:>14.1f}  {b_med:>14.1f}  {diff:>+7.1f}{marker}")

        # 수급 비교 (억 단위)
        print()
        for col, label in [
            ('foreign_net_5d', '외인 5일 순매수'),
            ('institution_net_5d', '기관 5일 순매수'),
        ]:
            top_vals = (top[col].dropna() / 1e8)
            bot_vals = (bottom[col].dropna() / 1e8)
            if len(top_vals) > 0 and len(bot_vals) > 0:
                t_med = top_vals.median()
                b_med = bot_vals.median()
                t_pos = (top_vals > 0).sum() / len(top_vals) * 100
                b_pos = (bot_vals > 0).sum() / len(bot_vals) * 100
                print(f"  {label:25s}  {t_med:>10.1f}억 ({t_pos:.0f}%+)  {b_med:>10.1f}억 ({b_pos:.0f}%+)")

        # ============================================================
        # 핵심 인사이트 요약
        # ============================================================
        print("\n" + "=" * 80)
        print("💡 핵심 인사이트 요약")
        print("=" * 80)

        rsi_vals = df_signals['rsi'].dropna()
        pullback_vals = df_signals['pullback_from_high_pct'].dropna()
        vol_vals = df_signals['volume_ratio'].dropna()
        ret5_vals = df_signals['return_5d_before'].dropna()

        if len(rsi_vals) > 0:
            print(f"  1. RSI: 중간값 {rsi_vals.median():.0f} → ", end="")
            if rsi_vals.median() < 40:
                print("과매도 구간에서 매수 진입이 효과적")
            elif rsi_vals.median() < 55:
                print("중립~약간 저평가 구간에서 매수 진입")
            else:
                print("모멘텀 추종 (상승 중 매수) 패턴")

        if len(pullback_vals) > 0:
            print(f"  2. 고점대비 하락: 중간값 {pullback_vals.median():.1f}% → ", end="")
            if pullback_vals.median() < -10:
                print("큰 눌림 후 반등 매수 패턴")
            elif pullback_vals.median() < -3:
                print("적정 눌림 후 매수 패턴")
            else:
                print("고점 근처에서 돌파 매수 패턴")

        if len(vol_vals) > 0:
            print(f"  3. 거래량: 중간값 {vol_vals.median():.1f}x → ", end="")
            if vol_vals.median() > 2.0:
                print("거래량 급증이 매수 시그널")
            elif vol_vals.median() > 1.2:
                print("평균 이상 거래량에서 진입")
            else:
                print("조용한 구간에서 매수 (선취매)")

        if len(ret5_vals) > 0:
            print(f"  4. 직전5일 수익률: 중간값 {ret5_vals.median():.1f}% → ", end="")
            if ret5_vals.median() < -3:
                print("하락 후 반등 포착 전략")
            elif ret5_vals.median() < 3:
                print("횡보 구간 이탈 전략")
            else:
                print("상승 초기 추격 진입 전략")


if __name__ == '__main__':
    main()
