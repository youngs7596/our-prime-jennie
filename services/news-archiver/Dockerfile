FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# [Layer Caching] 의존성 먼저 설치
COPY services/news-archiver/requirements.txt /app/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Copy shared modules (자주 변경되는 파일)
COPY shared/ /app/shared/

# Copy service code
COPY services/news-archiver/archiver.py /app/archiver.py

# Run as daemon by default
CMD ["python", "archiver.py", "--daemon"]
