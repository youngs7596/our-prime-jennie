"""
tests/shared/test_llm_factory.py

LLM Factory 테스트 - ModelStateManager, LLMFactory
"""
import os
import pytest
from unittest.mock import patch, MagicMock

from shared.llm_factory import LLMTier, ModelStateManager, LLMFactory


class TestModelStateManager:
    """ModelStateManager Singleton 및 상태 관리 테스트"""
    
    def test_singleton_pattern(self):
        """Singleton 패턴 검증 - 동일 인스턴스 반환"""
        manager1 = ModelStateManager()
        manager2 = ModelStateManager()
        assert manager1 is manager2
    
    def test_set_and_get_current_model(self):
        """모델 설정 및 조회"""
        manager = ModelStateManager()
        manager.set_current_model("gemma3:27b")
        assert manager.get_current_model() == "gemma3:27b"
        
        manager.set_current_model("qwen3:32b")
        assert manager.get_current_model() == "qwen3:32b"
    
    def test_is_model_loaded(self):
        """로드된 모델 확인"""
        manager = ModelStateManager()
        manager.set_current_model("gemma3:27b")
        
        assert manager.is_model_loaded("gemma3:27b") is True
        assert manager.is_model_loaded("qwen3:32b") is False


class TestLLMFactoryHelpers:
    """LLMFactory 헬퍼 메서드 테스트"""
    
    def test_get_env_provider_type_fast(self):
        """FAST tier 기본값 - gemini"""
        # Ensure env var is absent
        with patch.dict(os.environ):
            if "TIER_FAST_PROVIDER" in os.environ:
                del os.environ["TIER_FAST_PROVIDER"]
            provider_type = LLMFactory._get_env_provider_type(LLMTier.FAST)
            assert provider_type == "gemini"
    
    def test_get_env_provider_type_reasoning(self):
        """REASONING tier 기본값 - openai"""
        with patch.dict(os.environ):
            if "TIER_REASONING_PROVIDER" in os.environ:
                del os.environ["TIER_REASONING_PROVIDER"]
            provider_type = LLMFactory._get_env_provider_type(LLMTier.REASONING)
            assert provider_type == "openai"
    
    def test_get_env_provider_type_thinking(self):
        """THINKING tier 기본값 - openai"""
        with patch.dict(os.environ):
            if "TIER_THINKING_PROVIDER" in os.environ:
                del os.environ["TIER_THINKING_PROVIDER"]
            provider_type = LLMFactory._get_env_provider_type(LLMTier.THINKING)
            assert provider_type == "openai"
    
    def test_get_env_provider_type_from_env(self):
        """환경변수로 provider type 오버라이드"""
        with patch.dict(os.environ, {"TIER_FAST_PROVIDER": "ollama"}):
            provider_type = LLMFactory._get_env_provider_type(LLMTier.FAST)
            assert provider_type == "ollama"
        
        with patch.dict(os.environ, {"TIER_REASONING_PROVIDER": "GEMINI"}):
            provider_type = LLMFactory._get_env_provider_type(LLMTier.REASONING)
            assert provider_type == "gemini"  # lower() 적용
    
    def test_get_local_model_name_defaults(self):
        """로컬 모델명 기본값 - gemma3:27b"""
        with patch.dict(os.environ):
            # Clean up all fallback keys
            for tier in ["FAST", "REASONING", "THINKING"]:
                key = f"LOCAL_MODEL_{tier}"
                if key in os.environ:
                    del os.environ[key]

            assert LLMFactory._get_local_model_name(LLMTier.FAST) == "gemma3:27b"
            assert LLMFactory._get_local_model_name(LLMTier.REASONING) == "gemma3:27b"
            assert LLMFactory._get_local_model_name(LLMTier.THINKING) == "gemma3:27b"
    
    def test_get_local_model_name_from_env(self):
        """환경변수로 로컬 모델명 오버라이드"""
        with patch.dict(os.environ, {"LOCAL_MODEL_FAST": "qwen3:32b"}):
            model_name = LLMFactory._get_local_model_name(LLMTier.FAST)
            assert model_name == "qwen3:32b"


