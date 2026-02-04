# youngs75_jennie/kis/gateway_client.py
# Version: v3.5
# KIS Gateway Client - KIS API 호출을 Gateway를 통해 수행

import os
import logging
import requests
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class KISGatewayClient:
    """
    KIS Gateway를 통해 KIS API를 호출하는 클라이언트
    
    Gateway를 사용하면:
    - Rate Limiting 자동 관리
    - Circuit Breaker 보호
    - 중앙화된 모니터링
    - 토큰 관리 불필요
    """
    
    def __init__(self, gateway_url: Optional[str] = None, timeout: int = 30):
        """
        Args:
            gateway_url: Gateway URL (기본: 환경 변수에서 읽기)
            timeout: 요청 타임아웃 (초)
        """
        self.gateway_url = gateway_url or os.getenv(
            'KIS_GATEWAY_URL',
            'http://127.0.0.1:8080'
        )
        self.timeout = timeout
        self.session = requests.Session()
        
        # Cloud Run 인증 토큰 (로컬에서는 gcloud 인증 사용)
        self.use_auth = os.getenv('USE_GATEWAY_AUTH', 'true').lower() == 'true'
        
        # Rate Limit 방지를 위한 클라이언트 측 딜레이
        # KIS 실전 가이드: 초당 20건 -> 안전하게 0.1s (10req/sec)
        # KIS 모의 가이드: 초당 2건 -> 0.6s
        trading_mode = os.getenv("TRADING_MODE", "REAL")
        self.API_CALL_DELAY = 0.1 if trading_mode == "REAL" else 0.6
        
        logger.info(f"✅ KIS Gateway Client 초기화: {self.gateway_url}")
    
    def _get_auth_token(self) -> Optional[str]:
        """Cloud Run 인증 토큰 획득 (서비스 간 통신)"""
        if not self.use_auth:
            return None
        
        try:
            # Cloud Run 내부에서는 Metadata Server에서 토큰 획득
            metadata_url = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity"
            params = {'audience': self.gateway_url}
            headers = {'Metadata-Flavor': 'Google'}
            
            response = requests.get(
                metadata_url,
                params=params,
                headers=headers,
                timeout=5
            )
            
            if response.status_code == 200:
                return response.text
            else:
                # Cloud Run 외부(로컬)에서는 실패하는 것이 정상입니다.
                logger.debug(f"Metadata Server 토큰 획득 실패 (로컬 환경 예상): {response.status_code}")
                return None
        except Exception:
            # 로컬 환경에서는 NameResolutionError 등이 발생하며, 이는 예상된 동작입니다.
            return None
    
    def _request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
        """
        Gateway에 HTTP 요청 전송
        
        Args:
            method: HTTP 메서드 (GET, POST)
            endpoint: API 엔드포인트
            data: 요청 데이터
            
        Returns:
            응답 데이터 또는 None
        """
        url = f"{self.gateway_url}{endpoint}"
        headers = {'Content-Type': 'application/json'}
        
        # 인증 토큰 추가
        if self.use_auth:
            token = self._get_auth_token()
            if token:
                headers['Authorization'] = f'Bearer {token}'
        
        try:
            if method == 'GET':
                response = self.session.get(url, headers=headers, timeout=self.timeout)
            elif method == 'POST':
                response = self.session.post(url, headers=headers, json=data, timeout=self.timeout)
            else:
                raise ValueError(f"Unsupported method: {method}")
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.Timeout:
            logger.error(f"❌ Gateway 타임아웃: {url}")
            return None
        except requests.exceptions.HTTPError as e:
            logger.error(f"❌ Gateway HTTP 오류: {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"❌ Gateway 요청 실패: {e}")
            return None
        finally:
            # Rate Limiting: 다음 요청까지 대기
            if hasattr(self, 'API_CALL_DELAY'):
                import time
                time.sleep(self.API_CALL_DELAY)
    
    def get_stock_snapshot(self, stock_code: str, is_index: bool = False) -> Optional[Dict[str, Any]]:
        """
        주식 현재가 조회 (Gateway를 통해)
        
        Args:
            stock_code: 종목 코드
            is_index: 지수 여부
            
        Returns:
            현재가 정보 또는 None
        """
        logger.debug(f"📊 [Gateway] Snapshot 요청: {stock_code}")
        
        response = self._request('POST', '/api/market-data/snapshot', {
            'stock_code': stock_code,
            'is_index': is_index
        })
        
        if response and response.get('success'):
            return response.get('data')
        else:
            logger.error(f"❌ Snapshot 조회 실패: {stock_code}")
            return None
    
    def check_market_open(self) -> bool:
        """
        오늘이 장 운영일(거래 가능일)인지 확인 (Gateway를 통해)
        
        Returns:
            True: 장 운영일 (평일 & 비휴일)
            False: 휴장일 (주말 또는 공휴일)
        """
        logger.debug(f"📅 [Gateway] Market Open Check 요청")
        
        # Endpoint 가칭: /api/market-data/check-market-open
        response = self._request('GET', '/api/market-data/check-market-open')
        
        if response and response.get('success'):
            is_open = response.get('data', {}).get('is_open', False)
            logger.info(f"   (Gateway) Market Open: {is_open}")
            return is_open
        else:
            logger.warning(f"⚠️ [Gateway] 휴장일 확인 실패 (기본값 False 반환)")
            return False
    
    def place_buy_order(self, stock_code: str, quantity: int, price: int = 0) -> Optional[str]:
        """
        매수 주문 (Gateway를 통해)
        
        Args:
            stock_code: 종목 코드
            quantity: 수량
            price: 가격 (0이면 시장가)
            
        Returns:
            주문번호 또는 None
        """
        logger.info(f"💰 [Gateway] 매수 주문: {stock_code} x {quantity}주")
        
        response = self._request('POST', '/api/trading/buy', {
            'stock_code': stock_code,
            'quantity': quantity,
            'price': price
        })
        
        if response and response.get('success'):
            order_no = response.get('order_no')
            logger.info(f"✅ 매수 주문 성공: {order_no}")
            return order_no
        else:
            logger.error(f"❌ 매수 주문 실패: {stock_code}")
            return None
    
    def place_sell_order(self, stock_code: str, quantity: int, price: int = 0) -> Optional[str]:
        """
        매도 주문 (Gateway를 통해)
        
        Args:
            stock_code: 종목 코드
            quantity: 수량
            price: 가격 (0이면 시장가)
            
        Returns:
            주문번호 또는 None
        """
        logger.info(f"💸 [Gateway] 매도 주문: {stock_code} x {quantity}주")
        
        response = self._request('POST', '/api/trading/sell', {
            'stock_code': stock_code,
            'quantity': quantity,
            'price': price
        })
        
        if response and response.get('success'):
            order_no = response.get('order_no')
            logger.info(f"✅ 매도 주문 성공: {order_no}")
            return order_no
        else:
            logger.error(f"❌ 매도 주문 실패: {stock_code}")
            return None
    
    def get_stock_daily_prices(self, stock_code: str, num_days_to_fetch: int = 30) -> Optional[Any]:
        """
        일봉 데이터 조회 (Gateway를 통해)
        
        Args:
            stock_code: 종목 코드
            num_days_to_fetch: 조회할 일수
            
        Returns:
            일봉 데이터 (DataFrame 형태의 dict) 또는 None
        """
        logger.debug(f"📈 [Gateway] Daily Prices 요청: {stock_code} ({num_days_to_fetch}일)")
        
        response = self._request('POST', '/api/market-data/daily-prices', {
            'stock_code': stock_code,
            'num_days_to_fetch': num_days_to_fetch
        })
        
        if response and response.get('success'):
            data = response.get('data')
            # DataFrame으로 변환 (원본 KISClient와 호환성 유지)
            try:
                import pandas as pd
                return pd.DataFrame(data) if isinstance(data, list) else data
            except ImportError:
                return data
        else:
            logger.error(f"❌ Daily Prices 조회 실패: {stock_code}")
            return None
    
    def get_stock_minute_chart(self, stock_code: str, target_date: str = None, minute_interval: int = 5) -> Optional[list]:
        """
        분봉 차트 데이터 조회 (Gateway를 통해)
        
        Args:
            stock_code: 종목 코드
            target_date: 조회 날짜 (YYYYMMDD, None이면 오늘)
            minute_interval: 분봉 주기 (기본 5분)
            
        Returns:
            분봉 데이터 리스트 (dict list) 또는 None
        """
        logger.debug(f"📈 [Gateway] Minute Chart 요청: {stock_code} ({minute_interval}분)")
        
        response = self._request('POST', '/api/market-data/minute-chart', {
            'stock_code': stock_code,
            'target_date': target_date,
            'minute_interval': minute_interval
        })
        
        if response and response.get('success'):
            return response.get('data')
        else:
            logger.error(f"❌ Minute Chart 조회 실패: {stock_code}")
            return None
    
    def get_account_balance(self) -> Optional[Dict[str, Any]]:
        """
        계좌 잔고 조회 (Gateway를 통해)
        
        Returns:
            계좌 잔고 정보 또는 None
        """
        logger.debug(f"💰 [Gateway] Account Balance 요청")
        
        response = self._request('POST', '/api/account/balance', {})
        
        if response and response.get('success'):
            return response.get('data')
        else:
            logger.error(f"❌ Account Balance 조회 실패")
            return None
    
    def get_cash_balance(self) -> float:
        """
        현금 잔고 조회 (Gateway를 통해)
        
        Returns:
            현금 잔고 (원)
        """
        logger.debug(f"💰 [Gateway] Cash Balance 요청")
        
        response = self._request('POST', '/api/account/cash-balance', {})
        
        if response and response.get('success'):
            return float(response.get('data', 0.0))
        else:
            logger.error(f"❌ Cash Balance 조회 실패")
            return 0.0
    
    def get_health(self) -> Optional[Dict[str, Any]]:
        """Gateway Health Check"""
        return self._request('GET', '/health')
    
    def get_stats(self) -> Optional[Dict[str, Any]]:
        """Gateway 통계 조회"""
        return self._request('GET', '/stats')

    def get_market_data(self):
        """
        MarketData 모듈 프록시 반환
        Existing code calls: kis_api.get_market_data().get_investor_trend(...)
        """
        return GatewayMarketData(self)


class GatewayMarketData:
    """KISGatewayClient용 MarketData 프록시 클래스"""
    
    def __init__(self, gateway_client):
        self.client = gateway_client
        
    def get_investor_trend(self, stock_code: str, start_date: str = None, end_date: str = None):
        """
        투자자별 매매동향 조회 (Gateway 프록시)
        """
        logger.debug(f"📊 [GatewayClient] Investor Trend 요청: {stock_code}")
        
        payload = {
            'stock_code': stock_code,
            'start_date': start_date,
            'end_date': end_date
        }
        
        response = self.client._request('POST', '/api/market-data/investor-trend', payload)
        
        if response and response.get('success'):
            return response.get('data')
        else:
            logger.error(f"❌ Investor Trend 조회 실패: {stock_code}")
            return None

