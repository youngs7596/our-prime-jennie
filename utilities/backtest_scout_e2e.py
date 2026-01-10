#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest_scout_e2e.py
---------------------

Scout 기반 E2E 백테스트 시뮬레이터

목적:
- Scout이 과거에 선정했을 법한 종목을 시뮬레이션
- 현재 시스템의 Buy/Sell Executor 로직으로 매매 시뮬레이션
- NEWS_SENTIMENT 테이블의 뉴스 감성 데이터 활용 (2017~2026, 49만건)

주요 기능:
1. ScoutSimulator: Factor Score + 뉴스 감성 기반 Scout 결과 추정
2. E2EBacktestEngine: Scout→Buy→Portfolio→Sell 전체 흐름 시뮬레이션
3. 기존 backtest_gpt_v2.py의 PortfolioEngine/ScannerLite 재사용
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd
from dotenv import load_dotenv

# 프로젝트 루트 설정
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)

from shared import auth, database
from shared.config import ConfigManager
from shared.factor_scoring import FactorScorer
from shared.market_regime import MarketRegimeDetector, StrategySelector
from shared.strategy_presets import (
    get_param_defaults as get_strategy_defaults,
    get_preset as get_strategy_preset,
)

# backtest_gpt_v2에서 공통 클래스 임포트
from utilities.backtest_gpt_v2 import (
    Candidate,
    Position,
    SellAction,
    PortfolioEngine,
    ScannerLite,
    load_price_series,
    prepare_indicators,
    get_row_at_or_before,
    fetch_top_trading_value_codes,
    load_investor_trading,
    load_financial_metrics,
)

logger = logging.getLogger(__name__)


# =============================================================================
# 뉴스 감성 데이터 로더
# =============================================================================

def load_news_sentiment_history(
    connection,
    stock_codes: List[str],
    start_date: datetime,
    end_date: datetime,
    lookback_days: int = 7
) -> Dict[str, pd.DataFrame]:
    """
    NEWS_SENTIMENT 테이블에서 종목별 뉴스 감성 히스토리 로드
    
    Args:
        connection: DB 연결
        stock_codes: 조회할 종목 코드 리스트
        start_date: 시작일
        end_date: 종료일
        lookback_days: 각 날짜에서 몇 일 이전까지 뉴스를 조회할지
        
    Returns:
        {stock_code: DataFrame(PUBLISHED_AT, SENTIMENT_SCORE, NEWS_TITLE)}
    """
    if not stock_codes:
        return {}
    
    # 조회 범위: start_date - lookback_days ~ end_date
    query_start = start_date - timedelta(days=lookback_days)
    
    placeholders = ','.join(['%s'] * len(stock_codes))
    query = f"""
        SELECT STOCK_CODE, PUBLISHED_AT, SENTIMENT_SCORE, NEWS_TITLE
        FROM NEWS_SENTIMENT
        WHERE STOCK_CODE IN ({placeholders})
          AND PUBLISHED_AT BETWEEN %s AND %s
        ORDER BY STOCK_CODE, PUBLISHED_AT
    """
    
    cursor = connection.cursor()
    try:
        cursor.execute(query, (*stock_codes, query_start, end_date))
        rows = cursor.fetchall()
    finally:
        cursor.close()
    
    if not rows:
        return {}
    
    # DataFrame으로 변환
    if isinstance(rows[0], dict):
        df = pd.DataFrame(rows)
    else:
        df = pd.DataFrame(rows, columns=["STOCK_CODE", "PUBLISHED_AT", "SENTIMENT_SCORE", "NEWS_TITLE"])
    
    df["PUBLISHED_AT"] = pd.to_datetime(df["PUBLISHED_AT"])
    
    # 종목별로 분리
    result = {}
    for code in stock_codes:
        code_df = df[df["STOCK_CODE"] == code].copy()
        if not code_df.empty:
            code_df.set_index("PUBLISHED_AT", inplace=True)
            result[code] = code_df
    
    logger.info(f"📰 뉴스 감성 데이터 로드: {len(result)}개 종목, {len(df)}건")
    return result


