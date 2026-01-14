
import os
import json
import logging
import time
import redis
from datetime import datetime, timezone
import traceback
from typing import List, Dict, Optional

from shared.db.connection import get_engine, session_scope
from shared.kis.client import KISClient

logger = logging.getLogger(__name__)

class SystemDiagnoser:
    """시스템 상태 진단 및 리포트 생성 클래스"""
    
    def __init__(self, kis_client: Optional[KISClient] = None):
        self.kis_client = kis_client
        self.redis_url = os.getenv("RABBITMQ_URL", "redis://localhost:6379/0").replace("amqp://", "redis://").replace("5672", "6379")
        # Redis URL이 amqp로 잘못 설정되는 경우 방지 (환경 변수 혼용 시)
        # 실제 Redis URL 환경변수가 있으면 그것 사용
        if os.getenv("REDIS_URL"):
            self.redis_url = os.getenv("REDIS_URL")
        elif "redis" not in self.redis_url:
             self.redis_url = "redis://localhost:6379/0"

    def run_diagnostics(self) -> str:
        """전체 시스템 진단 실행 및 리포트 생성"""
        report_lines = [
            f"🏥 *시스템 자가 진단 리포트*",
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "✅ *Infrastructure Check*"
        ]
        
        # 1. Redis Check
        redis_status = self._check_redis()
        report_lines.append(f"- Redis: {redis_status}")
        
        # 2. DB Check
        db_status = self._check_db()
        report_lines.append(f"- Database: {db_status}")
        
        # 3. KIS API Check
        kis_status = self._check_kis()
        report_lines.append(f"- KIS API: {kis_status}")
        
        # 4. Recent Incidents
        report_lines.append("")
        report_lines.append("🚨 *Recent Incidents (Last 3)*")
        incidents = self._get_recent_incidents(limit=3)
        if incidents:
            for i, inc in enumerate(incidents, 1):
                report_lines.append(f"{i}. {inc}")
        else:
            report_lines.append("No recent critical incidents found. 👍")
            
        report_lines.append("")
        report_lines.append("💡 *Action*: 이 리포트를 복사하여 AI(Jennie)에게 전달하면 원인 분석 및 수정이 가능합니다.")
        
        return "\n".join(report_lines)

    def _check_redis(self) -> str:
        try:
            r = redis.from_url(self.redis_url, socket_timeout=2)
            start = time.time()
            if r.ping():
                latency = (time.time() - start) * 1000
                return f"OK ({latency:.1f}ms)"
            return "FAIL (Ping response false)"
        except Exception as e:
            return f"ERROR ({str(e)})"

    def _check_db(self) -> str:
        try:
            # 엔진 가져오기 (연결 풀 테스트)
            with session_scope(readonly=True) as session:
                session.execute("SELECT 1")
            return "OK"
        except Exception as e:
            return f"ERROR ({str(e)})"

    def _check_kis(self) -> str:
        if not self.kis_client:
            return "N/A (Client not provided)"
        
        try:
            # 간단한 잔고 조회나 시세 조회로 토큰 유효성 검증
            # 여기서는 API 호출 비용 최소화를 위해 객체 상태만 확인하거나,
            # 실제 호출이 필요하다면 가장 가벼운 API 호출
            if hasattr(self.kis_client, 'access_token') and self.kis_client.access_token:
                 return "OK (Token Present)"
            return "WARNING (No Token)"
        except Exception as e:
            return f"ERROR ({str(e)})"

    def _get_recent_incidents(self, limit: int = 3) -> List[str]:
        log_path = os.path.join(os.getcwd(), "logs/incidents.jsonl")
        if not os.path.exists(log_path):
            return ["Log file not found."]
        
        results = []
        try:
            # 파일 끝에서부터 읽기 위해 전체를 읽는 것은 비효율적이나, 로그 파일이 아주 크지 않다고 가정
            # 효율적으로 개선하려면 seek 사용 필요. 여기서는 간단히 구현.
            with open(log_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
            last_lines = lines[-limit:]
            
            for line in reversed(last_lines):
                try:
                    data = json.loads(line)
                    meta = data.get('meta', {})
                    details = data.get('error_details', {})
                    
                    ts = meta.get('timestamp', '').split('.')[0].replace('T', ' ')
                    err_type = details.get('error_type', 'Unknown')
                    msg = details.get('message', '')
                    file = os.path.basename(details.get('file_path', ''))
                    line_no = details.get('line_number', '?')
                    
                    summary = f"[{err_type}] {msg}\n   └ {file}:{line_no} ({ts})"
                    results.append(summary)
                except json.JSONDecodeError:
                    continue
                    
        except Exception as e:
            logger.error(f"Error parsing incidents: {e}")
            results.append(f"Failed to parse logs: {e}")
            
        return results
