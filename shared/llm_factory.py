from enum import Enum
import os
import threading
import time
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class LLMTier(Enum):
    """
    LLM Tiers defining performance/quality trade-offs.
    """
    FAST = "FAST"           # High speed, low cost (e.g., Sentiment)
    REASONING = "REASONING" # Balanced (e.g., Hunter Summarization)
    THINKING = "THINKING"   # Deep Logic (e.g., Judge, Reports)


class ModelStateManager:
    """
    Singleton to manage Local LLM State (VRAM usage) to prevent race conditions.
    """
    _instance = None
    _lock = threading.Lock()
    _current_model: Optional[str] = None
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(ModelStateManager, cls).__new__(cls)
        return cls._instance

    def set_current_model(self, model_name: str):
        with self._lock:
            self._current_model = model_name

    def get_current_model(self) -> Optional[str]:
        with self._lock:
            return self._current_model

    def is_model_loaded(self, model_name: str) -> bool:
        with self._lock:
            return self._current_model == model_name


class LLMFactory:
    """
    Factory to create and retrieve LLM Providers based on Tiers and Configuration.
    """
    _providers: Dict[LLMTier, Any] = {}
    _state_manager = ModelStateManager()

    @staticmethod
    def _get_env_provider_type(tier: LLMTier) -> str:
        """
        Get the configured provider type (ollama, openai, claude, gemini) for a tier.
        Defaults: FAST -> gemini (cloud), REASONING -> ollama (local), THINKING -> openai
        """
        env_key = f"TIER_{tier.value}_PROVIDER"
        # [Cost Optimization 2026-01]
        # Scout와 News-Crawler 스케줄 분리로 Local LLM 사용 가능
        # FAST -> Ollama (Local gemma3:27b) - 비용 ₩0
        # REASONING -> OpenAI GPT-4o-mini (Best Value vs Performance)
        # THINKING -> OpenAI GPT-4o (Standard Quality)
        if tier == LLMTier.FAST:
            default = "ollama"  # Cloud Gemini -> Local Ollama
        elif tier == LLMTier.THINKING:
            default = "openai" 
        else:
            default = "openai" # REASONING Default: GPT-4o-mini
            
        return os.getenv(env_key, default).lower()

    @staticmethod
    def _get_local_model_name(tier: LLMTier) -> str:
        """Get the specific local model name for a tier."""
        env_key = f"LOCAL_MODEL_{tier.value}"
        # 2026-01-03: FAST Tier -> gemma3:27b (JSON 안정성 개선)
        # - gpt-oss:20b에서 JSON 파싱 오류 다수 발생 -> gemma3로 변경
        # - 뉴스 필터링 개선으로 처리량 감소 (1800개 -> ~300개) -> 속도 부담 감소
        defaults = {
            LLMTier.FAST: "gemma3:27b",        # 감성분석 (JSON 안정성)
            LLMTier.REASONING: "gemma3:27b",  # Hunter, Debate
            LLMTier.THINKING: "gemma3:27b"    # Judge
        }
        return os.getenv(env_key, defaults.get(tier, "gemma3:27b"))

    @classmethod
    def get_provider(cls, tier: LLMTier):
        """
        Returns an initialized LLM Provider for the requested Tier.
        """
        from shared.llm_providers import (
            OllamaLLMProvider, 
            OpenAILLMProvider, 
            ClaudeLLMProvider, 
            GeminiLLMProvider
        )

        provider_type = cls._get_env_provider_type(tier)
        
        # Determine specific model name if applicable
        model_name = None
        if provider_type == "ollama":
            model_name = cls._get_local_model_name(tier)

        # Cache key could be expanded if we need multiple instances per tier with different configs
        # For now, simplistic caching per tier is fine unless we change config at runtime.
        # However, to be safe with config changes, we might instantiate fresh or check config.
        # Let's instantiate fresh for now to respect dynamic env vars, or we can singleton it.
        # Given the state manager, instantiating generic providers is cheap. 
        # OllamaProvider needs the model name.

        if provider_type == "ollama":
            return OllamaLLMProvider(
                model=model_name,
                state_manager=cls._state_manager,
                is_fast_tier=(tier == LLMTier.FAST),
                is_thinking_tier=(tier == LLMTier.THINKING)
            )
        elif provider_type == "openai":
            # [2026-02-05] Tier-specific Configuration for OpenAI-compatible APIs (DeepSeek, etc.)
            tier_prefix = f"TIER_{tier.value}"
            
            # 1. Tier-specific Key & Base URL
            tier_api_key = os.getenv(f"{tier_prefix}_API_KEY")
            tier_base_url = os.getenv(f"{tier_prefix}_API_BASE")
            
            # 2. Tier-specific Model Name override
            # [2026-02-05] Added support for TIER specific model name (e.g. TIER_REASONING_MODEL_NAME=deepseek-chat)
            tier_model_name = os.getenv(f"{tier_prefix}_MODEL_NAME")
            
            return OpenAILLMProvider(
                api_key=tier_api_key,
                base_url=tier_base_url,
                default_model=tier_model_name
            ) 
        elif provider_type == "claude":
            return ClaudeLLMProvider() 
        elif provider_type == "gemini":
            from shared.llm_constants import SAFETY_SETTINGS
            project_id = os.getenv("GCP_PROJECT_ID")
            # Default secret ID if not in env
            secret_id = os.getenv("SECRET_ID_GEMINI_API_KEY", "gemini-api-key")  
            return GeminiLLMProvider(project_id, secret_id, SAFETY_SETTINGS)
        
        raise ValueError(f"Unknown provider type: {provider_type} for tier {tier}")


