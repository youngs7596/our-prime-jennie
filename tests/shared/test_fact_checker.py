# tests/shared/test_fact_checker.py
# Fact-Checker 유닛 테스트

import pytest
from shared.fact_checker import FactChecker, FactCheckResult, get_fact_checker


class TestFactChecker:
    """FactChecker 테스트"""
    
    @pytest.fixture
    def checker(self):
        return FactChecker()
    
    def test_check_empty_input(self, checker):
        """빈 입력 처리"""
        result = checker.check("", "")
        assert result.is_valid is True
        assert result.confidence == 0.0
        assert "검증 데이터 부족" in result.warnings
    
    def test_check_numbers_match(self, checker):
        """숫자 매칭 검증"""
        original = "삼성전자가 1조 5000억원의 투자를 발표했다. 주가는 75,000원이다."
        analysis = "삼성전자는 1조 5000억원 투자 계획을 밝혔으며, 현재 주가 75,000원에 거래 중이다."
        
        result = checker.check(original, analysis)
        
        assert result.details['numbers']['valid'] is True
        assert result.details['numbers']['score'] >= 0.5
    
    def test_check_numbers_hallucination(self, checker):
        """숫자 환각 탐지"""
        original = "삼성전자가 1조원의 투자를 발표했다."
        analysis = "삼성전자는 5조원 투자와 30% 성장을 전망했다."  # 환각
        
        result = checker.check(original, analysis)
        
        # 숫자 불일치로 인해 경고
        assert len(result.warnings) > 0 or result.details['numbers']['score'] < 0.5
    
    def test_check_dates_match(self, checker):
        """날짜 매칭 검증"""
        original = "2024년 12월 15일에 발표된 계획에 따르면"
        analysis = "12월 15일 발표에 의하면 2024년 계획이 진행 중이다."
        
        result = checker.check(original, analysis)
        assert result.details['dates']['valid'] is True
    
    def test_check_keywords_hallucination(self, checker):
        """키워드 환각 탐지"""
        original = "삼성전자가 반도체 공장 증설을 발표했다."
        analysis = "삼성전자가 전기차 배터리 사업과 ESG 경영을 강화한다."  # 원문에 없는 키워드
        
        result = checker.check(original, analysis, stock_name="삼성전자")
        
        # 키워드 불일치 - 원문에 없는 "전기차", "배터리", "ESG" 등
        assert result.details['keywords']['score'] < 1.0
    
    def test_check_valid_analysis(self, checker):
        """정상 분석 검증"""
        original = """
        SK하이닉스가 HBM(고대역폭메모리) 생산을 확대한다고 발표했다.
        2025년까지 10조원을 투자해 이천 공장을 증설할 예정이다.
        AI 반도체 수요 증가에 대응하기 위한 전략이다.
        """
        analysis = """
        SK하이닉스는 HBM 생산 확대를 위해 10조원 투자를 계획 중이다.
        이천 공장 증설을 통해 AI 반도체 수요에 대응할 전망이다.
        """
        
        result = checker.check(original, analysis, stock_name="SK하이닉스")
        
        assert result.is_valid is True
        assert result.confidence >= 0.5
        assert not result.has_hallucination
    
    def test_singleton_instance(self):
        """싱글톤 인스턴스 확인"""
        checker1 = get_fact_checker()
        checker2 = get_fact_checker()
        assert checker1 is checker2

    def test_check_quant_context_match(self, checker):
        """정량 데이터 컨텍스트 포함 시 검증 성공"""
        news_text = "삼성전자는 최근 반도체 업황 둔화로 어려움을 겪고 있다."
        
        # 단순화된 컨텍스트 (줄바꿈 이슈 방지)
        quant_context = "총점: 58.9점, 모멘텀: 15.0점, 가치: 12.0점"
        snapshot_context = "PER: 10.5 | PBR: 0.90 | 시가총액: 400조원"
        
        # LLM 분석 (키워드 매칭을 위해 정확한 단어 사용)
        analysis = "정량 총점 58.9점이며, PBR 0.90 배이다."
        
        # 1. 뉴스만 제공 시 -> 실패 (숫자 불일치)
        result_fail = checker.check(news_text, analysis, stock_name="삼성전자")
        assert result_fail.details['numbers']['valid'] is False
        
        # 2. 정량 컨텍스트 + 스냅샷 포함 제공 시 -> 성공
        full_context = f"{news_text}\n\n[정량 분석 리포트]\n{quant_context}\n\n[재무 데이터]\n{snapshot_context}"
        result_pass = checker.check(full_context, analysis, stock_name="삼성전자")
        
        # 숫자 검증 성공 확인
        assert result_pass.details['numbers']['valid'] is True
        # 키워드 검증 성공 확인 (총점, PBR 등은 원문에 존재)
        assert result_pass.details['keywords']['valid'] is True
        assert len(result_pass.warnings) == 0


class TestFactCheckResult:
    """FactCheckResult 테스트"""
    
    def test_has_hallucination_low_confidence(self):
        """낮은 신뢰도 = 환각"""
        result = FactCheckResult(
            is_valid=True,
            confidence=0.3,
            warnings=[],
            details={}
        )
        assert result.has_hallucination is True
    
    def test_has_hallucination_invalid(self):
        """is_valid False = 환각"""
        result = FactCheckResult(
            is_valid=False,
            confidence=0.8,
            warnings=["Warning"],
            details={}
        )
        assert result.has_hallucination is True
    
    def test_no_hallucination(self):
        """정상 결과"""
        result = FactCheckResult(
            is_valid=True,
            confidence=0.8,
            warnings=[],
            details={}
        )
        assert result.has_hallucination is False
    

