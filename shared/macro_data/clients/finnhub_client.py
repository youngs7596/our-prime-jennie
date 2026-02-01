#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shared/macro_data/clients/finnhub_client.py
-------------------------------------------
Finnhub API 클라이언트.

글로벌 시장 데이터, 뉴스 등을 수집합니다.
Rate Limit: 60 calls/minute (free tier)

무료 티어 제한:
- ✅ US Stock Quotes (AAPL 등)
- ✅ Market News
- ✅ Crypto Quotes
- ❌ Economic Calendar (Premium)
- ❌ Forex Rates (Premium)
- ❌ VIX/Index Quotes (CFD Subscription 필요)
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

from ..models import MacroDataPoint, NewsItem, IndicatorCategory
from ..rate_limiter import get_rate_limiter
from ..cache import get_macro_cache
from .base import MacroDataClient, ClientConfig

logger = logging.getLogger(__name__)

UTC = ZoneInfo("UTC")
KST = ZoneInfo("Asia/Seoul")


def _load_api_key_from_secrets() -> Optional[str]:
    """secrets.json에서 API 키 로드"""
    # 프로젝트 루트의 secrets.json 탐색
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
                    return secrets.get("finnhub_api_key")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"[Finnhub] Failed to read {path}: {e}")

    return None


class FinnhubClient(MacroDataClient):
    """
    Finnhub API 클라이언트.

    제공 데이터 (무료 티어):
    - US 주식 시세 (AAPL, SPY 등)
    - 글로벌 뉴스
    - 암호화폐 시세

    프리미엄 전용 (사용 불가):
    - VIX, DXY 지수 (CFD 구독 필요)
    - 환율 (Forex Premium 필요)
    - 경제 캘린더

    Usage:
        client = FinnhubClient()
        news = await client.fetch_news()
        data = await client.fetch_data(["spy"])
    """

    BASE_URL = "https://finnhub.io/api/v1"
    SOURCE_NAME = "finnhub"

    # 지표 -> Finnhub symbol 매핑 (무료 티어)
    INDICATOR_SYMBOLS = {
        # US ETFs (무료 티어에서 작동)
        "spy": "SPY",      # S&P 500 ETF
        "qqq": "QQQ",      # Nasdaq 100 ETF
        "dia": "DIA",      # Dow Jones ETF
        "iwm": "IWM",      # Russell 2000 ETF
        "eem": "EEM",      # Emerging Markets ETF
        "ewj": "EWJ",      # Japan ETF
        "fxi": "FXI",      # China Large-Cap ETF
        "ewy": "EWY",      # South Korea ETF (KOSPI 프록시)
        # VIX ETFs (실제 VIX 대용)
        "vxx": "VXX",      # VIX Short-Term Futures
        "uvxy": "UVXY",    # 2x VIX Short-Term
        # 암호화폐
        "btc": "BINANCE:BTCUSDT",
        "eth": "BINANCE:ETHUSDT",
    }

    # 프리미엄 전용 지표 (요청 시 스킵)
    PREMIUM_ONLY = {"vix", "dxy_index", "usd_krw", "usd_jpy", "usd_cny", "usd_eur"}

    def __init__(
        self,
        api_key: Optional[str] = None,
        config: Optional[ClientConfig] = None
    ):
        """
        클라이언트 초기화.

        Args:
            api_key: Finnhub API 키 (없으면 secrets.json 또는 환경변수에서)
            config: 클라이언트 설정
        """
        # API 키 로드 우선순위: 인자 > 환경변수 > secrets.json
        self.api_key = (
            api_key
            or os.getenv("FINNHUB_API_KEY")
            or _load_api_key_from_secrets()
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
            logger.info(f"[Finnhub] API key loaded ({self.api_key[:10]}...)")
        else:
            logger.warning("[Finnhub] API key not found")

    async def _get_session(self) -> aiohttp.ClientSession:
        """aiohttp 세션 반환 (lazy init)"""
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
        """Rate limit 반환: (60/min, 5000/day)"""
        return (60, 5000)

    def get_source_name(self) -> str:
        return self.SOURCE_NAME

    def get_default_indicators(self) -> List[str]:
        """무료 티어에서 사용 가능한 기본 지표"""
        return ["spy", "qqq", "vxx", "ewy"]

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
            endpoint: API 엔드포인트 (예: "/quote")
            params: 요청 파라미터

        Returns:
            응답 JSON 또는 None
        """
        if not self.is_available():
            logger.warning("[Finnhub] API key not configured")
            return None

        session = await self._get_session()
        url = f"{self.BASE_URL}{endpoint}"

        params = params or {}
        params["token"] = self.api_key

        for attempt in range(self.config.max_retries):
            try:
                async with self._rate_limiter.acquire(self.SOURCE_NAME):
                    async with session.get(url, params=params) as response:
                        if response.status == 200:
                            return await response.json()
                        elif response.status == 429:
                            # Rate limit hit
                            wait_time = int(response.headers.get("Retry-After", 60))
                            logger.warning(
                                f"[Finnhub] Rate limited. Waiting {wait_time}s"
                            )
                            await asyncio.sleep(wait_time)
                        elif response.status == 401:
                            logger.error("[Finnhub] Invalid API key")
                            return None
                        else:
                            logger.warning(
                                f"[Finnhub] Request failed: {response.status}"
                            )

            except asyncio.TimeoutError:
                logger.warning(f"[Finnhub] Timeout (attempt {attempt + 1})")
            except aiohttp.ClientError as e:
                logger.warning(f"[Finnhub] Request error: {e}")

            if attempt < self.config.max_retries - 1:
                await asyncio.sleep(self.config.retry_delay * (attempt + 1))

        return None

    async def fetch_quote(self, symbol: str) -> Optional[MacroDataPoint]:
        """
        시세 조회.

        Args:
            symbol: 심볼 (예: "^VIX")

        Returns:
            MacroDataPoint 또는 None
        """
        # 캐시 확인
        indicator = next(
            (k for k, v in self.INDICATOR_SYMBOLS.items() if v == symbol),
            symbol
        )
        cached = self._cache.get_data_point(self.SOURCE_NAME, indicator)
        if cached and cached.is_valid(max_age_hours=1):
            return cached

        # API 요청
        data = await self._request("/quote", {"symbol": symbol})

        if data and "c" in data:  # c = current price
            point = MacroDataPoint(
                indicator=indicator,
                value=float(data["c"]),
                timestamp=datetime.fromtimestamp(data.get("t", 0), tz=UTC),
                source=self.SOURCE_NAME,
                category=self._get_category(indicator),
                metadata={
                    "high": data.get("h"),
                    "low": data.get("l"),
                    "open": data.get("o"),
                    "prev_close": data.get("pc"),
                    "change_pct": data.get("dp"),
                }
            )

            # 캐시 저장
            self._cache.set_data_point(self.SOURCE_NAME, indicator, point)

            return point

        return None

    async def fetch_forex(self, pair: str) -> Optional[MacroDataPoint]:
        """
        환율 조회.

        Args:
            pair: 통화쌍 (예: "OANDA:USD_KRW")

        Returns:
            MacroDataPoint 또는 None
        """
        # 캐시 확인
        indicator = next(
            (k for k, v in self.INDICATOR_SYMBOLS.items() if v == pair),
            pair.replace("OANDA:", "").lower()
        )
        cached = self._cache.get_data_point(self.SOURCE_NAME, indicator)
        if cached and cached.is_valid(max_age_hours=1):
            return cached

        # API 요청
        data = await self._request("/forex/candle", {
            "symbol": pair,
            "resolution": "D",
            "from": int((datetime.now() - timedelta(days=1)).timestamp()),
            "to": int(datetime.now().timestamp()),
        })

        if data and data.get("s") == "ok" and data.get("c"):
            # 가장 최근 종가
            value = float(data["c"][-1])
            timestamp = datetime.fromtimestamp(data["t"][-1], tz=UTC)

            point = MacroDataPoint(
                indicator=indicator,
                value=value,
                timestamp=timestamp,
                source=self.SOURCE_NAME,
                category=IndicatorCategory.CURRENCY,
                metadata={
                    "high": data.get("h", [])[-1] if data.get("h") else None,
                    "low": data.get("l", [])[-1] if data.get("l") else None,
                    "open": data.get("o", [])[-1] if data.get("o") else None,
                }
            )

            self._cache.set_data_point(self.SOURCE_NAME, indicator, point)

            return point

        return None

    async def fetch_economic_calendar(
        self,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        경제 캘린더 조회.

        Args:
            from_date: 시작 일시
            to_date: 종료 일시

        Returns:
            경제 이벤트 리스트
        """
        from_date = from_date or datetime.now(UTC) - timedelta(days=1)
        to_date = to_date or datetime.now(UTC) + timedelta(days=7)

        data = await self._request("/calendar/economic", {
            "from": from_date.strftime("%Y-%m-%d"),
            "to": to_date.strftime("%Y-%m-%d"),
        })

        if data and "economicCalendar" in data:
            return data["economicCalendar"]

        return []

    async def fetch_news(
        self,
        category: str = "general",
        min_id: int = 0
    ) -> List[NewsItem]:
        """
        뉴스 조회.

        Args:
            category: 뉴스 카테고리 (general, forex, crypto, merger)
            min_id: 최소 뉴스 ID (페이지네이션)

        Returns:
            NewsItem 리스트
        """
        # 캐시 확인
        cached = self._cache.get_news(f"{self.SOURCE_NAME}_{category}")
        if cached:
            return [
                NewsItem(
                    title=n["title"],
                    source=n.get("source", self.SOURCE_NAME),
                    published_at=datetime.fromisoformat(n["published_at"]),
                    url=n.get("url", ""),
                    summary=n.get("summary", ""),
                    keywords=n.get("keywords", []),
                )
                for n in cached
            ]

        # API 요청
        data = await self._request("/news", {
            "category": category,
            "minId": min_id,
        })

        if not data:
            return []

        news_items = []
        for item in data[:20]:  # 최대 20개
            try:
                news_items.append(NewsItem(
                    title=item.get("headline", ""),
                    source=item.get("source", self.SOURCE_NAME),
                    published_at=datetime.fromtimestamp(
                        item.get("datetime", 0), tz=UTC
                    ),
                    url=item.get("url", ""),
                    summary=item.get("summary", ""),
                    keywords=item.get("related", "").split(",") if item.get("related") else [],
                ))
            except (KeyError, ValueError) as e:
                logger.warning(f"[Finnhub] News parse error: {e}")

        # 캐시 저장
        if news_items:
            self._cache.set_news(
                f"{self.SOURCE_NAME}_{category}",
                [n.to_dict() for n in news_items]
            )

        return news_items

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
            logger.warning("[Finnhub] Client not available (no API key)")
            return []

        indicators = indicators or self.get_default_indicators()
        results: List[MacroDataPoint] = []

        for indicator in indicators:
            # 프리미엄 전용 지표 스킵
            if indicator.lower() in self.PREMIUM_ONLY:
                logger.debug(
                    f"[Finnhub] Skipping premium indicator: {indicator}"
                )
                continue

            symbol = self.INDICATOR_SYMBOLS.get(indicator.lower())
            if not symbol:
                logger.warning(f"[Finnhub] Unknown indicator: {indicator}")
                continue

            try:
                # 암호화폐 vs 주식 구분
                if symbol.startswith("BINANCE:"):
                    point = await self.fetch_quote(symbol)
                else:
                    point = await self.fetch_quote(symbol)

                if point:
                    results.append(point)
                    logger.debug(
                        f"[Finnhub] Fetched {indicator}: {point.value}"
                    )

            except Exception as e:
                logger.error(f"[Finnhub] Error fetching {indicator}: {e}")

        self._cache.set_last_fetch(self.SOURCE_NAME)
        logger.info(f"[Finnhub] Fetched {len(results)} indicators")

        return results

    def _get_category(self, indicator: str) -> IndicatorCategory:
        """지표 카테고리 반환"""
        ind = indicator.lower()
        if ind in ["vxx", "uvxy"]:
            return IndicatorCategory.VOLATILITY
        elif ind in ["btc", "eth"]:
            return IndicatorCategory.US_ECONOMY  # 암호화폐는 별도 카테고리 없음
        elif ind in ["spy", "qqq", "dia", "iwm"]:
            return IndicatorCategory.US_ECONOMY
        elif ind in ["eem", "ewj", "fxi", "ewy"]:
            return IndicatorCategory.US_ECONOMY  # 해외 ETF도 일단 US로
        else:
            return IndicatorCategory.US_ECONOMY
