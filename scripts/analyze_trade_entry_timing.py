"""
Trade Entry Timing Analysis — 매수 타이밍 & 추격매수 분석

매매 데이터에서 전략별 성과, 당일 상승률 vs 실현 수익, Watchlist 지연일 분석.

사용법:
    .venv/bin/python scripts/analyze_trade_entry_timing.py
    .venv/bin/python scripts/analyze_trade_entry_timing.py --days 60
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import argparse
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from sqlalchemy import text

from shared.db.connection import init_engine, session_scope


def load_buy_trades(session, start_date):
    """TRADELOG에서 BUY 거래 조회"""
    query = text("""
        SELECT
            t.LOG_DATE,
            t.STOCK_CODE,
            t.STOCK_NAME,
            t.STRATEGY_SIGNAL,
            t.ENTRY_PRICE,
            t.KEY_METRICS_JSON,
            t.TOTAL_AMOUNT
        FROM TRADELOG t
        WHERE t.ACTION = 'BUY'
          AND t.LOG_DATE >= :start_date
        ORDER BY t.LOG_DATE
    """)
    rows = session.execute(query, {"start_date": start_date}).fetchall()
    df = pd.DataFrame(rows, columns=[
        'log_date', 'stock_code', 'stock_name', 'strategy',
        'entry_price', 'key_metrics_json', 'total_amount'
    ])
    return df


def load_daily_prices(session, stock_codes, start_date):
    """일별 가격 데이터 로드"""
    if not stock_codes:
        return pd.DataFrame()
    codes_str = ",".join([f"'{c}'" for c in stock_codes])
    query = text(f"""
        SELECT STOCK_CODE, PRICE_DATE, OPEN_PRICE, CLOSE_PRICE, HIGH_PRICE, LOW_PRICE
        FROM STOCK_DAILY_PRICES_3Y
        WHERE STOCK_CODE IN ({codes_str})
          AND PRICE_DATE >= DATE_SUB(:start_date, INTERVAL 5 DAY)
        ORDER BY STOCK_CODE, PRICE_DATE
    """)
    rows = session.execute(query, {"start_date": start_date}).fetchall()
    return pd.DataFrame(rows, columns=[
        'stock_code', 'price_date', 'open_price', 'close_price', 'high_price', 'low_price'
    ])


def load_watchlist_history(session, stock_codes, start_date):
    """Watchlist 진입 히스토리 로드"""
    if not stock_codes:
        return pd.DataFrame()
    codes_str = ",".join([f"'{c}'" for c in stock_codes])
    query = text(f"""
        SELECT STOCK_CODE, MIN(SNAPSHOT_DATE) AS first_seen
        FROM WATCHLIST_HISTORY
        WHERE STOCK_CODE IN ({codes_str})
          AND SNAPSHOT_DATE >= DATE_SUB(:start_date, INTERVAL 10 DAY)
        GROUP BY STOCK_CODE
    """)
    rows = session.execute(query, {"start_date": start_date}).fetchall()
    return pd.DataFrame(rows, columns=['stock_code', 'first_seen'])


def calculate_forward_returns(trades_df, prices_df):
    """각 매수에 대해 D+1, D+3, D+5 수익률 계산"""
    results = []
    for _, trade in trades_df.iterrows():
        code = trade['stock_code']
        buy_date = trade['log_date']
        buy_price = trade['entry_price']
        if not buy_price or buy_price <= 0:
            continue
        
        stock_prices = prices_df[prices_df['stock_code'] == code].sort_values('price_date')
        future_prices = stock_prices[stock_prices['price_date'] > pd.Timestamp(buy_date).date() 
                                     if hasattr(buy_date, 'date') else stock_prices['price_date'] > buy_date]
        
        # Open price on buy date (for intraday gain calculation)
        buy_date_val = buy_date.date() if hasattr(buy_date, 'date') else buy_date
        same_day = stock_prices[stock_prices['price_date'] == buy_date_val]
        open_price = same_day['open_price'].iloc[0] if len(same_day) > 0 else None
        intraday_gain = ((buy_price - open_price) / open_price * 100) if open_price and open_price > 0 else None
        
        row = {
            'log_date': buy_date,
            'stock_code': code,
            'stock_name': trade['stock_name'],
            'strategy': trade['strategy'],
            'entry_price': buy_price,
            'open_price': open_price,
            'intraday_gain_pct': intraday_gain,
            'total_amount': trade.get('total_amount', 0),
        }
        
        for horizon, label in [(1, 'fwd_d1'), (3, 'fwd_d3'), (5, 'fwd_d5')]:
            if len(future_prices) >= horizon:
                future_close = future_prices.iloc[horizon - 1]['close_price']
                row[label] = ((future_close - buy_price) / buy_price) * 100
            else:
                row[label] = None
        
        results.append(row)
    
    return pd.DataFrame(results)


def analyze_by_strategy(df):
    """전략별 성과 분석"""
    print("\n" + "=" * 70)
    print("📊 전략별 매수 성과")
    print("=" * 70)
    
    for strat in df['strategy'].unique():
        subset = df[df['strategy'] == strat]
        d5 = subset['fwd_d5'].dropna()
        hit = (d5 > 0).mean() * 100 if len(d5) > 0 else 0
        avg_gain = subset['intraday_gain_pct'].dropna().mean()
        print(f"\n  [{strat}] 매수 {len(subset)}건")
        print(f"    D+5 평균: {d5.mean():.2f}%  |  Hit Rate: {hit:.1f}%  |  매수시 상승률: {avg_gain:.1f}%")


def analyze_chase_buy_inflection(df):
    """당일 상승률 vs 실현수익 — 추격매수 변곡점 분석"""
    print("\n" + "=" * 70)
    print("📈 당일 상승률 구간별 D+5 수익률 (추격매수 변곡점)")
    print("=" * 70)
    
    valid = df.dropna(subset=['intraday_gain_pct', 'fwd_d5'])
    if valid.empty:
        print("  데이터 부족")
        return
    
    bins = [-100, -2, 0, 1, 2, 3, 5, 7, 100]
    labels = ['<-2%', '-2~0%', '0~1%', '1~2%', '2~3%', '3~5%', '5~7%', '7%+']
    valid = valid.copy()
    valid['gain_bin'] = pd.cut(valid['intraday_gain_pct'], bins=bins, labels=labels)
    
    for label in labels:
        subset = valid[valid['gain_bin'] == label]
        if len(subset) == 0:
            continue
        d5 = subset['fwd_d5']
        hit = (d5 > 0).mean() * 100
        print(f"  {label:>8s}: {len(subset):3d}건  |  D+5 avg: {d5.mean():+.2f}%  |  Hit: {hit:.0f}%")


def analyze_entry_delay(df, watchlist_df):
    """Watchlist 등록 후 매수까지 지연일 분석"""
    print("\n" + "=" * 70)
    print("⏱️  Watchlist 등록 → 매수 지연일 분석")
    print("=" * 70)
    
    if watchlist_df.empty:
        print("  Watchlist 데이터 없음")
        return
    
    merged = df.merge(watchlist_df, on='stock_code', how='left')
    merged['delay_days'] = None
    
    for idx, row in merged.iterrows():
        if pd.notna(row.get('first_seen')) and pd.notna(row.get('log_date')):
            buy_d = row['log_date'].date() if hasattr(row['log_date'], 'date') else row['log_date']
            wl_d = row['first_seen'].date() if hasattr(row['first_seen'], 'date') else row['first_seen']
            merged.at[idx, 'delay_days'] = (buy_d - wl_d).days
    
    valid = merged.dropna(subset=['delay_days', 'fwd_d5'])
    if valid.empty:
        print("  데이터 부족")
        return
    
    for d in sorted(valid['delay_days'].unique()):
        subset = valid[valid['delay_days'] == d]
        d5 = subset['fwd_d5']
        hit = (d5 > 0).mean() * 100
        print(f"  D+{int(d):2d}: {len(subset):3d}건  |  D+5 avg: {d5.mean():+.2f}%  |  Hit: {hit:.0f}%")


def analyze_by_hour(df):
    """매수 시간대별 분석"""
    print("\n" + "=" * 70)
    print("🕐 매수 시간대별 D+5 수익률 (KST)")
    print("=" * 70)
    
    valid = df.dropna(subset=['fwd_d5']).copy()
    if valid.empty:
        print("  데이터 부족")
        return
    
    valid['hour'] = valid['log_date'].apply(
        lambda x: x.hour if hasattr(x, 'hour') else 0
    )
    
    for h in sorted(valid['hour'].unique()):
        subset = valid[valid['hour'] == h]
        d5 = subset['fwd_d5']
        hit = (d5 > 0).mean() * 100
        print(f"  {h:02d}시: {len(subset):3d}건  |  D+5 avg: {d5.mean():+.2f}%  |  Hit: {hit:.0f}%")


def main():
    parser = argparse.ArgumentParser(description="Trade Entry Timing Analysis")
    parser.add_argument("--days", type=int, default=30, help="분석 기간 (일)")
    args = parser.parse_args()

    init_engine()
    start_date = (datetime.now() - timedelta(days=args.days)).strftime('%Y-%m-%d')

    print(f"🔍 Trade Entry Timing Analysis (최근 {args.days}일)")
    print(f"   기간: {start_date} ~ {datetime.now().strftime('%Y-%m-%d')}")

    with session_scope(readonly=True) as session:
        # 1. 매수 거래 로드
        trades = load_buy_trades(session, start_date)
        if trades.empty:
            print("❌ 매수 거래 데이터 없음")
            return

        print(f"   총 매수 거래: {len(trades)}건")

        stock_codes = trades['stock_code'].unique().tolist()

        # 2. 일별 가격 로드
        prices = load_daily_prices(session, stock_codes, start_date)

        # 3. Watchlist 히스토리 로드
        watchlist = load_watchlist_history(session, stock_codes, start_date)

        # 4. Forward Return 계산
        analysis_df = calculate_forward_returns(trades, prices)
        if analysis_df.empty:
            print("❌ Forward Return 계산 실패")
            return

        print(f"   분석 가능 건수: {len(analysis_df)}건")

        # 5. 분석 실행
        analyze_by_strategy(analysis_df)
        analyze_chase_buy_inflection(analysis_df)
        analyze_entry_delay(analysis_df, watchlist)
        analyze_by_hour(analysis_df)

    print("\n✅ 분석 완료")


if __name__ == "__main__":
    main()
