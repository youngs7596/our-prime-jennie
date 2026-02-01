#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shared/macro_data/clients/rss_news_client.py
--------------------------------------------
RSS 뉴스 수집 클라이언트.

한국 경제뉴스 RSS 피드에서 뉴스를 수집하고
간단한 센티먼트 분석을 수행합니다.

소스:
- 매일경제 (mk.co.kr)
- 한국경제 (hankyung.com)
- 연합뉴스 (yna.co.kr)
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET
from html import unescape

import aiohttp

from ..models import MacroDataPoint, NewsItem, IndicatorCategory
from ..rate_limiter import get_rate_limiter
from ..cache import get_macro_cache
from .base import MacroDataClient, ClientConfig

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
UTC = ZoneInfo("UTC")


class RSSNewsClient(MacroDataClient):
    """
    RSS 뉴스 수집 클라이언트.

    제공 데이터:
    - 한국 경제뉴스 수집
    - 키워드 기반 간단한 센티먼트 분석
    - 주요 테마 추출

    Usage:
        client = RSSNewsClient()
        news = await client.fetch_news()
        sentiment = await client.fetch_data(["korea_news_sentiment"])
    """

    SOURCE_NAME = "rss"

    # RSS 피드 URL 목록
    RSS_FEEDS = {
        "mk_economy": {
            "url": "https://www.mk.co.kr/rss/30100041/",
            "name": "매일경제 경제",
            "category": "economy",
        },
        "mk_stock": {
            "url": "https://www.mk.co.kr/rss/30100030/",
            "name": "매일경제 증권",
            "category": "stock",
        },
        "hankyung_economy": {
            "url": "https://www.hankyung.com/feed/economy",
            "name": "한국경제 경제",
            "category": "economy",
        },
        "hankyung_stock": {
            "url": "https://www.hankyung.com/feed/stock",
            "name": "한국경제 증권",
            "category": "stock",
        },
        "yna_economy": {
            "url": "https://www.yna.co.kr/rss/economy.xml",
            "name": "연합뉴스 경제",
            "category": "economy",
        },
    }

    # 센티먼트 키워드 (간단한 규칙 기반)
    POSITIVE_KEYWORDS = [
        "상승", "급등", "최고", "호재", "성장", "기대", "회복", "반등",
        "상향", "호실적", "흑자", "호황", "강세", "사상최고", "돌파",
        "수출증가", "경기회복", "취업증가", "실적개선", "금리인하",
    ]

    NEGATIVE_KEYWORDS = [
        "하락", "급락", "폭락", "악재", "우려", "위기", "충격", "약세",
        "하향", "적자", "불황", "침체", "불안", "리스크", "위험",
        "수출감소", "경기침체", "실업증가", "실적악화", "금리인상",
    ]

    def __init__(self, config: Optional[ClientConfig] = None):
        """
        클라이언트 초기화.

        Args:
            config: 클라이언트 설정
        """
        self.config = config or ClientConfig(
            timeout=15,
            max_retries=2,
            retry_delay=0.5
        )
        self._session: Optional[aiohttp.ClientSession] = None
        self._rate_limiter = get_rate_limiter()
        self._cache = get_macro_cache()

    async def _get_session(self) -> aiohttp.ClientSession:
        """aiohttp 세션 반환"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.config.timeout),
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; MacroDataBot/1.0)",
                }
            )
        return self._session

    async def close(self) -> None:
        """세션 종료"""
        if self._session and not self._session.closed:
            await self._session.close()

    def get_rate_limit(self) -> Tuple[int, int]:
        """Rate limit: (30/min, 10000/day)"""
        return (30, 10000)

    def get_source_name(self) -> str:
        return self.SOURCE_NAME

    def get_default_indicators(self) -> List[str]:
        return ["korea_news_sentiment"]

    def is_available(self) -> bool:
        """항상 사용 가능"""
        return True

    def _parse_rss(self, xml_content: str, feed_info: Dict[str, str]) -> List[NewsItem]:
        """
        RSS XML 파싱.

        Args:
            xml_content: RSS XML 문자열
            feed_info: 피드 정보

        Returns:
            NewsItem 리스트
        """
        news_items = []

        try:
            root = ET.fromstring(xml_content)

            # RSS 2.0 또는 Atom 형식 처리
            items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")

            for item in items[:20]:  # 최대 20개
                try:
                    # RSS 2.0
                    title = item.findtext("title") or ""
                    link = item.findtext("link") or ""
                    pub_date = item.findtext("pubDate") or ""
                    description = item.findtext("description") or ""

                    # Atom
                    if not title:
                        title = item.findtext("{http://www.w3.org/2005/Atom}title") or ""
                    if not link:
                        link_elem = item.find("{http://www.w3.org/2005/Atom}link")
                        if link_elem is not None:
                            link = link_elem.get("href", "")
                    if not pub_date:
                        pub_date = item.findtext("{http://www.w3.org/2005/Atom}published") or ""
                        if not pub_date:
                            pub_date = item.findtext("{http://www.w3.org/2005/Atom}updated") or ""

                    # HTML 태그 제거 및 unescape
                    title = unescape(re.sub(r"<[^>]+>", "", title)).strip()
                    description = unescape(re.sub(r"<[^>]+>", "", description)).strip()

                    # 날짜 파싱
                    published_at = self._parse_date(pub_date)

                    if title and published_at:
                        news_items.append(NewsItem(
                            title=title,
                            source=feed_info["name"],
                            published_at=published_at,
                            url=link,
                            summary=description[:200] if description else "",
                            keywords=[feed_info["category"]],
                        ))

                except Exception as e:
                    logger.debug(f"[RSS] Item parse error: {e}")
                    continue

        except ET.ParseError as e:
            logger.error(f"[RSS] XML parse error: {e}")

        return news_items

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """
        다양한 날짜 형식 파싱.

        Args:
            date_str: 날짜 문자열

        Returns:
            datetime 또는 None
        """
        if not date_str:
            return None

        date_str = date_str.strip()

        # 일반적인 RSS 날짜 형식들
        formats = [
            "%a, %d %b %Y %H:%M:%S %z",      # RFC 822
            "%a, %d %b %Y %H:%M:%S %Z",      # RFC 822 with timezone name
            "%Y-%m-%dT%H:%M:%S%z",           # ISO 8601
            "%Y-%m-%dT%H:%M:%SZ",            # ISO 8601 UTC
            "%Y-%m-%d %H:%M:%S",             # Simple
            "%Y-%m-%d",                       # Date only
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=KST)
                return dt
            except ValueError:
                continue

        # +0900 형식 처리
        try:
            # "Wed, 01 Feb 2026 10:30:00 +0900" 형식
            if "+0900" in date_str or "+09:00" in date_str:
                date_str = date_str.replace("+09:00", "+0900")
                dt = datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S %z")
                return dt
        except ValueError:
            pass

        logger.debug(f"[RSS] Cannot parse date: {date_str}")
        return None

    def _analyze_sentiment(self, text: str) -> float:
        """
        간단한 키워드 기반 센티먼트 분석.

        Args:
            text: 분석할 텍스트

        Returns:
            센티먼트 점수 (-1.0 ~ 1.0)
        """
        text_lower = text.lower()

        positive_count = sum(1 for kw in self.POSITIVE_KEYWORDS if kw in text)
        negative_count = sum(1 for kw in self.NEGATIVE_KEYWORDS if kw in text)

        total = positive_count + negative_count
        if total == 0:
            return 0.0

        # -1.0 ~ 1.0 범위로 정규화
        sentiment = (positive_count - negative_count) / total

        return round(sentiment, 3)

    async def _fetch_feed(self, feed_key: str) -> List[NewsItem]:
        """
        단일 RSS 피드 수집.

        Args:
            feed_key: 피드 키

        Returns:
            NewsItem 리스트
        """
        feed_info = self.RSS_FEEDS.get(feed_key)
        if not feed_info:
            return []

        session = await self._get_session()
        url = feed_info["url"]

        for attempt in range(self.config.max_retries):
            try:
                async with self._rate_limiter.acquire(self.SOURCE_NAME):
                    async with session.get(url) as response:
                        if response.status == 200:
                            content = await response.text()
                            return self._parse_rss(content, feed_info)
                        else:
                            logger.warning(
                                f"[RSS] {feed_key} failed: {response.status}"
                            )

            except asyncio.TimeoutError:
                logger.warning(f"[RSS] {feed_key} timeout")
            except aiohttp.ClientError as e:
                logger.warning(f"[RSS] {feed_key} error: {e}")

            if attempt < self.config.max_retries - 1:
                await asyncio.sleep(self.config.retry_delay)

        return []

    async def fetch_news(
        self,
        feeds: Optional[List[str]] = None,
        max_age_hours: int = 24
    ) -> List[NewsItem]:
        """
        여러 RSS 피드에서 뉴스 수집.

        Args:
            feeds: 수집할 피드 키 목록 (None이면 전체)
            max_age_hours: 최대 뉴스 연령 (시간)

        Returns:
            NewsItem 리스트 (최신순)
        """
        # 캐시 확인
        cache_key = f"{self.SOURCE_NAME}_all_news"
        cached = self._cache.get_news(cache_key)
        if cached:
            return [
                NewsItem(
                    title=n["title"],
                    source=n["source"],
                    published_at=datetime.fromisoformat(n["published_at"]),
                    url=n.get("url", ""),
                    summary=n.get("summary", ""),
                    sentiment=n.get("sentiment"),
                    keywords=n.get("keywords", []),
                )
                for n in cached
                if datetime.fromisoformat(n["published_at"]) >
                   datetime.now(UTC) - timedelta(hours=max_age_hours)
            ]

        feeds = feeds or list(self.RSS_FEEDS.keys())
        all_news: List[NewsItem] = []

        # 병렬로 피드 수집
        tasks = [self._fetch_feed(feed_key) for feed_key in feeds]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        cutoff_time = datetime.now(UTC) - timedelta(hours=max_age_hours)

        for result in results:
            if isinstance(result, Exception):
                logger.error(f"[RSS] Feed error: {result}")
                continue

            for news in result:
                # 시간 필터링
                if news.published_at.astimezone(UTC) > cutoff_time:
                    # 센티먼트 분석
                    news.sentiment = self._analyze_sentiment(
                        news.title + " " + news.summary
                    )
                    all_news.append(news)

        # 최신순 정렬
        all_news.sort(key=lambda x: x.published_at, reverse=True)

        # 캐시 저장
        if all_news:
            self._cache.set_news(
                cache_key,
                [n.to_dict() for n in all_news[:50]]  # 최대 50개
            )

        logger.info(f"[RSS] Collected {len(all_news)} news items")

        return all_news

    async def fetch_data(
        self,
        indicators: Optional[List[str]] = None
    ) -> List[MacroDataPoint]:
        """
        뉴스 기반 센티먼트 지표 수집.

        Args:
            indicators: 수집할 지표 목록

        Returns:
            MacroDataPoint 리스트
        """
        indicators = indicators or self.get_default_indicators()
        results: List[MacroDataPoint] = []

        # 뉴스 수집
        news_items = await self.fetch_news(max_age_hours=24)

        if not news_items:
            logger.warning("[RSS] No news items collected")
            return results

        # 전체 센티먼트 계산
        sentiments = [n.sentiment for n in news_items if n.sentiment is not None]
        if sentiments:
            avg_sentiment = sum(sentiments) / len(sentiments)

            # 경제 뉴스만 필터링
            economy_news = [
                n for n in news_items
                if "economy" in n.keywords or "경제" in n.source
            ]
            economy_sentiments = [
                n.sentiment for n in economy_news if n.sentiment is not None
            ]
            economy_sentiment = (
                sum(economy_sentiments) / len(economy_sentiments)
                if economy_sentiments else avg_sentiment
            )

            # 증권 뉴스만 필터링
            stock_news = [
                n for n in news_items
                if "stock" in n.keywords or "증권" in n.source
            ]
            stock_sentiments = [
                n.sentiment for n in stock_news if n.sentiment is not None
            ]
            stock_sentiment = (
                sum(stock_sentiments) / len(stock_sentiments)
                if stock_sentiments else avg_sentiment
            )

            # 지표 생성
            now = datetime.now(KST)

            if "korea_news_sentiment" in indicators:
                results.append(MacroDataPoint(
                    indicator="korea_news_sentiment",
                    value=round(avg_sentiment, 3),
                    timestamp=now,
                    source=self.SOURCE_NAME,
                    category=IndicatorCategory.SENTIMENT,
                    metadata={
                        "news_count": len(news_items),
                        "economy_sentiment": round(economy_sentiment, 3),
                        "stock_sentiment": round(stock_sentiment, 3),
                        "positive_count": sum(1 for s in sentiments if s > 0),
                        "negative_count": sum(1 for s in sentiments if s < 0),
                    }
                ))

                self._cache.set_data_point(
                    self.SOURCE_NAME, "korea_news_sentiment", results[-1]
                )

        self._cache.set_last_fetch(self.SOURCE_NAME)
        logger.info(f"[RSS] Fetched {len(results)} sentiment indicators")

        return results

    async def get_top_headlines(
        self,
        count: int = 10,
        category: Optional[str] = None
    ) -> List[NewsItem]:
        """
        주요 헤드라인 조회.

        Args:
            count: 반환할 뉴스 수
            category: 카테고리 필터 (economy, stock)

        Returns:
            NewsItem 리스트
        """
        news_items = await self.fetch_news(max_age_hours=24)

        if category:
            news_items = [
                n for n in news_items
                if category in n.keywords
            ]

        return news_items[:count]

    async def get_sentiment_summary(self) -> Dict[str, Any]:
        """
        센티먼트 요약 조회.

        Returns:
            센티먼트 요약 딕셔너리
        """
        data = await self.fetch_data(["korea_news_sentiment"])

        if not data:
            return {
                "sentiment": 0.0,
                "label": "neutral",
                "news_count": 0,
            }

        point = data[0]
        sentiment = point.value

        if sentiment > 0.3:
            label = "very_positive"
        elif sentiment > 0.1:
            label = "positive"
        elif sentiment > -0.1:
            label = "neutral"
        elif sentiment > -0.3:
            label = "negative"
        else:
            label = "very_negative"

        return {
            "sentiment": sentiment,
            "label": label,
            "news_count": point.metadata.get("news_count", 0),
            "economy_sentiment": point.metadata.get("economy_sentiment", 0.0),
            "stock_sentiment": point.metadata.get("stock_sentiment", 0.0),
        }
