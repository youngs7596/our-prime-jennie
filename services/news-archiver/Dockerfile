# News Archiver Dockerfile (Multi-stage)

# ------------------------------------------------------------------------------
# Stage 1: Builder
# ------------------------------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /app/.venv
ENV PATH="/app/.venv/bin:${PATH}"

# Install dependencies
COPY services/news-archiver/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ------------------------------------------------------------------------------
# Stage 2: Runtime
# ------------------------------------------------------------------------------
FROM python:3.12-slim

WORKDIR /app

# Copy virtual environment
COPY --from=builder /app/.venv /app/.venv

# Enable venv
ENV PATH="/app/.venv/bin:${PATH}"
ENV PYTHONPATH=/app

# Copy shared modules
COPY shared /app/shared

# Copy service code
COPY services/news-archiver /app/services/news-archiver

# Set working directory
WORKDIR /app/services/news-archiver

# Run archiver
CMD ["python", "archiver.py", "--daemon"]
