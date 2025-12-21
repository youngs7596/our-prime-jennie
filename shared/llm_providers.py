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

    @abstractmethod
    def generate_json(
        self,
        prompt: str,
        response_schema: Dict,
        *,
        temperature: float = 0.2,
        model_name: Optional[str] = None,
        fallback_models: Optional[Sequence[str]] = None,
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
    ) -> Dict:
        ...


class OllamaLLMProvider(BaseLLMProvider):
    """
    Ollama Local LLM Provider.
    Implements defensive coding: Retries, Tag Removal, Timeouts, Keep-Alive.
    
    Gateway 모드 지원:
    - USE_OLLAMA_GATEWAY=true 설정 시 중앙 Gateway를 통해 요청 (순차 처리 보장)
    - Gateway가 Rate Limiting, Circuit Breaker, 큐잉 처리
    
    Debug 로깅:
    - LLM_DEBUG_LOG_PATH 환경변수 설정 시 요청/응답을 JSON 파일로 저장
    """
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
        
        # Gateway 모드 설정
        self.use_gateway = os.getenv("USE_OLLAMA_GATEWAY", "false").lower() == "true"
        self.gateway_url = os.getenv("OLLAMA_GATEWAY_URL", "http://ollama-gateway:11500")
        
        if self.use_gateway:
            logger.info(f"🌐 [Ollama] Gateway 모드 활성화: {self.gateway_url}")
        
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
            
        self.max_retries = 3

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

    def _call_via_gateway(self, payload: Dict, endpoint: str = None) -> Dict:
        """
        Gateway를 통해 Ollama API 호출
        Gateway가 Rate Limiting, Circuit Breaker, 큐잉을 처리
        
        타임아웃 증가: Gateway 큐 대기 시간 + 실제 처리 시간 고려
        /api/chat 지원 추가
        """
        # Endpoint 결정 (기본값 하위 호환)
        if endpoint is None:
             endpoint = "/api/generate"
        
        url = f"{self.gateway_url}{endpoint}"
        
        # Gateway 전용 페이로드 구성
        gateway_payload = {
            "model": payload.get("model", self.model),
            "options": payload.get("options", {"temperature": 0.2, "num_ctx": 8192}),
            "timeout": self.timeout,
        }
        
        # Payload 필드 매핑
        if "prompt" in payload:
            gateway_payload["prompt"] = payload["prompt"]
        if "messages" in payload:  # Chat support
            gateway_payload["messages"] = payload["messages"]
        if "format" in payload:
            gateway_payload["format"] = payload["format"]
            
        # Gateway 모드에서는 큐 대기 시간을 고려하여 더 긴 타임아웃 사용
        # 최대 5개 요청 대기 (30초 x 5) + 자신의 처리 시간 (300초) = 450초, 여유 포함 600초
        gateway_timeout = int(os.getenv("OLLAMA_GATEWAY_TIMEOUT", "600"))
        
        try:
            logger.info(f"🌐 [Ollama] Gateway 요청: {self.gateway_url}{endpoint} (timeout={gateway_timeout}s)")
            response = requests.post(url, json=gateway_payload, timeout=gateway_timeout)
            response.raise_for_status()
            
            result = response.json()
            
            # Gateway가 이미 파싱한 JSON 반환 (/api/generate-json 등 사용 시)
            if "parsed_json" in result:
                return {"response": json.dumps(result["parsed_json"])}
            
            return result
            
        except requests.exceptions.Timeout:
            logger.error(f"❌ [Ollama] Gateway 타임아웃 ({gateway_timeout}s)")
            raise TimeoutError(f"Ollama Gateway timed out after {gateway_timeout}s")
        except Exception as e:
            logger.error(f"❌ [Ollama] Gateway 요청 실패: {e}")
            raise

    def _call_ollama_api(self, endpoint: str, payload: Dict) -> Dict:
        """
        [Defensive] Robust API Caller with Retries
        Gateway 모드 시 Gateway를 통해 요청
        """
        # Gateway 모드 체크
        if self.use_gateway:
            return self._call_via_gateway(payload, endpoint=endpoint)
        
        # 직접 호출 모드 (기존 로직)
        url = f"{self.host}{endpoint}"
        payload["stream"] = False
        payload["keep_alive"] = -1 # [Ops] Prevent unloading
        
        last_error = None
        
        for attempt in range(self.max_retries):
            try:
                self._ensure_model_loaded()
                response = requests.post(url, json=payload, timeout=self.timeout)
                response.raise_for_status()
                return response.json()
            except requests.exceptions.Timeout:
                logger.warning(f"⚠️ [Ollama] Timeout ({self.timeout}s) on attempt {attempt+1}/{self.max_retries}")
                last_error = TimeoutError(f"Ollama timed out after {self.timeout}s")
            except Exception as e:
                logger.warning(f"⚠️ [Ollama] Error on attempt {attempt+1}/{self.max_retries}: {e}")
                last_error = e
            
            # Exponential Backoff
            time.sleep(2 ** attempt)
            
        raise last_error

    def generate_json(
        self,
        prompt: str,
        response_schema: Dict,
        *,
        temperature: float = 0.2,
        model_name: Optional[str] = None,
        fallback_models: Optional[Sequence[str]] = None,
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
                logger.warning("   ⚠️ [Ollama] Empty response content received!")
            
            # Debug 로깅
            self._log_llm_interaction(
                interaction_type="generate_json",
                request_data={"prompt": prompt, "temperature": temperature},
                response_data={"content": content, "parsed": None},  # parsed는 나중에 업데이트
                model_name=target_model
            )
            
            # [Defensive] Tag Removal
            raw_content = content
            content = self._clean_deepseek_tags(content)
            
            if not content.strip() and raw_content.strip():
                # [Defensive] Model generated only thinking traces
                error_msg = f"Model generated {len(raw_content)} chars of reasoning but no final JSON output."
                logger.warning(f"⚠️ [Ollama] {error_msg}")
                raise ValueError(error_msg)
            
            # [Defensive] JSON Parsing with basic cleanup
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
                     raise ValueError(f"No JSON content found in output (len={len(raw_content)})")
                     
                parsed = json.loads(content)
            
            # [Defensive] Case-insensitive Key Normalization
            # Qwen3 sometimes returns 'Score' instead of 'score'
            if response_schema:
                 normalized = {}
                 required_keys = response_schema.get("required", [])
                 # Create a mapping of lowercase key -> original key in parsed result
                 parsed_keys_lower = {k.lower(): k for k in parsed.keys()}
                 
                 for req_key in required_keys:
                     req_key_lower = req_key.lower()
                     if req_key in parsed:
                         normalized[req_key] = parsed[req_key]
                     elif req_key_lower in parsed_keys_lower:
                         # Found it with different case
                         original_key = parsed_keys_lower[req_key_lower]
                         normalized[req_key] = parsed[original_key]
                         logger.warning(f"⚠️ [Ollama] Normalized key case: {original_key} -> {req_key}")
                     else:
                         # Key missing, keep what we have (or let it fail later)
                         pass
                 
                 # Copy over other keys that weren't required (optional)
                 for k, v in parsed.items():
                     if k not in normalized and k.lower() not in parsed_keys_lower:
                         normalized[k] = v
                         
                 # If we normalized anything, use it. 
                 # But checks if we actually found required keys. 
                 # If 'normalized' has the required keys, return it.
                 # Otherwise return 'parsed' and let the caller handle missing keys 
                 # (or maybe 'parsed' is just better).
                 # Let's simple return 'normalized' merging with 'parsed' for safety.
                 parsed.update(normalized) # Ensure required keys are present with correct casing
            
            return parsed
                
        except Exception as e:
            logger.error(f"❌ [Ollama] generate_json failed: {e}")
            raise

    def generate_chat(
        self,
        history: List[Dict],
        response_schema: Optional[Dict] = None,
        *,
        temperature: float = 0.2,
        model_name: Optional[str] = None,
        fallback_models: Optional[Sequence[str]] = None,
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

        try:
            # [Debug] Log Chat Request
            if self.debug_enabled:
                logger.info(f"📝 [Ollama] Chat Messages Check: {len(messages)} messages.")
            
            result = self._call_ollama_api("/api/chat", payload)
            content = result.get("message", {}).get("content", "")
            
            # [Debug] Log JSON Response
            if self.debug_enabled:
                logger.info(f"📝 [Ollama] Chat Response: {content[:500]}... [Truncated]")
            
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
                     if "{" in content:
                        start = content.find("{")
                        end = content.rfind("}") + 1
                        content = content[start:end]
                     return json.loads(content)
            
            return {"text": content}

        except Exception as e:
             logger.error(f"❌ [Ollama] generate_chat failed: {e}")
             raise


class GeminiLLMProvider(BaseLLMProvider):
    def __init__(self, project_id: str, gemini_api_key_secret: str, safety_settings):
        super().__init__(safety_settings)
        import google.generativeai as genai
        from . import auth
        
        api_key = auth.get_secret(gemini_api_key_secret, project_id)
        if not api_key:
            raise RuntimeError(f"GCP Secret '{gemini_api_key_secret}' 로드 실패")

        genai.configure(api_key=api_key)
        self._genai = genai
        # Updated to Gemini 3 Pro for Self-Evolution tasks (Daily Feedback)
        # Note: As of Dec 2025, stable is 'gemini-3-pro-preview' in API
        self.default_model = os.getenv("LLM_MODEL_NAME", "gemini-3-pro-preview")
        self.flash_model = os.getenv("LLM_FLASH_MODEL_NAME", "gemini-2.5-flash")
        self._model_cache: Dict[tuple[str, float, str], Any] = {}

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
            self._model_cache[cache_key] = self._genai.GenerativeModel(
                model_name=model_name,
                generation_config=generation_config,
                safety_settings=self.safety_settings,
            )
        return self._model_cache[cache_key]

    def generate_json(
        self,
        prompt: str,
        response_schema: Dict,
        *,
        temperature: float = 0.2,
        model_name: Optional[str] = None,
        fallback_models: Optional[Sequence[str]] = None,
    ) -> Dict:
        model_candidates = [model_name or self.default_model]
        if fallback_models:
            model_candidates.extend(fallback_models)

        last_error: Optional[Exception] = None
        for target_model in model_candidates:
            try:
                model = self._get_or_create_model(target_model, response_schema, temperature)
                response = model.generate_content(prompt, safety_settings=self.safety_settings)
                return json.loads(response.text)
            except Exception as exc:
                last_error = exc
                logger.warning(f"⚠️ [GeminiProvider] 모델 '{target_model}' 호출 실패: {exc}")

        raise RuntimeError(f"LLM 호출 실패: {last_error}") from last_error

    def generate_chat(
        self,
        history: List[Dict],
        response_schema: Optional[Dict] = None,
        *,
        temperature: float = 0.2,
        model_name: Optional[str] = None,
        fallback_models: Optional[Sequence[str]] = None,
    ) -> Dict:
        model_candidates = [model_name or self.default_model]
        if fallback_models:
            model_candidates.extend(fallback_models)

        # [Fix] Convert OpenAI-style history to Gemini format
        # OpenAI: [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
        # Gemini: [{"role": "user", "parts": [{"text": "..."}]}, {"role": "model", "parts": [{"text": "..."}]}]
        gemini_history = []
        last_message = None
        
        for h in history:
            role = h.get('role', 'user')
            content = h.get('content') or (h.get('parts', [{}])[0].get('text', ''))
            
            if role == 'assistant': 
                role = 'model'
            
            # Gemini requires strict alternating turns. 
            # We assume history is well-formed but ensure conversion.
            gemini_history.append({
                "role": role,
                "parts": [{"text": content}]
            })
            
        # Separate the last user message as the prompt for send_message
        if gemini_history and gemini_history[-1]['role'] == 'user':
            last_message = gemini_history.pop()['parts'][0]['text']
        else:
            # Fallback if history is empty or ends with model (shouldn't happen in standard chat)
            last_message = "Continue"

        last_error: Optional[Exception] = None
        for target_model in model_candidates:
            try:
                generation_config = {"temperature": temperature}
                if response_schema:
                    generation_config["response_mime_type"] = "application/json"
                    generation_config["response_schema"] = response_schema

                model = self._genai.GenerativeModel(
                    model_name=target_model,
                    generation_config=generation_config,
                    safety_settings=self.safety_settings,
                )
                chat = model.start_chat(history=gemini_history)
                response = chat.send_message(last_message)
                
                if response_schema:
                    return json.loads(response.text)
                return {"text": response.text}
            except Exception as exc:
                last_error = exc
                logger.warning(f"⚠️ [GeminiProvider] Chat 모델 '{target_model}' 호출 실패: {exc}")

        raise RuntimeError(f"LLM Chat 호출 실패: {last_error}") from last_error


class OpenAILLMProvider(BaseLLMProvider):
    """OpenAI GPT Provider for reasoning-heavy tasks"""
    
    REASONING_MODELS = {"gpt-5-mini", "gpt-5", "o1", "o1-mini", "o1-preview", "o3", "o3-mini"}
    
    def __init__(self, project_id: Optional[str] = None, openai_api_key_secret: Optional[str] = None, safety_settings=None):
        super().__init__(safety_settings)
        try:
            from openai import OpenAI
            self._openai_module = OpenAI
        except ImportError:
            raise RuntimeError("openai 패키지가 설치되지 않았습니다. pip install openai 실행이 필요합니다.")
        
        # If secrets are provided, fetch them. Ideally passed from factory or env.
        # Fallback to direct env var for simplicity in Factory pattern if secret manager is tricky without project_id
        api_key = os.getenv("OPENAI_API_KEY")

        # [Fix] Fallback to secrets.json using environment variable key ID
        if not api_key:
             from . import auth
             # Try to get key ID from env, default to 'openai-api-key'
             secret_id = os.getenv("SECRET_ID_OPENAI_API_KEY", "openai-api-key")
             api_key = auth.get_secret(secret_id)
        
        if not api_key:
             # Just log warning, might rely on env var that OpenAI client picks up automatically
             logger.warning("⚠️ OpenAI API Key not found in env or secrets.json") 
        
        self.client = self._openai_module(api_key=api_key)
        # GPT-5.2 for THINKING tier (Daily Self-Evolution & Weekly Council)
        self.default_model = os.getenv("OPENAI_MODEL_NAME", "gpt-5.2")
        self.reasoning_model = os.getenv("OPENAI_REASONING_MODEL_NAME", "gpt-5.2")
    
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
                        "news_analysis",
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
                        "news_analysis",
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
    ) -> Dict:
        model_candidates = [model_name or self.fast_model]
        if fallback_models:
            model_candidates.extend(fallback_models)
        
        messages = []
        for entry in history:
            role = entry.get('role', 'user')
            if role == 'model':
                role = 'assistant'
            content = entry['parts'][0]['text'] if 'parts' in entry else entry.get('content', '')
            messages.append({"role": role, "content": content})
        
        last_error: Optional[Exception] = None
        for target_model in model_candidates:
            try:
                system_msg = "You are a helpful assistant."
                if response_schema:
                    system_msg += " Always respond with valid JSON only, no markdown formatting."
                
                response = self.client.messages.create(
                    model=target_model,
                    max_tokens=4096,  # 2048→4096
                    temperature=temperature,
                    system=system_msg,
                    messages=messages
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



