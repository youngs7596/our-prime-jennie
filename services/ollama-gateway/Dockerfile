# services/ollama-gateway/Dockerfile
# Ollama Gateway - Local LLM 요청 중앙화 서비스

FROM python:3.10-slim

WORKDIR /app

# curl 설치 (헬스체크용)
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# [Layer Caching] 의존성 설치
COPY services/ollama-gateway/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# 애플리케이션 코드 복사
COPY services/ollama-gateway/main.py .

# 포트 노출
EXPOSE 11500

# 헬스 체크
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:11500/health || exit 1

# Gunicorn으로 실행 (Worker 1개 = 순차 처리 보장)
# --timeout 900: Qwen3 응답 대기 + 큐 대기 시간 (최대 15분)
CMD ["gunicorn", "-b", "0.0.0.0:11500", "main:app", "-w", "1", "--timeout", "900", "--access-logfile", "-"]
