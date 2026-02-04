#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shared/macro_data/validator.py
------------------------------
데이터 검증 모듈.

3현자 Council 권고사항:
- 24시간 이상 지연 데이터 자동 필터링
- 다중 소스 검증 (최소 2개 소스)
- 필수 지표 누락 경고
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

from .models import MacroDataPoint, GlobalMacroSnapshot, DataQuality

logger = logging.getLogger(__name__)

UTC = ZoneInfo("UTC")
KST = ZoneInfo("Asia/Seoul")


@dataclass
class ValidationResult:
    """검증 결과"""
    is_valid: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    filtered_indicators: List[str] = field(default_factory=list)  # 필터링된 지표
    stale_indicators: List[str] = field(default_factory=list)     # 오래된 지표
    missing_indicators: List[str] = field(default_factory=list)   # 누락된 지표

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "filtered_indicators": self.filtered_indicators,
            "stale_indicators": self.stale_indicators,
            "missing_indicators": self.missing_indicators,
        }


@dataclass
class ValidatorConfig:
    """검증 설정"""
    # 기본 최대 데이터 연령 (시간) - 3현자 권고: 24시간
    max_age_hours: int = 24

    # 경고 데이터 연령 (시간)
    warning_age_hours: int = 6

    # 지표별 최대 데이터 연령 (주말/공휴일 고려)
    # - 시장 데이터: 72시간 (금요일 → 월요일)
    # - 월간 지표: 45일 (월간 발표)
    # - 분기 지표: 120일 (분기 발표)
    indicator_max_age: Dict[str, int] = field(default_factory=lambda: {
        # 시장 데이터 (주말 고려: 72시간)
        "spy": 72,
        "qqq": 72,
        "vxx": 72,
        "ewy": 72,
        "vix": 72,
        "kospi_index": 72,
        "kosdaq_index": 72,
        "usd_krw": 72,
        "usd_krw_bok": 72,
        # 일간 경제지표 (주말 고려: 96시간)
        "fed_rate": 96,
        "treasury_10y": 96,
        "treasury_2y": 96,
        "bok_rate": 96,
        # 월간 지표 (65일 - 발표 지연 고려)
        "us_cpi_yoy": 65 * 24,
        "us_pce_yoy": 65 * 24,
        "us_unemployment": 65 * 24,
        "korea_cpi_yoy": 65 * 24,
        # 뉴스 감성 (실시간)
        "korea_news_sentiment": 6,
        "global_news_sentiment": 6,
    })

    # 필수 지표 (하나라도 없으면 경고)
    required_indicators: List[str] = field(default_factory=lambda: [
        "fed_rate", "vix", "usd_krw",
        "bok_rate", "kospi_index", "kosdaq_index"
    ])

    # 다중 소스 검증 필요 지표 (3현자 권고)
    multi_source_indicators: List[str] = field(default_factory=lambda: [
        "usd_krw", "vix"
    ])

    # 값 범위 검증
    value_ranges: Dict[str, Tuple[float, float]] = field(default_factory=lambda: {
        "fed_rate": (0, 20),
        "bok_rate": (0, 15),
        "vix": (5, 100),
        "vxx": (10, 200),  # VXX ETF
        "usd_krw": (900, 1800),
        "kospi_index": (1500, 6000),  # Updated: KOSPI reached 5000+ level
        "kosdaq_index": (400, 1500),
        "us_cpi_yoy": (-5, 20),
        "korea_cpi_yoy": (-5, 20),
        "spy": (100, 1000),  # SPY ETF
        "qqq": (100, 1000),  # QQQ ETF
        "ewy": (20, 200),    # EWY ETF
    })


