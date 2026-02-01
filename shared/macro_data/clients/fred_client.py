#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shared/macro_data/clients/fred_client.py
----------------------------------------
FRED (Federal Reserve Economic Data) API 클라이언트.

미국 경제 지표를 수집합니다.
- 금리: Federal Funds Rate, Treasury Yields
- 물가: CPI, PCE
- 고용: Unemployment Rate
- 경기: PMI, GDP

Rate Limit: 120 calls/minute (with API key)
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import aiohttp

from ..models import MacroDataPoint, IndicatorCategory
from ..rate_limiter import get_rate_limiter
from ..cache import get_macro_cache
from .base import MacroDataClient, ClientConfig

logger = logging.getLogger(__name__)

UTC = ZoneInfo("UTC")


def _load_fred_api_key() -> Optional[str]:
    """secrets.json에서 FRED API 키 로드"""
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
                    return secrets.get("fred_api_key")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"[FRED] Failed to read {path}: {e}")

    return None


class FREDClient(MacroDataClient):
    """
    FRED API 클라이언트.

    제공 데이터:
    - Federal Funds Rate (DFF)
    - 10Y Treasury Yield (DGS10)
    - 2Y Treasury Yield (DGS2)
    - CPI YoY (CPIAUCSL)
    - PCE YoY (PCEPI)
    - Unemployment Rate (UNRATE)

    Usage:
        client = FREDClient()
        data = await client.fetch_data(["fed_rate", "treasury_10y"])
    """

    BASE_URL = "https://api.stlouisfed.org/fred"
    SOURCE_NAME = "fred"

    # 지표 -> FRED series ID 매핑
    INDICATOR_SERIES = {
        # 금리
        "fed_rate": "DFF",           # Federal Funds Effective Rate
        "treasury_10y": "DGS10",     # 10-Year Treasury Constant Maturity Rate
        "treasury_2y": "DGS2",       # 2-Year Treasury Constant Maturity Rate
        "treasury_30y": "DGS30",     # 30-Year Treasury
        "treasury_3m": "DTB3",       # 3-Month Treasury Bill

        # 물가
        "us_cpi_yoy": "CPIAUCSL",    # Consumer Price Index
        "us_pce_yoy": "PCEPI",       # Personal Consumption Expenditures Price Index
        "us_core_cpi": "CPILFESL",   # Core CPI (Less Food & Energy)

        # 고용
        "us_unemployment": "UNRATE", # Unemployment Rate
        "us_nonfarm": "PAYEMS",      # Nonfarm Payrolls
        "us_claims": "ICSA",         # Initial Jobless Claims

        # 경기
        "us_pmi": "MANEMP",          # Manufacturing Employment (proxy)
        "us_gdp": "GDP",             # Real GDP
        "us_retail": "RSXFS",        # Retail Sales
    }

    # 지표별 변환 함수 (YoY 계산 필요 여부 등)
    INDICATOR_TRANSFORM = {
        "us_cpi_yoy": "pct_change_12",    # 12개월 전 대비 변화율
        "us_pce_yoy": "pct_change_12",
        "us_core_cpi": "pct_change_12",
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        config: Optional[ClientConfig] = None
    ):
        """
        클라이언트 초기화.

        Args:
            api_key: FRED API 키 (없으면 secrets.json 또는 환경변수에서)
            config: 클라이언트 설정
        """
        # API 키 로드 우선순위: 인자 > 환경변수 > secrets.json
        self.api_key = (
            api_key
            or os.getenv("FRED_API_KEY")
            or _load_fred_api_key()
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
            logger.info(f"[FRED] API key loaded ({self.api_key[:8]}...)")
        else:
            logger.warning("[FRED] API key not found")

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
        """Rate limit: (120/min, 100000/day)"""
        return (120, 100000)

    def get_source_name(self) -> str:
        return self.SOURCE_NAME

    def get_default_indicators(self) -> List[str]:
        return [
            "fed_rate", "treasury_10y", "treasury_2y",
            "us_cpi_yoy", "us_unemployment"
        ]

    def is_available(self) -> bool:
        """API 키 유효성 확인"""
        return bool(self.api_key)

    async def _request(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        API 요청 실행.

        Args:
            endpoint: API 엔드포인트
            params: 요청 파라미터

        Returns:
            응답 JSON 또는 None
        """
        if not self.is_available():
            logger.warning("[FRED] API key not configured")
            return None

        session = await self._get_session()
        url = f"{self.BASE_URL}{endpoint}"

        params = params or {}
        params["api_key"] = self.api_key
        params["file_type"] = "json"

        for attempt in range(self.config.max_retries):
            try:
                async with self._rate_limiter.acquire(self.SOURCE_NAME):
                    async with session.get(url, params=params) as response:
                        if response.status == 200:
                            return await response.json()
                        elif response.status == 429:
                            wait_time = 60
                            logger.warning(
                                f"[FRED] Rate limited. Waiting {wait_time}s"
                            )
                            await asyncio.sleep(wait_time)
                        elif response.status == 400:
                            text = await response.text()
                            logger.error(f"[FRED] Bad request: {text}")
                            return None
                        else:
                            logger.warning(
                                f"[FRED] Request failed: {response.status}"
                            )

            except asyncio.TimeoutError:
                logger.warning(f"[FRED] Timeout (attempt {attempt + 1})")
            except aiohttp.ClientError as e:
                logger.warning(f"[FRED] Request error: {e}")

            if attempt < self.config.max_retries - 1:
                await asyncio.sleep(self.config.retry_delay * (attempt + 1))

        return None

    async def fetch_series(
        self,
        series_id: str,
        observation_start: Optional[str] = None,
        observation_end: Optional[str] = None,
        limit: int = 30
    ) -> List[Dict[str, Any]]:
        """
        시계열 데이터 조회.

        Args:
            series_id: FRED 시리즈 ID
            observation_start: 시작 날짜 (YYYY-MM-DD)
            observation_end: 종료 날짜 (YYYY-MM-DD)
            limit: 최대 관측치 수

        Returns:
            관측치 리스트
        """
        if observation_start is None:
            # 기본값: 1년 전
            observation_start = (
                datetime.now() - timedelta(days=400)
            ).strftime("%Y-%m-%d")

        if observation_end is None:
            observation_end = datetime.now().strftime("%Y-%m-%d")

        data = await self._request("/series/observations", {
            "series_id": series_id,
            "observation_start": observation_start,
            "observation_end": observation_end,
            "sort_order": "desc",
            "limit": limit,
        })

        if data and "observations" in data:
            return data["observations"]

        return []

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
        # 캐시 확인 (FRED 데이터는 천천히 업데이트되므로 2시간 캐시)
        cached = self._cache.get_data_point(self.SOURCE_NAME, indicator)
        if cached and cached.is_valid(max_age_hours=2):
            return cached

        series_id = self.INDICATOR_SERIES.get(indicator)
        if not series_id:
            logger.warning(f"[FRED] Unknown indicator: {indicator}")
            return None

        # YoY 변환이 필요한 경우 더 많은 데이터 필요
        transform = self.INDICATOR_TRANSFORM.get(indicator)
        limit = 15 if transform == "pct_change_12" else 5

        observations = await self.fetch_series(series_id, limit=limit)

        if not observations:
            logger.warning(f"[FRED] No data for {indicator}")
            return None

        # 최신 유효 값 찾기
        value = None
        timestamp = None

        for obs in observations:
            if obs.get("value") and obs["value"] != ".":
                try:
                    raw_value = float(obs["value"])
                    obs_date = datetime.strptime(
                        obs["date"], "%Y-%m-%d"
                    ).replace(tzinfo=UTC)

                    # YoY 변환 (12개월 전 대비)
                    if transform == "pct_change_12" and len(observations) >= 13:
                        # 12개월 전 값 찾기
                        target_date = obs_date - timedelta(days=365)
                        prev_obs = None
                        for o in observations:
                            if o.get("value") and o["value"] != ".":
                                o_date = datetime.strptime(
                                    o["date"], "%Y-%m-%d"
                                ).replace(tzinfo=UTC)
                                if abs((o_date - target_date).days) < 45:
                                    prev_obs = o
                                    break

                        if prev_obs:
                            prev_value = float(prev_obs["value"])
                            if prev_value != 0:
                                value = ((raw_value - prev_value) / prev_value) * 100
                                timestamp = obs_date
                                break
                    else:
                        value = raw_value
                        timestamp = obs_date
                        break

                except (ValueError, KeyError) as e:
                    logger.debug(f"[FRED] Parse error for {indicator}: {e}")

        if value is None:
            return None

        # 단위 결정
        unit = self._get_unit(indicator)

        point = MacroDataPoint(
            indicator=indicator,
            value=value,
            timestamp=timestamp,
            source=self.SOURCE_NAME,
            category=self._get_category(indicator),
            unit=unit,
            metadata={
                "series_id": series_id,
                "transform": transform,
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
            logger.warning("[FRED] Client not available (no API key)")
            return []

        indicators = indicators or self.get_default_indicators()
        results: List[MacroDataPoint] = []

        for indicator in indicators:
            try:
                point = await self.fetch_indicator(indicator)
                if point:
                    results.append(point)
                    logger.debug(f"[FRED] Fetched {indicator}: {point.value}")

            except Exception as e:
                logger.error(f"[FRED] Error fetching {indicator}: {e}")

        self._cache.set_last_fetch(self.SOURCE_NAME)
        logger.info(f"[FRED] Fetched {len(results)} indicators")

        return results

    def _get_category(self, indicator: str) -> IndicatorCategory:
        """지표 카테고리 반환"""
        if indicator in ["fed_rate", "treasury_10y", "treasury_2y", "treasury_30y", "treasury_3m"]:
            return IndicatorCategory.US_RATES
        elif indicator in ["us_cpi_yoy", "us_pce_yoy", "us_core_cpi"]:
            return IndicatorCategory.US_ECONOMY
        elif indicator in ["us_unemployment", "us_nonfarm", "us_claims"]:
            return IndicatorCategory.US_ECONOMY
        else:
            return IndicatorCategory.US_ECONOMY

    def _get_unit(self, indicator: str) -> str:
        """지표 단위 반환"""
        if indicator in ["fed_rate", "treasury_10y", "treasury_2y", "treasury_30y",
                         "treasury_3m", "us_cpi_yoy", "us_pce_yoy", "us_core_cpi",
                         "us_unemployment"]:
            return "%"
        elif indicator in ["us_nonfarm"]:
            return "thousands"
        elif indicator in ["us_claims"]:
            return "claims"
        elif indicator in ["us_gdp"]:
            return "billions USD"
        else:
            return ""

    async def get_yield_curve(self) -> Dict[str, float]:
        """
        Treasury 수익률 곡선 조회.

        Returns:
            {"3m": rate, "2y": rate, "10y": rate, "30y": rate, "spread_10y_2y": spread}
        """
        indicators = ["treasury_3m", "treasury_2y", "treasury_10y", "treasury_30y"]
        points = await self.fetch_data(indicators)

        curve = {}
        for point in points:
            key = point.indicator.replace("treasury_", "")
            curve[key] = point.value

        # 스프레드 계산
        if "10y" in curve and "2y" in curve:
            curve["spread_10y_2y"] = curve["10y"] - curve["2y"]

        return curve
