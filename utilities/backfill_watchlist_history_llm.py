#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backfill_watchlist_history_llm.py

과거 시점 기준으로 Scout 결과를 재생성하여 WATCHLIST_HISTORY에 저장합니다.
- 과거 데이터(뉴스/가격/수급/재무) 컷오프로 구성
- 현재 로컬 LLM(Ollama)을 사용해 Hunter 점수를 생성
"""

from __future__ import annotations

import argparse
import os
import sys
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)

import shared.database as database
from shared.db.connection import ensure_engine_initialized, session_scope
from shared.llm_factory import LLMFactory, LLMTier
from shared.llm_constants import ANALYSIS_RESPONSE_SCHEMA
from shared.llm_prompts import build_hunter_prompt_v5

from utilities.backtest_scout_e2e import (
    ScoutSimulator,
    load_price_series,
    prepare_indicators,
    load_news_sentiment_history,
    load_investor_trading,
    load_financial_metrics,
    get_sentiment_at_date,
    fetch_top_trading_value_codes,
)

logger = logging.getLogger(__name__)


def _force_local_llm() -> None:
    os.environ.setdefault("TIER_FAST_PROVIDER", "ollama")
    os.environ.setdefault("TIER_REASONING_PROVIDER", "ollama")
    os.environ.setdefault("TIER_THINKING_PROVIDER", "ollama")
    os.environ.setdefault("LOCAL_MODEL_REASONING", "gpt-oss:20b")
    os.environ.setdefault("VLLM_LLM_URL", "http://localhost:8001/v1")


def _load_trading_days(conn, start: datetime, end: datetime) -> List[datetime]:
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT DISTINCT PRICE_DATE
            FROM STOCK_DAILY_PRICES_3Y
            WHERE PRICE_DATE BETWEEN %s AND %s
            ORDER BY PRICE_DATE ASC
            """,
            (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")),
        )
        rows = cursor.fetchall()
    finally:
        cursor.close()

    dates = []
    for row in rows:
        value = row["PRICE_DATE"] if isinstance(row, dict) else row[0]
        if isinstance(value, datetime):
            dates.append(value)
        else:
            dates.append(datetime.fromisoformat(str(value)))
    return dates


def _build_news_reason(
    news_df,
    target_date: datetime,
    lookback_days: int = 7,
    cutoff_hour: int = 9,
    cutoff_minute: int = 0,
    max_titles: int = 5,
) -> str:
    if news_df is None or news_df.empty:
        return "특별한 뉴스 없음"
    cutoff_time = target_date.replace(hour=cutoff_hour, minute=cutoff_minute, second=0, microsecond=0)
    start = cutoff_time - timedelta(days=lookback_days)
    period = news_df.loc[(news_df.index >= start) & (news_df.index <= cutoff_time)]
    if period.empty:
        return "특별한 뉴스 없음"
    titles = period["NEWS_TITLE"].dropna().tail(max_titles).tolist()
    if not titles:
        return "특별한 뉴스 없음"
    return " / ".join(str(t) for t in titles[:max_titles])


def _ensure_code_loaded(
    conn,
    code: str,
    start_date: datetime,
    end_date: datetime,
    price_cache: Dict,
    investor_cache: Dict,
    financial_cache: Dict,
    news_cache: Dict,
    stock_names: Dict,
) -> None:
    if code in price_cache:
        return
    df = load_price_series(conn, code)
    if df.empty:
        return
    price_cache[code] = prepare_indicators(df)
    investor_cache[code] = load_investor_trading(conn, code, days=400)
    financial_cache[code] = load_financial_metrics(conn, code)
    news = load_news_sentiment_history(
        conn,
        stock_codes=[code],
        start_date=start_date,
        end_date=end_date,
        lookback_days=7,
    )
    if news:
        news_cache[code] = news.get(code)

    cursor = conn.cursor()
    try:
        cursor.execute("SELECT STOCK_NAME FROM STOCK_MASTER WHERE STOCK_CODE = %s", (code,))
        row = cursor.fetchone()
        if row:
            name = row["STOCK_NAME"] if isinstance(row, dict) else row[0]
            stock_names[code] = name
    finally:
        cursor.close()


