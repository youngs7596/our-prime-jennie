#!/usr/bin/env python3
"""
scripts/ask_prime_council.py
----------------------------
Prime Council (3현자)에게 로컬 코드/질문에 대한 의견을 구하는 스크립트.
3단계 파이프라인(Jennie -> Minji -> Junho)을 통해 전략, 구현, 승인을 거친 리포트를 생성합니다.
"""

import argparse
import sys
import os
import json
import logging
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
    from shared.llm_factory import LLMFactory, LLMTier
    from shared.llm_providers import BaseLLMProvider, GeminiLLMProvider, ClaudeLLMProvider, OpenAILLMProvider
    from shared.llm_constants import SAFETY_SETTINGS
except ImportError as e:
    logger.error(f"Failed to import shared modules: {e}")
    sys.exit(1)

# --- Constants & Configuration ---
PROMPTS_DIR = PROJECT_ROOT / "prompts" / "council"
REPORTS_DIR = PROJECT_ROOT / ".ai" / "reviews"
SECRETS_FILE = PROJECT_ROOT / "secrets.json"

SAGE_NAMES = {
    "jennie": "Jennie (Gemini 3.0 Pro)",
    "minji": "Minji (Claude Opus 4.5)",
    "junho": "Junho (ChatGPT 5.2)",
    "orchestrator": "Orchestrator"
}

# === 비용 계산 상수 (2025-2026 기준 가격) ===
# 단위: USD per 1M tokens
MODEL_PRICING = {
    # Gemini (gemini-2.5-flash)
    "gemini": {
        "input_per_1m": 0.075,   # $0.075 / 1M input tokens
        "output_per_1m": 0.30,   # $0.30 / 1M output tokens
    },
    # Claude (claude-3-opus)
    "claude": {
        "input_per_1m": 15.0,    # $15 / 1M input tokens
        "output_per_1m": 75.0,   # $75 / 1M output tokens
    },
    # OpenAI (gpt-4o-mini)
    "openai": {
        "input_per_1m": 0.15,    # $0.15 / 1M input tokens
        "output_per_1m": 0.60,   # $0.60 / 1M output tokens
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
        # [Council Reflection] Return structured error for LLM context
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

def _mask_secrets(text: str) -> str:
    """[Council Reflection] Mask API keys in logs/errors"""
    if not text: return ""
    masked = text
    # Simple masking for known key patterns could be added here
    # For now, generic catch context is hard, but we ensure logs don't dump secrets dict
    return masked

import re

def _safe_generate(provider, system_prompt, user_query, context, prev_reports):
    """Refined generation with Robust JSON Parsing"""
    history = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"{context}\n\nQuestion: {user_query}"}
    ]
    try:
        res = provider.generate_chat(history)
        text_content = res.get("text") or res.get("content", "")
        
        # [Council Reflection] Robust JSON Parsing using Regex
        # Look for ```json ... ``` or just {...}
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text_content, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Fallback: Find outermost brackets
            start = text_content.find("{")
            end = text_content.rfind("}") + 1
            if start != -1 and end > start:
                json_str = text_content[start:end]
            else:
                return {"text": text_content, "error": "No JSON found in response"}, 0, 0
        
        # 토큰 사용량 추정 (응답에 usage 정보가 없으면 문자 수 기반 추정)
        input_chars = len(system_prompt) + len(context) + len(user_query)
        output_chars = len(text_content)
        # 대략 4자 = 1토큰 (영어 기준, 한글은 더 많음)
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
        logger.error(f"LLM Error: {_mask_secrets(str(e))}")
        return {"error": str(e), "decision": "veto"}, 0, 0

def _safe_chat(provider, system_prompt, content):
    """Helper for chat (markdown output)"""
    history = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": content}
    ]
    try:
        res = provider.generate_chat(history)
        text = res.get("text") or res.get("content", "")
        # 토큰 추정
        input_tokens = (len(system_prompt) + len(content)) // 3
        output_tokens = len(text) // 3
        return text, input_tokens, output_tokens
    except Exception as e:
        return f"Error generating final report: {e}", 0, 0

