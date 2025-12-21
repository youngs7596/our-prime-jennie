#!/usr/bin/env python3
"""
scripts/benchmark_llm.py

LLM 모델 및 Concurrency 성능 벤치마크 스크립트.
다양한 로컬 LLM 모델과 병렬처리(Worker) 수에 따른 안정성 및 처리 속도를 테스트합니다.

[변경사항]
- 요청 수: Case당 30회 (30개 종목 시뮬레이션)
- Fail-Fast: 한 건이라도 실패(Timeout/Error) 발생 시 해당 Case 즉시 중단
"""

import sys
import os
import time
import json
import logging
import concurrent.futures
import random
from typing import List, Dict

# 프로젝트 루트 경로 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.llm_providers import OllamaLLMProvider
from shared.llm_factory import ModelStateManager

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("Benchmark")

# 테스트 설정
MODELS = [
    # "qwen3:32b",
    # "gpt-oss:20b",
    "gemma3:27b",
    # "deepseek-r1:32b"
]

WORKER_COUNTS = [2, 4]
TOTAL_REQUESTS_PER_CASE = 16  # 30개 종목 테스트

# 30개의 더미 데이터 생성 (KV Cache 회피 및 리얼한 부하 테스트용)
SECTORS = ["반도체", "이차전지", "자동차", "바이오", "인터넷", "게임", "통신", "금융"]
NEWS_TEMPLATES = [
    "최근 글로벌 경기 침체 우려에도 불구하고 견조한 실적을 달성했습니다. 특히 북미 시장에서의 점유율 확대가 두드러지며, 신제품 출시 효과가 3분기부터 본격화될 것으로 예상됩니다. 다만, 원자재 가격 상승에 따른 이익률 훼손 우려는 여전히 존재합니다. CEO는 컨퍼런스 콜에서 '비용 절감을 위한 TF를 구성했다'고 밝혔지만, 시장 반응은 미지근합니다. 경쟁사 대비 밸류에이션 매력은 높으나 수급 상황이 좋지 않아 단기 반등은 제한적일 수 있습니다.",
    "대규모 수주 공시가 발표되면서 장 초반 강세를 보이고 있습니다. 이번 계약은 회사 창사 이래 최대 규모로, 내년 매출 성장에 크게 기여할 것으로 보입니다. 하지만 최근 유상증자 루머가 돌면서 주주들의 불안감이 커지고 있습니다. 회사 측은 '사실무근'이라고 부인했으나, 재무 구조 개선이 시급한 상황임은 부인할 수 없습니다. 외국인 투자자들은 3일 연속 순매도를 기록 중입니다.",
    "신약 임상 3상 결과 발표를 앞두고 바이오 섹터 전반에 기대감이 유입되고 있습니다. 동사는 경쟁 약물 대비 우수한 효능을 입증했다고 주장하고 있으며, FDA 승인 가능성을 높게 보고 있습니다. 그러나 임상 실패 리스크는 언제나 존재하며, 실패 시 주가 급락은 불가피합니다. 최근 공매도 잔고가 급증하고 있어 변동성 확대에 유의해야 합니다.",
    "정부의 규제 완화 수혜주로 부각되며 신고가를 경신했습니다. 정책 모멘텀은 당분간 지속될 것으로 보이나, 실적이 뒷받침되지 않는 단순 테마성 상승이라는 지적도 있습니다. PER 50배 수준의 고평가 논란이 있으며, 기관 투자자들은 차익 실현에 나서는 모습입니다. 기술적 분석상 과열 신호가 감지되므로 추격 매수는 자제하는 것이 좋습니다."
]

def generate_mock_stocks(n=30):
    stocks = []
    for i in range(n):
        # 뉴스 텍스트를 길게 만들기 위해 2~3개를 랜덤 조합
        news_summary = " ".join(random.sample(NEWS_TEMPLATES, k=2))
        
        stocks.append({
            "name": f"테스트종목_{i+1}",
            "code": f"{i:06d}",
            "price": random.randint(1000, 500000),
            "per": round(random.uniform(5.0, 50.0), 2),
            "pbr": round(random.uniform(0.5, 5.0), 2),
            "market_cap": f"{random.randint(1000, 50000)}억",
            "sector": random.choice(SECTORS),
            "news": news_summary
        })
    return stocks

