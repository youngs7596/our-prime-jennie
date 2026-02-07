"""
P1 패치 dry-run: 각 패치가 watchlist 종목 점수에 미치는 영향을 측정
- 최근 watchlist 종목에 대해 현재 로직 vs 패치별 점수 변화를 보여줌
- 민지 피드백: 효과 분리를 위해 각 패치별 before/after 확인 필요

사용법: .venv/bin/python scripts/dryrun_p1_patches.py
"""
import os
import sys
import logging
import pandas as pd
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from shared.db.connection import init_engine, session_scope
from shared.db.models import StockMaster
from sqlalchemy import text
import shared.database as database

logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def get_recent_watchlist_codes(session, days=7):
    """최근 N일간 watchlist에 등장한 종목 코드 조회"""
    query = text("""
        SELECT DISTINCT STOCK_CODE, STOCK_NAME
        FROM WATCHLIST_HISTORY
        WHERE CREATED_AT >= DATE_SUB(NOW(), INTERVAL :days DAY)
        ORDER BY STOCK_CODE
    """)
    rows = session.execute(query, {'days': days}).fetchall()
    return [(r[0], r[1]) for r in rows]


def get_stock_data(session, code, days=150):
    """종목 일봉 + 투자자 매매 데이터 조회"""
    query = text("""
        SELECT PRICE_DATE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, CLOSE_PRICE, VOLUME
        FROM STOCK_DAILY_PRICES_3Y
        WHERE STOCK_CODE = :code
        AND PRICE_DATE >= DATE_SUB(NOW(), INTERVAL :days DAY)
        AND VOLUME > 0
        ORDER BY PRICE_DATE
    """)
    df = pd.read_sql(query, session.bind, params={'code': code, 'days': days})

    inv_query = text("""
        SELECT TRADE_DATE, FOREIGN_NET_BUY, INSTITUTION_NET_BUY
        FROM STOCK_INVESTOR_TRADING
        WHERE STOCK_CODE = :code
        AND TRADE_DATE >= DATE_SUB(NOW(), INTERVAL 30 DAY)
        ORDER BY TRADE_DATE
    """)
    inv_df = pd.read_sql(inv_query, session.bind, params={'code': code})

    return df, inv_df


def calc_rsi(close_series, period=14):
    delta = close_series.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else None


def analyze_stock(daily_df, inv_df):
    """각 패치의 영향을 독립적으로 측정"""
    result = {
        'has_data': len(daily_df) >= 30,
    }
    if not result['has_data']:
        return result

    close = daily_df['CLOSE_PRICE'].astype(float)
    current_price = float(close.iloc[-1])

    # 기본 지표
    rsi = calc_rsi(close)
    result['rsi'] = rsi
    result['price'] = current_price

    # 6M/1M 모멘텀
    if len(daily_df) >= 120:
        result['mom_6m'] = (current_price / float(close.iloc[-120]) - 1) * 100
    if len(daily_df) >= 20:
        result['mom_1m'] = (current_price / float(close.iloc[-20]) - 1) * 100

    # P1-2: Recon Protection 영향
    # 기존: 모멘텀>=20 AND RSI 50~70 → 보호
    # 변경: 모멘텀>=20 AND RSI 50~59 AND 1M>0 → 보호
    mom_1m = result.get('mom_1m', 0)
    if rsi is not None:
        was_protected = (rsi >= 50 and rsi <= 70)  # 기존 조건 (모멘텀 조건 가정 충족)
        now_protected = (rsi >= 50 and rsi < 60 and mom_1m > 0)
        result['recon_was_protected'] = was_protected
        result['recon_now_protected'] = now_protected
        result['recon_changed'] = was_protected and not now_protected
        if result['recon_changed']:
            # RSI 60-70 구간에서 보호 해제되면 점수 하락
            if 60 <= rsi <= 70:
                result['recon_score_impact'] = '보호해제 (RSI 60+)'
            elif mom_1m <= 0:
                result['recon_score_impact'] = '보호해제 (1M 하락중)'
            else:
                result['recon_score_impact'] = '보호 유지'

    # P1-3: 고점 근접 + 과열 감점
    if len(daily_df) >= 20 and rsi is not None:
        peak_20d = daily_df['HIGH_PRICE'].astype(float).iloc[-20:].max()
        drawdown = (current_price - peak_20d) / peak_20d * 100
        result['drawdown_20d'] = drawdown

        peak_penalty = 0.0
        if drawdown > -3 and rsi > 70:
            peak_penalty = -1.5
        elif drawdown > -2 and rsi > 65:
            peak_penalty = -1.0
        result['peak_penalty'] = peak_penalty

    # P1-4: 수급 추세 반전
    if inv_df is not None and len(inv_df) >= 10:
        prev_5d = inv_df.iloc[-10:-5]['FOREIGN_NET_BUY'].sum()
        recent_5d = inv_df.tail(5)['FOREIGN_NET_BUY'].sum()
        result['foreign_prev_5d'] = int(prev_5d)
        result['foreign_recent_5d'] = int(recent_5d)

        if prev_5d > 0 and recent_5d < 0:
            result['flow_reversal'] = 'SELL_TURN (-2pts)'
        elif prev_5d < 0 and recent_5d > 0:
            result['flow_reversal'] = 'BUY_TURN (+1.5pts)'
        else:
            result['flow_reversal'] = 'NO_CHANGE'

    return result


