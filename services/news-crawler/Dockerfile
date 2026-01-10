# services/news-crawler/Dockerfile
FROM python:3.11-slim-bookworm

WORKDIR /app

# 시스템 패키지 설치
RUN apt-get update && apt-get install -y \
    wget \
    unzip \
    libaio1 \
    && rm -rf /var/lib/apt/lists/*

# [OPTIMIZATION] requirements.txt만 먼저 복사하여 레이어 캐싱 활용
# 의존성이 변경되지 않으면 pip install 스킵
COPY services/news-crawler/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 코드 복사 (의존성 이후)
COPY shared/ /app/shared/
COPY prompts/ /app/prompts/
COPY schemas/ /app/schemas/
COPY services/news-crawler/*.py /app/

# 환경 변수
ENV PORT=8080
ENV PYTHONPATH=/app

# Gunicorn 실행 (PORT 환경변수 사용)
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-8080} --timeout 1200 --workers 1 main:app"]
