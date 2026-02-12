"""
tests/shared/test_llm_providers.py - LLM Provider Mock 테스트 (2단계)
====================================================================

shared/llm.py의 LLM Provider 클래스들을 테스트합니다.
auth.get_secret과 API 클라이언트들을 mock하여 외부 의존성 없이 테스트합니다.

실행 방법:
    pytest tests/shared/test_llm_providers.py -v
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock, call
import json
import os


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_safety_settings():
    """안전 설정 fixture"""
    return [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    ]


@pytest.fixture
def sample_response_schema():
    """샘플 JSON 응답 스키마"""
    return {
        "type": "object",
        "properties": {
            "score": {"type": "integer"},
            "grade": {"type": "string"},
            "reason": {"type": "string"}
        },
        "required": ["score", "grade", "reason"]
    }


# ============================================================================
# Tests: GeminiLLMProvider
# ============================================================================

class TestGeminiLLMProvider:
    """Gemini LLM Provider 테스트"""
    
    @patch('shared.auth.get_secret')
    @patch('google.genai.Client')
    def test_init_success(self, mock_client_class, mock_get_secret, mock_safety_settings):
        """초기화 성공"""
        from shared.llm_providers import GeminiLLMProvider
        
        mock_get_secret.return_value = 'fake-gemini-api-key'
        mock_client_class.return_value = MagicMock()
        
        provider = GeminiLLMProvider(
            project_id='test-project',
            gemini_api_key_secret='gemini-api-key',
            safety_settings=mock_safety_settings
        )
        
        assert provider is not None
        assert provider.name == 'gemini'
        mock_client_class.assert_called_once_with(api_key='fake-gemini-api-key')
    
    @patch('shared.auth.get_secret')
    def test_init_missing_api_key(self, mock_get_secret, mock_safety_settings):
        """API 키 없으면 RuntimeError"""
        from shared.llm_providers import GeminiLLMProvider
        
        mock_get_secret.return_value = None
        
        with pytest.raises(RuntimeError) as exc_info:
            GeminiLLMProvider(
                project_id='test-project',
                gemini_api_key_secret='gemini-api-key',
                safety_settings=mock_safety_settings
            )
        
        assert 'Secret' in str(exc_info.value) or '로드 실패' in str(exc_info.value)
    
    @patch('shared.auth.get_secret')
    @patch('google.genai.Client')
    def test_generate_json_success(self, mock_client_class, mock_get_secret, 
                                    mock_safety_settings, sample_response_schema):
        """generate_json 성공"""
        from shared.llm_providers import GeminiLLMProvider
        
        mock_get_secret.return_value = 'fake-api-key'
        
        # Mock response
        mock_response = MagicMock()
        mock_response.text = json.dumps({'score': 75, 'grade': 'B', 'reason': 'Good stock'})
        
        # Mock client.models.generate_content
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_client_class.return_value = mock_client
        
        provider = GeminiLLMProvider('project', 'secret', mock_safety_settings)
        result = provider.generate_json(
            "Analyze this stock",
            sample_response_schema,
            temperature=0.2
        )
        
        assert result['score'] == 75
        assert result['grade'] == 'B'
    
    @patch('shared.auth.get_secret')
    @patch('google.genai.Client')
    def test_generate_json_fallback(self, mock_client_class, mock_get_secret,
                                     mock_safety_settings, sample_response_schema):
        """첫 번째 모델 실패 시 폴백 모델로 재시도"""
        from shared.llm_providers import GeminiLLMProvider
        
        mock_get_secret.return_value = 'fake-api-key'
        
        # 첫 번째 호출은 실패 (429 아닌 에러), 두 번째 모델은 성공
        call_count = [0]
        
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("First model failed")
            mock_response = MagicMock()
            mock_response.text = json.dumps({'score': 60, 'grade': 'C', 'reason': 'Fallback'})
            return mock_response
        
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = side_effect
        mock_client_class.return_value = mock_client
        
        provider = GeminiLLMProvider('project', 'secret', mock_safety_settings)
        result = provider.generate_json(
            "Analyze this stock",
            sample_response_schema,
            fallback_models=['gemini-1.5-flash']
        )
        
        assert result['score'] == 60
        assert result['reason'] == 'Fallback'
    
    @patch('shared.auth.get_secret')
    @patch('google.genai.Client')
    def test_generate_json_all_fail(self, mock_client_class, mock_get_secret,
                                     mock_safety_settings, sample_response_schema):
        """모든 모델 실패 시 RuntimeError"""
        from shared.llm_providers import GeminiLLMProvider
        
        mock_get_secret.return_value = 'fake-api-key'
        
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("API Error")
        mock_client_class.return_value = mock_client
        
        provider = GeminiLLMProvider('project', 'secret', mock_safety_settings)
        
        with pytest.raises(RuntimeError) as exc_info:
            provider.generate_json(
                "Analyze this stock",
                sample_response_schema
            )
        
        assert 'LLM 호출 실패' in str(exc_info.value)


# ============================================================================
# Tests: OpenAILLMProvider
# ============================================================================

class TestOpenAILLMProvider:
    """OpenAI LLM Provider 테스트"""
    
    @patch('shared.auth.get_secret')
    def test_init_success(self, mock_get_secret, mock_safety_settings):
        """초기화 성공"""
        from shared.llm_providers import OpenAILLMProvider
        
        mock_get_secret.return_value = 'fake-openai-api-key'
        
        with patch.object(OpenAILLMProvider, '__init__', lambda self, *args, **kwargs: None):
            provider = OpenAILLMProvider.__new__(OpenAILLMProvider)
            provider.safety_settings = mock_safety_settings
            provider.default_model = 'gpt-4o-mini'
            provider.reasoning_model = 'gpt-5-mini'
            provider.client = MagicMock()
            
            assert provider.default_model == 'gpt-4o-mini'
    
    def test_is_reasoning_model(self, mock_safety_settings):
        """Reasoning 모델 판별"""
        from shared.llm_providers import OpenAILLMProvider
        
        # __init__ 우회
        provider = object.__new__(OpenAILLMProvider)
        provider.REASONING_MODELS = {"gpt-5-mini", "gpt-5", "o1", "o1-mini", "o3"}
        
        assert provider._is_reasoning_model('gpt-5-mini') is True
        assert provider._is_reasoning_model('o1-preview') is True
        assert provider._is_reasoning_model('gpt-4o') is False
        assert provider._is_reasoning_model('gpt-4o-mini') is False
    
    @patch('shared.auth.get_secret')
    def test_generate_json_success(self, mock_get_secret, mock_safety_settings, sample_response_schema):
        """generate_json 성공"""
        from shared.llm_providers import OpenAILLMProvider
        
        mock_get_secret.return_value = 'fake-api-key'
        
        # Provider 인스턴스 직접 생성 (우회)
        provider = object.__new__(OpenAILLMProvider)
        provider.safety_settings = mock_safety_settings
        provider.default_model = 'gpt-4o-mini'
        provider.REASONING_MODELS = {"gpt-5-mini", "o1"}
        
        # Mock OpenAI client
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            'score': 80, 'grade': 'A', 'reason': 'Excellent'
        })
        mock_client.chat.completions.create.return_value = mock_response
        provider.client = mock_client
        
        result = provider.generate_json(
            "Analyze this stock",
            sample_response_schema,
            temperature=0.2
        )
        
        assert result['score'] == 80
        assert result['grade'] == 'A'
    
    @patch('shared.auth.get_secret')
    def test_generate_json_reasoning_model_no_temperature(self, mock_get_secret, mock_safety_settings, sample_response_schema):
        """Reasoning 모델은 temperature 파라미터 없음"""
        from shared.llm_providers import OpenAILLMProvider
        
        mock_get_secret.return_value = 'fake-api-key'
        
        provider = object.__new__(OpenAILLMProvider)
        provider.safety_settings = mock_safety_settings
        provider.default_model = 'gpt-5-mini'  # Reasoning 모델
        provider.REASONING_MODELS = {"gpt-5-mini", "o1"}
        
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            'score': 70, 'grade': 'B', 'reason': 'Good'
        })
        mock_client.chat.completions.create.return_value = mock_response
        provider.client = mock_client
        
        provider.generate_json("Test", sample_response_schema, temperature=0.5)
        
        # temperature가 kwargs에 없어야 함 (reasoning model)
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert 'temperature' not in call_kwargs


# ============================================================================
# Tests: ClaudeLLMProvider
# ============================================================================

class TestClaudeLLMProvider:
    """Claude LLM Provider 테스트"""
    
    @patch('shared.auth.get_secret')
    def test_init_success(self, mock_get_secret, mock_safety_settings):
        """초기화 성공"""
        from shared.llm_providers import ClaudeLLMProvider
        
        mock_get_secret.return_value = 'fake-claude-api-key'
        
        # __init__ 우회
        provider = object.__new__(ClaudeLLMProvider)
        provider.safety_settings = mock_safety_settings
        provider.fast_model = 'claude-haiku-4-5'
        provider.reasoning_model = 'claude-sonnet-4-5'
        provider.client = MagicMock()
        
        assert provider.fast_model == 'claude-haiku-4-5'
    
    @patch('shared.auth.get_secret')
    def test_generate_json_success(self, mock_get_secret, mock_safety_settings, sample_response_schema):
        """generate_json 성공"""
        from shared.llm_providers import ClaudeLLMProvider
        
        mock_get_secret.return_value = 'fake-api-key'
        
        provider = object.__new__(ClaudeLLMProvider)
        provider.safety_settings = mock_safety_settings
        provider.fast_model = 'claude-haiku-4-5'
        
        # Mock Claude client
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_content = MagicMock()
        mock_content.text = json.dumps({'score': 85, 'grade': 'A', 'reason': 'Great stock'})
        mock_response.content = [mock_content]
        mock_client.messages.create.return_value = mock_response
        provider.client = mock_client
        
        result = provider.generate_json(
            "Analyze this stock",
            sample_response_schema,
            temperature=0.2
        )
        
        assert result['score'] == 85
        assert result['grade'] == 'A'
    
    @patch('shared.auth.get_secret')
    def test_generate_json_with_markdown(self, mock_get_secret, mock_safety_settings, sample_response_schema):
        """마크다운 코드블록 제거"""
        from shared.llm_providers import (
    BaseLLMProvider,
    GeminiLLMProvider,
    OpenAILLMProvider,
    ClaudeLLMProvider
)
        
        provider = object.__new__(ClaudeLLMProvider)
        provider.safety_settings = mock_safety_settings
        provider.fast_model = 'claude-haiku-4-5'
        
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_content = MagicMock()
        # 마크다운 코드블록으로 감싼 JSON
        mock_content.text = '```json\n{"score": 90, "grade": "S", "reason": "Excellent"}\n```'
        mock_response.content = [mock_content]
        mock_client.messages.create.return_value = mock_response
        provider.client = mock_client
        
        result = provider.generate_json("Test", sample_response_schema)
        
        assert result['score'] == 90
        assert result['grade'] == 'S'


# ============================================================================
# Tests: OllamaLLMProvider
# ============================================================================

class TestOllamaLLMProvider:
    """Ollama LLM Provider 테스트"""
    
    @pytest.fixture
    def mock_state_manager(self):
        """State Manager fixture"""
        manager = MagicMock()
        manager.get_current_model.return_value = 'qwen3:32b'
        return manager
    
    def test_init_success(self, mock_state_manager, monkeypatch):
        """초기화 성공"""
        from shared.llm_providers import OllamaLLMProvider

        monkeypatch.setenv('OLLAMA_HOST', 'http://localhost:11434')

        provider = OllamaLLMProvider(
            model='qwen3:32b',
            state_manager=mock_state_manager,
            is_fast_tier=False,
            is_thinking_tier=False
        )

        assert provider.model == 'qwen3:32b'
        assert provider.timeout == 600
        assert provider.max_retries == 2
    
    def test_init_fast_tier(self, mock_state_manager, monkeypatch):
        """Fast tier 초기화"""
        from shared.llm_providers import OllamaLLMProvider

        provider = OllamaLLMProvider(
            model='qwen3:32b',
            state_manager=mock_state_manager,
            is_fast_tier=True
        )
        
        assert provider.timeout == 60
    
    def test_clean_deepseek_tags(self, mock_state_manager, monkeypatch):
        """DeepSeek <think> 태그 제거"""
        from shared.llm_providers import OllamaLLMProvider
        
        provider = OllamaLLMProvider('qwen3:32b', mock_state_manager)

        text_with_think = '<think>This is reasoning...</think>{"score": 80}'
        result = provider._clean_deepseek_tags(text_with_think)
        
        assert result == '{"score": 80}'
    
    def test_ensure_model_loaded_different_model(self, mock_state_manager, monkeypatch):
        """다른 모델로 전환 시 상태 업데이트"""
        from shared.llm_providers import OllamaLLMProvider
        
        mock_state_manager.get_current_model.return_value = 'llama3:8b'
        
        provider = OllamaLLMProvider('qwen3:32b', mock_state_manager)
        provider._ensure_model_loaded()
        
        mock_state_manager.set_current_model.assert_called_once_with('qwen3:32b')
    
    @patch('requests.post')
    def test_generate_json_success(self, mock_post, mock_state_manager, monkeypatch, sample_response_schema):
        """generate_json 성공 (vLLM OpenAI-compatible API)"""
        from shared.llm_providers import OllamaLLMProvider

        mock_response = MagicMock()
        mock_response.json.return_value = {
            'choices': [{'message': {'content': '{"score": 75, "grade": "B", "reason": "Good"}'}}]
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        provider = OllamaLLMProvider('qwen3:32b', mock_state_manager)
        result = provider.generate_json("Analyze this stock", sample_response_schema)

        assert result['score'] == 75
        assert result['grade'] == 'B'
    
    @patch('requests.post')
    def test_generate_json_with_think_tags(self, mock_post, mock_state_manager, monkeypatch, sample_response_schema):
        """think 태그 포함 응답 처리"""
        from shared.llm_providers import OllamaLLMProvider

        mock_response = MagicMock()
        mock_response.json.return_value = {
            'choices': [{'message': {'content': '<think>Analyzing...</think>{"score": 80, "grade": "A", "reason": "Excellent"}'}}]
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        provider = OllamaLLMProvider('qwen3:32b', mock_state_manager)
        result = provider.generate_json("Test", sample_response_schema)

        assert result['score'] == 80
    
    @patch('requests.post')
    def test_generate_chat_success(self, mock_post, mock_state_manager, monkeypatch):
        """generate_chat 성공 (vLLM OpenAI-compatible API)"""
        from shared.llm_providers import OllamaLLMProvider

        mock_response = MagicMock()
        mock_response.json.return_value = {
            'choices': [{'message': {'content': 'This is a great stock to buy.'}}]
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        provider = OllamaLLMProvider('qwen3:32b', mock_state_manager)
        history = [{'role': 'user', 'content': 'Analyze Samsung stock'}]

        result = provider.generate_chat(history)

        assert 'text' in result
        assert result['text'] == 'This is a great stock to buy.'


# ============================================================================
# Tests: Provider Properties
# ============================================================================

class TestProviderProperties:
    """Provider 속성 테스트"""
    
    @patch('shared.auth.get_secret')
    @patch('google.genai.Client')
    def test_gemini_flash_model_name(self, mock_client_class, mock_get_secret, mock_safety_settings, monkeypatch):
        """Gemini flash 모델명 확인"""
        from shared.llm_providers import GeminiLLMProvider
        
        mock_get_secret.return_value = 'fake-api-key'
        mock_client_class.return_value = MagicMock()
        monkeypatch.setenv('LLM_FLASH_MODEL_NAME', 'gemini-custom-flash')
        
        provider = GeminiLLMProvider('project', 'secret', mock_safety_settings)
        
        assert provider.flash_model_name() == 'gemini-custom-flash'
    
    @patch('shared.auth.get_secret')
    @patch('google.genai.Client')
    def test_gemini_default_model_from_env(self, mock_client_class, mock_get_secret, mock_safety_settings, monkeypatch):
        """환경변수에서 기본 모델명 로드"""
        from shared.llm_providers import GeminiLLMProvider

        mock_get_secret.return_value = 'fake-api-key'
        mock_client_class.return_value = MagicMock()
        monkeypatch.setenv('LLM_MODEL_NAME', 'gemini-custom-pro')

        provider = GeminiLLMProvider('project', 'secret', mock_safety_settings)

        assert provider.default_model == 'gemini-custom-pro'


# ============================================================================
# Tests: LLM Usage Recording (_record_llm_usage)
# ============================================================================

class TestLLMUsageRecording:
    """LLM 사용량 Redis 기록 테스트"""

    @patch('redis.from_url')
    def test_base_provider_record_llm_usage(self, mock_redis_from_url, monkeypatch):
        """BaseLLMProvider._record_llm_usage가 Redis에 올바르게 기록"""
        from shared.llm_providers import BaseLLMProvider

        # Concrete subclass for testing
        class DummyProvider(BaseLLMProvider):
            def generate_json(self, *a, **kw): pass
            def generate_chat(self, *a, **kw): pass

        monkeypatch.setenv("REDIS_URL", "redis://test:6379")
        mock_r = MagicMock()
        mock_redis_from_url.return_value = mock_r

        provider = DummyProvider()
        provider._record_llm_usage("scout", 1000, 500, "deepseek-chat")

        mock_redis_from_url.assert_called_once()
        mock_r.hincrby.assert_any_call(mock_r.hincrby.call_args_list[0][0][0], "calls", 1)
        mock_r.hincrby.assert_any_call(mock_r.hincrby.call_args_list[1][0][0], "tokens_in", 1000)
        mock_r.hincrby.assert_any_call(mock_r.hincrby.call_args_list[2][0][0], "tokens_out", 500)
        mock_r.expire.assert_called_once()

    @patch('redis.from_url')
    def test_record_llm_usage_redis_failure_no_raise(self, mock_redis_from_url):
        """Redis 실패 시 예외를 발생시키지 않음"""
        from shared.llm_providers import BaseLLMProvider

        class DummyProvider(BaseLLMProvider):
            def generate_json(self, *a, **kw): pass
            def generate_chat(self, *a, **kw): pass

        mock_redis_from_url.side_effect = Exception("Connection refused")

        provider = DummyProvider()
        # Should not raise
        provider._record_llm_usage("scout", 100, 50, "test-model")

    def test_openai_generate_json_passes_service(self, sample_response_schema):
        """OpenAILLMProvider.generate_json이 service 파라미터를 _record_llm_usage에 전달"""
        from shared.llm_providers import OpenAILLMProvider

        provider = object.__new__(OpenAILLMProvider)
        provider.safety_settings = None
        provider.default_model = 'deepseek-chat'
        provider.REASONING_MODELS = {"gpt-5-mini", "o1"}

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            'score': 80, 'grade': 'A', 'reason': 'Good'
        })
        mock_response.usage.prompt_tokens = 500
        mock_response.usage.completion_tokens = 200
        mock_client.chat.completions.create.return_value = mock_response
        provider.client = mock_client

        with patch.object(provider, '_record_llm_usage') as mock_record:
            provider.generate_json("Test", sample_response_schema, service="scout")
            mock_record.assert_called_once_with("scout", 500, 200, "deepseek-chat")

    def test_openai_generate_json_default_service_unknown(self, sample_response_schema):
        """OpenAILLMProvider.generate_json에서 service 미지정 시 'unknown'"""
        from shared.llm_providers import OpenAILLMProvider

        provider = object.__new__(OpenAILLMProvider)
        provider.safety_settings = None
        provider.default_model = 'deepseek-chat'
        provider.REASONING_MODELS = {"gpt-5-mini"}

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            'score': 70, 'grade': 'B', 'reason': 'OK'
        })
        mock_response.usage.prompt_tokens = 300
        mock_response.usage.completion_tokens = 100
        mock_client.chat.completions.create.return_value = mock_response
        provider.client = mock_client

        with patch.object(provider, '_record_llm_usage') as mock_record:
            provider.generate_json("Test", sample_response_schema)
            mock_record.assert_called_once_with("unknown", 300, 100, "deepseek-chat")

    def test_openai_generate_chat_passes_service(self):
        """OpenAILLMProvider.generate_chat이 service 파라미터를 _record_llm_usage에 전달"""
        from shared.llm_providers import OpenAILLMProvider

        provider = object.__new__(OpenAILLMProvider)
        provider.safety_settings = None
        provider.default_model = 'deepseek-chat'
        provider.REASONING_MODELS = {"gpt-5-mini"}

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hello"
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        mock_client.chat.completions.create.return_value = mock_response
        provider.client = mock_client

        with patch.object(provider, '_record_llm_usage') as mock_record:
            provider.generate_chat(
                [{"role": "user", "content": "Hi"}],
                service="briefing"
            )
            mock_record.assert_called_once_with("briefing", 100, 50, "deepseek-chat")

    def test_claude_generate_json_records_usage(self, sample_response_schema):
        """ClaudeLLMProvider.generate_json이 service 지정 시 사용량 기록"""
        from shared.llm_providers import ClaudeLLMProvider

        provider = object.__new__(ClaudeLLMProvider)
        provider.safety_settings = None
        provider.fast_model = 'claude-haiku-4-5'

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_content = MagicMock()
        mock_content.text = json.dumps({'score': 85, 'grade': 'A', 'reason': 'Great'})
        mock_response.content = [mock_content]
        mock_response.usage.input_tokens = 800
        mock_response.usage.output_tokens = 300
        mock_client.messages.create.return_value = mock_response
        provider.client = mock_client

        with patch.object(provider, '_record_llm_usage') as mock_record:
            provider.generate_json("Test", sample_response_schema, service="macro_council")
            mock_record.assert_called_once_with("macro_council", 800, 300, "claude-haiku-4-5")

    def test_claude_generate_json_no_record_without_service(self, sample_response_schema):
        """ClaudeLLMProvider.generate_json에서 service=None이면 기록 안 함"""
        from shared.llm_providers import ClaudeLLMProvider

        provider = object.__new__(ClaudeLLMProvider)
        provider.safety_settings = None
        provider.fast_model = 'claude-haiku-4-5'

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_content = MagicMock()
        mock_content.text = json.dumps({'score': 85, 'grade': 'A', 'reason': 'Great'})
        mock_response.content = [mock_content]
        mock_response.usage.input_tokens = 800
        mock_response.usage.output_tokens = 300
        mock_client.messages.create.return_value = mock_response
        provider.client = mock_client

        with patch.object(provider, '_record_llm_usage') as mock_record:
            provider.generate_json("Test", sample_response_schema)
            mock_record.assert_not_called()

    def test_claude_generate_chat_records_usage(self):
        """ClaudeLLMProvider.generate_chat이 service 지정 시 사용량 기록"""
        from shared.llm_providers import ClaudeLLMProvider

        provider = object.__new__(ClaudeLLMProvider)
        provider.safety_settings = None
        provider.fast_model = 'claude-haiku-4-5'

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_content = MagicMock()
        mock_content.text = "Hello response"
        mock_response.content = [mock_content]
        mock_response.usage.input_tokens = 200
        mock_response.usage.output_tokens = 100
        mock_client.messages.create.return_value = mock_response
        provider.client = mock_client

        with patch.object(provider, '_record_llm_usage') as mock_record:
            provider.generate_chat(
                [{"role": "user", "content": "Hi"}],
                service="briefing"
            )
            mock_record.assert_called_once_with("briefing", 200, 100, "claude-haiku-4-5")

    def test_cloud_failover_passes_service_to_inner_provider(self, sample_response_schema):
        """CloudFailoverProvider가 service를 inner provider에 전달"""
        from shared.llm_providers import CloudFailoverProvider

        # 직접 생성 (auth 우회)
        provider = object.__new__(CloudFailoverProvider)
        provider.tier_name = "REASONING"

        mock_inner = MagicMock()
        mock_inner.generate_json.return_value = {'score': 70, 'grade': 'B', 'reason': 'OK'}
        provider._providers = [mock_inner]
        provider._provider_names = ["MockProvider"]

        provider.generate_json("Test", sample_response_schema, service="scout")

        mock_inner.generate_json.assert_called_once()
        call_kwargs = mock_inner.generate_json.call_args[1]
        assert call_kwargs['service'] == 'scout'

    def test_cloud_failover_chat_passes_service(self):
        """CloudFailoverProvider.generate_chat도 service 전달"""
        from shared.llm_providers import CloudFailoverProvider

        provider = object.__new__(CloudFailoverProvider)
        provider.tier_name = "REASONING"

        mock_inner = MagicMock()
        mock_inner.generate_chat.return_value = {'text': 'response'}
        provider._providers = [mock_inner]
        provider._provider_names = ["MockProvider"]

        provider.generate_chat(
            [{"role": "user", "content": "Hi"}],
            service="macro_council"
        )

        mock_inner.generate_chat.assert_called_once()
        call_kwargs = mock_inner.generate_chat.call_args[1]
        assert call_kwargs['service'] == 'macro_council'

