# tests/e2e/fixtures/rabbitmq_fixtures.py
"""
RabbitMQ Mock Fixtures for E2E Testing

Provides in-memory message queue simulation for testing
message-based communication between services.
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
class Message:
    """A message in the mock queue"""
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


class MockQueue:
    """In-memory queue that mimics RabbitMQ queue behavior"""

    def __init__(self, name: str, durable: bool = True):
        self.name = name
        self.durable = durable
        self._messages: Queue = Queue()
        self._unacked: Dict[str, Message] = {}
        self._message_count = 0
        self._consumers: List[Callable] = []
        self._lock = threading.Lock()

    def enqueue(self, message: Message):
        """Add a message to the queue"""
        with self._lock:
            self._messages.put(message)
            self._message_count += 1

    def dequeue(self, timeout: Optional[float] = None) -> Optional[Message]:
        """Get a message from the queue"""
        try:
            message = self._messages.get(timeout=timeout)
            self._unacked[message.message_id] = message
            return message
        except Empty:
            return None

    def ack(self, message_id: str) -> bool:
        """Acknowledge a message"""
        with self._lock:
            if message_id in self._unacked:
                self._unacked[message_id].acknowledged = True
                del self._unacked[message_id]
                return True
            return False

    def nack(self, message_id: str, requeue: bool = True) -> bool:
        """Negative acknowledge a message"""
        with self._lock:
            if message_id in self._unacked:
                message = self._unacked.pop(message_id)
                if requeue:
                    message.redelivered = True
                    self._messages.put(message)
                return True
            return False

    def size(self) -> int:
        """Get approximate queue size"""
        return self._messages.qsize()

    def is_empty(self) -> bool:
        """Check if queue is empty"""
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


class MockRabbitMQPublisher:
    """
    Mock RabbitMQ Publisher

    Simulates message publishing to queues for testing.
    Compatible with the real RabbitMQPublisher interface.
    """

    def __init__(self, queue_name: str = "buy-signals"):
        self.queue_name = queue_name
        self._queues: Dict[str, MockQueue] = {}
        self._published_messages: List[Message] = []
        self._connected = True

        # Initialize default queue
        self._get_or_create_queue(queue_name)

    def _get_or_create_queue(self, name: str) -> MockQueue:
        """Get or create a queue"""
        if name not in self._queues:
            self._queues[name] = MockQueue(name)
        return self._queues[name]

    def publish(self, message: Any, routing_key: Optional[str] = None,
                properties: Optional[Dict] = None) -> Optional[str]:
        """
        Publish a message to the queue

        Args:
            message: Message body (will be JSON serialized)
            routing_key: Optional routing key (defaults to queue_name)
            properties: Optional message properties

        Returns:
            Message ID on success, None on failure
        """
        if not self._connected:
            return None

        target_queue = routing_key or self.queue_name
        queue = self._get_or_create_queue(target_queue)

        msg = Message(
            message_id=str(uuid.uuid4()),
            body=message,
            timestamp=time.time(),
            properties=properties or {}
        )

        queue.enqueue(msg)
        self._published_messages.append(msg)

        return msg.message_id

    def publish_batch(self, messages: List[Any]) -> List[str]:
        """Publish multiple messages"""
        return [self.publish(msg) for msg in messages]

    def disconnect(self):
        """Simulate disconnection"""
        self._connected = False

    def reconnect(self):
        """Simulate reconnection"""
        self._connected = True

    @property
    def is_connected(self) -> bool:
        return self._connected

    def get_queue(self, name: Optional[str] = None) -> MockQueue:
        """Get a queue by name"""
        return self._get_or_create_queue(name or self.queue_name)

    def get_published_messages(self) -> List[Message]:
        """Get all published messages (for assertions)"""
        return self._published_messages.copy()

    def clear_history(self):
        """Clear published message history"""
        self._published_messages.clear()

    def reset(self):
        """Reset all queues and history"""
        for queue in self._queues.values():
            queue.clear()
        self._published_messages.clear()
        self._connected = True


class MockRabbitMQConsumer:
    """
    Mock RabbitMQ Consumer

    Simulates message consumption from queues for testing.
    """

    def __init__(self, queue_name: str, handler: Optional[Callable] = None):
        self.queue_name = queue_name
        self.handler = handler
        self._queue: Optional[MockQueue] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._processed_messages: List[Message] = []
        self._errors: List[Exception] = []

    def bind_to_queue(self, queue: MockQueue):
        """Bind to a specific queue"""
        self._queue = queue

    def start(self, blocking: bool = False):
        """Start consuming messages"""
        if not self._queue:
            raise RuntimeError("No queue bound to consumer")

        self._running = True

        if blocking:
            self._consume_loop()
        else:
            self._thread = threading.Thread(target=self._consume_loop, daemon=True)
            self._thread.start()

    def stop(self):
        """Stop consuming"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def _consume_loop(self):
        """Main consumption loop"""
        while self._running:
            message = self._queue.dequeue(timeout=0.1)
            if message:
                self._process_message(message)

    def _process_message(self, message: Message):
        """Process a single message"""
        try:
            if self.handler:
                self.handler(message.body)
            self._queue.ack(message.message_id)
            self._processed_messages.append(message)
        except Exception as e:
            self._errors.append(e)
            self._queue.nack(message.message_id, requeue=True)

    def consume_one(self, timeout: float = 1.0) -> Optional[Message]:
        """
        Consume a single message (for synchronous testing)

        Args:
            timeout: How long to wait for a message

        Returns:
            The message if available, None otherwise
        """
        if not self._queue:
            raise RuntimeError("No queue bound to consumer")

        message = self._queue.dequeue(timeout=timeout)
        if message:
            self._process_message(message)
        return message

    def consume_all(self, max_messages: int = 100) -> List[Message]:
        """
        Consume all available messages

        Args:
            max_messages: Maximum messages to consume

        Returns:
            List of consumed messages
        """
        messages = []
        for _ in range(max_messages):
            msg = self.consume_one(timeout=0.1)
            if not msg:
                break
            messages.append(msg)
        return messages

    def get_processed_messages(self) -> List[Message]:
        """Get all processed messages"""
        return self._processed_messages.copy()

    def get_errors(self) -> List[Exception]:
        """Get all processing errors"""
        return self._errors.copy()

    def clear_history(self):
        """Clear processed messages and errors"""
        self._processed_messages.clear()
        self._errors.clear()


