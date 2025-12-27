#!/usr/bin/env python3
"""
scripts/test_hunter_ollama.py

Hunter 단계 Ollama 모델 성능 테스트 스크립트
- 모델별 응답 시간 측정
- 병렬 처리 안정성 테스트
- JSON 파싱 성공률 확인

사용법:
    python scripts/test_hunter_ollama.py --model gemma3:27b --workers 4 --count 5
"""

import os
import sys
import time
import json
import argparse
import logging
import pytest

# CI 환경에서는 외부 Ollama/gateway 의존성이 없으므로 스킵
pytest.skip("Requires external Ollama/gateway; skip in CI", allow_module_level=True)
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Tuple

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("Hunter-Test")

# 테스트용 종목 데이터 (실제 Hunter에서 사용하는 형태)
TEST_STOCKS = [
    {"code": "005930", "name": "삼성전자", "per": 12.3, "pbr": 1.05, "news": "반도체 업황 개선 기대"},
    {"code": "000660", "name": "SK하이닉스", "per": 8.5, "pbr": 1.32, "news": "HBM 수요 급증"},
    {"code": "035420", "name": "NAVER", "per": 25.1, "pbr": 1.45, "news": "AI 서비스 확대"},
    {"code": "051910", "name": "LG화학", "per": 15.2, "pbr": 0.95, "news": "배터리 사업 분리 검토"},
    {"code": "006400", "name": "삼성SDI", "per": 18.3, "pbr": 1.12, "news": "전고체 배터리 개발 진척"},
    {"code": "035720", "name": "카카오", "per": 45.2, "pbr": 2.15, "news": "광고 매출 회복"},
    {"code": "105560", "name": "KB금융", "per": 5.8, "pbr": 0.45, "news": "NIM 개선 기대"},
    {"code": "055550", "name": "신한지주", "per": 5.2, "pbr": 0.42, "news": "배당 확대 발표"},
]

# Hunter 프롬프트 (간소화 버전)
HUNTER_PROMPT_TEMPLATE = """당신은 데이터 기반 주식 분석 AI입니다.

## 종목 정보
종목: {name} ({code})

## 정량 지표
- PER: {per}
- PBR: {pbr}

## 최신 뉴스
{news}

## 평가 기준
- 80점 이상: 강력 추천
- 60-79점: 추천
- 40-59점: 중립
- 40점 미만: 비추천

JSON 응답: {{"score": 숫자, "grade": "등급(S/A/B/C/D)", "reason": "판단 이유(한국어 20자 이내)"}}

⚠️ 반드시 위 JSON 형식으로만 응답하세요.
"""

def create_ollama_provider(model_name: str):
    """Ollama Provider 생성"""
    from shared.llm_providers import OllamaLLMProvider
    from shared.llm_factory import ModelStateManager
    
    return OllamaLLMProvider(
        model=model_name,
        state_manager=ModelStateManager(),
        is_fast_tier=False,
        is_thinking_tier=False
    )


def test_single_stock(provider, stock: Dict, test_id: int) -> Tuple[bool, float, Dict]:
    """
    단일 종목 Hunter 분석 테스트
    
    Returns:
        (success, elapsed_time, result)
    """
    prompt = HUNTER_PROMPT_TEMPLATE.format(
        name=stock["name"],
        code=stock["code"],
        per=stock["per"],
        pbr=stock["pbr"],
        news=stock["news"]
    )
    
    response_schema = {
        "type": "object",
        "properties": {
            "score": {"type": "number"},
            "grade": {"type": "string"},
            "reason": {"type": "string"}
        },
        "required": ["score", "grade", "reason"]
    }
    
    start_time = time.time()
    
    try:
        result = provider.generate_json(
            prompt=prompt,
            response_schema=response_schema,
            temperature=0.2
        )
        elapsed = time.time() - start_time
        
        # 결과 검증
        if "score" in result and "grade" in result:
            logger.info(f"   ✅ [{test_id}] {stock['name']}: {result['score']}점 ({result['grade']}) - {elapsed:.1f}초")
            return True, elapsed, result
        else:
            logger.warning(f"   ⚠️ [{test_id}] {stock['name']}: 불완전한 응답 - {elapsed:.1f}초")
            return False, elapsed, result
            
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"   ❌ [{test_id}] {stock['name']}: {str(e)[:50]} - {elapsed:.1f}초")
        return False, elapsed, {"error": str(e)}


