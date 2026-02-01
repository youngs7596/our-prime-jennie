#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shared/macro_data/aggregator.py
-------------------------------
데이터 통합 모듈.

여러 소스에서 수집된 매크로 데이터를 하나의 GlobalMacroSnapshot으로 통합합니다.

3현자 Council 권고사항:
- 24시간 이상 지연 데이터 자동 필터링
- 다중 소스 검증
- 외부 가중치 ≤10% 제한
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Type
from zoneinfo import ZoneInfo

from .models import MacroDataPoint, GlobalMacroSnapshot, IndicatorCategory
from .clients.base import MacroDataClient
from .clients.finnhub_client import FinnhubClient
from .clients.fred_client import FREDClient
from .clients.bok_ecos_client import BOKECOSClient
from .clients.pykrx_client import PyKRXClient
from .clients.rss_news_client import RSSNewsClient
from .validator import DataValidator, ValidationResult
from .cache import get_macro_cache

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
UTC = ZoneInfo("UTC")


@dataclass
class AggregatorConfig:
    """Aggregator 설정"""
    # 소스별 활성화 여부
    enable_finnhub: bool = True
    enable_fred: bool = True
    enable_bok_ecos: bool = True
    enable_pykrx: bool = True
    enable_rss: bool = True

    # 병렬 수집 타임아웃 (초)
    collection_timeout: int = 60

    # 캐시 사용 여부
    use_cache: bool = True

    # 부분 실패 허용
    allow_partial_failure: bool = True

    # 외부 가중치 제한 (3현자 권고: ≤10%)
    max_external_weight: float = 0.10


@dataclass
class CollectionResult:
    """수집 결과"""
    success: bool = True
    data_points: List[MacroDataPoint] = field(default_factory=list)
    sources_used: List[str] = field(default_factory=list)
    sources_failed: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    collection_time: float = 0.0


