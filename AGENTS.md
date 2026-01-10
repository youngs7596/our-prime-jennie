# AGENTS.md — my-prime-jennie (Codex Instructions)

본 문서는 OpenAI Codex CLI/에이전트가 my-prime-jennie 코드베이스에서 일관된 방식으로 작업하기 위한 운영 규칙입니다.

---

## 0) Quick Start (Codex CLI 세션 시작 루틴)
Codex가 새 세션을 시작하면 아래를 순서대로 수행합니다.

1. 루트 `rules.md`를 최우선으로 읽고 준수합니다. (Single Source of Truth)
2. 필요 시 `.ai/RULES.md`를 레거시/보조 문서로 참고합니다.
3. `.ai/sessions/`에서 최신 `session-*.md`를 찾아 읽고,
   - 이전 작업 요약
   - 다음 할 일 (Next Steps)
   - 추가로 로드해야 할 파일 목록
   을 사용자에게 브리핑한 뒤 "이어서 진행할까요?"를 묻습니다.

주의: 위 절차는 `/resume` 워크플로우와 동일합니다. (섹션 3 참고)

---

## 1) 프로젝트 컨텍스트
- 프로젝트명: my-prime-jennie
- 목적: 주식/자산 자동 매매 에이전트 개발 (LLM 기반 판단 + 실제 트레이딩)
- 핵심 특징(추정/일반화):
  - Scout(종목 발굴) -> Buy Scanner -> Buy Executor -> Price Monitor -> Sell Executor 파이프라인
  - 실거래/자동매매가 포함될 수 있으므로 안전/승인/DRY_RUN 우선

정확한 구성(서비스명, 엔트리포인트, Docker profile 등)은 Codex가 리포지토리를 스캔하며 확정합니다.

---

## 2) 작업 원칙 (Non-Negotiables)

### 2.1 Single Source of Truth
- 정본은 루트 `rules.md`입니다.
- `.ai/RULES.md`는 레거시/보조로만 사용합니다.

### 2.2 안전/리스크 관리 (Trading System Guardrails)
- 실거래/주문/자동 매매와 연관된 변경은 항상 보수적으로 접근합니다.
- 다음 작업은 반드시 사용자 승인을 받습니다.
  - 실거래 관련 플래그 변경(예: `DRY_RUN=false`로 전환)
  - 주문 실행 로직 변경(매수/매도 조건, 수량, 손절/익절)
  - 데이터 삭제/초기화(특히 DB/Redis/볼륨 삭제)
  - 키/시크릿/계정 정보가 포함될 가능성이 있는 파일 수정 또는 출력
- 로그/샘플/문서/커밋 메시지에 API Key, 토큰, 계좌정보가 포함되지 않도록 점검합니다.

### 2.3 변경 방식
- "한 번에 크게"보다 작게 쪼개서 변경하고, 각 단계에서 동작 검증을 수행합니다.
- 가능하면 아래 순서로 진행합니다.
  1) 원인 규명 -> 2) 최소 수정 -> 3) 테스트/리그레션 -> 4) 문서/세션 인계

---

## 3) 세션 워크플로우 (Cross-IDE Rules)
이 프로젝트는 세션 인계/재개를 표준화합니다.

### 3.1 /rules (규칙만 로드)
1. 루트 `rules.md` 파일을 먼저 읽습니다. (정본)
2. `.ai/RULES.md`는 레거시/보조 문서이므로 필요 시 참고합니다.
3. 프로젝트 개요와 핵심 규칙을 파악합니다.
   - 기술 스택
   - 빌드/테스트/실행 방법
   - 위험 작업 제한 사항
   - 커뮤니케이션 규칙
4. 규칙을 숙지했음을 사용자에게 간단히 알립니다.

### 3.2 /resume (이전 세션 이어서)
1. 루트 `rules.md` 파일을 먼저 읽고 프로젝트 규칙(정본)을 파악합니다.
2. `.ai/sessions/` 폴더에서 가장 최근 `session-*.md` 파일을 찾아 읽습니다.
3. 세션 파일의 내용을 바탕으로 사용자에게 브리핑합니다.
   - 이전 세션에서 한 작업 요약
   - 다음 할 일 (Next Steps)
   - 로드해야 할 파일 목록
4. 사용자에게 "이어서 진행할까요?"라고 묻습니다.

### 3.3 /handoff (세션 종료 및 인계)
1. 현재 세션에서 수행한 작업을 분석합니다. (루트 `rules.md`의 "세션 종료(Handoff)" 절차 준수)
2. `CHANGELOG.md`에 오늘 작업 내용을 한 줄 요약으로 업데이트합니다.
3. `.ai/sessions/session-YYYY-MM-DD-HH-MM.md` 생성:
   ```markdown
   # Session Handoff: [제목]
   ## 요약 (Summary)
   [간단한 설명]
   ## 변경 사항 (Changes)
   - [파일]: [변경 내용]
   ## 다음 단계 (Next Steps)
   - [할 일 항목]
   ```
4. 필요 시 다음 명령을 실행합니다(사용자 승인 후).
   ```bash
   git add .
   git commit -m "Session Handoff: [제목]"
   git push origin development
   ```
5. 사용자에게 "세션 핸드오프 완료"를 알립니다.

---

## 4) Codex 작업 수행 체크리스트 (필수 루틴)

