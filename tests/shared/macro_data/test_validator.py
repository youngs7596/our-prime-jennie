#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/shared/macro_data/test_validator.py
-----------------------------------------
DataValidator 테스트.

3현자 Council 권고사항 검증:
- 24시간 이상 지연 데이터 자동 필터링
- 다중 소스 검증
- 필수 지표 누락 경고
"""

import pytest
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

from shared.macro_data.models import MacroDataPoint, GlobalMacroSnapshot, IndicatorCategory
from shared.macro_data.validator import (
    DataValidator,
    SnapshotValidator,
    ValidationResult,
    ValidatorConfig,
)


UTC = ZoneInfo("UTC")
KST = ZoneInfo("Asia/Seoul")


class TestDataValidator:
    """DataValidator 테스트"""

    @pytest.fixture
    def validator(self):
        return DataValidator()

    def test_validate_fresh_data(self, validator):
        """신선한 데이터 검증"""
        point = MacroDataPoint(
            indicator="vix",
            value=18.5,
            timestamp=datetime.now(UTC),
            source="finnhub",
        )

        is_valid, errors = validator.validate_data_point(point)
        assert is_valid
        assert len(errors) == 0

    def test_filter_expired_data(self, validator):
        """만료된 데이터 필터링 (3현자 권고: 24시간)"""
        # 25시간 전 데이터
        old_timestamp = datetime.now(UTC) - timedelta(hours=25)
        point = MacroDataPoint(
            indicator="vix",
            value=18.5,
            timestamp=old_timestamp,
            source="finnhub",
        )

        is_valid, errors = validator.validate_data_point(point)
        assert not is_valid
        assert any("too old" in e for e in errors)

    def test_validate_value_range(self, validator):
        """값 범위 검증"""
        # VIX 값이 너무 높음 (비정상)
        point = MacroDataPoint(
            indicator="vix",
            value=150.0,  # 정상 범위: 5-100
            timestamp=datetime.now(UTC),
            source="finnhub",
        )

        is_valid, errors = validator.validate_data_point(point)
        assert not is_valid
        assert any("out of range" in e for e in errors)

    def test_validate_future_timestamp(self, validator):
        """미래 타임스탬프 검증"""
        future_timestamp = datetime.now(UTC) + timedelta(hours=2)
        point = MacroDataPoint(
            indicator="vix",
            value=18.5,
            timestamp=future_timestamp,
            source="finnhub",
        )

        is_valid, errors = validator.validate_data_point(point)
        assert not is_valid
        assert any("future" in e for e in errors)

    def test_validate_list(self, validator):
        """데이터 포인트 리스트 검증"""
        points = [
            MacroDataPoint(
                indicator="vix",
                value=18.5,
                timestamp=datetime.now(UTC),
                source="finnhub",
            ),
            MacroDataPoint(
                indicator="fed_rate",
                value=5.25,
                timestamp=datetime.now(UTC),
                source="fred",
            ),
            MacroDataPoint(
                indicator="old_data",
                value=100.0,
                timestamp=datetime.now(UTC) - timedelta(hours=30),
                source="test",
            ),
        ]

        result = validator.validate(points)

        assert len(result.filtered_indicators) == 1
        assert "old_data" in result.filtered_indicators

    def test_check_required_indicators(self, validator):
        """필수 지표 누락 확인"""
        # 일부 필수 지표만 제공
        points = [
            MacroDataPoint(
                indicator="vix",
                value=18.5,
                timestamp=datetime.now(UTC),
                source="finnhub",
            ),
        ]

        result = validator.validate(points)

        assert len(result.missing_indicators) > 0
        assert "fed_rate" in result.missing_indicators

    def test_multi_source_verification_warning(self, validator):
        """다중 소스 검증 경고 (3현자 권고)"""
        # USD/KRW를 단일 소스에서만 제공
        points = [
            MacroDataPoint(
                indicator="usd_krw",
                value=1350.0,
                timestamp=datetime.now(UTC),
                source="finnhub",
            ),
        ]

        result = validator.validate(points)

        # 다중 소스 검증 경고
        assert any("only 1 source" in w for w in result.warnings)

    def test_filter_valid_points(self, validator):
        """유효한 데이터만 필터링"""
        points = [
            MacroDataPoint(
                indicator="vix",
                value=18.5,
                timestamp=datetime.now(UTC),
                source="finnhub",
            ),
            MacroDataPoint(
                indicator="old_vix",
                value=20.0,
                timestamp=datetime.now(UTC) - timedelta(hours=30),
                source="finnhub",
            ),
        ]

        valid_points = validator.filter_valid_points(points)

        assert len(valid_points) == 1
        assert valid_points[0].indicator == "vix"

    def test_select_best_value_latest(self, validator):
        """최신 데이터 선택"""
        points = [
            MacroDataPoint(
                indicator="vix",
                value=18.5,
                timestamp=datetime.now(UTC) - timedelta(hours=2),
                source="finnhub",
            ),
            MacroDataPoint(
                indicator="vix",
                value=19.0,
                timestamp=datetime.now(UTC),  # 더 최신
                source="other",
            ),
        ]

        best = validator.select_best_value(points)

        assert best is not None
        assert best.value == 19.0

    def test_data_freshness_score(self, validator):
        """데이터 신선도 점수"""
        # 모두 신선한 데이터
        fresh_points = [
            MacroDataPoint(
                indicator=f"indicator_{i}",
                value=i,
                timestamp=datetime.now(UTC),
                source="test",
            )
            for i in range(5)
        ]

        score = validator.get_data_freshness_score(fresh_points)
        assert score == 1.0

        # 빈 리스트
        score = validator.get_data_freshness_score([])
        assert score == 0.0


class TestSnapshotValidator:
    """SnapshotValidator 테스트"""

    @pytest.fixture
    def validator(self):
        return SnapshotValidator()

    def test_validate_complete_snapshot(self, validator):
        """완전한 스냅샷 검증"""
        snapshot = GlobalMacroSnapshot(
            snapshot_date=date.today(),
            snapshot_time=datetime.now(KST),
            fed_rate=5.25,
            bok_rate=3.50,
            vix=18.5,
            usd_krw=1350.0,
            kospi_index=2650.0,
            kosdaq_index=850.0,
        )

        result = validator.validate(snapshot)

        assert result.is_valid
        assert len(result.errors) == 0

    def test_validate_incomplete_snapshot(self, validator):
        """불완전한 스냅샷 검증"""
        snapshot = GlobalMacroSnapshot(
            snapshot_date=date.today(),
            snapshot_time=datetime.now(KST),
            vix=18.5,  # 필수 지표 대부분 누락
        )

        result = validator.validate(snapshot)

        assert len(result.missing_indicators) > 0

    def test_validate_old_snapshot(self, validator):
        """오래된 스냅샷 검증"""
        old_time = datetime.now(KST) - timedelta(hours=30)
        snapshot = GlobalMacroSnapshot(
            snapshot_date=date.today() - timedelta(days=1),
            snapshot_time=old_time,
            vix=18.5,
        )

        result = validator.validate(snapshot)

        assert not result.is_valid
        assert any("too old" in e for e in result.errors)

    def test_validate_risk_off(self, validator):
        """Risk-Off 환경 검증"""
        snapshot = GlobalMacroSnapshot(
            snapshot_date=date.today(),
            snapshot_time=datetime.now(KST),
            vix=40.0,
            treasury_10y=4.0,
            treasury_2y=5.0,  # inverted
        )

        result = validator.validate(snapshot)

        # Risk-Off 경고 (에러 아님, 정보성 경고)
        assert any("Risk-Off" in w for w in result.warnings)
