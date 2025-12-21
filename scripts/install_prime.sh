#!/bin/bash
set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${GREEN}================================================================${NC}"
echo -e "${GREEN}   🚀 Project Prime: 유니버셜 설치 스크립트 (Ubuntu/WSL2)     ${NC}"
echo -e "${GREEN}================================================================${NC}"
echo -e "${CYAN}📖 설치 가이드: docs/INSTALL_GUIDE.md${NC}"

# 1. Prerequisites Check
echo -e "\n${YELLOW}[1/6] 사전 조건 확인 중...${NC}"

if [ "$EUID" -ne 0 ]; then 
  echo -e "${RED}Please run as root (sudo ./install_prime.sh)${NC}"
  exit 1
fi

# Check Internet
if ! ping -c 1 google.com &> /dev/null; then
    echo -e "${RED}Error: No internet connection.${NC}"
    exit 1
fi

# Check GPU
if command -v nvidia-smi &> /dev/null; then
    echo -e "${GREEN}✓ NVIDIA GPU detected.${NC}"
    HAS_GPU=true
else
    echo -e "${YELLOW}! No NVIDIA GPU detected. LLaMA/Tensorflow will run on CPU (Slow).${NC}"
    HAS_GPU=false
fi

# 2. System Packages
echo -e "\n${YELLOW}[2/5] Installing System Packages...${NC}"
apt-get update
apt-get install -y \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    git \
    python3 \
    python3-venv \
    python3-pip \
    build-essential \
    pkg-config \
    libmariadb-dev \
    net-tools

# Install Docker if not exists
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    # Add Docker's official GPG key:
    mkdir -p /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg

    # Set up the repository:
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      tee /etc/apt/sources.list.d/docker.list > /dev/null
    
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    
    # 실제 사용자를 docker 그룹에 추가 (SUDO_USER 또는 현재 사용자)
    REAL_USER="${SUDO_USER:-$USER}"
    usermod -aG docker "$REAL_USER"
    echo -e "${GREEN}✓ Docker 설치 완료. 사용자 '$REAL_USER'를 docker 그룹에 추가했습니다.${NC}"
    echo -e "${YELLOW}⚠️  Docker 명령어를 sudo 없이 사용하려면 재로그인 또는 'newgrp docker'를 실행하세요.${NC}"
else
    echo -e "${GREEN}✓ Docker already installed.${NC}"
    # 기존 Docker가 있어도 docker 그룹 확인
    REAL_USER="${SUDO_USER:-$USER}"
    if ! groups "$REAL_USER" | grep -q docker; then
        usermod -aG docker "$REAL_USER"
        echo -e "${YELLOW}⚠️  사용자 '$REAL_USER'를 docker 그룹에 추가했습니다. 재로그인 또는 'newgrp docker'가 필요합니다.${NC}"
    fi
fi

# Install NVIDIA Container Toolkit if GPU exists
if [ "$HAS_GPU" = true ]; then
    if ! dpkg -l | grep -q nvidia-container-toolkit; then
        echo "Installing NVIDIA Container Toolkit..."
        curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg \
        && curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
            sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
            tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
        
        apt-get update
        apt-get install -y nvidia-container-toolkit
        nvidia-ctk runtime configure --runtime=docker
        systemctl restart docker || echo "Warning: Could not restart docker (if in WSL, restart manually)"
    else
         echo -e "${GREEN}✓ NVIDIA Container Toolkit already installed.${NC}"
    fi
fi

# 3. Environment Setup (Run as SUDO_USER if sudo used)
echo -e "\n${YELLOW}[3/5] Setting up User Environment...${NC}"
REAL_USER=${SUDO_USER:-$USER}
USER_HOME=$(getent passwd $REAL_USER | cut -d: -f6)
PROJECT_DIR=$(pwd)

echo "Setting up for user: $REAL_USER in $PROJECT_DIR"

# Change ownership of directory to user to avoid permission issues
chown -R $REAL_USER:$REAL_USER $PROJECT_DIR

# Create Docker data directories (run as root)
echo -e "${YELLOW}[4/6] 모니터링 서비스 설정 파일 생성 중...${NC}"
mkdir -p /docker_data/loki /docker_data/loki_data /docker_data/promtail /docker_data/redis_data /docker_data/scheduler_data

# Create Loki config if not exists
if [ ! -f "/docker_data/loki/local-config.yaml" ]; then
    cat > /docker_data/loki/local-config.yaml << 'LOKICONF'
auth_enabled: false
server:
  http_listen_port: 3100
  grpc_listen_port: 9096
common:
  instance_addr: 127.0.0.1
  path_prefix: /tmp/loki
  storage:
    filesystem:
      chunks_directory: /tmp/loki/chunks
      rules_directory: /tmp/loki/rules
  replication_factor: 1
  ring:
    kvstore:
      store: inmemory
query_range:
  results_cache:
    cache:
      embedded_cache:
        enabled: true
        max_size_mb: 100
schema_config:
  configs:
    - from: 2020-10-24
      store: tsdb
      object_store: filesystem
      schema: v13
      index:
        prefix: index_
        period: 24h
ruler:
  alertmanager_url: http://localhost:9093
LOKICONF
    echo -e "${GREEN}✓ Loki 설정 파일 생성 완료${NC}"
fi

# Create Promtail config if not exists
if [ ! -f "/docker_data/promtail/config.yaml" ]; then
    cat > /docker_data/promtail/config.yaml << 'PROMCONF'
