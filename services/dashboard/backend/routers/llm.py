from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Dict, Optional, List
import os
import redis
import json
import logging
from datetime import datetime

# Shared Imports
from shared.llm_factory import LLMFactory, LLMTier

router = APIRouter(prefix="/api/llm", tags=["LLM"])
logger = logging.getLogger("dashboard.llm")

# --- Schemas ---
class LLMModelInfo(BaseModel):
    tier: str
    role: str
    provider: str
    model_name: str
    is_local: bool

class LLMConfigResponse(BaseModel):
    fast: LLMModelInfo
    reasoning: LLMModelInfo
    thinking: LLMModelInfo
    
class LLMStatItem(BaseModel):
    calls: int
    tokens: int

class LLMStatsResponse(BaseModel):
    fast: Optional[LLMStatItem]
    reasoning: Optional[LLMStatItem]
    thinking: Optional[LLMStatItem]
    news_analysis: Optional[LLMStatItem] # Legacy
    scout: Optional[LLMStatItem]
    briefing: Optional[LLMStatItem]
    macro_council: Optional[LLMStatItem]
    decisions_today: Optional[Dict[str, int]]

# --- Helper ---
def get_model_info_for_tier(tier: LLMTier, role_desc: str) -> LLMModelInfo:
    try:
        # LLMFactory 내부 로직 재사용 (Accessing protected methods for inspection)
        provider_type = LLMFactory._get_env_provider_type(tier)
        
        model_name = "Unknown"
        if provider_type == "ollama":
            model_name = LLMFactory._get_local_model_name(tier)
        elif provider_type == "openai":
            model_name = os.getenv("OPENAI_MODEL_NAME", "gpt-5.2")
        elif provider_type == "gemini":
            model_name = os.getenv("LLM_MODEL_NAME", "gemini-3-pro-preview") # Default from Factory
            # Fast Tier usually uses Flash
            if tier == LLMTier.FAST:
                 model_name = os.getenv("LLM_FLASH_MODEL_NAME", "gemini-2.5-flash")
        elif provider_type == "claude":
             if tier == LLMTier.FAST:
                 model_name = os.getenv("CLAUDE_FAST_MODEL", "claude-haiku-4-5")
             else:
                 model_name = os.getenv("CLAUDE_REASONING_MODEL", "claude-sonnet-4-5")
                 
        return LLMModelInfo(
            tier=tier.value,
            role=role_desc,
            provider=provider_type,
            model_name=model_name,
            is_local=(provider_type == "ollama")
        )
    except Exception as e:
        logger.error(f"Failed to resolve model info for {tier}: {e}")
        return LLMModelInfo(
            tier=tier.value,
            role=role_desc,
            provider="error",
            model_name="Error",
            is_local=False
        )

# --- Endpoints ---

@router.get("/config", response_model=LLMConfigResponse)
async def get_llm_config():
    """
    현재 활성화된 LLM 구성 정보를 반환합니다.
    (환경 변수 및 LLMFactory 설정 기반)
    """
    return LLMConfigResponse(
        fast=get_model_info_for_tier(LLMTier.FAST, "News Analysis & Simple Checks"),
        reasoning=get_model_info_for_tier(LLMTier.REASONING, "Hunter Scout & Debate"),
        thinking=get_model_info_for_tier(LLMTier.THINKING, "Judge Decision & Briefing")
    )

@router.get("/stats", response_model=LLMStatsResponse)
async def get_llm_stats():
    """
    오늘의 LLM 사용 통계 (Redis 기반)
    NOTE: 기존 main.py나 다른 곳에 구현된 것이 있다면 통합 고려.
          현재 main.py에는 구현이 없으므로 새로 구현.
    """
    try:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        r = redis.from_url(redis_url, decode_responses=True)
        
        today = datetime.now().strftime("%Y-%m-%d")
        base_key = f"llm:stats:{today}" # e.g. llm:stats:2025-12-21
        
        # Service Keys (Defined in OpenAILLMProvider._record_llm_usage etc)
        # We need to standardize keys. Currently code uses: "news_analysis", "scout", "briefing" mapped loosely.
        # Let's support both Tier-based and Functional keys if they exist.
        
        stats = {}
        target_keys = ["news_analysis", "scout", "briefing", "macro_council", "fast", "reasoning", "thinking"]
        
        for k in target_keys:
            key = f"{base_key}:{k}"
            data = r.hgetall(key)
            if data:
                stats[k] = LLMStatItem(
                    calls=int(data.get("calls", 0)),
                    tokens=int(data.get("tokens_in", 0)) + int(data.get("tokens_out", 0))
                )
            else:
                stats[k] = LLMStatItem(calls=0, tokens=0)
                
        # Scout Decisions Count
        # Assuming keys like scout:decisions:today:buy etc. exist or we parse from pipeline results.
        # Actually Overview.tsx uses 'llmStats.decisions_today'.
        # Let's implement basics.
        
        # Temporary logic for decisions:
        buy_count = 0
        reject_count = 0
        
        # Try to count from 'scout:pipeline:results' if available
        results_json = r.get("scout:pipeline:results")
        if results_json:
            results = json.loads(results_json)
            for res in results:
                # This logic depends on result structure
                if res.get("final_decision") == "BUY":
                    buy_count += 1
                elif res.get("final_decision") == "REJECT":
                    reject_count += 1
                    
        return LLMStatsResponse(
            fast=stats.get("fast"),
            reasoning=stats.get("reasoning"),
            thinking=stats.get("thinking"),
            news_analysis=stats.get("news_analysis"),
            scout=stats.get("scout"),
            briefing=stats.get("briefing"),
            macro_council=stats.get("macro_council"),
            decisions_today={"buy": buy_count, "reject": reject_count}
        )
        
    except Exception as e:
        logger.error(f"Failed to fetch LLM stats: {e}")
        # Return empty on error
        return LLMStatsResponse(
            decisions_today={"buy": 0, "reject": 0}
        )