class DataValidator:
    """
    데이터 검증기.

    수집된 매크로 데이터의 유효성을 검증합니다.

    Usage:
        validator = DataValidator()
        result = validator.validate(data_points)
        if not result.is_valid:
            logger.warning(f"Validation errors: {result.errors}")
    """

    def __init__(self, config: Optional[ValidatorConfig] = None):
        """
        검증기 초기화.

        Args:
            config: 검증 설정
        """
        self.config = config or ValidatorConfig()

    def validate_data_point(
        self,
        point: MacroDataPoint
    ) -> Tuple[bool, List[str]]:
        """
        단일 데이터 포인트 검증.

        Args:
            point: 검증할 데이터 포인트

        Returns:
            (유효 여부, 오류 메시지 리스트)
        """
        errors = []

        # 1. 데이터 연령 검증 (지표별 max_age 적용)
        indicator_max_age = self.config.indicator_max_age.get(
            point.indicator,
            self.config.max_age_hours  # 기본값
        )
        if not point.is_valid(max_age_hours=indicator_max_age):
            errors.append(
                f"{point.indicator}: data too old ({point.age_hours:.1f}h > {indicator_max_age}h)"
            )

        # 2. 값 범위 검증
        if point.indicator in self.config.value_ranges:
            min_val, max_val = self.config.value_ranges[point.indicator]
            if not (min_val <= point.value <= max_val):
                errors.append(
                    f"{point.indicator}: value {point.value} out of range [{min_val}, {max_val}]"
                )

        # 3. 타임스탬프 검증 (미래 시간 불가)
        now = datetime.now(UTC)
        if point.timestamp.tzinfo:
            point_time = point.timestamp.astimezone(UTC)
        else:
            point_time = point.timestamp.replace(tzinfo=UTC)

        if point_time > now + timedelta(hours=1):
            errors.append(
                f"{point.indicator}: timestamp in future ({point.timestamp})"
            )

        return len(errors) == 0, errors

    def validate(
        self,
        data_points: List[MacroDataPoint]
    ) -> ValidationResult:
        """
        데이터 포인트 리스트 검증.

        Args:
            data_points: 검증할 데이터 포인트 리스트

        Returns:
            ValidationResult
        """
        result = ValidationResult()

        # 지표별로 그룹핑
        indicator_points: Dict[str, List[MacroDataPoint]] = {}
        for point in data_points:
            if point.indicator not in indicator_points:
                indicator_points[point.indicator] = []
            indicator_points[point.indicator].append(point)

        # 1. 각 데이터 포인트 검증
        valid_points: List[MacroDataPoint] = []
        for point in data_points:
            is_valid, errors = self.validate_data_point(point)

            if not is_valid:
                result.filtered_indicators.append(point.indicator)
                for error in errors:
                    if "too old" in error:
                        result.stale_indicators.append(point.indicator)
                    else:
                        result.errors.append(error)
            else:
                valid_points.append(point)

                # 경고 연령 체크
                if point.age_hours > self.config.warning_age_hours:
                    result.warnings.append(
                        f"{point.indicator}: data is {point.age_hours:.1f}h old"
                    )

        # 2. 필수 지표 누락 검증
        collected_indicators = set(indicator_points.keys())
        for required in self.config.required_indicators:
            if required not in collected_indicators:
                result.missing_indicators.append(required)
                result.warnings.append(
                    f"Required indicator missing: {required}"
                )

        # 3. 다중 소스 검증 (3현자 권고)
        for indicator in self.config.multi_source_indicators:
            if indicator in indicator_points:
                sources = set(p.source for p in indicator_points[indicator])
                if len(sources) < 2:
                    result.warnings.append(
                        f"{indicator}: only 1 source ({list(sources)[0]}), "
                        "recommend multiple sources for verification"
                    )

        # 최종 유효성 판단
        # 필수 지표 중 50% 이상 누락되면 무효
        missing_count = len(result.missing_indicators)
        required_count = len(self.config.required_indicators)
        if missing_count > required_count * 0.5:
            result.is_valid = False
            result.errors.append(
                f"Too many required indicators missing: {missing_count}/{required_count}"
            )

        # 심각한 에러가 있으면 무효
        if result.errors:
            result.is_valid = False

        return result

    def filter_valid_points(
        self,
        data_points: List[MacroDataPoint]
    ) -> List[MacroDataPoint]:
        """
        유효한 데이터 포인트만 필터링.

        3현자 권고: 24시간 이상 지연 데이터 자동 필터링

        Args:
            data_points: 데이터 포인트 리스트

        Returns:
            유효한 데이터 포인트 리스트
        """
        valid_points = []

        for point in data_points:
            is_valid, _ = self.validate_data_point(point)
            if is_valid:
                valid_points.append(point)
            else:
                logger.debug(
                    f"[Validator] Filtered out: {point.indicator} "
                    f"(age: {point.age_hours:.1f}h, quality: {point.quality.value})"
                )

        logger.info(
            f"[Validator] Filtered {len(data_points) - len(valid_points)} "
            f"of {len(data_points)} points"
        )

        return valid_points

    def select_best_value(
        self,
        points: List[MacroDataPoint]
    ) -> Optional[MacroDataPoint]:
        """
        동일 지표의 여러 소스에서 최적값 선택.

        선택 기준:
        1. 가장 최신 데이터
        2. 동일 시간이면 더 신뢰할 수 있는 소스

        Args:
            points: 동일 지표의 데이터 포인트 리스트

        Returns:
            최적의 MacroDataPoint 또는 None
        """
        if not points:
            return None

        # 유효한 포인트만 필터링
        valid_points = self.filter_valid_points(points)
        if not valid_points:
            return None

        # 소스 우선순위 (낮을수록 우선)
        source_priority = {
            "fred": 1,      # 미국 지표는 FRED 우선
            "bok_ecos": 1,  # 한국 지표는 BOK 우선
            "finnhub": 2,
            "pykrx": 2,
            "rss": 3,
        }

        # 가장 최신이면서 우선순위 높은 소스 선택
        best = max(
            valid_points,
            key=lambda p: (
                p.timestamp,
                -source_priority.get(p.source, 10)
            )
        )

        return best

    def get_data_freshness_score(
        self,
        data_points: List[MacroDataPoint]
    ) -> float:
        """
        데이터 전체 신선도 점수 계산.

        Args:
            data_points: 데이터 포인트 리스트

        Returns:
            0.0 ~ 1.0 신선도 점수
        """
        if not data_points:
            return 0.0

        quality_scores = {
            DataQuality.FRESH: 1.0,
            DataQuality.RECENT: 0.8,
            DataQuality.STALE: 0.5,
            DataQuality.EXPIRED: 0.0,
        }

        total_score = sum(
            quality_scores[p.quality] for p in data_points
        )

        return total_score / len(data_points)


