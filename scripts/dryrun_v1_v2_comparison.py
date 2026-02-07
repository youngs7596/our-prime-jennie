"""
Dry-run: Quant Scorer v1 vs v2 점수 비교

최근 Watchlist 종목에 대해 v1/v2 동시 스코어링 → 점수 변화 비교
데이터: DB에서 실시간 조회 (현재 시점 기준)

사용법:
    .venv/bin/python scripts/dryrun_v1_v2_comparison.py
    .venv/bin/python scripts/dryrun_v1_v2_comparison.py --top 30
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import argparse
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from scipy import stats
from sqlalchemy import text, select, desc

from shared.db.connection import init_engine, session_scope
from shared.db.models import (
    WatchlistHistory, StockDailyPrice, StockInvestorTrading,
    StockNewsSentiment, FinancialMetricsQuarterly, StockMaster,
)
from shared.db.factor_repository import FactorRepository
from shared.database import market as market_db
from shared.hybrid_scoring.quant_scorer import QuantScorer
import shared.hybrid_scoring.quant_scorer as qs_module


def load_recent_watchlist(session, days=7):
    """최근 N일 내 Watchlist 종목 조회"""
    cutoff = datetime.now().date() - timedelta(days=days)
    stmt = (
        select(
            WatchlistHistory.snapshot_date,
            WatchlistHistory.stock_code,
            WatchlistHistory.stock_name,
            WatchlistHistory.llm_score,
        )
        .where(WatchlistHistory.snapshot_date >= cutoff)
        .order_by(desc(WatchlistHistory.snapshot_date))
    )
    rows = session.execute(stmt).fetchall()
    if not rows:
        print(f"⚠️ 최근 {days}일 내 Watchlist 데이터 없음 → 14일로 확장")
        cutoff = datetime.now().date() - timedelta(days=14)
        stmt = stmt.where(WatchlistHistory.snapshot_date >= cutoff)
        rows = session.execute(stmt).fetchall()

    df = pd.DataFrame(rows, columns=['date', 'stock_code', 'stock_name', 'llm_score'])
    # 가장 최근 날짜의 종목만
    if df.empty:
        return df
    latest = df['date'].max()
    return df[df['date'] == latest].reset_index(drop=True)


def load_financial_snapshot(session, stock_code):
    """최신 분기 재무 지표 조회"""
    stmt = (
        select(
            FinancialMetricsQuarterly.roe,
            FinancialMetricsQuarterly.per,
            FinancialMetricsQuarterly.pbr,
            FinancialMetricsQuarterly.eps,
        )
        .where(FinancialMetricsQuarterly.stock_code == stock_code)
        .order_by(desc(FinancialMetricsQuarterly.quarter_date))
        .limit(1)
    )
    row = session.execute(stmt).fetchone()
    if row:
        return {
            'roe': row[0],
            'per': row[1],
            'pbr': row[2],
            'eps': row[3],
        }
    return {}


def load_latest_investor_trading(session, stock_code):
    """최근 1일 수급 데이터"""
    stmt = (
        select(
            StockInvestorTrading.foreign_net_buy,
            StockInvestorTrading.institution_net_buy,
        )
        .where(StockInvestorTrading.stock_code == stock_code)
        .order_by(desc(StockInvestorTrading.trade_date))
        .limit(1)
    )
    row = session.execute(stmt).fetchone()
    if row:
        return {
            'foreign_net_buy': row[0],
            'institution_net_buy': row[1],
        }
    return {}


def load_latest_sentiment(session, stock_code):
    """최근 5일 평균 센티먼트"""
    cutoff = datetime.now().date() - timedelta(days=7)
    stmt = (
        select(StockNewsSentiment.sentiment_score)
        .where(StockNewsSentiment.stock_code == stock_code)
        .where(StockNewsSentiment.news_date >= cutoff)
    )
    rows = session.execute(stmt).scalars().all()
    if rows:
        return float(np.mean([r for r in rows if r is not None]))
    return 50.0


def compute_eps_growth(session, stock_code):
    """EPS 성장률 계산 (최근 2분기 비교)"""
    stmt = (
        select(FinancialMetricsQuarterly.eps)
        .where(FinancialMetricsQuarterly.stock_code == stock_code)
        .order_by(desc(FinancialMetricsQuarterly.quarter_date))
        .limit(2)
    )
    rows = session.execute(stmt).scalars().all()
    if len(rows) >= 2 and rows[1] and rows[1] != 0:
        return ((rows[0] or 0) - rows[1]) / abs(rows[1]) * 100
    return None


def run_comparison(top_n=50):
    """v1 vs v2 비교 실행"""
    init_engine()

    print(f"\n{'='*100}")
    print("  Quant Scorer v1 vs v2 Dry-Run Comparison")
    print(f"{'='*100}")

    with session_scope(readonly=True) as session:
        # 1. Watchlist 종목 로드
        wl_df = load_recent_watchlist(session)
        if wl_df.empty:
            print("❌ Watchlist 데이터 없음")
            return

        stock_codes = wl_df['stock_code'].unique().tolist()[:top_n]
        print(f"\n📋 대상: {wl_df['date'].iloc[0]} Watchlist {len(stock_codes)}종목")

        # 2. v2 캐시 데이터 벌크 조회
        factor_repo = FactorRepository(session)
        financial_trends = factor_repo.get_financial_trend(stock_codes)
        sentiment_momenta = factor_repo.get_sentiment_momentum_bulk(stock_codes)
        investor_ext = factor_repo.get_investor_trading_with_ratio(stock_codes)

        # KOSPI 일봉
        kospi_df = market_db.get_daily_prices(session, '0001', limit=150)

        # 3. 종목별 v1/v2 스코어링
        scorer = QuantScorer(db_conn=None)
        results = []

        for _, row in wl_df.iterrows():
            code = row['stock_code']
            name = row['stock_name'] or code

            # 데이터 로드
            daily_df = market_db.get_daily_prices(session, code, limit=150)
            if daily_df.empty or len(daily_df) < 30:
                continue

            fin = load_financial_snapshot(session, code)
            inv = load_latest_investor_trading(session, code)
            sentiment = load_latest_sentiment(session, code)
            eps_growth = compute_eps_growth(session, code)

            # 투자자 매매 동향 (10일)
            inv_trading_df = market_db.get_investor_trading(session, code, limit=10)

            # v2 전용 데이터
            ft = financial_trends.get(code)
            sm = sentiment_momenta.get(code)
            ext_df = investor_ext.get(code)
            frt = None
            if ext_df is not None and not ext_df.empty:
                if 'FOREIGN_HOLDING_RATIO' in ext_df.columns and len(ext_df) >= 20:
                    ratios = ext_df['FOREIGN_HOLDING_RATIO'].dropna()
                    if len(ratios) >= 20:
                        frt = float(ratios.iloc[-1] - ratios.iloc[-20])

            common_kwargs = dict(
                stock_code=code,
                stock_name=name,
                daily_prices_df=daily_df,
                kospi_prices_df=kospi_df if not kospi_df.empty else None,
                roe=fin.get('roe'),
                eps_growth=eps_growth,
                pbr=fin.get('pbr'),
                per=fin.get('per'),
                current_sentiment_score=sentiment,
                foreign_net_buy=inv.get('foreign_net_buy'),
                institution_net_buy=inv.get('institution_net_buy'),
                foreign_holding_ratio=inv.get('foreign_holding_ratio'),
                investor_trading_df=inv_trading_df if not inv_trading_df.empty else None,
            )

            # --- v1 ---
            qs_module.QUANT_SCORER_VERSION = 'v1'
            try:
                r1 = scorer.calculate_total_quant_score(**common_kwargs)
            except Exception as e:
                print(f"  ⚠️ v1 실패 {name}: {e}")
                continue

            # --- v2 ---
            qs_module.QUANT_SCORER_VERSION = 'v2'
            try:
                r2 = scorer.calculate_total_quant_score(
                    **common_kwargs,
                    financial_trend=ft,
                    sentiment_momentum=sm,
                    foreign_ratio_trend=frt,
                )
            except Exception as e:
                print(f"  ⚠️ v2 실패 {name}: {e}")
                continue

            results.append({
                'code': code,
                'name': name,
                'llm_score': row['llm_score'],
                'v1_total': r1.total_score,
                'v1_momentum': r1.momentum_score,
                'v1_quality': r1.quality_score,
                'v1_value': r1.value_score,
                'v1_technical': r1.technical_score,
                'v1_news': r1.news_stat_score,
                'v1_supply': r1.supply_demand_score,
                'v2_total': r2.total_score,
                'v2_momentum': r2.momentum_score,
                'v2_quality': r2.quality_score,
                'v2_value': r2.value_score,
                'v2_technical': r2.technical_score,
                'v2_news': r2.news_stat_score,
                'v2_supply': r2.supply_demand_score,
                'delta': r2.total_score - r1.total_score,
            })

        # 원래 v1으로 복원
        qs_module.QUANT_SCORER_VERSION = 'v1'

    if not results:
        print("❌ 스코어링 결과 없음")
        return

    df = pd.DataFrame(results)

    # ===================== 출력 =====================
    print(f"\n{'='*100}")
    print(f"  종목별 v1 vs v2 점수 비교 ({len(df)}종목)")
    print(f"{'='*100}")
    print(f"{'종목':>10} {'v1총점':>7} {'v2총점':>7} {'Δ':>6} │ {'v1M':>5} {'v2M':>5} {'v1Q':>5} {'v2Q':>5} {'v1V':>5} {'v2V':>5} {'v1T':>5} {'v2T':>5} {'v1N':>5} {'v2N':>5} {'v1S':>5} {'v2S':>5}")
    print(f"{'-'*100}")

    for _, r in df.sort_values('delta', ascending=False).iterrows():
        sign = '+' if r['delta'] >= 0 else ''
        print(
            f"{r['name'][:6]:>10} {r['v1_total']:7.1f} {r['v2_total']:7.1f} {sign}{r['delta']:5.1f} │ "
            f"{r['v1_momentum']:5.1f} {r['v2_momentum']:5.1f} "
            f"{r['v1_quality']:5.1f} {r['v2_quality']:5.1f} "
            f"{r['v1_value']:5.1f} {r['v2_value']:5.1f} "
            f"{r['v1_technical']:5.1f} {r['v2_technical']:5.1f} "
            f"{r['v1_news']:5.1f} {r['v2_news']:5.1f} "
            f"{r['v1_supply']:5.1f} {r['v2_supply']:5.1f}"
        )

    # 요약 통계
    print(f"\n{'='*100}")
    print("  요약 통계")
    print(f"{'='*100}")
    print(f"  v1 평균: {df['v1_total'].mean():.1f}  중위수: {df['v1_total'].median():.1f}  표준편차: {df['v1_total'].std():.1f}")
    print(f"  v2 평균: {df['v2_total'].mean():.1f}  중위수: {df['v2_total'].median():.1f}  표준편차: {df['v2_total'].std():.1f}")
    print(f"  Delta 평균: {df['delta'].mean():+.1f}  중위수: {df['delta'].median():+.1f}")
    print(f"  v2 상승: {(df['delta'] > 0).sum()}종목 / v2 하락: {(df['delta'] < 0).sum()}종목")

    # Rank 상관
    if len(df) >= 5:
        rank_corr, p_val = stats.spearmanr(df['v1_total'], df['v2_total'])
        print(f"\n  v1↔v2 Rank 상관: {rank_corr:.3f} (p={p_val:.4f})")

    # LLM 점수와의 상관
    valid_llm = df[df['llm_score'].notna()]
    if len(valid_llm) >= 5:
        ic_v1, _ = stats.spearmanr(valid_llm['v1_total'], valid_llm['llm_score'])
        ic_v2, _ = stats.spearmanr(valid_llm['v2_total'], valid_llm['llm_score'])
        print(f"  v1↔LLM 상관: {ic_v1:.3f}")
        print(f"  v2↔LLM 상관: {ic_v2:.3f}")

    # 팩터별 변화
    print(f"\n  팩터별 평균 변화:")
    for factor in ['momentum', 'quality', 'value', 'technical', 'news', 'supply']:
        v1_col, v2_col = f'v1_{factor}', f'v2_{factor}'
        d = df[v2_col].mean() - df[v1_col].mean()
        print(f"    {factor:>12}: v1={df[v1_col].mean():.1f} → v2={df[v2_col].mean():.1f} (Δ={d:+.1f})")

    # v2에서 순위 크게 변화한 종목
    df['v1_rank'] = df['v1_total'].rank(ascending=False)
    df['v2_rank'] = df['v2_total'].rank(ascending=False)
    df['rank_change'] = df['v1_rank'] - df['v2_rank']

    print(f"\n  🔺 v2에서 순위 상승 Top 5:")
    for _, r in df.nlargest(5, 'rank_change').iterrows():
        print(f"    {r['name'][:8]:>10}: v1 #{int(r['v1_rank'])} → v2 #{int(r['v2_rank'])} ({int(r['rank_change']):+d}위)")

    print(f"\n  🔻 v2에서 순위 하락 Top 5:")
    for _, r in df.nsmallest(5, 'rank_change').iterrows():
        print(f"    {r['name'][:8]:>10}: v1 #{int(r['v1_rank'])} → v2 #{int(r['v2_rank'])} ({int(r['rank_change']):+d}위)")

    # CSV 저장
    os.makedirs('scripts/output', exist_ok=True)
    out_path = f"scripts/output/v1_v2_dryrun_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    df.to_csv(out_path, index=False, encoding='utf-8-sig')
    print(f"\n  📄 결과 저장: {out_path}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Quant Scorer v1 vs v2 Dry-Run')
    parser.add_argument('--top', type=int, default=50, help='최대 종목 수')
    args = parser.parse_args()
    run_comparison(top_n=args.top)
