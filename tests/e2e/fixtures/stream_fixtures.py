# tests/e2e/fixtures/stream_fixtures.py
"""
Redis Streams Mock Fixtures for E2E Testing

Provides in-memory message stream simulation for testing
message-based communication between services.
Replaces legacy rabbitmq_fixtures.py (RabbitMQ removed 2026-02-12).
"""

import json
import time
import uuid
import threading
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from collections import defaultdict
from datetime import datetime, timezone
from queue import Queue, Empty


@dataclass
class StreamMessage:
    """A message in the mock stream"""
    message_id: str
    body: Any
    timestamp: float
    properties: Dict[str, Any] = field(default_factory=dict)
    acknowledged: bool = False
    redelivered: bool = False

    def to_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "body": self.body,
            "timestamp": self.timestamp,
            "properties": self.properties,
            "acknowledged": self.acknowledged
        }


class MockStream:
    """In-memory stream that mimics Redis Streams behavior"""

    def __init__(self, name: str):
        self.name = name
        self._messages: Queue = Queue()
        self._unacked: Dict[str, StreamMessage] = {}
        self._message_count = 0
        self._lock = threading.Lock()

    def xadd(self, message: StreamMessage):
        """Add a message to the stream (XADD)"""
        with self._lock:
            self._messages.put(message)
            self._message_count += 1

    def xread(self, timeout: Optional[float] = None) -> Optional[StreamMessage]:
        """Read a message from the stream (XREADGROUP)"""
        try:
            message = self._messages.get(timeout=timeout)
            self._unacked[message.message_id] = message
            return message
        except Empty:
            return None

    def xack(self, message_id: str) -> bool:
        """Acknowledge a message (XACK)"""
        with self._lock:
            if message_id in self._unacked:
                self._unacked[message_id].acknowledged = True
                del self._unacked[message_id]
                return True
            return False

    def size(self) -> int:
        """Get approximate stream length (XLEN)"""
        return self._messages.qsize()

    def is_empty(self) -> bool:
        return self._messages.empty()

    def clear(self):
        """Clear all messages"""
        with self._lock:
            while not self._messages.empty():
                try:
                    self._messages.get_nowait()
                except Empty:
                    break
            self._unacked.clear()
            self._message_count = 0


class MockStreamPublisher:
    """
    Mock Redis Streams Publisher

    Simulates TradingSignalPublisher for testing.
    """

    def __init__(self, stream_name: str = "stream:buy-signals"):
        self.stream_name = stream_name
        self._streams: Dict[str, MockStream] = {}
        self._published_messages: List[StreamMessage] = []
        self._connected = True

        self._get_or_create_stream(stream_name)

    def _get_or_create_stream(self, name: str) -> MockStream:
        if name not in self._streams:
            self._streams[name] = MockStream(name)
        return self._streams[name]

    def publish(self, message: Any, routing_key: Optional[str] = None,
                properties: Optional[Dict] = None) -> Optional[str]:
        """Publish a message to the stream (XADD)"""
        if not self._connected:
            return None

        target = routing_key or self.stream_name
        stream = self._get_or_create_stream(target)

        msg = StreamMessage(
            message_id=str(uuid.uuid4()),
            body=message,
            timestamp=time.time(),
            properties=properties or {}
        )

        stream.xadd(msg)
        self._published_messages.append(msg)
        return msg.message_id

    def publish_batch(self, messages: List[Any]) -> List[str]:
        return [self.publish(msg) for msg in messages]

    def disconnect(self):
        self._connected = False

    def reconnect(self):
        self._connected = True

    @property
    def is_connected(self) -> bool:
        return self._connected

    def get_stream(self, name: Optional[str] = None) -> MockStream:
        return self._get_or_create_stream(name or self.stream_name)

    def get_published_messages(self) -> List[StreamMessage]:
        return self._published_messages.copy()

    def clear_history(self):
        self._published_messages.clear()

    def reset(self):
        for stream in self._streams.values():
            stream.clear()
        self._published_messages.clear()
        self._connected = True


