#!/usr/bin/env python3
"""
scripts/run_weekly_council.py

Weekly Council Orchestrator.
Flow: WeeklyPacket -> Junho (Strategy Sage) -> Patch Bundle
Schedule: 매주 금요일 18:00 KST 권장
"""

import argparse
import json
import logging
import os
import sys
import time
from typing import Dict, Any, Type
from pathlib import Path

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.llm_providers import GeminiLLMProvider, ClaudeLLMProvider, OpenAILLMProvider, BaseLLMProvider
from shared.llm_constants import SAFETY_SETTINGS

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("DailyCouncil")

# Validation Schemas (Simulated loading for now, or strict validation if passed)
# In production, we'd load the .json schema files and validate with `jsonschema`.
# For now, we trust the LLM provider's `generate_json` or simple check.

def load_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path: str, data: Dict[str, Any]):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def retry_llm_call(
    provider: BaseLLMProvider, 
    prompt: str, 
    schema: Dict, 
    retries: int = 1, 
    model_name: str = None
) -> Dict[str, Any]:
    """
    Wraps LLM call with retry logic for JSON validation failures.
    """
    for attempt in range(retries + 1):
        try:
            return provider.generate_json(
                prompt=prompt,
                response_schema=schema,
                temperature=0.7, # Slightly creative for reviews
                model_name=model_name
            )
        except Exception as e:
            logger.warning(f"⚠️ LLM Call failed (Attempt {attempt+1}/{retries+1}): {e}")
            if attempt == retries:
                raise e
            time.sleep(2)

def main():
    parser = argparse.ArgumentParser(description="Run Daily Council - Junho (Strategy Sage)")
    parser.add_argument("--input", required=True, help="Path to daily_packet.json")
    parser.add_argument("--output-dir", required=True, help="Directory to save review artifacts")
    parser.add_argument("--model", type=str, default="gpt-5.2", help="OpenAI Model to use (e.g. gpt-5.2, gpt-5)")
    parser.add_argument("--mock", action="store_true", help="Use mock responses for testing")
    args = parser.parse_args()

    # Setup Paths
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    project_root = Path(__file__).parent.parent
    prompts_dir = project_root / "prompts" / "council"
    
    # Load Inputs
    daily_packet = load_json(args.input)
    logger.info(f"Loaded Daily Packet for {daily_packet.get('date')}")

    # Load Junho Prompt
    prompt_path = prompts_dir / "junho_strategy_analyst.txt"
    if prompt_path.exists():
        junho_system = load_text(prompt_path)
    else:
        logger.warning(f"Prompt file not found: {prompt_path}. Using default.")
        junho_system = "You are Junho, the Strategy Sage. Analyze the daily packet and provide feedback."

    # Define Schema (Conceptually, Junho output structure)
    junho_schema = {
        "type": "object",
        "properties": {
            "reviewer": {"type": "string"},
            "strategy_analysis": {"type": "string"},
            "key_findings": {
                "type": "array", 
                "items": {
                    "type": "object",
                    "properties": {
                        "case_id": {"type": "string"},
                        "observation": {"type": "string"},
                        "suggestion": {"type": "string"}
                    },
                    "required": ["observation", "suggestion"]
                }
            },
            "action_items_for_minji": {
                "type": "array",
                "items": {"type": "string"}
            }
        },
        "required": ["strategy_analysis", "action_items_for_minji"]
    }
    
    # Instantiate Junho (OpenAI)
    if args.mock:
        logger.info("🎭 MOCK MODE: Skipping real LLM calls.")
        junho_review = {
            "reviewer": "Junho",
            "strategy_analysis": "Mock Analysis: Market was volatile.",
            "key_findings": [],
            "action_items_for_minji": ["Mock Action 1", "Mock Action 2"]
        }
    else:
        logger.info(f"📈 Calling Junho (Strategy Sage) using {args.model}...")
        try:
            junho_provider = OpenAILLMProvider()
            
            # Combine System Prompt + Packet
            junho_prompt = f"{junho_system}\n\n[Daily Packet]\n{json.dumps(daily_packet, ensure_ascii=False, indent=2)}"
            
            # Call LLM
            junho_review = retry_llm_call(
                provider=junho_provider, 
                prompt=junho_prompt, 
                schema=junho_schema, 
                model_name=args.model # Allow override
            )
        except Exception as e:
            logger.error(f"❌ Junho failed: {e}")
            sys.exit(1)

    # Save Output
    output_path = output_dir / "junho_review.json"
    save_json(output_path, junho_review)
    logger.info(f"✅ Junho Review saved to {output_path}")
    logger.info("👉 Next Step: Run '/council-patch' workflow in IDE (Minji).")

if __name__ == "__main__":
    main()
