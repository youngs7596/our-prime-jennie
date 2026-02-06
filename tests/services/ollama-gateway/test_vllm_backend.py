"""
tests/services/ollama-gateway/test_vllm_backend.py
===================================================
vLLM 백엔드 변환 로직 테스트
- Ollama → vLLM 요청 변환
- vLLM → Ollama 응답 변환
- 모델 이름 매핑
- 헬스 체크
- 라우팅 분기
"""

import json
import os
import sys
import pytest
from unittest.mock import patch, MagicMock

# gateway 모듈 로드를 위해 sys.path 설정
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
_gateway_path = os.path.join(_project_root, "services", "ollama-gateway")
if _gateway_path not in sys.path:
    sys.path.insert(0, _gateway_path)

# 환경변수 사전 설정 (모듈 로드 전)
os.environ.setdefault("BACKEND_MODE", "vllm")
os.environ.setdefault("VLLM_LLM_URL", "http://localhost:8001")
os.environ.setdefault("VLLM_EMBED_URL", "http://localhost:8002")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

# Redis 없이 Limiter가 작동하도록 in-memory storage 사용
os.environ["RATELIMIT_STORAGE_URI"] = "memory://"

# 모듈 임포트 (다른 main.py와 충돌 방지)
if "main" in sys.modules:
    del sys.modules["main"]
import main as gw


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 모델 매핑 테스트
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestVLLMModelMapping:
    """VLLM_MODEL_MAP 기반 모델 이름 변환 테스트"""

    def test_exaone_mapping(self):
        assert gw._resolve_vllm_model("exaone3.5:7.8b") == "LGAI-EXAONE/EXAONE-4.0-32B-AWQ"

    def test_exaone_short_mapping(self):
        assert gw._resolve_vllm_model("exaone") == "LGAI-EXAONE/EXAONE-4.0-32B-AWQ"

    def test_gpt_oss_mapping(self):
        assert gw._resolve_vllm_model("gpt-oss:20b") == "LGAI-EXAONE/EXAONE-4.0-32B-AWQ"

    def test_kure_mapping(self):
        assert gw._resolve_vllm_model("daynice/kure-v1") == "nlpai-lab/KURE-v1"

    def test_kure_short_mapping(self):
        assert gw._resolve_vllm_model("kure-v1") == "nlpai-lab/KURE-v1"

    def test_unknown_model_passthrough(self):
        """매핑에 없는 모델은 원본 이름 그대로 반환"""
        assert gw._resolve_vllm_model("some-custom-model") == "some-custom-model"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# vLLM LLM 변환 테스트
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestVLLMGenerate:
    """Ollama /api/generate → vLLM /v1/chat/completions 변환 테스트"""

    def _mock_vllm_response(self, content="Hello!", prompt_tokens=10, completion_tokens=5):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop"
            }],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}
        }
        mock_response.raise_for_status = MagicMock()
        return mock_response

    @patch("main.requests.post")
    def test_generate_to_vllm(self, mock_post):
        """generate 요청이 vLLM chat/completions로 변환되는지 확인"""
        mock_post.return_value = self._mock_vllm_response()

        payload = {
            "model": "exaone3.5:7.8b",
            "prompt": "Hello, world!",
            "options": {"temperature": 0}
        }

        result = gw._call_vllm_llm("/api/generate", payload, timeout=60)

        # vLLM으로의 요청 확인
        call_args = mock_post.call_args
        assert call_args[0][0] == "http://localhost:8001/v1/chat/completions"
        sent_payload = call_args[1]["json"]
        assert sent_payload["model"] == "LGAI-EXAONE/EXAONE-4.0-32B-AWQ"
        assert sent_payload["messages"] == [{"role": "user", "content": "Hello, world!"}]
        assert sent_payload["temperature"] == 0
        assert sent_payload["stream"] is False

        # Ollama 형식 응답 확인
        assert result["response"] == "Hello!"
        assert result["model"] == "exaone3.5:7.8b"
        assert result["done"] is True
        assert result["eval_count"] == 5
        assert result["prompt_eval_count"] == 10

    @patch("main.requests.post")
    def test_generate_with_system_prompt(self, mock_post):
        """system 프롬프트가 포함된 generate 요청"""
        mock_post.return_value = self._mock_vllm_response(content="OK", prompt_tokens=20, completion_tokens=1)

        payload = {
            "model": "exaone3.5:7.8b",
            "prompt": "Analyze this",
            "system": "You are an analyst",
            "options": {"temperature": 0.2}
        }

        gw._call_vllm_llm("/api/generate", payload, timeout=60)

        sent_payload = mock_post.call_args[1]["json"]
        assert len(sent_payload["messages"]) == 2
        assert sent_payload["messages"][0] == {"role": "system", "content": "You are an analyst"}
        assert sent_payload["messages"][1] == {"role": "user", "content": "Analyze this"}

    @patch("main.requests.post")
    def test_generate_json_format(self, mock_post):
        """format: json 요청 시 response_format 변환"""
        mock_post.return_value = self._mock_vllm_response(content='{"key": "value"}')

        payload = {
            "model": "exaone3.5:7.8b",
            "prompt": "Return JSON",
            "format": "json",
            "options": {"temperature": 0}
        }

        gw._call_vllm_llm("/api/generate", payload, timeout=60)

        sent_payload = mock_post.call_args[1]["json"]
        assert sent_payload["response_format"] == {"type": "json_object"}

    @patch("main.requests.post")
    def test_generate_default_options(self, mock_post):
        """options가 없는 경우 기본값 사용"""
        mock_post.return_value = self._mock_vllm_response()

        payload = {
            "model": "exaone3.5:7.8b",
            "prompt": "test",
        }

        gw._call_vllm_llm("/api/generate", payload, timeout=60)

        sent_payload = mock_post.call_args[1]["json"]
        assert sent_payload["temperature"] == 0.7  # default
        assert sent_payload["max_tokens"] == 2048  # default


