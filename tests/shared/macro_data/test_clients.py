#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/shared/macro_data/test_clients.py
---------------------------------------
API 클라이언트 테스트 (Mock 기반).
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

UTC = ZoneInfo("UTC")


class TestFinnhubClient:
    """FinnhubClient 테스트"""

    @pytest.fixture
    def client(self):
        from shared.macro_data.clients.finnhub_client import FinnhubClient
        return FinnhubClient(api_key="test_key")

    def test_init(self, client):
        """초기화"""
        assert client.api_key == "test_key"
        assert client.is_available() is True

    def test_is_available_no_key(self):
        """API 키 없을 때"""
        from shared.macro_data.clients.finnhub_client import FinnhubClient
        client = FinnhubClient(api_key="")
        assert client.is_available() is False

    def test_get_rate_limit(self, client):
        """Rate limit 조회"""
        rate_limit = client.get_rate_limit()
        assert rate_limit == (60, 5000)

    def test_get_source_name(self, client):
        """소스 이름"""
        assert client.get_source_name() == "finnhub"

    def test_get_default_indicators(self, client):
        """기본 지표"""
        indicators = client.get_default_indicators()
        assert "vix" in indicators
        assert "usd_krw" in indicators

    @pytest.mark.asyncio
    async def test_fetch_data_no_key(self):
        """API 키 없이 fetch"""
        from shared.macro_data.clients.finnhub_client import FinnhubClient
        client = FinnhubClient(api_key="")

        result = await client.fetch_data()
        assert result == []

    @pytest.mark.asyncio
    async def test_close(self, client):
        """세션 종료"""
        await client.close()


class TestFREDClient:
    """FREDClient 테스트"""

    @pytest.fixture
    def client(self):
        from shared.macro_data.clients.fred_client import FREDClient
        return FREDClient(api_key="test_key")

    def test_init(self, client):
        """초기화"""
        assert client.api_key == "test_key"
        assert client.is_available() is True

    def test_get_rate_limit(self, client):
        """Rate limit 조회"""
        rate_limit = client.get_rate_limit()
        assert rate_limit == (120, 100000)

    def test_get_source_name(self, client):
        """소스 이름"""
        assert client.get_source_name() == "fred"

    def test_get_default_indicators(self, client):
        """기본 지표"""
        indicators = client.get_default_indicators()
        assert "fed_rate" in indicators
        assert "treasury_10y" in indicators

    @pytest.mark.asyncio
    async def test_get_yield_curve_mock(self, client):
        """수익률 곡선 조회 (mock)"""
        with patch.object(client, 'fetch_data', new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = []
            result = await client.get_yield_curve()
            assert isinstance(result, dict)


class TestBOKECOSClient:
    """BOKECOSClient 테스트"""

    @pytest.fixture
    def client(self):
        from shared.macro_data.clients.bok_ecos_client import BOKECOSClient
        return BOKECOSClient(api_key="test_key")

    def test_init(self, client):
        """초기화"""
        assert client.api_key == "test_key"
        assert client.is_available() is True

    def test_get_rate_limit(self, client):
        """Rate limit 조회"""
        rate_limit = client.get_rate_limit()
        assert rate_limit == (30, 50000)

    def test_get_source_name(self, client):
        """소스 이름"""
        assert client.get_source_name() == "bok_ecos"

    def test_get_default_indicators(self, client):
        """기본 지표"""
        indicators = client.get_default_indicators()
        assert "bok_rate" in indicators


class TestPyKRXClient:
    """PyKRXClient 테스트"""

    @pytest.fixture
    def client(self):
        from shared.macro_data.clients.pykrx_client import PyKRXClient
        return PyKRXClient()

    def test_init(self, client):
        """초기화"""
        # pykrx 설치 여부에 따라 다름
        pass

    def test_get_rate_limit(self, client):
        """Rate limit 조회"""
        rate_limit = client.get_rate_limit()
        assert rate_limit == (60, 100000)

    def test_get_source_name(self, client):
        """소스 이름"""
        assert client.get_source_name() == "pykrx"

    def test_get_default_indicators(self, client):
        """기본 지표"""
        indicators = client.get_default_indicators()
        assert "kospi_index" in indicators
        assert "kosdaq_index" in indicators


class TestRSSNewsClient:
    """RSSNewsClient 테스트"""

    @pytest.fixture
    def client(self):
        from shared.macro_data.clients.rss_news_client import RSSNewsClient
        return RSSNewsClient()

    def test_init(self, client):
        """초기화"""
        assert client.is_available() is True

    def test_get_rate_limit(self, client):
        """Rate limit 조회"""
        rate_limit = client.get_rate_limit()
        assert rate_limit == (30, 10000)

    def test_get_source_name(self, client):
        """소스 이름"""
        assert client.get_source_name() == "rss"

    def test_sentiment_analysis(self, client):
        """센티먼트 분석"""
        # 긍정
        sentiment = client._analyze_sentiment("주가 상승 기대, 호재 지속")
        assert sentiment > 0

        # 부정
        sentiment = client._analyze_sentiment("주가 하락 우려, 위기 확산")
        assert sentiment < 0

        # 중립
        sentiment = client._analyze_sentiment("시장 동향 분석")
        assert sentiment == 0

    def test_parse_date(self, client):
        """날짜 파싱"""
        # RFC 822
        dt = client._parse_date("Wed, 01 Feb 2026 10:30:00 +0900")
        assert dt is not None
        assert dt.hour == 10

        # ISO 8601
        dt = client._parse_date("2026-02-01T10:30:00+09:00")
        assert dt is not None

        # Invalid
        dt = client._parse_date("invalid date")
        assert dt is None

    @pytest.mark.asyncio
    async def test_get_sentiment_summary_mock(self, client):
        """센티먼트 요약 (mock)"""
        with patch.object(client, 'fetch_data', new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = []
            result = await client.get_sentiment_summary()
            assert "sentiment" in result
            assert "label" in result