def get_sentiment_at_date(
    news_df: pd.DataFrame,
    target_date: datetime,
    lookback_days: int = 7
) -> Tuple[float, int]:
    """
    특정 날짜 기준 뉴스 감성 점수 계산
    
    Args:
        news_df: 종목의 뉴스 DataFrame (index: PUBLISHED_AT)
        target_date: 기준일
        lookback_days: 조회할 기간 (일)
        
    Returns:
        (avg_sentiment, news_count): 평균 감성 점수, 뉴스 건수
    """
    if news_df is None or news_df.empty:
        return 50.0, 0  # 중립값 반환
    
    start = target_date - timedelta(days=lookback_days)
    mask = (news_df.index >= start) & (news_df.index <= target_date)
    period_news = news_df.loc[mask]
    
    if period_news.empty:
        return 50.0, 0
    
    avg_score = period_news["SENTIMENT_SCORE"].mean()
    return float(avg_score), len(period_news)


# =============================================================================
# Scout 시뮬레이터
# =============================================================================

@dataclass
class ScoutSnapshot:
    """특정 시점의 Scout 결과 스냅샷"""
    date: datetime
    regime: str  # BULL, BEAR, NEUTRAL/SIDEWAYS
    hot_watchlist: List[dict]  # code, name, score, strategy, factor_score, news_sentiment


class ScoutSimulator:
    """
    과거 시점 Scout 결과 시뮬레이션
    
    Scout이 특정 날짜에 선정했을 종목을 Factor Score + 뉴스 감성으로 추정
    """
    
    def __init__(
        self,
        connection,
        price_cache: Dict[str, pd.DataFrame],
        stock_names: Dict[str, str],
        news_cache: Dict[str, pd.DataFrame],
        investor_cache: Dict[str, pd.DataFrame] = None,
        financial_cache: Dict[str, pd.DataFrame] = None,
        top_n: int = 30,
        min_score: float = 60.0,
    ):
        """
        Args:
            connection: DB 연결
            price_cache: 종목별 가격 DataFrame 캐시
            stock_names: {code: name} 매핑
            news_cache: 종목별 뉴스 DataFrame 캐시
            investor_cache: 수급 데이터 캐시
            financial_cache: 재무 데이터 캐시
            top_n: Hot Watchlist 크기
            min_score: Scout 통과 최소 점수
        """
        self.connection = connection
        self.price_cache = price_cache
        self.stock_names = stock_names
        self.news_cache = news_cache
        self.investor_cache = investor_cache or {}
        self.financial_cache = financial_cache or {}
        self.top_n = top_n
        self.min_score = min_score
        
        # 시장 분석 도구
        self.regime_detector = MarketRegimeDetector()
        self.strategy_selector = StrategySelector()
        self.factor_scorer = FactorScorer()
        
    def simulate_scout_for_date(self, target_date: datetime) -> ScoutSnapshot:
        """
        지정 날짜에 Scout이 선정했을 종목 추정
        
        로직:
        1. 해당 일자의 시장 Regime 판단
        2. 전일까지의 데이터로 각 종목 Factor Score 계산
        3. 뉴스 감성 점수 조회 및 반영
        4. 최종 점수 상위 N개 종목을 Hot Watchlist로 반환
        """
        # 1. 시장 Regime 감지
        kospi_df = self.price_cache.get("0001")
        if kospi_df is None or kospi_df.empty:
            regime = "SIDEWAYS"
        else:
            kospi_slice = kospi_df.loc[:target_date].tail(60)
            if not kospi_slice.empty:
                close_df = kospi_slice[["CLOSE_PRICE"]]
                current_price = float(close_df["CLOSE_PRICE"].iloc[-1])
                regime, _ = self.regime_detector.detect_regime(close_df, current_price, quiet=True)
            else:
                regime = "SIDEWAYS"
        
        strategies = self.strategy_selector.select_strategies(regime)
        
        # 2. 종목별 점수 계산
        candidates = []
        
        for code in sorted(self.price_cache.keys()):
            if code == "0001":  # KOSPI 인덱스 제외
                continue
                
            df = self.price_cache[code]
            if df.empty:
                continue
            
            # 전일까지의 데이터만 사용 (Look-Ahead Bias 방지)
            df_window = df.loc[:target_date].tail(220)
            if df_window.empty or len(df_window) < 20:
                continue
            
            # 전일 데이터로 점수 계산
            prev_data = df_window.iloc[:-1] if target_date in df_window.index else df_window
            if prev_data.empty:
                continue
            
            try:
                # Factor Score 계산
                kospi_slice = kospi_df.loc[:target_date].tail(len(prev_data)) if kospi_df is not None else pd.DataFrame()
                
                momentum, _ = self.factor_scorer.calculate_momentum_score(prev_data, kospi_slice)
                quality, _ = self.factor_scorer.calculate_quality_score(
                    roe=None, sales_growth=None, eps_growth=None, daily_prices_df=prev_data
                )
                value, _ = self.factor_scorer.calculate_value_score(pbr=None, per=None)
                technical, _ = self.factor_scorer.calculate_technical_score(prev_data)
                
                # 수급 보너스
                investor_bonus = 0.0
                inv_df = self.investor_cache.get(code)
                if inv_df is not None and not inv_df.empty:
                    recent = inv_df.loc[:target_date].tail(5)
                    if not recent.empty:
                        f_sum = recent.get("FOREIGN_NET_BUY", pd.Series([0])).sum()
                        i_sum = recent.get("INSTITUTION_NET_BUY", pd.Series([0])).sum()
                        if f_sum > 0 and i_sum > 0:
                            investor_bonus = 50.0  # 쌍끌이 보너스
                
                final_score, _ = self.factor_scorer.calculate_final_score(
                    momentum, quality, value, technical, regime
                )
                factor_score = min(100.0, (final_score + investor_bonus) / 10.0)
                
                # 뉴스 감성 점수 조회
                news_df = self.news_cache.get(code)
                news_sentiment, news_count = get_sentiment_at_date(news_df, target_date, lookback_days=7)
                
                # 뉴스 감성 보정 (-10 ~ +10점)
                # 감성 50 = 중립, 0 = 매우 부정, 100 = 매우 긍정
                news_adjustment = (news_sentiment - 50) / 5  # -10 ~ +10
                
                # 최종 Scout 점수 추정
                # 기본점수 55 + Factor 기여(40%) + 뉴스 보정
                estimated_score = 55 + (factor_score * 0.4) + news_adjustment
                estimated_score = max(0, min(100, estimated_score))
                
                if estimated_score >= self.min_score:
                    candidates.append({
                        "code": code,
                        "name": self.stock_names.get(code, code),
                        "factor_score": factor_score,
                        "news_sentiment": news_sentiment,
                        "news_count": news_count,
                        "estimated_score": estimated_score,
                        "regime": regime,
                        "strategies": strategies,
                    })
                    
            except Exception as e:
                logger.debug(f"[{code}] Scout 시뮬레이션 실패: {e}")
                continue
        
        # 3. 상위 N개 선정
        candidates.sort(key=lambda x: x["estimated_score"], reverse=True)
        hot_watchlist = candidates[:self.top_n]
        
        logger.info(
            f"📊 [{target_date.strftime('%Y-%m-%d')}] Scout 시뮬레이션: "
            f"Regime={regime}, 후보={len(candidates)}, Hot Watchlist={len(hot_watchlist)}"
        )
        
        return ScoutSnapshot(
            date=target_date,
            regime=regime,
            hot_watchlist=hot_watchlist,
        )