class TestVLLMChat:
    """Ollama /api/chat → vLLM /v1/chat/completions 변환 테스트"""

    @patch("main.requests.post")
    def test_chat_to_vllm(self, mock_post):
        """chat 요청이 vLLM으로 정상 변환"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{
                "message": {"role": "assistant", "content": "Hi there!"},
                "finish_reason": "stop"
            }],
            "usage": {"prompt_tokens": 8, "completion_tokens": 3}
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"}
        ]
        payload = {
            "model": "exaone3.5:7.8b",
            "messages": messages,
            "options": {"temperature": 0.5}
        }

        result = gw._call_vllm_llm("/api/chat", payload, timeout=60)

        # vLLM 요청 확인
        sent_payload = mock_post.call_args[1]["json"]
        assert sent_payload["model"] == "LGAI-EXAONE/EXAONE-4.0-32B-AWQ"
        assert sent_payload["messages"] == messages
        assert sent_payload["temperature"] == 0.5

        # Ollama chat 응답 형식 확인
        assert result["message"]["role"] == "assistant"
        assert result["message"]["content"] == "Hi there!"
        assert result["model"] == "exaone3.5:7.8b"
        assert result["done"] is True
        assert result["eval_count"] == 3


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# vLLM Embedding 변환 테스트
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestVLLMEmbed:
    """Ollama /api/embed → vLLM /v1/embeddings 변환 테스트"""

    @patch("main.requests.post")
    def test_embed_single(self, mock_post):
        """단일 텍스트 임베딩"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [{"embedding": [0.1, 0.2, 0.3], "index": 0}],
            "usage": {"prompt_tokens": 5}
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        payload = {
            "model": "daynice/kure-v1",
            "input": "Hello world"
        }

        result = gw._call_vllm_embed(payload, timeout=60)

        # vLLM 요청 확인
        call_args = mock_post.call_args
        assert call_args[0][0] == "http://localhost:8002/v1/embeddings"
        sent_payload = call_args[1]["json"]
        assert sent_payload["model"] == "nlpai-lab/KURE-v1"
        assert sent_payload["input"] == "Hello world"

        # Ollama 형식 응답 확인
        assert result["embeddings"] == [[0.1, 0.2, 0.3]]
        assert result["model"] == "daynice/kure-v1"

    @patch("main.requests.post")
    def test_embed_batch(self, mock_post):
        """배치 임베딩"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"embedding": [0.1, 0.2], "index": 0},
                {"embedding": [0.3, 0.4], "index": 1},
            ],
            "usage": {"prompt_tokens": 8}
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        payload = {
            "model": "daynice/kure-v1",
            "input": ["Hello", "World"]
        }

        result = gw._call_vllm_embed(payload, timeout=60)

        assert result["embeddings"] == [[0.1, 0.2], [0.3, 0.4]]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 라우팅 테스트 (call_ollama_with_breaker)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestBackendRouting:
    """BACKEND_MODE에 따른 라우팅 테스트"""

    @patch("main.requests.post")
    def test_vllm_mode_routes_generate_to_vllm(self, mock_post):
        """vLLM 모드에서 generate 요청이 vLLM으로 라우팅"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "test"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1}
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = gw.call_ollama_with_breaker(
            "/api/generate",
            {"model": "exaone3.5:7.8b", "prompt": "test", "options": {}},
            timeout=60
        )

        assert "response" in result
        call_url = mock_post.call_args[0][0]
        assert "8001" in call_url
        assert "/v1/chat/completions" in call_url

    @patch("main.requests.post")
    def test_vllm_mode_routes_chat_to_vllm(self, mock_post):
        """vLLM 모드에서 chat 요청이 vLLM으로 라우팅"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "test"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1}
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = gw.call_ollama_with_breaker(
            "/api/chat",
            {"model": "exaone3.5:7.8b", "messages": [{"role": "user", "content": "hi"}], "options": {}},
            timeout=60
        )

        assert "message" in result
        call_url = mock_post.call_args[0][0]
        assert "8001" in call_url

    @patch("main.requests.post")
    def test_vllm_mode_routes_embed_to_vllm(self, mock_post):
        """vLLM 모드에서 embed 요청이 vLLM embed 서버로 라우팅"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [{"embedding": [0.1], "index": 0}],
            "usage": {"prompt_tokens": 1}
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = gw.call_ollama_with_breaker(
            "/api/embed",
            {"model": "daynice/kure-v1", "input": "test"},
            timeout=60
        )

        assert "embeddings" in result
        call_url = mock_post.call_args[0][0]
        assert "8002" in call_url
        assert "/v1/embeddings" in call_url

    @patch("main.requests.post")
    def test_vllm_mode_routes_embeddings_to_vllm(self, mock_post):
        """vLLM 모드에서 /api/embeddings 요청도 vLLM embed 서버로 라우팅"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [{"embedding": [0.1], "index": 0}],
            "usage": {"prompt_tokens": 1}
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = gw.call_ollama_with_breaker(
            "/api/embeddings",
            {"model": "daynice/kure-v1", "input": "test"},
            timeout=60
        )

        assert "embeddings" in result

    @patch("main.requests.post")
    def test_cloud_proxy_bypasses_vllm(self, mock_post):
        """Cloud Proxy (:cloud 접미사)는 vLLM 무시하고 cloud로 라우팅"""
        original_key = gw.OLLAMA_API_KEY
        try:
            gw.OLLAMA_API_KEY = "test-key"
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "message": {"role": "assistant", "content": "cloud response"},
                "done": True
            }
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response

            result = gw.call_ollama_with_breaker(
                "/api/chat",
                {"model": "qwen3:cloud", "messages": [{"role": "user", "content": "test"}]},
                timeout=60
            )

            call_url = mock_post.call_args[0][0]
            assert "ollama.com" in call_url
        finally:
            gw.OLLAMA_API_KEY = original_key


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 헬스 체크 테스트
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestHealthCheck:

    @patch("main.requests.get")
    def test_vllm_health_both_up(self, mock_get):
        """vLLM 모드: LLM + Embed 둘 다 정상이면 healthy"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        assert gw._check_vllm_health() is True
        assert mock_get.call_count == 2

    @patch("main.requests.get")
    def test_vllm_health_llm_down(self, mock_get):
        """vLLM 모드: LLM 서버 다운이면 unhealthy"""
        def side_effect(url, **kwargs):
            if "8001" in url:
                raise ConnectionError("Connection refused")
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            return mock_resp

        mock_get.side_effect = side_effect
        assert gw._check_vllm_health() is False

    @patch("main.requests.get")
    def test_vllm_health_embed_down(self, mock_get):
        """vLLM 모드: Embed 서버 다운이면 unhealthy"""
        def side_effect(url, **kwargs):
            if "8002" in url:
                raise ConnectionError("Connection refused")
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            return mock_resp

        mock_get.side_effect = side_effect
        assert gw._check_vllm_health() is False

    @patch("main.requests.get")
    def test_check_ollama_health_vllm_delegates(self, mock_get):
        """check_ollama_health()가 vLLM 모드에서 _check_vllm_health를 호출"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        result = gw.check_ollama_health()
        assert result is True
        # vLLM 모드이므로 /v1/models 호출 확인
        call_urls = [c[0][0] for c in mock_get.call_args_list]
        assert any("/v1/models" in url for url in call_urls)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Flask 엔드포인트 통합 테스트
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestFlaskEndpoints:
    """Flask 테스트 클라이언트를 이용한 엔드포인트 테스트"""

    @pytest.fixture
    def client(self):
        gw.app.config["TESTING"] = True
        with gw.app.test_client() as c:
            yield c

    @patch("main.requests.get")
    def test_health_endpoint_vllm_mode(self, mock_get, client):
        """Health 엔드포인트가 backend_mode를 반환"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        resp = client.get("/health")
        data = resp.get_json()

        assert data["backend_mode"] == "vllm"
        assert data["service"] == "ollama-gateway"

    @patch("main.requests.post")
    def test_generate_endpoint_via_vllm(self, mock_post, client):
        """POST /api/generate가 vLLM 경유로 정상 작동"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "response text"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 10}
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        resp = client.post("/api/generate", json={
            "model": "exaone3.5:7.8b",
            "prompt": "Hello",
            "options": {"temperature": 0}
        })

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["response"] == "response text"
        assert data["model"] == "exaone3.5:7.8b"

    @patch("main.requests.post")
    def test_chat_endpoint_via_vllm(self, mock_post, client):
        """POST /api/chat가 vLLM 경유로 정상 작동"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "chat reply"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3}
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        resp = client.post("/api/chat", json={
            "model": "exaone3.5:7.8b",
            "messages": [{"role": "user", "content": "Hi"}],
            "options": {"temperature": 0}
        })

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["message"]["content"] == "chat reply"

    @patch("main.requests.post")
    def test_embed_endpoint_via_vllm(self, mock_post, client):
        """POST /api/embed가 vLLM 경유로 정상 작동"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [{"embedding": [0.1, 0.2, 0.3], "index": 0}],
            "usage": {"prompt_tokens": 3}
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        resp = client.post("/api/embed", json={
            "model": "daynice/kure-v1",
            "input": "test text"
        })

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["embeddings"] == [[0.1, 0.2, 0.3]]

    @patch("main.requests.get")
    def test_models_endpoint_vllm(self, mock_get, client):
        """GET /api/models가 vLLM에서 모델 목록을 가져옴"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [{"id": "LGAI-EXAONE/EXAONE-4.0-32B-AWQ"}]
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        resp = client.get("/api/models")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "models" in data
