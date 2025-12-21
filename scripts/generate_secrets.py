#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Project Prime: 설정 마법사
API 키 및 환경 설정을 대화형으로 입력받아 secrets.json을 생성합니다.
"""

import json
import os
import getpass
import sys

SECRETS_FILE = "secrets.json"
TEMPLATE_FILE = "secrets.json.template"

# 색상 코드
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
RESET = "\033[0m"

# 각 설정값에 대한 한국어 설명
FIELD_DESCRIPTIONS = {
    "mariadb-user": {
        "name": "MariaDB 사용자명",
        "desc": "데이터베이스 접속 ID입니다. Docker MariaDB의 기본값은 'jennie'입니다.",
        "where": "처음 설치 시 기본값 사용 권장 (Docker 컨테이너 설정과 일치해야 함)"
    },
    "mariadb-password": {
        "name": "MariaDB 비밀번호",
        "desc": "데이터베이스 접속 비밀번호입니다.",
        "where": "보안을 위해 반드시 변경하세요. docker-compose.yml의 MARIADB_PASSWORD와 일치해야 합니다.",
        "secret": True
    },
    "mariadb-host": {
        "name": "MariaDB 호스트",
        "desc": "데이터베이스 서버 주소입니다.",
        "where": "Docker 사용 시 기본값 '127.0.0.1' 사용"
    },
    "mariadb-port": {
        "name": "MariaDB 포트",
        "desc": "데이터베이스 서버 포트입니다.",
        "where": "Docker 컨테이너는 3307 포트를 사용합니다 (기본 MySQL 3306과 충돌 방지)"
    },
    "mariadb-database": {
        "name": "MariaDB 데이터베이스명",
        "desc": "사용할 데이터베이스 이름입니다.",
        "where": "기본값 'jennie_db' 사용 권장"
    },
    "dashboard-username": {
        "name": "대시보드 로그인 ID",
        "desc": "웹 대시보드 접속 시 사용할 사용자명입니다.",
        "where": "원하는 ID를 입력하세요"
    },
    "dashboard-password": {
        "name": "대시보드 로그인 비밀번호",
        "desc": "웹 대시보드 접속 시 사용할 비밀번호입니다.",
        "where": "보안을 위해 강력한 비밀번호 설정 권장",
        "secret": True
    },
    "kis-v-app-key": {
        "name": "한국투자증권 모의투자 App Key",
        "desc": "KIS Open API 모의투자용 인증키입니다.",
        "where": "https://apiportal.koreainvestment.com → 내 앱 관리 → 모의투자 앱의 App Key",
        "secret": True
    },
    "kis-v-app-secret": {
        "name": "한국투자증권 모의투자 App Secret",
        "desc": "KIS Open API 모의투자용 시크릿키입니다.",
        "where": "https://apiportal.koreainvestment.com → 내 앱 관리 → 모의투자 앱의 App Secret",
        "secret": True
    },
    "kis-v-account-no": {
        "name": "한국투자증권 모의투자 계좌번호",
        "desc": "모의투자 계좌번호입니다 (8자리-2자리 형식).",
        "where": "https://apiportal.koreainvestment.com → 모의투자 신청 후 발급받은 계좌번호"
    },
    "kis-r-app-key": {
        "name": "한국투자증권 실전투자 App Key",
        "desc": "KIS Open API 실전투자용 인증키입니다.",
        "where": "https://apiportal.koreainvestment.com → 내 앱 관리 → 실전투자 앱의 App Key",
        "secret": True
    },
    "kis-r-app-secret": {
        "name": "한국투자증권 실전투자 App Secret",
        "desc": "KIS Open API 실전투자용 시크릿키입니다.",
        "where": "https://apiportal.koreainvestment.com → 내 앱 관리 → 실전투자 앱의 App Secret",
        "secret": True
    },
    "kis-r-account-no": {
        "name": "한국투자증권 실전투자 계좌번호",
        "desc": "실전투자 계좌번호입니다 (8자리-2자리 형식).",
        "where": "증권사 HTS/MTS에서 확인 가능한 실제 계좌번호"
    },
    "gemini-api-key": {
        "name": "Google Gemini API Key",
        "desc": "Google AI Studio에서 발급받은 Gemini API 키입니다.",
        "where": "https://aistudio.google.com/app/apikey",
        "secret": True
    },
    "openai-api-key": {
        "name": "OpenAI API Key",
        "desc": "ChatGPT/GPT-4 API 키입니다 (선택사항).",
        "where": "https://platform.openai.com/api-keys",
        "secret": True
    },
    "claude-api-key": {
        "name": "Anthropic Claude API Key",
        "desc": "Claude AI API 키입니다 (선택사항).",
        "where": "https://console.anthropic.com/settings/keys",
        "secret": True
    },
    "SCOUT_UNIVERSE_SIZE": {
        "name": "분석 대상 종목 수 (Scout Universe Size)",
        "desc": "KOSPI 시가총액 상위 N개 종목을 분석합니다. 값이 클수록 LLM API 호출 비용이 증가합니다.",
        "where": "권장: 테스트=10, 소규모=30, 일반=50, 대규모=100~200"
    },
    "ENABLE_NEWS_ANALYSIS": {
        "name": "뉴스 감성 분석 활성화",
        "desc": "뉴스 크롤링 및 LLM 감성 분석 기능을 활성화합니다.",
        "where": "true=활성화 (LLM 비용 발생), false=비활성화"
    }
}


def load_template():
    if not os.path.exists(TEMPLATE_FILE):
        print(f"{RED}오류: {TEMPLATE_FILE} 파일을 찾을 수 없습니다.{RESET}")
        print("프로젝트 루트 디렉토리에서 실행해주세요.")
        sys.exit(1)
    
    with open(TEMPLATE_FILE, "r") as f:
        return json.load(f)


def prompt_value(key, default_value):
    info = FIELD_DESCRIPTIONS.get(key, {})
    name = info.get("name", key)
    desc = info.get("desc", "")
    where = info.get("where", "")
    is_secret = info.get("secret", False)
    
    print(f"\n{CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}")
    print(f"{GREEN}[{name}]{RESET}")
    if desc:
        print(f"  {desc}")
    if where:
        print(f"  {YELLOW}📍 {where}{RESET}")
    
    # 기본값이 있으면 표시
    if default_value and not is_secret:
        suffix = f" [{default_value}]: "
    else:
        suffix = ": "
    
    try:
        if is_secret:
            print(f"  (입력 시 화면에 표시되지 않습니다)")
            user_input = getpass.getpass(prompt=f"  입력{suffix}")
        else:
            user_input = input(f"  입력{suffix}")
    except KeyboardInterrupt:
        print(f"\n{YELLOW}설치가 취소되었습니다.{RESET}")
        sys.exit(0)

    if not user_input.strip():
        return default_value
    
    # 타입 변환
    if isinstance(default_value, bool):
        return user_input.lower() in ('true', '1', 'yes', 'y', '예')
    if isinstance(default_value, int):
        try:
            return int(user_input)
        except ValueError:
            print(f"{RED}잘못된 숫자입니다. 기본값({default_value})을 사용합니다.{RESET}")
            return default_value
            
    return user_input


def main():
    print(f"\n{GREEN}{'═' * 60}{RESET}")
    print(f"{GREEN}   🚀 Project Prime: 설정 마법사{RESET}")
    print(f"{GREEN}{'═' * 60}{RESET}")
    print(f"\n이 마법사는 API 키와 환경 설정을 구성하여")
    print(f"secrets.json 파일을 생성합니다.\n")
    print(f"{YELLOW}💡 도움말:{RESET}")
    print(f"  - 기본값을 사용하려면 Enter를 누르세요")
    print(f"  - 비밀번호/API Key는 화면에 표시되지 않습니다")
    print(f"  - 설치 취소: Ctrl+C")

    if os.path.exists(SECRETS_FILE):
        print(f"\n{YELLOW}⚠️  {SECRETS_FILE} 파일이 이미 존재합니다.{RESET}")
        choice = input("덮어쓰시겠습니까? (y/N): ")
        if choice.lower() != 'y':
            print("설치를 취소합니다.")
            return

    template = load_template()
    new_secrets = {}

    # 카테고리별 섹션 표시
    print(f"\n{CYAN}{'─' * 60}{RESET}")
    print(f"{CYAN}📦 1단계: 데이터베이스 설정 (MariaDB){RESET}")
    for key in ["mariadb-user", "mariadb-password", "mariadb-host", "mariadb-port", "mariadb-database"]:
        if key in template:
            new_secrets[key] = prompt_value(key, template[key])

    print(f"\n{CYAN}{'─' * 60}{RESET}")
    print(f"{CYAN}🔐 2단계: 대시보드 로그인 설정{RESET}")
    for key in ["dashboard-username", "dashboard-password"]:
        if key in template:
            new_secrets[key] = prompt_value(key, template[key])

    print(f"\n{CYAN}{'─' * 60}{RESET}")
    print(f"{CYAN}📈 3단계: 한국투자증권 API 설정 (KIS){RESET}")
    print(f"  {YELLOW}모의투자 설정 (테스트용){RESET}")
    for key in ["kis-v-app-key", "kis-v-app-secret", "kis-v-account-no"]:
        if key in template:
            new_secrets[key] = prompt_value(key, template[key])
    
    print(f"\n  {YELLOW}실전투자 설정 (실제 거래용 - 선택사항){RESET}")
    for key in ["kis-r-app-key", "kis-r-app-secret", "kis-r-account-no"]:
        if key in template:
            new_secrets[key] = prompt_value(key, template[key])

    print(f"\n{CYAN}{'─' * 60}{RESET}")
    print(f"{CYAN}🤖 4단계: LLM API 설정{RESET}")
    for key in ["gemini-api-key", "openai-api-key", "claude-api-key"]:
        if key in template:
            new_secrets[key] = prompt_value(key, template[key])

    print(f"\n{CYAN}{'─' * 60}{RESET}")
    print(f"{CYAN}⚙️  5단계: 운영 설정{RESET}")
    for key in ["SCOUT_UNIVERSE_SIZE", "ENABLE_NEWS_ANALYSIS"]:
        if key in template:
            new_secrets[key] = prompt_value(key, template[key])

    # 파일 저장
    try:
        with open(SECRETS_FILE, "w") as f:
            json.dump(new_secrets, f, indent=4, ensure_ascii=False)
        
        # 파일 권한 설정 (소유자만 읽기/쓰기)
        os.chmod(SECRETS_FILE, 0o600)
        
        print(f"\n{GREEN}{'═' * 60}{RESET}")
        print(f"{GREEN}✅ 설정 완료!{RESET}")
        print(f"{GREEN}{'═' * 60}{RESET}")
        print(f"\n생성된 파일: {SECRETS_FILE} (권한: 600)")
        print(f"분석 대상 종목 수: {new_secrets.get('SCOUT_UNIVERSE_SIZE', 50)}개")
        print(f"뉴스 분석: {'활성화' if new_secrets.get('ENABLE_NEWS_ANALYSIS', True) else '비활성화'}")
        
    except Exception as e:
        print(f"{RED}오류: {SECRETS_FILE} 저장 실패: {e}{RESET}")
        sys.exit(1)


if __name__ == "__main__":
    main()