# =============================================================================
# E2E 백테스트 엔진
# =============================================================================

class E2EBacktestEngine:
    """
    Scout→Buy Scanner→Buy Executor→Price Monitor→Sell Executor
    전체 흐름 시뮬레이션
    """
    
    def __init__(
        self,
        connection,
        start_date: datetime,
        end_date: datetime,
        initial_capital: float = 10_000_000,
        # Buy Executor 설정
        daily_buy_limit: int = 3,
        max_portfolio_size: int = 10,
        max_sector_pct: float = 0.3,
        max_stock_pct: float = 0.15,
        # Sell Executor 설정
        target_profit_pct: float = 0.15,
        stop_loss_pct: float = 0.07,
        rsi_overbought: float = 70,
        # Scout 설정
        scout_top_n: int = 30,
        scout_min_score: float = 60.0,
        # 매수 신호 임계값
        buy_signal_threshold: float = 70.0,
    ):
        self.connection = connection
        self.start_date = start_date
        self.end_date = end_date
        
        # 설정
        self.daily_buy_limit = daily_buy_limit
        self.max_portfolio_size = max_portfolio_size
        self.max_sector_pct = max_sector_pct
        self.max_stock_pct = max_stock_pct
        self.target_profit_pct = target_profit_pct
        self.stop_loss_pct = stop_loss_pct
        self.rsi_overbought = rsi_overbought
        self.scout_top_n = scout_top_n
        self.scout_min_score = scout_min_score
        self.buy_signal_threshold = buy_signal_threshold
        
        # Portfolio Engine (기존 백테스트 재사용)
        self.portfolio = PortfolioEngine(
            initial_capital=initial_capital,
            max_position_pct=max_stock_pct,
            max_positions=max_portfolio_size,
            target_profit_pct=target_profit_pct,
            stop_loss_pct=stop_loss_pct,
            stop_loss_atr_mult=2.0,
            max_hold_days=60,
        )
        
        # 캐시 (나중에 로드)
        self.price_cache: Dict[str, pd.DataFrame] = {}
        self.stock_names: Dict[str, str] = {}
        self.news_cache: Dict[str, pd.DataFrame] = {}
        self.investor_cache: Dict[str, pd.DataFrame] = {}
        self.financial_cache: Dict[str, pd.DataFrame] = {}
        
        # 결과
        self.equity_curve: List[Tuple[datetime, float]] = []
        self.scout_snapshots: List[ScoutSnapshot] = []
        
    def load_data(self, stock_codes: List[str] = None):
        """
        시뮬레이션에 필요한 모든 데이터 로드
        """
        logger.info("📥 데이터 로딩 시작...")
        
        # 종목 코드 결정
        if stock_codes is None:
            stock_codes = fetch_top_trading_value_codes(self.connection, limit=200)
            stock_codes.insert(0, "0001")  # KOSPI 인덱스
        
        # 1. 가격 데이터 로드
        logger.info(f"   ... 가격 데이터 로드 ({len(stock_codes)}개 종목)")
        for code in stock_codes:
            df = load_price_series(self.connection, code)
            if not df.empty:
                df = prepare_indicators(df)
                self.price_cache[code] = df
        
        # 종목명 조회
        cursor = self.connection.cursor()
        cursor.execute("SELECT STOCK_CODE, STOCK_NAME FROM STOCK_MASTER")
        for row in cursor.fetchall():
            if isinstance(row, dict):
                self.stock_names[row["STOCK_CODE"]] = row["STOCK_NAME"]
            else:
                self.stock_names[row[0]] = row[1]
        cursor.close()
        
        # 2. 뉴스 감성 데이터 로드
        logger.info("   ... 뉴스 감성 데이터 로드")
        self.news_cache = load_news_sentiment_history(
            self.connection,
            stock_codes=[c for c in stock_codes if c != "0001"],
            start_date=self.start_date,
            end_date=self.end_date,
            lookback_days=7
        )
        
        # 3. 수급 데이터 로드
        logger.info("   ... 수급 데이터 로드")
        for code in stock_codes:
            if code == "0001":
                continue
            inv_df = load_investor_trading(self.connection, code, days=400)
            if not inv_df.empty:
                self.investor_cache[code] = inv_df
        
        # 4. 재무 데이터 로드
        logger.info("   ... 재무 데이터 로드")
        for code in stock_codes:
            if code == "0001":
                continue
            fin_df = load_financial_metrics(self.connection, code)
            if not fin_df.empty:
                self.financial_cache[code] = fin_df
        
        logger.info(
            f"✅ 데이터 로드 완료: "
            f"가격={len(self.price_cache)}, 뉴스={len(self.news_cache)}, "
            f"수급={len(self.investor_cache)}, 재무={len(self.financial_cache)}"
        )
        
    def run_simulation(self) -> Dict:
        """
        E2E 시뮬레이션 실행
        
        Returns:
            결과 요약 dict
        """
        logger.info(f"🚀 E2E 시뮬레이션 시작: {self.start_date.strftime('%Y-%m-%d')} ~ {self.end_date.strftime('%Y-%m-%d')}")
        
        # Scout 시뮬레이터 초기화
        scout_sim = ScoutSimulator(
            connection=self.connection,
            price_cache=self.price_cache,
            stock_names=self.stock_names,
            news_cache=self.news_cache,
            investor_cache=self.investor_cache,
            financial_cache=self.financial_cache,
            top_n=self.scout_top_n,
            min_score=self.scout_min_score,
        )
        
        # 거래일 목록 추출
        kospi_df = self.price_cache.get("0001")
        if kospi_df is None:
            logger.error("KOSPI 데이터 없음")
            return {}
        
        trading_days = kospi_df.loc[self.start_date:self.end_date].index.tolist()
        logger.info(f"📅 거래일: {len(trading_days)}일")
        
        # 일별 시뮬레이션
        for i, current_date in enumerate(trading_days):
            daily_buys = 0
            
            # 1. Scout 시뮬레이션 (매일 아침)
            scout_result = scout_sim.simulate_scout_for_date(current_date)
            self.scout_snapshots.append(scout_result)
            
            hot_watchlist_codes = {item["code"] for item in scout_result.hot_watchlist}
            
            # 2. Buy Scanner 시뮬레이션
            # Hot Watchlist 종목 중 매수 신호 발생한 종목 탐색
            for item in scout_result.hot_watchlist:
                if daily_buys >= self.daily_buy_limit:
                    break
                if len(self.portfolio.positions) >= self.max_portfolio_size:
                    break
                if item["code"] in self.portfolio.positions:
                    continue  # 이미 보유 중
                    
                code = item["code"]
                df = self.price_cache.get(code)
                if df is None or current_date not in df.index:
                    continue
                
                row = df.loc[current_date]
                price = float(row["CLOSE_PRICE"])
                atr = float(row.get("ATR", price * 0.02)) if not pd.isna(row.get("ATR")) else price * 0.02
                
                # 매수 신호: Scout 점수가 임계값 이상
                if item["estimated_score"] >= self.buy_signal_threshold:
                    # 포지션 사이즈 계산
                    position_value = self.portfolio.cash * self.max_stock_pct
                    qty = int(position_value / price)
                    
                    if qty > 0:
                        # 매수 실행
                        candidate = Candidate(
                            code=code,
                            price=price,
                            signal="SCOUT_BUY",
                            score=item["estimated_score"],
                            factor_score=item["factor_score"],
                            llm_score=item["estimated_score"],
                        )
                        
                        risk_setting = {
                            "stop_loss_pct": self.stop_loss_pct,
                            "target_profit_pct": self.target_profit_pct,
                        }
                        
                        success = self.portfolio.execute_buy(
                            candidate=candidate,
                            qty=qty,
                            trade_date=current_date,
                            slot_timestamp=current_date,
                            atr=atr,
                            sector="기타",  # TODO: 섹터 정보 추가
                            risk_setting=risk_setting,
                        )
                        
                        if success:
                            daily_buys += 1
            
            # 3. Sell 시뮬레이션
            def price_lookup(code: str) -> float:
                df = self.price_cache.get(code)
                if df is None or current_date not in df.index:
                    return 0.0
                return float(df.loc[current_date]["CLOSE_PRICE"])
            
            sell_actions = self.portfolio.process_slot(
                slot_timestamp=current_date,
                trade_date=current_date,
                price_lookup=price_lookup,
                price_cache=self.price_cache,
                risk_setting={
                    "stop_loss_pct": -self.stop_loss_pct,
                    "target_profit_pct": self.target_profit_pct,
                },
                rsi_thresholds=(70, 75, 80),
            )
            
            # 4. 일일 자산 기록
            equity = self.portfolio.total_value(current_date, self.price_cache, price_lookup)
            self.equity_curve.append((current_date, equity))
            
            if (i + 1) % 20 == 0:
                logger.info(
                    f"   [{current_date.strftime('%Y-%m-%d')}] "
                    f"자산: {equity:,.0f}원, 포지션: {len(self.portfolio.positions)}"
                )
        
        # 결과 계산
        initial = self.portfolio.initial_capital
        final = self.equity_curve[-1][1] if self.equity_curve else initial
        total_return = (final - initial) / initial * 100
        
        # MDD 계산
        peak = initial
        mdd = 0
        for _, equity in self.equity_curve:
            if equity > peak:
                peak = equity
            drawdown = (peak - equity) / peak
            if drawdown > mdd:
                mdd = drawdown
        
        result = {
            "start_date": self.start_date.strftime("%Y-%m-%d"),
            "end_date": self.end_date.strftime("%Y-%m-%d"),
            "trading_days": len(trading_days),
            "initial_capital": initial,
            "final_equity": final,
            "total_return_pct": total_return,
            "max_drawdown_pct": mdd * 100,
            "total_trades": len(self.portfolio.trade_log),
        }
        
        logger.info("=" * 60)
        logger.info(f"📈 시뮬레이션 완료")
        logger.info(f"   기간: {result['start_date']} ~ {result['end_date']} ({result['trading_days']}일)")
        logger.info(f"   초기 자본: {initial:,.0f}원")
        logger.info(f"   최종 자산: {final:,.0f}원")
        logger.info(f"   총 수익률: {total_return:.2f}%")
        logger.info(f"   최대 낙폭: {mdd * 100:.2f}%")
        logger.info(f"   총 거래: {result['total_trades']}건")
        logger.info("=" * 60)
        
        return result
    
    def save_results(self, output_dir: str = "logs"):
        """결과 저장"""
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        
        # 자산 곡선 저장
        equity_df = pd.DataFrame(self.equity_curve, columns=["date", "equity"])
        equity_path = os.path.join(output_dir, f"backtest_scout_e2e_equity_{timestamp}.csv")
        equity_df.to_csv(equity_path, index=False)
        
        # 거래 로그 저장
        if self.portfolio.trade_log:
            trades_df = pd.DataFrame(self.portfolio.trade_log)
            trades_path = os.path.join(output_dir, f"backtest_scout_e2e_trades_{timestamp}.csv")
            trades_df.to_csv(trades_path, index=False)
        
        logger.info(f"💾 결과 저장: {equity_path}")


