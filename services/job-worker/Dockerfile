# Job Worker Service Dockerfile
# scripts/ 및 utilities/ 스크립트를 subprocess로 실행하는 범용 워커

FROM python:3.11-slim-bookworm

WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    default-libmysqlclient-dev \
    pkg-config \
    curl \
    && rm -rf /var/lib/apt/lists/*

# [Layer Caching] Install Python dependencies first
COPY services/job-worker/requirements.txt /app/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r requirements.txt

# Copy shared modules & resources
COPY shared /app/shared
COPY prompts /app/prompts
COPY schemas /app/schemas

# Copy scripts & utilities (job-worker가 실행하는 대상)
COPY scripts /app/scripts
COPY utilities /app/utilities

# Copy telegram-collector (macro_council 의존)
COPY services/telegram-collector /app/services/telegram-collector

# Copy service code
COPY services/job-worker/main.py /app/services/job-worker/main.py

ENV PYTHONPATH=/app
ENV TZ=Asia/Seoul

EXPOSE 8095

CMD ["python", "services/job-worker/main.py"]