class EnhancedMacroAggregator:
    """
    Enhanced Macro Data Aggregator.

    여러 API 클라이언트에서 데이터를 수집하고
    GlobalMacroSnapshot으로 통합합니다.

    Usage:
        aggregator = EnhancedMacroAggregator()
        snapshot = await aggregator.collect_and_aggregate()
    """

    # 지표 -> 스냅샷 필드 매핑
    INDICATOR_TO_SNAPSHOT = {
        # US Rates (FRED)
        "fed_rate": "fed_rate",
        "treasury_10y": "treasury_10y",
        "treasury_2y": "treasury_2y",
        # US Economy (FRED)
        "us_cpi_yoy": "us_cpi_yoy",
        "us_pce_yoy": "us_pce_yoy",
        "us_unemployment": "us_unemployment",
        "us_pmi": "us_pmi",
        # Volatility
        "vix": "vix",
        "vxx": "vix",  # VIX ETF proxy (Finnhub 무료)
        "uvxy": "vix",  # 2x VIX ETF proxy
        # US ETFs (Finnhub 무료) - 참고용
        "spy": "spy_price",  # S&P 500 ETF
        "qqq": "qqq_price",  # Nasdaq 100 ETF
        "ewy": "ewy_price",  # Korea ETF (KOSPI proxy)
        # Currency
        "dxy_index": "dxy_index",
        "usd_krw": "usd_krw",
        "usd_krw_bok": "usd_krw",  # BOK 환율도 동일 필드
        "usd_jpy": "usd_jpy",
        "usd_cny": "usd_cny",
        # Korea (BOK ECOS, pykrx)
        "bok_rate": "bok_rate",
        "korea_cpi_yoy": "korea_cpi_yoy",
        "korea_cpi": "korea_cpi_yoy",  # alias
        "kospi_index": "kospi_index",
        "kosdaq_index": "kosdaq_index",
        "kospi_change_pct": "kospi_change_pct",
        "kosdaq_change_pct": "kosdaq_change_pct",
        # Sentiment (RSS)
        "global_news_sentiment": "global_news_sentiment",
        "korea_news_sentiment": "korea_news_sentiment",
    }

    def __init__(self, config: Optional[AggregatorConfig] = None):
        """
        Aggregator 초기화.

        Args:
            config: Aggregator 설정
        """
        self.config = config or AggregatorConfig()
        self._clients: Dict[str, MacroDataClient] = {}
        self._validator = DataValidator()
        self._cache = get_macro_cache()

        # 클라이언트 초기화
        self._init_clients()

    def _init_clients(self) -> None:
        """API 클라이언트 초기화"""
        if self.config.enable_finnhub:
            client = FinnhubClient()
            if client.is_available():
                self._clients["finnhub"] = client
            else:
                logger.warning("[Aggregator] Finnhub client not available (no API key)")

        if self.config.enable_fred:
            client = FREDClient()
            if client.is_available():
                self._clients["fred"] = client
            else:
                logger.warning("[Aggregator] FRED client not available (no API key)")

        if self.config.enable_bok_ecos:
            client = BOKECOSClient()
            if client.is_available():
                self._clients["bok_ecos"] = client
            else:
                logger.warning("[Aggregator] BOK ECOS client not available (no API key)")

        if self.config.enable_pykrx:
            client = PyKRXClient()
            if client.is_available():
                self._clients["pykrx"] = client
            else:
                logger.warning("[Aggregator] pykrx client not available")

        if self.config.enable_rss:
            self._clients["rss"] = RSSNewsClient()

        logger.info(
            f"[Aggregator] Initialized {len(self._clients)} clients: "
            f"{list(self._clients.keys())}"
        )

    async def close(self) -> None:
        """모든 클라이언트 종료"""
        for client in self._clients.values():
            if hasattr(client, 'close'):
                await client.close()

    async def _collect_from_source(
        self,
        source: str,
        client: MacroDataClient
    ) -> List[MacroDataPoint]:
        """
        단일 소스에서 데이터 수집.

        Args:
            source: 소스 이름
            client: API 클라이언트

        Returns:
            MacroDataPoint 리스트
        """
        try:
            logger.debug(f"[Aggregator] Collecting from {source}")
            points = await client.fetch_data()
            logger.info(f"[Aggregator] {source}: collected {len(points)} points")
            return points

        except Exception as e:
            logger.error(f"[Aggregator] {source} collection failed: {e}")
            return []

    async def collect_all(self) -> CollectionResult:
        """
        모든 소스에서 데이터 수집.

        Returns:
            CollectionResult
        """
        result = CollectionResult()
        start_time = datetime.now()

        # 병렬로 모든 소스에서 수집
        tasks = {
            source: self._collect_from_source(source, client)
            for source, client in self._clients.items()
        }

        try:
            done, pending = await asyncio.wait(
                [
                    asyncio.create_task(coro, name=source)
                    for source, coro in tasks.items()
                ],
                timeout=self.config.collection_timeout,
            )

            # 완료된 태스크 결과 수집
            for task in done:
                source = task.get_name()
                try:
                    points = task.result()
                    if points:
                        result.data_points.extend(points)
                        result.sources_used.append(source)
                    else:
                        result.sources_failed.append(source)
                except Exception as e:
                    result.sources_failed.append(source)
                    result.errors.append(f"{source}: {str(e)}")

            # 타임아웃된 태스크
            for task in pending:
                source = task.get_name()
                task.cancel()
                result.sources_failed.append(source)
                result.errors.append(f"{source}: timeout")

        except Exception as e:
            result.success = False
            result.errors.append(f"Collection failed: {str(e)}")

        result.collection_time = (datetime.now() - start_time).total_seconds()

        # 부분 실패 허용 여부
        if not self.config.allow_partial_failure and result.sources_failed:
            result.success = False

        # 모든 소스 실패 시
        if not result.sources_used:
            result.success = False
            result.errors.append("All sources failed")

        logger.info(
            f"[Aggregator] Collection complete: {len(result.data_points)} points "
            f"from {len(result.sources_used)} sources in {result.collection_time:.2f}s"
        )

        return result

    def aggregate(
        self,
        data_points: List[MacroDataPoint],
        sources_used: List[str]
    ) -> GlobalMacroSnapshot:
        """
        데이터 포인트를 GlobalMacroSnapshot으로 통합.

        Args:
            data_points: 수집된 데이터 포인트
            sources_used: 사용된 소스 목록

        Returns:
            GlobalMacroSnapshot
        """
        now = datetime.now(KST)
        today = now.date()

        # 유효한 데이터만 필터링 (3현자 권고: 24시간 필터링)
        valid_points = self._validator.filter_valid_points(data_points)

        # 지표별로 그룹핑
        indicator_points: Dict[str, List[MacroDataPoint]] = {}
        for point in valid_points:
            if point.indicator not in indicator_points:
                indicator_points[point.indicator] = []
            indicator_points[point.indicator].append(point)

        # 스냅샷 필드 채우기
        snapshot_data: Dict[str, Any] = {
            "snapshot_date": today,
            "snapshot_time": now,
            "data_sources": sources_used,
            "raw_data_points": valid_points,
        }

        missing_indicators = []
        stale_indicators = []

        for indicator, points in indicator_points.items():
            # 최적의 값 선택
            best_point = self._validator.select_best_value(points)

            if best_point is None:
                continue

            # 스냅샷 필드 매핑
            snapshot_field = self.INDICATOR_TO_SNAPSHOT.get(indicator)
            if snapshot_field:
                snapshot_data[snapshot_field] = best_point.value

                # 메타데이터에서 등락률 추출 (pykrx)
                if indicator == "kospi_index" and "change_pct" in best_point.metadata:
                    snapshot_data["kospi_change_pct"] = best_point.metadata["change_pct"]
                elif indicator == "kosdaq_index" and "change_pct" in best_point.metadata:
                    snapshot_data["kosdaq_change_pct"] = best_point.metadata["change_pct"]

            # 오래된 데이터 추적
            if best_point.quality.value in ["stale", "expired"]:
                stale_indicators.append(indicator)

        # 누락된 지표 추적
        expected_indicators = set(self.INDICATOR_TO_SNAPSHOT.keys())
        collected_indicators = set(indicator_points.keys())
        missing_indicators = list(expected_indicators - collected_indicators)

        snapshot_data["missing_indicators"] = missing_indicators
        snapshot_data["stale_indicators"] = stale_indicators
        snapshot_data["data_freshness"] = self._validator.get_data_freshness_score(valid_points)

        # 검증 에러 추가
        validation_result = self._validator.validate(valid_points)
        snapshot_data["validation_errors"] = validation_result.errors + validation_result.warnings

        return GlobalMacroSnapshot(**snapshot_data)

    async def collect_and_aggregate(self) -> Optional[GlobalMacroSnapshot]:
        """
        데이터 수집 및 통합 (원스톱).

        Returns:
            GlobalMacroSnapshot 또는 None
        """
        # 캐시 확인
        if self.config.use_cache:
            cached = self._cache.get_snapshot()
            if cached and cached.data_freshness > 0.7:
                logger.info("[Aggregator] Using cached snapshot")
                return cached

        # 데이터 수집
        collection_result = await self.collect_all()

        if not collection_result.success and not self.config.allow_partial_failure:
            logger.error(f"[Aggregator] Collection failed: {collection_result.errors}")
            return None

        if not collection_result.data_points:
            logger.error("[Aggregator] No data points collected")
            return None

        # 통합
        snapshot = self.aggregate(
            collection_result.data_points,
            collection_result.sources_used
        )

        # 캐시 저장
        if self.config.use_cache:
            self._cache.set_snapshot(snapshot)

        logger.info(
            f"[Aggregator] Snapshot created: "
            f"completeness={snapshot.get_completeness_score():.0%}, "
            f"freshness={snapshot.data_freshness:.0%}"
        )

        return snapshot

    async def collect_specific(
        self,
        sources: List[str],
        indicators: Optional[Dict[str, List[str]]] = None
    ) -> CollectionResult:
        """
        특정 소스/지표만 수집.

        Args:
            sources: 수집할 소스 목록
            indicators: 소스별 수집할 지표 목록

        Returns:
            CollectionResult
        """
        result = CollectionResult()
        start_time = datetime.now()

        for source in sources:
            if source not in self._clients:
                result.errors.append(f"Unknown source: {source}")
                continue

            client = self._clients[source]

            try:
                # 특정 지표만 요청
                source_indicators = None
                if indicators and source in indicators:
                    source_indicators = indicators[source]

                points = await client.fetch_data(source_indicators)

                if points:
                    result.data_points.extend(points)
                    result.sources_used.append(source)
                else:
                    result.sources_failed.append(source)

            except Exception as e:
                result.sources_failed.append(source)
                result.errors.append(f"{source}: {str(e)}")

        result.collection_time = (datetime.now() - start_time).total_seconds()
        result.success = bool(result.sources_used)

        return result

    def get_available_sources(self) -> List[str]:
        """사용 가능한 소스 목록"""
        return list(self._clients.keys())

    def get_source_status(self) -> Dict[str, Dict[str, Any]]:
        """소스별 상태 조회"""
        status = {}
        for source, client in self._clients.items():
            last_fetch = self._cache.get_last_fetch(source)
            status[source] = {
                "available": client.is_available(),
                "rate_limit": client.get_rate_limit(),
                "last_fetch": last_fetch.isoformat() if last_fetch else None,
            }
        return status
