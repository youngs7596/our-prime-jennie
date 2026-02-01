#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shared/macro_data/rate_limiter.py
---------------------------------
통합 Rate Limiter.

여러 API 클라이언트의 rate limit을 중앙에서 관리합니다.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Optional
from collections import deque

logger = logging.getLogger(__name__)


class RateLimitExceeded(Exception):
    """Rate limit 초과 예외"""

    def __init__(self, source: str, wait_seconds: float):
        self.source = source
        self.wait_seconds = wait_seconds
        super().__init__(
            f"Rate limit exceeded for {source}. Wait {wait_seconds:.1f}s"
        )


@dataclass
class RateLimitConfig:
    """Rate limit 설정"""
    requests_per_minute: int = 60
    daily_limit: int = 10000
    burst_limit: int = 10  # 연속 요청 허용 수


@dataclass
class RateLimitState:
    """Rate limit 상태"""
    minute_requests: deque = field(default_factory=lambda: deque(maxlen=1000))
    daily_requests: int = 0
    daily_reset_time: datetime = field(default_factory=datetime.now)
    last_request_time: float = 0.0

    def __post_init__(self):
        self.daily_reset_time = datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)


class RateLimiter:
    """
    통합 Rate Limiter.

    여러 API 소스의 rate limit을 관리합니다.

    Usage:
        limiter = RateLimiter()
        limiter.configure("finnhub", requests_per_minute=60, daily_limit=5000)

        async with limiter.acquire("finnhub"):
            response = await client.fetch_data()
    """

    def __init__(self):
        self._configs: Dict[str, RateLimitConfig] = {}
        self._states: Dict[str, RateLimitState] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    def configure(
        self,
        source: str,
        requests_per_minute: int = 60,
        daily_limit: int = 10000,
        burst_limit: int = 10
    ) -> None:
        """
        소스별 rate limit 설정.

        Args:
            source: 소스 이름 (예: "finnhub", "fred")
            requests_per_minute: 분당 요청 수 제한
            daily_limit: 일일 요청 수 제한
            burst_limit: 버스트 허용 수
        """
        self._configs[source] = RateLimitConfig(
            requests_per_minute=requests_per_minute,
            daily_limit=daily_limit,
            burst_limit=burst_limit,
        )
        self._states[source] = RateLimitState()
        self._locks[source] = asyncio.Lock()

        logger.info(
            f"[RateLimiter] Configured {source}: "
            f"{requests_per_minute}/min, {daily_limit}/day"
        )

    def get_remaining(self, source: str) -> Dict[str, int]:
        """
        남은 요청 수 조회.

        Args:
            source: 소스 이름

        Returns:
            {"minute": remaining_per_minute, "daily": remaining_daily}
        """
        if source not in self._configs:
            return {"minute": 0, "daily": 0}

        config = self._configs[source]
        state = self._states[source]

        # Reset daily counter if new day
        now = datetime.now()
        if now >= state.daily_reset_time:
            state.daily_requests = 0
            state.daily_reset_time = now.replace(
                hour=0, minute=0, second=0, microsecond=0
            ) + timedelta(days=1)

        # Count requests in last minute
        minute_ago = time.time() - 60
        minute_count = sum(1 for t in state.minute_requests if t > minute_ago)

        return {
            "minute": max(0, config.requests_per_minute - minute_count),
            "daily": max(0, config.daily_limit - state.daily_requests),
        }

    def _check_rate_limit(self, source: str) -> Optional[float]:
        """
        Rate limit 확인 및 대기 시간 계산.

        Returns:
            대기 필요 시간 (초), None이면 즉시 요청 가능
        """
        if source not in self._configs:
            # 설정 없으면 기본값으로 자동 설정
            self.configure(source)

        config = self._configs[source]
        state = self._states[source]
        now = time.time()

        # Reset daily counter if new day
        now_dt = datetime.now()
        if now_dt >= state.daily_reset_time:
            state.daily_requests = 0
            state.daily_reset_time = now_dt.replace(
                hour=0, minute=0, second=0, microsecond=0
            ) + timedelta(days=1)

        # Check daily limit
        if state.daily_requests >= config.daily_limit:
            wait_until = state.daily_reset_time
            wait_seconds = (wait_until - now_dt).total_seconds()
            return wait_seconds

        # Clean old minute requests
        minute_ago = now - 60
        while state.minute_requests and state.minute_requests[0] < minute_ago:
            state.minute_requests.popleft()

        # Check minute limit
        if len(state.minute_requests) >= config.requests_per_minute:
            oldest = state.minute_requests[0]
            wait_seconds = oldest + 60 - now + 0.1  # 0.1초 여유
            return max(0, wait_seconds)

        return None

    def _record_request(self, source: str) -> None:
        """요청 기록"""
        state = self._states[source]
        now = time.time()
        state.minute_requests.append(now)
        state.daily_requests += 1
        state.last_request_time = now

    async def wait_if_needed(self, source: str) -> None:
        """
        Rate limit 확인 후 필요시 대기.

        Args:
            source: 소스 이름

        Raises:
            RateLimitExceeded: 일일 한도 초과 시
        """
        if source not in self._locks:
            self._locks[source] = asyncio.Lock()

        async with self._locks[source]:
            wait_seconds = self._check_rate_limit(source)

            if wait_seconds is not None:
                if wait_seconds > 3600:  # 1시간 이상이면 일일 한도
                    raise RateLimitExceeded(source, wait_seconds)

                logger.debug(
                    f"[RateLimiter] {source}: waiting {wait_seconds:.1f}s"
                )
                await asyncio.sleep(wait_seconds)

            self._record_request(source)

    class _AcquireContext:
        """Rate limit acquire context manager"""

        def __init__(self, limiter: "RateLimiter", source: str):
            self.limiter = limiter
            self.source = source

        async def __aenter__(self):
            await self.limiter.wait_if_needed(self.source)
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    def acquire(self, source: str) -> _AcquireContext:
        """
        Rate limit 획득 컨텍스트 매니저.

        Usage:
            async with limiter.acquire("finnhub"):
                response = await client.fetch_data()
        """
        return self._AcquireContext(self, source)


# 글로벌 인스턴스
_global_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """글로벌 Rate Limiter 인스턴스 반환"""
    global _global_limiter
    if _global_limiter is None:
        _global_limiter = RateLimiter()

        # 기본 설정
        _global_limiter.configure("finnhub", requests_per_minute=60, daily_limit=5000)
        _global_limiter.configure("fred", requests_per_minute=120, daily_limit=100000)
        _global_limiter.configure("bok_ecos", requests_per_minute=30, daily_limit=50000)
        _global_limiter.configure("pykrx", requests_per_minute=60, daily_limit=100000)
        _global_limiter.configure("rss", requests_per_minute=30, daily_limit=10000)

    return _global_limiter
