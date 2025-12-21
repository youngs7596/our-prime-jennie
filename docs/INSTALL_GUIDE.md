# 🚀 Project Prime 설치 가이드

이 문서는 Project Prime을 새로운 Ubuntu/WSL2 환경에 설치하는 전체 절차를 안내합니다.

## 📋 사전 준비 사항

### 필수 요구사항
- **OS**: Ubuntu 22.04+ 또는 WSL2
- **메모리**: 16GB RAM 이상 권장
- **저장공간**: 50GB 이상 여유 공간
- **GPU** (선택): NVIDIA GPU (Ollama 로컬 LLM 사용 시)

### 필요한 API 키 및 계정 정보

| 항목 | 필수 | 발급처 |
|------|------|--------|
| 한국투자증권 API (모의/실전) | ✅ | https://apiportal.koreainvestment.com |
| Google Gemini API Key | ✅ | https://aistudio.google.com/app/apikey |
| OpenAI API Key | ❌ | https://platform.openai.com/api-keys |
| Claude API Key | ❌ | https://console.anthropic.com/settings/keys |

---

## 🔧 설치 절차

### Step 1: 프로젝트 Clone

```bash
cd ~
git clone https://github.com/youngs7596/my-prime-jennie.git
cd my-prime-jennie
```

### Step 2: 설치 스크립트 실행

```bash
sudo ./scripts/install_prime.sh
```

이 스크립트는 다음 작업을 자동으로 수행합니다:

| 단계 | 설명 | 소요시간 |
|------|------|----------|
| [1/6] 사전 조건 확인 | root 권한, 인터넷 연결, GPU 감지 | ~5초 |
| [2/6] 시스템 패키지 설치 | Docker, Python, 빌드 도구 | ~2분 |
| [3/6] 사용자 환경 설정 | 디렉토리 생성, Python venv, pip 패키지 | ~3분 |
| [4/6] 데이터 초기화 | DB 덤프 확인 (없으면 자동 스키마 생성) | ~5초 |
| [5/6] 설정 마법사 실행 | API 키 및 환경 설정 입력 | ~5분 |
| [6/6] 완료 | 다음 단계 안내 | - |

---

## ⚙️ 설정 마법사 상세

`[5/6] 설정 마법사` 단계에서는 다음 정보를 입력합니다:

### 📦 1단계: 데이터베이스 설정 (MariaDB)

| 항목 | 기본값 | 설명 |
|------|--------|------|
| `mariadb-user` | jennie | DB 사용자명 (Docker 기본값 유지 권장) |
| `mariadb-password` | change-me | **반드시 변경** - Docker 컨테이너와 일치해야 함 |
| `mariadb-host` | 127.0.0.1 | Docker 사용 시 기본값 유지 |
| `mariadb-port` | 3307 | 기본 MySQL(3306)과 충돌 방지 |
| `mariadb-database` | jennie_db | 데이터베이스명 |

### 🔐 2단계: 대시보드 로그인

| 항목 | 기본값 | 설명 |
|------|--------|------|
| `dashboard-username` | admin | 웹 대시보드 로그인 ID |
| `dashboard-password` | change-me | 웹 대시보드 로그인 비밀번호 |

### 📈 3단계: 한국투자증권 API (KIS)

**모의투자** (테스트용):
- `kis-v-app-key`: KIS 포털 → 내 앱 관리 → 모의투자 앱
- `kis-v-app-secret`: 위와 동일
- `kis-v-account-no`: 모의투자 계좌번호 (XXXXXXXX-XX 형식)

**실전투자** (선택사항):
- `kis-r-app-key`: KIS 포털 → 내 앱 관리 → 실전투자 앱
- `kis-r-app-secret`: 위와 동일
- `kis-r-account-no`: 실제 증권 계좌번호

> 💡 **KIS API 발급 방법**: https://apiportal.koreainvestment.com → 로그인 → API 신청

### 🤖 4단계: LLM API 설정

| 항목 | 필수 | 발급처 |
|------|------|--------|
| `gemini-api-key` | ✅ | https://aistudio.google.com/app/apikey |
| `openai-api-key` | ❌ | https://platform.openai.com/api-keys |
| `claude-api-key` | ❌ | https://console.anthropic.com/settings/keys |

### 📱 5단계: 텔레그램 알림 설정 (선택사항)

| 항목 | 설명 | 발급처 |
|------|------|--------|
| `telegram-bot-token` | 텔레그램 봇 토큰 | @BotFather → /newbot |
| `telegram-chat-id` | 알림 받을 채팅방 ID | @userinfobot에게 메시지 전송 |

### ⚙️ 6단계: 운영 설정