MockStocks = generate_mock_stocks(TOTAL_REQUESTS_PER_CASE)

TEST_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer"},
        "grade": {"type": "string"},
        "reason": {"type": "string"}
    },
    "required": ["score", "grade", "reason"]
}

def build_prompt(stock):
    return f"""
당신은 주식 투자 전문가입니다. 다음 종목에 대해 심층 분석을 수행하고 JSON 형식으로 응답하세요.

[종목 정보]
- 종목명: {stock['name']} ({stock['code']})
- 현재가: {stock['price']}원
- PER: {stock['per']}
- PBR: {stock['pbr']}
- 시가총액: {stock['market_cap']}
- 섹터: {stock['sector']}

[최근 뉴스 요약 (중요)]
{stock['news']}

[분석 요구사항]
1. 이 종목의 재무 건전성과 성장성을 평가하세요.
2. 위 뉴스 요약을 바탕으로 현재의 기회와 리스크를 구체적으로 분석하세요.
3. 최종적으로 '매수', '매도', '보유' 중 하나의 의견을 제시하고, 그 이유를 논리적으로 설명하세요.
4. 반드시 JSON 형식으로만 응답해야 합니다.

JSON Schema:
{{
    "score": "integer (0-100)",
    "grade": "string (S/A/B/C/D)",
    "reason": "string (detailed analysis)"
}}
"""

def run_single_request(model: str, task_id: int, stock: Dict) -> Dict:
    """단일 LLM 요청 수행"""
    provider = OllamaLLMProvider(
        model=model,
        state_manager=ModelStateManager()
    )
    
    prompt = build_prompt(stock)
    start_ts = time.time()
    try:
        logger.info(f"    [Task-{task_id}] 요청 시작 ({stock['name']})")
        # Timeout은 Provider 기본값(보통 120s~300s)을 따르거나, 필요 시 override
        result = provider.generate_json(
            prompt=prompt,
            response_schema=TEST_SCHEMA,
            temperature=0.1
        )
        elapsed = time.time() - start_ts
        logger.info(f"    ✅ [Task-{task_id}] 성공 ({elapsed:.1f}s)")
        return {"success": True, "elapsed": elapsed, "error": None}
    except Exception as e:
        elapsed = time.time() - start_ts
        logger.error(f"    ❌ [Task-{task_id}] 실패 ({elapsed:.1f}s): {e}")
        return {"success": False, "elapsed": elapsed, "error": str(e)}

def run_benchmark_case(model: str, workers: int, total_reqs: int) -> Dict:
    """특정 모델 및 Worker 수에 대한 벤치마크 수행 (Fail-Fast 적용)"""
    logger.info(f"\n🚀 Case Start: Model={model}, Workers={workers}, TotalReqs={total_reqs}")
    
    start_time = time.time()
    results = []
    failed_early = False
    fail_reason = None
    
    # Python 3.9+ cancel_futures=True 지원
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        # Future -> Task ID 매핑
        future_to_id = {}
        for i in range(total_reqs):
            stock = MockStocks[i]
            future = executor.submit(run_single_request, model, i, stock)
            future_to_id[future] = i
        
        # as_completed로 완료되는 순서대로 확인
        try:
            for future in concurrent.futures.as_completed(future_to_id):
                result = future.result()
                results.append(result)
                
                if not result['success']:
                    logger.error(f"🚨 [Fail-Fast] Task Failed! Stopping remaining tasks for this case...")
                    failed_early = True
                    fail_reason = result['error']
                    
                    # 남은 대기중인 Future들 취소 시도
                    for f in future_to_id.keys():
                        f.cancel()
                    break # Loop 중단 -> Context Manager exit 호출 -> Shutdown waiting for running threads
                    
        except Exception as e:
            logger.error(f"🚨 [System Error] {e}")
            failed_early = True
            fail_reason = str(e)

    total_time = time.time() - start_time
    
    success_count = sum(1 for r in results if r['success'])
    fail_count = total_reqs - success_count if not failed_early else "STOPPED"
    
    if failed_early:
        logger.warning(f"🛑 Case Aborted due to failure. Success: {success_count}")
    else:
        # 분당 처리 건수 (Throughput)
        tpm = (success_count / total_time) * 60 if total_time > 0 else 0
        logger.info(f"🏁 Case Done: Success={success_count}/{total_reqs}, TotalTime={total_time:.1f}s, TPM={tpm:.1f}")
    
    avg_latency = 0
    max_latency = 0
    tpm = 0
    if not failed_early and success_count > 0:
        avg_latency = sum(r['elapsed'] for r in results) / success_count
        max_latency = max(r['elapsed'] for r in results)
        tpm = (success_count / total_time) * 60

    return {
        "model": model,
        "workers": workers,
        "total_reqs": total_reqs,
        "success": success_count,
        "failed_early": failed_early,
        "fail_reason": fail_reason,
        "total_time": total_time,
        "avg_latency": avg_latency,
        "max_latency": max_latency,
        "tpm": tpm
    }

