#!/usr/bin/env python3
"""
LLM 모델 벤치마크 스크립트
- 뉴스 감성 분석 프롬프트(실제 프로덕션)로 모델별 속도 & 품질 비교
- Ollama API 직접 호출 (localhost:11434)
"""

import json
import time
import requests
import sys
from datetime import datetime

OLLAMA_URL = "http://localhost:11434"

# ============================================================================
# 테스트 모델 목록
# ============================================================================
MODELS = [
    "exaone3.5:7.8b",      # 현재 FAST (baseline)
    "qwen3:14b",            # 가성비 후보
    "solar-pro",            # 한국어 특화 22B
    "gemma3:27b",           # Google 27B
    "qwen3:30b-a3b",        # MoE 30B (3B active)
    "qwen3:32b",            # Dense 32B (빠듯)
]

# ============================================================================
# 테스트 뉴스 데이터 (실제 한국 증시 뉴스 스타일)
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
# 프롬프트: 실제 프로덕션 UNIFIED_NEWS_ANALYSIS_PROMPT 축약 버전
# ============================================================================
BENCHMARK_PROMPT = """[ROLE]
너는 한국 주식 시장 전문 금융 뉴스 분석가야.
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
}

[입력 데이터]
ITEMS_JSON
"""

# ============================================================================
# 단일 뉴스 감성 분석 프롬프트 (속도 측정용)
# ============================================================================
SINGLE_NEWS_PROMPT = """[금융 뉴스 감성 분석]
당신은 '금융 전문가'입니다. 아래 뉴스를 보고 해당 종목에 대한 호재/악재 여부를 점수로 판단해주세요.

[중요] 반드시 한국어(Korean)로만 응답하세요.

- 뉴스 제목: 삼성전자, 차세대 HBM4 양산 성공… 엔비디아 공급망 합류
- 뉴스 내용: 삼성전자가 차세대 고대역폭메모리(HBM4) 양산에 성공하며 엔비디아 공급망에 합류했다. 업계에서는 SK하이닉스가 독점하던 HBM 시장에서 삼성전자가 본격적인 경쟁 구도를 형성할 것으로 전망하고 있다.

[채점 기준]
- 80 ~ 100점 (강력 호재): 실적 서프라이즈, 대규모 수주, 신기술 개발
- 60 ~ 79점 (호재): 긍정적 전망, 목표가 상향
- 40 ~ 59점 (중립): 단순 시황, 일반적 소식
- 20 ~ 39점 (악재): 실적 부진, 목표가 하향
- 0 ~ 19점 (강력 악재): 어닝 쇼크, 횡령, 규제 강화

[출력 형식]
JSON으로 응답: { "score": 점수(int), "reason": "판단 이유(한 문장, 한국어)" }
"""


def check_model_available(model: str) -> bool:
    """모델이 Ollama에 다운로드되어 있는지 확인 (태그 :latest 자동 매칭)"""
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        models = [m["name"] for m in resp.json().get("models", [])]
        # 정확 매칭 또는 :latest 접미사 매칭
        return model in models or f"{model}:latest" in models
    except Exception:
        return False


def stop_all_models():
    """로딩된 모든 모델을 VRAM에서 내림"""
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/ps", timeout=5)
        running = resp.json().get("models", [])
        for m in running:
            name = m.get("name", "")
            if name:
                requests.post(f"{OLLAMA_URL}/api/generate",
                              json={"model": name, "keep_alive": 0}, timeout=30)
                print(f"  → {name} 언로드 완료")
    except Exception as e:
        print(f"  [WARN] 모델 언로드 실패: {e}")


def warm_up_model(model: str):
    """모델을 VRAM에 프리로드"""
    print(f"  → {model} 로딩 중...")
    start = time.time()
    try:
        resp = requests.post(f"{OLLAMA_URL}/api/generate",
                             json={"model": model, "prompt": "hello", "stream": False,
                                   "options": {"num_predict": 1}},
                             timeout=300)
        elapsed = time.time() - start
        if resp.status_code == 200:
            print(f"  → 로딩 완료 ({elapsed:.1f}s)")
            return True
        else:
            print(f"  [ERROR] 로딩 실패: HTTP {resp.status_code}")
            return False
    except Exception as e:
        print(f"  [ERROR] 로딩 실패: {e}")
        return False


