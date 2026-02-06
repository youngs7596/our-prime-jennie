"""
승자 종목 분석 (Step 1): 최근 3개월간 20영업일 내 +20% 이상 상승 구간이 있는 종목 발굴
- 시총 3,000억 이상
- 액면분할/병합 등 비정상 변동 제외 (하루 ±50% 이상 변동)

사용법:
    .venv/bin/python scripts/analyze_winners.py
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from sqlalchemy import func as sa_func
from shared.db.connection import init_engine, session_scope
from shared.db.models import StockDailyPrice, StockMaster


MIN_MARKET_CAP = 3000_0000_0000  # 3,000억 원
MIN_GAIN_PCT = 20.0
WINDOW = 20  # 영업일
LOOKBACK_DAYS = 90
# 하루 변동률이 이 값을 초과하면 비정상(액면분할 등)으로 판단
ABNORMAL_DAILY_CHANGE_PCT = 50.0


def find_winner_stocks(session, df_prices, name_map, market_cap_map):
    """
    승자 종목 발굴: window 영업일 내 min_gain_pct% 이상 상승 구간 탐색
    """
    winners = []
    stock_codes = df_prices['stock_code'].unique()
    filtered_by_cap = 0
    filtered_by_abnormal = 0

    print(f"🔍 {len(stock_codes):,}개 종목에서 {WINDOW}영업일 내 +{MIN_GAIN_PCT}% 상승 구간 탐색 중...")
    print(f"   (시총 ≥ {MIN_MARKET_CAP/1e8:,.0f}억, 비정상 변동 ±{ABNORMAL_DAILY_CHANGE_PCT}% 제외)")

    for code in stock_codes:
        # 시총 필터
        cap = market_cap_map.get(code, 0) or 0
        if cap < MIN_MARKET_CAP:
            filtered_by_cap += 1
            continue

        sdf = df_prices[df_prices['stock_code'] == code].reset_index(drop=True)
        if len(sdf) < WINDOW:
            continue

        closes = sdf['close'].values

        # 비정상 변동 감지 (액면분할/병합)
        daily_returns = np.diff(closes) / closes[:-1] * 100
        if np.any(np.abs(daily_returns) > ABNORMAL_DAILY_CHANGE_PCT):
            filtered_by_abnormal += 1
            continue

        dates = sdf['price_date'].values

        best_gain = 0
        best_buy_idx = 0
        best_sell_idx = 0

        # 슬라이딩 윈도우: 각 날짜를 매수일로 가정, 이후 window일 내 최대 수익률 탐색
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
                best_sell_idx = i + 1 + np.argmax(future_prices)

        if best_gain >= MIN_GAIN_PCT:
            winners.append({
                'stock_code': code,
                'stock_name': name_map.get(code, code),
                'market_cap_b': round((cap or 0) / 1e8),  # 억 단위
                'best_gain_pct': round(best_gain, 2),
                'buy_date': dates[best_buy_idx],
                'sell_date': dates[best_sell_idx],
                'buy_price': int(closes[best_buy_idx]),
                'sell_price': int(closes[best_sell_idx]),
                'holding_days': int(best_sell_idx - best_buy_idx),
                'data_points': len(sdf),
            })

    print(f"   시총 미달 제외: {filtered_by_cap}개, 비정상 변동 제외: {filtered_by_abnormal}개")

    result = pd.DataFrame(winners)
    if not result.empty:
        result = result.sort_values('best_gain_pct', ascending=False).reset_index(drop=True)

    return result


def load_price_data(session):
    """가격 데이터 + 마스터 데이터 로드"""
    cutoff_date = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).date()

    print(f"📊 최근 {LOOKBACK_DAYS}일 가격 데이터 로드 중...")
    prices = session.query(
        StockDailyPrice.stock_code,
        StockDailyPrice.price_date,
        StockDailyPrice.close_price,
        StockDailyPrice.low_price,
        StockDailyPrice.high_price,
        StockDailyPrice.volume,
    ).filter(
        StockDailyPrice.price_date >= cutoff_date
    ).order_by(
        StockDailyPrice.stock_code,
        StockDailyPrice.price_date,
    ).all()

    if not prices:
        print("❌ 가격 데이터가 없습니다.")
        return pd.DataFrame(), {}, {}

    df = pd.DataFrame(prices, columns=['stock_code', 'price_date', 'close', 'low', 'high', 'volume'])
    print(f"   → {len(df):,}건 로드 (종목 수: {df['stock_code'].nunique():,})")

    # 종목 마스터 (이름 + 시총)
    masters = session.query(
        StockMaster.stock_code, StockMaster.stock_name, StockMaster.market_cap
    ).all()
    name_map = {m.stock_code: m.stock_name for m in masters}
    cap_map = {m.stock_code: float(m.market_cap) if m.market_cap else 0 for m in masters}

    return df, name_map, cap_map


def check_data_coverage(session):
    """데이터 커버리지 통계"""
    cutoff_date = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).date()

    daily_count = session.query(sa_func.count(StockDailyPrice.stock_code)).filter(
        StockDailyPrice.price_date >= cutoff_date
    ).scalar()

    daily_stocks = session.query(sa_func.count(sa_func.distinct(StockDailyPrice.stock_code))).filter(
        StockDailyPrice.price_date >= cutoff_date
    ).scalar()

    daily_dates = session.query(sa_func.count(sa_func.distinct(StockDailyPrice.price_date))).filter(
        StockDailyPrice.price_date >= cutoff_date
    ).scalar()

    date_range = session.query(
        sa_func.min(StockDailyPrice.price_date),
        sa_func.max(StockDailyPrice.price_date)
    ).filter(
        StockDailyPrice.price_date >= cutoff_date
    ).first()

    # 시총 3,000억 이상 종목 수
    large_cap_count = session.query(sa_func.count(StockMaster.stock_code)).filter(
        StockMaster.market_cap >= MIN_MARKET_CAP
    ).scalar()

    print("=" * 60)
    print("📊 데이터 커버리지")
    print("=" * 60)
    print(f"  기간: {date_range[0]} ~ {date_range[1]} ({daily_dates}거래일)")
    print(f"  일봉: {daily_count:,}건 / {daily_stocks:,}개 종목")
    print(f"  시총 ≥ 3,000억: {large_cap_count}개 종목")

    from shared.db.models import StockInvestorTrading, NewsSentiment

    investor_count = session.query(sa_func.count(StockInvestorTrading.id)).filter(
        StockInvestorTrading.trade_date >= cutoff_date
    ).scalar()
    investor_stocks = session.query(sa_func.count(sa_func.distinct(StockInvestorTrading.stock_code))).filter(
        StockInvestorTrading.trade_date >= cutoff_date
    ).scalar()
    news_count = session.query(sa_func.count(NewsSentiment.id)).filter(
        NewsSentiment.created_at >= cutoff_date
    ).scalar()

    print(f"  수급: {investor_count:,}건 ({investor_stocks}개 종목)")
    print(f"  뉴스 감성: {news_count:,}건")
    print("=" * 60)


def main():
    init_engine()

    with session_scope(readonly=True) as session:
        check_data_coverage(session)

        print()
        df_prices, name_map, cap_map = load_price_data(session)
        if df_prices.empty:
            return

        winners = find_winner_stocks(session, df_prices, name_map, cap_map)

        if winners.empty:
            print("❌ 조건을 만족하는 승자 종목이 없습니다.")
            return

        print()
        print("=" * 90)
        print(f"🏆 승자 종목: {len(winners)}개 (시총≥3,000억, 20영업일 내 +{MIN_GAIN_PCT}%, 비정상변동 제외)")
        print("=" * 90)

        for idx, row in winners.iterrows():
            print(f"  {idx+1:3d}. {row['stock_name']:12s} ({row['stock_code']}) "
                  f"시총{row['market_cap_b']:>7,}억  "
                  f"+{row['best_gain_pct']:5.1f}% ({row['holding_days']}일)  "
                  f"{str(row['buy_date'])[:10]} {row['buy_price']:>8,}원 → "
                  f"{str(row['sell_date'])[:10]} {row['sell_price']:>8,}원")

        # 통계 요약
        print()
        print("📈 통계 요약:")
        print(f"  총 승자 종목: {len(winners)}개")
        print(f"  평균 상승률: +{winners['best_gain_pct'].mean():.1f}%")
        print(f"  중간값: +{winners['best_gain_pct'].median():.1f}%")
        print(f"  최대 상승: +{winners['best_gain_pct'].max():.1f}%")
        print(f"  평균 보유일: {winners['holding_days'].mean():.1f}일")
        print(f"  +30% 이상: {len(winners[winners['best_gain_pct'] >= 30])}개")
        print(f"  +50% 이상: {len(winners[winners['best_gain_pct'] >= 50])}개")


if __name__ == '__main__':
    main()
