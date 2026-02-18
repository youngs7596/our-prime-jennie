#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shared/macro_data/clients/political_news_client.py
--------------------------------------------------
정치/지정학적 뉴스 키워드 모니터링 클라이언트.

글로벌 정치 뉴스 RSS 피드에서 시장 영향력 있는 키워드를 감지하고
알림을 생성합니다.

모니터링 대상:
- 미국 대통령/행정부 발언 (Trump, Biden 등)
- 연준 관련 (Fed chair, Powell, FOMC, rate decision)
- 무역/관세 (tariff, sanction, trade war)
- 지정학적 리스크 (war, conflict, crisis)
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Set
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


@dataclass
class PoliticalAlert:
    """정치 뉴스 알림"""
    keyword: str              # 매칭된 키워드
    category: str             # 카테고리 (fed, trade, geopolitical, etc.)
    severity: str             # 심각도 (critical, high, medium, low)
    title: str                # 뉴스 제목
    source: str               # 출처
    published_at: datetime    # 발행 시간
    url: str = ""            # 뉴스 URL
    impact_direction: str = "unknown"  # bullish, bearish, unknown

    def to_dict(self) -> Dict[str, Any]:
        return {
            "keyword": self.keyword,
            "category": self.category,
            "severity": self.severity,
            "title": self.title,
            "source": self.source,
            "published_at": self.published_at.isoformat(),
            "url": self.url,
            "impact_direction": self.impact_direction,
        }