def main():
    init_engine()

    with session_scope(readonly=True) as session:
        codes = get_recent_watchlist_codes(session, days=7)
        if not codes:
            print("최근 7일 watchlist 종목이 없습니다.")
            return

        print(f"=== P1 Dry-Run: 최근 7일 Watchlist {len(codes)}개 종목 ===")
        print(f"실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print()

        # P1-2 영향
        print("─" * 80)
        print("[P1-2] Recon Protection 강화 (RSI 60+ 보호 해제, 1M 모멘텀 양수 필수)")
        print("─" * 80)
        recon_affected = []

        for code, name in codes:
            daily_df, inv_df = get_stock_data(session, code)
            info = analyze_stock(daily_df, inv_df)
            if not info.get('has_data'):
                continue
            if info.get('recon_changed'):
                recon_affected.append({
                    'code': code, 'name': name,
                    'rsi': info.get('rsi'),
                    'mom_1m': info.get('mom_1m'),
                    'impact': info.get('recon_score_impact', ''),
                })

        if recon_affected:
            print(f"  영향 종목: {len(recon_affected)}개")
            for s in sorted(recon_affected, key=lambda x: -(x.get('rsi') or 0)):
                print(f"  {s['name']:12s}({s['code']}) RSI={s['rsi']:.0f} 1M={s['mom_1m']:+.1f}% → {s['impact']}")
        else:
            print("  영향 종목: 0개 (현재 watchlist에 RSI 50-70 보호 대상 없음)")
        print()

        # P1-3 영향
        print("─" * 80)
        print("[P1-3] 고점 근접 + 과열 감점 (DD>-3%+RSI>70:-1.5, DD>-2%+RSI>65:-1.0)")
        print("─" * 80)
        peak_affected = []

        for code, name in codes:
            daily_df, inv_df = get_stock_data(session, code)
            info = analyze_stock(daily_df, inv_df)
            if not info.get('has_data'):
                continue
            if info.get('peak_penalty', 0) < 0:
                peak_affected.append({
                    'code': code, 'name': name,
                    'rsi': info.get('rsi'),
                    'drawdown': info.get('drawdown_20d'),
                    'penalty': info.get('peak_penalty'),
                })

        if peak_affected:
            print(f"  영향 종목: {len(peak_affected)}개")
            for s in sorted(peak_affected, key=lambda x: x['penalty']):
                print(f"  {s['name']:12s}({s['code']}) RSI={s['rsi']:.0f} DD={s['drawdown']:.1f}% → {s['penalty']:+.1f}점")
        else:
            print("  영향 종목: 0개")
        print()

        # P1-4 영향
        print("─" * 80)
        print("[P1-4] 수급 추세 반전 (양→음:-2, 음→양:+1.5)")
        print("─" * 80)
        flow_affected = []

        for code, name in codes:
            daily_df, inv_df = get_stock_data(session, code)
            info = analyze_stock(daily_df, inv_df)
            if not info.get('has_data'):
                continue
            reversal = info.get('flow_reversal', 'NO_CHANGE')
            if reversal != 'NO_CHANGE':
                flow_affected.append({
                    'code': code, 'name': name,
                    'prev': info.get('foreign_prev_5d'),
                    'recent': info.get('foreign_recent_5d'),
                    'reversal': reversal,
                })

        if flow_affected:
            print(f"  영향 종목: {len(flow_affected)}개")
            for s in flow_affected:
                print(f"  {s['name']:12s}({s['code']}) 이전5D={s['prev']:+,d} → 최근5D={s['recent']:+,d} → {s['reversal']}")
        else:
            print("  영향 종목: 0개")

        print()
        print("─" * 80)
        print("[요약] 전체 영향도")
        print("─" * 80)
        print(f"  P1-2 Recon 보호해제: {len(recon_affected)}개 종목")
        print(f"  P1-3 고점+과열 감점: {len(peak_affected)}개 종목")
        print(f"  P1-4 수급 추세 반전: {len(flow_affected)}개 종목")
        total_affected = len(set(
            [s['code'] for s in recon_affected] +
            [s['code'] for s in peak_affected] +
            [s['code'] for s in flow_affected]
        ))
        print(f"  총 영향 종목 (중복 제거): {total_affected}개 / {len(codes)}개")


if __name__ == '__main__':
    main()
