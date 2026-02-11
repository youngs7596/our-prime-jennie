#!/usr/bin/env python3
"""
scripts/ask_prime_council.py
----------------------------
Prime Council (3현자)에게 로컬 코드/질문에 대한 의견을 구하는 스크립트.
3단계 파이프라인(Jennie -> Minji -> Junho)을 통해 전략, 구현, 승인을 거친 리포트를 생성합니다.

비용 최적화 (2026-02-11 v2):
  - Jennie/Minji: DeepSeek v3.2 (CloudFailoverProvider) — 저비용 대량 분석
  - Junho/Orchestrator: Claude Opus 4.6 — 짧은 최종 판단만 수행
  - 예상 비용: ~$0.10~0.20/회 (기존 대비 ~70% 절감)
"""

import argparse
import sys
import os
import json
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path

# 프로젝트 루트 경로 설정
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.append(str(PROJECT_ROOT))

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("PrimeCouncil")

# 모듈 임포트
try:
    from shared.llm_providers import ClaudeLLMProvider, CloudFailoverProvider
except ImportError as e:
    logger.error(f"Failed to import shared modules: {e}")
    sys.exit(1)

# --- Constants & Configuration ---
PROMPTS_DIR = PROJECT_ROOT / "prompts" / "council"
REPORTS_DIR = PROJECT_ROOT / ".ai" / "reviews"
SECRETS_FILE = PROJECT_ROOT / "secrets.json"

SAGE_NAMES = {
    "jennie": "Jennie (DeepSeek v3.2)",
    "minji": "Minji (DeepSeek v3.2)",
    "junho": "Junho (Claude Opus 4.6)",
    "orchestrator": "Orchestrator (Claude Opus 4.6)"
}

# === 비용 계산 상수 (2026 기준 가격) ===
# 단위: USD per 1M tokens
MODEL_PRICING = {
    # DeepSeek v3.2 (via OpenRouter / DeepSeek API)
    "deepseek": {
        "input_per_1m": 0.27,    # $0.27 / 1M input tokens
        "output_per_1m": 1.10,   # $1.10 / 1M output tokens
    },
    # Claude Opus 4.6
    "claude": {
        "input_per_1m": 15.0,    # $15 / 1M input tokens
        "output_per_1m": 75.0,   # $75 / 1M output tokens
    },
}

# KRW / USD 환율 (대략적)
USD_TO_KRW = 1450

def load_system_prompt(sage_name: str) -> str:
    """prompts/council/{name}_system.txt 로드"""
    path = PROMPTS_DIR / f"{sage_name}_system.txt"
    if not path.exists():
        logger.warning(f"System prompt not found for {sage_name}: {path}")
        return f"You are {sage_name}. analyzing the request."
    return path.read_text(encoding="utf-8")

def load_file_content(file_path: str) -> str:
    """분석 대상 파일 내용 로드"""
    path = Path(file_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path

    if not path.exists():
        return json.dumps({
            "status": "error",
            "type": "file_not_found",
            "path": str(file_path),
            "message": f"File not found: {file_path}. Please check the path."
        }, ensure_ascii=False)

    try:
        content = path.read_text(encoding="utf-8")
        return f"File: {file_path}\nRunning on: {sys.platform}\n\n```python\n{content}\n```"
    except Exception as e:
        return json.dumps({
            "status": "error",
            "type": "read_error",
            "message": str(e)
        }, ensure_ascii=False)


def _safe_generate(provider, system_prompt, user_query, context, service="prime_council"):
    """Refined generation with Robust JSON Parsing"""
    history = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"{context}\n\nQuestion: {user_query}"}
    ]
    try:
        res = provider.generate_chat(history, service=service)
        text_content = res.get("text") or res.get("content", "")

        # Robust JSON Parsing using Regex
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text_content, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            start = text_content.find("{")
            end = text_content.rfind("}") + 1
            if start != -1 and end > start:
                json_str = text_content[start:end]
            else:
                logger.warning(f"JSON parsing failed. Returning raw text.")
                return {"text": text_content, "decision": "neutral", "raw_output": True}, 0, 0

        # 토큰 사용량 추정
        input_chars = len(system_prompt) + len(context) + len(user_query)
        output_chars = len(text_content)
        input_tokens = input_chars // 3
        output_tokens = output_chars // 3

        try:
            return json.loads(json_str), input_tokens, output_tokens
        except json.JSONDecodeError as je:
            return {
                "text": text_content,
                "error": f"JSON Parse Failed: {je}",
                "raw_json_snippet": json_str[:200]
            }, input_tokens, output_tokens

    except Exception as e:
        logger.error(f"LLM Error: {e}")
        return {"error": str(e), "decision": "veto"}, 0, 0

