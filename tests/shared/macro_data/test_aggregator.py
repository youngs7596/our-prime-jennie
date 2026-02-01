#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/shared/macro_data/test_aggregator.py
------------------------------------------
EnhancedMacroAggregator 테스트.
"""

import pytest
from datetime import datetime, date
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from shared.macro_data.models import MacroDataPoint, GlobalMacroSnapshot, IndicatorCategory
from shared.macro_data.aggregator import (
    EnhancedMacroAggregator,
    AggregatorConfig,
    CollectionResult,
)


UTC = ZoneInfo("UTC")
KST = ZoneInfo("Asia/Seoul")


class TestAggregatorConfig:
    """AggregatorConfig 테스트"""

    def test_default_config(self):
        """기본 설정"""
        config = AggregatorConfig()

        assert config.enable_finnhub is True
        assert config.enable_fred is True
        assert config.enable_pykrx is True
        assert config.allow_partial_failure is True
        assert config.max_external_weight == 0.10

    def test_custom_config(self):
        """커스텀 설정"""
        config = AggregatorConfig(
            enable_finnhub=False,
            enable_fred=False,
            collection_timeout=30,
        )

        assert config.enable_finnhub is False
        assert config.enable_fred is False
        assert config.collection_timeout == 30


class TestCollectionResult:
    """CollectionResult 테스트"""

    def test_successful_result(self):
        """성공 결과"""
        result = CollectionResult(
            success=True,
            data_points=[
                MacroDataPoint(
                    indicator="vix",
                    value=18.5,
                    timestamp=datetime.now(UTC),
                    source="finnhub",
                )
            ],
            sources_used=["finnhub"],
        )

        assert result.success is True
        assert len(result.data_points) == 1
        assert "finnhub" in result.sources_used

    def test_failed_result(self):
        """실패 결과"""
        result = CollectionResult(
            success=False,
            sources_failed=["fred"],
            errors=["FRED API timeout"],
        )

        assert result.success is False
        assert "fred" in result.sources_failed


class TestEnhancedMacroAggregator:
    """EnhancedMacroAggregator 테스트"""

    @pytest.fixture
    def mock_aggregator(self):
        """모든 클라이언트가 비활성화된 Aggregator"""
        config = AggregatorConfig(
            enable_finnhub=False,
            enable_fred=False,
            enable_bok_ecos=False,
            enable_pykrx=False,
            enable_rss=False,
        )
        return EnhancedMacroAggregator(config)

    def test_init_with_config(self, mock_aggregator):
        """설정으로 초기화"""
        # 모든 클라이언트 비활성화
        assert len(mock_aggregator._clients) == 0

    def test_get_available_sources(self, mock_aggregator):
        """사용 가능한 소스 조회"""
        sources = mock_aggregator.get_available_sources()
        assert isinstance(sources, list)

    @pytest.mark.asyncio
    async def test_collect_all_no_sources(self, mock_aggregator):
        """소스 없이 수집"""
        result = await mock_aggregator.collect_all()

        assert result.success is False
        assert "All sources failed" in result.errors

    def test_aggregate_empty_data(self, mock_aggregator):
        """빈 데이터 통합"""
        snapshot = mock_aggregator.aggregate([], [])

        # aggregator는 KST 기준 날짜 사용
        expected_date = datetime.now(KST).date()
        assert snapshot.snapshot_date == expected_date
        assert snapshot.get_completeness_score() == 0.0

    def test_aggregate_with_data(self, mock_aggregator):
        """데이터 통합"""
        points = [
            MacroDataPoint(
                indicator="vix",
                value=18.5,
                timestamp=datetime.now(UTC),
                source="finnhub",
                category=IndicatorCategory.VOLATILITY,
            ),
            MacroDataPoint(
                indicator="kospi_index",
                value=2650.0,
                timestamp=datetime.now(KST),
                source="pykrx",
                category=IndicatorCategory.KOREA_MARKET,
            ),
        ]

        snapshot = mock_aggregator.aggregate(points, ["finnhub", "pykrx"])

        assert snapshot.vix == 18.5
        assert snapshot.kospi_index == 2650.0
        assert "finnhub" in snapshot.data_sources
        assert "pykrx" in snapshot.data_sources

    def test_aggregate_filters_old_data(self, mock_aggregator):
        """오래된 데이터 필터링"""
        from datetime import timedelta

        # VIX의 max_age는 72시간 (주말 고려), 따라서 73시간 이상 오래된 데이터 사용
        old_timestamp = datetime.now(UTC) - timedelta(hours=73)
        points = [
            MacroDataPoint(
                indicator="vix",
                value=18.5,
                timestamp=old_timestamp,  # 73시간 전 (만료, vix max_age=72)
                source="finnhub",
            ),
        ]

        snapshot = mock_aggregator.aggregate(points, ["finnhub"])

        # 만료된 데이터는 필터링됨
        assert snapshot.vix is None

    def test_aggregate_selects_latest(self, mock_aggregator):
        """최신 데이터 선택"""
        from datetime import timedelta

        points = [
            MacroDataPoint(
                indicator="usd_krw",
                value=1340.0,
                timestamp=datetime.now(UTC) - timedelta(hours=2),
                source="finnhub",
            ),
            MacroDataPoint(
                indicator="usd_krw",
                value=1350.0,  # 더 최신
                timestamp=datetime.now(UTC),
                source="bok_ecos",
            ),
        ]

        snapshot = mock_aggregator.aggregate(points, ["finnhub", "bok_ecos"])

        assert snapshot.usd_krw == 1350.0

    @pytest.mark.asyncio
    async def test_collect_and_aggregate_mock(self, mock_aggregator):
        """수집 및 통합 (mock)"""
        # Mock 클라이언트 추가
        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        mock_client.get_source_name.return_value = "mock"
        mock_client.fetch_data = AsyncMock(return_value=[
            MacroDataPoint(
                indicator="vix",
                value=18.5,
                timestamp=datetime.now(UTC),
                source="mock",
            ),
        ])

        mock_aggregator._clients["mock"] = mock_client

        snapshot = await mock_aggregator.collect_and_aggregate()

        assert snapshot is not None
        assert snapshot.vix == 18.5

    @pytest.mark.asyncio
    async def test_close(self, mock_aggregator):
        """클라이언트 종료"""
        await mock_aggregator.close()
        # 에러 없이 완료되어야 함


class TestAggregatorIntegration:
    """Aggregator 통합 테스트 (실제 클라이언트, 환경변수 필요)"""

    @pytest.fixture
    def aggregator_pykrx_only(self):
        """pykrx만 활성화된 Aggregator (API 키 불필요)"""
        config = AggregatorConfig(
            enable_finnhub=False,
            enable_fred=False,
            enable_bok_ecos=False,
            enable_pykrx=True,
            enable_rss=False,
        )
        return EnhancedMacroAggregator(config)

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="pykrx 네트워크 호출 필요")
    async def test_collect_pykrx_real(self, aggregator_pykrx_only):
        """실제 pykrx 수집"""
        snapshot = await aggregator_pykrx_only.collect_and_aggregate()

        if snapshot:
            assert snapshot.kospi_index is not None or snapshot.kosdaq_index is not None

        await aggregator_pykrx_only.close()
