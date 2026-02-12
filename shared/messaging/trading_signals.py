"""
shared/messaging/trading_signals.py
------------------------------------
Redis Streams 기반 트레이딩 시그널 메시징.
RabbitMQ(pika)를 대체하여 buy-signals, sell-orders, jobs.scout 큐를 처리합니다.

사용 예시:
---------
>>> from shared.messaging.trading_signals import TradingSignalPublisher, TradingSignalWorker
>>>
>>> # 발행
>>> pub = TradingSignalPublisher(redis_url, STREAM_BUY_SIGNALS)
>>> pub.publish({'stock_code': '005930', 'signal': 'RSI_OVERSOLD'})
>>>
>>> # 소비
>>> def handler(message):
...     print(f"Received: {message}")
>>> worker = TradingSignalWorker(redis_url, STREAM_BUY_SIGNALS, GROUP_BUY_EXECUTOR, "worker-1", handler)
>>> worker.start()
"""

import json
import logging
import os
import threading
import time
from typing import Callable, Dict, Optional

import redis

logger = logging.getLogger(__name__)

# ==============================================================================
# Stream & Consumer Group Names
# ==============================================================================

STREAM_BUY_SIGNALS = "stream:buy-signals"
STREAM_SELL_ORDERS = "stream:sell-orders"
STREAM_JOBS_SCOUT = "stream:jobs:scout"

GROUP_BUY_EXECUTOR = "group_buy_executor"
GROUP_SELL_EXECUTOR = "group_sell_executor"
GROUP_SCOUT_WORKER = "group_scout_worker"

# Scheduler-service 동적 큐용 prefix
STREAM_JOBS_PREFIX = "stream:jobs:"

# ==============================================================================
# Defaults
# ==============================================================================

RECONNECT_DELAY = 5  # 초기 재연결 대기 (초)
MAX_RECONNECT_DELAY = 60  # 최대 재연결 대기 (초)


class TradingSignalPublisher:
    """Redis Streams 기반 메시지 발행 클래스 (RabbitMQPublisher 대체)"""

    def __init__(self, redis_url: str, stream_name: str):
        self.redis_url = redis_url
        self.stream_name = stream_name
        self._client: Optional[redis.Redis] = None

    def _get_client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(self.redis_url, decode_responses=True)
        return self._client

    def publish(
        self,
        payload: dict,
        delay_seconds: int = 0,
        headers: Optional[Dict] = None,
        message_ttl_ms: Optional[int] = None,
    ) -> Optional[str]:
        """메시지를 Redis Stream에 발행하고 메시지 ID를 반환합니다.

        delay_seconds, headers, message_ttl_ms 는 RabbitMQ 호환 시그니처이며
        Redis Streams에서는 무시됩니다 (at-most-once 시맨틱).
        """
        try:
            client = self._get_client()
            data = {
                "payload": json.dumps(payload, ensure_ascii=False, default=str),
            }
            msg_id = client.xadd(self.stream_name, data)
            logger.info(
                "✅ Redis Stream 메시지 발행: %s (stream=%s)",
                msg_id,
                self.stream_name,
            )
            return msg_id
        except Exception as e:
            logger.error(f"❌ Redis Stream 메시지 발행 실패: {e}", exc_info=True)
            # 연결 리셋하여 다음 호출 시 재연결
            self._client = None
            return None

    def close(self):
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None