def print_table(results: List[Dict]):
    """결과 테이블 출력"""
    print("\n" + "="*120)
    print(f"{'Model':<20} | {'W':<3} | {'Result':<15} | {'Time(s)':<8} | {'AvgLat':<8} | {'TPM':<8} | {'Note':<20}")
    print("-" * 120)
    
    best_tpm = 0
    best_config = None
    
    for r in results:
        status_str = f"{r['success']}/{r['total_reqs']}"
        if r['failed_early']:
            status_str = "ABORTED"
            note = f"❌ Error: {r['fail_reason'][:15]}..."
        else:
            note = ""
            if r['tpm'] > best_tpm:
                best_tpm = r['tpm']
                best_config = f"{r['model']} ({r['workers']}w)"
                note = "🏆 Best Speed"
            
        print(f"{r['model']:<20} | {r['workers']:<3} | {status_str:<15} | {r['total_time']:<8.1f} | {r['avg_latency']:<8.1f} | {r['tpm']:<8.1f} | {note:<20}")
    print("="*120)
    if best_config:
        print(f"\n🏅 Winner: {best_config} with {best_tpm:.1f} TPM (Approx. {int(best_tpm*60)} requests/hour)")
    else:
        print("\n⚠️ No successful configuration found.")

def main():
    # 환경 변수 설정
    if not os.getenv("OLLAMA_GATEWAY_URL"):
        os.environ["OLLAMA_GATEWAY_URL"] = "http://localhost:11500"
        
    # Gateway 사용 강제
    os.environ["USE_OLLAMA_GATEWAY"] = "true"

    print("\n🏎️  LLM Stress Test Benchmark (Fail-Fast Mode)")
    print(f"Models: {MODELS}")
    print(f"Workers: {WORKER_COUNTS}")
    print(f"Requests per Case: {TOTAL_REQUESTS_PER_CASE} (Unique Stocks)")
    print("Condition: Stop immediately on ANY failure.")
    
    all_results = []
    
    for model in MODELS:
        print(f"\n==================================================")
        print(f"🤖 Testing Model: {model}")
        print(f"==================================================")
        
        for workers in WORKER_COUNTS:
            result = run_benchmark_case(model, workers, TOTAL_REQUESTS_PER_CASE)
            all_results.append(result)
            
            # 실패했으면 해당 모델의 더 높은 Worker 테스트는 의미가 없을 확률이 큼 (이미 과부하)
            # 하지만 User request는 "멈추는걸로"가 "테스트 전체"인지 "해당 케이스"인지 모호함.
            # "한번이라도 실패하면 그 즉시 테스트는 멈추는걸로" -> Case 중단을 의미한다고 해석.
            # 만약 Worker=2에서 실패하면 Worker=3, 4도 실패할 것이 뻔하므로 모델 자체를 스킵하는게 효율적일 수 있음.
            # 여기서는 Case만 멈추고 다음 Worker 테스트로 넘어갈지, 모델 전체를 스킵할지 고민.
            # 보통 안정성 테스트니, 2에서 터지면 3은 볼 필요 없음.
            
            if result['failed_early']:
                print(f"⚠️  Skipping higher worker counts for {model} due to failure at {workers} workers.")
                break # 다음 모델로 넘어감
            
            time.sleep(3) # Cool-down
            
    print_table(all_results)
    print("\n✅ Benchmark Completed.")

if __name__ == "__main__":
    main()