def run_sequential_test(model_name: str, count: int) -> Dict:
    """순차 처리 테스트"""
    logger.info(f"\n{'='*60}")
    logger.info(f"🔄 순차 처리 테스트 (model: {model_name}, count: {count})")
    logger.info(f"{'='*60}")
    
    provider = create_ollama_provider(model_name)
    
    results = []
    total_start = time.time()
    
    for i in range(count):
        stock = TEST_STOCKS[i % len(TEST_STOCKS)]
        success, elapsed, result = test_single_stock(provider, stock, i + 1)
        results.append({"success": success, "elapsed": elapsed, "result": result})
    
    total_elapsed = time.time() - total_start
    
    success_count = sum(1 for r in results if r["success"])
    avg_time = sum(r["elapsed"] for r in results) / len(results) if results else 0
    
    return {
        "mode": "sequential",
        "model": model_name,
        "count": count,
        "success": success_count,
        "failed": count - success_count,
        "success_rate": f"{success_count/count*100:.1f}%",
        "total_time": f"{total_elapsed:.1f}s",
        "avg_time": f"{avg_time:.1f}s"
    }


def run_parallel_test(model_name: str, count: int, workers: int) -> Dict:
    """병렬 처리 테스트"""
    logger.info(f"\n{'='*60}")
    logger.info(f"⚡ 병렬 처리 테스트 (model: {model_name}, count: {count}, workers: {workers})")
    logger.info(f"{'='*60}")
    
    provider = create_ollama_provider(model_name)
    
    results = []
    total_start = time.time()
    
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {}
        for i in range(count):
            stock = TEST_STOCKS[i % len(TEST_STOCKS)]
            future = executor.submit(test_single_stock, provider, stock, i + 1)
            futures[future] = i
        
        for future in as_completed(futures):
            try:
                success, elapsed, result = future.result()
                results.append({"success": success, "elapsed": elapsed, "result": result})
            except Exception as e:
                logger.error(f"   ❌ Thread error: {e}")
                results.append({"success": False, "elapsed": 0, "result": {"error": str(e)}})
    
    total_elapsed = time.time() - total_start
    
    success_count = sum(1 for r in results if r["success"])
    avg_time = sum(r["elapsed"] for r in results) / len(results) if results else 0
    
    return {
        "mode": f"parallel (workers={workers})",
        "model": model_name,
        "count": count,
        "success": success_count,
        "failed": count - success_count,
        "success_rate": f"{success_count/count*100:.1f}%",
        "total_time": f"{total_elapsed:.1f}s",
        "avg_time": f"{avg_time:.1f}s",
        "throughput": f"{count/total_elapsed:.2f} req/s"
    }


def main():
    parser = argparse.ArgumentParser(description="Hunter Ollama 모델 테스트")
    parser.add_argument("--model", type=str, default="gemma3:27b", help="테스트할 모델명")
    parser.add_argument("--workers", type=int, default=4, help="병렬 처리 worker 수")
    parser.add_argument("--count", type=int, default=5, help="테스트할 종목 수")
    parser.add_argument("--sequential-only", action="store_true", help="순차 처리만 테스트")
    parser.add_argument("--parallel-only", action="store_true", help="병렬 처리만 테스트")
    
    args = parser.parse_args()
    
    logger.info(f"🚀 Hunter Ollama 테스트 시작")
    logger.info(f"   모델: {args.model}")
    logger.info(f"   종목 수: {args.count}")
    logger.info(f"   병렬 Workers: {args.workers}")
    
    results = []
    
    # 순차 처리 테스트
    if not args.parallel_only:
        seq_result = run_sequential_test(args.model, args.count)
        results.append(seq_result)
    
    # 병렬 처리 테스트
    if not args.sequential_only:
        par_result = run_parallel_test(args.model, args.count, args.workers)
        results.append(par_result)
    
    # 결과 요약
    logger.info(f"\n{'='*60}")
    logger.info(f"📊 테스트 결과 요약")
    logger.info(f"{'='*60}")
    
    for r in results:
        logger.info(f"\n[{r['mode']}]")
        logger.info(f"   모델: {r['model']}")
        logger.info(f"   성공/실패: {r['success']}/{r['failed']} ({r['success_rate']})")
        logger.info(f"   총 소요시간: {r['total_time']}")
        logger.info(f"   평균 응답시간: {r['avg_time']}")
        if "throughput" in r:
            logger.info(f"   처리량: {r['throughput']}")
    
    logger.info(f"\n{'='*60}")
    
    # 모든 테스트 성공 여부
    all_success = all(r["failed"] == 0 for r in results)
    if all_success:
        logger.info("🎉 모든 테스트 통과!")
        return 0
    else:
        logger.warning("⚠️ 일부 테스트 실패")
        return 1


if __name__ == "__main__":
    sys.exit(main())

