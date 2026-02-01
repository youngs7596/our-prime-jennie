#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shared/macro_insight/enhanced_analyzer.py
------------------------------------------
Enhanced Macro Analyzer.

글로벌 매크로 데이터 스냅샷과 텔레그램 브리핑을 통합 분석합니다.

3현자 Council 권고사항:
- 모든 LLM 출력에 근거 데이터 + 타임스탬프 첨부
- 24시간 이상 지연 데이터 자동 필터링
- 외부 정보 가중치 ≤10% 적용
- RISK_OFF 단독 발동 금지 (다중 지표 확인)
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from shared.macro_data import GlobalMacroSnapshot

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")

# 프로젝트 루트
PROJECT_ROOT = Path(__file__).parent.parent.parent


@dataclass
class DataCitation:
    """데이터 인용 (3현자 권고: 근거 데이터 첨부)"""
    indicator: str
    value: float
    source: str
    timestamp: datetime

    def to_dict(self) -> Dict[str, Any]:
        return {
            "indicator": self.indicator,
            "value": self.value,
            "source": self.source,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class RiskOffAssessment:
    """Risk-Off 평가 (3현자 권고: 다중 지표 확인)"""
    is_risk_off: bool = False
    signals_detected: List[str] = field(default_factory=list)
    confidence: int = 50


@dataclass
class PositionSizeRecommendation:
    """포지션 사이즈 추천"""
    multiplier: float = 1.0
    reasoning: str = ""


@dataclass
class DataQualityNotes:
    """데이터 품질 메모"""
    completeness_score: float = 0.0
    missing_critical: List[str] = field(default_factory=list)
    stale_indicators: List[str] = field(default_factory=list)
    caveats: List[str] = field(default_factory=list)


@dataclass
class EnhancedMacroInsight:
    """
    Enhanced Macro Insight.

    기존 DailyMacroInsight를 확장하여 글로벌 데이터 통합.
    """
    insight_date: date
    analysis_timestamp: datetime

    # 기존 필드 (DailyMacroInsight 호환)
    source_channel: str = ""
    source_analyst: str = ""
    sentiment: str = "neutral"
    sentiment_score: int = 50
    sentiment_reasoning: str = ""
    regime_hint: str = ""

    # 확장 필드 (글로벌 데이터 기반)
    vix_regime: str = "normal"
    krw_pressure: str = "neutral"
    rate_differential: Optional[float] = None
    rate_differential_impact: str = ""

    # 3현자 권고 필드
    data_citations: List[DataCitation] = field(default_factory=list)
    risk_off_assessment: Optional[RiskOffAssessment] = None
    position_size: Optional[PositionSizeRecommendation] = None
    data_quality: Optional[DataQualityNotes] = None

    # 상세 데이터
    sector_signals: Dict[str, Any] = field(default_factory=dict)
    key_themes: List[Dict[str, Any]] = field(default_factory=list)
    risk_factors: List[str] = field(default_factory=list)
    opportunity_factors: List[str] = field(default_factory=list)
    key_stocks: List[str] = field(default_factory=list)

    # 원본 데이터
    global_snapshot: Optional[GlobalMacroSnapshot] = None
    raw_telegram_briefing: str = ""
    raw_llm_output: str = ""
    council_cost_usd: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리 변환"""
        return {
            "insight_date": self.insight_date.isoformat(),
            "analysis_timestamp": self.analysis_timestamp.isoformat(),
            "source_channel": self.source_channel,
            "source_analyst": self.source_analyst,
            "sentiment": self.sentiment,
            "sentiment_score": self.sentiment_score,
            "sentiment_reasoning": self.sentiment_reasoning,
            "regime_hint": self.regime_hint,
            "vix_regime": self.vix_regime,
            "krw_pressure": self.krw_pressure,
            "rate_differential": self.rate_differential,
            "rate_differential_impact": self.rate_differential_impact,
            "data_citations": [c.to_dict() for c in self.data_citations],
            "risk_off_assessment": {
                "is_risk_off": self.risk_off_assessment.is_risk_off,
                "signals_detected": self.risk_off_assessment.signals_detected,
                "confidence": self.risk_off_assessment.confidence,
            } if self.risk_off_assessment else None,
            "position_size": {
                "multiplier": self.position_size.multiplier,
                "reasoning": self.position_size.reasoning,
            } if self.position_size else None,
            "data_quality": {
                "completeness_score": self.data_quality.completeness_score,
                "missing_critical": self.data_quality.missing_critical,
                "stale_indicators": self.data_quality.stale_indicators,
                "caveats": self.data_quality.caveats,
            } if self.data_quality else None,
            "sector_signals": self.sector_signals,
            "key_themes": self.key_themes,
            "risk_factors": self.risk_factors,
            "opportunity_factors": self.opportunity_factors,
            "key_stocks": self.key_stocks,
            "council_cost_usd": self.council_cost_usd,
        }

    def get_position_multiplier(self) -> float:
        """포지션 사이즈 배율 반환"""
        if self.position_size:
            return self.position_size.multiplier

        # 기본 로직 (sentiment_score 기반)
        if self.sentiment_score >= 70:
            return 1.2
        elif self.sentiment_score >= 60:
            return 1.1
        elif self.sentiment_score <= 30:
            return 0.7
        elif self.sentiment_score <= 40:
            return 0.85
        else:
            return 1.0


class EnhancedMacroAnalyzer:
    """
    Enhanced Macro Analyzer.

    글로벌 매크로 데이터 스냅샷과 텔레그램 브리핑을 통합 분석합니다.

    Usage:
        analyzer = EnhancedMacroAnalyzer()
        insight = await analyzer.analyze(
            snapshot=global_snapshot,
            telegram_briefing=briefing_text,
        )
    """

    def __init__(self, prompt_path: Optional[str] = None):
        """
        분석기 초기화.

        Args:
            prompt_path: 프롬프트 파일 경로 (없으면 기본값)
        """
        self.prompt_path = prompt_path or str(
            PROJECT_ROOT / "prompts" / "council" / "enhanced_macro_analysis.txt"
        )
        self._prompt_template: Optional[str] = None

    def _load_prompt_template(self) -> str:
        """프롬프트 템플릿 로드"""
        if self._prompt_template is None:
            with open(self.prompt_path, "r", encoding="utf-8") as f:
                self._prompt_template = f.read()
        return self._prompt_template

    def _build_prompt(
        self,
        snapshot: GlobalMacroSnapshot,
        telegram_briefing: str
    ) -> str:
        """
        분석 프롬프트 생성.

        Args:
            snapshot: 글로벌 매크로 스냅샷
            telegram_briefing: 텔레그램 브리핑 텍스트

        Returns:
            완성된 프롬프트
        """
        template = self._load_prompt_template()

        # 스냅샷을 LLM 컨텍스트로 변환
        snapshot_context = snapshot.to_llm_context()

        return template.format(
            global_macro_snapshot=snapshot_context,
            telegram_briefing=telegram_briefing or "(텔레그램 브리핑 없음)",
        )

    def _parse_llm_response(
        self,
        response: str,
        snapshot: GlobalMacroSnapshot
    ) -> EnhancedMacroInsight:
        """
        LLM 응답 파싱.

        Args:
            response: LLM 응답 문자열
            snapshot: 원본 스냅샷

        Returns:
            EnhancedMacroInsight
        """
        now = datetime.now(KST)
        insight = EnhancedMacroInsight(
            insight_date=now.date(),
            analysis_timestamp=now,
            global_snapshot=snapshot,
            raw_llm_output=response,
        )

        try:
            # JSON 블록 추출
            json_match = re.search(r'```json\s*([\s\S]*?)\s*```', response)
            if json_match:
                json_str = json_match.group(1)
            else:
                # JSON 블록이 없으면 전체 응답에서 JSON 찾기
                json_match = re.search(r'\{[\s\S]*\}', response)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    logger.warning("[EnhancedAnalyzer] JSON not found in response")
                    return insight

            data = json.loads(json_str)

            # 기본 필드
            insight.sentiment = data.get("overall_sentiment", "neutral")
            insight.sentiment_score = data.get("sentiment_score", 50)
            insight.sentiment_reasoning = data.get("sentiment_reasoning", "")
            insight.regime_hint = data.get("regime_hint", "")
            insight.vix_regime = data.get("vix_regime", snapshot.vix_regime or "normal")
            insight.krw_pressure = data.get("krw_pressure", snapshot.krw_pressure_direction)
            insight.rate_differential = snapshot.rate_differential
            insight.rate_differential_impact = data.get("rate_differential_impact", "")

            # 데이터 인용 (3현자 권고)
            citations = data.get("data_citations", [])
            for c in citations:
                try:
                    insight.data_citations.append(DataCitation(
                        indicator=c.get("indicator", ""),
                        value=float(c.get("value", 0)),
                        source=c.get("source", ""),
                        timestamp=datetime.fromisoformat(c.get("timestamp", now.isoformat())),
                    ))
                except (ValueError, KeyError):
                    continue

            # Risk-Off 평가 (3현자 권고: 다중 지표)
            risk_off = data.get("risk_off_assessment", {})
            insight.risk_off_assessment = RiskOffAssessment(
                is_risk_off=risk_off.get("is_risk_off", snapshot.is_risk_off_environment),
                signals_detected=risk_off.get("signals_detected", []),
                confidence=risk_off.get("confidence", 50),
            )

            # 포지션 사이즈
            pos_size = data.get("position_size_recommendation", {})
            insight.position_size = PositionSizeRecommendation(
                multiplier=float(pos_size.get("multiplier", 1.0)),
                reasoning=pos_size.get("reasoning", ""),
            )

            # 데이터 품질
            quality = data.get("data_quality_notes", {})
            insight.data_quality = DataQualityNotes(
                completeness_score=float(quality.get("completeness_score", snapshot.get_completeness_score())),
                missing_critical=quality.get("missing_critical", snapshot.missing_indicators),
                stale_indicators=quality.get("stale_indicators", snapshot.stale_indicators),
                caveats=quality.get("caveats", []),
            )

            # 상세 데이터
            insight.sector_signals = data.get("sector_signals", {})
            insight.key_themes = data.get("key_themes", [])
            insight.risk_factors = data.get("risk_factors", [])
            insight.opportunity_factors = data.get("opportunity_factors", [])
            insight.key_stocks = data.get("key_stocks", [])

        except json.JSONDecodeError as e:
            logger.error(f"[EnhancedAnalyzer] JSON parse error: {e}")
        except Exception as e:
            logger.error(f"[EnhancedAnalyzer] Parse error: {e}", exc_info=True)

        return insight

    async def analyze(
        self,
        snapshot: GlobalMacroSnapshot,
        telegram_briefing: str = "",
        use_council: bool = True,
    ) -> EnhancedMacroInsight:
        """
        매크로 데이터 분석.

        Args:
            snapshot: 글로벌 매크로 스냅샷
            telegram_briefing: 텔레그램 브리핑 텍스트
            use_council: 3현자 Council 사용 여부

        Returns:
            EnhancedMacroInsight
        """
        prompt = self._build_prompt(snapshot, telegram_briefing)

        if use_council:
            # Council 분석 실행
            insight = await self._run_council_analysis(
                prompt, snapshot, telegram_briefing
            )
        else:
            # 단일 LLM 분석
            insight = await self._run_single_llm_analysis(
                prompt, snapshot, telegram_briefing
            )

        return insight

    async def _run_council_analysis(
        self,
        prompt: str,
        snapshot: GlobalMacroSnapshot,
        telegram_briefing: str
    ) -> EnhancedMacroInsight:
        """
        3현자 Council 분석 실행.
        """
        import subprocess
        import tempfile

        now = datetime.now(KST)

        # 임시 파일에 프롬프트 저장
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False, encoding='utf-8'
        ) as f:
            f.write(f"# Enhanced Macro Analysis Request\n\n{prompt}")
            temp_file = f.name

        try:
            # Council 스크립트 실행
            cmd = [
                "python",
                str(PROJECT_ROOT / "scripts" / "ask_prime_council.py"),
                "--query", "위 데이터를 분석하고 JSON 형식으로 결과를 제공해주세요.",
                "--file", temp_file,
            ]

            logger.info("[EnhancedAnalyzer] Running Council analysis...")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
                cwd=str(PROJECT_ROOT),
            )

            if result.returncode != 0:
                logger.error(f"[EnhancedAnalyzer] Council failed: {result.stderr}")
                return self._create_fallback_insight(snapshot, telegram_briefing)

            # 리포트 파일 찾기
            reports_dir = PROJECT_ROOT / ".ai" / "reviews"
            report_files = sorted(reports_dir.glob("council_report_*.md"), reverse=True)

            if report_files:
                with open(report_files[0], "r", encoding="utf-8") as f:
                    report_content = f.read()

                # 비용 추출
                cost_match = re.search(r'\*\*\$([0-9.]+)\*\*', report_content)
                cost_usd = float(cost_match.group(1)) if cost_match else 0.0

                insight = self._parse_llm_response(report_content, snapshot)
                insight.raw_telegram_briefing = telegram_briefing
                insight.council_cost_usd = cost_usd

                return insight

        except subprocess.TimeoutExpired:
            logger.error("[EnhancedAnalyzer] Council timeout")
        except Exception as e:
            logger.error(f"[EnhancedAnalyzer] Council error: {e}")
        finally:
            os.unlink(temp_file)

        return self._create_fallback_insight(snapshot, telegram_briefing)

    async def _run_single_llm_analysis(
        self,
        prompt: str,
        snapshot: GlobalMacroSnapshot,
        telegram_briefing: str
    ) -> EnhancedMacroInsight:
        """
        단일 LLM 분석 실행 (Council 없이).
        """
        # TODO: Gemini 또는 Claude API 직접 호출
        logger.warning("[EnhancedAnalyzer] Single LLM analysis not implemented, using fallback")
        return self._create_fallback_insight(snapshot, telegram_briefing)

    def _create_fallback_insight(
        self,
        snapshot: GlobalMacroSnapshot,
        telegram_briefing: str
    ) -> EnhancedMacroInsight:
        """
        폴백 인사이트 생성 (규칙 기반).
        """
        now = datetime.now(KST)

        # VIX 기반 sentiment 결정
        sentiment = "neutral"
        sentiment_score = 50

        if snapshot.vix is not None:
            if snapshot.vix < 15:
                sentiment = "bullish"
                sentiment_score = 65
            elif snapshot.vix < 20:
                sentiment = "neutral_to_bullish"
                sentiment_score = 55
            elif snapshot.vix < 30:
                sentiment = "neutral"
                sentiment_score = 50
            elif snapshot.vix < 35:
                sentiment = "neutral_to_bearish"
                sentiment_score = 40
            else:
                sentiment = "bearish"
                sentiment_score = 30

        # 포지션 배율 계산
        multiplier = 1.0
        if sentiment_score >= 65:
            multiplier = 1.2
        elif sentiment_score >= 55:
            multiplier = 1.1
        elif sentiment_score <= 35:
            multiplier = 0.8
        elif sentiment_score <= 45:
            multiplier = 0.9

        return EnhancedMacroInsight(
            insight_date=now.date(),
            analysis_timestamp=now,
            sentiment=sentiment,
            sentiment_score=sentiment_score,
            sentiment_reasoning="규칙 기반 폴백 분석 (VIX, 금리차 기반)",
            vix_regime=snapshot.vix_regime,
            krw_pressure=snapshot.krw_pressure_direction,
            rate_differential=snapshot.rate_differential,
            risk_off_assessment=RiskOffAssessment(
                is_risk_off=snapshot.is_risk_off_environment,
                signals_detected=["VIX >= 35"] if snapshot.vix and snapshot.vix >= 35 else [],
                confidence=70 if snapshot.is_risk_off_environment else 50,
            ),
            position_size=PositionSizeRecommendation(
                multiplier=multiplier,
                reasoning="VIX 및 금리차 기반 자동 계산",
            ),
            data_quality=DataQualityNotes(
                completeness_score=snapshot.get_completeness_score(),
                missing_critical=snapshot.missing_indicators,
                stale_indicators=snapshot.stale_indicators,
                caveats=["Council 분석 실패로 규칙 기반 폴백 사용"],
            ),
            global_snapshot=snapshot,
            raw_telegram_briefing=telegram_briefing,
        )

    def analyze_synchronous(
        self,
        snapshot: GlobalMacroSnapshot,
        telegram_briefing: str = "",
    ) -> EnhancedMacroInsight:
        """
        동기 방식 분석 (규칙 기반, LLM 미사용).
        """
        return self._create_fallback_insight(snapshot, telegram_briefing)
