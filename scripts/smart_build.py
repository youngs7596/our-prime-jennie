#!/usr/bin/env python3
"""
scripts/smart_build.py - Jenkins Smart Build Script
===================================================

Git 변경 사항을 기반으로 필요한 서비스만 선별적으로 빌드/배포합니다.

사용법:
    python3 scripts/smart_build.py --action build --commit-range HEAD~1..HEAD
    python3 scripts/smart_build.py --action deploy

기능:
1. `git diff`로 변경된 파일 목록 추출
2. 파일 경로와 서비스 매핑 확인
3. 변경된 서비스만 `docker compose build` 및 `up` 실행
4. `shared/`나 공통 설정 변경 시 전체 빌드
"""

import os
import sys
import subprocess
import argparse
import logging
from typing import List, Set, Dict

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("smart-build")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 설정: 파일 경로 -> 서비스 매핑
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 서비스 별 경로 매핑 (디렉토리 prefix 기준)
SERVICE_MAP = {
    "services/scout-job": ["scout-job", "scout-worker"],
    "services/buy-scanner": ["buy-scanner"],
    "services/buy-executor": ["buy-executor"],
    "services/sell-executor": ["sell-executor"],
    "services/price-monitor": ["price-monitor"],
    "services/kis-gateway": ["kis-gateway"],
    "services/news-archiver": ["news-archiver"],
    "services/news-collector": ["news-collector"],
    "services/news-analyzer": ["news-analyzer"],
    "services/daily-briefing": ["daily-briefing"],
    "services/dashboard/backend": ["dashboard-backend"],
    "services/dashboard/frontend": ["dashboard-frontend"],
    "services/command-handler": ["command-handler"],
    "services/scheduler-service": ["scheduler-service", "scheduler-worker"], # Legacy support
    "dags": ["airflow-scheduler", "airflow-webserver"], # Airflow DAGs -> Airflow services
}

# 전체 빌드를 유발하는 중요 경로
CRITICAL_PATHS = [
    "shared/",
    "docker-compose.yml",
    "infrastructure/",
    "scripts/smart_build.py",
    "requirements.txt", # Root requirements (if any)
    ".env"
]

# 배포 순서 (의존성 고려)
DEPLOY_ORDER = [
    "kis-gateway",
    "news-archiver",
    "buy-scanner",
    "buy-executor",
    "sell-executor",
    "price-monitor",
    "scout-job",
    "scout-worker",
    "command-handler",
    "dashboard-backend",
    "dashboard-frontend",
    "airflow-scheduler",
    "airflow-webserver",
    "daily-briefing",
    "news-collector",
    "news-analyzer"
]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Git Utils
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_cmd(cmd: str) -> str:
    """쉘 명령어 실행 및 출력 반환"""
    try:
        logger.info(f"EXEC: {cmd}")
        result = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT)
        return result.decode('utf-8').strip()
    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed: {cmd}\nOutput: {e.output.decode('utf-8')}")
        sys.exit(1)

def get_changed_files(commit_range: str) -> List[str]:
    """Git diff로 변경된 파일 목록 조회"""
    cmd = f"git diff --name-only {commit_range}"
    output = run_cmd(cmd)
    if not output:
        return []
    return output.split('\n')

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Build Logic
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def detect_changed_services(changed_files: List[str]) -> Set[str]:
    """변경된 파일을 기반으로 재빌드해야 할 서비스 목록 반환"""
    services_to_build = set()
    
    for file_path in changed_files:
        # 1. Critical Path 확인 (전체 빌드 트리거)
        for critical in CRITICAL_PATHS:
            if file_path.startswith(critical):
                logger.warning(f"🚨 Critical change detected in '{file_path}'. Triggering FULL BUILD.")
                return set(["ALL"])
        
        # 2. Service Map 확인
        matched = False
        for prefix, services in SERVICE_MAP.items():
            if file_path.startswith(prefix):
                for svc in services:
                    services_to_build.add(svc)
                matched = True
                break
        
        if not matched:
            logger.debug(f"File '{file_path}' does not map to any specific service. Ignoring.")

    return services_to_build

