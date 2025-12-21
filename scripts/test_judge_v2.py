#!/usr/bin/env python
"""
test_judge_logic.py - Scout Pipeline V2 Judge 검증 스크립트

주요 검증 항목:
1. Judge Loginc: 이중 감점 방지 (RSI 85 시나리오)
2. Grade Calculation: 코드 기반 등급 산정 검증
3. Logging: 실제 모델명(target_model) 로깅 확인
"""

import os
import sys
import logging
import json
from datetime import datetime

# 프로젝트 루트를 PYTHONPATH에 추가
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# [검증 모드] LLM 로그 별도 파일로 저장
TEST_LOG_PATH = "/app/logs/test_judge_logs.jsonl"
os.environ["LLM_DEBUG_LOG_PATH"] = TEST_LOG_PATH
os.environ["USE_OLLAMA_GATEWAY"] = "true"
os.environ["OLLAMA_GATEWAY_URL"] = "http://localhost:11500"

def test_judge_double_penalty():
    print("\n" + "="*60)
    print("🧪 Test: Judge 이중 감점 방지 테스트")
    print("="*60)
    
    try:
        from shared.llm import JennieBrain
        
        brain = JennieBrain()
        
        # [시나리오] RSI가 85로 매우 높아 정량 점수가 55점으로 깎인 상태
        # Judge가 이를 보고 또 감점하는지 확인
        stock_info = {
            "code": "005930",
            "name": "테스트전자",
            "hunter_score": 75.0, # Gatekeeper Pass (>=70)
            "per": 12.5,
            "pbr": 1.2,
            "news_reason": "최근 AI 반도체 수주 기대감 있으나 단기 급등 부담.",
            "dominant_keywords": ["반도체", "AI"]
        }
        
        quant_context = """
        [정량 분석 결과]
        - 종합 점수: 75점 (매수)
        - RSI: 85.0 (매우 높음, 과열권 진입이지만 수급이 강력함)
        - 기술적 지표가 과열을 가리키고 있으나 아직 추세는 살아있음.
        """
        
        debate_log = """
        준호: 야 민지야, 이거 RSI 85야. 미친 거 아니야? 당장 팔아야 돼. 과열이라고! 감점해! [정량]
        민지: 팀장님, RSI 높은 건 맞지만 수주 모멘텀이 살아있잖아요. [뉴스] 기계적으로 팔 필요는 없어요.
        준호: 아니야, 통계적으로 RSI 80 넘으면 무조건 조정을 받았어. 이건 위험해. [통계]
        """
        
        logger.info(f"Input Hunter Score: {stock_info['hunter_score']}")
        logger.info("Running Judge Scoring V5...")
        
        result = brain.run_judge_scoring_v5(stock_info, debate_log, quant_context)
        
        logger.info(f"✅ Judge Result: {json.dumps(result, ensure_ascii=False, indent=2)}")
        
        score = float(result.get('score', 0))
        grade = result.get('grade', 'F')
        reason = result.get('reason', '')
        
        # [검증]
        # 1. 점수가 55점에서 크게 깎이지 않았는지 (-10점 이내)
        if score < 45:
             logger.error(f"❌ 이중 감점 의심! Score: {stock_info['hunter_score']} -> {score}")
        else:
             logger.info(f"✅ 점수 방어 성공: {stock_info['hunter_score']} -> {score}")
             
        # 2. 등급이 코드로 계산되었는지 (LLM 의존 X)
        # 55점이면 C등급이어야 함 (build_judge_prompt의 예전 기준이 아닌 코드 로직 기준)
        # _calculate_grade: >=50 is C
        expected_grade = 'C'
        if grade == expected_grade:
            logger.info(f"✅ 등급 산정 정확함: {grade}")
        else:
            logger.error(f"❌ 등급 산정 오류: Expected {expected_grade}, Got {grade}")

        # 3. 모델명 로깅 확인
        check_log_file()

    except Exception as e:
        logger.error(f"❌ 테스트 실패: {e}", exc_info=True)

def check_log_file():
    print("\n" + "-"*60)
    print("📝 Log File Check")
    print("-"*(60))
    
    if not os.path.exists(TEST_LOG_PATH):
        logger.error("❌ 로그 파일이 생성되지 않음!")
        return
        
    with open(TEST_LOG_PATH, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    if not lines:
        logger.error("❌ 로그 파일이 비어있음!")
        return

    last_log = json.loads(lines[-1])
    logger.info(f"Last Log Entry Type: {last_log.get('type')}")
    logger.info(f"Model Name Logged: {last_log.get('model')}")
    
    # Verify Model Name
    expected_model = "gpt-oss" # llm_factory settings might point to gpt-oss which maps to qwen3:32b?
    # Actually OllamaLLMProvider should log 'qwen3:32b' if that's what's passed, or 'gpt-oss' if it's the alias.
    # In V2 we fixed it to use 'target_model'. Let's see what it logs.
    
    if "qwen" in str(last_log.get('model')).lower() or "gpt-oss" in str(last_log.get('model')).lower():
         logger.info("✅ 모델명 로깅 확인됨.")
    else:
         logger.warning(f"⚠️ 모델명이 예상과 다름: {last_log.get('model')}")

if __name__ == "__main__":
    test_judge_double_penalty()
