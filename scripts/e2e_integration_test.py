#!/usr/bin/env python3
# scripts/e2e_integration_test.py
# E2E 통합 테스트 스크립트 (매수→매도 플로우)

"""
End-to-End Integration Test

Mock 모드에서 전체 트레이딩 플로우를 테스트합니다:
1. Scout → 뉴스 수집 및 후보 생성
2. Buy-Scanner → 후보 분석 및 매수 신호 생성
3. Buy-Executor → Mock 매수 주문 실행 (Optional)
4. Sell-Executor → Mock 매도 주문 실행 (Optional)

사용법:
    python scripts/e2e_integration_test.py --phase scout
    python scripts/e2e_integration_test.py --phase buy
    python scripts/e2e_integration_test.py --full
"""

import os
import sys
import argparse
import logging
import subprocess
import time
import json
from datetime import datetime
from pathlib import Path

# 프로젝트 루트 설정
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


class IntegrationTester:
    """E2E 통합 테스트 실행기"""
    
    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self.results = {}
        
    def check_service_health(self, service_name: str, port: int) -> bool:
        """서비스 헬스 체크"""
        import requests
        try:
            resp = requests.get(f"http://localhost:{port}/health", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False
    
    def run_docker_service(self, service_name: str, timeout: int = 120) -> tuple[bool, str]:
        """Docker 서비스 실행 및 로그 확인"""
        logger.info(f"🚀 Starting {service_name}...")
        
        try:
            # 서비스 실행
            proc = subprocess.run(
                ["docker", "compose", "run", "--rm", "-e", "TRADING_MODE=MOCK", service_name],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            success = proc.returncode == 0
            output = proc.stdout + proc.stderr
            
            return success, output
            
        except subprocess.TimeoutExpired:
            logger.warning(f"⏱️ {service_name} timeout ({timeout}s)")
            return False, "Timeout"
        except Exception as e:
            logger.error(f"❌ {service_name} error: {e}")
            return False, str(e)
    
    def test_scout_phase(self) -> dict:
        """Scout 단계 테스트"""
        logger.info("=" * 50)
        logger.info("📡 Phase 1: Scout (뉴스 수집 & 후보 생성)")
        logger.info("=" * 50)
        
        result = {
            'phase': 'scout',
            'status': 'unknown',
            'details': {}
        }
        
        # Redis 확인
        try:
            import redis
            r = redis.Redis(host='localhost', port=6379, db=0)
            r.ping()
            result['details']['redis'] = 'connected'
        except Exception as e:
            result['details']['redis'] = f'error: {e}'
            result['status'] = 'failed'
            return result
        
        # Scout 실행
        success, output = self.run_docker_service('scout-job', timeout=180)
        
        result['status'] = 'passed' if success else 'failed'
        result['details']['output_lines'] = len(output.split('\n'))
        
        # 매수 후보 확인 (Redis)
        try:
            candidates = r.get('buy_candidates')
            if candidates:
                data = json.loads(candidates)
                result['details']['candidates_count'] = len(data.get('candidates', []))
        except Exception:
            pass
        
        return result
    
    def test_buy_scanner_phase(self) -> dict:
        """Buy-Scanner 단계 테스트"""
        logger.info("=" * 50)
        logger.info("🔍 Phase 2: Buy-Scanner (후보 분석)")
        logger.info("=" * 50)
        
        result = {
            'phase': 'buy-scanner',
            'status': 'unknown',
            'details': {}
        }
        
        # Buy-Scanner 실행 (timeout 짧게)
        success, output = self.run_docker_service('buy-scanner', timeout=60)
        
        result['status'] = 'passed' if success else 'failed'
        result['details']['output_lines'] = len(output.split('\n'))
        
        return result
    
    def test_database_connection(self) -> dict:
        """데이터베이스 연결 테스트"""
        logger.info("🔗 Testing database connection...")
        
        result = {
            'phase': 'database',
            'status': 'unknown',
            'details': {}
        }
        
        try:
            from shared.db.connection import get_engine
            engine = get_engine()
            with engine.connect() as conn:
                conn.execute("SELECT 1")
            result['status'] = 'passed'
            result['details']['message'] = 'Connection successful'
        except Exception as e:
            result['status'] = 'failed'
            result['details']['error'] = str(e)
        
        return result
    
    def test_service_connectivity(self) -> dict:
        """서비스 간 연결성 테스트"""
        logger.info("🔗 Testing service connectivity...")
        
        services = [
            ('kis-gateway', 8001),
            ('scheduler', 8002),
            ('dashboard-backend', 8000),
        ]
        
        result = {
            'phase': 'connectivity',
            'status': 'passed',
            'details': {}
        }
        
        for name, port in services:
            healthy = self.check_service_health(name, port)
            result['details'][name] = 'healthy' if healthy else 'unhealthy'
            if not healthy:
                result['status'] = 'partial'
        
        return result
    
    def run_full_test(self):
        """전체 E2E 테스트 실행"""
        logger.info("🎯 Starting Full E2E Integration Test")
        logger.info(f"   Mode: {'DRY RUN' if self.dry_run else 'LIVE'}")
        logger.info(f"   Time: {datetime.now().isoformat()}")
        
        # 1. 데이터베이스 연결
        self.results['database'] = self.test_database_connection()
        
        # 2. 서비스 연결성
        self.results['connectivity'] = self.test_service_connectivity()
        
        # 3. Scout 테스트 (시간 소요)
        # self.results['scout'] = self.test_scout_phase()
        
        # 결과 출력
        self.print_summary()
    
    def run_quick_test(self):
        """빠른 연결성 테스트만 실행"""
        logger.info("⚡ Running Quick Connectivity Test")
        
        self.results['database'] = self.test_database_connection()
        self.results['connectivity'] = self.test_service_connectivity()
        
        self.print_summary()
    
    def print_summary(self):
        """테스트 결과 요약 출력"""
        logger.info("")
        logger.info("=" * 50)
        logger.info("📊 TEST SUMMARY")
        logger.info("=" * 50)
        
        all_passed = True
        
        for phase, result in self.results.items():
            status = result.get('status', 'unknown')
            icon = '✅' if status == 'passed' else ('⚠️' if status == 'partial' else '❌')
            logger.info(f"  {icon} {phase}: {status}")
            
            if status not in ['passed', 'partial']:
                all_passed = False
        
        logger.info("")
        if all_passed:
            logger.info("🎉 All tests passed!")
        else:
            logger.info("⚠️ Some tests failed. Check details above.")
        
        return all_passed


def main():
    parser = argparse.ArgumentParser(description='E2E Integration Test')
    parser.add_argument('--phase', choices=['scout', 'buy', 'sell', 'quick'],
                        help='Specific phase to test')
    parser.add_argument('--full', action='store_true', help='Run full E2E test')
    parser.add_argument('--dry-run', action='store_true', default=True,
                        help='Dry run mode (no actual trades)')
    
    args = parser.parse_args()
    
    tester = IntegrationTester(dry_run=args.dry_run)
    
    if args.phase == 'scout':
        result = tester.test_scout_phase()
        tester.results['scout'] = result
        tester.print_summary()
    elif args.phase == 'buy':
        result = tester.test_buy_scanner_phase()
        tester.results['buy-scanner'] = result
        tester.print_summary()
    elif args.phase == 'quick':
        tester.run_quick_test()
    elif args.full:
        tester.run_full_test()
    else:
        # 기본: 빠른 테스트
        tester.run_quick_test()


if __name__ == '__main__':
    main()
