# shared/fact_checker.py
# AI Auditor 모듈 - Gemini 2.5 Flash 기반 LLM 환각 검증
# gemma3 분석 결과를 Gemini Flash로 교차 검증

"""
Fact-Checker 노드 (v2.0 - LLM 기반)

Scout Pipeline의 Judge 단계 전에 실행되어
LLM이 생성한 분석 내용이 뉴스 원문과 일치하는지 검증합니다.

변경 이력:
- v2.0: regex 기반 검증 → Gemini 2.5 Flash LLM 검증으로 교체
- 더 정확한 맥락 이해와 환각 탐지 가능
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class FactCheckResult:
    """환각 검증 결과"""
    is_valid: bool
    confidence: float  # 0.0 ~ 1.0
    warnings: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)
    
    @property
    def has_hallucination(self) -> bool:
        return not self.is_valid or self.confidence < 0.5


class FactChecker:
    """
    AI Auditor - Gemini 2.5 Flash 기반 LLM 환각 탐지기
    
    gemma3 LLM의 분석 결과를 Gemini Flash가 검증합니다.
    """
    
    # LLM 응답 스키마
    RESPONSE_SCHEMA = {
        "type": "object",
        "properties": {
            "is_valid": {
                "type": "boolean",
                "description": "분석이 원문에 근거하는지 여부"
            },
            "confidence": {
                "type": "number",
                "description": "검증 신뢰도 (0.0 ~ 1.0)"
            },
            "warnings": {
                "type": "array",
                "items": {"type": "string"},
                "description": "발견된 문제점 목록"
            },
            "reason": {
                "type": "string",
                "description": "판단 근거 요약"
            }
        },
        "required": ["is_valid", "confidence", "warnings", "reason"]
    }
    
    def __init__(self):
        self._provider = None
    
    def _get_provider(self):
        """Gemini Flash Provider 지연 로딩"""
        if self._provider is None:
            from shared.llm_factory import LLMFactory, LLMTier
            self._provider = LLMFactory.get_provider(LLMTier.FAST)
        return self._provider
    
    def check(
        self,
        original_news: str,
        llm_analysis: str,
        stock_name: Optional[str] = None
    ) -> FactCheckResult:
        """
        LLM 분석 결과와 뉴스 원문을 교차 검증 (Gemini Flash 사용)
        
        Args:
            original_news: 뉴스 원문 텍스트 (정량 컨텍스트 포함 가능)
            llm_analysis: LLM(gemma3)이 생성한 분석 결과
            stock_name: 종목명 (선택)
        
        Returns:
            FactCheckResult: 검증 결과
        """
        if not original_news or not llm_analysis:
            return FactCheckResult(
                is_valid=True,
                confidence=0.0,
                warnings=["검증 데이터 부족"],
                details={"reason": "empty_input"}
            )
        
        try:
            provider = self._get_provider()
            prompt = self._build_prompt(original_news, llm_analysis, stock_name)
            
            result = provider.generate_json(
                prompt=prompt,
                response_schema=self.RESPONSE_SCHEMA,
                temperature=0.1  # 일관성 있는 검증을 위해 낮은 temperature
            )
            
            # LLM 응답 파싱
            is_valid = result.get("is_valid", True)
            confidence = float(result.get("confidence", 0.5))
            warnings = result.get("warnings", [])
            reason = result.get("reason", "")
            
            # 신뢰도 범위 조정 (0.0 ~ 1.0)
            confidence = max(0.0, min(1.0, confidence))
            
            if warnings:
                logger.warning(f"⚠️ [AI Auditor] 경고: {warnings}")
            
            return FactCheckResult(
                is_valid=is_valid,
                confidence=round(confidence, 2),
                warnings=warnings,
                details={"reason": reason, "source": "gemini-flash-audit"}
            )
            
        except Exception as e:
            logger.error(f"❌ [AI Auditor] LLM 검증 오류: {e}")
            # LLM 호출 실패 시 기본값 반환 (보수적으로 valid 처리)
            return FactCheckResult(
                is_valid=True,
                confidence=0.5,
                warnings=[f"검증 오류: {str(e)[:50]}"],
                details={"error": str(e), "fallback": True}
            )
    
    def _build_prompt(
        self, 
        original_news: str, 
        llm_analysis: str, 
        stock_name: Optional[str]
    ) -> str:
        """환각 검증 프롬프트 생성"""
        stock_info = f" ({stock_name})" if stock_name else ""
        
        prompt = f"""당신은 LLM 분석 결과의 사실 검증을 담당하는 AI Auditor입니다.

[임무]
다른 LLM(gemma3)이 생성한 분석 결과가 원문 데이터에 근거하는지 검증하세요.

[원문 데이터]{stock_info}
{original_news[:3000]}

[gemma3 분석 결과]
{llm_analysis[:2000]}

[검증 기준]
1. **사실 일치**: 분석에 언급된 숫자, 날짜, 사실이 원문과 일치하는가?
2. **맥락 충실**: 원문의 맥락을 왜곡하지 않고 정확히 해석했는가?
3. **환각 탐지**: 원문에 없는 정보를 창조(Hallucination)하지 않았는가?

[판정 기준]
- is_valid=true, confidence≥0.7: 분석이 원문에 충실함
- is_valid=true, confidence<0.7: 일부 불확실하나 큰 문제 없음
- is_valid=false: 명백한 사실 오류 또는 환각 발견

[주의사항]
- 정량 분석 리포트(Quant Score, PER/PBR 등)가 포함된 경우, 해당 수치 역시 "원문"의 일부로 간주하세요.
- 분석의 "의견"이나 "전망"은 환각으로 판정하지 마세요. 오직 "사실 관계"만 검증합니다.

JSON 형식으로 응답하세요."""
        
        return prompt.strip()


# 싱글톤 인스턴스
_fact_checker = None

def get_fact_checker() -> FactChecker:
    """Fact-Checker 싱글톤 인스턴스 반환"""
    global _fact_checker
    if _fact_checker is None:
        _fact_checker = FactChecker()
    return _fact_checker