# =============================================================================
# 메인
# =============================================================================

def parse_args():
    # 기본값: 최근 6개월
    from datetime import datetime, timedelta
    default_end = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")  # 어제
    default_start = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")  # 6개월 전
    
    parser = argparse.ArgumentParser(description="Scout 기반 E2E 백테스트 시뮬레이터")
    
    # 기본 설정
    parser.add_argument("--start-date", type=str, default=default_start, help=f"시작일 (YYYY-MM-DD, 기본: {default_start})")
    parser.add_argument("--end-date", type=str, default=default_end, help=f"종료일 (YYYY-MM-DD, 기본: {default_end})")
    parser.add_argument("--capital", type=float, default=10_000_000, help="초기 자본금")
    parser.add_argument("--verbose", action="store_true", help="상세 로그 출력")
    
    # === Scout 설정 (튜닝 대상) ===
    parser.add_argument("--scout-min-score", type=float, default=60.0, help="Scout 통과 최소 점수")
    parser.add_argument("--scout-top-n", type=int, default=30, help="Hot Watchlist 크기")
    
    # === Buy Executor 설정 (튜닝 대상) ===
    parser.add_argument("--daily-buy-limit", type=int, default=3, help="일일 매수 한도")
    parser.add_argument("--max-portfolio-size", type=int, default=10, help="최대 포트폴리오 크기")
    parser.add_argument("--max-stock-pct", type=float, default=0.15, help="종목당 최대 비중")
    parser.add_argument("--max-sector-pct", type=float, default=0.30, help="섹터당 최대 비중")
    
    # === Sell Executor 설정 (튜닝 대상) ===
    parser.add_argument("--target-profit-pct", type=float, default=0.15, help="목표 수익률")
    parser.add_argument("--stop-loss-pct", type=float, default=0.07, help="손절 비율")
    parser.add_argument("--rsi-overbought", type=float, default=70, help="RSI 과매수 기준")
    
    # === 매수 신호 임계값 (튜닝 대상) ===
    parser.add_argument("--buy-signal-threshold", type=float, default=70, help="매수 신호 트리거 점수")
    
    return parser.parse_args()



