# tests/e2e/fixtures/redis_fixtures.py
"""
Redis Fixtures with Streams Support for E2E Testing

Provides fakeredis extension with XADD/XREAD support and
price stream simulation utilities.
"""

import time
import json
import threading
from typing import Dict, List, Optional, Tuple, Any, Callable
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

import fakeredis


@dataclass
class StreamEntry:
    """A single entry in a Redis stream"""
    entry_id: str
    data: Dict[str, str]


class StreamsEnabledFakeRedis:
    """
    Extended FakeRedis with Redis Streams support (XADD, XREAD, XRANGE, etc.)

    This class wraps fakeredis and adds stream operations that aren't
    natively supported in older fakeredis versions.
    """

    def __init__(self, decode_responses: bool = True):
        """Initialize with a fakeredis server"""
        self._server = fakeredis.FakeServer()
        self._client = fakeredis.FakeStrictRedis(
            server=self._server,
            decode_responses=decode_responses
        )
        self._streams: Dict[str, List[StreamEntry]] = defaultdict(list)
        self._stream_id_counter: Dict[str, int] = defaultdict(int)
        self._decode_responses = decode_responses

    def __getattr__(self, name: str):
        """Delegate to underlying fakeredis client"""
        return getattr(self._client, name)

    def _generate_entry_id(self, stream_key: str) -> str:
        """Generate a stream entry ID"""
        timestamp_ms = int(time.time() * 1000)
        self._stream_id_counter[stream_key] += 1
        seq = self._stream_id_counter[stream_key]
        return f"{timestamp_ms}-{seq}"

    def xadd(self, stream_key: str, fields: Dict[str, Any],
             entry_id: str = "*", maxlen: Optional[int] = None) -> str:
        """
        Add an entry to a stream (XADD)

        Args:
            stream_key: The stream name
            fields: Dictionary of field-value pairs
            entry_id: Entry ID ("*" for auto-generate)
            maxlen: Maximum stream length (approximate)

        Returns:
            The entry ID
        """
        if entry_id == "*":
            entry_id = self._generate_entry_id(stream_key)

        # Convert values to strings
        str_fields = {
            k: json.dumps(v) if not isinstance(v, str) else v
            for k, v in fields.items()
        }

        entry = StreamEntry(entry_id=entry_id, data=str_fields)
        self._streams[stream_key].append(entry)

        # Apply maxlen if specified
        if maxlen and len(self._streams[stream_key]) > maxlen:
            self._streams[stream_key] = self._streams[stream_key][-maxlen:]

        return entry_id

    def xread(self, streams: Dict[str, str], count: Optional[int] = None,
              block: Optional[int] = None) -> Optional[List]:
        """
        Read from streams (XREAD)

        Args:
            streams: Dict of stream_key -> last_id
            count: Maximum number of entries to return
            block: Blocking timeout in milliseconds (0 = forever)

        Returns:
            List of [stream_key, [[entry_id, fields], ...]] or None
        """
        start_time = time.time()
        timeout_sec = (block / 1000.0) if block else 0

        while True:
            results = []

            for stream_key, last_id in streams.items():
                stream_entries = self._streams.get(stream_key, [])

                # Filter entries after last_id
                if last_id == "0" or last_id == "0-0":
                    matching = stream_entries
                elif last_id == "$":
                    matching = []  # Only new entries
                else:
                    # Parse last_id and get entries after it
                    matching = []
                    found_last = False
                    for entry in stream_entries:
                        if found_last:
                            matching.append(entry)
                        if entry.entry_id == last_id:
                            found_last = True

                if count:
                    matching = matching[:count]

                if matching:
                    entries = [[e.entry_id, e.data] for e in matching]
                    results.append([stream_key, entries])

            if results:
                return results

            # Check timeout
            if block is None or block == 0:
                break
            if time.time() - start_time >= timeout_sec:
                break

            time.sleep(0.01)  # Small sleep to avoid busy loop

        return None

    def xrange(self, stream_key: str, start: str = "-", end: str = "+",
               count: Optional[int] = None) -> List:
        """
        Read range of entries from a stream (XRANGE)

        Args:
            stream_key: The stream name
            start: Start ID ("-" for beginning)
            end: End ID ("+" for end)
            count: Maximum number of entries

        Returns:
            List of [entry_id, fields]
        """
        stream_entries = self._streams.get(stream_key, [])

        results = []
        for entry in stream_entries:
            if count and len(results) >= count:
                break
            # Simplified range check (in real Redis this would be more complex)
            results.append([entry.entry_id, entry.data])

        return results

    def xlen(self, stream_key: str) -> int:
        """Get stream length"""
        return len(self._streams.get(stream_key, []))

    def xinfo_stream(self, stream_key: str) -> Dict:
        """Get stream info"""
        entries = self._streams.get(stream_key, [])
        return {
            "length": len(entries),
            "first-entry": [entries[0].entry_id, entries[0].data] if entries else None,
            "last-entry": [entries[-1].entry_id, entries[-1].data] if entries else None
        }

    def xdel(self, stream_key: str, *entry_ids: str) -> int:
        """Delete entries from stream"""
        if stream_key not in self._streams:
            return 0

        count = 0
        self._streams[stream_key] = [
            e for e in self._streams[stream_key]
            if e.entry_id not in entry_ids or (count := count + 1) < 0  # trick to count
        ]
        # Recalculate count properly
        original_len = len(self._streams[stream_key]) + len(entry_ids)
        return original_len - len(self._streams[stream_key])

    def xtrim(self, stream_key: str, maxlen: int, approximate: bool = True) -> int:
        """Trim stream to maxlen"""
        if stream_key not in self._streams:
            return 0

        original_len = len(self._streams[stream_key])
        if original_len <= maxlen:
            return 0

        self._streams[stream_key] = self._streams[stream_key][-maxlen:]
        return original_len - maxlen

    def clear_streams(self):
        """Clear all stream data (for test cleanup)"""
        self._streams.clear()
        self._stream_id_counter.clear()

    def flushall(self):
        """Clear all data including streams"""
        self._client.flushall()
        self.clear_streams()


