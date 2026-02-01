#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shared/macro_data/clients/base.py
---------------------------------
매크로 데이터 클라이언트 기본 인터페이스 (Protocol 기반).
"""

from abc import abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Protocol, Tuple, runtime_checkable

from ..models import MacroDataPoint


@runtime_checkable
class MacroDataClient(Protocol):
    """
    매크로 데이터 클라이언트 Protocol.

    모든 데이터 소스 클라이언트는 이 프로토콜을 구현해야 합니다.
    """

    @abstractmethod
    async def fetch_data(
        self,
        indicators: Optional[List[str]] = None
    ) -> List[MacroDataPoint]:
        """
        지표 데이터를 가져옵니다.

        Args:
            indicators: 가져올 지표 목록 (None이면 기본 지표 전체)

        Returns:
            MacroDataPoint 리스트
        """
        ...

    @abstractmethod
    def get_rate_limit(self) -> Tuple[int, int]:
        """
        Rate limit 정보를 반환합니다.

        Returns:
            (requests_per_minute, daily_limit) 튜플
        """
        ...

    @abstractmethod
    def get_source_name(self) -> str:
        """
        데이터 소스 이름을 반환합니다.

        Returns:
            소스 이름 (예: "finnhub", "fred", "bok_ecos")
        """
        ...

    def get_default_indicators(self) -> List[str]:
        """
        기본 지표 목록을 반환합니다.

        Returns:
            기본 지표 이름 리스트
        """
        return []

    def is_available(self) -> bool:
        """
        클라이언트 사용 가능 여부를 확인합니다.
        (API 키 유효성 등)

        Returns:
            사용 가능 여부
        """
        return True


@dataclass
class ClientConfig:
    """API 클라이언트 설정"""
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    timeout: int = 30
    max_retries: int = 3
    retry_delay: float = 1.0