def run_single_news_test(model: str) -> dict:
    """단일 뉴스 감성 분석 테스트 (속도 측정)"""
    # /no_think 태그로 Qwen3 thinking mode 비활성화
    prompt = SINGLE_NEWS_PROMPT
    # Qwen3 thinking mode 비활성화: /no_think 대신 시스템 프롬프트 방식
    # (Ollama generate API에서는 /no_think가 제대로 동작 안 함)

    start = time.time()
    try:
        resp = requests.post(f"{OLLAMA_URL}/api/generate",
                             json={
                                 "model": model,
                                 "prompt": prompt,
                                 "stream": False,
                                 "format": "json",
                                 "options": {
                                     "temperature": 0,
                                     "num_predict": 256,
                                     "num_ctx": 4096,
                                 }
                             }, timeout=120)
        elapsed = time.time() - start

        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}", "elapsed": elapsed}

        data = resp.json()
        response_text = data.get("response", "")
        eval_count = data.get("eval_count", 0)
        eval_duration = data.get("eval_duration", 0)

        tok_per_sec = (eval_count / (eval_duration / 1e9)) if eval_duration > 0 else 0

        # JSON 파싱 시도
        try:
            parsed = json.loads(response_text)
        except json.JSONDecodeError:
            parsed = {"parse_error": True, "raw": response_text[:200]}

        return {
            "elapsed_sec": round(elapsed, 2),
            "tokens": eval_count,
            "tok_per_sec": round(tok_per_sec, 1),
            "response": parsed,
        }
    except requests.exceptions.Timeout:
        return {"error": "TIMEOUT (120s)", "elapsed": 120}
    except Exception as e:
        return {"error": str(e), "elapsed": time.time() - start}


def run_batch_news_test(model: str) -> dict:
    """5건 뉴스 배치 분석 테스트 (실제 프로덕션 시나리오)"""
    items_json = json.dumps({"items": TEST_NEWS_ITEMS}, ensure_ascii=False, indent=2)
    prompt = BENCHMARK_PROMPT.replace("ITEMS_JSON", items_json)

    # Qwen3 thinking mode 비활성화: /no_think 대신 시스템 프롬프트 방식
    # (Ollama generate API에서는 /no_think가 제대로 동작 안 함)

    start = time.time()
    try:
        resp = requests.post(f"{OLLAMA_URL}/api/generate",
                             json={
                                 "model": model,
                                 "prompt": prompt,
                                 "stream": False,
                                 "format": "json",
                                 "options": {
                                     "temperature": 0,
                                     "num_predict": 2048,
                                     "num_ctx": 8192,
                                 }
                             }, timeout=300)
        elapsed = time.time() - start

        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}", "elapsed": elapsed}

        data = resp.json()
        response_text = data.get("response", "")
        eval_count = data.get("eval_count", 0)
        eval_duration = data.get("eval_duration", 0)

        tok_per_sec = (eval_count / (eval_duration / 1e9)) if eval_duration > 0 else 0

        # JSON 파싱 시도
        try:
            parsed = json.loads(response_text)
        except json.JSONDecodeError:
            parsed = {"parse_error": True, "raw": response_text[:500]}

        # 품질 체크: results 배열 길이, 한국어 reason 여부
        quality = {"json_valid": "parse_error" not in parsed}
        if quality["json_valid"] and "results" in parsed:
            results = parsed["results"]
            quality["count_match"] = len(results) == len(TEST_NEWS_ITEMS)
            quality["all_korean_reasons"] = all(
                not r.get("sentiment", {}).get("reason", "").isascii()
                for r in results
            )
            # 감성 점수 합리성 체크
            scores = [r.get("sentiment", {}).get("score", -1) for r in results]
            quality["scores"] = scores
            # 기대: 뉴스1(호재>70), 뉴스2(악재<30), 뉴스3(호재>65), 뉴스4(악재<25), 뉴스5(호재>75)
            expected_ranges = [(70, 100), (0, 30), (65, 100), (0, 25), (75, 100)]
            in_range = sum(1 for s, (lo, hi) in zip(scores, expected_ranges) if lo <= s <= hi)
            quality["score_accuracy"] = f"{in_range}/5"

        return {
            "elapsed_sec": round(elapsed, 2),
            "tokens": eval_count,
            "tok_per_sec": round(tok_per_sec, 1),
            "quality": quality,
            "response": parsed,
        }
    except requests.exceptions.Timeout:
        return {"error": "TIMEOUT (300s)", "elapsed": 300}
    except Exception as e:
        return {"error": str(e), "elapsed": time.time() - start}


