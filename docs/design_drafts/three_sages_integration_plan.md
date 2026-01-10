# 3현자(Three Sages) 로컬 통합 개발 방안

> 작성일: 2026-01-10
> 작성자: Antigravity

## 1. 개요 및 목표

사용자는 로컬 개발 환경(Antigravity/Codex)에서 웹 버전의 LLM(Gemini, Claude, ChatGPT)과 직접 소통하여 "복사/붙여넣기"의 비효율성을 제거하고자 합니다. 3현자(Jennie, Minji, Junho)의 피드백을 종합하여, 가장 현실적이고 효율적인 **"API 기반 로컬 Council 커맨드 + 워크플로우 통합"** 방안을 제안합니다.

## 2. 현황 분석

- **인프라**: 이미 `my-prime-jennie` 프로젝트 내에 `shared/llm_providers.py`로 3사(Google, Anthropic, OpenAI) API 연동 준비 완료.
- **라이브러리**: `anthropic`, `openai`, `google-genai` 등 필수 패키지 설치 완료 확인.
- **기존 코드**: `scripts/run_daily_council.py`가 존재하나, 이는 `daily_packet.json`에 의존적인 정형화된 프로세스라 "임의의 질문"에는 부적합.

## 3. 개발 방안 (Proposal)

준호가 제안한 **"1번(파일 기반 왕복)"**과 **"3번(커스텀 커맨드)"**을 결합하여 구현합니다.

### 3.1 [Step 1] 범용 질의 스크립트 개발 (`scripts/ask_prime_council.py`)

기존 `run_daily_council.py`의 핵심 로직(`llm_providers` 호출)을 재사용하되, 임의의 텍스트/파일 입력을 받을 수 있는 범용 쿼리 도구를 만듭니다.

- **기능**:
  - 사용자 입력(질문 또는 파일 경로)을 받음.
  - 3현자에게 병렬/순차 질의 (역할에 따라 프롬프트 조정).
    - **Jennie (Gemini)**: 문제 분석, 전략적 접근, 잠재 이슈 제기.
    - **Minji (Claude)**: 구체적인 코드 예시, 구현 가이드, 리팩토링 제안.
    - **Junho (GPT)**: 전체 요약, 장단점 비교, 최종 추천.
  - 결과를 하나의 Markdown 리포트(`reviews/council_report_YYYYMMDD_HHMM.md`)로 통합 저장.
- **CLI 예시**:
  ```bash
  python scripts/ask_prime_council.py --query "이 코드의 성능 개선 방안은?" --file "utilities/backtest.py"
  ```

### 3.2 [Step 2] Antigravity 워크플로우 통합 (`High Priority`)

Antigravity의 워크플로우 기능을 활용하여 IDE 내에서 자연스럽게 호출합니다.

- **워크플로우 파일**: `.agent/workflows/council.md`
- **사용법**: 
  - 채팅창에서 `/council [질문]` 입력.
  - 또는 현재 작업 중인 파일을 열어두고 `/council` 입력.
- **동작**:
  1. 현재 활성 파일의 내용을 임시 파일로 저장(필요 시).
  2. `scripts/ask_prime_council.py` 실행.
  3. 결과 리포트 파일(`reviews/...md`)을 자동으로 열어서 사용자에게 보여줌.

### 3.3 [Step 3] API 키 및 환경 설정 가이드

- `secrets.json`에 `openai-api-key`, `anthropic-api-key`, `gemini-api-key` 설정 필요.
- 사용자에게 설정 템플릿 제공.

### 3.4 [Step 4] Antigravity 자동화 루프 (The "Auto-Pilot")

사용자 질문: *"이 방안으로 구현 시 Antigravity가 자동으로 최적의 방안을 찾아내도록 처리가 가능한가?"*  
**답변: 네, 가능합니다.**

Antigravity(Agent)는 `/council` 워크플로우의 결과물을 **"행동 지침"**으로 인식할 수 있습니다.

1.  **실행**: 사용자가 `/council` 명령어 실행.
2.  **수집**: 스크립트가 3현자의 의견을 모아 `report.md` 생성.
3.  **인식**: 워크플로우가 끝난 후, Antigravity에게 **"Generated Report: `reviews/...md`. Please implement the consensus."** 라는 프롬프트 컨텍스트가 주어짐.
4.  **행동**: Antigravity는 리포트의 `[Junho's Final Recommendation]` 및 `[Minji's Code Guide]` 섹션을 읽고, 즉시 코드 편집(write_to_file/replace_file_content)을 수행.

즉, **"/council 실행 -> (대기) -> Antigravity가 코드 자동 수정"**의 완전 자동화 흐름이 완성됩니다.

### 3.5 [Step 5] "Best Brains" 전략 (High Quality, On-Demand)

사용자의 피드백을 반영하여, **3현자(Council)는 항상 "최고의 두뇌"를 사용**하도록 구성합니다.
빈번한 호출은 자제하되, 한 번 호출할 때는 확실한 인사이트를 얻는 것이 목표입니다.

- **기본 구성 (The Council)**:
  - **Jennie (Strategy)**: **Gemini 3.0 Pro** (A.K.A 제니) - 방대한 컨텍스트와 전략적 추론
  - **Minji (Code)**: **Claude Opus 4.5** (A.K.A 민지) - 현존 최고의 코딩 능력
  - **Junho (Review)**: **ChatGPT 5.2** (A.K.A 준호) - 균형 잡힌 비판과 최종 검수

- **운영 원칙**:
  - `/council` 명령어는 중요한 의사결정, 복잡한 리팩토링, 아키텍처 설계 시에만 신중하게 사용합니다.
  - 사소한 버그 수정이나 문법 오류는 로컬 LLM이나 IDE 기능을 활용합니다.
  - 비용보다는 **"압도적인 품질"**을 우선순위에 둡니다.

`scripts/ask_prime_council.py`는 기본적으로 위 모델들을 호출하도록 설정됩니다.

## 4. 기대 효과

1. **Zero Copy-Paste**: 더 이상 웹 브라우저를 왔다 갔다 할 필요가 없습니다. 명령어 하나로 3명의 피드백이 내 에디터에 꽂힙니다.
2. **Context Awareness**: 로컬 파일을 직접 인자로 넘기므로, LLM이 실제 코드를 정확히 보고 답변합니다.
3. **History**: 모든 질의/응답 내용이 파일로 저장되어 이력 관리가 가능합니다.

## 5. 실행 계획

1. `scripts/ask_prime_council.py` 구현 (기존 `llm_providers.py` 활용).
2. `.agent/workflows/council.md` 작성.
3. 관련 `prompts/council/` (범용 질의용 시스템 프롬프트) 추가.
4. 사용자에게 `secrets.json` 설정 요청 후 테스트.