def main():
    load_dotenv()
    args = parse_args()
    
    # 로깅 설정
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    
    start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
    end_date = datetime.strptime(args.end_date, "%Y-%m-%d")
    
    logger.info("🔧 Scout E2E 백테스트 시뮬레이터")
    logger.info(f"   기간: {args.start_date} ~ {args.end_date}")
    logger.info(f"   초기 자본: {args.capital:,.0f}원")
    
    # DB 연결
    conn = database.get_db_connection()
    if not conn:
        logger.error("DB 연결 실패")
        return
    
    try:
        # 엔진 초기화 (CLI 파라미터 사용)
        engine = E2EBacktestEngine(
            connection=conn,
            start_date=start_date,
            end_date=end_date,
            initial_capital=args.capital,
            # Buy Executor 설정
            daily_buy_limit=args.daily_buy_limit,
            max_portfolio_size=args.max_portfolio_size,
            max_sector_pct=args.max_sector_pct,
            max_stock_pct=args.max_stock_pct,
            # Sell Executor 설정
            target_profit_pct=args.target_profit_pct,
            stop_loss_pct=args.stop_loss_pct,
            rsi_overbought=args.rsi_overbought,
            # Scout 설정
            scout_top_n=args.scout_top_n,
            scout_min_score=args.scout_min_score,
        )
        
        # 매수 신호 임계값 저장 (실행 시 사용)
        engine.buy_signal_threshold = args.buy_signal_threshold
        
        # 데이터 로드
        engine.load_data()
        
        # 시뮬레이션 실행
        result = engine.run_simulation()
        
        # 결과 저장
        engine.save_results()
        
    finally:
        conn.close()


if __name__ == "__main__":
    main()
