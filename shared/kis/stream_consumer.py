"""
shared/kis/stream_consumer.py
=============================
Redis Streams 기반 실시간 가격 소비자.

kis-gateway가 발행하는 Redis Stream에서 가격 데이터를 소비합니다.
Consumer Group을 사용하여 메시지 손실 없이 안정적으로 처리합니다.
"""

import os
import time
import json
import logging
import threading
from typing import Callable, Optional

import redis

logger = logging.getLogger(__name__)

# Redis Stream 설정
STREAM_NAME = "kis:prices"
DEFAULT_CONSUMER_GROUP = "price-consumers"
BLOCK_MS = 5000  # 5초 블로킹 읽기


class StreamPriceConsumer:
    """
    Redis Streams 기반 가격 데이터 소비자.
    
    사용 예시:
        consumer = StreamPriceConsumer(redis_url="redis://localhost:6379")
        consumer.start_consuming(
            on_price_func=my_callback,
            consumer_group="buy-scanner-group",
            consumer_name="scanner-1"
        )
    """
    
    def __init__(self, redis_url: str = None):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")
        self.redis_client: Optional[redis.Redis] = None
        self.is_running = False
        self.consumer_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
    def _ensure_connection(self):
        """Redis 연결 확인 및 생성"""
        if self.redis_client is None:
            self.redis_client = redis.from_url(self.redis_url, decode_responses=True)
            logger.info(f"   (Stream) Redis 연결 완료: {self.redis_url}")
    
    def _ensure_consumer_group(self, group_name: str):
        """Consumer Group 생성 (없으면)"""
        try:
            self.redis_client.xgroup_create(
                STREAM_NAME, 
                group_name, 
                id="0",  # 처음부터 읽기
                mkstream=True  # 스트림이 없으면 생성
            )
            logger.info(f"   (Stream) Consumer Group 생성: {group_name}")
        except redis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                # 이미 존재하는 그룹 - 정상
                logger.debug(f"   (Stream) Consumer Group 이미 존재: {group_name}")
            else:
                raise
    
    def request_subscription(self, codes: list, gateway_url: str = None):
        """
        kis-gateway에 구독 요청을 보냅니다.
        
        Args:
            codes: 구독할 종목 코드 리스트
            gateway_url: Gateway URL (기본: http://127.0.0.1:8080)
        """
        import requests
        
        gateway_url = gateway_url or os.getenv("KIS_GATEWAY_URL", "http://127.0.0.1:8080")
        endpoint = f"{gateway_url}/api/realtime/subscribe"
        
        try:
            response = requests.post(
                endpoint,
                json={"codes": codes},
                timeout=10
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"   (Stream) 구독 요청 완료: {len(codes)}개 종목 -> Gateway")
            return result
        except Exception as e:
            logger.error(f"   (Stream) 구독 요청 실패: {e}")
            return None
    
    def start_consuming(
        self,
        on_price_func: Callable[[str, float, float], None],
        consumer_group: str = DEFAULT_CONSUMER_GROUP,
        consumer_name: str = None,
        codes_to_subscribe: list = None,
        gateway_url: str = None
    ):
        """
        Redis Stream에서 가격 데이터 소비 시작.
        
        Args:
            on_price_func: 가격 업데이트 콜백 (code, price, high)
            consumer_group: Consumer Group 이름
            consumer_name: Consumer 이름 (기본: hostname + pid)
            codes_to_subscribe: 구독할 종목 코드 (선택)
            gateway_url: Gateway URL (구독 요청용)
        """
        if self.is_running:
            logger.warning("   (Stream) 이미 소비 중입니다.")
            return
        
        self._ensure_connection()
        self._ensure_consumer_group(consumer_group)
        
        # 구독 요청 (선택)
        if codes_to_subscribe:
            self.request_subscription(codes_to_subscribe, gateway_url)
        
        consumer_name = consumer_name or f"{os.uname().nodename}-{os.getpid()}"
        
        self._stop_event.clear()
        self.is_running = True
        
        def consume_loop():
            logger.info(f"   (Stream) 소비자 시작: group={consumer_group}, name={consumer_name}")
            
            while not self._stop_event.is_set():
                try:
                    # XREADGROUP으로 블로킹 읽기
                    messages = self.redis_client.xreadgroup(
                        groupname=consumer_group,
                        consumername=consumer_name,
                        streams={STREAM_NAME: ">"},  # 새 메시지만
                        count=100,
                        block=BLOCK_MS
                    )
                    
                    if not messages:
                        continue
                    
                    for stream_name, entries in messages:
                        for msg_id, data in entries:
                            try:
                                code = data.get("code")
                                price = float(data.get("price", 0))
                                high = float(data.get("high", price))
                                
                                if code and price > 0:
                                    on_price_func(code, price, high)
                                
                                # ACK 처리
                                self.redis_client.xack(STREAM_NAME, consumer_group, msg_id)
                                
                            except Exception as e:
                                logger.error(f"   (Stream) 메시지 처리 오류: {e}")
                                
                except redis.ConnectionError as e:
                    logger.error(f"   (Stream) Redis 연결 끊김: {e}")
                    time.sleep(5)
                    self._ensure_connection()
                    
                except Exception as e:
                    logger.error(f"   (Stream) 소비 루프 오류: {e}")
                    time.sleep(1)
            
            logger.info("   (Stream) 소비자 종료")
            self.is_running = False
        
        self.consumer_thread = threading.Thread(target=consume_loop, daemon=True)
        self.consumer_thread.start()
        
        return self.consumer_thread
    
    def stop(self):
        """소비 중지"""
        logger.info("   (Stream) 소비 중지 요청")
        self._stop_event.set()
        
        if self.consumer_thread and self.consumer_thread.is_alive():
            self.consumer_thread.join(timeout=10)
        
        self.is_running = False
    
    def is_connected(self) -> bool:
        """연결 상태 확인"""
        return self.is_running and self.redis_client is not None