def main():
    print("=" * 70)
    print(f"  LLM 뉴스 분석 벤치마크 — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # 특정 모델만 테스트 가능
    target_models = sys.argv[1:] if len(sys.argv) > 1 else MODELS

    results = {}

    for model in target_models:
        print(f"\n{'─' * 60}")
        print(f"  모델: {model}")
        print(f"{'─' * 60}")

        # 모델 존재 확인
        if not check_model_available(model):
            print(f"  [SKIP] {model} 미설치 — 건너뜀")
            results[model] = {"status": "NOT_AVAILABLE"}
            continue

        # 기존 모델 전부 언로드
        print("  [1/4] 기존 모델 언로드")
        stop_all_models()
        time.sleep(2)

        # 타겟 모델 로딩
        print("  [2/4] 모델 로딩 (warm-up)")
        if not warm_up_model(model):
            results[model] = {"status": "LOAD_FAILED"}
            continue

        # 단일 뉴스 테스트
        print("  [3/4] 단일 뉴스 감성 분석 테스트")
        single_result = run_single_news_test(model)
        print(f"        → {single_result.get('elapsed_sec', '?')}s, "
              f"{single_result.get('tok_per_sec', '?')} tok/s")
        if "response" in single_result:
            print(f"        → 응답: {json.dumps(single_result['response'], ensure_ascii=False)[:120]}")

        # 배치 뉴스 테스트
        print("  [4/4] 5건 배치 뉴스 분석 테스트")
        batch_result = run_batch_news_test(model)
        print(f"        → {batch_result.get('elapsed_sec', '?')}s, "
              f"{batch_result.get('tok_per_sec', '?')} tok/s")
        if "quality" in batch_result:
            q = batch_result["quality"]
            print(f"        → JSON 유효: {q.get('json_valid')}, "
                  f"건수 일치: {q.get('count_match')}, "
                  f"점수 정확도: {q.get('score_accuracy')}")
            if "scores" in q:
                print(f"        → 감성 점수: {q['scores']}")

        results[model] = {
            "status": "OK",
            "single_news": single_result,
            "batch_news": batch_result,
        }

    # ========================================================================
    # 최종 비교표 출력
    # ========================================================================
    print(f"\n{'=' * 70}")
    print("  최종 비교표")
    print(f"{'=' * 70}")
    print(f"{'모델':<25} {'단일(초)':<10} {'배치(초)':<10} {'tok/s':<10} {'JSON':<6} {'점수정확':<8}")
    print(f"{'─' * 25} {'─' * 10} {'─' * 10} {'─' * 10} {'─' * 6} {'─' * 8}")

    for model, data in results.items():
        if data.get("status") != "OK":
            print(f"{model:<25} {'N/A':<10} {'N/A':<10} {'N/A':<10} {'N/A':<6} {data.get('status','?'):<8}")
            continue

        single = data["single_news"]
        batch = data["batch_news"]
        single_time = single.get("elapsed_sec", "?")
        batch_time = batch.get("elapsed_sec", "?")
        tok_s = batch.get("tok_per_sec", single.get("tok_per_sec", "?"))
        json_ok = batch.get("quality", {}).get("json_valid", "?")
        accuracy = batch.get("quality", {}).get("score_accuracy", "?")

        print(f"{model:<25} {str(single_time):<10} {str(batch_time):<10} {str(tok_s):<10} {str(json_ok):<6} {str(accuracy):<8}")

    # JSON 결과 저장
    output_path = f"scripts/benchmark_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  상세 결과 저장: {output_path}")


if __name__ == "__main__":
    main()
