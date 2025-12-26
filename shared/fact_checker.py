# shared/fact_checker.py
# 환각(Hallucination) 탐지 모듈
# LLM 분석 결과를 뉴스 원문과 교차 검증

"""
Fact-Checker 노드

Scout Pipeline의 Judge 단계 전에 실행되어
LLM이 생성한 분석 내용이 뉴스 원문과 일치하는지 검증합니다.

주요 기능:
1. 키워드 교차 검증: 분석에 언급된 주요 키워드가 원문에 존재하는지
2. 숫자/날짜 검증: 분석에 언급된 수치가 원문과 일치하는지
3. 환각 플래그: 불일치 발견 시 경고 플래그 반환
"""

import re
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class FactCheckResult:
    """환각 검증 결과"""
    is_valid: bool
    confidence: float  # 0.0 ~ 1.0
    warnings: list[str]
    details: dict
    
    @property
    def has_hallucination(self) -> bool:
        return not self.is_valid or self.confidence < 0.5


class FactChecker:
    """LLM 환각 탐지기"""
    
    # 주요 추출 패턴
    NUMBER_PATTERN = re.compile(r'(\d+(?:,\d{3})*(?:\.\d+)?)\s*(%|원|억|조|만)?')
    DATE_PATTERN = re.compile(r'(\d{4})[-./년](\d{1,2})[-./월]?(\d{1,2})?일?')
    
    # 환각 탐지 임계값
    KEYWORD_MATCH_THRESHOLD = 0.4  # 핵심 키워드의 40% 이상이 원문에 있어야 함
    NUMBER_MATCH_THRESHOLD = 0.5   # 숫자의 50% 이상이 원문에 있어야 함
    
    def __init__(self):
        pass
    
    def check(
        self,
        original_news: str,
        llm_analysis: str,
        stock_name: Optional[str] = None
    ) -> FactCheckResult:
        """
        LLM 분석 결과와 뉴스 원문을 교차 검증
        
        Args:
            original_news: 뉴스 원문 텍스트
            llm_analysis: LLM이 생성한 분석 결과
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
        
        warnings = []
        details = {}
        
        # 1. 숫자 검증
        number_result = self._check_numbers(original_news, llm_analysis)
        details['numbers'] = number_result
        if not number_result['valid']:
            warnings.extend(number_result.get('warnings', []))
        
        # 2. 날짜 검증
        date_result = self._check_dates(original_news, llm_analysis)
        details['dates'] = date_result
        if not date_result['valid']:
            warnings.extend(date_result.get('warnings', []))
        
        # 3. 키워드 검증
        keyword_result = self._check_keywords(original_news, llm_analysis, stock_name)
        details['keywords'] = keyword_result
        if not keyword_result['valid']:
            warnings.extend(keyword_result.get('warnings', []))
        
        # 전체 신뢰도 계산
        score_weights = {'numbers': 0.4, 'dates': 0.3, 'keywords': 0.3}
        confidence = sum(
            details[key].get('score', 0.5) * weight
            for key, weight in score_weights.items()
        )
        
        is_valid = confidence >= 0.5 and len(warnings) < 3
        
        if warnings:
            logger.warning(f"⚠️ Fact-Check 경고: {warnings}")
        
        return FactCheckResult(
            is_valid=is_valid,
            confidence=round(confidence, 2),
            warnings=warnings,
            details=details
        )
    
    def _check_numbers(self, original: str, analysis: str) -> dict:
        """숫자 검증"""
        original_numbers = set(self._extract_numbers(original))
        analysis_numbers = set(self._extract_numbers(analysis))
        
        if not analysis_numbers:
            return {'valid': True, 'score': 0.5, 'message': 'No numbers to verify'}
        
        # 분석에 있는 숫자가 원문에도 있는지
        matched = analysis_numbers & original_numbers
        match_ratio = len(matched) / len(analysis_numbers) if analysis_numbers else 1.0
        
        valid = match_ratio >= self.NUMBER_MATCH_THRESHOLD
        warnings = []
        
        if not valid:
            unmatched = analysis_numbers - original_numbers
            if unmatched:
                warnings.append(f"원문에 없는 숫자: {list(unmatched)[:3]}")
        
        return {
            'valid': valid,
            'score': match_ratio,
            'original': list(original_numbers)[:5],
            'analysis': list(analysis_numbers)[:5],
            'matched': list(matched)[:5],
            'warnings': warnings
        }
    
    def _check_dates(self, original: str, analysis: str) -> dict:
        """날짜 검증"""
        original_dates = set(self._extract_dates(original))
        analysis_dates = set(self._extract_dates(analysis))
        
        if not analysis_dates:
            return {'valid': True, 'score': 0.5, 'message': 'No dates to verify'}
        
        matched = analysis_dates & original_dates
        match_ratio = len(matched) / len(analysis_dates) if analysis_dates else 1.0
        
        valid = match_ratio >= 0.5
        warnings = []
        
        if not valid:
            unmatched = analysis_dates - original_dates
            if unmatched:
                warnings.append(f"원문에 없는 날짜: {list(unmatched)[:2]}")
        
        return {
            'valid': valid,
            'score': match_ratio,
            'warnings': warnings
        }
    
    def _check_keywords(self, original: str, analysis: str, stock_name: Optional[str] = None) -> dict:
        """핵심 키워드 검증"""
        # 분석에서 핵심 키워드 추출 (명사 기반)
        analysis_keywords = self._extract_korean_keywords(analysis)
        
        if stock_name:
            # 종목명은 제외 (당연히 언급됨)
            analysis_keywords = [k for k in analysis_keywords if stock_name not in k]
        
        if not analysis_keywords:
            return {'valid': True, 'score': 0.5, 'message': 'No keywords to verify'}
        
        # 원문에 키워드가 있는지 확인
        matched = [k for k in analysis_keywords if k in original]
        match_ratio = len(matched) / len(analysis_keywords) if analysis_keywords else 1.0
        
        valid = match_ratio >= self.KEYWORD_MATCH_THRESHOLD
        warnings = []
        
        if not valid:
            unmatched = [k for k in analysis_keywords if k not in original]
            if unmatched:
                warnings.append(f"원문에 없는 키워드: {unmatched[:3]}")
        
        return {
            'valid': valid,
            'score': match_ratio,
            'keywords': analysis_keywords[:10],
            'matched': matched[:5],
            'warnings': warnings
        }
    
    def _extract_numbers(self, text: str) -> list[str]:
        """텍스트에서 숫자 추출"""
        matches = self.NUMBER_PATTERN.findall(text)
        # 숫자 + 단위를 결합하여 반환
        return [f"{num}{unit}" if unit else num for num, unit in matches]
    
    def _extract_dates(self, text: str) -> list[str]:
        """텍스트에서 날짜 추출"""
        matches = self.DATE_PATTERN.findall(text)
        return [f"{y}-{m.zfill(2)}-{d.zfill(2) if d else '01'}" for y, m, d in matches]
    
    def _extract_korean_keywords(self, text: str) -> list[str]:
        """한국어 텍스트에서 핵심 키워드 추출 (간단 방식)"""
        # 2글자 이상의 한글 명사 패턴
        pattern = re.compile(r'[가-힣]{2,6}')
        keywords = pattern.findall(text)
        
        # 불용어 제거
        stopwords = {'것이다', '하였다', '있다고', '한다고', '라고', '때문에', 
                     '이라고', '따르면', '있으며', '있다는', '라며', '이라며',
                     '으로써', '에서는', '에서도', '들이', '에게'}
        
        return [k for k in keywords if k not in stopwords]


# 싱글톤 인스턴스
_fact_checker = None

def get_fact_checker() -> FactChecker:
    """Fact-Checker 싱글톤 인스턴스 반환"""
    global _fact_checker
    if _fact_checker is None:
        _fact_checker = FactChecker()
    return _fact_checker