server:
  http_listen_port: 9080
  grpc_listen_port: 0
positions:
  filename: /tmp/positions.yaml
clients:
  - url: http://loki:3100/loki/api/v1/push
scrape_configs:
  - job_name: containers
    static_configs:
      - targets:
          - localhost
        labels:
          job: containerlogs
          __path__: /var/lib/docker/containers/*/*-json.log
    pipeline_stages:
      - json:
          expressions:
            output: log
            stream: stream
            timestamp: time
      - output:
          source: output
PROMCONF
    echo -e "${GREEN}✓ Promtail 설정 파일 생성 완료${NC}"
fi

chown -R $REAL_USER:$REAL_USER /docker_data

# [5/6] User environment setup
echo -e "\n${YELLOW}[5/6] 사용자 환경 설정 중...${NC}"

sudo -u $REAL_USER bash <<EOF
    cd $PROJECT_DIR
    
    # Create Directories
    mkdir -p data/mariadb logs models tokens
    
    # Python Venv
    if [ ! -d "venv" ]; then
        echo "Creating Python virtual environment..."
        python3 -m venv venv
    fi
    
    # Activate and Install Requirements
    echo "Installing Python dependencies..."
    source venv/bin/activate
    pip install --upgrade pip
    if [ -f "requirements.txt" ]; then
        pip install -r requirements.txt
    else
        echo "Warning: requirements.txt not found."
    fi
EOF

# 4. Data Initialization
echo -e "\n${YELLOW}[4/5] Preparing Data...${NC}"
# Check if init_dump.sql exists
if [ -f "docker/init/init_dump.sql" ]; then
    echo -e "${GREEN}✓ Custom database dump detected. It will be imported automatically.${NC}"
else
    echo -e "${GREEN}✓ No custom dump found. The database will handle schema initialization (Clean Install).${NC}"
fi

# 5. Secrets Configuration
echo -e "\n${YELLOW}[5/6] Configuring Secrets...${NC}"

if [ ! -f "secrets.json" ]; then
    echo -e "${YELLOW}secrets.json not found. Launching configuration wizard...${NC}"
    
    # Check if template exists
    if [ ! -f "secrets.json.template" ]; then
         echo -e "${RED}Error: secrets.json.template not found! Cannot generate secrets.${NC}"
         exit 1
    fi
    
    # Run python script
    python3 scripts/generate_secrets.py
    
    if [ ! -f "secrets.json" ]; then
        echo -e "${RED}Error: Secrets generation failed or cancelled.${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}✓ secrets.json found.${NC}"
fi

# 6. Final Instructions
echo -e "\n${GREEN}================================================================${NC}"
echo -e "${GREEN}   ✅ 설치 완료!${NC}"
echo -e "${GREEN}================================================================${NC}"
echo -e "\n${CYAN}📋 다음 단계:${NC}"
echo -e ""
echo -e "${RED}⚠️  중요: Docker 권한 적용 (반드시 실행)${NC}"
echo -e "   ${YELLOW}newgrp docker${NC}  # 또는 터미널 재시작"
echo -e ""
echo -e "1. Python 환경 활성화:"
echo -e "   ${YELLOW}source venv/bin/activate${NC}"
echo -e ""
echo -e "2. Docker 서비스 시작 (프로파일 선택):"
echo -e ""
echo -e "   ${CYAN}[인프라만 시작]${NC} - DB, Redis, RabbitMQ 등 기반 서비스만"
echo -e "   ${YELLOW}docker compose --profile infra up -d${NC}"
echo -e ""
echo -e "   ${CYAN}[모의투자 모드]${NC} - 인프라 + 모의투자 서비스"
echo -e "   ${YELLOW}docker compose --profile infra --profile mock up -d${NC}"
echo -e ""
echo -e "   ${CYAN}[실전투자 모드]${NC} - 인프라 + 실전투자 서비스"
echo -e "   ${YELLOW}docker compose --profile infra --profile real up -d${NC}"
echo -e ""
echo -e "3. 서비스 상태 확인:"  
echo -e "   ${YELLOW}docker compose ps${NC}"
echo -e ""
echo -e "4. 대시보드 접속:"
echo -e "   ${YELLOW}http://localhost:3000${NC}"
echo -e ""
echo -e "5. 자동화 작업 등록 (Cron Jobs - 선택사항):"
echo -e "   ${YELLOW}./scripts/setup_cron_jobs.sh${NC}"
echo -e "   ${CYAN}  - 주간 팩터 분석: 매주 일요일 오전 3시${NC}"
echo -e "   ${CYAN}  - 일일 브리핑: 평일 오후 5시 (텔레그램 발송)${NC}"
echo -e ""
echo -e "6. 시스템 시작 시 자동 실행 (systemd - 선택사항):"
echo -e "   ${YELLOW}sudo cp infrastructure/my-prime-jennie.service /etc/systemd/system/${NC}"
echo -e "   ${YELLOW}sudo systemctl daemon-reload${NC}"
echo -e "   ${YELLOW}sudo systemctl enable my-prime-jennie${NC}"
echo -e "   ${YELLOW}sudo systemctl start my-prime-jennie${NC}"
echo -e ""
echo -e "${GREEN}📖 상세 가이드: docs/INSTALL_GUIDE.md${NC}"
echo -e "${GREEN}🔧 설정 재구성: python3 scripts/generate_secrets.py${NC}"
echo -e "\n🚀 Happy Trading!"
