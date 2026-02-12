"""
shared/llm_providers.py - LLM Provider 클래스들

이 모듈은 각 LLM 서비스(Gemini, OpenAI, Claude, Ollama)에 대한 Provider 클래스를 제공합니다.

핵심 구성요소:
-------------
1. BaseLLMProvider: LLM 프로바이더 추상 베이스 클래스
2. GeminiLLMProvider: Google Gemini API 구현 (Scout 단계)
3. ClaudeLLMProvider: Anthropic Claude API 구현 (Hunter 단계)  
4. OpenAILLMProvider: OpenAI GPT API 구현 (Judge 단계)
5. OllamaLLMProvider: Local LLM API 구현 (Cost Saving)
"""

import logging
import json
import os
import re
import time
import requests
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)


class BaseLLMProvider(ABC):
    def __init__(self, safety_settings=None):
        self.safety_settings = safety_settings

    @property
    def name(self) -> str:
        return self.__class__.__name__

    def _record_llm_usage(self, service: str, tokens_in: int, tokens_out: int, model: str):
        """
        LLM 사용량을 Redis에 기록 (Dashboard 통계용)
        """
        try:
            import redis
            from datetime import datetime

            redis_url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379")
            r = redis.from_url(redis_url, decode_responses=True)

            today = datetime.now().strftime("%Y-%m-%d")
            key = f"llm:stats:{today}:{service}"

            r.hincrby(key, "calls", 1)
            r.hincrby(key, "tokens_in", tokens_in)
            r.hincrby(key, "tokens_out", tokens_out)
            r.expire(key, 86400 * 7)  # 7일 보관

            logger.debug(f"📊 [LLM Stats] {service}: +{tokens_in}/{tokens_out} tokens")
        except Exception as e:
            logger.warning(f"⚠️ [LLM Stats] 사용량 기록 실패: {e}")

    @abstractmethod
    def generate_json(
        self,
        prompt: str,
        response_schema: Dict,
        *,
        temperature: float = 0.2,
        model_name: Optional[str] = None,
        fallback_models: Optional[Sequence[str]] = None,
        service: Optional[str] = None,
    ) -> Dict:
        ...

    @abstractmethod
    def generate_chat(
        self,
        history: List[Dict],
        response_schema: Optional[Dict] = None,
        *,
        temperature: float = 0.2,
        model_name: Optional[str] = None,
        fallback_models: Optional[Sequence[str]] = None,
        service: Optional[str] = None,
    ) -> Dict:
        ...