class PoliticalNewsClient(MacroDataClient):
    """
    정치/지정학적 뉴스 키워드 모니터링 클라이언트.

    Usage:
        client = PoliticalNewsClient()
        alerts = await client.fetch_alerts()
        data = await client.fetch_data(["political_risk_score"])
    """

    SOURCE_NAME = "political_news"

    # 글로벌 정치/경제 뉴스 RSS 피드
    RSS_FEEDS = {
        "reuters_world": {
            "url": "https://feeds.reuters.com/reuters/worldNews",
            "name": "Reuters World",
            "category": "world",
        },
        "reuters_business": {
            "url": "https://feeds.reuters.com/reuters/businessNews",
            "name": "Reuters Business",
            "category": "business",
        },
        "bbc_world": {
            "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
            "name": "BBC World",
            "category": "world",
        },
        "bbc_business": {
            "url": "https://feeds.bbci.co.uk/news/business/rss.xml",
            "name": "BBC Business",
            "category": "business",
        },
        "nyt_world": {
            "url": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
            "name": "NYT World",
            "category": "world",
        },
        "wsj_world": {
            "url": "https://feeds.a.dj.com/rss/RSSWorldNews.xml",
            "name": "WSJ World",
            "category": "world",
        },
        # 한국 시장 영향 뉴스
        "yonhap_world": {
            "url": "https://www.yna.co.kr/rss/international.xml",
            "name": "연합뉴스 국제",
            "category": "world",
        },
    }

    # 키워드 카테고리 및 심각도 정의
    KEYWORD_CONFIG = {
        # 연준 관련 (Critical - 시장 직접 영향)
        "fed": {
            "keywords": [
                "fed chair", "federal reserve", "fomc", "powell",
                "rate decision", "rate hike", "rate cut", "interest rate",
                "quantitative tightening", "quantitative easing",
                "연준", "파월", "금리 인상", "금리 인하", "기준금리",
            ],
            "severity": "critical",
            "impact_direction_hints": {
                "rate cut": "bullish",
                "rate hike": "bearish",
                "hawkish": "bearish",
                "dovish": "bullish",
                "금리 인하": "bullish",
                "금리 인상": "bearish",
            }
        },
        # 미국 행정부 (Medium - 일반 정치 뉴스 가중치 축소)
        "us_politics": {
            "keywords": [
                "white house", "executive order", "행정명령", "백악관",
                "treasury secretary", "commerce secretary",
                "presidential", "congress", "senate",
                "정부 정책", "대통령령",
            ],
            "severity": "medium",
            "impact_direction_hints": {
                "executive order": "bearish",
                "행정명령": "bearish",
                "bipartisan": "bullish",
            }
        },
        # 미국 무역/관세 정책 (Critical - 한국 직접 영향)
        "us_trade_policy": {
            "keywords": [
                "trump tariff", "trump sanction", "trump trade",
                "biden tariff", "biden sanction",
                "section 301", "section 232",
                "chips act", "ira", "inflation reduction act",
                "한미 무역", "대한 관세", "korea tariff",
            ],
            "severity": "critical",
            "impact_direction_hints": {
                "exemption": "bullish", "면제": "bullish",
                "tariff increase": "bearish", "관세 인상": "bearish",
            }
        },
        # 무역/관세 일반 (Critical - 한국 수출 영향)
        "trade": {
            "keywords": [
                "tariff", "trade war", "trade deal", "sanction",
                "export ban", "import restriction", "trade agreement",
                "관세", "무역 전쟁", "무역 협상", "제재", "수출 규제",
                "반도체 수출", "chip war", "semiconductor sanction",
            ],
            "severity": "critical",
            "impact_direction_hints": {
                "trade deal": "bullish",
                "무역 협상 타결": "bullish",
                "tariff increase": "bearish",
                "관세 인상": "bearish",
                "sanction": "bearish",
                "제재": "bearish",
            }
        },
        # 지정학적 리스크 (High) — 복합 키워드만 (단독 "war" 등 제거)
        "geopolitical": {
            "keywords": [
                "military conflict", "armed conflict", "invasion",
                "missile launch", "nuclear test", "crisis escalat",
                "north korea missile", "north korea nuclear",
                "china taiwan conflict", "china taiwan tension",
                "russia ukraine", "middle east conflict", "iran israel",
                "군사 충돌", "미사일 발사", "핵실험",
                "침공", "긴장 고조", "북한 도발", "대만 해협",
            ],
            "severity": "high",
            "impact_direction_hints": {
                "peace": "bullish", "ceasefire": "bullish",
                "peace deal": "bullish", "de-escalat": "bullish",
                "평화": "bullish", "휴전": "bullish",
                "military conflict": "bearish", "invasion": "bearish",
                "missile launch": "bearish", "nuclear test": "bearish",
                "전쟁": "bearish", "침공": "bearish", "미사일 발사": "bearish",
            }
        },
        # 중앙은행 관련 (Medium)
        "central_banks": {
            "keywords": [
                "ecb", "boj", "pboc", "bank of england",
                "european central bank", "bank of japan",
                "한국은행", "금통위", "기준금리 결정",
            ],
            "severity": "medium",
            "impact_direction_hints": {}
        },
        # 경제 위기 시그널 (Critical) — 복합 키워드만 (단독 "recession" 등 제거)
        "crisis": {
            "keywords": [
                "recession warning", "recession risk", "economic depression",
                "market crash", "financial collapse", "sovereign default",
                "bank bankruptcy", "bailout package", "market meltdown",
                "systemic risk", "credit crisis",
                "경기 침체 경고", "금융 위기", "시장 폭락",
                "디폴트 선언", "은행 파산", "구제금융",
            ],
            "severity": "critical",
            "impact_direction_hints": {
                "recovery": "bullish", "회복": "bullish",
                "recession": "bearish", "crash": "bearish",
                "collapse": "bearish", "침체": "bearish", "폭락": "bearish",
            }
        },
    }

    def __init__(self, config: Optional[ClientConfig] = None):
        """클라이언트 초기화"""
        self.config = config or ClientConfig(
            timeout=15,
            max_retries=2,
            retry_delay=0.5
        )
        self._session: Optional[aiohttp.ClientSession] = None
        self._rate_limiter = get_rate_limiter()
        self._cache = get_macro_cache()

        # 전체 키워드 셋 (빠른 검색용)
        self._all_keywords: Set[str] = set()
        for category_config in self.KEYWORD_CONFIG.values():
            self._all_keywords.update(
                kw.lower() for kw in category_config["keywords"]
            )

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
        """Rate limit: (20/min, 5000/day)"""
        return (20, 5000)

    def get_source_name(self) -> str:
        return self.SOURCE_NAME

    def get_default_indicators(self) -> List[str]:
        return ["political_risk_score", "political_alert_count"]

    def is_available(self) -> bool:
        """항상 사용 가능"""
        return True

    def _parse_rss(self, xml_content: str, feed_info: Dict[str, str]) -> List[NewsItem]:
        """RSS XML 파싱"""
        news_items = []

        try:
            root = ET.fromstring(xml_content)
            items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")

            for item in items[:30]:  # 최대 30개
                try:
                    title = item.findtext("title") or ""
                    link = item.findtext("link") or ""
                    pub_date = item.findtext("pubDate") or ""
                    description = item.findtext("description") or ""

                    # Atom 형식
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

                    # HTML 태그 제거
                    title = unescape(re.sub(r"<[^>]+>", "", title)).strip()
                    description = unescape(re.sub(r"<[^>]+>", "", description)).strip()

                    published_at = self._parse_date(pub_date)

                    if title and published_at:
                        news_items.append(NewsItem(
                            title=title,
                            source=feed_info["name"],
                            published_at=published_at,
                            url=link,
                            summary=description[:300] if description else "",
                            keywords=[feed_info["category"]],
                        ))

                except Exception as e:
                    logger.debug(f"[PoliticalNews] Item parse error: {e}")
                    continue

        except ET.ParseError as e:
            logger.error(f"[PoliticalNews] XML parse error: {e}")

        return news_items

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """날짜 파싱"""
        if not date_str:
            return None

        date_str = date_str.strip()

        formats = [
            "%a, %d %b %Y %H:%M:%S %z",
            "%a, %d %b %Y %H:%M:%S %Z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                return dt
            except ValueError:
                continue

        # +0000 형식 처리
        try:
            if "+" in date_str or "-" in date_str[-6:]:
                # "Mon, 03 Feb 2026 10:30:00 +0000"
                dt = datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S %z")
                return dt
        except ValueError:
            pass

        logger.debug(f"[PoliticalNews] Cannot parse date: {date_str}")
        return None

    def _detect_keywords(self, text: str) -> List[Tuple[str, str, str, str]]:
        """
        텍스트에서 키워드 감지.

        짧은 영문 키워드(5자 이하, ASCII)는 word boundary(\b)를 적용하여
        부분 매칭을 방지합니다. 예: "war"가 "award"에 매칭되는 것을 방지.

        Returns:
            List of (keyword, category, severity, impact_direction)
        """
        text_lower = text.lower()
        detected = []

        for category, config in self.KEYWORD_CONFIG.items():
            for keyword in config["keywords"]:
                kw_lower = keyword.lower()

                # 짧은 ASCII 키워드는 word boundary 적용
                if len(kw_lower) <= 5 and kw_lower.isascii():
                    if not re.search(r'\b' + re.escape(kw_lower) + r'\b', text_lower):
                        continue
                else:
                    if kw_lower not in text_lower:
                        continue

                # 영향 방향 결정
                impact = "unknown"
                for hint_kw, direction in config.get("impact_direction_hints", {}).items():
                    if hint_kw.lower() in text_lower:
                        impact = direction
                        break

                detected.append((
                    keyword,
                    category,
                    config["severity"],
                    impact
                ))

        return detected

    async def _fetch_feed(self, feed_key: str) -> List[NewsItem]:
        """단일 RSS 피드 수집"""
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
                                f"[PoliticalNews] {feed_key} failed: {response.status}"
                            )

            except asyncio.TimeoutError:
                logger.warning(f"[PoliticalNews] {feed_key} timeout")
            except aiohttp.ClientError as e:
                logger.warning(f"[PoliticalNews] {feed_key} error: {e}")

            if attempt < self.config.max_retries - 1:
                await asyncio.sleep(self.config.retry_delay)

        return []

    async def fetch_alerts(
        self,
        max_age_hours: int = 48,
        min_severity: str = "medium"
    ) -> List[PoliticalAlert]:
        """
        정치 뉴스 알림 수집.

        Args:
            max_age_hours: 최대 뉴스 연령 (시간)
            min_severity: 최소 심각도 (critical, high, medium, low)

        Returns:
            PoliticalAlert 리스트 (최신순)
        """
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        min_severity_level = severity_order.get(min_severity, 2)

        # 캐시 확인
        cache_key = f"{self.SOURCE_NAME}_alerts"
        cached = self._cache.get_news(cache_key)
        if cached:
            alerts = [
                PoliticalAlert(
                    keyword=a["keyword"],
                    category=a["category"],
                    severity=a["severity"],
                    title=a["title"],
                    source=a["source"],
                    published_at=datetime.fromisoformat(a["published_at"]),
                    url=a.get("url", ""),
                    impact_direction=a.get("impact_direction", "unknown"),
                )
                for a in cached
                if datetime.fromisoformat(a["published_at"]) >
                   datetime.now(UTC) - timedelta(hours=max_age_hours)
            ]
            if alerts:
                return [
                    a for a in alerts
                    if severity_order.get(a.severity, 3) <= min_severity_level
                ]

        # 모든 피드에서 뉴스 수집
        all_news: List[NewsItem] = []
        tasks = [self._fetch_feed(feed_key) for feed_key in self.RSS_FEEDS.keys()]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        cutoff_time = datetime.now(UTC) - timedelta(hours=max_age_hours)

        for result in results:
            if isinstance(result, Exception):
                logger.error(f"[PoliticalNews] Feed error: {result}")
                continue

            for news in result:
                if news.published_at.astimezone(UTC) > cutoff_time:
                    all_news.append(news)

        # 키워드 감지 및 알림 생성
        alerts: List[PoliticalAlert] = []
        seen_titles: Set[str] = set()  # 중복 제거

        for news in all_news:
            if news.title in seen_titles:
                continue
            seen_titles.add(news.title)

            # 제목 + 요약에서 키워드 감지
            full_text = f"{news.title} {news.summary}"
            detected = self._detect_keywords(full_text)

            for keyword, category, severity, impact in detected:
                if severity_order.get(severity, 3) <= min_severity_level:
                    alerts.append(PoliticalAlert(
                        keyword=keyword,
                        category=category,
                        severity=severity,
                        title=news.title,
                        source=news.source,
                        published_at=news.published_at,
                        url=news.url,
                        impact_direction=impact,
                    ))

        # 심각도/시간 순 정렬
        alerts.sort(key=lambda x: (
            severity_order.get(x.severity, 3),
            -x.published_at.timestamp()
        ))

        # 중복 제거 (같은 제목의 다른 키워드 알림은 가장 심각한 것만)
        unique_alerts: List[PoliticalAlert] = []
        seen_alert_titles: Set[str] = set()
        for alert in alerts:
            if alert.title not in seen_alert_titles:
                unique_alerts.append(alert)
                seen_alert_titles.add(alert.title)

        # 캐시 저장
        if unique_alerts:
            self._cache.set_news(
                cache_key,
                [a.to_dict() for a in unique_alerts[:100]]
            )

        logger.info(
            f"[PoliticalNews] Detected {len(unique_alerts)} political alerts "
            f"(critical: {sum(1 for a in unique_alerts if a.severity == 'critical')}, "
            f"high: {sum(1 for a in unique_alerts if a.severity == 'high')})"
        )

        return unique_alerts

    async def fetch_data(
        self,
        indicators: Optional[List[str]] = None
    ) -> List[MacroDataPoint]:
        """
        정치 리스크 지표 수집.

        Returns:
            MacroDataPoint 리스트:
            - political_risk_score: 0-100 (높을수록 위험)
            - political_alert_count: 활성 알림 수
        """
        indicators = indicators or self.get_default_indicators()
        results: List[MacroDataPoint] = []

        # 알림 수집
        alerts = await self.fetch_alerts(max_age_hours=24, min_severity="medium")

        if not alerts:
            # 알림 없음 = 낮은 리스크
            now = datetime.now(KST)

            if "political_risk_score" in indicators:
                results.append(MacroDataPoint(
                    indicator="political_risk_score",
                    value=10.0,  # 기본 낮은 리스크
                    timestamp=now,
                    source=self.SOURCE_NAME,
                    category=IndicatorCategory.SENTIMENT,
                    metadata={
                        "alert_count": 0,
                        "critical_count": 0,
                        "high_count": 0,
                        "risk_level": "low",
                    }
                ))

            if "political_alert_count" in indicators:
                results.append(MacroDataPoint(
                    indicator="political_alert_count",
                    value=0.0,
                    timestamp=now,
                    source=self.SOURCE_NAME,
                    category=IndicatorCategory.SENTIMENT,
                ))

            return results

        # 리스크 점수 계산
        severity_weights = {"critical": 30, "high": 15, "medium": 5, "low": 2}

        total_weight = 0
        critical_count = 0
        high_count = 0
        bearish_count = 0

        # 최근 24시간 알림 분석
        recent_alerts = [
            a for a in alerts
            if a.published_at.astimezone(UTC) > datetime.now(UTC) - timedelta(hours=24)
        ]

        for alert in recent_alerts:
            total_weight += severity_weights.get(alert.severity, 0)

            if alert.severity == "critical":
                critical_count += 1
            elif alert.severity == "high":
                high_count += 1

            if alert.impact_direction == "bearish":
                bearish_count += 1

        # 점수 계산 (0-100, 최대 100)
        risk_score = min(total_weight, 100)

        # 리스크 레벨 결정
        if risk_score >= 70 or critical_count >= 2:
            risk_level = "critical"
        elif risk_score >= 50 or critical_count >= 1:
            risk_level = "high"
        elif risk_score >= 30:
            risk_level = "medium"
        else:
            risk_level = "low"

        now = datetime.now(KST)

        if "political_risk_score" in indicators:
            # 카테고리별 알림 수
            category_counts = {}
            for alert in recent_alerts:
                category_counts[alert.category] = category_counts.get(alert.category, 0) + 1

            results.append(MacroDataPoint(
                indicator="political_risk_score",
                value=float(risk_score),
                timestamp=now,
                source=self.SOURCE_NAME,
                category=IndicatorCategory.SENTIMENT,
                metadata={
                    "alert_count": len(recent_alerts),
                    "critical_count": critical_count,
                    "high_count": high_count,
                    "bearish_count": bearish_count,
                    "risk_level": risk_level,
                    "category_counts": category_counts,
                    "top_alerts": [
                        {
                            "title": a.title[:100],
                            "category": a.category,
                            "severity": a.severity,
                            "keyword": a.keyword,
                        }
                        for a in recent_alerts[:5]
                    ],
                }
            ))

            self._cache.set_data_point(
                self.SOURCE_NAME, "political_risk_score", results[-1]
            )

        if "political_alert_count" in indicators:
            results.append(MacroDataPoint(
                indicator="political_alert_count",
                value=float(len(recent_alerts)),
                timestamp=now,
                source=self.SOURCE_NAME,
                category=IndicatorCategory.SENTIMENT,
            ))

        self._cache.set_last_fetch(self.SOURCE_NAME)
        logger.info(
            f"[PoliticalNews] Risk score: {risk_score}, level: {risk_level}, "
            f"alerts: {len(recent_alerts)}"
        )

        return results

    async def get_summary(self) -> Dict[str, Any]:
        """
        정치 리스크 요약 조회.

        Returns:
            요약 딕셔너리
        """
        data = await self.fetch_data(["political_risk_score"])

        if not data:
            return {
                "risk_score": 10,
                "risk_level": "low",
                "alert_count": 0,
                "top_alerts": [],
            }

        point = data[0]
        return {
            "risk_score": int(point.value),
            "risk_level": point.metadata.get("risk_level", "low"),
            "alert_count": point.metadata.get("alert_count", 0),
            "critical_count": point.metadata.get("critical_count", 0),
            "high_count": point.metadata.get("high_count", 0),
            "bearish_count": point.metadata.get("bearish_count", 0),
            "category_counts": point.metadata.get("category_counts", {}),
            "top_alerts": point.metadata.get("top_alerts", []),
        }
