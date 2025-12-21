#!/usr/bin/env python3
"""
scripts/test_llm_models.py

LLM 모델 연결 테스트 스크립트
- Gemini 3.0 Pro (Self-Evolution Daily Feedback)
- GPT 5.2 (Weekly Council)
"""

import os
import sys
import logging

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("LLM-Test")

def test_gpt_5_2_thinking():
    """Test GPT 5.2 (THINKING Tier for Daily Self-Evolution)"""
    logger.info("=" * 60)
    logger.info("🧪 [Test 1] GPT 5.2 (Daily Self-Evolution - THINKING Tier)")
    logger.info("=" * 60)
    
    try:
        from shared.llm_providers import OpenAILLMProvider
        
        provider = OpenAILLMProvider()
        test_model = "gpt-5.2"
        
        logger.info(f"   Model: {test_model}")
        logger.info(f"   Sending test prompt...")
        
        result = provider.generate_json(
            prompt="Return a JSON object with exactly one key 'status' and value 'ok'. Nothing else.",
            response_schema={
                "type": "object",
                "properties": {"status": {"type": "string"}},
                "required": ["status"]
            },
            temperature=0.1,
            model_name=test_model
        )
        
        if result.get("status") == "ok":
            logger.info(f"   ✅ SUCCESS! Response: {result}")
            return True
        else:
            logger.warning(f"   ⚠️ Unexpected response: {result}")
            return False
            
    except Exception as e:
        logger.error(f"   ❌ FAILED: {e}")
        return False


def test_gpt_5_2():
    """Test GPT 5.2 (Weekly Council - Junho)"""
    logger.info("=" * 60)
    logger.info("🧪 [Test 2] GPT 5.2 (Weekly Council)")
    logger.info("=" * 60)
    
    try:
        from shared.llm_providers import OpenAILLMProvider
        
        provider = OpenAILLMProvider()
        
        test_model = "gpt-5.2"
        
        logger.info(f"   Model: {test_model}")
        logger.info(f"   Sending test prompt...")
        
        result = provider.generate_json(
            prompt="Return a JSON object with exactly one key 'status' and value 'ok'. Nothing else.",
            response_schema={
                "type": "object",
                "properties": {"status": {"type": "string"}},
                "required": ["status"]
            },
            temperature=0.1,
            model_name=test_model
        )
        
        if result.get("status") == "ok":
            logger.info(f"   ✅ SUCCESS! Response: {result}")
            return True
        else:
            logger.warning(f"   ⚠️ Unexpected response: {result}")
            return False
            
    except Exception as e:
        logger.error(f"   ❌ FAILED: {e}")
        return False


def main():
    logger.info("🚀 Starting LLM Model Connection Tests...")
    logger.info("")
    
    results = {
        "GPT 5.2 (THINKING)": test_gpt_5_2_thinking(),
        "GPT 5.2 (Weekly Council)": test_gpt_5_2()
    }
    
    logger.info("")
    logger.info("=" * 60)
    logger.info("📊 TEST RESULTS")
    logger.info("=" * 60)
    
    all_passed = True
    for model, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        logger.info(f"   {model}: {status}")
        if not passed:
            all_passed = False
    
    logger.info("=" * 60)
    
    if all_passed:
        logger.info("🎉 All tests passed!")
        sys.exit(0)
    else:
        logger.error("⚠️ Some tests failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
