#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shared/macro_data/clients/bok_ecos_client.py
--------------------------------------------
한국은행 ECOS API 클라이언트.

한국 경제 지표를 수집합니다.
- 기준금리, 콜금리
- 원/달러 환율
- GDP, 물가지수
- 통화량

Rate Limit: 제한 없음 (무료)
API 문서: https://ecos.bok.or.kr/api
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

import aiohttp

from ..models import MacroDataPoint, IndicatorCategory
from ..rate_limiter import get_rate_limiter
from ..cache import get_macro_cache
from .base import MacroDataClient, ClientConfig

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
UTC = ZoneInfo("UTC")


def _load_bok_api_key() -> Optional[str]:
    """secrets.json에서 BOK ECOS API 키 로드"""
    possible_paths = [
        Path("/opt/airflow/secrets.json"),  # Airflow 컨테이너
        Path("/home/youngs75/projects/my-prime-jennie/secrets.json"),  # 로컬
        Path("secrets.json"),
        Path("config/secrets.json"),
    ]

    for path in possible_paths:
        if path.exists():
            try:
                with open(path, "r") as f:
                    secrets = json.load(f)
                    return secrets.get("bok_ecos_api_key")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"[BOK ECOS] Failed to read {path}: {e}")

    return None


class BOKECOSClient(MacroDataClient):
    """
    한국은행 ECOS API 클라이언트.

    제공 데이터:
    - 기준금리 (722Y001)
    - 콜금리 (817Y002)
    - 원/달러 환율 (731Y001)
    - 소비자물가지수 (901Y009)
    - GDP (200Y001)

    Usage:
        client = BOKECOSClient()
        data = await client.fetch_data(["bok_rate", "korea_cpi_yoy"])
    """

    BASE_URL = "https://ecos.bok.or.kr/api/StatisticSearch"
    SOURCE_NAME = "bok_ecos"

    # 지표 -> ECOS 통계코드 매핑
    # (통계표코드, 항목코드1, 항목코드2, 주기)
    INDICATOR_CODES = {
        "bok_rate": {
            "stat_code": "722Y001",
            "item_code1": "0101000",
            "item_code2": None,
            "cycle": "M",  # Monthly
            "name": "한국은행 기준금리",
        },
        "bok_call_rate": {
            "stat_code": "817Y002",
            "item_code1": "010100000",
            "item_code2": None,
            "cycle": "D",  # Daily
            "name": "콜금리(1일물)",
        },
        "usd_krw_bok": {  # BOK 환율 (원화 기준)
            "stat_code": "731Y001",
            "item_code1": "0000001",  # 미 달러
            "item_code2": None,
            "cycle": "D",
            "name": "원/달러 환율",
        },
        "korea_cpi": {
            "stat_code": "901Y009",
            "item_code1": "0",  # 총지수
            "item_code2": None,
            "cycle": "M",
            "name": "소비자물가지수",
        },
        "korea_gdp": {
            "stat_code": "200Y001",
            "item_code1": "10101",  # GDP
            "item_code2": None,
            "cycle": "Q",  # Quarterly
            "name": "국내총생산(GDP)",
        },
        "korea_m2": {  # 광의통화
            "stat_code": "101Y003",
            "item_code1": "BBHS00",
            "item_code2": None,
            "cycle": "M",
            "name": "M2(광의통화)",
        },
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        config: Optional[ClientConfig] = None
    ):
        """
        클라이언트 초기화.

        Args:
            api_key: ECOS API 키 (없으면 secrets.json 또는 환경변수에서)
            config: 클라이언트 설정
        """
        # API 키 로드 우선순위: 인자 > 환경변수 > secrets.json
        self.api_key = (
            api_key
            or os.getenv("BOK_ECOS_API_KEY")
            or _load_bok_api_key()
            or ""
        )
        self.config = config or ClientConfig(
            timeout=30,
            max_retries=3,
            retry_delay=1.0
        )
        self._session: Optional[aiohttp.ClientSession] = None
        self._rate_limiter = get_rate_limiter()
        self._cache = get_macro_cache()

        if self.api_key:
            logger.info(f"[BOK ECOS] API key loaded ({self.api_key[:8]}...)")
        else:
            logger.warning("[BOK ECOS] API key not found")

    async def _get_session(self) -> aiohttp.ClientSession:
        """aiohttp 세션 반환"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.config.timeout)
            )
        return self._session

    async def close(self) -> None:
        """세션 종료"""
        if self._session and not self._session.closed:
            await self._session.close()

    def get_rate_limit(self) -> Tuple[int, int]:
        """Rate limit: (30/min conservative, 50000/day)"""
        return (30, 50000)

    def get_source_name(self) -> str:
        return self.SOURCE_NAME

    def get_default_indicators(self) -> List[str]:
        return ["bok_rate", "usd_krw_bok", "korea_cpi"]

    def is_available(self) -> bool:
        """API 키 유효성 확인"""
        return bool(self.api_key)

    def _get_date_range(self, cycle: str) -> Tuple[str, str]:
        """
        주기에 따른 조회 기간 반환.

        Args:
            cycle: D(일), M(월), Q(분기)

        Returns:
            (시작일, 종료일) YYYYMMDD 형식
        """
        now = datetime.now(KST)
        end_date = now.strftime("%Y%m%d")

        if cycle == "D":
            start_date = (now - timedelta(days=30)).strftime("%Y%m%d")
        elif cycle == "M":
            start_date = (now - timedelta(days=400)).strftime("%Y%m%d")
        elif cycle == "Q":
            start_date = (now - timedelta(days=800)).strftime("%Y%m%d")
        else:
            start_date = (now - timedelta(days=365)).strftime("%Y%m%d")

        return start_date, end_date

    async def _request(
        self,
        stat_code: str,
        item_code1: str,
        item_code2: Optional[str],
        cycle: str,
        start_date: str,
        end_date: str
    ) -> Optional[List[Dict[str, Any]]]:
        """
        ECOS API 요청.

        Returns:
            데이터 행 리스트 또는 None
        """
        if not self.is_available():
            logger.warning("[BOK_ECOS] API key not configured")
            return None

        session = await self._get_session()

        # URL 구성
        # /StatisticSearch/{api_key}/{format}/{lang}/{start}/{end}/{code}/{cycle}/{start_date}/{end_date}/{item1}/{item2}
        item2 = item_code2 or "?"
        url = (
            f"{self.BASE_URL}/{self.api_key}/json/kr/"
            f"1/100/{stat_code}/{cycle}/{start_date}/{end_date}/"
            f"{item_code1}/{item2}"
        )

        for attempt in range(self.config.max_retries):
            try:
                async with self._rate_limiter.acquire(self.SOURCE_NAME):
                    async with session.get(url) as response:
                        if response.status == 200:
                            data = await response.json()

                            # ECOS 응답 구조 확인
                            if "StatisticSearch" in data:
                                stats = data["StatisticSearch"]
                                if "row" in stats:
                                    return stats["row"]
                                else:
                                    logger.debug(
                                        f"[BOK_ECOS] No data: {stats.get('RESULT', {})}"
                                    )
                            return None

                        elif response.status == 500:
                            logger.warning("[BOK_ECOS] Server error, retrying")
                        else:
                            text = await response.text()
                            logger.warning(
                                f"[BOK_ECOS] Request failed: {response.status}, {text[:200]}"
                            )

            except asyncio.TimeoutError:
                logger.warning(f"[BOK_ECOS] Timeout (attempt {attempt + 1})")
            except aiohttp.ClientError as e:
                logger.warning(f"[BOK_ECOS] Request error: {e}")

            if attempt < self.config.max_retries - 1:
                await asyncio.sleep(self.config.retry_delay * (attempt + 1))

        return None

    async def fetch_indicator(
        self,
        indicator: str
    ) -> Optional[MacroDataPoint]:
        """
        단일 지표 조회.

        Args:
            indicator: 지표 이름

        Returns:
            MacroDataPoint 또는 None
        """
        # 캐시 확인 (BOK 데이터는 천천히 업데이트되므로 2시간 캐시)
        cached = self._cache.get_data_point(self.SOURCE_NAME, indicator)
        if cached and cached.is_valid(max_age_hours=2):
            return cached

        indicator_info = self.INDICATOR_CODES.get(indicator)
        if not indicator_info:
            logger.warning(f"[BOK_ECOS] Unknown indicator: {indicator}")
            return None

        cycle = indicator_info["cycle"]
        start_date, end_date = self._get_date_range(cycle)

        rows = await self._request(
            stat_code=indicator_info["stat_code"],
            item_code1=indicator_info["item_code1"],
            item_code2=indicator_info.get("item_code2"),
            cycle=cycle,
            start_date=start_date,
            end_date=end_date,
        )

        if not rows:
            logger.warning(f"[BOK_ECOS] No data for {indicator}")
            return None

        # 최신 데이터 찾기 (시간 역순 정렬)
        rows.sort(key=lambda x: x.get("TIME", ""), reverse=True)

        value = None
        timestamp = None

        for row in rows:
            try:
                data_value = row.get("DATA_VALUE")
                if data_value and data_value != "-":
                    value = float(data_value)
                    time_str = row.get("TIME", "")

                    # 시간 파싱 (YYYYMM, YYYYMMDD, YYYYQ 등)
                    if len(time_str) == 6:  # YYYYMM
                        timestamp = datetime.strptime(
                            time_str + "01", "%Y%m%d"
                        ).replace(tzinfo=KST)
                    elif len(time_str) == 8:  # YYYYMMDD
                        timestamp = datetime.strptime(
                            time_str, "%Y%m%d"
                        ).replace(tzinfo=KST)
                    elif len(time_str) == 5 and "Q" in time_str:  # YYYYQ
                        year = int(time_str[:4])
                        quarter = int(time_str[4])
                        month = (quarter - 1) * 3 + 1
                        timestamp = datetime(year, month, 1, tzinfo=KST)
                    else:
                        timestamp = datetime.now(KST)

                    break

            except (ValueError, KeyError) as e:
                logger.debug(f"[BOK_ECOS] Parse error: {e}")
                continue

        if value is None:
            return None

        # CPI의 경우 YoY 변화율 계산
        if indicator == "korea_cpi" and len(rows) >= 13:
            # 12개월 전 데이터 찾기
            prev_value = None
            for row in rows:
                try:
                    time_str = row.get("TIME", "")
                    if len(time_str) == 6:
                        row_date = datetime.strptime(time_str + "01", "%Y%m%d")
                        target_date = timestamp.replace(tzinfo=None) - timedelta(days=365)
                        if abs((row_date - target_date).days) < 45:
                            prev_value = float(row.get("DATA_VALUE", 0))
                            break
                except (ValueError, KeyError):
                    continue

            if prev_value and prev_value > 0:
                value = ((value - prev_value) / prev_value) * 100
                indicator = "korea_cpi_yoy"

        point = MacroDataPoint(
            indicator=indicator,
            value=value,
            timestamp=timestamp,
            source=self.SOURCE_NAME,
            category=self._get_category(indicator),
            unit=self._get_unit(indicator),
            metadata={
                "stat_code": indicator_info["stat_code"],
                "name_kr": indicator_info["name"],
            }
        )

        # 캐시 저장
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
            logger.warning("[BOK_ECOS] Client not available (no API key)")
            return []

        indicators = indicators or self.get_default_indicators()
        results: List[MacroDataPoint] = []

        for indicator in indicators:
            try:
                point = await self.fetch_indicator(indicator)
                if point:
                    results.append(point)
                    logger.debug(f"[BOK_ECOS] Fetched {indicator}: {point.value}")

            except Exception as e:
                logger.error(f"[BOK_ECOS] Error fetching {indicator}: {e}")

        self._cache.set_last_fetch(self.SOURCE_NAME)
        logger.info(f"[BOK_ECOS] Fetched {len(results)} indicators")

        return results

    def _get_category(self, indicator: str) -> IndicatorCategory:
        """지표 카테고리 반환"""
        if indicator in ["bok_rate", "bok_call_rate"]:
            return IndicatorCategory.KOREA_RATES
        elif indicator in ["usd_krw_bok"]:
            return IndicatorCategory.CURRENCY
        elif indicator in ["korea_cpi", "korea_cpi_yoy", "korea_gdp"]:
            return IndicatorCategory.KOREA_ECONOMY
        else:
            return IndicatorCategory.KOREA_ECONOMY

    def _get_unit(self, indicator: str) -> str:
        """지표 단위 반환"""
        if indicator in ["bok_rate", "bok_call_rate", "korea_cpi_yoy"]:
            return "%"
        elif indicator in ["usd_krw_bok"]:
            return "KRW/USD"
        elif indicator in ["korea_cpi"]:
            return "index"
        elif indicator in ["korea_gdp"]:
            return "billions KRW"
        elif indicator in ["korea_m2"]:
            return "billions KRW"
        else:
            return ""
