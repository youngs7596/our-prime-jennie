#!/usr/bin/env python3
"""
섹터 모멘텀 분석 스크립트

네이버 업종 기반 섹터별 모멘텀/성과 분석.
STOCK_MASTER(SECTOR_NAVER_GROUP) + STOCK_DAILY_PRICES_3Y 조인.

분석 항목:
  1. 섹터별 수익률 (1W, 1M, 3M, 6M)
  2. 섹터 순위 변동 (로테이션 감지)
  3. 핫 섹터 / 콜드 섹터
  4. 섹터 내 종목 분산 (동조화 정도)
  5. 섹터별 수급 흐름 (외인 순매수)

Usage:
    .venv/bin/python scripts/analyze_sector_momentum.py
"""

import sys
import os
import json
import argparse
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.db.connection import ensure_engine_initialized, session_scope
from shared.db.models import StockMaster, StockDailyPrice, StockInvestorTrading
from shared.sector_taxonomy import NAVER_TO_GROUP


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


def load_sector_prices(session, lookback_days: int = 180):
    """STOCK_MASTER + STOCK_DAILY_PRICES_3Y 로드"""
    # 1. 종목-섹터 매핑
    masters = session.query(
        StockMaster.stock_code,
        StockMaster.stock_name,
        StockMaster.sector_naver,
        StockMaster.sector_naver_group,
        StockMaster.market_cap,
    ).filter(
        StockMaster.sector_naver_group.isnot(None),
    ).all()

    df_master = pd.DataFrame(masters, columns=['code', 'name', 'sector_fine', 'sector_group', 'market_cap'])

    if df_master.empty:
        print("STOCK_MASTER에 SECTOR_NAVER_GROUP 데이터가 없습니다.")
        print("utilities/update_naver_sectors.py를 먼저 실행하세요.")
        return None, None

    # 2. 가격 데이터
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=lookback_days + 10)

    stock_codes = df_master['code'].tolist()

    prices = session.query(
        StockDailyPrice.stock_code,
        StockDailyPrice.price_date,
        StockDailyPrice.close_price,
        StockDailyPrice.volume,
    ).filter(
        StockDailyPrice.stock_code.in_(stock_codes),
        StockDailyPrice.price_date >= start_date,
        StockDailyPrice.price_date <= end_date,
    ).all()

    df_price = pd.DataFrame(prices, columns=['code', 'date', 'close', 'volume'])
    df_price['date'] = pd.to_datetime(df_price['date']).dt.date

    return df_master, df_price


def load_investor_flows(session, stock_codes: list, days: int = 30):
    """종목별 외인 순매수 데이터 로드"""
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=days + 5)

    rows = session.query(
        StockInvestorTrading.stock_code,
        StockInvestorTrading.trade_date,
        StockInvestorTrading.foreign_net_buy,
        StockInvestorTrading.institution_net_buy,
    ).filter(
        StockInvestorTrading.stock_code.in_(stock_codes),
        StockInvestorTrading.trade_date >= start_date,
        StockInvestorTrading.trade_date <= end_date,
    ).all()

    if not rows:
        return None

    df = pd.DataFrame(rows, columns=['code', 'date', 'foreign_net', 'institution_net'])
    df['foreign_net'] = pd.to_numeric(df['foreign_net'], errors='coerce').fillna(0)
    df['institution_net'] = pd.to_numeric(df['institution_net'], errors='coerce').fillna(0)
    return df


def calc_sector_returns(df_master: pd.DataFrame, df_price: pd.DataFrame):
    """섹터별 수익률 계산 (1W, 1M, 3M, 6M)"""
    pivot = df_price.pivot_table(index='date', columns='code', values='close', aggfunc='last').sort_index()

    if len(pivot) < 5:
        return None

    today_idx = pivot.index[-1]
    periods = {
        '1W': 5,
        '1M': 21,
        '3M': 63,
        '6M': 126,
    }

    results = []
    code_to_sector = dict(zip(df_master['code'], df_master['sector_group']))

    for period_name, days in periods.items():
        if len(pivot) < days + 1:
            continue

        base_idx = max(0, len(pivot) - days - 1)
        base_prices = pivot.iloc[base_idx]
        latest_prices = pivot.iloc[-1]

        returns = ((latest_prices - base_prices) / base_prices * 100).dropna()

        for code, ret in returns.items():
            sector = code_to_sector.get(code)
            if sector:
                results.append({
                    'code': code,
                    'sector': sector,
                    'period': period_name,
                    'return_pct': ret,
                })

    return pd.DataFrame(results)


