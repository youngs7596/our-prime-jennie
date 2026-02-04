#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shared/macro_data/clients/pykrx_client.py
-----------------------------------------
pykrx 기반 KRX 시장 데이터 클라이언트.

KOSPI/KOSDAQ 지수, 수급 데이터를 수집합니다.
Rate Limit: 없음 (pykrx 내부 처리)
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor

from ..models import MacroDataPoint, IndicatorCategory
from ..cache import get_macro_cache
from .base import MacroDataClient, ClientConfig

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")


# pykrx import를 함수 내에서 수행 (lazy import)
def _import_pykrx():
    try:
        from pykrx import stock
        return stock
    except ImportError:
        logger.error("pykrx not installed. Run: pip install pykrx")
        return None


class PyKRXClient(MacroDataClient):
    """
    pykrx 기반 KRX 시장 데이터 클라이언트.

    제공 데이터:
    - KOSPI 지수
    - KOSDAQ 지수
    - 지수 등락률
    - 투자자별 매매동향 (외국인, 기관)

    Usage:
        client = PyKRXClient()
        data = await client.fetch_data(["kospi_index", "kosdaq_index"])
    """

    SOURCE_NAME = "pykrx"

    # 지표 매핑
    INDICATOR_TICKERS = {
        "kospi_index": "1001",   # KOSPI
        "kosdaq_index": "2001",  # KOSDAQ
        "kospi200": "1028",      # KOSPI 200
        "kq150": "3003",         # KQ 150
    }

    def __init__(self, config: Optional[ClientConfig] = None):
        """
        클라이언트 초기화.

        Args:
            config: 클라이언트 설정
        """
        self.config = config or ClientConfig(
            timeout=30,
            max_retries=3,
            retry_delay=1.0
        )
        self._cache = get_macro_cache()
        self._executor = ThreadPoolExecutor(max_workers=2)
        self._stock = None  # lazy load

    @property
    def stock(self):
        """pykrx stock 모듈 (lazy load)"""
        if self._stock is None:
            self._stock = _import_pykrx()
        return self._stock

    async def close(self) -> None:
        """리소스 정리"""
        self._executor.shutdown(wait=False)

    def get_rate_limit(self) -> Tuple[int, int]:
        """Rate limit: (60/min, 100000/day) - pykrx 내부 처리"""
        return (60, 100000)

    def get_source_name(self) -> str:
        return self.SOURCE_NAME

    def get_default_indicators(self) -> List[str]:
        return [
            "kospi_index", 
            "kosdaq_index",
            "kospi_foreign_net",   # 투자자 순매수 (외국인/기관/개인)
            "kosdaq_foreign_net",
        ]

    def is_available(self) -> bool:
        """pykrx 사용 가능 여부"""
        return self.stock is not None

    def _get_trading_date(self) -> str:
        """
        최근 거래일 반환 (YYYYMMDD).

        주말이면 금요일로 조정.
        """
        now = datetime.now(KST)

        # 장 시작 전이면 전일
        if now.hour < 9:
            now = now - timedelta(days=1)

        # 주말 처리
        while now.weekday() >= 5:  # 토요일(5), 일요일(6)
            now = now - timedelta(days=1)

        return now.strftime("%Y%m%d")

    def _sync_fetch_index(
        self,
        ticker: str,
        start_date: str,
        end_date: str
    ) -> Optional[Dict[str, Any]]:
        """
        동기 방식으로 지수 데이터 조회.

        Args:
            ticker: 지수 티커
            start_date: 시작일 (YYYYMMDD)
            end_date: 종료일 (YYYYMMDD)

        Returns:
            지수 데이터 딕셔너리
        """
        if not self.stock:
            return None

        try:
            df = self.stock.get_index_ohlcv(start_date, end_date, ticker)

            if df.empty:
                return None

            # 최신 데이터 (마지막 행)
            latest = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else latest

            # 등락률 계산
            prev_close = float(prev["종가"]) if "종가" in prev else 0
            close = float(latest["종가"]) if "종가" in latest else 0
            change_pct = 0.0
            if prev_close > 0:
                change_pct = ((close - prev_close) / prev_close) * 100

            return {
                "close": close,
                "open": float(latest.get("시가", 0)),
                "high": float(latest.get("고가", 0)),
                "low": float(latest.get("저가", 0)),
                "volume": int(latest.get("거래량", 0)),
                "change_pct": round(change_pct, 2),
                "date": df.index[-1].strftime("%Y%m%d"),
            }

        except Exception as e:
            logger.error(f"[pykrx] Error fetching index {ticker}: {e}")
            return None

    def _sync_fetch_investor_trading(
        self,
        ticker: str,
        date: str
    ) -> Optional[Dict[str, Any]]:
        """
        동기 방식으로 투자자별 매매동향 조회.

        Args:
            ticker: 지수 티커
            date: 조회일 (YYYYMMDD)

        Returns:
            투자자별 순매수 데이터
        """
        if not self.stock:
            return None

        try:
            # pykrx 1.2.x: get_market_trading_value_by_investor 사용
            # 반환 형식: 인덱스=투자자유형, 컬럼=['매도', '매수', '순매수']
            df = self.stock.get_market_trading_value_by_investor(
                date, date, ticker
            )

            if df is None or df.empty:
                logger.warning(f"[pykrx] No investor trading data for {ticker} on {date}")
                return None

            # 순매수 금액 (억원 단위)
            result = {}

            # 순매수 컬럼에서 투자자별 데이터 추출
            if '순매수' in df.columns:
                investor_mapping = {
                    "금융투자": "금융투자",
                    "보험": "보험",
                    "투신": "투신",
                    "사모": "사모",
                    "은행": "은행",
                    "기타금융": "기타금융",
                    "연기금 등": "연기금등",
                    "연기금등": "연기금등",
                    "기관합계": "기관합계",
                    "기타법인": "기타법인",
                    "개인": "개인",
                    "외국인": "외국인",
                    "기타외국인": "기타외국인",
                }
                for idx_name in df.index:
                    result_key = investor_mapping.get(idx_name)
                    if result_key:
                        net = float(df.loc[idx_name, '순매수'])
                        result[result_key] = round(net / 100000000, 2)  # 억원

            return result if result else None

        except Exception as e:
            logger.error(f"[pykrx] Error fetching investor trading: {e}")
            return None

    async def fetch_index(
        self,
        indicator: str
    ) -> Optional[MacroDataPoint]:
        """
        지수 데이터 조회.

        Args:
            indicator: 지표 이름 (kospi_index, kosdaq_index 등)

        Returns:
            MacroDataPoint 또는 None
        """
        # 캐시 확인 (1시간 캐시)
        cached = self._cache.get_data_point(self.SOURCE_NAME, indicator)
        if cached and cached.is_valid(max_age_hours=1):
            return cached

        ticker = self.INDICATOR_TICKERS.get(indicator)
        if not ticker:
            logger.warning(f"[pykrx] Unknown indicator: {indicator}")
            return None

        # 최근 5일 데이터 조회 (휴장일 고려)
        end_date = self._get_trading_date()
        start_date = (
            datetime.strptime(end_date, "%Y%m%d") - timedelta(days=7)
        ).strftime("%Y%m%d")

        # 동기 함수를 비동기로 실행
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(
            self._executor,
            self._sync_fetch_index,
            ticker, start_date, end_date
        )

        if not data:
            return None

        timestamp = datetime.strptime(
            data["date"], "%Y%m%d"
        ).replace(hour=15, minute=30, tzinfo=KST)

        point = MacroDataPoint(
            indicator=indicator,
            value=data["close"],
            timestamp=timestamp,
            source=self.SOURCE_NAME,
            category=IndicatorCategory.KOREA_MARKET,
            unit="index",
            metadata={
                "open": data["open"],
                "high": data["high"],
                "low": data["low"],
                "volume": data["volume"],
                "change_pct": data["change_pct"],
            }
        )

        # 캐시 저장
        self._cache.set_data_point(self.SOURCE_NAME, indicator, point)

        # 등락률도 별도 저장
        change_indicator = f"{indicator.replace('_index', '')}_change_pct"
        change_point = MacroDataPoint(
            indicator=change_indicator,
            value=data["change_pct"],
            timestamp=timestamp,
            source=self.SOURCE_NAME,
            category=IndicatorCategory.KOREA_MARKET,
            unit="%",
        )
        self._cache.set_data_point(self.SOURCE_NAME, change_indicator, change_point)

        return point

    async def fetch_investor_trading(
        self,
        market: str = "kospi"
    ) -> Optional[MacroDataPoint]:
        """
        투자자별 매매동향 조회.

        Args:
            market: 시장 (kospi, kosdaq)

        Returns:
            MacroDataPoint (외국인 순매수)
        """
        indicator = f"{market.lower()}_foreign_net"

        # 캐시 확인 (미래 타임스탬프는 무효화)
        now = datetime.now(KST)
        cached = self._cache.get_data_point(self.SOURCE_NAME, indicator)
        if cached and cached.is_valid(max_age_hours=2) and cached.timestamp <= now:
            return cached

        # get_market_trading_value_by_investor는 "KOSPI", "KOSDAQ" 문자열 필요
        market_name = market.upper()
        if market_name not in ["KOSPI", "KOSDAQ"]:
            return None

        date = self._get_trading_date()

        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(
            self._executor,
            self._sync_fetch_investor_trading,
            market_name, date  # ticker 대신 market_name 전달
        )

        if not data:
            return None

        # 외국인 순매수 (억원)
        foreign_net = data.get("외국인", 0) + data.get("기타외국인", 0)

        # 타임스탬프: 장 마감 시간(15:30) 또는 현재 시간 중 더 이른 시간
        data_date = datetime.strptime(date, "%Y%m%d").replace(tzinfo=KST)
        market_close_time = data_date.replace(hour=15, minute=30)
        now = datetime.now(KST)
        timestamp = min(market_close_time, now)  # 미래 시간 방지

        point = MacroDataPoint(
            indicator=indicator,
            value=foreign_net,
            timestamp=timestamp,
            source=self.SOURCE_NAME,
            category=IndicatorCategory.KOREA_MARKET,
            unit="억원",
            metadata={
                "institutional": data.get("금융투자", 0) + data.get("투신", 0) + data.get("연기금등", 0),
                "retail": data.get("개인", 0),
                "all_investors": data,
            }
        )

        self._cache.set_data_point(self.SOURCE_NAME, indicator, point)

        return point

    async def fetch_data(
        self,
        indicators: Optional[List[str]] = None
    ) -> List[MacroDataPoint]:
        """
        지표 데이터 수집.

        Args:
            indicators: 수집할 지표 목록

        Returns:
            MacroDataPoint 리스트
        """
        if not self.is_available():
            logger.warning("[pykrx] Client not available (pykrx not installed)")
            return []

        indicators = indicators or self.get_default_indicators()
        results: List[MacroDataPoint] = []

        for indicator in indicators:
            try:
                if indicator in self.INDICATOR_TICKERS:
                    point = await self.fetch_index(indicator)
                elif indicator.endswith("_foreign_net"):
                    market = indicator.replace("_foreign_net", "")
                    point = await self.fetch_investor_trading(market)
                else:
                    logger.warning(f"[pykrx] Unknown indicator: {indicator}")
                    continue

                if point:
                    results.append(point)
                    logger.debug(f"[pykrx] Fetched {indicator}: {point.value}")

            except Exception as e:
                logger.error(f"[pykrx] Error fetching {indicator}: {e}")

        self._cache.set_last_fetch(self.SOURCE_NAME)
        logger.info(f"[pykrx] Fetched {len(results)} indicators")

        return results

    async def get_market_summary(self) -> Dict[str, Any]:
        """
        시장 요약 데이터 조회.

        Returns:
            KOSPI/KOSDAQ 요약 딕셔너리
        """
        results = await self.fetch_data([
            "kospi_index", "kosdaq_index",
        ])

        # 투자자 동향도 추가
        kospi_investor = await self.fetch_investor_trading("kospi")
        kosdaq_investor = await self.fetch_investor_trading("kosdaq")

        if kospi_investor:
            results.append(kospi_investor)
        if kosdaq_investor:
            results.append(kosdaq_investor)

        summary = {}
        for point in results:
            summary[point.indicator] = {
                "value": point.value,
                "unit": point.unit,
                "metadata": point.metadata,
            }

        return summary
