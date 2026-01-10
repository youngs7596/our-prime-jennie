FROM python:3.11-slim

WORKDIR /app

# 최소 의존성 (WebSocket 지원 추가)
RUN pip install --no-cache-dir flask flask-socketio python-socketio requests

COPY docker/kis-mock/mock_server.py .

EXPOSE 9443

CMD ["python", "mock_server.py"]

