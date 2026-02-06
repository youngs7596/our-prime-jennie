"""
tests/shared/test_cloud_failover_provider.py

CloudFailoverProvider 유닛 테스트
- 3-Tier failover 체인: OpenRouter → DeepSeek → Ollama Cloud
- API 키 없는 프로바이더 건너뛰기
- 전체 실패 시 에러 전파
"""
import os
import pytest
from unittest.mock import patch, MagicMock


class TestCloudFailoverProviderInit:
    """CloudFailoverProvider 초기화 테스트"""

    @patch("shared.llm_providers.OllamaLLMProvider")
    @patch("shared.llm_providers.OpenAILLMProvider")
    @patch("shared.auth.get_secret")
    def test_all_providers_registered(self, mock_secret, mock_openai, mock_ollama):
        """3개 API 키 모두 있으면 3개 프로바이더 등록"""
        mock_secret.side_effect = lambda key: {
            "openrouter-api-key": "or-key-123",
            "deepseek-api-key": "ds-key-456",
        }.get(key)

        # Ollama Cloud에 API 키가 있는 것으로 설정
        mock_ollama_instance = MagicMock()
        mock_ollama_instance._cloud_api_key = "ollama-key-789"
        mock_ollama.return_value = mock_ollama_instance

        from shared.llm_providers import CloudFailoverProvider

        provider = CloudFailoverProvider(tier_name="REASONING")

        assert len(provider._providers) == 3
        assert provider._provider_names == ["DeepSeek", "OpenRouter", "OllamaCloud"]

    @patch("shared.llm_providers.OllamaLLMProvider")
    @patch("shared.llm_providers.OpenAILLMProvider")
    @patch("shared.auth.get_secret")
    def test_skip_missing_api_keys(self, mock_secret, mock_openai, mock_ollama):
        """API 키 없는 프로바이더는 건너뜀"""
        mock_secret.side_effect = lambda key: {
            "openrouter-api-key": None,
            "deepseek-api-key": "ds-key-456",
        }.get(key)

        mock_ollama_instance = MagicMock()
        mock_ollama_instance._cloud_api_key = None
        mock_ollama.return_value = mock_ollama_instance

        from shared.llm_providers import CloudFailoverProvider

        provider = CloudFailoverProvider(tier_name="THINKING")

        assert len(provider._providers) == 1
        assert provider._provider_names == ["DeepSeek"]

    @patch("shared.llm_providers.OllamaLLMProvider")
    @patch("shared.llm_providers.OpenAILLMProvider")
    @patch("shared.auth.get_secret")
    def test_no_providers_raises(self, mock_secret, mock_openai, mock_ollama):
        """모든 API 키가 없으면 RuntimeError"""
        mock_secret.return_value = None

        mock_ollama_instance = MagicMock()
        mock_ollama_instance._cloud_api_key = None
        mock_ollama.return_value = mock_ollama_instance

        from shared.llm_providers import CloudFailoverProvider

        with pytest.raises(RuntimeError, match="사용 가능한 프로바이더가 없습니다"):
            CloudFailoverProvider(tier_name="REASONING")