def _safe_chat(provider, system_prompt, content, service="prime_council"):
    """Helper for chat (markdown output)"""
    history = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": content}
    ]
    try:
        res = provider.generate_chat(history, service=service)
        text = res.get("text") or res.get("content", "")
        input_tokens = (len(system_prompt) + len(content)) // 3
        output_tokens = len(text) // 3
        return text, input_tokens, output_tokens
    except Exception as e:
        return f"Error generating final report: {e}", 0, 0

def _calculate_cost(provider_name: str, input_tokens: int, output_tokens: int) -> float:
    """비용 계산 (USD)"""
    pricing = MODEL_PRICING.get(provider_name, MODEL_PRICING["deepseek"])
    input_cost = (input_tokens / 1_000_000) * pricing["input_per_1m"]
    output_cost = (output_tokens / 1_000_000) * pricing["output_per_1m"]
    return input_cost + output_cost

def _format_cost_report(usage_stats: dict) -> str:
    """비용 리포트 문자열 생성"""
    lines = ["\n" + "=" * 60]
    lines.append("💰 Prime Council 세션 비용 리포트")
    lines.append("=" * 60)

    total_usd = 0.0
    for name, stats in usage_stats.items():
        input_t = stats["input_tokens"]
        output_t = stats["output_tokens"]
        cost_usd = stats["cost_usd"]
        total_usd += cost_usd

        lines.append(f"  {name}:")
        lines.append(f"    - Input:  {input_t:,} tokens")
        lines.append(f"    - Output: {output_t:,} tokens")
        lines.append(f"    - Cost:   ${cost_usd:.4f} USD")

    total_krw = total_usd * USD_TO_KRW
    lines.append("-" * 60)
    lines.append(f"  합계: ${total_usd:.4f} USD (≈ {total_krw:,.0f}원)")
    lines.append("=" * 60 + "\n")

    return "\n".join(lines)

