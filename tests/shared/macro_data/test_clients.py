#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/shared/macro_data/test_clients.py
---------------------------------------
API 클라이언트 테스트 (Mock 기반).
"""

import os
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
        # Mock env and secrets.json to ensure no API key is loaded
        with patch.dict(os.environ, {"FINNHUB_API_KEY": ""}, clear=False), \
             patch("shared.macro_data.clients.finnhub_client._load_api_key_from_secrets", return_value=None):
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
        """기본 지표 (무료 티어)"""
        indicators = client.get_default_indicators()
        # 무료 티어에서 사용 가능한 지표 (ETFs)
        assert "spy" in indicators    # S&P 500 ETF
        assert "vxx" in indicators    # VIX futures ETF
        assert "ewy" in indicators    # Korea ETF

    @pytest.mark.asyncio
    async def test_fetch_data_no_key(self):
        """API 키 없이 fetch"""
        from shared.macro_data.clients.finnhub_client import FinnhubClient
        # Mock env and secrets.json to ensure no API key is loaded
        with patch.dict(os.environ, {"FINNHUB_API_KEY": ""}, clear=False), \
             patch("shared.macro_data.clients.finnhub_client._load_api_key_from_secrets", return_value=None):
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


class TestPoliticalNewsClient:
    """PoliticalNewsClient 테스트"""

    @pytest.fixture
    def client(self):
        from shared.macro_data.clients.political_news_client import PoliticalNewsClient
        return PoliticalNewsClient()

    def test_init(self, client):
        """초기화"""
        assert client.is_available() is True
        assert len(client._all_keywords) > 0

    def test_get_rate_limit(self, client):
        """Rate limit 조회"""
        rate_limit = client.get_rate_limit()
        assert rate_limit == (20, 5000)

    def test_get_source_name(self, client):
        """소스 이름"""
        assert client.get_source_name() == "political_news"

    def test_get_default_indicators(self, client):
        """기본 지표"""
        indicators = client.get_default_indicators()
        assert "political_risk_score" in indicators
        assert "political_alert_count" in indicators

    def test_detect_keywords_fed(self, client):
        """연준 관련 키워드 감지"""
        text = "Federal Reserve chair Powell announces rate cut decision"
        detected = client._detect_keywords(text)
        assert len(detected) > 0

        # 키워드, 카테고리, 심각도, 영향방향
        keywords = [d[0] for d in detected]
        categories = [d[1] for d in detected]
        severities = [d[2] for d in detected]

        assert any("fed" in cat for cat in categories)
        assert "critical" in severities

    def test_detect_keywords_trade(self, client):
        """무역/관세 키워드 감지"""
        text = "Trump announces new tariff on semiconductor imports"
        detected = client._detect_keywords(text)
        assert len(detected) > 0

        categories = [d[1] for d in detected]
        assert any(cat in ["trade", "us_politics"] for cat in categories)

    def test_detect_keywords_geopolitical(self, client):
        """지정학적 키워드 감지"""
        text = "North Korea missile test raises tension in the region"
        detected = client._detect_keywords(text)
        assert len(detected) > 0

        categories = [d[1] for d in detected]
        assert "geopolitical" in categories

    def test_detect_keywords_crisis(self, client):
        """위기 키워드 감지"""
        text = "Market crash fears as recession looms"
        detected = client._detect_keywords(text)
        assert len(detected) > 0

        categories = [d[1] for d in detected]
        severities = [d[2] for d in detected]
        assert "crisis" in categories
        assert "critical" in severities

    def test_detect_keywords_korean(self, client):
        """한글 키워드 감지"""
        text = "트럼프 대통령이 새 연준의장 후보를 지명했다"
        detected = client._detect_keywords(text)
        assert len(detected) > 0

        keywords = [d[0] for d in detected]
        assert any("트럼프" in kw or "연준" in kw for kw in keywords)

    def test_detect_keywords_impact_direction(self, client):
        """영향 방향 감지"""
        # Bearish
        text = "Fed announces rate hike amid inflation concerns"
        detected = client._detect_keywords(text)
        directions = [d[3] for d in detected]
        assert "bearish" in directions

        # Bullish
        text = "Fed signals rate cut in upcoming meeting"
        detected = client._detect_keywords(text)
        directions = [d[3] for d in detected]
        assert "bullish" in directions

    def test_detect_keywords_no_match(self, client):
        """키워드 미매칭"""
        text = "Local weather forecast for tomorrow"
        detected = client._detect_keywords(text)
        assert len(detected) == 0

    def test_parse_date(self, client):
        """날짜 파싱"""
        # RFC 822
        dt = client._parse_date("Mon, 03 Feb 2026 10:30:00 +0000")
        assert dt is not None

        # ISO 8601
        dt = client._parse_date("2026-02-03T10:30:00Z")
        assert dt is not None

        # Invalid
        dt = client._parse_date("invalid date")
        assert dt is None

    @pytest.mark.asyncio
    async def test_fetch_data_empty(self, client):
        """알림 없을 때 fetch"""
        with patch.object(client, 'fetch_alerts', new_callable=AsyncMock) as mock_alerts:
            mock_alerts.return_value = []
            result = await client.fetch_data()

            assert len(result) > 0
            risk_score = next((p for p in result if p.indicator == "political_risk_score"), None)
            assert risk_score is not None
            assert risk_score.value == 10.0  # 기본 낮은 리스크
            assert risk_score.metadata["risk_level"] == "low"

    @pytest.mark.asyncio
    async def test_get_summary_mock(self, client):
        """요약 조회 (mock)"""
        with patch.object(client, 'fetch_data', new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = []
            result = await client.get_summary()
            assert "risk_score" in result
            assert "risk_level" in result
            assert "alert_count" in result

    @pytest.mark.asyncio
    async def test_close(self, client):
        """세션 종료"""
        await client.close()
