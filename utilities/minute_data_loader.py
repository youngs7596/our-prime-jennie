#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
minute_data_loader.py
---------------------

분봉 데이터 로더 모듈

목적:
- stock_minute_price 테이블에서 분봉 데이터 로드
- 일중 가격 경로(path)로 변환하여 백테스트에서 활용

데이터 기간: 2025-12-17 ~ (ongoing)
"""

import logging
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

# 장 운영 시간 (09:00 ~ 15:30)
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 0
MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MINUTE = 30

# 5분봉 기준 슬롯 수: 09:00 ~ 15:25 = 78개 슬롯
# (15:30은 동시호가이므로 15:25까지)
MINUTE_INTERVAL = 5
SLOT_COUNT = ((MARKET_CLOSE_HOUR * 60 + MARKET_CLOSE_MINUTE) - 
              (MARKET_OPEN_HOUR * 60 + MARKET_OPEN_MINUTE)) // MINUTE_INTERVAL


def load_minute_prices(
    connection,
    stock_code: str,
    start_date: datetime,
    end_date: datetime,
) -> pd.DataFrame:
    """
    stock_minute_price 테이블에서 분봉 데이터 로드
    
    Args:
        connection: PyMySQL/SQLAlchemy 연결
        stock_code: 종목 코드
        start_date: 시작일
        end_date: 종료일
        
    Returns:
        DataFrame with columns: [PRICE_TIME, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, CLOSE_PRICE, VOLUME]
        Index: PRICE_TIME (datetime)
    """
    query = """
        SELECT PRICE_TIME, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, CLOSE_PRICE, VOLUME
        FROM stock_minute_price
        WHERE STOCK_CODE = %s
          AND PRICE_TIME BETWEEN %s AND %s
        ORDER BY PRICE_TIME ASC
    """
    
    cursor = connection.cursor()
    try:
        cursor.execute(query, (stock_code, start_date, end_date))
        rows = cursor.fetchall()
    finally:
        cursor.close()
    
    if not rows:
        return pd.DataFrame()
    
    # DictCursor 지원
    if isinstance(rows[0], dict):
        df = pd.DataFrame(rows)
    else:
        df = pd.DataFrame(
            rows, 
            columns=["PRICE_TIME", "OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE", "CLOSE_PRICE", "VOLUME"]
        )
    
    df["PRICE_TIME"] = pd.to_datetime(df["PRICE_TIME"])
    df.set_index("PRICE_TIME", inplace=True)
    
    return df


def load_minute_prices_batch(
    connection,
    stock_codes: List[str],
    start_date: datetime,
    end_date: datetime,
) -> Dict[str, pd.DataFrame]:
    """
    여러 종목의 분봉 데이터 일괄 로드
    
    Args:
        connection: DB 연결
        stock_codes: 종목 코드 리스트
        start_date: 시작일
        end_date: 종료일
        
    Returns:
        {stock_code: DataFrame} 매핑
    """
    if not stock_codes:
        return {}
    
    placeholders = ','.join(['%s'] * len(stock_codes))
    query = f"""
        SELECT STOCK_CODE, PRICE_TIME, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, CLOSE_PRICE, VOLUME
        FROM stock_minute_price
        WHERE STOCK_CODE IN ({placeholders})
          AND PRICE_TIME BETWEEN %s AND %s
        ORDER BY STOCK_CODE, PRICE_TIME ASC
    """
    
    cursor = connection.cursor()
    try:
        cursor.execute(query, (*stock_codes, start_date, end_date))
        rows = cursor.fetchall()
    finally:
        cursor.close()
    
    if not rows:
        return {}
    
    # DataFrame 변환
    if isinstance(rows[0], dict):
        df = pd.DataFrame(rows)
    else:
        df = pd.DataFrame(
            rows,
            columns=["STOCK_CODE", "PRICE_TIME", "OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE", "CLOSE_PRICE", "VOLUME"]
        )
    
    df["PRICE_TIME"] = pd.to_datetime(df["PRICE_TIME"])
    
    # 종목별로 분리
    result = {}
    for code in stock_codes:
        code_df = df[df["STOCK_CODE"] == code].copy()
        if not code_df.empty:
            code_df.set_index("PRICE_TIME", inplace=True)
            code_df.drop(columns=["STOCK_CODE"], inplace=True)
            result[code] = code_df
    
    logger.info(f"📊 분봉 데이터 로드: {len(result)}개 종목, 총 {len(df)}건")
    return result


def build_intraday_path(
    minute_df: pd.DataFrame,
    target_date: date,
    interval_minutes: int = 5,
) -> List[float]:
    """
    특정 날짜의 분봉 데이터를 일중 가격 경로로 변환
    
    Args:
        minute_df: 분봉 DataFrame (index: PRICE_TIME)
        target_date: 대상 날짜 (date 객체)
        interval_minutes: 분봉 간격 (기본 5분)
        
    Returns:
        List[float]: 시간순 종가 리스트 (5분 간격)
        빈 슬롯은 이전 가격으로 forward-fill
    """
    if minute_df is None or minute_df.empty:
        return []
    
    # 해당 날짜의 데이터만 필터링
    if isinstance(target_date, datetime):
        target_date = target_date.date()
    
    day_start = datetime.combine(target_date, datetime.min.time())
    day_end = day_start + timedelta(days=1)
    
    day_df = minute_df[(minute_df.index >= day_start) & (minute_df.index < day_end)]
    
    if day_df.empty:
        return []
    
    # 5분 간격 슬롯 생성 (09:00 ~ 15:25)
    slots = []
    current_time = day_start.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE)
    end_time = day_start.replace(hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MINUTE - interval_minutes)
    
    last_price = None
    
    while current_time <= end_time:
        # 해당 시간대의 분봉 찾기 (정확한 시간 또는 직전)
        slot_data = day_df[day_df.index <= current_time]
        
        if not slot_data.empty:
            last_price = float(slot_data["CLOSE_PRICE"].iloc[-1])
        
        if last_price is not None:
            slots.append(last_price)
        
        current_time += timedelta(minutes=interval_minutes)
    
    return slots


def get_intraday_ohlc(
    minute_df: pd.DataFrame,
    target_date: date,
) -> Optional[Dict[str, float]]:
    """
    특정 날짜의 시가/고가/저가/종가 계산
    
    Args:
        minute_df: 분봉 DataFrame
        target_date: 대상 날짜
        
    Returns:
        {"open": float, "high": float, "low": float, "close": float}
        또는 데이터 없으면 None
    """
    if minute_df is None or minute_df.empty:
        return None
    
    if isinstance(target_date, datetime):
        target_date = target_date.date()
    
    day_start = datetime.combine(target_date, datetime.min.time())
    day_end = day_start + timedelta(days=1)
    
    day_df = minute_df[(minute_df.index >= day_start) & (minute_df.index < day_end)]
    
    if day_df.empty:
        return None
    
    return {
        "open": float(day_df["OPEN_PRICE"].iloc[0]),
        "high": float(day_df["HIGH_PRICE"].max()),
        "low": float(day_df["LOW_PRICE"].min()),
        "close": float(day_df["CLOSE_PRICE"].iloc[-1]),
    }


def get_price_at_time(
    minute_df: pd.DataFrame,
    target_datetime: datetime,
    lookback_minutes: int = 10,
) -> Optional[float]:
    """
    특정 시각의 가격 조회 (정확한 시간이 없으면 lookback)
    
    Args:
        minute_df: 분봉 DataFrame
        target_datetime: 조회할 시각
        lookback_minutes: 데이터 없을 때 이전 몇 분까지 탐색
        
    Returns:
        해당 시각의 종가 또는 None
    """
    if minute_df is None or minute_df.empty:
        return None
    
    # 정확한 시각 조회
    if target_datetime in minute_df.index:
        return float(minute_df.loc[target_datetime, "CLOSE_PRICE"])
    
    # Lookback: 해당 시각 이전 데이터 중 가장 최근
    lookback_start = target_datetime - timedelta(minutes=lookback_minutes)
    recent = minute_df[(minute_df.index >= lookback_start) & (minute_df.index <= target_datetime)]
    
    if not recent.empty:
        return float(recent["CLOSE_PRICE"].iloc[-1])
    
    return None


# =============================================================================
# Scout History 로더
# =============================================================================

def load_scout_history(
    connection,
    start_date: datetime,
    end_date: datetime,
) -> Dict[date, List[dict]]:
    """
    watchlist_history 테이블에서 Scout 선정 종목 히스토리 로드
    
    Args:
        connection: DB 연결
        start_date: 시작일
        end_date: 종료일
        
    Returns:
        {date: [{"code": "005930", "name": "삼성전자", "llm_score": 85.0, "is_tradable": 1}, ...]}
    """
    query = """
        SELECT SNAPSHOT_DATE, STOCK_CODE, STOCK_NAME, LLM_SCORE, IS_TRADABLE, LLM_REASON
        FROM watchlist_history
        WHERE SNAPSHOT_DATE BETWEEN %s AND %s
        ORDER BY SNAPSHOT_DATE, LLM_SCORE DESC
    """
    
    cursor = connection.cursor()
    try:
        cursor.execute(query, (start_date.date(), end_date.date()))
        rows = cursor.fetchall()
    finally:
        cursor.close()
    
    if not rows:
        return {}
    
    result = {}
    for row in rows:
        if isinstance(row, dict):
            snapshot_date = row["SNAPSHOT_DATE"]
            score = float(row["LLM_SCORE"] or 0)
            item = {
                "code": row["STOCK_CODE"],
                "name": row["STOCK_NAME"],
                "llm_score": score,
                "estimated_score": score,  # 호환성을 위해 추가
                "factor_score": score,  # Candidate 클래스 호환성
                "is_tradable": row["IS_TRADABLE"],
                "llm_reason": row.get("LLM_REASON", ""),
            }
        else:
            snapshot_date, code, name, score, is_tradable, reason = row
            score = float(score or 0)
            item = {
                "code": code,
                "name": name,
                "llm_score": score,
                "estimated_score": score,  # 호환성을 위해 추가
                "factor_score": score,  # Candidate 클래스 호환성
                "is_tradable": is_tradable,
                "llm_reason": reason or "",
            }
        
        if snapshot_date not in result:
            result[snapshot_date] = []
        result[snapshot_date].append(item)
    
    logger.info(f"📋 Scout history 로드: {len(result)}일, 총 {len(rows)}건")
    return result


def load_llm_decisions(
    connection,
    start_date: datetime,
    end_date: datetime,
    stock_codes: Optional[List[str]] = None,
) -> Dict[Tuple[date, str], dict]:
    """
    llm_decision_ledger 테이블에서 LLM 결정 히스토리 로드
    
    Args:
        connection: DB 연결
        start_date: 시작일
        end_date: 종료일
        stock_codes: 조회할 종목 코드 (None이면 전체)
        
    Returns:
        {(date, stock_code): {"decision": "BUY", "hunter_score": 85.0, ...}}
    """
    if stock_codes:
        placeholders = ','.join(['%s'] * len(stock_codes))
        query = f"""
            SELECT DATE(CREATED_AT) as decision_date, STOCK_CODE, 
                   FINAL_DECISION, HUNTER_SCORE, MARKET_REGIME, FINAL_REASON
            FROM llm_decision_ledger
            WHERE DATE(CREATED_AT) BETWEEN %s AND %s
              AND STOCK_CODE IN ({placeholders})
            ORDER BY CREATED_AT DESC
        """
        params = (start_date.date(), end_date.date(), *stock_codes)
    else:
        query = """
            SELECT DATE(CREATED_AT) as decision_date, STOCK_CODE,
                   FINAL_DECISION, HUNTER_SCORE, MARKET_REGIME, FINAL_REASON
            FROM llm_decision_ledger
            WHERE DATE(CREATED_AT) BETWEEN %s AND %s
            ORDER BY CREATED_AT DESC
        """
        params = (start_date.date(), end_date.date())
    
    cursor = connection.cursor()
    try:
        cursor.execute(query, params)
        rows = cursor.fetchall()
    finally:
        cursor.close()
    
    if not rows:
        return {}
    
    result = {}
    for row in rows:
        if isinstance(row, dict):
            decision_date = row["decision_date"]
            code = row["STOCK_CODE"]
            item = {
                "decision": row["FINAL_DECISION"],
                "hunter_score": float(row["HUNTER_SCORE"] or 0),
                "regime": row["MARKET_REGIME"],
                "reason": row.get("FINAL_REASON", ""),
            }
        else:
            decision_date, code, decision, score, regime, reason = row
            item = {
                "decision": decision,
                "hunter_score": float(score or 0),
                "regime": regime,
                "reason": reason or "",
            }
        
        key = (decision_date, code)
        if key not in result:  # 가장 최신 결정만 저장
            result[key] = item
    
    logger.info(f"🤖 LLM decisions 로드: {len(result)}건")
    return result