class SnapshotValidator:
    """
    GlobalMacroSnapshot 전용 검증기.
    """

    def __init__(self, config: Optional[ValidatorConfig] = None):
        self.config = config or ValidatorConfig()
        self.data_validator = DataValidator(config)

    def validate(
        self,
        snapshot: GlobalMacroSnapshot
    ) -> ValidationResult:
        """
        스냅샷 검증.

        Args:
            snapshot: 검증할 스냅샷

        Returns:
            ValidationResult
        """
        result = ValidationResult()

        # 1. 완성도 검사
        completeness = snapshot.get_completeness_score()
        if completeness < 0.5:
            result.warnings.append(
                f"Low completeness score: {completeness:.0%}"
            )

        # 2. 필수 지표 검사
        required_attrs = [
            ("fed_rate", "Fed Rate"),
            ("bok_rate", "BOK Rate"),
            ("vix", "VIX"),
            ("usd_krw", "USD/KRW"),
            ("kospi_index", "KOSPI"),
            ("kosdaq_index", "KOSDAQ"),
        ]

        for attr, name in required_attrs:
            if getattr(snapshot, attr, None) is None:
                result.missing_indicators.append(attr)
                result.warnings.append(f"Missing: {name}")

        # 3. 값 범위 검사
        for attr, (min_val, max_val) in self.config.value_ranges.items():
            value = getattr(snapshot, attr, None)
            if value is not None:
                if not (min_val <= value <= max_val):
                    result.errors.append(
                        f"{attr}: {value} out of range [{min_val}, {max_val}]"
                    )

        # 4. 스냅샷 시간 검사
        now = datetime.now(UTC)
        snapshot_time = snapshot.snapshot_time
        if snapshot_time.tzinfo:
            snapshot_time = snapshot_time.astimezone(UTC)
        else:
            snapshot_time = snapshot_time.replace(tzinfo=UTC)

        age_hours = (now - snapshot_time).total_seconds() / 3600
        if age_hours > 24:
            result.errors.append(
                f"Snapshot too old: {age_hours:.1f}h"
            )

        # 5. Risk-Off 검증 (3현자 권고: 단독 발동 금지)
        if snapshot.is_risk_off_environment:
            # 최소 2개 지표에서 확인되어야 함 (이미 로직에 포함)
            result.warnings.append(
                "Risk-Off environment detected (confirmed by multiple indicators)"
            )

        # 최종 유효성
        if result.errors:
            result.is_valid = False
        elif len(result.missing_indicators) > len(required_attrs) * 0.5:
            result.is_valid = False
            result.errors.append("Too many required indicators missing")

        return result