def build_services(services: Set[str]):
    """Docker Compose Build 실행"""
    if not services:
        logger.info("✅ No services to build.")
        return

    compose_file = os.getenv("DOCKER_COMPOSE_FILE", "docker-compose.yml")
    project_name = os.getenv("COMPOSE_PROJECT_NAME", "my-prime-jennie")
    
    if "ALL" in services:
        logger.info("🏗️ Building ALL services...")
        cmd = f"docker compose -p {project_name} -f {compose_file} build --parallel"
    else:
        service_list = " ".join(services)
        logger.info(f"🏗️ Building services: {service_list}")
        cmd = f"docker compose -p {project_name} -f {compose_file} build --parallel {service_list}"
    
    run_cmd(cmd)

def deploy_services(services: Set[str]):
    """Docker Compose Up 실행 (Rolling Update)"""
    if not services:
        logger.info("✅ No services to deploy.")
        return

    compose_file = os.getenv("DOCKER_COMPOSE_FILE", "docker-compose.yml")
    project_name = os.getenv("COMPOSE_PROJECT_NAME", "my-prime-jennie")
    
    target_services = []
    
    if "ALL" in services:
        target_services = DEPLOY_ORDER
    else:
        # 배포 순서 정렬
        target_services = [s for s in DEPLOY_ORDER if s in services]
        # 순서에 없는 서비스(예: 새로 추가된 것)는 마지막에 추가
        remainder = [s for s in services if s not in DEPLOY_ORDER and s != "ALL"]
        target_services.extend(remainder)

    logger.info(f"🚀 Deploying services: {', '.join(target_services)}")

    for svc in target_services:
        logger.info(f"🔄 Restarting {svc}...")
        # --no-deps: 의존성 재시작 방지 (Rolling Update)
        # --no-build: 이미 빌드 단계에서 빌드 완료됨
        cmd = f"docker compose -p {project_name} -f {compose_file} --profile real up -d --no-deps --no-build {svc}"
        run_cmd(cmd)
        
        # Simple health check wait (optional improvement: use docker inspect)
        # Jenkins pipeline handles detailed health checks, so we just trigger update here if running standalone.
        # But if running inside Jenkins, Jenkins script does the health check. 
        # For this script, lets assuming it triggers the update.
        
    # Prune unused images if fully deployed
    if "ALL" in services:
         run_cmd("docker image prune -f")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Main
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Smart Build Script")
    parser.add_argument("--action", choices=["identify", "build", "deploy"], required=True, help="Action to perform")
    parser.add_argument("--commit-range", help="Git commit range for diff (e.g. HEAD~1..HEAD)")
    parser.add_argument("--services", help="Comma-separated list of services (override detection)")
    
    args = parser.parse_args()
    
    # 1. 대상 서비스 식별
    target_services = set()
    
    if args.services:
        if args.services == "ALL":
             target_services = set(["ALL"])
        else:
            target_services = set(args.services.split(","))
    elif args.commit_range:
        logger.info(f"🔍 Analyzing changes in {args.commit_range}...")
        changed_files = get_changed_files(args.commit_range)
        for f in changed_files:
            logger.info(f"   Modified: {f}")
        
        target_services = detect_changed_services(changed_files)
    else:
        if args.action != "deploy": # Deploy default behavior might be 'redeploy changed' but usually needs input
             logger.error("Either --commit-range or --services is required.")
             sys.exit(1)
        # If deploy is called without args, maybe we assume we deploy what was built?
        # For now, let's enforce explicit input or use a temp file to pass state if needed.
        # But for Jenkins, we can pass the result of 'identify' step.
        pass

    if not target_services and args.action != "identify":
        logger.info("✨ No relevant changes detected. Skipping action.")
        sys.exit(0)

    logger.info(f"🎯 Target Services: {target_services}")

    # 2. 액션 수행
    if args.action == "identify":
        # Jenkins에서 읽을 수 있도록 stdout으로 출력
        print(" ".join(target_services))
        
    elif args.action == "build":
        build_services(target_services)
        
    elif args.action == "deploy":
        deploy_services(target_services)
