#!/usr/bin/env python3
"""
scripts/run_daily_council.py
Daily Council 실행 스크립트.
Jennie -> Minji -> Junho 순서로 리뷰를 수행하고 최종 Patch Bundle을 생성합니다.
"""

import argparse
import json
import logging
import os
import sys
import time
import re
from datetime import datetime
from typing import Dict, Any, Optional

# Add project root to sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from dotenv import load_dotenv

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# LLM 관련 모듈 임포트 (지연 임포트 아님)
try:
    from shared.llm_factory import LLMFactory, LLMTier
except ImportError as e:
    logger.error(f"Failed to import shared modules: {e}")
    sys.exit(1)

def load_json(path: str) -> Dict[str, Any]:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_json(data: Dict[str, Any], path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_prompt(agent_name: str) -> str:
    """프롬프트 파일 로드"""
    # 매핑: Agent Name -> Prompt Filename
    filename_map = {
        "Jennie": "jennie_data_selector.txt",
        "Minji": "minji_execution_architect.txt", # 가정된 파일명
        "Junho": "junho_strategy_analyst.txt"
    }
    
    filename = filename_map.get(agent_name)
    if not filename:
        raise ValueError(f"Unknown agent: {agent_name}")
        
    prompt_path = os.path.join(project_root, "prompts", "council", filename)
    
    # 파일이 없으면 기본 파일명으로 시도하거나 에러
    if not os.path.exists(prompt_path):
        logger.warning(f"Prompt file not found: {prompt_path}")
        return f"You are {agent_name}. Analyze the given data."
        
    with open(prompt_path, 'r', encoding='utf-8') as f:
        return f.read()

def extract_json_from_text(text: str) -> Dict[str, Any]:
    """LLM 응답에서 JSON 추출"""
    try:
        if isinstance(text, dict):
            return text

        # 1.```json ... ``` 패턴 찾기
        match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
        if match:
            json_str = match.group(1)
        else:
            # 2. { ... } 패턴 찾기 (가장 바깥쪽 괄호)
            match = re.search(r'(\{.*\})', text, re.DOTALL)
            if match:
                json_str = match.group(1)
            else:
                json_str = text
                
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON: {e}")
        logger.debug(f"Raw text: {text}")
        return {"error": "JSON parse error", "raw_text": text}

def mock_agent_response(agent_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """에이전트 응답 Mocking (이전 코드 유지)"""
    logger.info(f"[{agent_name}] Generating mock response...")
    time.sleep(1) 
    
    if agent_name == "Jennie":
        return {
            "reviewer": "Jennie (Mock)",
            "selected_cases": [
                 {"case_id": "MOCK-1", "category": "VETO", "symbol": "005930", "reasoning_summary": "Mock reason", "model_decision": "REJECT"}
            ]
        }
    elif agent_name == "Minji":
        return {
            "reviewer": "Minji (Mock)",
            "execution_plan": "Update strategy thresholds based on recent volatility.",
            "patch_candidates": [
                {
                    "target_file": "config/symbol_overrides.json",
                    "operation": "update",
                    "description": "Adjust override for symbol 000120",
                    "content": "Updated content here (mock)"
                }
            ]
        }
    elif agent_name == "Junho":
        return {
            "reviewer": "Junho (Mock)",
            "strategy_analysis": "Mock Analysis",
            "action_items_for_minji": [],
            "final_decision": "APPROVE"
        }
    return {}

def call_llm_agent(agent_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """
    실제 LLM 호출 로직
    """
    try:
        # 1. Tier 설정
        tier = LLMTier.FAST
        if agent_name == "Jennie":
            tier = LLMTier.FAST       # Gemini
        elif agent_name == "Minji":
            tier = LLMTier.REASONING   # Claude/GPT-4o-mini
        elif agent_name == "Junho":
            tier = LLMTier.THINKING    # GPT-4o
            
        provider = LLMFactory.get_provider(tier)
        logger.info(f"[{agent_name}] Using provider: {provider.__class__.__name__} (Tier: {tier.name})")
        
        # 2. 프롬프트 구성
        system_prompt = load_prompt(agent_name)
        user_content = json.dumps(context, indent=2, ensure_ascii=False)
        
        # Langchain 객체 대신 Dict List 사용
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Here is the daily packet/context data:\n\n{user_content}"},
        ]
        
        # 3. LLM 호출 (generate_chat 사용)
        # GeminiProvider의 경우 generate_chat은 딕셔너리 또는 텍스트가 담긴 딕셔너리를 반환함
        response = provider.generate_chat(messages)
        
        # 4. 결과 처리
        if isinstance(response, dict):
            if "text" in response:
                return extract_json_from_text(response["text"])
            else:
                # 이미 파싱된 JSON이거나 다른 구조
                return response
        
        return extract_json_from_text(str(response))
        
    except Exception as e:
        logger.error(f"[{agent_name}] LLM Call Failed: {e}", exc_info=True)
        return {"error": str(e)}

def main():
    load_dotenv(override=True)
    
    parser = argparse.ArgumentParser(description="Run Daily Council Review")
    parser.add_argument("--input", required=True, help="Path to input daily_packet.json")
    parser.add_argument("--output-dir", required=True, help="Directory to save review results")
    parser.add_argument("--mock", action="store_true", help="Use mock responses without calling LLMs")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.input):
        logger.error(f"Input file not found: {args.input}")
        sys.exit(1)
        
    packet = load_json(args.input)
    logger.info(f"Loaded daily packet for {packet.get('date', 'Unknown Date')}")
    
    # 1. Jennie Review
    logger.info(">>> Starting Jennie Review...")
    if args.mock:
        jennie_review = mock_agent_response("Jennie", packet)
    else:
        jennie_review = call_llm_agent("Jennie", packet)
    save_json(jennie_review, os.path.join(args.output_dir, "jennie_review.json"))
    
    # 2. Junho Review (Strategy) - Minji보다 먼저 전략 분석
    # Note: 순서는 Jennie(Data) -> Junho(Strategy) -> Minji(Execution)가 더 자연스러울 수 있음.
    # 하지만 원본 계획상 Jennie -> Minji -> Junho 였으나, Junho의 역할이 Strategy Analyst라면 
    # 데이터를 보고 전략을 수립(Junho) -> 실행 계획(Minji) 순서가 맞을수도.
    # 일단 기존 파일 구조상 Junho 분석이 Minji에게 입력으로 들어가는게 맞아보임.
    # 프롬프트 내용을 보면 Junho가 Strategy Sage, Minji가 Execution Agent.
    # 전략이 나와야 실행을 하므로 Jennie -> Junho -> Minji 순서로 변경 제안?
    # 하지만 스크립트 원본대로 일단 진행하되, Junho는 Minji의 결과를 보고 최종 승인하는 역할일 수도 있음.
    # 파일 내용을 보면 Junho는 "Strategy Sage"로 Minji에게 action items를 줌.
    # 즉 Jennie -> Junho -> Minji 순서가 논리적임.
    
    # 변경: Jennie -> Junho -> Minji
    logger.info(">>> Starting Junho Review (Strategy)...")
    junho_context = {"packet": packet, "jennie_review": jennie_review}
    
    if args.mock:
        junho_review = mock_agent_response("Junho", junho_context)
    else:
        junho_review = call_llm_agent("Junho", junho_context)
    save_json(junho_review, os.path.join(args.output_dir, "junho_review.json"))

    # 3. Minji Review (Execution/Patch)
    logger.info(">>> Starting Minji Review (Execution)...")
    minji_context = {
        "packet": packet, 
        "jennie_review": jennie_review,
        "junho_review": junho_review
    }
    
    if args.mock:
        minji_review = mock_agent_response("Minji", minji_context)
    else:
        minji_review = call_llm_agent("Minji", minji_context)
    save_json(minji_review, os.path.join(args.output_dir, "minji_review.json"))
    
    logger.info("Daily Council Review Completed Successfully.")

if __name__ == "__main__":
    main()