작업을 시작할 때:
- `rules.md` 확인 (정본)
- 최신 세션 파일 확인 (`.ai/sessions/session-*.md`)
- 변경 대상 모듈(서비스/파이프라인) 범위를 명확히 하고
- 실행/테스트 경로를 먼저 확보합니다.

작업을 끝낼 때:
- 최소 1개의 재현/검증 절차 수행(로컬/도커/유닛 테스트 등)
- 문서/세션 기록이 필요한 수준이면 `/handoff` 수행

---

## 5) 개발/실행 기본 규약 (일반)
정확한 명령은 리포지토리 스캔 후 확정합니다. 아래는 기본 골격이며, Codex는 실제 파일(README, docker-compose, scripts, Makefile, package.json 등)을 근거로 갱신/정정합니다.

### 5.1 환경 변수/시크릿
- `.env`, `secrets.json`, 또는 `configs/*` 형태로 관리될 수 있습니다.
- 어떤 형태든 리포지토리에 시크릿을 커밋하지 않습니다.
- 기본 정책:
  - 예시 파일이 있으면(`.env.example`, `secrets.example.json`) 그것을 복사해 로컬만 채웁니다.
  - 출력/로그/문서에 키가 노출되지 않게 합니다.

### 5.2 Python/Node 혼합 프로젝트 가정
Python:
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```
Node:
```bash
npm ci
# 또는 pnpm i (프로젝트에 맞게)
```
Codex는 실제 리포지토리에 맞춰 정답 커맨드를 README/스크립트/CI에서 찾아 사용합니다.

---

## 6) 운영 커맨드 (Operations Commands)
이 섹션은 운영/개발 환경에서 자주 쓰는 명령을 한 곳에 모아둔 것입니다. Codex는 리포지토리 스캔 후 서비스명/프로파일/포트/스크립트명을 실제 값으로 정정합니다.

### 6.1 Docker Compose 기반 운영 (권장)
(A) 프로파일/서비스 확인
```bash
docker compose config --profiles
docker compose ps
```
(B) 인프라만 기동 (DB/Redis/Queue 등)
```bash
docker compose --profile infra up -d
```
(C) 애플리케이션까지 전체 기동
```bash
docker compose --profile infra --profile app up -d
# 또는 (프로젝트가 단일 프로파일이면)
docker compose up -d
```
(D) 상태/로그
```bash
docker compose ps
docker compose logs -f
docker compose logs -f <service>
```
(E) 재시작/중지/정리
```bash
docker compose restart <service>
docker compose stop
docker compose down
```
(F) 볼륨까지 초기화 (위험: 데이터 삭제)
반드시 사용자 승인 후 수행합니다.
```bash
docker compose down -v
```

### 6.2 안전 모드 / DRY_RUN 운영 원칙
- 기본값은 DRY_RUN(모의매매)을 우선합니다.
- 실거래 전환/주문 실행 관련 플래그 변경은 반드시 사용자 승인을 받습니다.
- 권장 흐름:
  - DRY_RUN으로 end-to-end 동작 확인
  - 제한된 소액/단일 종목으로 실거래 리허설
  - 점진적 확대
- 실제 플래그명(DRY_RUN, PAPER_TRADING, TRADING_MODE 등)은 코드/설정 파일에서 확인 후 이 문서에 고정합니다.

### 6.3 파이프라인 단위 실행(예시 템플릿)
리포지토리 스캔 후 아래 템플릿을 실제 엔트리포인트로 치환합니다.

(A) Scout 단독 실행
```bash
# 예: python -m scout.run
python -m <scout_entrypoint>
```
(B) Buy Scanner 단독 실행
```bash
python -m <buy_scanner_entrypoint>
```
(C) Price Monitor 단독 실행
```bash
python -m <price_monitor_entrypoint>
```
(D) Sell Executor 단독 실행
```bash
python -m <sell_executor_entrypoint>
```

### 6.4 데이터/캐시 점검 및 리셋(주의)
- Redis/DB/큐의 리셋은 개발 환경에서만, 그리고 반드시 사용자 승인 후 수행합니다.
- 리셋이 필요할 때는 아래 순서로 보수적으로 접근합니다.
  1) 서비스 중지
  2) 상태 백업/스냅샷(가능하면)
  3) 부분 리셋(특정 키/테이블) -> 최후에 전체 볼륨 삭제

### 6.5 운영 트러블슈팅(기본)
(A) 특정 서비스가 계속 재시작될 때
```bash
docker compose ps
docker compose logs -f <service>
```
(B) 포트 충돌
```bash
ss -ltnp | grep -E ':(포트번호)\\b'
```
(C) WSL2 + Docker Desktop 환경 이슈(일반)
- Docker Desktop에서 WSL 통합(Integration)이 켜져 있는지 확인
- 프로젝트 디렉토리가 WSL 파일시스템(`~/projects/...`)에 있는지 확인
- Windows 파일시스템(`/mnt/c/...`)은 I/O가 느려 문제가 될 수 있습니다.

---

## 7) (스캔 후 보강) 코드베이스 맵 / 테스트 / 린트 / CI
Codex는 리포지토리 스캔 결과를 기반으로 아래를 채웁니다.
- 주요 서비스 디렉토리 및 역할
- 설정 파일 위치(예: `configs/`, `secrets.json`, `.env`)
- 테스트/린트 명령(예: `pytest`, `ruff`, `mypy`, `npm test`)
- CI 파이프라인에서 실행되는 표준 커맨드
- 운영 포트/헬스체크 엔드포인트
