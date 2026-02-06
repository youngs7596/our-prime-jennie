#!/usr/bin/env python3
"""
PoC: CloudFailoverProvider 실제 API 호출 테스트

Usage:
    python scripts/poc_cloud_failover.py
    python scripts/poc_cloud_failover.py --provider openrouter
    python scripts/poc_cloud_failover.py --provider deepseek
    python scripts/poc_cloud_failover.py --provider ollama_cloud
    python scripts/poc_cloud_failover.py --provider failover   # 전체 체인
"""
import sys
import os
import json
import time
import argparse

# 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("SECRETS_FILE", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "secrets.json"))

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
logger = logging.getLogger("poc")

from shared.auth import get_secret
from shared.llm_providers import OpenAILLMProvider, OllamaLLMProvider, CloudFailoverProvider
from shared.llm_factory import ModelStateManager

# 테스트 프롬프트 (간단한 JSON 응답 요청)
TEST_PROMPT = """다음 종목을 간단히 분석해주세요. JSON으로 응답하세요.
종목: 삼성전자 (005930)
현재가: 58,000원

응답 형식:
{"ticker": "005930", "name": "삼성전자", "signal": "BUY 또는 HOLD 또는 SELL", "reason": "간단한 이유"}
"""

TEST_SCHEMA = {
    "type": "object",
    "required": ["ticker", "name", "signal", "reason"],
}


def test_openrouter():
    """OpenRouter 단독 테스트"""
    api_key = get_secret("openrouter-api-key")
    if not api_key:
        logger.error("openrouter-api-key 없음")
        return False

    logger.info("=== OpenRouter (deepseek/deepseek-v3.2) ===")
    provider = OpenAILLMProvider(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
        default_model="deepseek/deepseek-v3.2",
    )

    start = time.time()
    try:
        result = provider.generate_json(TEST_PROMPT, TEST_SCHEMA)
        elapsed = time.time() - start
        logger.info(f"✅ OpenRouter 성공 ({elapsed:.1f}s)")
        logger.info(f"   응답: {json.dumps(result, ensure_ascii=False, indent=2)}")
        return True
    except Exception as e:
        elapsed = time.time() - start
        logger.error(f"❌ OpenRouter 실패 ({elapsed:.1f}s): {e}")
        return False


def test_deepseek():
    """DeepSeek 공식 API 단독 테스트"""
    api_key = get_secret("deepseek-api-key")
    if not api_key:
        logger.error("deepseek-api-key 없음")
        return False

    logger.info("=== DeepSeek API (deepseek-chat) ===")
    provider = OpenAILLMProvider(
        base_url="https://api.deepseek.com",
        api_key=api_key,
        default_model="deepseek-chat",
    )

    start = time.time()
    try:
        result = provider.generate_json(TEST_PROMPT, TEST_SCHEMA)
        elapsed = time.time() - start
        logger.info(f"✅ DeepSeek 성공 ({elapsed:.1f}s)")
        logger.info(f"   응답: {json.dumps(result, ensure_ascii=False, indent=2)}")
        return True
    except Exception as e:
        elapsed = time.time() - start
        logger.error(f"❌ DeepSeek 실패 ({elapsed:.1f}s): {e}")
        return False


def test_ollama_cloud():
    """Ollama Cloud 단독 테스트"""
    logger.info("=== Ollama Cloud (deepseek-v3.2:cloud) ===")
    provider = OllamaLLMProvider(
        model="deepseek-v3.2:cloud",
        state_manager=ModelStateManager(),
    )

    if not provider._cloud_api_key:
        logger.error("ollama-api-key 없음")
        return False

    start = time.time()
    try:
        result = provider.generate_json(TEST_PROMPT, TEST_SCHEMA)
        elapsed = time.time() - start
        logger.info(f"✅ Ollama Cloud 성공 ({elapsed:.1f}s)")
        logger.info(f"   응답: {json.dumps(result, ensure_ascii=False, indent=2)}")
        return True
    except Exception as e:
        elapsed = time.time() - start
        logger.error(f"❌ Ollama Cloud 실패 ({elapsed:.1f}s): {e}")
        return False


def test_failover():
    """CloudFailoverProvider 전체 체인 테스트"""
    logger.info("=== CloudFailoverProvider (전체 체인) ===")

    start = time.time()
    try:
        provider = CloudFailoverProvider(tier_name="REASONING")
        logger.info(f"   체인: {' → '.join(provider._provider_names)}")

        result = provider.generate_json(TEST_PROMPT, TEST_SCHEMA)
        elapsed = time.time() - start
        logger.info(f"✅ Failover 체인 성공 ({elapsed:.1f}s)")
        logger.info(f"   응답: {json.dumps(result, ensure_ascii=False, indent=2)}")
        return True
    except Exception as e:
        elapsed = time.time() - start
        logger.error(f"❌ Failover 체인 실패 ({elapsed:.1f}s): {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="CloudFailoverProvider PoC")
    parser.add_argument(
        "--provider",
        choices=["openrouter", "deepseek", "ollama_cloud", "failover", "all"],
        default="all",
        help="테스트할 프로바이더 (기본: all)",
    )
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("CloudFailoverProvider PoC 시작")
    logger.info("=" * 60)

    # API 키 상태 확인
    or_key = get_secret("openrouter-api-key")
    ds_key = get_secret("deepseek-api-key")
    ol_key = get_secret("ollama-api-key") or get_secret("ollama_api_key")
    logger.info(f"API 키 상태: OpenRouter={'✅' if or_key else '❌'}  DeepSeek={'✅' if ds_key else '❌'}  Ollama={'✅' if ol_key else '❌'}")
    logger.info("")

    results = {}

    if args.provider in ("openrouter", "all"):
        results["OpenRouter"] = test_openrouter()
        print()

    if args.provider in ("deepseek", "all"):
        results["DeepSeek"] = test_deepseek()
        print()

    if args.provider in ("ollama_cloud", "all"):
        results["OllamaCloud"] = test_ollama_cloud()
        print()

    if args.provider in ("failover", "all"):
        results["Failover"] = test_failover()
        print()

    # 결과 요약
    logger.info("=" * 60)
    logger.info("결과 요약:")
    for name, ok in results.items():
        logger.info(f"  {name}: {'✅ PASS' if ok else '❌ FAIL'}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