class OllamaLLMProvider(BaseLLMProvider):
    """
    Local LLM Provider — vLLM 직접 호출 (OpenAI-compatible API).
    Implements defensive coding: Retries, Tag Removal, Timeouts, Keep-Alive.

    vLLM 모드:
    - VLLM_LLM_URL로 직접 vLLM /v1/chat/completions 호출
    - 토큰 클램핑: 한국어 ~2char/token 기준 동적 max_tokens 조정

    Debug 로깅:
    - LLM_DEBUG_LOG_PATH 환경변수 설정 시 요청/응답을 JSON 파일로 저장
    """

    # Ollama 모델명 → vLLM 실제 모델명 매핑 (ollama-gateway에서 이전)
    VLLM_MODEL_MAP = {
        "exaone3.5:7.8b": "LGAI-EXAONE/EXAONE-4.0-32B-AWQ",
        "exaone": "LGAI-EXAONE/EXAONE-4.0-32B-AWQ",
        "gpt-oss:20b": "LGAI-EXAONE/EXAONE-4.0-32B-AWQ",
        "gemma3:27b": "LGAI-EXAONE/EXAONE-4.0-32B-AWQ",  # 레거시 호환
    }

    def __init__(
        self,
        model: str,
        state_manager: Any,
        is_fast_tier: bool = False,
        is_thinking_tier: bool = False,
        host: str = "http://localhost:11434"
    ):
        super().__init__()
        self.model = model
        self.state_manager = state_manager
        self.host = os.getenv("OLLAMA_HOST", host)

        # vLLM 직접 호출 설정
        self.vllm_llm_url = os.getenv("VLLM_LLM_URL", "http://localhost:8001/v1")
        self.vllm_max_model_len = int(os.getenv("VLLM_MAX_MODEL_LEN", "4096"))

        # ☁️ Cloud 직접 연결 모드 (Gateway 우회)
        self.is_cloud = model.endswith(":cloud")
        self._cloud_api_key = None
        if self.is_cloud:
            self.cloud_model = model.replace(":cloud", "")
            self.cloud_host = os.getenv("OLLAMA_CLOUD_HOST", "https://ollama.com")
            self._cloud_api_key = self._load_cloud_api_key()
            if self._cloud_api_key:
                logger.info(f"☁️ [Ollama] Cloud 직접 연결 모드: {self.cloud_host} (model={self.cloud_model})")
            else:
                logger.warning(f"⚠️ [Ollama] Cloud 모델 요청이나 API Key 없음. Gateway 폴백 사용")

        # Debug 로깅 설정 (Toggle Support)
        self.debug_enabled = os.getenv("LLM_DEBUG_ENABLED", "false").lower() == "true"
        # 기본 경로 설정
        default_log_path = "/app/logs/llm_interactions.jsonl"
        self.debug_log_path = os.getenv("LLM_DEBUG_LOG_PATH", default_log_path)
        
        if self.debug_enabled:
            logger.info(f"📝 [Ollama] Debug 로깅 활성화: {self.debug_log_path}")
        else:
            self.debug_log_path = None # Disable logging explicitly
        
        # [Defensive] Timeout Strategy
        if is_fast_tier:
            self.timeout = 60  # 1 min for fast tasks
        elif is_thinking_tier:
            self.timeout = 600 # 10 min for deep thinking (Increased from 300s)
        else:
            # Reasoning Tier
            self.timeout = 600 # Increased to 600s for Qwen3:32B stability
            
        self.max_retries = 2  # CloudFailover 3단계이므로 개별 retry 최소화

    def _load_cloud_api_key(self) -> Optional[str]:
        """Ollama Cloud API Key 로드 (env → secrets.json)"""
        key = os.getenv("OLLAMA_API_KEY")
        if not key:
            secrets_file = os.getenv("SECRETS_FILE", "/app/config/secrets.json")
            if os.path.exists(secrets_file):
                try:
                    with open(secrets_file, "r") as f:
                        secrets = json.load(f)
                        key = secrets.get("ollama_api_key") or secrets.get("ollama-api-key")
                except Exception as e:
                    logger.warning(f"⚠️ [Ollama] Cloud API Key 로드 실패: {e}")
        return key

    def _call_cloud_api(self, endpoint: str, payload: Dict) -> Dict:
        """
        Ollama Cloud API 직접 호출 (Gateway 우회)
        - Ollama Cloud는 /api/chat만 지원 → /api/generate 요청을 자동 변환
        - 5xx 에러 시 exponential backoff retry (최대 5회)
        - 응답 body 로깅으로 에러 원인 추적 가능
        """
        headers = {"Content-Type": "application/json"}
        if self._cloud_api_key:
            headers["Authorization"] = f"Bearer {self._cloud_api_key}"

        # Cloud용 페이로드 구성
        cloud_payload = dict(payload)
        # Ollama Cloud에서 :cloud는 실제 모델 태그 → 유지
        model_in_payload = cloud_payload.get("model", self.model)
        if not model_in_payload.endswith(":cloud"):
            model_in_payload = model_in_payload.replace(":cloud", "")
        cloud_payload["model"] = model_in_payload
        cloud_payload["stream"] = False

        # Cloud 전용: 로컬 Ollama 옵션 제거 (num_ctx, num_predict 등은 Cloud에서 미지원)
        if "options" in cloud_payload:
            cloud_opts = {}
            # temperature만 유지, 나머지 로컬 전용 옵션 제거
            if "temperature" in cloud_payload["options"]:
                cloud_opts["temperature"] = cloud_payload["options"]["temperature"]
            if cloud_opts:
                cloud_payload["options"] = cloud_opts
            else:
                del cloud_payload["options"]
        # keep_alive도 로컬 전용
        cloud_payload.pop("keep_alive", None)

        # Ollama Cloud는 /api/chat만 지원 → /api/generate를 /api/chat으로 변환
        is_generate_compat = False
        if endpoint == "/api/generate":
            cloud_endpoint = "/api/chat"
            prompt = cloud_payload.pop("prompt", "")
            cloud_payload["messages"] = [{"role": "user", "content": prompt}]
            is_generate_compat = True
        else:
            cloud_endpoint = endpoint

        url = f"{self.cloud_host}{cloud_endpoint}"

        max_retries = int(os.getenv("OLLAMA_CLOUD_MAX_RETRIES", "2"))
        base_delay = float(os.getenv("OLLAMA_CLOUD_RETRY_DELAY", "1.0"))

        for attempt in range(max_retries):
            logger.info(f"☁️ [Ollama Cloud] 요청: {cloud_endpoint} (model={cloud_payload['model']}, attempt={attempt + 1}/{max_retries})")

            try:
                response = requests.post(url, json=cloud_payload, headers=headers, timeout=self.timeout)
                response.raise_for_status()
                result = response.json()

                # /api/generate 호환: chat 응답을 generate 형식으로 변환
                if is_generate_compat:
                    content = result.get("message", {}).get("content", "")
                    result["response"] = content

                return result
            except requests.exceptions.HTTPError as e:
                status_code = e.response.status_code if e.response is not None else 0
                # 응답 body 로깅 (에러 원인 추적용)
                response_body = ""
                try:
                    response_body = e.response.text[:500] if e.response is not None else "No response body"
                except Exception:
                    response_body = "Failed to read response body"

                if status_code >= 500 and attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)  # 3s, 6s, 12s, 24s
                    logger.warning(
                        f"⚠️ [Ollama Cloud] {status_code} 에러 (attempt {attempt + 1}/{max_retries}). "
                        f"{delay:.1f}s 후 재시도... body={response_body}"
                    )
                    time.sleep(delay)
                    continue
                else:
                    logger.error(
                        f"❌ [Ollama Cloud] 최종 실패: {status_code} {e}. body={response_body}"
                    )
                    raise

    def _log_llm_interaction(self, interaction_type: str, request_data: Dict, response_data: Dict, model_name: str = None):
        """
        LLM 요청/응답을 JSON 파일로 저장 (디버깅용)
        LLM_DEBUG_LOG_PATH 환경변수가 설정된 경우에만 활성화
        """
        if not self.debug_log_path:
            return
        
        try:
            from datetime import datetime
            
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "type": interaction_type,
                "model": model_name or self.model,
                "request": request_data,
                "response": response_data
            }
            
            # 파일에 추가 (줄 단위 JSON - JSONL 형식)
            with open(self.debug_log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
            
            logger.info(f"📝 [Ollama] Debug log saved: {interaction_type}")
        except Exception as e:
            logger.warning(f"⚠️ [Ollama] Debug log failed: {e}")

    def _clean_deepseek_tags(self, text: str) -> str:
        """
        [Defensive] Remove <think>...</think> tags from DeepSeek output.
        Some models output reasoning trace which breaks JSON parsing.
        """
        # Remove multiline think tags
        cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
        return cleaned.strip()

    def _ensure_model_loaded(self):
        """
        [State Management] Ensure the model is loaded efficiently.
        """
        current = self.state_manager.get_current_model()
        if current != self.model:
            logger.info(f"🔄 [Ollama] Switching model: {current} -> {self.model} ...")
            # Note: The actual loading happens on the first inference request,
            # but we update our state manager to reflect intent.
            self.state_manager.set_current_model(self.model)

    def _clamp_max_tokens(self, prompt_text: str, requested_max: int) -> int:
        """vLLM max_model_len 초과 방지: 프롬프트 길이 추정 후 동적 클램핑"""
        estimated_input = max(len(prompt_text) // 2, 100)  # 한국어 ~2char/token
        available = self.vllm_max_model_len - estimated_input - 64  # 64 토큰 여유
        safe_max = max(available, 256)  # 최소 256 토큰 보장
        return min(requested_max, safe_max)

    def _call_vllm_direct(self, endpoint: str, payload: Dict) -> Dict:
        """
        vLLM OpenAI-compatible API 직접 호출.
        Ollama 형식 payload를 OpenAI 형식으로 변환.
        """
        model_name = payload.get("model", self.model)
        vllm_model = self.VLLM_MODEL_MAP.get(model_name, model_name)
        options = payload.get("options", {})
        temperature = options.get("temperature", 0.2)
        requested_max_tokens = options.get("num_predict", 2048)

        # /api/generate → /v1/chat/completions 변환
        if endpoint == "/api/generate":
            prompt = payload.get("prompt", "")
            messages = [{"role": "user", "content": prompt}]
            max_tokens = self._clamp_max_tokens(prompt, requested_max_tokens)
        elif endpoint == "/api/chat":
            messages = payload.get("messages", [])
            total_text = " ".join(m.get("content", "") for m in messages)
            max_tokens = self._clamp_max_tokens(total_text, requested_max_tokens)
        else:
            raise ValueError(f"Unsupported endpoint: {endpoint}")

        openai_payload = {
            "model": vllm_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        url = f"{self.vllm_llm_url}/chat/completions"
        last_error = None

        for attempt in range(self.max_retries):
            try:
                logger.info(f"🔮 [vLLM] 직접 호출: {url} (model={vllm_model}, max_tokens={max_tokens})")
                response = requests.post(url, json=openai_payload, timeout=self.timeout)
                response.raise_for_status()
                result = response.json()

                content = result["choices"][0]["message"]["content"]

                # OpenAI → Ollama 응답 형식 변환
                if endpoint == "/api/generate":
                    return {"response": content}
                else:
                    return {"message": {"content": content}}
            except requests.exceptions.Timeout:
                logger.warning(f"⚠️ [vLLM] Timeout ({self.timeout}s) on attempt {attempt+1}/{self.max_retries}")
                last_error = TimeoutError(f"vLLM timed out after {self.timeout}s")
            except Exception as e:
                logger.warning(f"⚠️ [vLLM] Error on attempt {attempt+1}/{self.max_retries}: {e}")
                last_error = e

            time.sleep(2 ** attempt)

        raise last_error

    def _call_ollama_api(self, endpoint: str, payload: Dict) -> Dict:
        """
        [Defensive] Robust API Caller with Retries
        Cloud 모델: Ollama Cloud API 직접 호출
        Local 모델: vLLM 직접 호출
        """
        # ☁️ Cloud 모드: Ollama Cloud API 직접 호출
        if self.is_cloud and self._cloud_api_key:
            return self._call_cloud_api(endpoint, payload)

        # vLLM 직접 호출 (Gateway 제거됨)
        return self._call_vllm_direct(endpoint, payload)

    def generate_json(
        self,
        prompt: str,
        response_schema: Dict,
        *,
        temperature: float = 0.2,
        model_name: Optional[str] = None,
        fallback_models: Optional[Sequence[str]] = None,
        service: Optional[str] = None,
    ) -> Dict:
        target_model = model_name or self.model

        payload = {
            "model": target_model,
            "prompt": prompt,
            # "format": "json",  <-- [Fix] Removed because Qwen3 returns empty JSON with this
            "options": {
                "temperature": temperature,
                "num_ctx": 8192, # Context Window
                "num_predict": 4096, # [Fix] Increase output limit (default is 128)
            }
        }

        # [Defensive] Internal Retry for Empty/Malformed Content
        # Sometimes Ollama returns empty string or cut-off JSON.
        # We retry locally before falling back to Cloud.
        max_internal_retries = 2

        for attempt in range(max_internal_retries):
            try:
                # [Debug] Log Request/Response for Qwen3 stability check
                if self.debug_enabled:
                    logger.info(f"📝 [Ollama] Request Prompt (First 500 chars): {prompt[:500]}...")
                
                result = self._call_ollama_api("/api/generate", payload)
                content = result.get("response", "")
                
                # [Debug] Log Raw Response
                if self.debug_enabled:
                    logger.info(f"📝 [Ollama] Raw Response (len={len(content)}): {content[:500]}... [Truncated]")
                
                if not content:
                    logger.warning(f"   ⚠️ [Ollama] Empty response content received! (Attempt {attempt+1}/{max_internal_retries})")
                    if attempt < max_internal_retries - 1:
                        time.sleep(1)
                        continue
                    else:
                        raise ValueError("Empty response content from Ollama after retries")
                
                # Debug 로깅
                self._log_llm_interaction(
                    interaction_type="generate_json",
                    request_data={"prompt": prompt, "temperature": temperature},
                    response_data={"content": content, "parsed": None},
                    model_name=target_model
                )
                
                # [Defensive] Tag Removal
                raw_content = content
                content = self._clean_deepseek_tags(content)
                
                if not content.strip() and raw_content.strip():
                    error_msg = f"Model generated {len(raw_content)} chars of reasoning but no final JSON output."
                    logger.warning(f"⚠️ [Ollama] {error_msg}")
                    if attempt < max_internal_retries - 1:
                        time.sleep(1)
                        continue
                    raise ValueError(error_msg)
                
                # [Defensive] JSON Parsing with basic cleanup
                parsed = None
                try:
                    parsed = json.loads(content)
                except json.JSONDecodeError:
                    # Try to find JSON block if mixed with text
                    if "```json" in content:
                        content = content.split("```json")[1].split("```")[0]
                    elif "```" in content:
                        content = content.split("```")[1].split("```")[0]
                    elif "{" in content:
                        start = content.find("{")
                        end = content.rfind("}") + 1
                        content = content[start:end]
                    
                    if not content.strip():
                         logger.error(f"❌ [Ollama] No JSON found. Raw Content:\n{raw_content}")
                         if attempt < max_internal_retries - 1:
                            time.sleep(1)
                            continue
                         raise ValueError(f"No JSON content found in output (len={len(raw_content)})")
                         
                    parsed = json.loads(content)
                
                # [Defensive] Case-insensitive Key Normalization
                if response_schema:
                     normalized = {}
                     required_keys = response_schema.get("required", [])
                     parsed_keys_lower = {k.lower(): k for k in parsed.keys()}
                     
                     for req_key in required_keys:
                         req_key_lower = req_key.lower()
                         if req_key in parsed:
                             normalized[req_key] = parsed[req_key]
                         elif req_key_lower in parsed_keys_lower:
                             original_key = parsed_keys_lower[req_key_lower]
                             normalized[req_key] = parsed[original_key]
                             logger.warning(f"⚠️ [Ollama] Normalized key case: {original_key} -> {req_key}")
                     
                     # Merge normalized keys back into parsed
                     parsed.update(normalized) # Ensure required keys are present
                
                return parsed
                
            except Exception as e:
                if attempt < max_internal_retries - 1:
                    logger.warning(f"⚠️ [Ollama] Retryable error during generation: {e}")
                    time.sleep(2 ** attempt)  # Exponential backoff
                else:
                    logger.error(f"❌ [Ollama] generate_json failed after {max_internal_retries} attempts: {e}")
                    raise

    def generate_chat(
        self,
        history: List[Dict],
        response_schema: Optional[Dict] = None,
        *,
        temperature: float = 0.2,
        model_name: Optional[str] = None,
        fallback_models: Optional[Sequence[str]] = None,
        service: Optional[str] = None,
    ) -> Dict:
        target_model = model_name or self.model

        messages = []
        for h in history:
            role = h.get('role', 'user')
            if role == 'model': role = 'assistant'
            content = h.get('parts', [{}])[0].get('text', '') or h.get('content', '')
            messages.append({"role": role, "content": content})

        payload = {
            "model": target_model,
            "messages": messages,
            "options": {
                "temperature": temperature,
                "num_ctx": 8192,
                "num_predict": 4096, # [Fix] Increase output limit
            }
        }
        
        if response_schema:
            pass # payload["format"] = "json" <-- [Fix] Removed

        max_internal_retries = 2
        
        for attempt in range(max_internal_retries):
            try:
                # [Debug] Log Chat Request
                if self.debug_enabled:
                    logger.info(f"📝 [Ollama] Chat Messages Check: {len(messages)} messages.")
                
                result = self._call_ollama_api("/api/chat", payload)
                content = result.get("message", {}).get("content", "")
                
                # [Debug] Log JSON Response
                if self.debug_enabled:
                    logger.info(f"📝 [Ollama] Chat Response: {content[:500]}... [Truncated]")
                
                if not content:
                    logger.warning(f"   ⚠️ [Ollama] Empty chat response received! (Attempt {attempt+1}/{max_internal_retries})")
                    if attempt < max_internal_retries - 1:
                        time.sleep(1)
                        continue
                    else:
                        raise ValueError("Empty chat response from Ollama after retries")

                # Debug 로깅
                self._log_llm_interaction(
                    interaction_type="generate_chat",
                    request_data={"messages": messages, "temperature": temperature},
                    response_data={"content": content},
                    model_name=target_model
                )
                
                # [Defensive] Tag Removal
                content = self._clean_deepseek_tags(content)

                if response_schema:
                    try:
                        return json.loads(content)
                    except json.JSONDecodeError:
                         # Try to find JSON block
                         if "```json" in content:
                            content = content.split("```json")[1].split("```")[0]
                         elif "```" in content:
                            content = content.split("```")[1].split("```")[0]
                         elif "{" in content:
                            start = content.find("{")
                            end = content.rfind("}") + 1
                            content = content[start:end]
                            
                         if not content.strip():
                             logger.error(f"❌ [Ollama] No JSON found in chat. Raw Content:\n{content}")
                             if attempt < max_internal_retries - 1:
                                time.sleep(1)
                                continue
                             raise ValueError("No JSON content found in chat output")
                             
                         return json.loads(content)
                
                return {"text": content}

            except Exception as e:
                if attempt < max_internal_retries - 1:
                    logger.warning(f"⚠️ [Ollama] Retryable error during chat generation: {e}")
                    time.sleep(2 ** attempt)
                else:
                    logger.error(f"❌ [Ollama] generate_chat failed after {max_internal_retries} attempts: {e}")
                    raise


class GeminiLLMProvider(BaseLLMProvider):
    def __init__(self, project_id: str, gemini_api_key_secret: str, safety_settings):
        super().__init__(safety_settings)
        import google.genai as genai
        from . import auth
        
        api_key = auth.get_secret(gemini_api_key_secret, project_id)
        if not api_key:
            raise RuntimeError(f"Secret '{gemini_api_key_secret}' not found in configuration (secrets.json or env vars)")

        # google.genai는 Client/GenerativeModel에 직접 키를 전달하므로 전역 configure 불필요
        self._genai = genai
        self._api_key = api_key
        self._client = genai.Client(api_key=api_key)
        # Updated to Gemini 2.5 Flash for Cost Efficiency (User Request)
        # Note: 'gemini-3-pro' is too expensive for default usage.
        self.default_model = os.getenv("LLM_MODEL_NAME", "gemini-2.5-flash")
        self.flash_model = os.getenv("LLM_FLASH_MODEL_NAME", "gemini-2.5-flash")
        self._model_cache: Dict[tuple[str, float, str], Any] = {}

    def _get_api_key(self) -> str:
        return self._api_key

    @property
    def name(self) -> str:
        return "gemini"

    def flash_model_name(self) -> str:
        return self.flash_model

    def _get_or_create_model(self, model_name: str, response_schema: Dict, temperature: float):
        schema_fingerprint = json.dumps(response_schema, sort_keys=True)
        cache_key = (model_name, temperature, schema_fingerprint)
        if cache_key not in self._model_cache:
            generation_config = {
                "temperature": temperature,
                "response_mime_type": "application/json",
                "response_schema": response_schema,
            }
            self._model_cache[cache_key] = {
                "model_name": model_name,
                "generation_config": generation_config,
            }
        return self._model_cache[cache_key]

    def generate_json(
        self,
        prompt: str,
        response_schema: Dict,
        *,
        temperature: float = 0.2,
        model_name: Optional[str] = None,
        fallback_models: Optional[Sequence[str]] = None,
        service: Optional[str] = None,
    ) -> Dict:
        model_candidates = [model_name or self.default_model]
        if fallback_models:
            model_candidates.extend(fallback_models)

        last_error: Optional[Exception] = None
        max_retries = 3

        for target_model in model_candidates:
            # [Defensive] Retry Logic for Rate Limits (429)
            for attempt in range(max_retries + 1):
                try:
                    model = self._get_or_create_model(target_model, response_schema, temperature)
                    response = self._client.models.generate_content(
                        model=model["model_name"],
                        contents=prompt,
                        config=model["generation_config"],
                    )
                    return json.loads(response.text)
                except Exception as exc:
                    err_str = str(exc)
                    if "429" in err_str or "quota" in err_str.lower():
                        if attempt < max_retries:
                            wait_time = (2 ** attempt) + 1  # 2, 3, 5 seconds...
                            # If error message contains explicit retry delay, we could parse it, but simple backoff is often enough.
                            # The log showed "Please retry in 30.3s", so we might need a longer wait if we parse it.
                            # For now, let's just use a more aggressive backoff for 429.
                            wait_time = 5 * (attempt + 1) # 5, 10, 15s
                            logger.warning(f"⚠️ [GeminiProvider] Rate Limit (429) on '{target_model}'. Retrying in {wait_time}s... (Attempt {attempt+1}/{max_retries})")
                            time.sleep(wait_time)
                            continue
                    
                    # Not a 429 or retries exhausted
                    last_error = exc
                    logger.warning(f"⚠️ [GeminiProvider] 모델 '{target_model}' 호출 실패: {exc}")
                    break # Try next model candidate

        raise RuntimeError(f"LLM 호출 실패: {last_error}") from last_error

    def generate_chat(
        self,
        history: List[Dict],
        response_schema: Optional[Dict] = None,
        *,
        temperature: float = 0.2,
        model_name: Optional[str] = None,
        fallback_models: Optional[Sequence[str]] = None,
        service: Optional[str] = None,
    ) -> Dict:
        model_candidates = [model_name or self.default_model]
        if fallback_models:
            model_candidates.extend(fallback_models)

        # [Fix] Handle System Prompt for Gemini
        system_instruction = ""
        gemini_history = []
        last_message = None
        
        for h in history:
            role = h.get('role', 'user')
            content = h.get('content') or (h.get('parts', [{}])[0].get('text', ''))
            
            if role == 'system':
                # Gemini doesn't support 'system' role in history directly in some versions.
                # Safe approach: Prepend to first user message or keep as instruction log.
                system_instruction += f"{content}\n\n"
                continue

            if role == 'assistant': 
                role = 'model'
            
            gemini_history.append({
                "role": role,
                "parts": [{"text": content}]
            })
            
        # Separate the last user message as the prompt for send_message
        # Also prepend system instruction to the last message if history is empty, 
        # or find the first user message in history? 
        # API requires turns. Let's prepend to the LAST message if it is user, 
        # or Append a user message with system instruction if needed.
        
        if gemini_history and gemini_history[-1]['role'] == 'user':
            last_entry = gemini_history.pop()
            last_message = last_entry['parts'][0]['text']
            # Prepend system instruction
            if system_instruction:
                last_message = f"System Instruction:\n{system_instruction}\n\nUser Request:\n{last_message}"
        else:
            last_message = "Continue" # Fallback
            if system_instruction:
                 last_message = f"System Instruction:\n{system_instruction}\n\n{last_message}"

        last_error: Optional[Exception] = None
        max_retries = 3

        for target_model in model_candidates:
            # [Defensive] Retry Logic for Rate Limits (429)
            for attempt in range(max_retries + 1):
                try:
                    generation_config = {"temperature": temperature}
                    if response_schema:
                        generation_config["response_mime_type"] = "application/json"
                        # [Fix] Skip schema validation on client side to avoid 400 Errors if empty
                        # generation_config["response_schema"] = response_schema 

                    response = self._client.models.generate_content(
                        model=target_model,
                        contents=gemini_history + [{"role": "user", "parts": [{"text": last_message}]}],
                        config=generation_config,
                    )

                    text = response.text
                    if response_schema:
                        # Try parsing JSON manually if API returns text
                        try:
                            return json.loads(text)
                        except (json.JSONDecodeError, TypeError):
                            # Try finding JSON block
                            start = text.find("{")
                            end = text.rfind("}") + 1
                            if start != -1 and end != -1:
                                return json.loads(text[start:end])
                            return {"text": text, "error": "JSON Parse Failed"}
                            
                    return {"text": text}
                except Exception as exc:
                    err_str = str(exc)
                    if "429" in err_str or "quota" in err_str.lower():
                        if attempt < max_retries:
                            wait_time = 5 * (attempt + 1)
                            logger.warning(f"⚠️ [GeminiProvider] Chat Rate Limit (429) on '{target_model}'. Retrying in {wait_time}s...")
                            time.sleep(wait_time)
                            continue

                    last_error = exc
                    logger.warning(f"⚠️ [GeminiProvider] Chat 모델 '{target_model}' 호출 실패: {exc}")
                    break 

        raise RuntimeError(f"LLM Chat 호출 실패: {last_error}") from last_error


class OpenAILLMProvider(BaseLLMProvider):
    """OpenAI GPT Provider for reasoning-heavy tasks"""
    
    REASONING_MODELS = {"gpt-5-mini", "gpt-5", "gpt-5.2", "o1", "o1-mini", "o1-preview", "o3", "o3-mini"}
    
    def __init__(self, project_id: Optional[str] = None, openai_api_key_secret: Optional[str] = None, safety_settings=None, base_url: Optional[str] = None, api_key: Optional[str] = None, default_model: Optional[str] = None):
        super().__init__(safety_settings)
        try:
            from openai import OpenAI
            self._openai_module = OpenAI
        except ImportError:
            raise RuntimeError("openai 패키지가 설치되지 않았습니다. pip install openai 실행이 필요합니다.")
        
        # 1. API Key 우선순위: 인자 -> Secrets -> Env
        final_api_key = api_key
        
        if not final_api_key:
             # Try env vars first (standard)
             final_api_key = os.getenv("OPENAI_API_KEY")

        if not final_api_key:
             # Fallback to secrets
             from . import auth
             secret_id = openai_api_key_secret or os.getenv("SECRET_ID_OPENAI_API_KEY", "openai-api-key")
             try:
                final_api_key = auth.get_secret(secret_id)
             except Exception:
                pass
        
        if not final_api_key:
             logger.warning("⚠️ OpenAI API Key not found in args, env, or secrets.json") 
        
        # 2. Base URL 설정 (DeepSeek 등 호환 API 지원)
        final_base_url = base_url or os.getenv("OPENAI_API_BASE")

        self.client = self._openai_module(api_key=final_api_key, base_url=final_base_url)
        # [Budget Strategy 2025]
        # Default (Reasoning Tier): gpt-4o-mini (Cost Efficiency)
        # Thinking (Judge Tier): gpt-4o (Balanced Cost/Perf)
        self.default_model = default_model or os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini")
        self.reasoning_model = os.getenv("OPENAI_REASONING_MODEL_NAME", "gpt-4o")

    def _is_reasoning_model(self, model_name: str) -> bool:
        """Reasoning 모델인지 확인 (temperature 미지원)"""
        return any(rm in model_name.lower() for rm in self.REASONING_MODELS)
    
    @property
    def name(self) -> str:
        return "openai"
    
    def generate_json(
        self,
        prompt: str,
        response_schema: Dict,
        *,
        temperature: float = 0.2,
        model_name: Optional[str] = None,
        fallback_models: Optional[Sequence[str]] = None,
        service: Optional[str] = None,
    ) -> Dict:
        model_candidates = [model_name or self.default_model]
        if fallback_models:
            model_candidates.extend(fallback_models)

        last_error: Optional[Exception] = None
        for target_model in model_candidates:
            try:
                messages = [
                    {"role": "system", "content": "You are a helpful assistant. Always respond with valid JSON."},
                    {"role": "user", "content": prompt}
                ]
                kwargs = {
                    "model": target_model,
                    "messages": messages,
                    "response_format": {"type": "json_object"},
                }
                if not self._is_reasoning_model(target_model):
                    kwargs["temperature"] = temperature

                response = self.client.chat.completions.create(**kwargs)

                # 토큰 사용량 기록
                if hasattr(response, 'usage') and response.usage:
                    self._record_llm_usage(
                        service or "unknown",
                        response.usage.prompt_tokens,
                        response.usage.completion_tokens,
                        target_model
                    )

                return json.loads(response.choices[0].message.content)
            except Exception as exc:
                last_error = exc
                logger.warning(f"⚠️ [OpenAIProvider] 모델 '{target_model}' 호출 실패: {exc}")

        raise RuntimeError(f"OpenAI LLM 호출 실패: {last_error}") from last_error
    
    def generate_chat(
        self,
        history: List[Dict],
        response_schema: Optional[Dict] = None,
        *,
        temperature: float = 0.2,
        model_name: Optional[str] = None,
        fallback_models: Optional[Sequence[str]] = None,
        service: Optional[str] = None,
    ) -> Dict:
        model_candidates = [model_name or self.default_model]
        if fallback_models:
            model_candidates.extend(fallback_models)

        messages = []
        if response_schema:
            messages.append({"role": "system", "content": "You are a helpful assistant. Always respond with valid JSON."})

        for entry in history:
            role = entry.get('role', 'user')
            if role == 'model':
                role = 'assistant'
            content = entry['parts'][0]['text'] if 'parts' in entry else entry.get('content', '')
            messages.append({"role": role, "content": content})

        last_error: Optional[Exception] = None
        for target_model in model_candidates:
            try:
                kwargs = {"model": target_model, "messages": messages}
                if not self._is_reasoning_model(target_model):
                    kwargs["temperature"] = temperature
                if response_schema:
                    kwargs["response_format"] = {"type": "json_object"}

                response = self.client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content

                # 토큰 사용량 기록
                if hasattr(response, 'usage') and response.usage:
                    self._record_llm_usage(
                        service or "unknown",
                        response.usage.prompt_tokens,
                        response.usage.completion_tokens,
                        target_model
                    )

                if response_schema:
                    return json.loads(content)
                return {"text": content}
            except Exception as exc:
                last_error = exc
                logger.warning(f"⚠️ [OpenAIProvider] Chat 모델 '{target_model}' 호출 실패: {exc}")

        raise RuntimeError(f"OpenAI Chat 호출 실패: {last_error}") from last_error


class CloudFailoverProvider(BaseLLMProvider):
    """
    Multi-provider failover for DeepSeek V3.2.
    Chain: OpenRouter → DeepSeek Official API → Ollama Cloud
    API 키가 없는 프로바이더는 자동 건너뜀.
    """

    def __init__(self, tier_name: str = "REASONING"):
        super().__init__()
        self.tier_name = tier_name
        self._providers = []
        self._provider_names = []

        from . import auth

        # 1. DeepSeek Official API (가장 저렴 + 가장 빠름)
        ds_key = auth.get_secret("deepseek-api-key")
        if ds_key:
            self._providers.append(
                OpenAILLMProvider(
                    base_url="https://api.deepseek.com",
                    api_key=ds_key,
                    default_model="deepseek-chat",
                )
            )
            self._provider_names.append("DeepSeek")
            logger.info(f"☁️ [CloudFailover:{tier_name}] DeepSeek API 등록")

        # 2. OpenRouter (failover)
        or_key = auth.get_secret("openrouter-api-key")
        if or_key:
            self._providers.append(
                OpenAILLMProvider(
                    base_url="https://openrouter.ai/api/v1",
                    api_key=or_key,
                    default_model="deepseek/deepseek-v3.2",
                )
            )
            self._provider_names.append("OpenRouter")
            logger.info(f"☁️ [CloudFailover:{tier_name}] OpenRouter 등록")

        # 3. Ollama Cloud (최종 fallback)
        from shared.llm_factory import ModelStateManager
        ollama_cloud = OllamaLLMProvider(
            model="deepseek-v3.2:cloud",
            state_manager=ModelStateManager(),
            is_thinking_tier=(tier_name == "THINKING"),
        )
        if ollama_cloud._cloud_api_key:
            self._providers.append(ollama_cloud)
            self._provider_names.append("OllamaCloud")
            logger.info(f"☁️ [CloudFailover:{tier_name}] Ollama Cloud 등록")

        if not self._providers:
            raise RuntimeError(
                f"[CloudFailover:{tier_name}] 사용 가능한 프로바이더가 없습니다. "
                "openrouter-api-key, deepseek-api-key, 또는 ollama-api-key를 설정하세요."
            )

        logger.info(
            f"☁️ [CloudFailover:{tier_name}] 체인: {' → '.join(self._provider_names)}"
        )

    @property
    def name(self) -> str:
        return "cloud_failover"

    def generate_json(
        self,
        prompt: str,
        response_schema: Dict,
        *,
        temperature: float = 0.2,
        model_name: Optional[str] = None,
        fallback_models: Optional[Sequence[str]] = None,
        service: Optional[str] = None,
    ) -> Dict:
        return self._failover_call(
            "generate_json",
            prompt=prompt,
            response_schema=response_schema,
            temperature=temperature,
            service=service,
        )

    def generate_chat(
        self,
        history: List[Dict],
        response_schema: Optional[Dict] = None,
        *,
        temperature: float = 0.2,
        model_name: Optional[str] = None,
        fallback_models: Optional[Sequence[str]] = None,
        service: Optional[str] = None,
    ) -> Dict:
        return self._failover_call(
            "generate_chat",
            history=history,
            response_schema=response_schema,
            temperature=temperature,
            service=service,
        )

    def _failover_call(self, method: str, **kwargs) -> Dict:
        """순차적으로 프로바이더를 시도하며 첫 성공 결과를 반환"""
        last_error = None
        for i, (provider, pname) in enumerate(
            zip(self._providers, self._provider_names)
        ):
            try:
                logger.info(
                    f"☁️ [CloudFailover:{self.tier_name}] {pname} 시도 ({i+1}/{len(self._providers)})"
                )
                result = getattr(provider, method)(**kwargs)
                if i > 0:
                    logger.info(
                        f"✅ [CloudFailover:{self.tier_name}] {pname}에서 성공 (failover)"
                    )
                return result
            except Exception as e:
                last_error = e
                logger.warning(
                    f"⚠️ [CloudFailover:{self.tier_name}] {pname} 실패: {e}"
                )
                if i < len(self._providers) - 1:
                    logger.info(
                        f"🔄 [CloudFailover:{self.tier_name}] 다음 프로바이더로 전환: {self._provider_names[i+1]}"
                    )

        raise RuntimeError(
            f"[CloudFailover:{self.tier_name}] 모든 프로바이더 실패: {last_error}"
        ) from last_error


class ClaudeLLMProvider(BaseLLMProvider):
    """Anthropic Claude Provider - 빠르고 똑똑함"""
    
    def __init__(self, project_id: Optional[str] = None, claude_api_key_secret: Optional[str] = None, safety_settings=None):
        super().__init__(safety_settings)
        try:
            import anthropic
            self._anthropic_module = anthropic
        except ImportError:
            raise RuntimeError("anthropic 패키지가 설치되지 않았습니다. pip install anthropic 실행이 필요합니다.")
        
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key and project_id and claude_api_key_secret:
            from . import auth
            api_key = auth.get_secret(claude_api_key_secret, project_id)
        # secrets.json 자동 조회 폴백 (인자 없이 호출된 경우)
        if not api_key:
            from . import auth
            api_key = auth.get_secret("claude-api-key")

        self.client = self._anthropic_module.Anthropic(api_key=api_key)
        self.fast_model = os.getenv("CLAUDE_FAST_MODEL", "claude-haiku-4-5")
        self.reasoning_model = os.getenv("CLAUDE_REASONING_MODEL", "claude-sonnet-4-5")
    
    @property
    def name(self) -> str:
        return "claude"
    
    def generate_json(
        self,
        prompt: str,
        response_schema: Dict,
        *,
        temperature: float = 0.2,
        model_name: Optional[str] = None,
        fallback_models: Optional[Sequence[str]] = None,
        service: Optional[str] = None,
    ) -> Dict:
        model_candidates = [model_name or self.fast_model]
        if fallback_models:
            model_candidates.extend(fallback_models)

        last_error: Optional[Exception] = None
        for target_model in model_candidates:
            try:
                response = self.client.messages.create(
                    model=target_model,
                    max_tokens=8192,  # 4096→8192
                    temperature=temperature,
                    system="You are a helpful assistant. Always respond with valid JSON only, no markdown formatting.",
                    messages=[{"role": "user", "content": prompt}]
                )

                # 토큰 사용량 기록
                if service and hasattr(response, 'usage') and response.usage:
                    self._record_llm_usage(
                        service,
                        response.usage.input_tokens,
                        response.usage.output_tokens,
                        target_model
                    )

                content = response.content[0].text
                raw_content = content
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0]
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0]
                return json.loads(content.strip())
            except json.JSONDecodeError as je:
                logger.error(f"❌ [ClaudeProvider] JSON 파싱 실패: {je}")
                logger.error(f"   (Raw Content): {raw_content[:500]}...")
                last_error = je
            except Exception as exc:
                last_error = exc
                logger.warning(f"⚠️ [ClaudeProvider] 모델 '{target_model}' 호출 실패: {exc}")

        raise RuntimeError(f"Claude LLM 호출 실패: {last_error}") from last_error
    
    def generate_chat(
        self,
        history: List[Dict],
        response_schema: Optional[Dict] = None,
        *,
        temperature: float = 0.2,
        model_name: Optional[str] = None,
        fallback_models: Optional[Sequence[str]] = None,
        service: Optional[str] = None,
    ) -> Dict:
        model_candidates = [model_name or self.fast_model]
        if fallback_models:
            model_candidates.extend(fallback_models)

        messages = []
        system_msg = "You are a helpful assistant."

        # [Fix] Extract System Prompt from history
        for entry in history:
            role = entry.get('role', 'user')
            content = entry['parts'][0]['text'] if 'parts' in entry else entry.get('content', '')

            if role == 'system':
                system_msg = content
                continue

            if role == 'model':
                role = 'assistant'

            messages.append({"role": role, "content": content})

        last_error: Optional[Exception] = None
        for target_model in model_candidates:
            try:
                if response_schema:
                    system_msg += " Always respond with valid JSON only, no markdown formatting."

                response = self.client.messages.create(
                    model=target_model,
                    max_tokens=4096,
                    temperature=temperature,
                    system=system_msg,
                    messages=messages
                )

                # 토큰 사용량 기록
                if service and hasattr(response, 'usage') and response.usage:
                    self._record_llm_usage(
                        service,
                        response.usage.input_tokens,
                        response.usage.output_tokens,
                        target_model
                    )

                content = response.content[0].text

                if response_schema:
                    if "```json" in content:
                        content = content.split("```json")[1].split("```")[0]
                    elif "```" in content:
                        content = content.split("```")[1].split("```")[0]
                    return json.loads(content.strip())
                return {"text": content}
            except Exception as exc:
                last_error = exc
                logger.warning(f"⚠️ [ClaudeProvider] Chat 모델 '{target_model}' 호출 실패: {exc}")

        raise RuntimeError(f"Claude Chat 호출 실패: {last_error}") from last_error

    def generate_json_with_thinking(
        self,
        prompt: str,
        response_schema: Dict,
        *,
        model_name: str = "claude-opus-4-6",
        budget_tokens: int = 8000,
        max_tokens: int = 16000,
        service: Optional[str] = None,
    ) -> Dict:
        """
        Extended Thinking을 사용한 JSON 생성.
        Claude Opus 4.6의 깊은 사고 모드를 활용하여 복잡한 분석을 수행합니다.

        주의사항:
        - thinking 모드에서는 temperature 설정 불가 (API에서 1.0 고정)
        - system 파라미터 사용 가능하나, thinking과 함께 사용 시 제한 있을 수 있음

        Args:
            prompt: 분석 요청 프롬프트 (시스템 지시 포함)
            response_schema: 참고용 JSON 스키마 (API 강제 아님)
            model_name: 사용할 모델 (기본: claude-opus-4-6)
            budget_tokens: thinking에 할당할 최대 토큰 수
            max_tokens: 전체 응답 최대 토큰 수 (thinking + text 합계)

        Returns:
            파싱된 JSON dict
        """
        try:
            response = self.client.messages.create(
                model=model_name,
                max_tokens=max_tokens,
                thinking={
                    "type": "enabled",
                    "budget_tokens": budget_tokens,
                },
                messages=[{"role": "user", "content": prompt}],
            )

            # Extended Thinking 응답: [ThinkingBlock, TextBlock]
            text_content = ""
            for block in response.content:
                if block.type == "text":
                    text_content = block.text
                    break

            if not text_content:
                raise ValueError("Extended Thinking 응답에서 TextBlock을 찾을 수 없습니다.")

            # JSON 추출
            content = text_content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            elif content[0] != "{":
                start = content.find("{")
                end = content.rfind("}") + 1
                if start != -1 and end > start:
                    content = content[start:end]

            parsed = json.loads(content.strip())

            # 토큰 사용량 로깅 + Redis 기록
            if hasattr(response, "usage"):
                logger.info(
                    f"🧠 [Claude Thinking] model={model_name}, "
                    f"input={response.usage.input_tokens}, "
                    f"output={response.usage.output_tokens}"
                )
                if service:
                    self._record_llm_usage(
                        service,
                        response.usage.input_tokens,
                        response.usage.output_tokens,
                        model_name
                    )

            return parsed

        except json.JSONDecodeError as je:
            logger.error(f"❌ [Claude Thinking] JSON 파싱 실패: {je}")
            logger.error(f"   Raw text: {text_content[:500]}...")
            raise
        except Exception as exc:
            logger.error(f"❌ [Claude Thinking] 호출 실패: {exc}")
            raise


