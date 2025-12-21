#!/usr/bin/env python
"""
test_debate_issue.py - Bull vs Bear 토론 빈 로그 문제 디버깅

Scout Judge 단계에서 "Bull vs Bear 토론 로그가 비어 있어" 문제 재현 및 디버깅
"""

import os
import sys
import logging
import json
import requests

# 프로젝트 루트를 PYTHONPATH에 추가
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# 로깅 설정
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_gateway_chat_direct():
    """
    1. Ollama Gateway /api/chat 엔드포인트 직접 테스트
    """
    print("\n" + "="*60)
    print("🧪 Test 1: Ollama Gateway /api/chat 직접 호출")
    print("="*60)
    
    gateway_url = os.getenv("OLLAMA_GATEWAY_URL", "http://localhost:11500")
    
    payload = {
        "model": "qwen3:32b",
        "messages": [
            {"role": "user", "content": "간단히 '안녕하세요'라고만 답해주세요."}
        ],
        "options": {
            "temperature": 0.7,
            "num_ctx": 8192
        }
    }
    
    try:
        logger.info(f"Gateway URL: {gateway_url}/api/chat")
        logger.info(f"Payload: {json.dumps(payload, ensure_ascii=False, indent=2)}")
        
        response = requests.post(
            f"{gateway_url}/api/chat",
            json=payload,
            timeout=120
        )
        
        logger.info(f"Status Code: {response.status_code}")
        logger.info(f"Response Headers: {dict(response.headers)}")
        
        result = response.json()
        logger.info(f"Response JSON: {json.dumps(result, ensure_ascii=False, indent=2)}")
        
        # 응답 구조 확인
        if "message" in result:
            content = result["message"].get("content", "")
            logger.info(f"✅ message.content: '{content[:200]}...' (len={len(content)})")
        else:
            logger.warning(f"⚠️ 'message' 키가 없음! Keys: {result.keys()}")
        
        return result
        
    except Exception as e:
        logger.error(f"❌ Gateway 호출 실패: {e}")
        return None


def test_ollama_chat_direct():
    """
    2. Ollama 서버 /api/chat 직접 테스트 (Gateway 우회)
    """
    print("\n" + "="*60)
    print("🧪 Test 2: Ollama 서버 /api/chat 직접 호출 (Gateway 우회)")
    print("="*60)
    
    ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    
    payload = {
        "model": "qwen3:32b",
        "messages": [
            {"role": "user", "content": "간단히 '안녕하세요'라고만 답해주세요."}
        ],
        "stream": False,
        "keep_alive": -1,
        "options": {
            "temperature": 0.7,
            "num_ctx": 8192
        }
    }
    
    try:
        logger.info(f"Ollama URL: {ollama_host}/api/chat")
        
        response = requests.post(
            f"{ollama_host}/api/chat",
            json=payload,
            timeout=120
        )
        
        logger.info(f"Status Code: {response.status_code}")
        
        result = response.json()
        logger.info(f"Response JSON: {json.dumps(result, ensure_ascii=False, indent=2)}")
        
        if "message" in result:
            content = result["message"].get("content", "")
            logger.info(f"✅ message.content: '{content[:200]}...' (len={len(content)})")
        
        return result
        
    except Exception as e:
        logger.error(f"❌ Ollama 직접 호출 실패: {e}")
        return None


def test_debate_session_via_llm():
    """
    3. JennieBrain.run_debate_session() 직접 테스트
    """
    print("\n" + "="*60)
    print("🧪 Test 3: JennieBrain.run_debate_session() 테스트")
    print("="*60)
    
    # 환경 변수 설정 (Gateway 모드)
    os.environ["USE_OLLAMA_GATEWAY"] = "true"
    os.environ["OLLAMA_GATEWAY_URL"] = "http://localhost:11500"
    
    try:
        from shared.llm import JennieBrain
        
        brain = JennieBrain()
        
        # 테스트용 stock_info
        stock_info = {
            "code": "005930",
            "name": "삼성전자",
            "sector": "반도체",
            "current_price": 55000,
            "hunter_score": 85.0,
            "quant_score": 60.0,
            "dominant_keywords": ["AI", "반도체"]
        }
        
        logger.info(f"Input stock_info: {stock_info}")
        
        result = brain.run_debate_session(
            stock_info=stock_info,
            hunter_score=85
        )
        
        logger.info(f"Debate Result Type: {type(result)}")
        logger.info(f"Debate Result Length: {len(result) if result else 0}")
        logger.info(f"Debate Result: {result[:500] if result else 'EMPTY'}...")
        
        if not result or result.strip() == "" or "Error" in result:
            logger.warning("⚠️ 토론 결과가 비어있거나 에러 발생!")
        else:
            logger.info("✅ 토론 결과 정상 생성")
        
        return result
        
    except Exception as e:
        logger.error(f"❌ Debate 세션 테스트 실패: {e}", exc_info=True)
        return None


def test_llm_provider_generate_chat():
    """
    4. OllamaLLMProvider.generate_chat() 직접 테스트
    """
    print("\n" + "="*60)
    print("🧪 Test 4: OllamaLLMProvider.generate_chat() 직접 테스트")
    print("="*60)
    
    os.environ["USE_OLLAMA_GATEWAY"] = "true"
    os.environ["OLLAMA_GATEWAY_URL"] = "http://localhost:11500"
    
    try:
        from shared.llm_factory import OllamaStateManager
        from shared.llm_providers import OllamaLLMProvider
        
        state_manager = OllamaStateManager()
        provider = OllamaLLMProvider(
            model="qwen3:32b",
            state_manager=state_manager,
            is_fast_tier=False,
            is_thinking_tier=False
        )
        
        chat_history = [
            {"role": "user", "content": "간단히 '안녕하세요'라고만 답해주세요."}
        ]
        
        logger.info(f"Chat History: {chat_history}")
        
        result = provider.generate_chat(chat_history, temperature=0.7)
        
        logger.info(f"Result Type: {type(result)}")
        logger.info(f"Result: {result}")
        
        if isinstance(result, dict):
            text = result.get("text", "")
            logger.info(f"Text Length: {len(text)}")
            if not text.strip():
                logger.warning("⚠️ text가 비어있음!")
            else:
                logger.info(f"✅ Response: {text[:200]}...")
        
        return result
        
    except Exception as e:
        logger.error(f"❌ generate_chat 테스트 실패: {e}", exc_info=True)
        return None


if __name__ == "__main__":
    print("="*60)
    print("🔍 Bull vs Bear 토론 빈 로그 문제 디버깅")
    print("="*60)
    
    # Test 1: Gateway 직접 호출
    result1 = test_gateway_chat_direct()
    
    # Test 2: Ollama 서버 직접 호출
    result2 = test_ollama_chat_direct()
    
    # Test 3: JennieBrain 테스트
    result3 = test_debate_session_via_llm()
    
    # Test 4: Provider 테스트
    result4 = test_llm_provider_generate_chat()
    
    print("\n" + "="*60)
    print("📊 테스트 결과 요약")
    print("="*60)
    print(f"Test 1 (Gateway /api/chat): {'✅ PASS' if result1 else '❌ FAIL'}")
    print(f"Test 2 (Ollama Direct):     {'✅ PASS' if result2 else '❌ FAIL'}")
    print(f"Test 3 (JennieBrain):       {'✅ PASS' if result3 and len(str(result3)) > 20 else '❌ FAIL'}")
    print(f"Test 4 (Provider):          {'✅ PASS' if result4 else '❌ FAIL'}")
