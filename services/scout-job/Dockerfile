# Scout Job Service Dockerfile (Multi-stage)

# ------------------------------------------------------------------------------
# Stage 1: Builder
# ------------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS builder

WORKDIR /app

# Install system dependencies for build
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    pkg-config \
    libssl-dev \
    python3-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Rust toolchain
RUN curl https://sh.rustup.rs -sSf | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# Install Maturin for Rust builds
RUN pip install maturin

# Create virtual environment
RUN python -m venv /app/.venv
ENV PATH="/app/.venv/bin:${PATH}"

# Install Python dependencies
COPY services/scout-job/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Build & Install Rust Strategy Core
COPY shared/strategy_core /app/shared/strategy_core
COPY scripts/build_strategy_core.sh /app/scripts/build_strategy_core.sh
RUN chmod +x /app/scripts/build_strategy_core.sh && \
    /app/scripts/build_strategy_core.sh

# ------------------------------------------------------------------------------
# Stage 2: Runtime
# ------------------------------------------------------------------------------
FROM python:3.11-slim-bookworm

WORKDIR /app

# Install runtime system dependencies (minimal)
# libaio1 might be needed for some shared DB drivers if used
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libaio1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Enable venv
ENV PATH="/app/.venv/bin:${PATH}"
ENV PYTHONPATH=/app

# Copy shared modules & resources
COPY shared /app/shared
COPY prompts /app/prompts
COPY schemas /app/schemas

# Copy service code
COPY services/scout-job /app/services/scout-job
COPY utilities /app/utilities

# Set working directory to service folder
WORKDIR /app/services/scout-job

# Run with gunicorn
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 1 --timeout 1800 --access-logfile - --error-logfile - main:app"]
