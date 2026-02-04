#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shared/macro_data/storage.py
----------------------------
DB 저장 모듈.

GlobalMacroSnapshot을 ENHANCED_MACRO_SNAPSHOT 테이블에 저장합니다.
"""

import json
import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import shared.database as database
from .models import GlobalMacroSnapshot

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")


# ==============================================================================
# DB Schema (참고용 - 실제 생성은 별도 마이그레이션)
# ==============================================================================
"""
CREATE TABLE ENHANCED_MACRO_SNAPSHOT (
    ID INT AUTO_INCREMENT PRIMARY KEY,
    SNAPSHOT_DATE DATE NOT NULL,
    SNAPSHOT_TIME DATETIME NOT NULL,

    -- US Indicators
    FED_RATE DECIMAL(5,2),
    US_CPI_YOY DECIMAL(5,2),
    US_PCE_YOY DECIMAL(5,2),
    TREASURY_2Y DECIMAL(5,3),
    TREASURY_10Y DECIMAL(5,3),
    TREASURY_SPREAD DECIMAL(5,3),
    US_UNEMPLOYMENT DECIMAL(5,2),
    US_PMI DECIMAL(5,2),

    -- Volatility
    VIX DECIMAL(6,2),
    VIX_REGIME VARCHAR(20),

    -- Currency
    DXY_INDEX DECIMAL(6,2),
    USD_KRW DECIMAL(8,2),
    USD_JPY DECIMAL(8,4),
    USD_CNY DECIMAL(8,4),

    -- Korea
    BOK_RATE DECIMAL(5,2),
    KOREA_CPI_YOY DECIMAL(5,2),
    KOSPI_INDEX DECIMAL(8,2),
    KOSDAQ_INDEX DECIMAL(8,2),
    KOSPI_CHANGE_PCT DECIMAL(6,2),
    KOSDAQ_CHANGE_PCT DECIMAL(6,2),

    -- Calculated
    RATE_DIFFERENTIAL DECIMAL(5,2),

    -- Sentiment
    GLOBAL_NEWS_SENTIMENT DECIMAL(4,3),
    KOREA_NEWS_SENTIMENT DECIMAL(4,3),

    -- Metadata
    DATA_SOURCES JSON,
    MISSING_INDICATORS JSON,
    STALE_INDICATORS JSON,
    VALIDATION_ERRORS JSON,
    DATA_FRESHNESS DECIMAL(3,2),
    COMPLETENESS_SCORE DECIMAL(3,2),

    CREATED_AT DATETIME DEFAULT CURRENT_TIMESTAMP,
    UPDATED_AT DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY UK_SNAPSHOT_DATE (SNAPSHOT_DATE),
    INDEX IDX_SNAPSHOT_TIME (SNAPSHOT_TIME)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""


def save_snapshot_to_db(
    snapshot: GlobalMacroSnapshot,
    conn=None
) -> bool:
    """
    GlobalMacroSnapshot을 DB에 저장 (UPSERT).

    Args:
        snapshot: 저장할 스냅샷
        conn: DB 커넥션 (없으면 새로 생성)

    Returns:
        저장 성공 여부
    """
    close_conn = False
    if conn is None:
        conn = database.get_db_connection()
        close_conn = True

    try:
        sql = """
        INSERT INTO ENHANCED_MACRO_SNAPSHOT (
            SNAPSHOT_DATE, SNAPSHOT_TIME,
            FED_RATE, US_CPI_YOY, US_PCE_YOY,
            TREASURY_2Y, TREASURY_10Y, TREASURY_SPREAD,
            US_UNEMPLOYMENT, US_PMI,
            VIX, VIX_REGIME,
            DXY_INDEX, USD_KRW, USD_JPY, USD_CNY,
            BOK_RATE, KOREA_CPI_YOY,
            KOSPI_INDEX, KOSDAQ_INDEX,
            KOSPI_CHANGE_PCT, KOSDAQ_CHANGE_PCT,
            KOSPI_FOREIGN_NET, KOSDAQ_FOREIGN_NET,
            KOSPI_INSTITUTIONAL_NET, KOSPI_RETAIL_NET,
            RATE_DIFFERENTIAL,
            GLOBAL_NEWS_SENTIMENT, KOREA_NEWS_SENTIMENT,
            DATA_SOURCES, MISSING_INDICATORS, STALE_INDICATORS,
            VALIDATION_ERRORS, DATA_FRESHNESS, COMPLETENESS_SCORE
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s
        ) ON DUPLICATE KEY UPDATE
            SNAPSHOT_TIME = VALUES(SNAPSHOT_TIME),
            FED_RATE = VALUES(FED_RATE),
            US_CPI_YOY = VALUES(US_CPI_YOY),
            US_PCE_YOY = VALUES(US_PCE_YOY),
            TREASURY_2Y = VALUES(TREASURY_2Y),
            TREASURY_10Y = VALUES(TREASURY_10Y),
            TREASURY_SPREAD = VALUES(TREASURY_SPREAD),
            US_UNEMPLOYMENT = VALUES(US_UNEMPLOYMENT),
            US_PMI = VALUES(US_PMI),
            VIX = VALUES(VIX),
            VIX_REGIME = VALUES(VIX_REGIME),
            DXY_INDEX = VALUES(DXY_INDEX),
            USD_KRW = VALUES(USD_KRW),
            USD_JPY = VALUES(USD_JPY),
            USD_CNY = VALUES(USD_CNY),
            BOK_RATE = VALUES(BOK_RATE),
            KOREA_CPI_YOY = VALUES(KOREA_CPI_YOY),
            KOSPI_INDEX = VALUES(KOSPI_INDEX),
            KOSDAQ_INDEX = VALUES(KOSDAQ_INDEX),
            KOSPI_CHANGE_PCT = VALUES(KOSPI_CHANGE_PCT),
            KOSDAQ_CHANGE_PCT = VALUES(KOSDAQ_CHANGE_PCT),
            KOSPI_FOREIGN_NET = VALUES(KOSPI_FOREIGN_NET),
            KOSDAQ_FOREIGN_NET = VALUES(KOSDAQ_FOREIGN_NET),
            KOSPI_INSTITUTIONAL_NET = VALUES(KOSPI_INSTITUTIONAL_NET),
            KOSPI_RETAIL_NET = VALUES(KOSPI_RETAIL_NET),
            RATE_DIFFERENTIAL = VALUES(RATE_DIFFERENTIAL),
            GLOBAL_NEWS_SENTIMENT = VALUES(GLOBAL_NEWS_SENTIMENT),
            KOREA_NEWS_SENTIMENT = VALUES(KOREA_NEWS_SENTIMENT),
            DATA_SOURCES = VALUES(DATA_SOURCES),
            MISSING_INDICATORS = VALUES(MISSING_INDICATORS),
            STALE_INDICATORS = VALUES(STALE_INDICATORS),
            VALIDATION_ERRORS = VALUES(VALIDATION_ERRORS),
            DATA_FRESHNESS = VALUES(DATA_FRESHNESS),
            COMPLETENESS_SCORE = VALUES(COMPLETENESS_SCORE),
            UPDATED_AT = CURRENT_TIMESTAMP
        """

        params = (
            snapshot.snapshot_date,
            snapshot.snapshot_time,
            snapshot.fed_rate,
            snapshot.us_cpi_yoy,
            snapshot.us_pce_yoy,
            snapshot.treasury_2y,
            snapshot.treasury_10y,
            snapshot.treasury_spread,
            snapshot.us_unemployment,
            snapshot.us_pmi,
            snapshot.vix,
            snapshot.vix_regime,
            snapshot.dxy_index,
            snapshot.usd_krw,
            snapshot.usd_jpy,
            snapshot.usd_cny,
            snapshot.bok_rate,
            snapshot.korea_cpi_yoy,
            snapshot.kospi_index,
            snapshot.kosdaq_index,
            snapshot.kospi_change_pct,
            snapshot.kosdaq_change_pct,
            snapshot.kospi_foreign_net,
            snapshot.kosdaq_foreign_net,
            snapshot.kospi_institutional_net,
            snapshot.kospi_retail_net,
            snapshot.rate_differential,
            snapshot.global_news_sentiment,
            snapshot.korea_news_sentiment,
            json.dumps(snapshot.data_sources, ensure_ascii=False),
            json.dumps(snapshot.missing_indicators, ensure_ascii=False),
            json.dumps(snapshot.stale_indicators, ensure_ascii=False),
            json.dumps(snapshot.validation_errors, ensure_ascii=False),
            snapshot.data_freshness,
            snapshot.get_completeness_score(),
        )

        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            conn.commit()

        logger.info(f"[Storage] Snapshot saved: {snapshot.snapshot_date}")
        return True

    except Exception as e:
        logger.error(f"[Storage] Save snapshot failed: {e}", exc_info=True)
        return False
    finally:
        if close_conn:
            conn.close()


def load_snapshot_from_db(
    target_date: date,
    conn=None
) -> Optional[GlobalMacroSnapshot]:
    """
    특정 날짜의 스냅샷 조회.

    Args:
        target_date: 조회할 날짜
        conn: DB 커넥션

    Returns:
        GlobalMacroSnapshot 또는 None
    """
    close_conn = False
    if conn is None:
        conn = database.get_db_connection()
        close_conn = True

    try:
        sql = """
        SELECT
            SNAPSHOT_DATE, SNAPSHOT_TIME,
            FED_RATE, US_CPI_YOY, US_PCE_YOY,
            TREASURY_2Y, TREASURY_10Y, TREASURY_SPREAD,
            US_UNEMPLOYMENT, US_PMI,
            VIX, VIX_REGIME,
            DXY_INDEX, USD_KRW, USD_JPY, USD_CNY,
            BOK_RATE, KOREA_CPI_YOY,
            KOSPI_INDEX, KOSDAQ_INDEX,
            KOSPI_CHANGE_PCT, KOSDAQ_CHANGE_PCT,
            KOSPI_FOREIGN_NET, KOSDAQ_FOREIGN_NET,
            KOSPI_INSTITUTIONAL_NET, KOSPI_RETAIL_NET,
            RATE_DIFFERENTIAL,
            GLOBAL_NEWS_SENTIMENT, KOREA_NEWS_SENTIMENT,
            DATA_SOURCES, MISSING_INDICATORS, STALE_INDICATORS,
            VALIDATION_ERRORS, DATA_FRESHNESS
        FROM ENHANCED_MACRO_SNAPSHOT
        WHERE SNAPSHOT_DATE = %s
        """

        with conn.cursor() as cursor:
            cursor.execute(sql, (target_date,))
            row = cursor.fetchone()

        if not row:
            return None

        return GlobalMacroSnapshot(
            snapshot_date=row[0],
            snapshot_time=row[1].replace(tzinfo=KST) if row[1] else datetime.now(KST),
            fed_rate=float(row[2]) if row[2] is not None else None,
            us_cpi_yoy=float(row[3]) if row[3] is not None else None,
            us_pce_yoy=float(row[4]) if row[4] is not None else None,
            treasury_2y=float(row[5]) if row[5] is not None else None,
            treasury_10y=float(row[6]) if row[6] is not None else None,
            treasury_spread=float(row[7]) if row[7] is not None else None,
            us_unemployment=float(row[8]) if row[8] is not None else None,
            us_pmi=float(row[9]) if row[9] is not None else None,
            vix=float(row[10]) if row[10] is not None else None,
            vix_regime=row[11] or "normal",
            dxy_index=float(row[12]) if row[12] is not None else None,
            usd_krw=float(row[13]) if row[13] is not None else None,
            usd_jpy=float(row[14]) if row[14] is not None else None,
            usd_cny=float(row[15]) if row[15] is not None else None,
            bok_rate=float(row[16]) if row[16] is not None else None,
            korea_cpi_yoy=float(row[17]) if row[17] is not None else None,
            kospi_index=float(row[18]) if row[18] is not None else None,
            kosdaq_index=float(row[19]) if row[19] is not None else None,
            kospi_change_pct=float(row[20]) if row[20] is not None else None,
            kosdaq_change_pct=float(row[21]) if row[21] is not None else None,
            kospi_foreign_net=float(row[22]) if row[22] is not None else None,
            kosdaq_foreign_net=float(row[23]) if row[23] is not None else None,
            kospi_institutional_net=float(row[24]) if row[24] is not None else None,
            kospi_retail_net=float(row[25]) if row[25] is not None else None,
            rate_differential=float(row[26]) if row[26] is not None else None,
            global_news_sentiment=float(row[27]) if row[27] is not None else None,
            korea_news_sentiment=float(row[28]) if row[28] is not None else None,
            data_sources=json.loads(row[29]) if row[29] else [],
            missing_indicators=json.loads(row[30]) if row[30] else [],
            stale_indicators=json.loads(row[31]) if row[31] else [],
            validation_errors=json.loads(row[32]) if row[32] else [],
            data_freshness=float(row[33]) if row[33] is not None else 0.0,
        )

    except Exception as e:
        logger.error(f"[Storage] Load snapshot failed: {e}", exc_info=True)
        return None
    finally:
        if close_conn:
            conn.close()


def load_recent_snapshots(
    days: int = 7,
    conn=None
) -> List[GlobalMacroSnapshot]:
    """
    최근 N일간의 스냅샷 조회.

    Args:
        days: 조회 기간 (일)
        conn: DB 커넥션

    Returns:
        GlobalMacroSnapshot 리스트 (최신순)
    """
    close_conn = False
    if conn is None:
        conn = database.get_db_connection()
        close_conn = True

    try:
        sql = """
        SELECT
            SNAPSHOT_DATE, SNAPSHOT_TIME,
            FED_RATE, US_CPI_YOY, US_PCE_YOY,
            TREASURY_2Y, TREASURY_10Y, TREASURY_SPREAD,
            US_UNEMPLOYMENT, US_PMI,
            VIX, VIX_REGIME,
            DXY_INDEX, USD_KRW, USD_JPY, USD_CNY,
            BOK_RATE, KOREA_CPI_YOY,
            KOSPI_INDEX, KOSDAQ_INDEX,
            KOSPI_CHANGE_PCT, KOSDAQ_CHANGE_PCT,
            KOSPI_FOREIGN_NET, KOSDAQ_FOREIGN_NET,
            KOSPI_INSTITUTIONAL_NET, KOSPI_RETAIL_NET,
            RATE_DIFFERENTIAL,
            GLOBAL_NEWS_SENTIMENT, KOREA_NEWS_SENTIMENT,
            DATA_SOURCES, MISSING_INDICATORS, STALE_INDICATORS,
            VALIDATION_ERRORS, DATA_FRESHNESS
        FROM ENHANCED_MACRO_SNAPSHOT
        WHERE SNAPSHOT_DATE >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
        ORDER BY SNAPSHOT_DATE DESC
        """

        with conn.cursor() as cursor:
            cursor.execute(sql, (days,))
            rows = cursor.fetchall()

        snapshots = []
        for row in rows:
            try:
                snapshots.append(GlobalMacroSnapshot(
                    snapshot_date=row[0],
                    snapshot_time=row[1].replace(tzinfo=KST) if row[1] else datetime.now(KST),
                    fed_rate=float(row[2]) if row[2] is not None else None,
                    us_cpi_yoy=float(row[3]) if row[3] is not None else None,
                    us_pce_yoy=float(row[4]) if row[4] is not None else None,
                    treasury_2y=float(row[5]) if row[5] is not None else None,
                    treasury_10y=float(row[6]) if row[6] is not None else None,
                    treasury_spread=float(row[7]) if row[7] is not None else None,
                    us_unemployment=float(row[8]) if row[8] is not None else None,
                    us_pmi=float(row[9]) if row[9] is not None else None,
                    vix=float(row[10]) if row[10] is not None else None,
                    vix_regime=row[11] or "normal",
                    dxy_index=float(row[12]) if row[12] is not None else None,
                    usd_krw=float(row[13]) if row[13] is not None else None,
                    usd_jpy=float(row[14]) if row[14] is not None else None,
                    usd_cny=float(row[15]) if row[15] is not None else None,
                    bok_rate=float(row[16]) if row[16] is not None else None,
                    korea_cpi_yoy=float(row[17]) if row[17] is not None else None,
                    kospi_index=float(row[18]) if row[18] is not None else None,
                    kosdaq_index=float(row[19]) if row[19] is not None else None,
                    kospi_change_pct=float(row[20]) if row[20] is not None else None,
                    kosdaq_change_pct=float(row[21]) if row[21] is not None else None,
                    kospi_foreign_net=float(row[22]) if row[22] is not None else None,
                    kosdaq_foreign_net=float(row[23]) if row[23] is not None else None,
                    kospi_institutional_net=float(row[24]) if row[24] is not None else None,
                    kospi_retail_net=float(row[25]) if row[25] is not None else None,
                    rate_differential=float(row[26]) if row[26] is not None else None,
                    global_news_sentiment=float(row[27]) if row[27] is not None else None,
                    korea_news_sentiment=float(row[28]) if row[28] is not None else None,
                    data_sources=json.loads(row[29]) if row[29] else [],
                    missing_indicators=json.loads(row[30]) if row[30] else [],
                    stale_indicators=json.loads(row[31]) if row[31] else [],
                    validation_errors=json.loads(row[32]) if row[32] else [],
                    data_freshness=float(row[33]) if row[33] is not None else 0.0,
                ))
            except Exception as e:
                logger.warning(f"[Storage] Failed to parse snapshot row: {e}")
                continue

        return snapshots

    except Exception as e:
        logger.error(f"[Storage] Load recent snapshots failed: {e}", exc_info=True)
        return []
    finally:
        if close_conn:
            conn.close()


def get_today_snapshot(conn=None) -> Optional[GlobalMacroSnapshot]:
    """
    오늘의 스냅샷 조회.

    Returns:
        GlobalMacroSnapshot 또는 None
    """
    today = datetime.now(KST).date()
    return load_snapshot_from_db(today, conn)


def get_snapshot_trends(
    days: int = 30,
    conn=None
) -> Dict[str, List[Dict[str, Any]]]:
    """
    지표별 추세 데이터 조회.

    Args:
        days: 조회 기간 (일)
        conn: DB 커넥션

    Returns:
        지표별 시계열 데이터
    """
    snapshots = load_recent_snapshots(days, conn)

    if not snapshots:
        return {}

    # 지표별로 시계열 데이터 구성
    indicators = [
        "fed_rate", "bok_rate", "rate_differential",
        "vix", "dxy_index", "usd_krw",
        "kospi_index", "kosdaq_index",
        "korea_news_sentiment",
    ]

    trends: Dict[str, List[Dict[str, Any]]] = {ind: [] for ind in indicators}

    for snapshot in reversed(snapshots):  # 오래된 순으로
        for indicator in indicators:
            value = getattr(snapshot, indicator, None)
            if value is not None:
                trends[indicator].append({
                    "date": snapshot.snapshot_date.isoformat(),
                    "value": value,
                })

    return trends
