#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/shared/macro_data/test_models.py
--------------------------------------
MacroDataPoint, GlobalMacroSnapshot 모델 테스트.
"""

import pytest
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

from shared.macro_data.models import (
    MacroDataPoint,
    GlobalMacroSnapshot,
    DataQuality,
    IndicatorCategory,
)


UTC = ZoneInfo("UTC")
KST = ZoneInfo("Asia/Seoul")


class TestMacroDataPoint:
    """MacroDataPoint 테스트"""

    def test_create_data_point(self):
        """데이터 포인트 생성"""
        point = MacroDataPoint(
            indicator="vix",
            value=18.5,
            timestamp=datetime.now(UTC),
            source="finnhub",
            category=IndicatorCategory.VOLATILITY,
            unit="index",
        )

        assert point.indicator == "vix"
        assert point.value == 18.5
        assert point.source == "finnhub"

    def test_age_hours(self):
        """데이터 연령 계산"""
        # 2시간 전 데이터
        timestamp = datetime.now(UTC) - timedelta(hours=2)
        point = MacroDataPoint(
            indicator="vix",
            value=18.5,
            timestamp=timestamp,
            source="finnhub",
        )

        assert 1.9 < point.age_hours < 2.1

    def test_data_quality_fresh(self):
        """신선한 데이터 품질"""
        point = MacroDataPoint(
            indicator="vix",
            value=18.5,
            timestamp=datetime.now(UTC),
            source="finnhub",
        )

        assert point.quality == DataQuality.FRESH

    def test_data_quality_stale(self):
        """오래된 데이터 품질"""
        timestamp = datetime.now(UTC) - timedelta(hours=20)
        point = MacroDataPoint(
            indicator="vix",
            value=18.5,
            timestamp=timestamp,
            source="finnhub",
        )

        assert point.quality == DataQuality.STALE

    def test_data_quality_expired(self):
        """만료된 데이터 품질 (3현자 권고: 24시간 이상)"""
        timestamp = datetime.now(UTC) - timedelta(hours=25)
        point = MacroDataPoint(
            indicator="vix",
            value=18.5,
            timestamp=timestamp,
            source="finnhub",
        )

        assert point.quality == DataQuality.EXPIRED
        assert not point.is_valid(max_age_hours=24)

    def test_to_dict(self):
        """딕셔너리 변환"""
        point = MacroDataPoint(
            indicator="vix",
            value=18.5,
            timestamp=datetime.now(UTC),
            source="finnhub",
            category=IndicatorCategory.VOLATILITY,
        )

        d = point.to_dict()
        assert d["indicator"] == "vix"
        assert d["value"] == 18.5
        assert d["source"] == "finnhub"
        assert d["category"] == "volatility"
        assert "timestamp" in d
        assert "quality" in d


class TestGlobalMacroSnapshot:
    """GlobalMacroSnapshot 테스트"""

    def test_create_snapshot(self):
        """스냅샷 생성"""
        snapshot = GlobalMacroSnapshot(
            snapshot_date=date.today(),
            snapshot_time=datetime.now(KST),
            vix=18.5,
            fed_rate=5.25,
            bok_rate=3.50,
        )

        assert snapshot.vix == 18.5
        assert snapshot.fed_rate == 5.25
        assert snapshot.bok_rate == 3.50

    def test_vix_regime_classification(self):
        """VIX 레짐 분류"""
        # low_vol
        snapshot = GlobalMacroSnapshot(
            snapshot_date=date.today(),
            snapshot_time=datetime.now(KST),
            vix=12.0,
        )
        assert snapshot.vix_regime == "low_vol"

        # normal
        snapshot = GlobalMacroSnapshot(
            snapshot_date=date.today(),
            snapshot_time=datetime.now(KST),
            vix=20.0,
        )
        assert snapshot.vix_regime == "normal"

        # elevated
        snapshot = GlobalMacroSnapshot(
            snapshot_date=date.today(),
            snapshot_time=datetime.now(KST),
            vix=30.0,
        )
        assert snapshot.vix_regime == "elevated"

        # crisis
        snapshot = GlobalMacroSnapshot(
            snapshot_date=date.today(),
            snapshot_time=datetime.now(KST),
            vix=40.0,
        )
        assert snapshot.vix_regime == "crisis"

    def test_rate_differential(self):
        """금리차 계산"""
        snapshot = GlobalMacroSnapshot(
            snapshot_date=date.today(),
            snapshot_time=datetime.now(KST),
            fed_rate=5.25,
            bok_rate=3.50,
        )

        assert snapshot.rate_differential == 1.75

    def test_krw_pressure_direction(self):
        """원화 압력 방향"""
        # krw_weakness (금리차 > 1.5%)
        snapshot = GlobalMacroSnapshot(
            snapshot_date=date.today(),
            snapshot_time=datetime.now(KST),
            fed_rate=5.25,
            bok_rate=3.50,
        )
        assert snapshot.krw_pressure_direction == "krw_weakness"

        # neutral
        snapshot = GlobalMacroSnapshot(
            snapshot_date=date.today(),
            snapshot_time=datetime.now(KST),
            fed_rate=4.00,
            bok_rate=3.50,
        )
        assert snapshot.krw_pressure_direction == "neutral"

        # krw_strength (금리차 < -0.5%)
        snapshot = GlobalMacroSnapshot(
            snapshot_date=date.today(),
            snapshot_time=datetime.now(KST),
            fed_rate=3.00,
            bok_rate=4.00,
        )
        assert snapshot.krw_pressure_direction == "krw_strength"

    def test_risk_off_environment(self):
        """Risk-Off 환경 감지 (3현자 권고: 다중 지표)"""
        # 단일 지표 (VIX만) - Risk-Off 아님
        snapshot = GlobalMacroSnapshot(
            snapshot_date=date.today(),
            snapshot_time=datetime.now(KST),
            vix=40.0,
        )
        assert not snapshot.is_risk_off_environment

        # 다중 지표 (VIX + inverted curve) - Risk-Off
        snapshot = GlobalMacroSnapshot(
            snapshot_date=date.today(),
            snapshot_time=datetime.now(KST),
            vix=40.0,
            treasury_10y=4.0,
            treasury_2y=5.0,  # inverted
        )
        assert snapshot.is_risk_off_environment

    def test_completeness_score(self):
        """완성도 점수"""
        # 전체 필수 지표
        snapshot = GlobalMacroSnapshot(
            snapshot_date=date.today(),
            snapshot_time=datetime.now(KST),
            fed_rate=5.25,
            vix=18.5,
            dxy_index=104.5,
            usd_krw=1350.0,
            bok_rate=3.50,
            kospi_index=2650.0,
            kosdaq_index=850.0,
        )
        assert snapshot.get_completeness_score() == 1.0

        # 부분 지표
        snapshot = GlobalMacroSnapshot(
            snapshot_date=date.today(),
            snapshot_time=datetime.now(KST),
            vix=18.5,
            kospi_index=2650.0,
        )
        score = snapshot.get_completeness_score()
        assert 0 < score < 1

    def test_to_dict(self):
        """딕셔너리 변환"""
        snapshot = GlobalMacroSnapshot(
            snapshot_date=date.today(),
            snapshot_time=datetime.now(KST),
            vix=18.5,
            fed_rate=5.25,
        )

        d = snapshot.to_dict()
        assert "snapshot_date" in d
        assert "vix" in d
        assert "vix_regime" in d
        assert "completeness_score" in d

    def test_from_dict(self):
        """딕셔너리에서 생성"""
        data = {
            "snapshot_date": "2026-02-01",
            "snapshot_time": "2026-02-01T10:00:00+09:00",
            "vix": 18.5,
            "fed_rate": 5.25,
            "bok_rate": 3.50,
        }

        snapshot = GlobalMacroSnapshot.from_dict(data)
        assert snapshot.vix == 18.5
        assert snapshot.fed_rate == 5.25

    def test_to_llm_context(self):
        """LLM 컨텍스트 생성"""
        snapshot = GlobalMacroSnapshot(
            snapshot_date=date.today(),
            snapshot_time=datetime.now(KST),
            vix=18.5,
            fed_rate=5.25,
            bok_rate=3.50,
            kospi_index=2650.0,
        )

        context = snapshot.to_llm_context()
        assert "VIX" in context
        assert "Fed" in context
        assert "BOK" in context
        assert "KOSPI" in context
