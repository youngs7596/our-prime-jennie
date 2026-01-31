# shared/broker/factory.py
# Version: v1.0
# 브로커 팩토리 클래스

import os
import logging
from enum import Enum
from typing import Optional

from .interface import BrokerClient

logger = logging.getLogger(__name__)


class BrokerType(Enum):
    """지원하는 브로커 타입"""
    KIS = "kis"           # 한국투자증권
    KIWOOM = "kiwoom"     # 키움증권 (미구현)
    TOSS = "toss"         # 토스증권 (미구현)
    UPBIT = "upbit"       # 업비트 (미구현, 암호화폐)


class BrokerFactory:
    """
    브로커 클라이언트 팩토리

    환경변수 또는 명시적 타입으로 적절한 브로커 클라이언트를 생성합니다.

    Usage:
        # 환경변수 기반 (BROKER_TYPE)
        broker = BrokerFactory.create()

        # 명시적 타입 지정
        broker = BrokerFactory.create(BrokerType.KIS)

        # 문자열로도 가능
        broker = BrokerFactory.create("kis")
    """

    # 브로커별 설정
    _BROKER_CONFIGS = {
        BrokerType.KIS: {
            "env_vars": ["KIS_APP_KEY", "KIS_APP_SECRET"],
            "default_gateway": True,
        },
        BrokerType.KIWOOM: {
            "env_vars": ["KIWOOM_ID", "KIWOOM_PASSWORD"],
            "default_gateway": False,
        },
        BrokerType.TOSS: {
            "env_vars": ["TOSS_API_KEY"],
            "default_gateway": False,
        },
        BrokerType.UPBIT: {
            "env_vars": ["UPBIT_ACCESS_KEY", "UPBIT_SECRET_KEY"],
            "default_gateway": False,
        },
    }

    @classmethod
    def create(
        cls,
        broker_type: Optional[BrokerType | str] = None,
        use_gateway: Optional[bool] = None,
        **kwargs
    ) -> BrokerClient:
        """
        브로커 클라이언트 생성

        Args:
            broker_type: 브로커 타입 (기본: 환경변수 BROKER_TYPE, 없으면 "kis")
            use_gateway: Gateway 사용 여부 (기본: 환경변수 USE_KIS_GATEWAY)
            **kwargs: 브로커별 추가 설정

        Returns:
            BrokerClient 인터페이스를 구현하는 클라이언트 인스턴스

        Raises:
            NotImplementedError: 미구현 브로커 타입
            ValueError: 잘못된 브로커 타입
        """
        # 브로커 타입 결정
        if broker_type is None:
            broker_type_str = os.getenv("BROKER_TYPE", "kis").lower()
            try:
                broker_type = BrokerType(broker_type_str)
            except ValueError:
                raise ValueError(
                    f"Unknown broker type: {broker_type_str}. "
                    f"Supported: {[b.value for b in BrokerType]}"
                )
        elif isinstance(broker_type, str):
            try:
                broker_type = BrokerType(broker_type.lower())
            except ValueError:
                raise ValueError(
                    f"Unknown broker type: {broker_type}. "
                    f"Supported: {[b.value for b in BrokerType]}"
                )

        logger.info(f"🏦 Creating broker client: {broker_type.value}")

        # 브로커별 클라이언트 생성
        if broker_type == BrokerType.KIS:
            return cls._create_kis_client(use_gateway=use_gateway, **kwargs)
        elif broker_type == BrokerType.KIWOOM:
            raise NotImplementedError(
                "Kiwoom broker is not yet implemented. "
                "Contributions welcome at shared/broker/kiwoom/adapter.py"
            )
        elif broker_type == BrokerType.TOSS:
            raise NotImplementedError(
                "Toss broker is not yet implemented. "
                "Contributions welcome at shared/broker/toss/adapter.py"
            )
        elif broker_type == BrokerType.UPBIT:
            raise NotImplementedError(
                "Upbit broker is not yet implemented. "
                "Contributions welcome at shared/broker/upbit/adapter.py"
            )
        else:
            raise ValueError(f"Unsupported broker type: {broker_type}")

    @classmethod
    def _create_kis_client(
        cls,
        use_gateway: Optional[bool] = None,
        **kwargs
    ) -> BrokerClient:
        """
        KIS 브로커 클라이언트 생성

        Args:
            use_gateway: Gateway 사용 여부 (기본: 환경변수 USE_KIS_GATEWAY, 없으면 True)

        Returns:
            KISBrokerAdapter 인스턴스
        """
        from .kis.adapter import KISBrokerAdapter

        return KISBrokerAdapter(use_gateway=use_gateway, **kwargs)

    @classmethod
    def get_supported_brokers(cls) -> list[str]:
        """지원하는 브로커 목록 반환"""
        return [b.value for b in BrokerType]

    @classmethod
    def is_implemented(cls, broker_type: BrokerType | str) -> bool:
        """해당 브로커가 구현되었는지 확인"""
        if isinstance(broker_type, str):
            try:
                broker_type = BrokerType(broker_type.lower())
            except ValueError:
                return False

        # 현재는 KIS만 구현됨
        return broker_type == BrokerType.KIS