class RabbitMQTestBridge:
    """
    Test Bridge connecting Publishers and Consumers

    Provides a unified interface for testing message flows
    between services.
    """

    def __init__(self):
        self._publishers: Dict[str, MockRabbitMQPublisher] = {}
        self._consumers: Dict[str, MockRabbitMQConsumer] = {}
        self._queues: Dict[str, MockQueue] = {}

    def create_publisher(self, queue_name: str) -> MockRabbitMQPublisher:
        """Create a publisher for a queue"""
        publisher = MockRabbitMQPublisher(queue_name)
        self._publishers[queue_name] = publisher

        # Share queues between publishers and the bridge
        for name, queue in publisher._queues.items():
            if name not in self._queues:
                self._queues[name] = queue
            else:
                publisher._queues[name] = self._queues[name]

        return publisher

    def create_consumer(self, queue_name: str,
                        handler: Optional[Callable] = None) -> MockRabbitMQConsumer:
        """Create a consumer for a queue"""
        consumer = MockRabbitMQConsumer(queue_name, handler)
        self._consumers[queue_name] = consumer

        # Bind to existing queue or create new one
        if queue_name not in self._queues:
            self._queues[queue_name] = MockQueue(queue_name)
        consumer.bind_to_queue(self._queues[queue_name])

        return consumer

    def get_queue(self, name: str) -> Optional[MockQueue]:
        """Get a queue by name"""
        return self._queues.get(name)

    def get_publisher(self, queue_name: str) -> Optional[MockRabbitMQPublisher]:
        """Get a publisher by queue name"""
        return self._publishers.get(queue_name)

    def get_consumer(self, queue_name: str) -> Optional[MockRabbitMQConsumer]:
        """Get a consumer by queue name"""
        return self._consumers.get(queue_name)

    def publish(self, queue_name: str, message: Any) -> Optional[str]:
        """Convenience method to publish to a queue"""
        publisher = self._publishers.get(queue_name)
        if not publisher:
            publisher = self.create_publisher(queue_name)
        return publisher.publish(message)

    def consume(self, queue_name: str, timeout: float = 1.0) -> Optional[Message]:
        """Convenience method to consume from a queue"""
        consumer = self._consumers.get(queue_name)
        if not consumer:
            consumer = self.create_consumer(queue_name)
        return consumer.consume_one(timeout=timeout)

    def consume_all(self, queue_name: str) -> List[Message]:
        """Consume all messages from a queue"""
        consumer = self._consumers.get(queue_name)
        if not consumer:
            consumer = self.create_consumer(queue_name)
        return consumer.consume_all()

    def wait_for_message(self, queue_name: str, timeout: float = 5.0,
                         match: Optional[Callable[[Any], bool]] = None) -> Optional[Message]:
        """
        Wait for a specific message

        Args:
            queue_name: Queue to wait on
            timeout: Maximum wait time
            match: Optional predicate to match message body

        Returns:
            Matching message or None
        """
        start_time = time.time()
        consumer = self._consumers.get(queue_name) or self.create_consumer(queue_name)

        while time.time() - start_time < timeout:
            message = consumer.consume_one(timeout=0.1)
            if message:
                if match is None or match(message.body):
                    return message
        return None

    def get_all_messages(self) -> Dict[str, List[Message]]:
        """Get all processed messages from all consumers"""
        return {
            name: consumer.get_processed_messages()
            for name, consumer in self._consumers.items()
        }

    def reset(self):
        """Reset all queues, publishers, and consumers"""
        for publisher in self._publishers.values():
            publisher.reset()
        for consumer in self._consumers.values():
            consumer.stop()
            consumer.clear_history()
        for queue in self._queues.values():
            queue.clear()

    def start_all_consumers(self):
        """Start all consumers"""
        for consumer in self._consumers.values():
            if not consumer._running:
                consumer.start()

    def stop_all_consumers(self):
        """Stop all consumers"""
        for consumer in self._consumers.values():
            consumer.stop()


# Common queue names used in the system
class QueueNames:
    """Standard queue names for the trading system"""
    BUY_SIGNALS = "buy-signals"
    SELL_ORDERS = "sell-orders"
    PRICE_UPDATES = "price-updates"
    NOTIFICATIONS = "notifications"
