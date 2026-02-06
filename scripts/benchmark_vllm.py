#!/usr/bin/env python3
"""
vLLM Qwen3-32B-AWQ 벤치마크 스크립트
- Ollama 벤치마크와 동일한 프롬프트 사용
- OpenAI-compatible Chat API (localhost:8001)
"""

import json
import time
import requests
import sys
from datetime import datetime

VLLM_URL = "http://localhost:8001"
MODEL = "LGAI-EXAONE/EXAONE-4.0-32B-AWQ"

# ============================================================================
# 테스트 뉴스 데이터 (Ollama 벤치마크와 동일)
# ============================================================================
TEST_NEWS_ITEMS = [
    {
        "id": 1,
        "title": "삼성전자, 차세대 HBM4 양산 성공… 엔비디아 공급망 합류",
        "summary": "삼성전자가 차세대 고대역폭메모리(HBM4) 양산에 성공하며 엔비디아 공급망에 합류했다. "
                   "업계에서는 SK하이닉스가 독점하던 HBM 시장에서 삼성전자가 본격적인 경쟁 구도를 "
                   "형성할 것으로 전망하고 있다. 증권가에서는 삼성전자의 반도체 부문 실적 개선이 "
                   "가시화될 것으로 보고 있다."
    },
    {
        "id": 2,
        "title": "카카오, 개인정보 유출 사고 발생… 이용자 230만명 피해",
        "summary": "카카오 계열사에서 대규모 개인정보 유출 사고가 발생해 약 230만명의 이용자 정보가 "
                   "외부로 유출된 것으로 확인됐다. 개인정보보호위원회는 즉시 조사에 착수했으며, "
                   "과징금 부과를 검토 중이다. 카카오 주가는 장중 5% 이상 급락했다."
    },
    {
        "id": 3,
        "title": "현대차, 美 조지아 전기차 공장 가동 개시… 연 30만대 생산",
        "summary": "현대자동차가 미국 조지아주에 건설한 전기차 전용 공장 '메타플랜트 아메리카'가 "
                   "본격 가동에 들어갔다. 연간 30만대 규모의 생산 능력을 갖추고 있으며, "
                   "IRA 보조금 수혜가 기대된다. 현대차는 이를 통해 북미 전기차 시장 점유율을 "
                   "현재 8%에서 15%까지 끌어올린다는 목표다."
    },
    {
        "id": 4,
        "title": "셀트리온, FDA 신약 임상 3상 실패… 바이오 업종 동반 하락",
        "summary": "셀트리온의 자가면역질환 치료제 신약 임상 3상이 1차 평가 변수를 충족하지 못해 "
                   "실패로 판정됐다. 이에 셀트리온 주가는 하한가에 근접했으며, "
                   "바이오 업종 전반에 투자심리 위축이 확산되고 있다. "
                   "전문가들은 파이프라인 리스크 재평가가 불가피하다고 진단했다."
    },
    {
        "id": 5,
        "title": "한화에어로스페이스, 폴란드 K9 자주포 2차 계약 체결… 4조원 규모",
        "summary": "한화에어로스페이스가 폴란드 정부와 K9 자주포 2차 수출 계약을 체결했다. "
                   "계약 규모는 약 4조원으로 역대 단일 방산 수출 계약 중 최대 규모다. "
                   "납품은 2027년부터 시작되며, 탄약·정비 등 후속 수요도 기대된다."
    },
]

# ============================================================================
# 프롬프트 (Ollama 벤치마크와 동일)
# ============================================================================
SYSTEM_PROMPT = """너는 한국 주식 시장 전문 금융 뉴스 분석가야.
여러 뉴스를 입력받아 각각에 대해 두 가지를 동시에 분석해:
1) 감성 점수: 해당 종목 주가에 미칠 영향 (0-100, 50=중립)
2) 경쟁사 리스크: 특정 기업에 치명적 악재가 있어 경쟁사가 반사이익을 얻을 가능성 (0-20)

[출력 규칙]
- 반드시 JSON만 출력 (설명/마크다운/코드펜스 금지)
- reason은 반드시 한국어로 작성

[감성 점수 기준 (0~100)]
- 80~100: 강력 호재 (실적 서프라이즈, 대규모 수주, M&A)
- 60~79: 일반 호재 (목표가 상향, 신사업)
- 40~59: 중립 (단순 시황, 기반영된 뉴스)
- 20~39: 악재 (실적 부진, 규제)
- 0~19: 강력 악재 (상장폐지, 횡령, 대규모 사고)

[경쟁사 리스크 이벤트 유형]
FIRE, RECALL, SECURITY, SERVICE_OUTAGE, OWNER_RISK, UNION, OTHER, NONE

[출력 형식]
{
  "results": [
    {
      "id": <int>,
      "sentiment": { "score": <0..100>, "reason": "<한국어>" },
      "competitor_risk": {
        "is_detected": <boolean>,
        "type": "<enum>",
        "benefit_score": <0..20>,
        "reason": "<한국어>"
      }
    }
  ]
}"""

