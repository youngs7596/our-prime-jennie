"""
services/ollama-gateway/main.py - Ollama Local LLM Gateway
============================================================

이 서비스는 Local LLM (Ollama/Qwen3) 요청을 중앙화하여 순차 처리합니다.

주요 기능:
---------
1. 요청 큐잉: 여러 서비스의 동시 요청을 순차 처리
2. Rate Limiting: Ollama 과부하 방지
3. Circuit Breaker: 장애 전파 차단
4. 통계/모니터링: 요청 현황 중앙 관리

API Endpoints:
-------------
- POST /api/generate      - 텍스트 생성 요청
- POST /api/generate-json - JSON 생성 요청 (스키마 검증 포함)
- GET  /health            - 헬스 체크
- GET  /stats             - 요청 통계

참조:
----
- KIS Gateway 패턴 적용 (services/kis-gateway/main.py)
"""

import json
import logging
import os
import time
import threading
from collections import deque
from datetime import datetime, timezone
from functools import wraps
from typing import Dict, Any, Optional

from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from pybreaker import CircuitBreaker, CircuitBreakerError, CircuitBreakerListener
import requests

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s] - %(message)s'
)
logger = logging.getLogger("ollama-gateway")

app = Flask(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 환경 변수 설정
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Secret Loading (DeepSeek/Cloud Proxy)
SECRETS_FILE = os.getenv("SECRETS_FILE", "/app/config/secrets.json")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY")

if not OLLAMA_API_KEY and os.path.exists(SECRETS_FILE):
    try:
        with open(SECRETS_FILE, "r") as f:
            secrets = json.load(f)
            # Support both naming conventions
            OLLAMA_API_KEY = secrets.get("ollama_api_key") or secrets.get("ollama-api-key")
    except Exception as e:
        logger.warning(f"⚠️ Failed to load secrets from {SECRETS_FILE}: {e}")

if OLLAMA_API_KEY:
    logger.info("🔐 OLLAMA_API_KEY loaded (Cloud Proxy Enabled)")
else:
    logger.info("ℹ️ OLLAMA_API_KEY not found (Local Mode Only)")

# Rate Limit 설정 (엔드포인트별 + 모델별 차등)
# generate/chat (heavy): LLM 추론 (GPU 부하 높음, 10-30초/요청)
# generate/chat (fast):  경량 모델 (exaone 등, 1-5초/요청)
# embed:                 임베딩 생성 (GPU 부하 낮음, 0.15-0.25초/요청)
RATE_LIMIT = os.getenv("OLLAMA_RATE_LIMIT", "60 per minute")
RATE_LIMIT_FAST = os.getenv("OLLAMA_RATE_LIMIT_FAST", "120 per minute")
RATE_LIMIT_EMBED = os.getenv("OLLAMA_RATE_LIMIT_EMBED", "3000 per minute")

# 경량 모델 패턴 (FAST rate limit 적용 대상)
FAST_MODEL_PREFIXES = os.getenv("OLLAMA_FAST_MODELS", "exaone").split(",")

logger.info(f"🚀 Ollama Gateway 시작")
logger.info(f"   OLLAMA_HOST: {OLLAMA_HOST}")
logger.info(f"   REDIS_URL: {REDIS_URL}")
logger.info(f"   RATE_LIMIT: {RATE_LIMIT}")
logger.info(f"   RATE_LIMIT_FAST: {RATE_LIMIT_FAST} (models: {FAST_MODEL_PREFIXES})")
logger.info(f"   RATE_LIMIT_EMBED: {RATE_LIMIT_EMBED}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Rate Limiter 설정
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_global_key():
    """
    모든 클라이언트의 요청을 하나의 버킷으로 통합하기 위한 Key 함수.
    Ollama는 단일 GPU에서 실행되므로 IP 기반이 아닌 전역 키를 사용해야 함.
    """
    return "ollama_global"


def _is_fast_model(model_name: str) -> bool:
    """경량 모델 여부 판별"""
    if not model_name:
        return False
    model_lower = model_name.lower()
    return any(prefix.strip().lower() in model_lower for prefix in FAST_MODEL_PREFIXES)


def get_model_aware_key():
    """
    모델 기반 rate limit 키.
    경량 모델(exaone 등)은 별도 버킷으로 분리하여 heavy 모델과 독립적으로 rate limit 적용.
    """
    try:
        data = request.get_json(silent=True) or {}
        model = data.get("model", "")
        if _is_fast_model(model):
            return "ollama_fast"
    except Exception:
        pass
    return "ollama_global"


def get_dynamic_generate_limit():
    """generate/chat 요청의 모델별 동적 rate limit 반환"""
    try:
        data = request.get_json(silent=True) or {}
        model = data.get("model", "")
        if _is_fast_model(model):
            return RATE_LIMIT_FAST
    except Exception:
        pass
    return RATE_LIMIT


limiter = Limiter(
    app=app,
    key_func=get_global_key,  # ⭐️ 중요: IP 기반이 아닌 전역 키 사용
    storage_uri=REDIS_URL,
    default_limits=[],  # 엔드포인트별로 개별 설정
    strategy="fixed-window"
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Circuit Breaker 설정
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class GatewayCircuitBreakerListener(CircuitBreakerListener):
    """Circuit Breaker 상태 변경 감지 리스너"""
    
    def state_change(self, breaker, old, new):
        logger.warning(f"🔌 [Circuit Breaker] 상태 변경: {old.name} → {new.name}")
        if new.name == "open":
            stats['circuit_breaker_open_count'] += 1


ollama_circuit_breaker = CircuitBreaker(
    fail_max=int(os.getenv('OLLAMA_CIRCUIT_FAIL_MAX', '5')),  # 5회 연속 실패 시 OPEN
    reset_timeout=int(os.getenv('OLLAMA_CIRCUIT_RESET_TIMEOUT', '120')),  # 2분 후 HALF-OPEN
    listeners=[GatewayCircuitBreakerListener()]
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 통계
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

stats = {
    'total_requests': 0,
    'successful_requests': 0,
    'failed_requests': 0,
    'rate_limited_requests': 0,
    'circuit_breaker_open_count': 0,
    'avg_response_time_ms': 0,
    'request_history': deque(maxlen=100),  # 최근 100개 요청 기록
    'queue_depth': 0,  # 현재 대기 중인 요청 수
}

# 요청 큐 세마포어 (동시 처리 제어)
max_concurrent = int(os.getenv("OLLAMA_MAX_CONCURRENT_REQUESTS", "3"))
request_lock = threading.BoundedSemaphore(value=max_concurrent)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Ollama API 호출 래퍼
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def call_ollama_with_breaker(endpoint: str, payload: Dict[str, Any], timeout: int = 600) -> Dict[str, Any]:
    """
    Circuit Breaker를 적용한 Ollama API 호출 래퍼
    [Cloud Proxy] Intercepts requests for known cloud models and routes to external API.
    """
    model_name = payload.get("model", "")
    
    # 🌩️ Cloud Proxy Logic (Ollama Cloud)
    # Triggered for models ending in ':cloud'
    if model_name.endswith(":cloud"):
         if OLLAMA_API_KEY:
             try:
                return _call_ollama_cloud(endpoint, payload, timeout)
             except Exception as e:
                logger.warning(f"⚠️ [Cloud Proxy] Failed (Quota/Error): {e}. Fallback to Local 'gpt-oss:20b'...")
                # Fallback to local model
                payload["model"] = "gpt-oss:20b"
         else:
             # No API key, fallback immediately
             logger.warning(f"⚠️ [Cloud Proxy] No API Key for {model_name}. Fallback to Local 'gpt-oss:20b'")
             payload["model"] = "gpt-oss:20b"

    url = f"{OLLAMA_HOST}{endpoint}"
    
    # 스트리밍 비활성화, 모델 유지
    payload["stream"] = False
    payload["keep_alive"] = -1
    
    @ollama_circuit_breaker
    def _call():
        response = requests.post(url, json=payload, timeout=timeout)
        response.raise_for_status()
        return response.json()
    
    return _call()

def _call_ollama_cloud(endpoint: str, payload: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    """Ollama Cloud API Proxy (Transparent Proxy)"""
    # https://ollama.com API endpoint
    # The client library uses https://ollama.com as host, modifying the path.
    # Typically /api/chat -> https://ollama.com/api/chat
    cloud_host = "https://ollama.com"

    headers = {
        "Authorization": f"Bearer {OLLAMA_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # Ollama Cloud에서 :cloud는 실제 모델 태그 → 유지
    upstream_model = payload["model"]
    if not upstream_model.endswith(":cloud"):
        upstream_model = f"{upstream_model}:cloud"
    payload["model"] = upstream_model

    # Ensure stream is false for our gateway
    payload["stream"] = False

    # Ollama Cloud는 /api/chat만 지원 → /api/generate를 /api/chat으로 변환
    cloud_endpoint = endpoint
    if endpoint == "/api/generate":
        cloud_endpoint = "/api/chat"
        prompt = payload.pop("prompt", "")
        payload["messages"] = [{"role": "user", "content": prompt}]

    url = f"{cloud_host}{cloud_endpoint}"
    logger.info(f"🌩️ [Cloud Proxy] Routing to Ollama Cloud: {upstream_model} ({cloud_endpoint})")

    response = requests.post(url, json=payload, headers=headers, timeout=timeout)
    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        logger.error(f"Cloud API Error: {response.text}")
        raise e

    result = response.json()

    # /api/generate 호환: chat 응답을 generate 형식으로 변환
    if endpoint == "/api/generate" and "message" in result:
        result["response"] = result.get("message", {}).get("content", "")

    return result


def check_ollama_health() -> bool:
    """Ollama 서버 헬스 체크"""
    try:
        response = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
        return response.status_code == 200
    except Exception:
        return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Health Check
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.route("/health", methods=["GET"])
def health():
    """헬스 체크"""
    ollama_healthy = check_ollama_health()
    circuit_state = ollama_circuit_breaker.current_state
    
    status = "healthy" if ollama_healthy and circuit_state != "open" else "degraded"
    
    return jsonify({
        "status": status,
        "service": "ollama-gateway",
        "ollama_status": "connected" if ollama_healthy else "disconnected",
        "circuit_breaker": str(circuit_state),
        "queue_depth": stats['queue_depth'],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }), 200 if status == "healthy" else 503


@app.route("/stats", methods=["GET"])
def get_stats():
    """요청 통계 조회"""
    return jsonify({
        "total_requests": stats['total_requests'],
        "successful_requests": stats['successful_requests'],
        "failed_requests": stats['failed_requests'],
        "rate_limited_requests": stats['rate_limited_requests'],
        "circuit_breaker_open_count": stats['circuit_breaker_open_count'],
        "avg_response_time_ms": round(stats['avg_response_time_ms'], 2),
        "queue_depth": stats['queue_depth'],
        "circuit_breaker_state": str(ollama_circuit_breaker.current_state),
        "recent_requests": list(stats['request_history'])[-10:],  # 최근 10개
    })


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# API Endpoints
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.route("/api/generate", methods=["POST"])
@limiter.limit(get_dynamic_generate_limit, key_func=get_model_aware_key)
def generate():
    """
    텍스트 생성 요청 (Ollama /api/generate Proxy)
    
    Request Body:
    {
        "model": "qwen3:32b",
        "prompt": "Hello, world!",
        "options": {"temperature": 0.2}
    }
    """
    stats['total_requests'] += 1
    stats['queue_depth'] += 1
    
    start_time = time.time()
    request_id = f"gen_{int(start_time * 1000)}"
    
    try:
        data = request.get_json()
        model = data.get("model", "qwen3:32b")
        prompt = data.get("prompt", "")
        
        logger.info(f"📥 [Request {request_id}] 텍스트 생성 요청 (model={model}, prompt_len={len(prompt)})")
        
        with request_lock:  # 순차 처리 보장
            result = call_ollama_with_breaker("/api/generate", data)
        
        elapsed_ms = (time.time() - start_time) * 1000
        stats['successful_requests'] += 1
        _update_avg_response_time(elapsed_ms)
        
        logger.info(f"✅ [Request {request_id}] 완료 ({elapsed_ms:.0f}ms)")
        
        stats['request_history'].append({
            "id": request_id,
            "type": "generate",
            "model": model,
            "status": "success",
            "elapsed_ms": round(elapsed_ms, 0),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        
        return jsonify(result)
        
    except CircuitBreakerError:
        stats['failed_requests'] += 1
        logger.error(f"❌ [Request {request_id}] Circuit Breaker OPEN - 요청 거부")
        return jsonify({
            "error": "Service temporarily unavailable (Circuit Breaker Open)",
            "retry_after": ollama_circuit_breaker.reset_timeout,
        }), 503
        
    except requests.exceptions.Timeout:
        stats['failed_requests'] += 1
        logger.error(f"❌ [Request {request_id}] Timeout")
        return jsonify({"error": "Ollama request timeout"}), 504
        
    except Exception as e:
        stats['failed_requests'] += 1
        logger.error(f"❌ [Request {request_id}] Error: {e}")
        return jsonify({"error": str(e)}), 500
        
    finally:
        stats['queue_depth'] -= 1

@app.route("/api/chat", methods=["POST"])
@limiter.limit(get_dynamic_generate_limit, key_func=get_model_aware_key)
def chat():
    """
    채팅 완료 요청 (Ollama /api/chat Proxy)
    
    Request Body:
    {
        "model": "qwen3:32b",
        "messages": [
            {"role": "user", "content": "Hello"}
        ],
        "options": {"temperature": 0.2}
    }
    """
    stats['total_requests'] += 1
    stats['queue_depth'] += 1
    
    start_time = time.time()
    request_id = f"chat_{int(start_time * 1000)}"
    
    try:
        data = request.get_json()
        model = data.get("model", "qwen3:32b")
        messages = data.get("messages", [])
        
        logger.info(f"📥 [Request {request_id}] 채팅 요청 (model={model}, msgs={len(messages)})")
        
        with request_lock:  # 순차 처리 보장
            result = call_ollama_with_breaker("/api/chat", data)
        
        elapsed_ms = (time.time() - start_time) * 1000
        stats['successful_requests'] += 1
        _update_avg_response_time(elapsed_ms)
        
        logger.info(f"✅ [Request {request_id}] 완료 ({elapsed_ms:.0f}ms)")
        
        stats['request_history'].append({
            "id": request_id,
            "type": "chat",
            "model": model,
            "status": "success",
            "elapsed_ms": round(elapsed_ms, 0),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        
        return jsonify(result)
        
    except CircuitBreakerError:
        stats['failed_requests'] += 1
        logger.error(f"❌ [Request {request_id}] Circuit Breaker OPEN - 요청 거부")
        return jsonify({
            "error": "Service temporarily unavailable (Circuit Breaker Open)",
            "retry_after": ollama_circuit_breaker.reset_timeout,
        }), 503
        
    except requests.exceptions.Timeout:
        stats['failed_requests'] += 1
        logger.error(f"❌ [Request {request_id}] Timeout")
        return jsonify({"error": "Ollama request timeout"}), 504
        
    except Exception as e:
        stats['failed_requests'] += 1
        logger.error(f"❌ [Request {request_id}] Error: {e}")
        return jsonify({"error": str(e)}), 500
        
    finally:
        stats['queue_depth'] -= 1


@app.route("/api/embed", methods=["POST"])
@app.route("/api/embeddings", methods=["POST"])
@limiter.limit(RATE_LIMIT_EMBED)
def embed():
    """
    임베딩 생성 요청 (Ollama /api/embed Proxy)
    
    Request Body:
    {
        "model": "daynice/kure-v1",
        "input": "Hello world" or ["Hello", "world"]
    }
    """
    stats['total_requests'] += 1
    stats['queue_depth'] += 1
    
    start_time = time.time()
    request_id = f"emb_{int(start_time * 1000)}"
    
    try:
        data = request.get_json()
        model = data.get("model", "unknown")
        input_data = data.get("input", "")
        
        # input 길이 로깅 (문자열 또는 리스트)
        input_len = len(input_data) if isinstance(input_data, list) else len(str(input_data))
        logger.info(f"📥 [Request {request_id}] 임베딩 요청 (model={model}, input_len={input_len})")
        
        # Endpoint determination based on request path
        # langchain_ollama uses /api/embed (new), others might use /api/embeddings (old)
        target_endpoint = request.path
        
        with request_lock:  # 순차 처리 보장
            result = call_ollama_with_breaker(target_endpoint, data)
        
        elapsed_ms = (time.time() - start_time) * 1000
        stats['successful_requests'] += 1
        _update_avg_response_time(elapsed_ms)
        
        logger.info(f"✅ [Request {request_id}] 완료 ({elapsed_ms:.0f}ms)")
        
        stats['request_history'].append({
            "id": request_id,
            "type": "embed",
            "model": model,
            "status": "success",
            "elapsed_ms": round(elapsed_ms, 0),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        
        return jsonify(result)
        
    except CircuitBreakerError:
        stats['failed_requests'] += 1
        logger.error(f"❌ [Request {request_id}] Circuit Breaker OPEN - 요청 거부")
        return jsonify({
            "error": "Service temporarily unavailable (Circuit Breaker Open)",
            "retry_after": ollama_circuit_breaker.reset_timeout,
        }), 503
        
    except requests.exceptions.Timeout:
        stats['failed_requests'] += 1
        logger.error(f"❌ [Request {request_id}] Timeout")
        return jsonify({"error": "Ollama request timeout"}), 504
        
    except Exception as e:
        stats['failed_requests'] += 1
        logger.error(f"❌ [Request {request_id}] Error: {e}")
        return jsonify({"error": str(e)}), 500
        
    finally:
        stats['queue_depth'] -= 1
@limiter.limit(get_dynamic_generate_limit, key_func=get_model_aware_key)
def generate_json():
    """
    JSON 생성 요청 (스키마 검증 포함)
    
    Request Body:
    {
        "model": "qwen3:32b",
        "prompt": "...",
        "response_schema": {...},
        "options": {"temperature": 0.2}
    }
    """
    stats['total_requests'] += 1
    stats['queue_depth'] += 1
    
    start_time = time.time()
    request_id = f"json_{int(start_time * 1000)}"
    
    try:
        data = request.get_json()
        model = data.get("model", "qwen3:32b")
        prompt = data.get("prompt", "")
        response_schema = data.get("response_schema")
        timeout = data.get("timeout", 180)
        
        logger.info(f"📥 [Request {request_id}] JSON 생성 요청 (model={model}, prompt_len={len(prompt)})")
        
        # Ollama 요청 페이로드 구성
        ollama_payload = {
            "model": model,
            "prompt": prompt,
            "options": data.get("options", {"temperature": 0.2, "num_ctx": 8192}),
        }
        
        with request_lock:  # 순차 처리 보장
            result = call_ollama_with_breaker("/api/generate", ollama_payload, timeout=timeout)
        
        # 응답 파싱
        response_text = result.get("response", "")
        
        # JSON 추출 (마크다운 코드블록 처리)
        json_content = _extract_json_from_response(response_text)
        
        if json_content is None:
            raise ValueError(f"JSON 파싱 실패: {response_text[:200]}")
        
        elapsed_ms = (time.time() - start_time) * 1000
        stats['successful_requests'] += 1
        _update_avg_response_time(elapsed_ms)
        
        logger.info(f"✅ [Request {request_id}] 완료 ({elapsed_ms:.0f}ms)")
        
        stats['request_history'].append({
            "id": request_id,
            "type": "generate-json",
            "model": model,
            "status": "success",
            "elapsed_ms": round(elapsed_ms, 0),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        
        return jsonify({
            "parsed_json": json_content,
            "raw_response": response_text,
            "model": model,
            "elapsed_ms": round(elapsed_ms, 0),
        })
        
    except CircuitBreakerError:
        stats['failed_requests'] += 1
        logger.error(f"❌ [Request {request_id}] Circuit Breaker OPEN - 요청 거부")
        return jsonify({
            "error": "Service temporarily unavailable (Circuit Breaker Open)",
            "retry_after": ollama_circuit_breaker.reset_timeout,
        }), 503
        
    except requests.exceptions.Timeout:
        stats['failed_requests'] += 1
        logger.error(f"❌ [Request {request_id}] Timeout")
        return jsonify({"error": "Ollama request timeout"}), 504
        
    except ValueError as e:
        stats['failed_requests'] += 1
        logger.error(f"❌ [Request {request_id}] JSON Parse Error: {e}")
        return jsonify({"error": str(e)}), 422
        
    except Exception as e:
        stats['failed_requests'] += 1
        logger.error(f"❌ [Request {request_id}] Error: {e}")
        return jsonify({"error": str(e)}), 500
        
    finally:
        stats['queue_depth'] -= 1


@app.route("/api/models", methods=["GET"])
def list_models():
    """사용 가능한 모델 목록 조회 (Ollama /api/tags Proxy)"""
    try:
        response = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except Exception as e:
        logger.error(f"❌ 모델 목록 조회 실패: {e}")
        return jsonify({"error": str(e)}), 500


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 유틸리티 함수
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _extract_json_from_response(response_text: str) -> Optional[Dict]:
    """응답 텍스트에서 JSON 추출 (마크다운 코드블록 처리)"""
    content = response_text.strip()
    
    # <think>...</think> 태그 제거 (Qwen3 특성)
    if "<think>" in content and "</think>" in content:
        think_end = content.find("</think>") + len("</think>")
        content = content[think_end:].strip()
    
    # 마크다운 코드블록 추출
    if "```json" in content:
        start = content.find("```json") + 7
        end = content.find("```", start)
        if end > start:
            content = content[start:end].strip()
    elif "```" in content:
        start = content.find("```") + 3
        end = content.find("```", start)
        if end > start:
            content = content[start:end].strip()
    
    # JSON 파싱 시도
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # { } 범위 추출 시도
        if "{" in content and "}" in content:
            start = content.find("{")
            end = content.rfind("}") + 1
            try:
                return json.loads(content[start:end])
            except json.JSONDecodeError:
                pass
        return None


def _update_avg_response_time(new_time_ms: float):
    """평균 응답 시간 업데이트 (지수 이동 평균)"""
    alpha = 0.1  # 스무딩 계수
    if stats['avg_response_time_ms'] == 0:
        stats['avg_response_time_ms'] = new_time_ms
    else:
        stats['avg_response_time_ms'] = (alpha * new_time_ms) + ((1 - alpha) * stats['avg_response_time_ms'])


# Rate Limit 초과 에러 핸들러
@app.errorhandler(429)
def ratelimit_handler(e):
    stats['rate_limited_requests'] += 1
    logger.warning(f"⚠️ Rate limit exceeded: {e.description}")
    return jsonify({
        "error": "Rate limit exceeded",
        "message": "Ollama Gateway is busy. Please retry after a moment.",
        "retry_after": 5,
    }), 429


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 메인 실행
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":
    # 개발 모드 실행
    app.run(host="0.0.0.0", port=11500, debug=False)
