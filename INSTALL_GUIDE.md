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
 
> 💡 **LLM 비용 절감 전략 (2025 Budget Strategy)**
>
> 일반 사용자를 위해 **가성비 최적화된** 기본값이 설정되어 있습니다. (별도 설정 불필요)
> - **FAST Tier (뉴스 분석)**: `Gemini 2.5 Flash` (최신 모델, Google 무료 구간 활용)
> - **REASONING Tier (종목 발굴)**: `GPT-5-mini` (최신 경량화 모델, 가성비 우수)
> - **THINKING Tier (최종 검증)**: `GPT-4o` (검증된 고성능 모델, 안정적 비용)
> 
> *완전 무료(Local LLM)로 전환하려면 `env-vars-wsl.yaml`에서 `ollama` 프로바이더를 설정하세요.*

### 📱 5단계: 텔레그램 알림 설정 (선택사항)

| 항목 | 설명 | 발급처 |
|------|------|--------|
| `telegram-bot-token` | 텔레그램 봇 토큰 | @BotFather → /newbot |
| `telegram-chat-id` | 알림 받을 채팅방 ID | @userinfobot에게 메시지 전송 |

> 🔗 **공식 가이드**: [텔레그램 봇 생성 및 토큰 발급 방법](https://core.telegram.org/bots/features#botfather)

### ⚙️ 6단계: 운영 설정

| 항목 | 기본값 | 권장 설정 |
|------|--------|-----------|
| `SCOUT_UNIVERSE_SIZE` | 50 | 테스트=10, 소규모=30, 일반=50, 대규모=200 |
| `ENABLE_NEWS_ANALYSIS` | true | true=뉴스 분석 활성화 (LLM 비용 발생) |
| `EXCLUDED_STOCKS` | (비어있음) | 제외할 종목 코드 (콤마로 구분, 예: "005930,000660") |

> ⚠️ **비용 주의**: `SCOUT_UNIVERSE_SIZE` 값이 클수록 LLM API 호출 횟수가 증가합니다.

### 💰 예상 운영 비용 (Monthly Cost Estimation)
 
LLM API 사용량은 **감시 종목 수(`SCOUT_UNIVERSE_SIZE`)**에 비례하여 급격히 증가합니다.
다음은 2025 Budget Strategy (`Gemini Flash` + `GPT-5-mini`) 기준의 **월간 예상 비용**입니다.
(일 1회 전체 스캔, 영업일 20일 기준)

| 감시 종목 수 | 예상 월 비용 (Approx.) | 구성 상세 (일일 토큰 소모) | 권장 사용자 |
| :---: | :---: | :--- | :--- |
| **50 종목** | **$3.00** | 🧠 2M tokens ($0.3)<br>💡 1M tokens ($2.5) | **입문자 / 테스트용** |
| **100 종목** | **$5.60** | 🧠 4M tokens ($0.6)<br>💡 2M tokens ($5.0) | **소액 투자자** |
| **200 종목** | **$11.20** | 🧠 8M tokens ($1.2)<br>💡 4M tokens ($10.0) | **본격 운영** |

### 📝 비용 계산 기준 (Calculation Basis)
위 비용은 **영업일 20일** 기준이며, 다음 토큰 단가(2025 Est.)를 적용했습니다.

1.  **🧠 REASONING (Scout)**: `GPT-5-mini` @ **$0.15 / 1M Input Tokens**
    *   *가정*: 종목당 약 2,000 토큰 (재무제표 + 뉴스 요약) × 전체 유니버스
2.  **💡 THINKING (Judge)**: `GPT-4o` @ **$2.50 / 1M Input Tokens**
    *   *가정*: 상위 10% 유망 종목에 대해 심층 검증 (토론 로그 포함 약 10,000 토큰)

> **⚠️ 비용 폭탄 방지 팁**:
> 1. 처음에는 `SCOUT_UNIVERSE_SIZE`를 **30** 이하로 설정하여 며칠간 비용을 모니터링하세요.
> 2. OpenAI 대시보드에서 **Usage Limit (월 사용 한도)**를 반드시 설정하세요 (예: $20).
> 3. `Gemini API`는 무료 티어(Pay-as-you-go 아님)를 사용하면 속도 제한이 있지만 비용은 0원입니다.

### 🌐 7단계: Cloudflare Tunnel (선택사항)

외부에서 대시보드에 접근하려면 Cloudflare Tunnel 토큰이 필요합니다:

| 항목 | 설명 | 발급처 |
|------|------|--------|
| `cloudflare-tunnel-token` | 터널 연결 토큰 | Cloudflare Zero Trust → Tunnels |

> 💡 토큰이 없으면 cloudflared 컨테이너는 자동으로 비활성화됩니다.
>
> 🔗 **공식 가이드**: [Cloudflare Tunnel 생성 및 토큰 발급 방법](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/get-started/create-remote-tunnel/)

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
| dashboard-frontend | **80** | real | 웹 대시보드 (http://localhost) |
| dashboard-backend | 8090 | real | 대시보드 API |
| scout-job | 8087 | real | Scout 서비스 |
| news-crawler | 8089 | real | 뉴스 크롤러 |
| price-monitor | 8088 | real | 가격 모니터 |

---

## ⚡ Step 4: 서비스 초기화 (자동)

Scheduler 서비스가 시작되면 **기본 작업(Job)이 자동으로 등록**됩니다. 별도의 설정이 필요 없습니다.

등록되는 작업:
- `scout-job`: 30분 간격 실행 (실제 LLM 분석은 4시간 주기로 제한됨)
- `news-crawler`: 20분 간격 실행 (08:00 ~ 18:00)
- `price-monitor-pulse`: 5분 간격 실행 (장중)

> 💡 **참고**: 만약 수동으로 작업을 초기화하거나 재설정하고 싶다면 다음 명령을 사용하세요:
> ```bash
> python3 scripts/register_default_jobs.py
> ```

---

## ✅ Step 5: 설치 확인

```bash
# 대시보드 접속 테스트
curl http://localhost:8090/api/health

# 웹 브라우저에서 접속 (포트 80)
# http://localhost
```

### 기본 로그인 정보

| 서비스 | ID | 비밀번호 | 비고 |
|--------|-----|----------|------|
| 대시보드 | secrets.json 설정값 | secrets.json 설정값 | `dashboard-username`, `dashboard-password` |
| Grafana | admin | admin | 첫 로그인 시 비밀번호 변경 요청됨 |
| RabbitMQ | guest | guest | http://localhost:15672 |

### 📊 서비스별 로그 모니터링 (Grafana + Loki)

Grafana Explore(`http://localhost:3300/explore`)에서 Loki 데이터소스를 선택하고 **LogQL** 필터를 사용해 로그를 조회합니다.

**기본 필터 문법:** `{service="서비스명"}`

| 서비스 | Grafana 바로가기 (필터 적용됨) | 필터 문법 (LogQL) |
|--------|---------------------|-------------------|
| 🔍 Scout Job | [Logs: scout-job](http://localhost:3300/explore?schemaVersion=1&panes=%7B%22a%22%3A%7B%22datasource%22%3A%22loki%22%2C%22queries%22%3A%5B%7B%22refId%22%3A%22A%22%2C%22expr%22%3A%22%7Bservice%3D%5C%22scout-job%5C%22%7D%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%2C%22to%22%3A%22now%22%7D%7D%7D&orgId=1) | `{service="scout-job"}` |
| 📰 News Crawler | [Logs: news-crawler](http://localhost:3300/explore?schemaVersion=1&panes=%7B%22a%22%3A%7B%22datasource%22%3A%22loki%22%2C%22queries%22%3A%5B%7B%22refId%22%3A%22A%22%2C%22expr%22%3A%22%7Bservice%3D%5C%22news-crawler%5C%22%7D%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%2C%22to%22%3A%22now%22%7D%7D%7D&orgId=1) | `{service="news-crawler"}` |
| 🛒 Buy Scanner | [Logs: buy-scanner](http://localhost:3300/explore?schemaVersion=1&panes=%7B%22a%22%3A%7B%22datasource%22%3A%22loki%22%2C%22queries%22%3A%5B%7B%22refId%22%3A%22A%22%2C%22expr%22%3A%22%7Bservice%3D%5C%22buy-scanner%5C%22%7D%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%2C%22to%22%3A%22now%22%7D%7D%7D&orgId=1) | `{service="buy-scanner"}` |
| 💰 Buy Executor | [Logs: buy-executor](http://localhost:3300/explore?schemaVersion=1&panes=%7B%22a%22%3A%7B%22datasource%22%3A%22loki%22%2C%22queries%22%3A%5B%7B%22refId%22%3A%22A%22%2C%22expr%22%3A%22%7Bservice%3D%5C%22buy-executor%5C%22%7D%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%2C%22to%22%3A%22now%22%7D%7D%7D&orgId=1) | `{service="buy-executor"}` |
| 💸 Sell Executor | [Logs: sell-executor](http://localhost:3300/explore?schemaVersion=1&panes=%7B%22a%22%3A%7B%22datasource%22%3A%22loki%22%2C%22queries%22%3A%5B%7B%22refId%22%3A%22A%22%2C%22expr%22%3A%22%7Bservice%3D%5C%22sell-executor%5C%22%7D%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%2C%22to%22%3A%22now%22%7D%7D%7D&orgId=1) | `{service="sell-executor"}` |
| 🔌 KIS Gateway | [Logs: kis-gateway](http://localhost:3300/explore?schemaVersion=1&panes=%7B%22a%22%3A%7B%22datasource%22%3A%22loki%22%2C%22queries%22%3A%5B%7B%22refId%22%3A%22A%22%2C%22expr%22%3A%22%7Bservice%3D%5C%22kis-gateway%5C%22%7D%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%2C%22to%22%3A%22now%22%7D%7D%7D&orgId=1) | `{service="kis-gateway"}` |
| 📅 Scheduler | [Logs: scheduler](http://localhost:3300/explore?schemaVersion=1&panes=%7B%22a%22%3A%7B%22datasource%22%3A%22loki%22%2C%22queries%22%3A%5B%7B%22refId%22%3A%22A%22%2C%22expr%22%3A%22%7Bservice%3D%5C%22scheduler-service%5C%22%7D%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%2C%22to%22%3A%22now%22%7D%7D%7D&orgId=1) | `{service="scheduler-service"}` |

> 💡 **Tip**: 특정 에러만 보고 싶다면 `|= "error"` 또는 `|= "exception"`을 추가하세요.
> 예: `{service="scout-job"} |= "error"`

---

## 🕒 Step 6: 자동 실행 등록 (Systemd) - 권장

서버 재부팅 시에도 봇이 자동으로 시작되도록 `systemd` 서비스를 등록합니다.

```bash
# 1. 서비스 파일 복사
sudo cp infrastructure/my-prime-jennie.service /etc/systemd/system/

# 2. 서비스 데몬 리로드
sudo systemctl daemon-reload

# 3. 부팅 시 자동 시작 활성화
sudo systemctl enable my-prime-jennie

# 4. 서비스 즉시 시작
sudo systemctl start my-prime-jennie

# 5. 상태 확인
sudo systemctl status my-prime-jennie
```

> **참고**: Systemd 서비스는 `docker compose --profile real up -d`를 자동으로 수행합니다.

### ⚠️ WSL2 사용자 필독 (시스템 부팅 시 자동 실행)
WSL2에서 `systemd`를 사용하려면 설정 파일 수정이 필요할 수 있습니다.

```bash
# 1. /etc/wsl.conf 파일 확인/수정
sudo nano /etc/wsl.conf
```
다음 내용을 추가합니다:
```ini
[boot]
systemd=true
```

설정 후에는 **Windows PowerShell**에서 WSL을 완전히 종료했다가 다시 켜야 적용됩니다:
```powershell
wsl --shutdown
```

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