def parse_args() -> argparse.Namespace:
    default_end = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    default_start = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")
    parser = argparse.ArgumentParser(description="WATCHLIST_HISTORY LLM 백필 스크립트")
    parser.add_argument("--start-date", type=str, default=default_start)
    parser.add_argument("--end-date", type=str, default=default_end)
    parser.add_argument("--top-n", type=int, default=30)
    parser.add_argument("--min-score", type=float, default=60.0)
    parser.add_argument("--force-local-llm", action="store_true", help="로컬 LLM(Ollama) 강제 사용")
    return parser.parse_args()


def main() -> None:
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    args = parse_args()
    start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
    end_date = datetime.strptime(args.end_date, "%Y-%m-%d")

    if args.force_local_llm:
        _force_local_llm()

    conn = database.get_db_connection()
    if conn is None:
        raise SystemExit("DB 연결 실패")
    ensure_engine_initialized()

    trading_days = _load_trading_days(conn, start_date, end_date)
    if not trading_days:
        logger.error("거래일 데이터가 없습니다.")
        return

    price_cache: Dict[str, object] = {}
    investor_cache: Dict[str, object] = {}
    financial_cache: Dict[str, object] = {}
    news_cache: Dict[str, object] = {}
    stock_names: Dict[str, str] = {}

    # KOSPI는 항상 로드
    _ensure_code_loaded(
        conn,
        "0001",
        start_date,
        end_date,
        price_cache,
        investor_cache,
        financial_cache,
        news_cache,
        stock_names,
    )

    provider = LLMFactory.get_provider(LLMTier.REASONING)
    scout_sim = ScoutSimulator(
        connection=conn,
        price_cache=price_cache,
        stock_names=stock_names,
        news_cache=news_cache,
        investor_cache=investor_cache,
        financial_cache=financial_cache,
        top_n=args.top_n,
        min_score=args.min_score,
    )

    for idx, current_date in enumerate(trading_days):
        universe = fetch_top_trading_value_codes(conn, limit=200, as_of_date=current_date)
        for code in universe:
            _ensure_code_loaded(
                conn,
                code,
                start_date,
                end_date,
                price_cache,
                investor_cache,
                financial_cache,
                news_cache,
                stock_names,
            )

        snapshot = scout_sim.simulate_scout_for_date(current_date, universe_codes=universe)
        results = []
        for item in snapshot.hot_watchlist:
            news_df = news_cache.get(item["code"])
            news_reason = _build_news_reason(news_df, current_date)
            quant_context = (
                f"정량 점수: {item.get('factor_score', 0):.1f}점, "
                f"뉴스 감성: {item.get('news_sentiment', 50):.1f}, "
                f"뉴스 건수: {item.get('news_count', 0)}"
            )
            stock_info = {
                "code": item["code"],
                "name": item["name"],
                "news_reason": news_reason,
            }
            prompt = build_hunter_prompt_v5(stock_info, quant_context)
            try:
                hunter = provider.generate_chat(
                    [{"role": "user", "content": prompt}],
                    response_schema=ANALYSIS_RESPONSE_SCHEMA,
                    temperature=0.2,
                )
            except Exception as e:
                logger.error("❌ Local LLM 실패 (%s %s): %s", item["name"], item["code"], e)
                continue
            llm_score = hunter.get("score", 0)
            llm_reason = hunter.get("reason", "")
            results.append(
                {
                    "code": item["code"],
                    "name": item["name"],
                    "is_tradable": True,
                    "llm_score": llm_score,
                    "llm_reason": f"[BACKFILL] {llm_reason}",
                }
            )

        if results:
            with session_scope() as session:
                database.save_to_watchlist_history(
                    session,
                    results,
                    snapshot_date=current_date.strftime("%Y-%m-%d"),
                )
            logger.info("✅ %s 저장: %d개", current_date.strftime("%Y-%m-%d"), len(results))

    conn.close()


if __name__ == "__main__":
    main()