class TradingSignalWorker:
    """Redis Streams 기반 메시지 소비 워커 (RabbitMQWorker 대체)

    기존 RabbitMQWorker와 동일한 at-most-once 시맨틱:
    - handler 호출 전 ACK (장시간 처리 중 연결 끊김으로 인한 재처리 방지)
    - handler 실패 시 메시지 유실 허용 (Scout Job 등은 자체 중복 방지 내장)
    """

    def __init__(
        self,
        redis_url: str,
        stream_name: str,
        group_name: str,
        consumer_name: str,
        handler: Callable[[Dict], None],
    ):
        self.redis_url = redis_url
        self.stream_name = stream_name
        self.group_name = group_name
        self.consumer_name = consumer_name
        self.handler = handler
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._reconnect_count = 0

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info(
            "✅ Redis Stream 워커 시작: stream=%s, group=%s, consumer=%s",
            self.stream_name,
            self.group_name,
            self.consumer_name,
        )

    def stop(self):
        logger.info("🛑 Redis Stream 워커 종료 요청...")
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _ensure_group(self, client: redis.Redis):
        """Consumer Group이 없으면 생성 (스트림도 자동 생성)"""
        try:
            client.xgroup_create(
                self.stream_name, self.group_name, id="0", mkstream=True
            )
            logger.info(
                "✅ Consumer Group 생성: %s on %s",
                self.group_name,
                self.stream_name,
            )
        except redis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                pass  # 이미 존재
            else:
                raise

    def _run(self):
        while not self._stop_event.is_set():
            client = None
            try:
                client = redis.from_url(self.redis_url, decode_responses=True)
                self._ensure_group(client)
                self._reconnect_count = 0
                logger.info(
                    "✅ Redis Stream 연결 성공 (stream=%s)", self.stream_name
                )

                # Phase 1: 미처리 pending 메시지 복구
                self._recover_pending(client)

                # Phase 2: 새 메시지 소비 루프
                while not self._stop_event.is_set():
                    try:
                        results = client.xreadgroup(
                            self.group_name,
                            self.consumer_name,
                            {self.stream_name: ">"},
                            count=1,
                            block=1000,  # 1초 블로킹 (stop_event 체크 주기)
                        )
                    except redis.ConnectionError:
                        logger.warning("⚠️ Redis 연결 끊김 감지, 재연결 시도...")
                        break

                    if not results:
                        continue

                    for _stream, messages in results:
                        for msg_id, data in messages:
                            self._process_message(client, msg_id, data)

            except redis.ConnectionError as e:
                self._handle_reconnect(e)
            except Exception as exc:
                self._handle_reconnect(exc)
            finally:
                if client:
                    try:
                        client.close()
                    except Exception:
                        pass

        logger.info("🛑 Redis Stream 워커 종료 완료 (stream=%s)", self.stream_name)

    def _recover_pending(self, client: redis.Redis):
        """미확인(pending) 메시지 복구 처리"""
        try:
            results = client.xreadgroup(
                self.group_name,
                self.consumer_name,
                {self.stream_name: "0"},  # "0" = pending messages
                count=100,
            )
            if not results:
                return

            for _stream, messages in results:
                if not messages:
                    continue
                logger.info(
                    "🔄 Pending 메시지 복구: %d건 (stream=%s)",
                    len(messages),
                    self.stream_name,
                )
                for msg_id, data in messages:
                    if data:  # data가 빈 dict이면 이미 처리된 것
                        self._process_message(client, msg_id, data)
                    else:
                        # 이미 ACK된 메시지 (빈 데이터) — 스킵
                        client.xack(self.stream_name, self.group_name, msg_id)
        except Exception as e:
            logger.warning(f"⚠️ Pending 메시지 복구 실패: {e}")

    def _process_message(self, client: redis.Redis, msg_id: str, data: dict):
        """단일 메시지 처리 (ACK-first, at-most-once)"""
        try:
            # 1. ACK 먼저 (at-most-once: 장시간 처리 중 연결 끊김 방지)
            client.xack(self.stream_name, self.group_name, msg_id)

            # 2. Payload 파싱
            raw = data.get("payload", "{}")
            payload = json.loads(raw)
            logger.info("📥 Redis Stream 메시지 수신: %s (stream=%s)", msg_id, self.stream_name)

            # 3. Handler 실행
            self.handler(payload)

        except json.JSONDecodeError as e:
            logger.error(f"❌ 메시지 JSON 파싱 실패 (msg_id={msg_id}): {e}")
        except Exception as e:
            # handler 실패 — 이미 ACK됨, 로그만 남김
            logger.exception("❌ 메시지 처리 실패 (이미 ACK됨, msg_id=%s)", msg_id)

    def _handle_reconnect(self, error):
        self._reconnect_count += 1
        delay = min(RECONNECT_DELAY * self._reconnect_count, MAX_RECONNECT_DELAY)
        logger.warning(
            "⚠️ Redis Stream 연결 실패 (시도 #%d). %d초 후 재시도. 오류: %s",
            self._reconnect_count,
            delay,
            error,
        )
        # stop_event를 사용하여 대기 중에도 빠르게 종료 가능
        self._stop_event.wait(timeout=delay)