class TestCloudFailoverProviderFailover:
    """CloudFailoverProvider failover 로직 테스트"""

    def _make_provider_with_mocks(self, providers, names):
        """Mock된 inner providers로 CloudFailoverProvider 생성"""
        from shared.llm_providers import CloudFailoverProvider

        with patch("shared.auth.get_secret", return_value=None), \
             patch("shared.llm_providers.OllamaLLMProvider") as mock_ollama:
            mock_ollama_instance = MagicMock()
            mock_ollama_instance._cloud_api_key = None
            mock_ollama.return_value = mock_ollama_instance

            # 빈 providers 에러를 우회하기 위해 직접 주입
            try:
                cp = CloudFailoverProvider.__new__(CloudFailoverProvider)
                cp.safety_settings = None
                cp.tier_name = "REASONING"
                cp._providers = providers
                cp._provider_names = names
                return cp
            except Exception:
                pytest.skip("CloudFailoverProvider 직접 생성 실패")

    def test_first_provider_succeeds(self):
        """첫 번째 프로바이더 성공 시 즉시 반환"""
        p1 = MagicMock()
        p1.generate_json.return_value = {"score": 85}

        p2 = MagicMock()

        provider = self._make_provider_with_mocks([p1, p2], ["OpenRouter", "DeepSeek"])
        result = provider.generate_json("prompt", {"type": "object"})

        assert result == {"score": 85}
        p1.generate_json.assert_called_once()
        p2.generate_json.assert_not_called()

    def test_failover_to_second_provider(self):
        """첫 번째 실패 시 두 번째로 failover"""
        p1 = MagicMock()
        p1.generate_json.side_effect = RuntimeError("503 Service Unavailable")

        p2 = MagicMock()
        p2.generate_json.return_value = {"score": 80}

        provider = self._make_provider_with_mocks([p1, p2], ["OpenRouter", "DeepSeek"])
        result = provider.generate_json("prompt", {"type": "object"})

        assert result == {"score": 80}
        p1.generate_json.assert_called_once()
        p2.generate_json.assert_called_once()

    def test_failover_to_third_provider(self):
        """1, 2번 실패 시 3번째로 failover"""
        p1 = MagicMock()
        p1.generate_json.side_effect = RuntimeError("503")

        p2 = MagicMock()
        p2.generate_json.side_effect = RuntimeError("429 Rate Limit")

        p3 = MagicMock()
        p3.generate_json.return_value = {"score": 70}

        provider = self._make_provider_with_mocks(
            [p1, p2, p3], ["OpenRouter", "DeepSeek", "OllamaCloud"]
        )
        result = provider.generate_json("prompt", {"type": "object"})

        assert result == {"score": 70}

    def test_all_providers_fail_raises(self):
        """모든 프로바이더 실패 시 RuntimeError"""
        p1 = MagicMock()
        p1.generate_json.side_effect = RuntimeError("503")

        p2 = MagicMock()
        p2.generate_json.side_effect = RuntimeError("500")

        provider = self._make_provider_with_mocks([p1, p2], ["OpenRouter", "DeepSeek"])

        with pytest.raises(RuntimeError, match="모든 프로바이더 실패"):
            provider.generate_json("prompt", {"type": "object"})

    def test_generate_chat_failover(self):
        """generate_chat도 failover 동작 확인"""
        p1 = MagicMock()
        p1.generate_chat.side_effect = RuntimeError("503")

        p2 = MagicMock()
        p2.generate_chat.return_value = {"text": "분석 결과"}

        provider = self._make_provider_with_mocks([p1, p2], ["OpenRouter", "DeepSeek"])
        history = [{"role": "user", "content": "분석해주세요"}]
        result = provider.generate_chat(history)

        assert result == {"text": "분석 결과"}

    def test_name_property(self):
        """name 프로퍼티 확인"""
        p1 = MagicMock()
        provider = self._make_provider_with_mocks([p1], ["OpenRouter"])
        assert provider.name == "cloud_failover"


class TestLLMFactoryDeepseekCloud:
    """LLMFactory에서 deepseek_cloud 타입 등록 테스트"""

    @patch.dict(os.environ, {"TIER_REASONING_PROVIDER": "deepseek_cloud"})
    @patch("shared.llm_providers.OllamaLLMProvider")
    @patch("shared.llm_providers.OpenAILLMProvider")
    @patch("shared.auth.get_secret")
    def test_factory_creates_cloud_failover(self, mock_secret, mock_openai, mock_ollama):
        """LLMFactory가 deepseek_cloud 타입으로 CloudFailoverProvider 생성"""
        mock_secret.side_effect = lambda key, *args, **kwargs: {
            "openrouter-api-key": "or-key",
            "deepseek-api-key": "ds-key",
        }.get(key)

        mock_ollama_instance = MagicMock()
        mock_ollama_instance._cloud_api_key = "ollama-key"
        mock_ollama.return_value = mock_ollama_instance

        from shared.llm_factory import LLMFactory, LLMTier
        from shared.llm_providers import CloudFailoverProvider

        provider = LLMFactory.get_provider(LLMTier.REASONING)
        assert isinstance(provider, CloudFailoverProvider)
