#!/usr/bin/env bash
# Ensures all required Docker Compose profiles are brought up for autostart scenarios.
# Modified: Start infra first, wait for health, then start real.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"


echo "[systemd-autostart] Checking for NVIDIA GPU readiness..."
# Wait up to 60 seconds for the GPU to be recognized
for ((i=1; i<=60; i++)); do
    if nvidia-smi > /dev/null 2>&1; then
        echo "[systemd-autostart] GPU detected successfully."
        break
    fi
    echo "[systemd-autostart] GPU not ready yet (attempt $i/60). Waiting 1s..."
    sleep 1
done

echo "[systemd-autostart] Starting infra profile first..."
/usr/bin/docker compose --profile infra up -d

echo "[systemd-autostart] Waiting for infra services to be healthy..."
sleep 30  # Give infra services time to initialize

# Check key services are healthy
for service in rabbitmq redis chromadb; do
  echo "[systemd-autostart] Checking $service health..."
  timeout 120 bash -c "until docker compose ps $service | grep -q 'healthy'; do sleep 5; done" || true
done

echo "[systemd-autostart] Starting real profile..."
/usr/bin/docker compose --profile real up -d

echo "[systemd-autostart] All profiles started successfully!"