def _calculate_cost(provider_name: str, input_tokens: int, output_tokens: int) -> float:
    """비용 계산 (USD)"""
    pricing = MODEL_PRICING.get(provider_name, MODEL_PRICING["openai"])
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
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = REPORTS_DIR / f"council_report_{report_timestamp}.md"
    
    file_context = load_file_content(target_file) if target_file else "(No specific file context provided)"
    
    jennie_prompt = load_system_prompt("jennie")
    minji_prompt = load_system_prompt("minji")
    junho_prompt = load_system_prompt("junho")
    orchestrator_prompt = load_system_prompt("orchestrator")

    # [Provider Initialization]
    try:
        jennie_provider = GeminiLLMProvider(
            project_id=os.getenv("GCP_PROJECT_ID"), 
            gemini_api_key_secret="gemini-api-key", 
            safety_settings=SAFETY_SETTINGS
        )
        minji_provider = ClaudeLLMProvider(
            claude_api_key_secret="anthropic-api-key"
        )
        junho_provider = OpenAILLMProvider(
            openai_api_key_secret="openai-api-key"
        )
    except Exception as e:
        logger.error(f"Failed to initialize providers: {e}")
        return

    # 비용 추적 딕셔너리
    usage_stats = {}

    # [Step 1] Jennie (Strategy & Analysis)
    logger.info("🟢 [1/3] Jennie (Analysis) is reviewing...")
    jennie_output, j_in, j_out = _safe_generate(jennie_provider, jennie_prompt, query, file_context, [])
    usage_stats["Jennie (Gemini)"] = {
        "input_tokens": j_in, "output_tokens": j_out,
        "cost_usd": _calculate_cost("gemini", j_in, j_out)
    }
    
    # [Step 2] Minji (Engineering)
    logger.info("🟢 [2/3] Minji (Engineering) is coding...")
    minji_context = f"{file_context}\n\n[Jennie's Findings]:\n{json.dumps(jennie_output, ensure_ascii=False)}"
    minji_output, m_in, m_out = _safe_generate(minji_provider, minji_prompt, query, minji_context, [])
    usage_stats["Minji (Claude)"] = {
        "input_tokens": m_in, "output_tokens": m_out,
        "cost_usd": _calculate_cost("claude", m_in, m_out)
    }

    # [Step 3] Junho (Approval)
    logger.info("🟣 [3/3] Junho (Review) is judging...")
    junho_context = (f"{file_context}\n\n"
                     f"[Jennie's Strategy]:\n{json.dumps(jennie_output, ensure_ascii=False)}\n\n"
                     f"[Minji's Proposal]:\n{json.dumps(minji_output, ensure_ascii=False)}")
    junho_output, h_in, h_out = _safe_generate(junho_provider, junho_prompt, query, junho_context, [])
    usage_stats["Junho (OpenAI)"] = {
        "input_tokens": h_in, "output_tokens": h_out,
        "cost_usd": _calculate_cost("openai", h_in, h_out)
    }

    # [Step 4] Orchestration
    logger.info("🎼 Orchestrating Final Report...")
    orchestrator_input = (f"[Jennie Report]\n{json.dumps(jennie_output, ensure_ascii=False)}\n\n"
                          f"[Minji Report]\n{json.dumps(minji_output, ensure_ascii=False)}\n\n"
                          f"[Junho Report]\n{json.dumps(junho_output, ensure_ascii=False)}")
    
    final_markdown, o_in, o_out = _safe_chat(junho_provider, orchestrator_prompt, orchestrator_input)
    usage_stats["Orchestrator (OpenAI)"] = {
        "input_tokens": o_in, "output_tokens": o_out,
        "cost_usd": _calculate_cost("openai", o_in, o_out)
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
        f.write(f"### Jennie\n```json\n{json.dumps(jennie_output, indent=2, ensure_ascii=False)}\n```\n")
        f.write(f"### Minji\n```json\n{json.dumps(minji_output, indent=2, ensure_ascii=False)}\n```\n")
        f.write(f"### Junho\n```json\n{json.dumps(junho_output, indent=2, ensure_ascii=False)}\n```\n")
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
    
    # Load secrets 
    if SECRETS_FILE.exists():
        try:
            secrets = json.loads(SECRETS_FILE.read_text())
            for k, v in secrets.items():
                if k == "openai-api-key": os.environ["OPENAI_API_KEY"] = v
                if k == "gemini-api-key": os.environ["GOOGLE_API_KEY"] = v
                if k == "claude-api-key": os.environ["ANTHROPIC_API_KEY"] = v 
        except Exception as e:
            logger.warning(f"Failed to load secrets.json: {e}")

    args = parser.parse_args()
    run_council(args.query, args.file)