def print_sector_returns(df_returns: pd.DataFrame):
    """섹터별 수익률 테이블"""
    print("\n" + "=" * 80)
    print("1. 섹터별 평균 수익률")
    print("=" * 80)

    pivot = df_returns.pivot_table(
        index='sector', columns='period', values='return_pct',
        aggfunc='mean',
    )

    # 정렬: 1M 수익률 기준 내림차순
    period_order = ['1W', '1M', '3M', '6M']
    available = [p for p in period_order if p in pivot.columns]
    pivot = pivot[available]

    sort_col = '1M' if '1M' in pivot.columns else available[0]
    pivot = pivot.sort_values(sort_col, ascending=False)

    # 종목 수 집계
    counts = df_returns[df_returns['period'] == sort_col].groupby('sector')['code'].nunique()

    header = f"  {'섹터':>14s}  {'n':>4s}"
    for p in available:
        header += f"  {p:>8s}"
    print(header)
    print(f"  {'-'*14}  {'-'*4}" + f"  {'-'*8}" * len(available))

    for sector in pivot.index:
        n = counts.get(sector, 0)
        line = f"  {sector:>14s}  {n:4d}"
        for p in available:
            val = pivot.loc[sector, p] if p in pivot.columns and pd.notna(pivot.loc[sector, p]) else None
            if val is not None:
                line += f"  {val:+7.2f}%"
            else:
                line += f"  {'N/A':>8s}"
        print(line)

    return pivot


def print_rotation_analysis(df_returns: pd.DataFrame):
    """섹터 순위 변동 (로테이션 감지)"""
    print("\n" + "=" * 80)
    print("2. 섹터 로테이션 (1M 순위 변동)")
    print("=" * 80)

    if '3M' not in df_returns['period'].values or '1M' not in df_returns['period'].values:
        print("  3M 데이터 부족으로 로테이션 분석 불가")
        return

    rank_1m = df_returns[df_returns['period'] == '1M'].groupby('sector')['return_pct'].mean().rank(ascending=False)
    rank_3m = df_returns[df_returns['period'] == '3M'].groupby('sector')['return_pct'].mean().rank(ascending=False)

    common = set(rank_1m.index) & set(rank_3m.index)
    if not common:
        return

    rotation = []
    for sector in common:
        change = int(rank_3m[sector] - rank_1m[sector])  # 양수 = 순위 상승
        rotation.append({'sector': sector, 'rank_1m': int(rank_1m[sector]), 'rank_3m': int(rank_3m[sector]), 'change': change})

    df_rot = pd.DataFrame(rotation).sort_values('change', ascending=False)

    print(f"  {'섹터':>14s}  {'3M순위':>6s}  {'1M순위':>6s}  {'변동':>6s}")
    print(f"  {'-'*14}  {'-'*6}  {'-'*6}  {'-'*6}")

    for _, row in df_rot.iterrows():
        arrow = "^" if row['change'] > 0 else ("v" if row['change'] < 0 else "-")
        print(f"  {row['sector']:>14s}  {row['rank_3m']:6d}  {row['rank_1m']:6d}  {row['change']:+5d} {arrow}")


def print_hot_cold_sectors(df_returns: pd.DataFrame):
    """핫/콜드 섹터"""
    print("\n" + "=" * 80)
    print("3. Hot / Cold 섹터 (1M 기준)")
    print("=" * 80)

    if '1M' not in df_returns['period'].values:
        print("  1M 데이터 부족")
        return

    avg_1m = df_returns[df_returns['period'] == '1M'].groupby('sector')['return_pct'].mean().sort_values(ascending=False)

    print("\n  [HOT] 상위 3 섹터:")
    for sector, ret in avg_1m.head(3).items():
        print(f"    {sector:>14s}  {ret:+.2f}%")

    print("\n  [COLD] 하위 3 섹터:")
    for sector, ret in avg_1m.tail(3).items():
        print(f"    {sector:>14s}  {ret:+.2f}%")