SINGLE_NEWS_SYSTEM = """당신은 '금융 전문가'입니다. 아래 뉴스를 보고 해당 종목에 대한 호재/악재 여부를 점수로 판단해주세요.
반드시 한국어(Korean)로만 응답하세요.

[채점 기준]
- 80 ~ 100점 (강력 호재): 실적 서프라이즈, 대규모 수주, 신기술 개발
- 60 ~ 79점 (호재): 긍정적 전망, 목표가 상향
- 40 ~ 59점 (중립): 단순 시황, 일반적 소식
- 20 ~ 39점 (악재): 실적 부진, 목표가 하향
- 0 ~ 19점 (강력 악재): 어닝 쇼크, 횡령, 규제 강화

JSON으로 응답: { "score": 점수(int), "reason": "판단 이유(한 문장, 한국어)" }"""

SINGLE_NEWS_USER = """- 뉴스 제목: 삼성전자, 차세대 HBM4 양산 성공… 엔비디아 공급망 합류
- 뉴스 내용: 삼성전자가 차세대 고대역폭메모리(HBM4) 양산에 성공하며 엔비디아 공급망에 합류했다. 업계에서는 SK하이닉스가 독점하던 HBM 시장에서 삼성전자가 본격적인 경쟁 구도를 형성할 것으로 전망하고 있다."""


def call_vllm_chat(system: str, user: str, max_tokens: int = 2048, temperature: float = 0) -> dict:
    """vLLM OpenAI-compatible chat completions API 호출"""
    # Qwen3는 thinking mode가 기본이므로 chat_template_kwargs로 비활성화 시도
    # 또는 extra_body로 thinking 비활성화
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
        # extra_body for Qwen3 thinking mode disable (not needed for EXAONE)
        # "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
    }

    start = time.time()
    try:
        resp = requests.post(
            f"{VLLM_URL}/v1/chat/completions",
            json=payload,
            timeout=300,
        )
        elapsed = time.time() - start

        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}", "elapsed_sec": round(elapsed, 2)}

        data = resp.json()
        choice = data["choices"][0]
        content = choice["message"]["content"]
        usage = data.get("usage", {})

        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        tok_per_sec = completion_tokens / elapsed if elapsed > 0 else 0

        # JSON 파싱
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = {"parse_error": True, "raw": content[:500]}

        return {
            "elapsed_sec": round(elapsed, 2),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "tok_per_sec": round(tok_per_sec, 1),
            "response": parsed,
        }
    except requests.exceptions.Timeout:
        return {"error": "TIMEOUT (300s)", "elapsed_sec": 300}
    except Exception as e:
        return {"error": str(e), "elapsed_sec": round(time.time() - start, 2)}


def run_single_news_test() -> dict:
    """단일 뉴스 감성 분석 테스트"""
    return call_vllm_chat(SINGLE_NEWS_SYSTEM, SINGLE_NEWS_USER, max_tokens=256)


def run_batch_news_test() -> dict:
    """5건 배치 뉴스 분석 테스트"""
    items_json = json.dumps({"items": TEST_NEWS_ITEMS}, ensure_ascii=False, indent=2)
    user_msg = f"[입력 데이터]\n{items_json}"
    result = call_vllm_chat(SYSTEM_PROMPT, user_msg, max_tokens=2048)

    # 품질 체크
    if "error" not in result and "parse_error" not in result.get("response", {}):
        parsed = result["response"]
        quality = {"json_valid": True}
        if "results" in parsed:
            results = parsed["results"]
            quality["count_match"] = len(results) == len(TEST_NEWS_ITEMS)
            quality["all_korean_reasons"] = all(
                not r.get("sentiment", {}).get("reason", "").isascii()
                for r in results
            )
            scores = [r.get("sentiment", {}).get("score", -1) for r in results]
            quality["scores"] = scores
            expected_ranges = [(70, 100), (0, 30), (65, 100), (0, 25), (75, 100)]
            in_range = sum(1 for s, (lo, hi) in zip(scores, expected_ranges) if lo <= s <= hi)
            quality["score_accuracy"] = f"{in_range}/5"
        result["quality"] = quality
    elif "error" not in result:
        result["quality"] = {"json_valid": False}

    return result


