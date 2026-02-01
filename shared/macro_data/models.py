#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shared/macro_data/models.py
---------------------------
매크로 데이터 모델 정의.

GlobalMacroSnapshot은 여러 소스에서 수집된 글로벌 매크로 데이터를
하나의 통합 스냅샷으로 관리합니다.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, date, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")
UTC = ZoneInfo("UTC")


class DataQuality(Enum):
    """데이터 품질 등급"""
    FRESH = "fresh"          # 1시간 이내
    RECENT = "recent"        # 6시간 이내
    STALE = "stale"          # 24시간 이내
    EXPIRED = "expired"      # 24시간 초과 (사용 금지)


class IndicatorCategory(Enum):
    """지표 카테고리"""
    US_RATES = "us_rates"           # 미국 금리
    US_ECONOMY = "us_economy"       # 미국 경제
    VOLATILITY = "volatility"       # 변동성
    CURRENCY = "currency"           # 환율
    KOREA_RATES = "korea_rates"     # 한국 금리
    KOREA_ECONOMY = "korea_economy" # 한국 경제
    KOREA_MARKET = "korea_market"   # 한국 시장
    SENTIMENT = "sentiment"         # 뉴스 센티먼트


@dataclass
class MacroDataPoint:
    """
    단일 매크로 데이터 포인트.

    Attributes:
        indicator: 지표 이름 (예: "fed_rate", "vix")
        value: 지표 값
        timestamp: 데이터 시점
        source: 데이터 소스 (예: "fred", "finnhub")
        category: 지표 카테고리
        unit: 단위 (예: "%", "USD", "index")
        metadata: 추가 메타데이터
    """
    indicator: str
    value: float
    timestamp: datetime
    source: str
    category: IndicatorCategory = IndicatorCategory.US_ECONOMY
    unit: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def age_hours(self) -> float:
        """데이터 경과 시간 (시간 단위)"""
        now = datetime.now(UTC)
        if self.timestamp.tzinfo is None:
            # naive datetime은 UTC로 가정
            ts = self.timestamp.replace(tzinfo=UTC)
        else:
            ts = self.timestamp.astimezone(UTC)
        return (now - ts).total_seconds() / 3600

    @property
    def quality(self) -> DataQuality:
        """데이터 품질 등급"""
        age = self.age_hours
        if age <= 1:
            return DataQuality.FRESH
        elif age <= 6:
            return DataQuality.RECENT
        elif age <= 24:
            return DataQuality.STALE
        else:
            return DataQuality.EXPIRED

    def is_valid(self, max_age_hours: int = 24) -> bool:
        """유효성 검사 (3현자 권고: 24시간 이상 데이터 필터링)"""
        return self.age_hours <= max_age_hours

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리 변환"""
        return {
            "indicator": self.indicator,
            "value": self.value,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "category": self.category.value,
            "unit": self.unit,
            "age_hours": round(self.age_hours, 2),
            "quality": self.quality.value,
            "metadata": self.metadata,
        }


@dataclass
class EconomicIndicator:
    """경제 지표 정의"""
    name: str
    display_name: str
    category: IndicatorCategory
    unit: str
    description: str = ""
    sources: List[str] = field(default_factory=list)  # 가능한 소스들


@dataclass
class NewsItem:
    """뉴스 아이템"""
    title: str
    source: str
    published_at: datetime
    url: str = ""
    summary: str = ""
    sentiment: Optional[float] = None  # -1.0 ~ 1.0
    keywords: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "source": self.source,
            "published_at": self.published_at.isoformat(),
            "url": self.url,
            "summary": self.summary,
            "sentiment": self.sentiment,
            "keywords": self.keywords,
        }


@dataclass
class GlobalMacroSnapshot:
    """
    글로벌 매크로 스냅샷.

    여러 소스에서 수집된 매크로 데이터를 통합한 스냅샷입니다.
    서비스들은 이 스냅샷을 기반으로 분석을 수행합니다.

    3현자 권고사항:
    - 24시간 이상 지연 데이터 자동 필터링
    - 다중 소스 검증
    - missing_indicators 추적
    """
    snapshot_date: date
    snapshot_time: datetime

    # US Indicators
    fed_rate: Optional[float] = None           # Federal Funds Rate (%)
    us_cpi_yoy: Optional[float] = None         # US CPI YoY (%)
    us_pce_yoy: Optional[float] = None         # US PCE YoY (%)
    treasury_2y: Optional[float] = None        # 2Y Treasury Yield (%)
    treasury_10y: Optional[float] = None       # 10Y Treasury Yield (%)
    treasury_spread: Optional[float] = None    # 10Y - 2Y Spread (%)
    us_unemployment: Optional[float] = None    # US Unemployment Rate (%)
    us_pmi: Optional[float] = None             # US Manufacturing PMI

    # Volatility
    vix: Optional[float] = None                # VIX Index (or VXX ETF proxy)
    vix_regime: str = "normal"                 # low_vol, normal, elevated, crisis

    # US ETFs (Finnhub 무료 티어)
    spy_price: Optional[float] = None          # S&P 500 ETF (SPY)
    qqq_price: Optional[float] = None          # Nasdaq 100 ETF (QQQ)
    ewy_price: Optional[float] = None          # Korea ETF (EWY) - KOSPI proxy

    # Currency
    dxy_index: Optional[float] = None          # Dollar Index
    usd_krw: Optional[float] = None            # USD/KRW
    usd_jpy: Optional[float] = None            # USD/JPY
    usd_cny: Optional[float] = None            # USD/CNY

    # Korea Indicators
    bok_rate: Optional[float] = None           # BOK Base Rate (%)
    korea_cpi_yoy: Optional[float] = None      # Korea CPI YoY (%)
    kospi_index: Optional[float] = None        # KOSPI Index
    kosdaq_index: Optional[float] = None       # KOSDAQ Index
    kospi_change_pct: Optional[float] = None   # KOSPI Daily Change (%)
    kosdaq_change_pct: Optional[float] = None  # KOSDAQ Daily Change (%)

    # Calculated Fields
    rate_differential: Optional[float] = None  # Fed Rate - BOK Rate (%)

    # Sentiment (from news)
    global_news_sentiment: Optional[float] = None  # -1.0 ~ 1.0
    korea_news_sentiment: Optional[float] = None   # -1.0 ~ 1.0

    # Data Quality
    data_sources: List[str] = field(default_factory=list)
    missing_indicators: List[str] = field(default_factory=list)
    stale_indicators: List[str] = field(default_factory=list)
    validation_errors: List[str] = field(default_factory=list)
    data_freshness: float = 0.0  # 0.0 ~ 1.0 (전체 데이터 신선도)

    # Raw data points (for audit)
    raw_data_points: List[MacroDataPoint] = field(default_factory=list)

    def __post_init__(self):
        """Calculate derived fields"""
        # VIX regime classification
        if self.vix is not None:
            if self.vix < 15:
                self.vix_regime = "low_vol"    # Risk-On
            elif self.vix < 25:
                self.vix_regime = "normal"
            elif self.vix < 35:
                self.vix_regime = "elevated"
            else:
                self.vix_regime = "crisis"     # Risk-Off 힌트

        # Rate differential (Fed - BOK)
        if self.fed_rate is not None and self.bok_rate is not None:
            self.rate_differential = self.fed_rate - self.bok_rate

        # Treasury spread
        if self.treasury_10y is not None and self.treasury_2y is not None:
            self.treasury_spread = self.treasury_10y - self.treasury_2y

    @property
    def is_risk_off_environment(self) -> bool:
        """
        Risk-Off 환경 여부 (다중 지표 확인).

        3현자 권고: RISK_OFF 단독 발동 금지
        최소 2개 이상의 지표에서 확인되어야 함.
        """
        risk_off_signals = 0

        # VIX >= 35
        if self.vix is not None and self.vix >= 35:
            risk_off_signals += 1

        # Inverted yield curve
        if self.treasury_spread is not None and self.treasury_spread < -0.5:
            risk_off_signals += 1

        # DXY sharp rise (flight to safety)
        if self.dxy_index is not None and self.dxy_index > 110:
            risk_off_signals += 1

        # Strong negative sentiment
        if self.global_news_sentiment is not None and self.global_news_sentiment < -0.5:
            risk_off_signals += 1

        return risk_off_signals >= 2

    @property
    def krw_pressure_direction(self) -> str:
        """
        원화 압력 방향.

        금리차 기반:
        - diff > 1.5% → krw_weakness (원화 약세 압력)
        - diff < -0.5% → krw_strength (원화 강세 압력)
        """
        if self.rate_differential is None:
            return "neutral"

        if self.rate_differential > 1.5:
            return "krw_weakness"
        elif self.rate_differential < -0.5:
            return "krw_strength"
        else:
            return "neutral"

    def get_completeness_score(self) -> float:
        """
        데이터 완성도 점수 (0.0 ~ 1.0).

        필수 지표 대비 수집된 지표 비율.
        """
        essential_indicators = [
            "fed_rate", "vix", "dxy_index", "usd_krw",
            "bok_rate", "kospi_index", "kosdaq_index",
        ]

        collected = 0
        for indicator in essential_indicators:
            if getattr(self, indicator, None) is not None:
                collected += 1

        return collected / len(essential_indicators)

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리 변환 (DB 저장용)"""
        return {
            "snapshot_date": self.snapshot_date.isoformat(),
            "snapshot_time": self.snapshot_time.isoformat(),
            # US
            "fed_rate": self.fed_rate,
            "us_cpi_yoy": self.us_cpi_yoy,
            "us_pce_yoy": self.us_pce_yoy,
            "treasury_2y": self.treasury_2y,
            "treasury_10y": self.treasury_10y,
            "treasury_spread": self.treasury_spread,
            "us_unemployment": self.us_unemployment,
            "us_pmi": self.us_pmi,
            # Volatility
            "vix": self.vix,
            "vix_regime": self.vix_regime,
            # Currency
            "dxy_index": self.dxy_index,
            "usd_krw": self.usd_krw,
            "usd_jpy": self.usd_jpy,
            "usd_cny": self.usd_cny,
            # Korea
            "bok_rate": self.bok_rate,
            "korea_cpi_yoy": self.korea_cpi_yoy,
            "kospi_index": self.kospi_index,
            "kosdaq_index": self.kosdaq_index,
            "kospi_change_pct": self.kospi_change_pct,
            "kosdaq_change_pct": self.kosdaq_change_pct,
            # Calculated
            "rate_differential": self.rate_differential,
            # Sentiment
            "global_news_sentiment": self.global_news_sentiment,
            "korea_news_sentiment": self.korea_news_sentiment,
            # Quality
            "data_sources": self.data_sources,
            "missing_indicators": self.missing_indicators,
            "stale_indicators": self.stale_indicators,
            "validation_errors": self.validation_errors,
            "data_freshness": self.data_freshness,
            "completeness_score": self.get_completeness_score(),
            "is_risk_off": self.is_risk_off_environment,
            "krw_pressure": self.krw_pressure_direction,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GlobalMacroSnapshot":
        """딕셔너리에서 생성"""
        snapshot_date = data.get("snapshot_date")
        if isinstance(snapshot_date, str):
            snapshot_date = date.fromisoformat(snapshot_date)

        snapshot_time = data.get("snapshot_time")
        if isinstance(snapshot_time, str):
            snapshot_time = datetime.fromisoformat(snapshot_time)

        return cls(
            snapshot_date=snapshot_date,
            snapshot_time=snapshot_time,
            fed_rate=data.get("fed_rate"),
            us_cpi_yoy=data.get("us_cpi_yoy"),
            us_pce_yoy=data.get("us_pce_yoy"),
            treasury_2y=data.get("treasury_2y"),
            treasury_10y=data.get("treasury_10y"),
            treasury_spread=data.get("treasury_spread"),
            us_unemployment=data.get("us_unemployment"),
            us_pmi=data.get("us_pmi"),
            vix=data.get("vix"),
            vix_regime=data.get("vix_regime", "normal"),
            dxy_index=data.get("dxy_index"),
            usd_krw=data.get("usd_krw"),
            usd_jpy=data.get("usd_jpy"),
            usd_cny=data.get("usd_cny"),
            bok_rate=data.get("bok_rate"),
            korea_cpi_yoy=data.get("korea_cpi_yoy"),
            kospi_index=data.get("kospi_index"),
            kosdaq_index=data.get("kosdaq_index"),
            kospi_change_pct=data.get("kospi_change_pct"),
            kosdaq_change_pct=data.get("kosdaq_change_pct"),
            rate_differential=data.get("rate_differential"),
            global_news_sentiment=data.get("global_news_sentiment"),
            korea_news_sentiment=data.get("korea_news_sentiment"),
            data_sources=data.get("data_sources", []),
            missing_indicators=data.get("missing_indicators", []),
            stale_indicators=data.get("stale_indicators", []),
            validation_errors=data.get("validation_errors", []),
            data_freshness=data.get("data_freshness", 0.0),
        )

    def to_llm_context(self) -> str:
        """
        LLM 분석용 컨텍스트 문자열 생성.

        Returns:
            LLM 프롬프트에 포함할 데이터 요약
        """
        lines = [
            "=== Global Macro Snapshot ===",
            f"Date: {self.snapshot_date}",
            f"Time: {self.snapshot_time.strftime('%Y-%m-%d %H:%M %Z')}",
            "",
            "# US Economy",
        ]

        if self.fed_rate is not None:
            lines.append(f"- Fed Funds Rate: {self.fed_rate:.2f}%")
        if self.us_cpi_yoy is not None:
            lines.append(f"- US CPI YoY: {self.us_cpi_yoy:.1f}%")
        if self.treasury_10y is not None:
            lines.append(f"- 10Y Treasury: {self.treasury_10y:.2f}%")
        if self.treasury_spread is not None:
            lines.append(f"- 10Y-2Y Spread: {self.treasury_spread:.2f}%")
        if self.us_unemployment is not None:
            lines.append(f"- Unemployment: {self.us_unemployment:.1f}%")

        lines.append("")
        lines.append("# Volatility & Risk")

        if self.vix is not None:
            lines.append(f"- VIX: {self.vix:.1f} (regime: {self.vix_regime})")
        if self.is_risk_off_environment:
            lines.append("- WARNING: Risk-Off environment detected")

        lines.append("")
        lines.append("# Currency")

        if self.dxy_index is not None:
            lines.append(f"- DXY Index: {self.dxy_index:.1f}")
        if self.usd_krw is not None:
            lines.append(f"- USD/KRW: {self.usd_krw:.1f}")
            lines.append(f"  (pressure: {self.krw_pressure_direction})")

        lines.append("")
        lines.append("# Korea")

        if self.bok_rate is not None:
            lines.append(f"- BOK Base Rate: {self.bok_rate:.2f}%")
        if self.rate_differential is not None:
            lines.append(f"- Rate Differential (Fed-BOK): {self.rate_differential:.2f}%")
        if self.kospi_index is not None:
            change = f" ({self.kospi_change_pct:+.2f}%)" if self.kospi_change_pct else ""
            lines.append(f"- KOSPI: {self.kospi_index:.2f}{change}")
        if self.kosdaq_index is not None:
            change = f" ({self.kosdaq_change_pct:+.2f}%)" if self.kosdaq_change_pct else ""
            lines.append(f"- KOSDAQ: {self.kosdaq_index:.2f}{change}")

        lines.append("")
        lines.append("# Sentiment")

        if self.global_news_sentiment is not None:
            lines.append(f"- Global News: {self.global_news_sentiment:+.2f}")
        if self.korea_news_sentiment is not None:
            lines.append(f"- Korea News: {self.korea_news_sentiment:+.2f}")

        lines.append("")
        lines.append("# Data Quality")
        lines.append(f"- Completeness: {self.get_completeness_score():.0%}")
        lines.append(f"- Sources: {', '.join(self.data_sources) or 'N/A'}")

        if self.missing_indicators:
            lines.append(f"- Missing: {', '.join(self.missing_indicators)}")
        if self.stale_indicators:
            lines.append(f"- Stale (>24h): {', '.join(self.stale_indicators)}")

        return "\n".join(lines)