class TestLLMFactoryGetProvider:
    """LLMFactory.get_provider() 테스트"""
    
    @patch('shared.llm_providers.OllamaLLMProvider')
    def test_get_provider_ollama(self, mock_ollama):
        """Ollama provider 생성"""
        mock_instance = MagicMock()
        mock_ollama.return_value = mock_instance
        
        with patch.dict(os.environ, {
            "TIER_FAST_PROVIDER": "ollama",
            "LOCAL_MODEL_FAST": "gemma3:27b"  # Override Jenkins env
        }):
            provider = LLMFactory.get_provider(LLMTier.FAST)
            
            assert provider is mock_instance
            mock_ollama.assert_called_once()
            call_kwargs = mock_ollama.call_args.kwargs
            assert call_kwargs['model'] == "gemma3:27b"
            assert call_kwargs['is_fast_tier'] is True
            assert call_kwargs['is_thinking_tier'] is False
    
    @patch('shared.llm_providers.OpenAILLMProvider')
    def test_get_provider_openai(self, mock_openai):
        """OpenAI provider 생성"""
        mock_instance = MagicMock()
        mock_openai.return_value = mock_instance
        
        with patch.dict(os.environ, {"TIER_REASONING_PROVIDER": "openai"}):
            provider = LLMFactory.get_provider(LLMTier.REASONING)
            
            assert provider is mock_instance
            mock_openai.assert_called_once_with()
    
    @patch('shared.llm_providers.ClaudeLLMProvider')
    def test_get_provider_claude(self, mock_claude):
        """Claude provider 생성"""
        mock_instance = MagicMock()
        mock_claude.return_value = mock_instance
        
        with patch.dict(os.environ, {"TIER_THINKING_PROVIDER": "claude"}):
            provider = LLMFactory.get_provider(LLMTier.THINKING)
            
            assert provider is mock_instance
            mock_claude.assert_called_once_with()
    
    @patch('shared.llm_providers.GeminiLLMProvider')
    def test_get_provider_gemini(self, mock_gemini):
        """Gemini provider 생성"""
        mock_instance = MagicMock()
        mock_gemini.return_value = mock_instance
        
        with patch.dict(os.environ, {
            "TIER_FAST_PROVIDER": "gemini",
            "GCP_PROJECT_ID": "test-project",
            "SECRET_ID_GEMINI_API_KEY": "test-secret"
        }):
            provider = LLMFactory.get_provider(LLMTier.FAST)
            
            assert provider is mock_instance
            mock_gemini.assert_called_once()
            call_args = mock_gemini.call_args.args
            assert call_args[0] == "test-project"
            assert call_args[1] == "test-secret"
    
    def test_get_provider_unknown(self):
        """알 수 없는 provider type - ValueError"""
        with patch.dict(os.environ, {"TIER_FAST_PROVIDER": "invalid"}):
            with pytest.raises(ValueError, match="Unknown provider type: invalid"):
                LLMFactory.get_provider(LLMTier.FAST)


class TestLLMFactoryFallback:
    """LLMFactory.get_fallback_provider() 테스트"""
    
    @patch('shared.llm_providers.GeminiLLMProvider')
    def test_get_fallback_provider(self, mock_gemini):
        """Gemini Flash 폴백 provider 생성"""
        mock_instance = MagicMock()
        mock_gemini.return_value = mock_instance
        
        with patch.dict(os.environ, {
            "GCP_PROJECT_ID": "fallback-project",
            "SECRET_ID_GEMINI_API_KEY": "fallback-secret"
        }):
            provider = LLMFactory.get_fallback_provider(LLMTier.FAST)
            
            assert provider is mock_instance
            mock_gemini.assert_called_once()
            call_kwargs = mock_gemini.call_args.kwargs
            assert call_kwargs['project_id'] == "fallback-project"
            assert call_kwargs['gemini_api_key_secret'] == "fallback-secret"
