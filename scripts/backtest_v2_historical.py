"""
Historical Backtest: Quant Scorer v1 vs v2 Forward Return 비교

WATCHLIST_HISTORY의 과거 종목에 대해 v1/v2 스코어링을 재계산하고,
실제 D+5/D+10/D+20 forward return과의 IC/IR/Hit Rate를 비교.

사용법:
    .venv/bin/python scripts/backtest_v2_historical.py
    .venv/bin/python scripts/backtest_v2_historical.py --days 30
    .venv/bin/python scripts/backtest_v2_historical.py --all-stocks --days 60
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import argparse
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from scipy import stats
from sqlalchemy import text, select, desc, and_, func

from shared.db.connection import init_engine, session_scope
from shared.db.models import (
    WatchlistHistory, StockDailyPrice, StockInvestorTrading,
    StockNewsSentiment, FinancialMetricsQuarterly, StockMaster,
)
from shared.db.factor_repository import FactorRepository
from shared.database import market as market_db
from shared.hybrid_scoring.quant_scorer import QuantScorer
import shared.hybrid_scoring.quant_scorer as qs_module

# ============================================================
# 데이터 로딩
# ============================================================

def load_watchlist_history(session, start_date, end_date):
    """기간 내 Watchlist 히스토리 조회"""
    stmt = (
        select(
            WatchlistHistory.snapshot_date,
            WatchlistHistory.stock_code,
            WatchlistHistory.stock_name,
            WatchlistHistory.llm_score,
        )
        .where(and_(
            WatchlistHistory.snapshot_date >= start_date,
            WatchlistHistory.snapshot_date <= end_date,
        ))
        .order_by(WatchlistHistory.snapshot_date)
    )
    rows = session.execute(stmt).fetchall()
    return pd.DataFrame(rows, columns=['date', 'stock_code', 'stock_name', 'llm_score'])


def load_all_stocks(session, min_market_cap=3000_0000_0000):
    """전종목 유니버스 로드 (시가총액 기준 필터)"""
    stmt = (
        select(StockMaster.stock_code, StockMaster.stock_name)
        .where(StockMaster.market_cap >= min_market_cap)
    )
    rows = session.execute(stmt).fetchall()
    return pd.DataFrame(rows, columns=['stock_code', 'stock_name'])


def load_bulk_prices(session, start_date, end_date):
    """전종목 일봉 벌크 로드 → pivot dict"""
    # start_date 이전 150일도 필요 (scoring에 120일 lookback)
    lookback_start = start_date - timedelta(days=220)

    result = session.execute(text("""
        SELECT STOCK_CODE, PRICE_DATE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, CLOSE_PRICE, VOLUME
        FROM STOCK_DAILY_PRICES_3Y
        WHERE PRICE_DATE >= :start AND PRICE_DATE <= :end
        ORDER BY STOCK_CODE, PRICE_DATE
    """), {'start': lookback_start, 'end': end_date + timedelta(days=30)})
    rows = result.fetchall()

    if not rows:
        return {}

    df = pd.DataFrame(rows, columns=[
        'STOCK_CODE', 'PRICE_DATE', 'OPEN_PRICE', 'HIGH_PRICE', 'LOW_PRICE', 'CLOSE_PRICE', 'VOLUME'
    ])

    # 종목별 DataFrame dict
    price_dict = {}
    for code, grp in df.groupby('STOCK_CODE'):
        price_dict[code] = grp.drop(columns='STOCK_CODE').sort_values('PRICE_DATE').reset_index(drop=True)

    return price_dict


def load_bulk_investor_trading(session, start_date, end_date):
    """전종목 수급 벌크 로드"""
    lookback_start = start_date - timedelta(days=40)
    result = session.execute(text("""
        SELECT STOCK_CODE, TRADE_DATE, FOREIGN_NET_BUY, INSTITUTION_NET_BUY,
               INDIVIDUAL_NET_BUY
        FROM STOCK_INVESTOR_TRADING
        WHERE TRADE_DATE >= :start AND TRADE_DATE <= :end
        ORDER BY STOCK_CODE, TRADE_DATE
    """), {'start': lookback_start, 'end': end_date})
    rows = result.fetchall()

    if not rows:
        return {}

    df = pd.DataFrame(rows, columns=[
        'STOCK_CODE', 'TRADE_DATE', 'FOREIGN_NET_BUY', 'INSTITUTION_NET_BUY',
        'INDIVIDUAL_NET_BUY',
    ])

    inv_dict = {}
    for code, grp in df.groupby('STOCK_CODE'):
        inv_dict[code] = grp.drop(columns='STOCK_CODE').sort_values('TRADE_DATE').reset_index(drop=True)

    return inv_dict


def load_bulk_sentiment(session, start_date, end_date):
    """전종목 뉴스 센티먼트 벌크 로드"""
    lookback_start = start_date - timedelta(days=40)
    result = session.execute(text("""
        SELECT STOCK_CODE, NEWS_DATE, SENTIMENT_SCORE
        FROM STOCK_NEWS_SENTIMENT
        WHERE NEWS_DATE >= :start AND NEWS_DATE <= :end
    """), {'start': lookback_start, 'end': end_date})
    rows = result.fetchall()

    if not rows:
        return {}

    df = pd.DataFrame(rows, columns=['STOCK_CODE', 'NEWS_DATE', 'SENTIMENT_SCORE'])

    sent_dict = {}
    for code, grp in df.groupby('STOCK_CODE'):
        sent_dict[code] = grp.drop(columns='STOCK_CODE').sort_values('NEWS_DATE').reset_index(drop=True)

    return sent_dict


def load_bulk_financials(session, stock_codes):
    """분기별 재무 벌크 로드"""
    if not stock_codes:
        return {}, {}

    placeholder = ','.join([f':c{i}' for i in range(len(stock_codes))])
    params = {f'c{i}': c for i, c in enumerate(stock_codes)}

    result = session.execute(text(f"""
        SELECT STOCK_CODE, QUARTER_DATE, ROE, PER, PBR, EPS
        FROM FINANCIAL_METRICS_QUARTERLY
        WHERE STOCK_CODE IN ({placeholder})
        ORDER BY STOCK_CODE, QUARTER_DATE
    """), params)
    rows = result.fetchall()

    # 최신 스냅샷 (종목별 최신 분기)
    fin_snapshot = {}
    # 트렌드 (종목별 최근 4분기)
    fin_trend = {}

    if not rows:
        return fin_snapshot, fin_trend

    df = pd.DataFrame(rows, columns=['STOCK_CODE', 'QUARTER_DATE', 'ROE', 'PER', 'PBR', 'EPS'])

    def _to_float(v):
        """Decimal/None → float 변환"""
        if v is None or (hasattr(v, '__class__') and 'Decimal' in v.__class__.__name__):
            return float(v) if v is not None else None
        return float(v) if v is not None else None

    for code, grp in df.groupby('STOCK_CODE'):
        grp = grp.sort_values('QUARTER_DATE')
        latest = grp.iloc[-1]
        fin_snapshot[code] = {
            'roe': _to_float(latest['ROE']),
            'per': _to_float(latest['PER']),
            'pbr': _to_float(latest['PBR']),
            'eps': _to_float(latest['EPS']),
        }

        # EPS 성장률
        if len(grp) >= 2:
            prev_eps = _to_float(grp.iloc[-2]['EPS'])
            curr_eps = _to_float(grp.iloc[-1]['EPS'])
            if prev_eps and prev_eps != 0:
                fin_snapshot[code]['eps_growth'] = (curr_eps - prev_eps) / abs(prev_eps) * 100
            else:
                fin_snapshot[code]['eps_growth'] = None
        else:
            fin_snapshot[code]['eps_growth'] = None

        # 트렌드 (최근 4분기)
        recent4 = grp.tail(4)
        fin_trend[code] = {
            'roe_trend': [_to_float(v) for v in recent4['ROE'].tolist()],
            'per_trend': [_to_float(v) for v in recent4['PER'].tolist()],
            'eps_trend': [_to_float(v) for v in recent4['EPS'].tolist()],
            'net_income_trend': [],
        }

    return fin_snapshot, fin_trend


# ============================================================
# 점수 계산
# ============================================================

def ensure_timestamp(d):
    """date/datetime → pd.Timestamp 변환"""
    return pd.Timestamp(d)


def get_prices_up_to(price_dict, code, target_date, lookback=150):
    """특정 날짜까지의 가격 DataFrame 반환"""
    if code not in price_dict:
        return pd.DataFrame()

    df = price_dict[code]
    # date 타입 통일
    target_ts = ensure_timestamp(target_date)
    dates = pd.to_datetime(df['PRICE_DATE'])
    mask = dates <= target_ts
    sliced = df[mask].tail(lookback)
    return sliced.reset_index(drop=True)


def get_forward_return(price_dict, code, target_date, days):
    """D+N forward return 계산"""
    if code not in price_dict:
        return None

    df = price_dict[code]
    target_ts = ensure_timestamp(target_date)
    dates = pd.to_datetime(df['PRICE_DATE'])

    # target_date에서의 종가
    target_rows = df[dates == target_ts]
    if target_rows.empty:
        target_rows = df[dates <= target_ts].tail(1)
    if target_rows.empty:
        return None

    base_price = float(target_rows.iloc[-1]['CLOSE_PRICE'])
    base_idx = target_rows.index[-1]

    # D+N 거래일 후 종가
    future = df.iloc[base_idx + 1:]
    trade_days_after = future.head(days + 5)
    if len(trade_days_after) >= days:
        future_price = float(trade_days_after.iloc[days - 1]['CLOSE_PRICE'])
        return (future_price / base_price - 1) * 100
    return None


def get_investor_up_to(inv_dict, code, target_date, lookback=10):
    """특정 날짜까지의 수급 DataFrame"""
    if code not in inv_dict:
        return pd.DataFrame()
    df = inv_dict[code]
    target_ts = ensure_timestamp(target_date)
    dates = pd.to_datetime(df['TRADE_DATE'])
    return df[dates <= target_ts].tail(lookback).reset_index(drop=True)


def get_sentiment_at(sent_dict, code, target_date):
    """특정 날짜 기준 최근 5일 평균 센티먼트"""
    if code not in sent_dict:
        return 50.0
    df = sent_dict[code]
    td = ensure_timestamp(target_date)
    dates = pd.to_datetime(df['NEWS_DATE'])
    cutoff = td - pd.Timedelta(days=7)
    recent = df[(dates >= cutoff) & (dates <= td)]
    scores = recent['SENTIMENT_SCORE'].dropna()
    if len(scores) > 0:
        return float(scores.mean())
    return 50.0


def get_sentiment_momentum_at(sent_dict, code, target_date):
    """특정 날짜 기준 센티먼트 모멘텀 (recent 7d - past 8~37d)"""
    if code not in sent_dict:
        return None
    df = sent_dict[code]
    td = ensure_timestamp(target_date)
    dates = pd.to_datetime(df['NEWS_DATE'])

    recent = df[(dates >= td - pd.Timedelta(days=7)) & (dates <= td)]
    past = df[(dates >= td - pd.Timedelta(days=37)) & (dates < td - pd.Timedelta(days=7))]

    r_scores = recent['SENTIMENT_SCORE'].dropna()
    p_scores = past['SENTIMENT_SCORE'].dropna()

    if len(r_scores) >= 1 and len(p_scores) >= 1:
        return float(r_scores.mean() - p_scores.mean())
    return None


def get_foreign_ratio_trend_at(inv_dict, code, target_date):
    """특정 날짜 기준 외인보유비율 20일 변화"""
    df = inv_dict.get(code)
    if df is None or df.empty:
        return None
    if 'FOREIGN_HOLDING_RATIO' not in df.columns:
        return None
    before = df[df['TRADE_DATE'] <= pd.Timestamp(target_date)]
    if len(before) < 20:
        return None
    ratios = before.tail(20)['FOREIGN_HOLDING_RATIO'].dropna()
    if len(ratios) < 20:
        return None
    return float(ratios.iloc[-1] - ratios.iloc[0])


def score_stock(scorer, code, name, daily_df, kospi_df, fin_snap, inv_trading_df,
                sentiment, eps_growth, fin_trend, sent_momentum, frt, version):
    """종목 스코어링 실행"""
    qs_module.QUANT_SCORER_VERSION = version

    kwargs = dict(
        stock_code=code,
        stock_name=name,
        daily_prices_df=daily_df,
        kospi_prices_df=kospi_df if kospi_df is not None and not kospi_df.empty else None,
        roe=fin_snap.get('roe') if fin_snap else None,
        eps_growth=eps_growth,
        pbr=fin_snap.get('pbr') if fin_snap else None,
        per=fin_snap.get('per') if fin_snap else None,
        current_sentiment_score=sentiment,
        investor_trading_df=inv_trading_df if inv_trading_df is not None and not inv_trading_df.empty else None,
    )

    # 수급 데이터
    if inv_trading_df is not None and not inv_trading_df.empty:
        latest_inv = inv_trading_df.iloc[-1]
        kwargs['foreign_net_buy'] = latest_inv.get('FOREIGN_NET_BUY')
        kwargs['institution_net_buy'] = latest_inv.get('INSTITUTION_NET_BUY')

    if version == 'v2':
        kwargs['financial_trend'] = fin_trend
        kwargs['sentiment_momentum'] = sent_momentum
        kwargs['foreign_ratio_trend'] = frt

    try:
        result = scorer.calculate_total_quant_score(**kwargs)
        return result.total_score
    except Exception as e:
        return None


# ============================================================
# 메트릭 계산
# ============================================================

def compute_metrics(scores, forwards, label):
    """IC/IR/Hit Rate/Quintile Spread 계산"""
    df = pd.DataFrame({'score': scores, 'fwd': forwards}).dropna()
    if len(df) < 10:
        return {'label': label, 'n': len(df), 'ic': np.nan, 'ir': np.nan,
                'hit_rate': np.nan, 'top20_avg': np.nan, 'bot20_avg': np.nan,
                'spread': np.nan, 'avg_return': np.nan}

    ic, _ = stats.spearmanr(df['score'], df['fwd'])

    # Quintile
    q80 = df['score'].quantile(0.8)
    q20 = df['score'].quantile(0.2)
    top = df[df['score'] >= q80]
    bot = df[df['score'] <= q20]

    top_avg = top['fwd'].mean() if len(top) > 0 else np.nan
    bot_avg = bot['fwd'].mean() if len(bot) > 0 else np.nan
    spread = top_avg - bot_avg if not np.isnan(top_avg) and not np.isnan(bot_avg) else np.nan
    hit_rate = (top['fwd'] > 0).mean() if len(top) > 0 else np.nan

    return {
        'label': label,
        'n': len(df),
        'ic': ic,
        'ir': np.nan,  # 단일 기간이므로 IR은 per-date에서 계산
        'hit_rate': hit_rate,
        'top20_avg': top_avg,
        'bot20_avg': bot_avg,
        'spread': spread,
        'avg_return': df['fwd'].mean(),
    }


def compute_daily_ic(daily_data, version_key):
    """날짜별 IC 계산 → IC mean / IC std = IR"""
    ics = []
    for date, items in daily_data.items():
        scores = [it[version_key] for it in items if it[version_key] is not None and it.get('fwd_5d') is not None]
        fwds = [it['fwd_5d'] for it in items if it[version_key] is not None and it.get('fwd_5d') is not None]
        if len(scores) >= 5:
            ic, _ = stats.spearmanr(scores, fwds)
            if not np.isnan(ic):
                ics.append(ic)
    if not ics:
        return np.nan, np.nan
    return np.mean(ics), np.mean(ics) / np.std(ics) if np.std(ics) > 0 else 0


# ============================================================
# 메인 실행
# ============================================================

def run_backtest(days=28, all_stocks=False, rebal_interval=5):
    """v1 vs v2 Historical Backtest"""
    init_engine()

    end_date = datetime.now().date() - timedelta(days=1)
    start_date = end_date - timedelta(days=days)

    mode_label = "전종목" if all_stocks else "Watchlist"
    print(f"\n{'='*100}")
    print(f"  Quant Scorer v1 vs v2 Historical Backtest ({mode_label})")
    print(f"  기간: {start_date} ~ {end_date} ({days}일)")
    print(f"{'='*100}")

    with session_scope(readonly=True) as session:
        # 1. 대상 종목 결정
        if all_stocks:
            stock_df = load_all_stocks(session)
            stock_map = dict(zip(stock_df['stock_code'], stock_df['stock_name']))
            print(f"  전종목 유니버스: {len(stock_map)}종목")
        else:
            wh_df = load_watchlist_history(session, start_date, end_date)
            if wh_df.empty:
                print("❌ Watchlist 히스토리 없음")
                return
            stock_map = dict(zip(wh_df['stock_code'], wh_df['stock_name']))
            print(f"  Watchlist 종목: {len(stock_map)}종목, {wh_df['date'].nunique()}일")

        stock_codes = list(stock_map.keys())

        # 2. 벌크 데이터 로드
        print("\n  데이터 로딩 중...")
        price_dict = load_bulk_prices(session, start_date, end_date)
        print(f"    가격: {len(price_dict)}종목")

        inv_dict = load_bulk_investor_trading(session, start_date, end_date)
        print(f"    수급: {len(inv_dict)}종목")

        sent_dict = load_bulk_sentiment(session, start_date, end_date)
        print(f"    뉴스: {len(sent_dict)}종목")

        fin_snapshot, fin_trend_all = load_bulk_financials(session, stock_codes)
        print(f"    재무: {len(fin_snapshot)}종목")

        # KOSPI 일봉
        kospi_df = market_db.get_daily_prices(session, '0001', limit=200)

        # 3. 리밸런싱 날짜 결정
        if all_stocks:
            # 전종목: 가격 데이터에서 거래일 추출
            all_dates = set()
            for code_df in price_dict.values():
                all_dates.update(code_df['PRICE_DATE'].tolist())
            trade_dates = sorted([d for d in all_dates
                                  if pd.Timestamp(start_date) <= d <= pd.Timestamp(end_date)])
            rebal_dates = trade_dates[::rebal_interval]
        else:
            # Watchlist: snapshot 날짜 기준
            wh_dates = sorted(wh_df['date'].unique())
            rebal_dates = [pd.Timestamp(d) for d in wh_dates]

        print(f"  리밸런싱: {len(rebal_dates)}회")
        if not rebal_dates:
            print("❌ 리밸런싱 날짜 없음")
            return

        # 4. 스코어링 + Forward Return 계산
        print("\n  스코어링 실행 중...")
        scorer = QuantScorer(db_conn=None)

        all_records = []
        daily_data = {}  # date -> list of records

        for ri, rdate in enumerate(rebal_dates):
            rdate_py = rdate.date() if hasattr(rdate, 'date') else rdate
            if (ri + 1) % 5 == 0 or ri == 0:
                print(f"    [{ri+1}/{len(rebal_dates)}] {rdate_py}")

            # 대상 종목
            if all_stocks:
                day_codes = stock_codes
            else:
                day_wh = wh_df[wh_df['date'] == rdate_py]
                day_codes = day_wh['stock_code'].tolist()

            day_records = []

            for code in day_codes:
                name = stock_map.get(code, code)

                # 가격 데이터
                daily_df = get_prices_up_to(price_dict, code, rdate_py, lookback=150)
                if daily_df.empty or len(daily_df) < 30:
                    continue

                # KOSPI도 같은 날짜까지 자르기
                kospi_up_to = None
                if kospi_df is not None and not kospi_df.empty:
                    kospi_dates = pd.to_datetime(kospi_df['PRICE_DATE'])
                    kospi_mask = kospi_dates <= ensure_timestamp(rdate_py)
                    kospi_up_to = kospi_df[kospi_mask].tail(150).reset_index(drop=True)

                # 재무 데이터
                fin_snap = fin_snapshot.get(code, {})
                eps_growth = fin_snap.get('eps_growth')
                fin_trend = fin_trend_all.get(code)

                # 수급 데이터
                inv_df = get_investor_up_to(inv_dict, code, rdate_py, lookback=10)

                # 센티먼트
                sentiment = get_sentiment_at(sent_dict, code, rdate_py)
                sent_mom = get_sentiment_momentum_at(sent_dict, code, rdate_py)

                # 외인비율 추세
                frt = get_foreign_ratio_trend_at(inv_dict, code, rdate_py)

                # v1 스코어링
                v1_score = score_stock(
                    scorer, code, name, daily_df, kospi_up_to,
                    fin_snap, inv_df, sentiment, eps_growth,
                    None, None, None, 'v1',
                )

                # v2 스코어링
                v2_score = score_stock(
                    scorer, code, name, daily_df, kospi_up_to,
                    fin_snap, inv_df, sentiment, eps_growth,
                    fin_trend, sent_mom, frt, 'v2',
                )

                if v1_score is None and v2_score is None:
                    continue

                # Forward returns
                fwd_5d = get_forward_return(price_dict, code, rdate_py, 5)
                fwd_10d = get_forward_return(price_dict, code, rdate_py, 10)
                fwd_20d = get_forward_return(price_dict, code, rdate_py, 20)

                rec = {
                    'date': rdate_py,
                    'code': code,
                    'name': name,
                    'v1_score': v1_score,
                    'v2_score': v2_score,
                    'fwd_5d': fwd_5d,
                    'fwd_10d': fwd_10d,
                    'fwd_20d': fwd_20d,
                }
                all_records.append(rec)
                day_records.append(rec)

            daily_data[rdate_py] = day_records

        # v1으로 복원
        qs_module.QUANT_SCORER_VERSION = 'v1'

    if not all_records:
        print("❌ 스코어링 결과 없음")
        return

    df = pd.DataFrame(all_records)
    print(f"\n  총 {len(df):,}건 스코어링 완료 ({df['code'].nunique()}종목 × {df['date'].nunique()}일)")

    # ===================== 메트릭 계산 =====================
    print(f"\n{'='*100}")
    print("  v1 vs v2 성과 비교")
    print(f"{'='*100}")

    for horizon, col in [('D+5', 'fwd_5d'), ('D+10', 'fwd_10d'), ('D+20', 'fwd_20d')]:
        valid = df[[col, 'v1_score', 'v2_score']].dropna()
        if len(valid) < 10:
            print(f"\n  [{horizon}] 데이터 부족 ({len(valid)}건)")
            continue

        m_v1 = compute_metrics(valid['v1_score'].tolist(), valid[col].tolist(), f'v1 {horizon}')
        m_v2 = compute_metrics(valid['v2_score'].tolist(), valid[col].tolist(), f'v2 {horizon}')

        print(f"\n  [{horizon}] (n={m_v1['n']})")
        print(f"  {'':>12} {'IC':>8} {'Hit Rate':>10} {'Top20 Avg':>10} {'Bot20 Avg':>10} {'Spread':>10} {'전체평균':>10}")
        for m, label in [(m_v1, 'v1'), (m_v2, 'v2')]:
            ic_str = f"{m['ic']:.4f}" if not np.isnan(m['ic']) else 'N/A'
            hr_str = f"{m['hit_rate']:.1%}" if not np.isnan(m['hit_rate']) else 'N/A'
            ta_str = f"{m['top20_avg']:.2f}%" if not np.isnan(m['top20_avg']) else 'N/A'
            ba_str = f"{m['bot20_avg']:.2f}%" if not np.isnan(m['bot20_avg']) else 'N/A'
            sp_str = f"{m['spread']:.2f}pp" if not np.isnan(m['spread']) else 'N/A'
            ar_str = f"{m['avg_return']:.2f}%" if not np.isnan(m['avg_return']) else 'N/A'
            print(f"  {label:>12} {ic_str:>8} {hr_str:>10} {ta_str:>10} {ba_str:>10} {sp_str:>10} {ar_str:>10}")

    # Daily IC → IR
    print(f"\n{'='*100}")
    print("  날짜별 IC → IR (Information Ratio)")
    print(f"{'='*100}")

    for version_key, label in [('v1_score', 'v1'), ('v2_score', 'v2')]:
        ic_mean, ir = compute_daily_ic(daily_data, version_key)
        print(f"  {label}: IC_mean={ic_mean:.4f}, IR={ir:.3f}" if not np.isnan(ic_mean) else f"  {label}: N/A")

    # Score 분포 비교
    print(f"\n{'='*100}")
    print("  점수 분포 비교")
    print(f"{'='*100}")
    valid_both = df[df['v1_score'].notna() & df['v2_score'].notna()]
    if len(valid_both) > 0:
        print(f"  v1: mean={valid_both['v1_score'].mean():.1f}, median={valid_both['v1_score'].median():.1f}, std={valid_both['v1_score'].std():.1f}")
        print(f"  v2: mean={valid_both['v2_score'].mean():.1f}, median={valid_both['v2_score'].median():.1f}, std={valid_both['v2_score'].std():.1f}")
        rank_corr, _ = stats.spearmanr(valid_both['v1_score'], valid_both['v2_score'])
        print(f"  v1↔v2 Rank 상관: {rank_corr:.3f}")

    # Score Bucket 분석 (v1, v2 각각)
    print(f"\n{'='*100}")
    print("  점수 구간별 Forward Return (D+5)")
    print(f"{'='*100}")

    for version, score_col in [('v1', 'v1_score'), ('v2', 'v2_score')]:
        valid = df[[score_col, 'fwd_5d']].dropna()
        if len(valid) < 20:
            continue

        buckets = pd.cut(valid[score_col], bins=[0, 30, 40, 50, 60, 70, 80, 100],
                         labels=['0-30', '30-40', '40-50', '50-60', '60-70', '70-80', '80+'])
        valid['bucket'] = buckets
        print(f"\n  [{version}]")
        print(f"  {'구간':>8} {'건수':>6} {'평균':>8} {'중위수':>8} {'승률':>8}")
        for bucket, grp in valid.groupby('bucket', observed=True):
            avg = grp['fwd_5d'].mean()
            med = grp['fwd_5d'].median()
            wr = (grp['fwd_5d'] > 0).mean()
            print(f"  {str(bucket):>8} {len(grp):>6} {avg:>7.2f}% {med:>7.2f}% {wr:>7.1%}")

    # CSV 저장
    os.makedirs('scripts/output', exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M')
    out_path = f"scripts/output/backtest_v1v2_{mode_label}_{ts}.csv"
    df.to_csv(out_path, index=False, encoding='utf-8-sig')
    print(f"\n  📄 결과 저장: {out_path}")

    # 핵심 결론
    print(f"\n{'='*100}")
    print("  핵심 결론")
    print(f"{'='*100}")

    valid_5d = df[['v1_score', 'v2_score', 'fwd_5d']].dropna()
    if len(valid_5d) >= 10:
        ic_v1, _ = stats.spearmanr(valid_5d['v1_score'], valid_5d['fwd_5d'])
        ic_v2, _ = stats.spearmanr(valid_5d['v2_score'], valid_5d['fwd_5d'])
        better = 'v2' if ic_v2 > ic_v1 else 'v1'
        print(f"  D+5 IC: v1={ic_v1:.4f} vs v2={ic_v2:.4f} → {better} 우세")

        # v2가 IC를 개선했는지
        if ic_v2 > ic_v1:
            improvement = ic_v2 - ic_v1
            print(f"  ✅ v2가 IC를 {improvement:.4f} 개선 (잠재력 기반 스코어링 유효)")
        else:
            print(f"  ⚠️ v2 IC 개선 없음 — 추가 튜닝 필요")

        # IC 부호
        if ic_v2 > 0:
            print(f"  ✅ v2 IC 양수 — 점수↑ → 수익↑ 관계 성립")
        elif ic_v2 > -0.05:
            print(f"  ⚠️ v2 IC 약한 음수 — 아직 역상관 존재하나 v1보다 개선")
        else:
            print(f"  ❌ v2 IC 음수 — 역상관 문제 미해결")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Quant Scorer v1 vs v2 Historical Backtest')
    parser.add_argument('--days', type=int, default=28, help='백테스트 기간 (일)')
    parser.add_argument('--all-stocks', action='store_true', help='전종목 백테스트 (기본: Watchlist만)')
    parser.add_argument('--rebal', type=int, default=5, help='리밸런싱 간격 (거래일, 전종목 모드)')
    args = parser.parse_args()
    run_backtest(days=args.days, all_stocks=args.all_stocks, rebal_interval=args.rebal)