@dataclass
class PriceTick:
    """A single price tick"""
    stock_code: str
    price: float
    volume: int
    timestamp: str


class PriceStreamSimulator:
    """
    Simulates price updates via Redis Streams

    Provides utilities for injecting price ticks and simulating
    various price patterns (uptrend, downtrend, volatile, etc.)
    """

    def __init__(self, redis_client: StreamsEnabledFakeRedis,
                 stream_key: str = "kis:prices"):
        self.redis = redis_client
        self.stream_key = stream_key
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._price_state: Dict[str, float] = {}

    def inject_price(self, stock_code: str, price: float, volume: int = 1000) -> str:
        """
        Inject a single price tick into the stream

        Args:
            stock_code: Stock code
            price: Current price
            volume: Trading volume

        Returns:
            Stream entry ID
        """
        tick_data = {
            "stock_code": stock_code,
            "price": str(price),
            "volume": str(volume),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        self._price_state[stock_code] = price
        return self.redis.xadd(self.stream_key, tick_data)

    def inject_batch(self, ticks: List[PriceTick]) -> List[str]:
        """Inject multiple price ticks"""
        entry_ids = []
        for tick in ticks:
            entry_id = self.inject_price(tick.stock_code, tick.price, tick.volume)
            entry_ids.append(entry_id)
        return entry_ids

    def simulate_uptrend(self, stock_code: str, start_price: float,
                         target_price: float, steps: int = 10,
                         base_volume: int = 10000) -> List[str]:
        """
        Simulate an uptrend pattern

        Args:
            stock_code: Stock code
            start_price: Starting price
            target_price: Target price
            steps: Number of price updates
            base_volume: Base volume (increases with trend)

        Returns:
            List of entry IDs
        """
        entry_ids = []
        price_step = (target_price - start_price) / steps

        for i in range(steps + 1):
            price = start_price + (price_step * i)
            # Add some noise
            noise = price * 0.001 * ((i % 3) - 1)
            current_price = price + noise

            # Volume increases as price goes up
            volume = int(base_volume * (1 + i * 0.1))

            entry_id = self.inject_price(stock_code, round(current_price, 0), volume)
            entry_ids.append(entry_id)

        return entry_ids

    def simulate_downtrend(self, stock_code: str, start_price: float,
                           target_price: float, steps: int = 10,
                           base_volume: int = 10000) -> List[str]:
        """
        Simulate a downtrend pattern

        Args:
            stock_code: Stock code
            start_price: Starting price
            target_price: Target price (lower than start)
            steps: Number of price updates
            base_volume: Base volume

        Returns:
            List of entry IDs
        """
        return self.simulate_uptrend(stock_code, start_price, target_price, steps, base_volume)

    def simulate_volatile(self, stock_code: str, base_price: float,
                          volatility_pct: float = 2.0, steps: int = 20,
                          base_volume: int = 10000) -> List[str]:
        """
        Simulate volatile (sideways) price movement

        Args:
            stock_code: Stock code
            base_price: Center price
            volatility_pct: Volatility as percentage
            steps: Number of updates
            base_volume: Base volume

        Returns:
            List of entry IDs
        """
        import random
        entry_ids = []

        for i in range(steps):
            # Random walk around base price
            pct_change = random.uniform(-volatility_pct, volatility_pct) / 100
            price = base_price * (1 + pct_change)

            # Higher volume during bigger moves
            vol_multiplier = 1 + abs(pct_change) * 10
            volume = int(base_volume * vol_multiplier)

            entry_id = self.inject_price(stock_code, round(price, 0), volume)
            entry_ids.append(entry_id)

        return entry_ids

    def simulate_golden_cross(self, stock_code: str, base_price: float,
                              steps: int = 30) -> List[str]:
        """
        Simulate a golden cross pattern (MA5 crosses above MA20)

        Creates price data where short MA crosses above long MA.
        """
        entry_ids = []

        # Phase 1: Downtrend (MA5 < MA20)
        for i in range(10):
            price = base_price * (1 - 0.005 * i)  # Small decline
            entry_ids.append(self.inject_price(stock_code, round(price, 0), 10000))

        # Phase 2: Consolidation
        for i in range(5):
            price = base_price * 0.95 * (1 + 0.002 * (i % 2))
            entry_ids.append(self.inject_price(stock_code, round(price, 0), 12000))

        # Phase 3: Breakout (MA5 > MA20)
        for i in range(15):
            price = base_price * (0.95 + 0.01 * i)  # Strong uptrend
            volume = 15000 + (i * 2000)  # Increasing volume
            entry_ids.append(self.inject_price(stock_code, round(price, 0), volume))

        return entry_ids

    def simulate_stop_loss_trigger(self, stock_code: str, buy_price: float,
                                   stop_loss_pct: float = -5.0) -> List[str]:
        """
        Simulate price dropping to stop loss level

        Args:
            stock_code: Stock code
            buy_price: Original buy price
            stop_loss_pct: Stop loss percentage (negative)

        Returns:
            List of entry IDs
        """
        entry_ids = []

        # Initial stability
        for i in range(5):
            price = buy_price * (1 - 0.005 * i)
            entry_ids.append(self.inject_price(stock_code, round(price, 0), 10000))

        # Sharp drop to stop loss
        stop_price = buy_price * (1 + stop_loss_pct / 100)
        current_price = buy_price * 0.975

        while current_price > stop_price:
            current_price *= 0.99  # 1% drops
            volume = 50000  # High volume on drops
            entry_ids.append(self.inject_price(stock_code, round(current_price, 0), volume))

        # Final price at stop loss
        entry_ids.append(self.inject_price(stock_code, round(stop_price, 0), 80000))

        return entry_ids

    def simulate_take_profit_trigger(self, stock_code: str, buy_price: float,
                                     take_profit_pct: float = 10.0) -> List[str]:
        """
        Simulate price rising to take profit level

        Args:
            stock_code: Stock code
            buy_price: Original buy price
            take_profit_pct: Take profit percentage

        Returns:
            List of entry IDs
        """
        entry_ids = []

        # Gradual rise to take profit
        target_price = buy_price * (1 + take_profit_pct / 100)
        steps = 15

        for i in range(steps):
            progress = i / (steps - 1)
            price = buy_price + (target_price - buy_price) * progress
            volume = 20000 + int(progress * 30000)  # Volume increases
            entry_ids.append(self.inject_price(stock_code, round(price, 0), volume))

        return entry_ids

    def get_current_price(self, stock_code: str) -> Optional[float]:
        """Get the current simulated price for a stock"""
        return self._price_state.get(stock_code)

    def clear(self):
        """Clear all price data"""
        self._price_state.clear()
        # Note: Stream data clearing is handled by redis_client.clear_streams()

    def start_continuous_simulation(self, stock_code: str, base_price: float,
                                    interval_sec: float = 0.1,
                                    volatility_pct: float = 0.5):
        """
        Start continuous price simulation in background thread

        Args:
            stock_code: Stock code
            base_price: Starting price
            interval_sec: Update interval in seconds
            volatility_pct: Price volatility percentage
        """
        import random

        self._running = True
        current_price = base_price

        def simulate():
            nonlocal current_price
            while self._running:
                pct_change = random.uniform(-volatility_pct, volatility_pct) / 100
                current_price = current_price * (1 + pct_change)
                volume = random.randint(1000, 50000)
                self.inject_price(stock_code, round(current_price, 0), volume)
                time.sleep(interval_sec)

        self._thread = threading.Thread(target=simulate, daemon=True)
        self._thread.start()

    def stop_continuous_simulation(self):
        """Stop continuous simulation"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=1)
            self._thread = None