def main():
    now = datetime.now()
    print("=" * 70)
    print(f"  vLLM Qwen3-32B-AWQ 벤치마크 — {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # API 확인
    try:
        resp = requests.get(f"{VLLM_URL}/v1/models", timeout=5)
        models = [m["id"] for m in resp.json().get("data", [])]
        print(f"\n  vLLM 서버: {VLLM_URL}")
        print(f"  모델: {', '.join(models)}")
    except Exception as e:
        print(f"\n  [ERROR] vLLM 서버 연결 실패: {e}")
        sys.exit(1)

    # Warm-up
    print(f"\n  [1/3] Warm-up (첫 요청)")
    warmup = call_vllm_chat("You are a helpful assistant.", "Hello", max_tokens=10)
    if "error" in warmup:
        print(f"  [ERROR] Warm-up 실패: {warmup['error']}")
        sys.exit(1)
    print(f"        → {warmup['elapsed_sec']}s, {warmup.get('completion_tokens', 0)} tokens")

    # 단일 뉴스 테스트
    print(f"\n  [2/3] 단일 뉴스 감성 분석 테스트")
    single = run_single_news_test()
    if "error" in single:
        print(f"        → ERROR: {single['error']}")
    else:
        print(f"        → {single['elapsed_sec']}s, {single['tok_per_sec']} tok/s ({single['completion_tokens']} tokens)")
        print(f"        → 응답: {json.dumps(single['response'], ensure_ascii=False)[:200]}")

    # 배치 뉴스 테스트
    print(f"\n  [3/3] 5건 배치 뉴스 분석 테스트")
    batch = run_batch_news_test()
    if "error" in batch:
        print(f"        → ERROR: {batch['error']}")
    else:
        q = batch.get("quality", {})
        print(f"        → {batch['elapsed_sec']}s, {batch['tok_per_sec']} tok/s ({batch['completion_tokens']} tokens)")
        print(f"        → JSON 유효: {q.get('json_valid')}, 건수 일치: {q.get('count_match')}, 점수 정확도: {q.get('score_accuracy')}")
        if q.get("scores"):
            print(f"        → 감성 점수: {q['scores']}")

    # 결과 저장
    results = {
        "model": MODEL,
        "engine": "vLLM 0.15.1",
        "quantization": "awq_marlin",
        "max_model_len": 4096,
        "gpu": "RTX 3090 24GB",
        "timestamp": now.isoformat(),
        "warmup": warmup,
        "single_news": single,
        "batch_news": batch,
    }

    outfile = f"scripts/benchmark_vllm_results_{now.strftime('%Y%m%d_%H%M%S')}.json"
    with open(outfile, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n  결과 저장: {outfile}")

    # Ollama 비교표
    print("\n" + "=" * 70)
    print("  Ollama 벤치마크 대비 비교")
    print("=" * 70)
    print(f"{'모델':<30} {'단일(초)':<12} {'배치(초)':<12} {'tok/s':<10} {'JSON':<8} {'점수정확'}")
    print("─" * 90)
    # Ollama baseline (exaone3.5:7.8b)
    print(f"{'exaone3.5:7.8b (Ollama)':<30} {'9.28':<12} {'20.39':<12} {'91.0':<10} {'True':<8} {'5/5'}")
    print(f"{'gemma3:27b (Ollama)':<30} {'2.69':<12} {'43.96':<12} {'32.4':<10} {'True':<8} {'5/5'}")
    print(f"{'qwen3:32b (Ollama/GGUF)':<30} {'3.33':<12} {'67.97':<12} {'13.8':<10} {'True':<8} {'5/5'}")
    # vLLM result
    s_time = single.get("elapsed_sec", "ERR") if "error" not in single else "ERR"
    b_time = batch.get("elapsed_sec", "ERR") if "error" not in batch else "ERR"
    tps = batch.get("tok_per_sec", "ERR") if "error" not in batch else "ERR"
    jv = batch.get("quality", {}).get("json_valid", "ERR")
    sa = batch.get("quality", {}).get("score_accuracy", "ERR")
    print(f"{'Qwen3-32B-AWQ (vLLM)':<30} {str(s_time):<12} {str(b_time):<12} {str(tps):<10} {str(jv):<8} {str(sa)}")


if __name__ == "__main__":
    main()
