# Scheduler Service Dockerfile
FROM python:3.11-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# [Layer Caching] 의존성 먼저 설치
COPY services/scheduler-service/requirements.txt /app/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Copy shared libs (자주 변경되는 파일)
COPY shared/ /app/shared/

# Copy service code
COPY services/scheduler-service/ /app/

# Copy scripts (for worker)
COPY scripts/ /app/scripts/

ENV PORT=8095
ENV PYTHONPATH=/app

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8095"]