def run_council(query: str, target_file: str = None):
    """
    3현자 파이프라인 실행: Jennie -> Minji -> Junho -> Report

    비용 최적화:
    - Jennie/Minji: DeepSeek v3.2 (CloudFailoverProvider) — 저비용, 긴 분석
    - Junho/Orchestrator: Claude Opus 4.6 — 고비용이지만 짧은 출력
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = REPORTS_DIR / f"council_report_{report_timestamp}.md"

    file_context = load_file_content(target_file) if target_file else "(No specific file context provided)"

    jennie_prompt = load_system_prompt("jennie")
    minji_prompt = load_system_prompt("minji")
    junho_prompt = load_system_prompt("junho")
    orchestrator_prompt = load_system_prompt("orchestrator")

    # [Provider Initialization] — Macro Council 패턴 적용
    try:
        # Jennie/Minji: DeepSeek v3.2 (CloudFailoverProvider) — 저비용 분석
        analysis_provider = CloudFailoverProvider(tier_name="REASONING")

        # Junho/Orchestrator: Claude Opus 4.6 — 최종 판단
        judge_provider = ClaudeLLMProvider()
    except Exception as e:
        logger.error(f"Failed to initialize providers: {e}")
        return

    # 비용 추적 딕셔너리
    usage_stats = {}

    # [Step 1] Jennie (Strategy & Analysis) — DeepSeek v3.2
    logger.info("🟢 [1/3] Jennie (DeepSeek v3.2) — 전략 분석 중...")
    jennie_output, j_in, j_out = _safe_generate(analysis_provider, jennie_prompt, query, file_context)
    usage_stats[SAGE_NAMES["jennie"]] = {
        "input_tokens": j_in, "output_tokens": j_out,
        "cost_usd": _calculate_cost("deepseek", j_in, j_out)
    }

    # [Step 2] Minji (Engineering) — DeepSeek v3.2
    logger.info("🟢 [2/3] Minji (DeepSeek v3.2) — 엔지니어링 검토 중...")
    minji_context = f"{file_context}\n\n[Jennie's Findings]:\n{json.dumps(jennie_output, ensure_ascii=False)}"
    minji_output, m_in, m_out = _safe_generate(analysis_provider, minji_prompt, query, minji_context)
    usage_stats[SAGE_NAMES["minji"]] = {
        "input_tokens": m_in, "output_tokens": m_out,
        "cost_usd": _calculate_cost("deepseek", m_in, m_out)
    }

    # [Step 3] Junho (Approval) — Claude Opus 4.6
    logger.info("🟣 [3/3] Junho (Claude Opus 4.6) — 최종 심사 중...")
    junho_context = (f"{file_context}\n\n"
                     f"[Jennie's Strategy]:\n{json.dumps(jennie_output, ensure_ascii=False)}\n\n"
                     f"[Minji's Proposal]:\n{json.dumps(minji_output, ensure_ascii=False)}")
    junho_output, h_in, h_out = _safe_generate(judge_provider, junho_prompt, query, junho_context)
    usage_stats[SAGE_NAMES["junho"]] = {
        "input_tokens": h_in, "output_tokens": h_out,
        "cost_usd": _calculate_cost("claude", h_in, h_out)
    }

    # [Step 4] Orchestration — Claude Opus 4.6
    logger.info("🎼 Orchestrating Final Report (Claude Opus 4.6)...")
    orchestrator_input = (f"[Jennie Report]\n{json.dumps(jennie_output, ensure_ascii=False)}\n\n"
                          f"[Minji Report]\n{json.dumps(minji_output, ensure_ascii=False)}\n\n"
                          f"[Junho Report]\n{json.dumps(junho_output, ensure_ascii=False)}")

    final_markdown, o_in, o_out = _safe_chat(judge_provider, orchestrator_prompt, orchestrator_input)
    usage_stats[SAGE_NAMES["orchestrator"]] = {
        "input_tokens": o_in, "output_tokens": o_out,
        "cost_usd": _calculate_cost("claude", o_in, o_out)
    }

    # 비용 리포트 출력
    cost_report = _format_cost_report(usage_stats)
    print(cost_report)
    logger.info(cost_report)

    with open(report_file, "w", encoding="utf-8") as f:
        f.write(f"# Prime Council Report\n")
        f.write(f"- Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"- Query: {query}\n")
        f.write(f"- Target: {target_file}\n\n")
        f.write(final_markdown)
        f.write("\n\n---\n## Appendix: Raw JSON Outputs\n")
        f.write("<details><summary>Click to expand</summary>\n\n")
        f.write(f"### Jennie (DeepSeek v3.2)\n```json\n{json.dumps(jennie_output, indent=2, ensure_ascii=False)}\n```\n")
        f.write(f"### Minji (DeepSeek v3.2)\n```json\n{json.dumps(minji_output, indent=2, ensure_ascii=False)}\n```\n")
        f.write(f"### Junho (Claude Opus 4.6)\n```json\n{json.dumps(junho_output, indent=2, ensure_ascii=False)}\n```\n")
        f.write("\n</details>\n\n")

        # 비용 정보를 리포트에도 추가
        f.write("---\n## Cost Summary\n")
        total_usd = sum(s["cost_usd"] for s in usage_stats.values())
        total_krw = total_usd * USD_TO_KRW
        f.write(f"| Model | Input | Output | Cost (USD) |\n")
        f.write(f"|-------|-------|--------|------------|\n")
        for name, stats in usage_stats.items():
            f.write(f"| {name} | {stats['input_tokens']:,} | {stats['output_tokens']:,} | ${stats['cost_usd']:.4f} |\n")
        f.write(f"| **Total** | - | - | **${total_usd:.4f}** (≈{total_krw:,.0f}원) |\n")

    logger.info(f"✅ Council session finished. Report saved to: {report_file}")
    print(f"\n[REPORT GENERATED] {report_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ask the Prime Council")
    parser.add_argument("--query", "-q", required=True, help="Question for the council")
    parser.add_argument("--file", "-f", help="Target file path")

    # Load secrets (CloudFailoverProvider + ClaudeLLMProvider에 필요한 키 자동 로드)
    if SECRETS_FILE.exists():
        try:
            secrets = json.loads(SECRETS_FILE.read_text())
            key_mapping = {
                "openrouter_api_key": "OPENROUTER_API_KEY",
                "openrouter-api-key": "OPENROUTER_API_KEY",
                "deepseek_api_key": "DEEPSEEK_API_KEY",
                "deepseek-api-key": "DEEPSEEK_API_KEY",
                "claude-api-key": "ANTHROPIC_API_KEY",
                "claude_api_key": "ANTHROPIC_API_KEY",
            }
            for secret_key, env_var in key_mapping.items():
                if secret_key in secrets and secrets[secret_key]:
                    os.environ[env_var] = secrets[secret_key]
        except Exception as e:
            logger.warning(f"Failed to load secrets.json: {e}")

    args = parser.parse_args()
    run_council(args.query, args.file)
