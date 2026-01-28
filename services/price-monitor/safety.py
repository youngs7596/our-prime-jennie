# services/price-monitor/safety.py
from datetime import datetime, time
import logging

logger = logging.getLogger(__name__)

class GapDownSafety:
    """
    시장 시초가 급락(Gap Down) 시, 투매 방지를 위한 안전장치
    """
    def __init__(self, config):
        self.config = config
        # 기본 5분 대기 (09:00:00 ~ 09:05:00)
        self.wait_minutes = config.get_int('GAP_DOWN_WAIT_MINUTES', default=5)
        # 갭락 기준: -5% 이하로 시작하면 발동
        self.gap_down_threshold = config.get_float('GAP_DOWN_THRESHOLD_PCT', default=-5.0)
        # 하드 스탑: -10% 이하면 시간 상관없이 즉시 매도 (안전장치 무시)
        self.hard_stop_threshold = config.get_float('GAP_DOWN_HARD_STOP_PCT', default=-10.0)

    def check_safety(self, current_time: datetime, profit_pct: float) -> dict:
        """
        매도 신호 실행 전 안전 여부를 확인
        Returns:
            {
                'is_safe': bool,  # True=매도진행, False=매도보류
                'reason': str     # 보류 사유
            }
        """
        # 1. 하드 스탑 체크 (-10% 이하 폭락 시 무조건 매도 허용)
        if profit_pct <= self.hard_stop_threshold:
             return {'is_safe': True, 'reason': f"Hard Stop Triggered ({profit_pct:.1f}% <= {self.hard_stop_threshold}%)"}

        # 2. 시간 체크 (09:00 ~ 09:05)
        # KST 기준으로 09시 장 시작 직후인지 확인해야 함.
        # monitor.py에서 넘겨주는 current_time은 보통 시스템 시간(KST)임.
        if not (current_time.hour == 9 and current_time.minute < self.wait_minutes):
            return {'is_safe': True, 'reason': "Outside Safety Window"}

        # 3. 갭락 여부 체크 (현재 수익률이 임계값보다 낮으면 갭락으로 간주)
        # 시초가가 이미 -5% 밑에서 놀고 있다면 발동
        if profit_pct <= self.gap_down_threshold:
            # 안전장치 발동 (매도 보류)
            wait_limit_str = f"09:{self.wait_minutes:02d}"
            msg = f"📉 Gap Down Safety Active ({profit_pct:.1f}%). Waiting until {wait_limit_str} for stabilization."
            return {'is_safe': False, 'reason': msg}

        return {'is_safe': True, 'reason': "Normal Condition"}