def print_dispersion_analysis(df_returns: pd.DataFrame):
    """섹터 내 종목 분산 (동조화 정도)"""
    print("\n" + "=" * 80)
    print("4. 섹터 내 종목 분산 (1M, 동조화 정도)")
    print("=" * 80)

    if '1M' not in df_returns['period'].values:
        print("  1M 데이터 부족")
        return

    monthly = df_returns[df_returns['period'] == '1M']
    stats = monthly.groupby('sector')['return_pct'].agg(['mean', 'std', 'count'])
    stats = stats[stats['count'] >= 3].sort_values('std')

    print(f"  {'섹터':>14s}  {'n':>4s}  {'Avg':>8s}  {'Std':>7s}  {'동조화':>6s}")
    print(f"  {'-'*14}  {'-'*4}  {'-'*8}  {'-'*7}  {'-'*6}")

    for sector, row in stats.iterrows():
        coherence = "높음" if row['std'] < 5 else ("보통" if row['std'] < 10 else "낮음")
        print(f"  {sector:>14s}  {int(row['count']):4d}  {row['mean']:+7.2f}%  {row['std']:6.2f}  {coherence:>6s}")


def print_flow_analysis(df_master: pd.DataFrame, df_flow: pd.DataFrame):
    """섹터별 수급 흐름"""
    print("\n" + "=" * 80)
    print("5. 섹터별 수급 흐름 (최근 1M, 외인+기관 순매수)")
    print("=" * 80)

    if df_flow is None or df_flow.empty:
        print("  수급 데이터 없음 (STOCK_INVESTOR_TRADING 테이블 확인)")
        return

    code_to_sector = dict(zip(df_master['code'], df_master['sector_group']))
    df_flow = df_flow.copy()
    df_flow['sector'] = df_flow['code'].map(code_to_sector)
    df_flow = df_flow.dropna(subset=['sector'])

    sector_flow = df_flow.groupby('sector').agg(
        foreign_total=('foreign_net', 'sum'),
        institution_total=('institution_net', 'sum'),
        n_stocks=('code', 'nunique'),
    ).sort_values('foreign_total', ascending=False)

    # 억 단위로 변환
    sector_flow['foreign_억'] = sector_flow['foreign_total'] / 1e8
    sector_flow['institution_억'] = sector_flow['institution_total'] / 1e8

    print(f"  {'섹터':>14s}  {'종목수':>5s}  {'외인(억)':>10s}  {'기관(억)':>10s}")
    print(f"  {'-'*14}  {'-'*5}  {'-'*10}  {'-'*10}")

    for sector, row in sector_flow.iterrows():
        print(f"  {sector:>14s}  {int(row['n_stocks']):5d}  {row['foreign_억']:+9.0f}  {row['institution_억']:+9.0f}")


def save_csv(df_returns: pd.DataFrame):
    """결과 CSV 저장"""
    output_dir = os.path.join(project_root, "scripts", "output")
    os.makedirs(output_dir, exist_ok=True)

    today_str = datetime.now().strftime("%Y%m%d")
    filepath = os.path.join(output_dir, f"sector_momentum_{today_str}.csv")

    pivot = df_returns.pivot_table(
        index='sector', columns='period', values='return_pct', aggfunc='mean',
    )
    period_order = ['1W', '1M', '3M', '6M']
    available = [p for p in period_order if p in pivot.columns]
    pivot = pivot[available]
    pivot = pivot.sort_values(available[1] if len(available) > 1 else available[0], ascending=False)

    pivot.to_csv(filepath, encoding='utf-8-sig')
    print(f"\n  CSV 저장: {filepath}")


def main():
    parser = argparse.ArgumentParser(description="섹터 모멘텀 분석")
    parser.add_argument("--days", type=int, default=180, help="가격 데이터 lookback (일)")
    args = parser.parse_args()

    print("섹터 모멘텀 분석")
    print("=" * 80)

    load_secrets()
    ensure_engine_initialized()

    with session_scope(readonly=True) as session:
        df_master, df_price = load_sector_prices(session, args.days)
        if df_master is None:
            return

        print(f"  종목 수: {len(df_master)}개 ({df_master['sector_group'].nunique()}개 섹터)")
        print(f"  가격 데이터: {len(df_price)}건")

        df_returns = calc_sector_returns(df_master, df_price)
        if df_returns is None or df_returns.empty:
            print("  수익률 계산 실패 (가격 데이터 부족)")
            return

        print_sector_returns(df_returns)
        print_rotation_analysis(df_returns)
        print_hot_cold_sectors(df_returns)
        print_dispersion_analysis(df_returns)

        # 수급 데이터
        stock_codes = df_master['code'].tolist()
        df_flow = load_investor_flows(session, stock_codes, days=30)
        print_flow_analysis(df_master, df_flow)

        save_csv(df_returns)

    print("\n" + "=" * 80)
    print("분석 완료")


if __name__ == "__main__":
    main()
