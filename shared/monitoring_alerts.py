# shared/monitoring_alerts.py
# 모니터링 알림 헬퍼 모듈

"""
Monitoring Alerts

시스템 상태 변화에 따른 알림을 Telegram으로 전송합니다:
- Circuit Breaker 상태 변화
- Fact-Checker 환각 경고
- 시스템 에러/경고
"""

import logging
from typing import Optional
from functools import wraps

logger = logging.getLogger(__name__)


class MonitoringAlerts:
    """운영 모니터링 알림 관리자"""
    
    # 알림 아이콘
    ICONS = {
        'circuit_open': '🔴',
        'circuit_closed': '🟢', 
        'circuit_half_open': '🟡',
        'hallucination': '👻',
        'warning': '⚠️',
        'error': '❌',
        'info': 'ℹ️',
    }
    
    def __init__(self, telegram_bot=None):
        """
        Args:
            telegram_bot: TelegramBot 인스턴스 (None이면 로깅만)
        """
        self.telegram = telegram_bot
    
    def _send(self, message: str) -> bool:
        """알림 전송"""
        logger.info(f"[ALERT] {message}")
        
        if self.telegram:
            try:
                return self.telegram.send_message(message)
            except Exception as e:
                logger.error(f"Telegram 전송 실패: {e}")
                return False
        return True
    
    def notify_circuit_breaker_state(
        self,
        breaker_name: str,
        new_state: str,
        failure_count: int = 0,
        next_retry: float = 0.0
    ):
        """Circuit Breaker 상태 변화 알림"""
        icon = self.ICONS.get(f'circuit_{new_state.lower()}', '🔄')
        
        if new_state == 'OPEN':
            message = (
                f"{icon} **Circuit Breaker OPEN**\n"
                f"• 서비스: {breaker_name}\n"
                f"• 연속 실패: {failure_count}회\n"
                f"• 재시도: {next_retry:.0f}초 후"
            )
        elif new_state == 'HALF_OPEN':
            message = (
                f"{icon} **Circuit Breaker 복구 테스트**\n"
                f"• 서비스: {breaker_name}\n"
                f"• 상태: 복구 시도 중..."
            )
        elif new_state == 'CLOSED':
            message = (
                f"{icon} **Circuit Breaker 정상 복구**\n"
                f"• 서비스: {breaker_name}\n"
                f"• 상태: 정상 운영"
            )
        else:
            return
        
        self._send(message)
    
    def notify_hallucination_detected(
        self,
        stock_name: str,
        confidence: float,
        warnings: list
    ):
        """환각 탐지 알림"""
        icon = self.ICONS['hallucination']
        
        warning_text = "\n".join([f"  • {w}" for w in warnings[:3]])
        
        message = (
            f"{icon} **LLM 환각 경고**\n"
            f"• 종목: {stock_name}\n"
            f"• 신뢰도: {confidence:.0%}\n"
            f"• 경고:\n{warning_text}"
        )
        
        self._send(message)
    
    def notify_system_error(self, service: str, error: str, details: str = ""):
        """시스템 에러 알림"""
        icon = self.ICONS['error']
        
        message = f"{icon} **시스템 에러**\n• 서비스: {service}\n• 에러: {error}"
        if details:
            message += f"\n• 상세: {details[:100]}"
        
        self._send(message)
    
    def notify_system_warning(self, message: str):
        """시스템 경고 알림"""
        icon = self.ICONS['warning']
        self._send(f"{icon} {message}")


# 싱글톤 인스턴스
_monitoring_alerts: Optional[MonitoringAlerts] = None


def get_monitoring_alerts(telegram_bot=None) -> MonitoringAlerts:
    """MonitoringAlerts 싱글톤"""
    global _monitoring_alerts
    if _monitoring_alerts is None:
        _monitoring_alerts = MonitoringAlerts(telegram_bot)
    return _monitoring_alerts


def init_monitoring_alerts(telegram_bot) -> MonitoringAlerts:
    """외부 TelegramBot으로 모니터링 알림 초기화"""
    global _monitoring_alerts
    _monitoring_alerts = MonitoringAlerts(telegram_bot)
    return _monitoring_alerts
