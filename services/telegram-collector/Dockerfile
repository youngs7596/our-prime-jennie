FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy shared modules
COPY shared/ /app/shared/
COPY services/telegram-collector/requirements.txt /app/requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy service code
COPY services/telegram-collector/ /app/

# secrets.json은 볼륨으로 마운트됨
# Run as daemon by default
CMD ["python", "collector.py", "--daemon", "--interval", "600"]