class MockStreamConsumer:
    """
    Mock Redis Streams Consumer

    Simulates TradingSignalWorker for testing.
    """

    def __init__(self, stream_name: str, handler: Optional[Callable] = None):
        self.stream_name = stream_name
        self.handler = handler
        self._stream: Optional[MockStream] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._processed_messages: List[StreamMessage] = []
        self._errors: List[Exception] = []

    def bind_to_stream(self, stream: MockStream):
        self._stream = stream

    def start(self, blocking: bool = False):
        if not self._stream:
            raise RuntimeError("No stream bound to consumer")

        self._running = True
        if blocking:
            self._consume_loop()
        else:
            self._thread = threading.Thread(target=self._consume_loop, daemon=True)
            self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def _consume_loop(self):
        while self._running:
            message = self._stream.xread(timeout=0.1)
            if message:
                self._process_message(message)

    def _process_message(self, message: StreamMessage):
        try:
            if self.handler:
                self.handler(message.body)
            self._stream.xack(message.message_id)
            self._processed_messages.append(message)
        except Exception as e:
            self._errors.append(e)

    def consume_one(self, timeout: float = 1.0) -> Optional[StreamMessage]:
        """Consume a single message (for synchronous testing)"""
        if not self._stream:
            raise RuntimeError("No stream bound to consumer")

        message = self._stream.xread(timeout=timeout)
        if message:
            self._process_message(message)
        return message

    def consume_all(self, max_messages: int = 100) -> List[StreamMessage]:
        messages = []
        for _ in range(max_messages):
            msg = self.consume_one(timeout=0.1)
            if not msg:
                break
            messages.append(msg)
        return messages

    def get_processed_messages(self) -> List[StreamMessage]:
        return self._processed_messages.copy()

    def get_errors(self) -> List[Exception]:
        return self._errors.copy()

    def clear_history(self):
        self._processed_messages.clear()
        self._errors.clear()


class StreamTestBridge:
    """
    Test Bridge connecting Publishers and Consumers via Redis Streams.

    Provides a unified interface for testing message flows
    between services.
    """

    def __init__(self):
        self._publishers: Dict[str, MockStreamPublisher] = {}
        self._consumers: Dict[str, MockStreamConsumer] = {}
        self._streams: Dict[str, MockStream] = {}

    def create_publisher(self, stream_name: str) -> MockStreamPublisher:
        publisher = MockStreamPublisher(stream_name)
        self._publishers[stream_name] = publisher

        for name, stream in publisher._streams.items():
            if name not in self._streams:
                self._streams[name] = stream
            else:
                publisher._streams[name] = self._streams[name]

        return publisher

    def create_consumer(self, stream_name: str,
                        handler: Optional[Callable] = None) -> MockStreamConsumer:
        consumer = MockStreamConsumer(stream_name, handler)
        self._consumers[stream_name] = consumer

        if stream_name not in self._streams:
            self._streams[stream_name] = MockStream(stream_name)
        consumer.bind_to_stream(self._streams[stream_name])

        return consumer

    def get_stream(self, name: str) -> Optional[MockStream]:
        return self._streams.get(name)

    def get_publisher(self, stream_name: str) -> Optional[MockStreamPublisher]:
        return self._publishers.get(stream_name)

    def get_consumer(self, stream_name: str) -> Optional[MockStreamConsumer]:
        return self._consumers.get(stream_name)

    def publish(self, stream_name: str, message: Any) -> Optional[str]:
        publisher = self._publishers.get(stream_name)
        if not publisher:
            publisher = self.create_publisher(stream_name)
        return publisher.publish(message)

    def consume(self, stream_name: str, timeout: float = 1.0) -> Optional[StreamMessage]:
        consumer = self._consumers.get(stream_name)
        if not consumer:
            consumer = self.create_consumer(stream_name)
        return consumer.consume_one(timeout=timeout)

    def consume_all(self, stream_name: str) -> List[StreamMessage]:
        consumer = self._consumers.get(stream_name)
        if not consumer:
            consumer = self.create_consumer(stream_name)
        return consumer.consume_all()

    def wait_for_message(self, stream_name: str, timeout: float = 5.0,
                         match: Optional[Callable[[Any], bool]] = None) -> Optional[StreamMessage]:
        start_time = time.time()
        consumer = self._consumers.get(stream_name) or self.create_consumer(stream_name)

        while time.time() - start_time < timeout:
            message = consumer.consume_one(timeout=0.1)
            if message:
                if match is None or match(message.body):
                    return message
        return None

    def get_all_messages(self) -> Dict[str, List[StreamMessage]]:
        return {
            name: consumer.get_processed_messages()
            for name, consumer in self._consumers.items()
        }

    def reset(self):
        for publisher in self._publishers.values():
            publisher.reset()
        for consumer in self._consumers.values():
            consumer.stop()
            consumer.clear_history()
        for stream in self._streams.values():
            stream.clear()

    def start_all_consumers(self):
        for consumer in self._consumers.values():
            if not consumer._running:
                consumer.start()

    def stop_all_consumers(self):
        for consumer in self._consumers.values():
            consumer.stop()


# Stream names matching production (shared/messaging/trading_signals.py)
class StreamNames:
    """Standard stream names for the trading system"""
    BUY_SIGNALS = "stream:buy-signals"
    SELL_ORDERS = "stream:sell-orders"
    JOBS_SCOUT = "stream:jobs:scout"