| 항목 | 기본값 | 권장 설정 |
|------|--------|-----------|
| `SCOUT_UNIVERSE_SIZE` | 50 | 테스트=10, 소규모=30, 일반=50, 대규모=200 |
| `ENABLE_NEWS_ANALYSIS` | true | true=뉴스 분석 활성화 (LLM 비용 발생) |

> ⚠️ **비용 주의**: `SCOUT_UNIVERSE_SIZE` 값이 클수록 LLM API 호출 횟수가 증가합니다.

### 🌐 7단계: Cloudflare Tunnel (선택사항)

외부에서 대시보드에 접근하려면 Cloudflare Tunnel 토큰이 필요합니다:

| 항목 | 설명 | 발급처 |
|------|------|--------|
| `cloudflare-tunnel-token` | 터널 연결 토큰 | Cloudflare Zero Trust → Tunnels |

> 💡 토큰이 없으면 cloudflared 컨테이너는 자동으로 비활성화됩니다.

---

## 🐳 Step 3: Docker 서비스 시작

### ⚠️ 중요: Docker 권한 적용

설치 스크립트 실행 후, **반드시 다음 명령을 실행**해야 Docker를 사용할 수 있습니다:

```bash
newgrp docker  # 또는 터미널 재시작
```

### Docker 프로파일 설명

서비스는 **프로파일** 단위로 구성됩니다:

| 프로파일 | 용도 | 포함 서비스 |
|----------|------|-------------|
| `infra` | **기반 인프라** (필수) | MariaDB, Redis, RabbitMQ, ChromaDB, Loki, Grafana |
| `gpu` | **로컬 LLM** (GPU 필요) | Ollama |
| `mock` | **모의투자 테스트** | KIS Mock Server, 모의투자용 서비스들 |
| `real` | **실전투자 운영** | 실전투자용 전체 서비스 (대시보드 포함) |
| `ci` | **CI/CD** (개발용) | Jenkins (빌드 필요) |

### 시작 명령어

```bash
# 1. Python 환경 활성화
source venv/bin/activate

# 2. 프로파일 선택하여 시작

# [인프라만] - DB, Redis 등 기반 서비스
docker compose --profile infra up -d

# [인프라 + GPU] - Ollama 포함 (NVIDIA GPU 필요)
docker compose --profile infra --profile gpu up -d

# [모의투자] - 인프라 + 모의투자 서비스
docker compose --profile infra --profile mock up -d

# [실전투자] - 인프라 + 실전 서비스 (대시보드 포함)
docker compose --profile infra --profile real up -d

# 상태 확인
docker compose ps
```

### 주요 서비스 및 포트

| 서비스 | 포트 | 프로파일 | 설명 |
|--------|------|----------|------|
| mariadb | 3307 | infra | 데이터베이스 |
| redis | 6379 | infra | 캐시 서버 |
| rabbitmq | 5672/15672 | infra | 메시지 큐 |
| chromadb | 8000 | infra | 벡터 DB (RAG) |
| grafana | 3300 | infra | 모니터링 대시보드 |
| loki | 3400 | infra | 로그 수집 |
| ollama | 11434 | gpu | 로컬 LLM (GPU 필요) |
| dashboard-frontend | 3000 | real | 웹 대시보드 |
| dashboard-backend | 8090 | real | 대시보드 API |

---

## ✅ Step 4: 설치 확인

```bash
# 대시보드 접속 테스트
curl http://localhost:8090/api/health

# 웹 브라우저에서 접속
# http://localhost:3000
```

### 기본 로그인 정보

| 서비스 | ID | 비밀번호 | 비고 |
|--------|-----|----------|------|
| 대시보드 | secrets.json 설정값 | secrets.json 설정값 | `dashboard-username`, `dashboard-password` |
| Grafana | admin | admin | 첫 로그인 시 비밀번호 변경 요청됨 |
| RabbitMQ | guest | guest | http://localhost:15672 |

---

## 🔧 문제 해결

### Docker 권한 오류
```bash
sudo usermod -aG docker $USER
newgrp docker
```

### MariaDB 연결 실패
```bash
# 컨테이너 로그 확인
docker logs my-prime-jennie-mariadb-1

# secrets.json의 비밀번호가 docker-compose.yml과 일치하는지 확인
# MariaDB 데이터 초기화 (비밀번호 변경 시)
docker compose --profile infra down
sudo rm -rf docker/mariadb/data_v2/*
docker compose --profile infra up -d
```

### GPU가 감지되지 않음
```bash
# NVIDIA 드라이버 확인
nvidia-smi

# NVIDIA Container Toolkit 재설치
sudo apt install -y nvidia-container-toolkit
sudo systemctl restart docker
```

---

## 📞 지원

문제가 발생하면 GitHub Issues에 등록해주세요:
https://github.com/youngs7596/my-prime-jennie/issues
