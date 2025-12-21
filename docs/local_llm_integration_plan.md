# 구현 계획 - "탄력적 하이브리드 에이전트" 아키텍처

이 계획은 "3현자" (Jennie, Claude, GPT)의 피드백을 종합하여 로컬 LLM의 견고하고 프로덕션급 통합을 만듭니다.

## 전략적 비전: 설정 가능한 하이브리드
> [!IMPORTANT]
> **핵심 철학**: "Thinking은 단순 연산이 아니라 권위다."
> 우리는 **Thinking Tier** (Judge)를 품질을 위해 기본적으로 Cloud를 사용하지만 Local로 폴백하거나 옵트인할 수 있는 고위험 결정 엔진으로 취급합니다.
> 우리는 **Reasoning Tier** (Hunter)를 비용 효율성을 위해 기본적으로 Local을 사용하는 대용량 데이터 프로세서로 취급합니다.

### 🎯 목표 아키텍처
1.  **Hunter (뉴스/분석)**: **로컬** `qwen2.5:14b`. (볼륨 최적화)
2.  **Judge (트레이딩 결정)**: **Cloud** `gpt-5-mini` / `claude-sonnet` (품질 최적화)
3.  **Reporter (일간 브리핑)**: **Cloud** `claude-opus` (품질 최적화)
4.  **탄력성**: 로컬이 실패 (타임아웃/크래시)하면 자동으로 Cloud로 에스컬레이션

## 제안된 변경사항

### 1. 새로운 아키텍처: 팩토리 및 상태 관리

#### [NEW] [shared/llm_factory.py](file:///home/youngs75/projects/my-ultra-jennie/shared/llm_factory.py)
- **`LLMFactory`**: 모델 검색을 위한 중앙 포인트
    - **`ModelStateManager`**: VRAM에 로드된 로컬 모델을 제어하는 전역 싱글톤. 경쟁 조건 방지.
    - **동적 라우팅**: `infrastructure/env-vars-wsl.yaml`을 사용하여 Tier를 Provider (Ollama vs OpenAI vs Claude)에 매핑
    - **폴백 로직**: `generate_json`이 `LocalModelFailure` 예외를 발생시키면 Factory (또는 JennieBrain 래퍼)가 자동으로 구성된 Cloud 프로바이더로 재시도

- **`LLMTier` Enum**:
    - `FAST`: **로컬 `qwen2.5:3b`**. (초고속 감성 체크용)
    - `REASONING`: **로컬 `qwen2.5:14b`**. (뉴스 요약/추출용)
    - `THINKING`: **Cloud** (기본값). (Judge/Debate/Reporting용)

### 2. 프로바이더 구현 (방어적)

#### [MODIFY] [shared/llm_providers.py](file:///home/youngs75/projects/my-ultra-jennie/shared/llm_providers.py)
- **`OllamaLLMProvider` 추가**:
    - **[견고성] 재시도**: JSON 파싱 오류에 대해 3회 재시도 루프
    - **[견고성] 태그 정리**: `<think>...</think>` 태그의 정규식 제거 (DeepSeek에 중요)
    - **[견고성] 타임아웃**:
        - Fast: 60초
        - Reasoning: 120초
        - Thinking: 300초
    - **[운영] Keep-Alive**: `keep_alive: -1` (무한) 언로딩 오버헤드 방지

### 3. 서비스 리팩토링

#### [MODIFY] [shared/llm.py](file:///home/youngs75/projects/my-ultra-jennie/shared/llm.py)
- **`JennieBrain` 리팩토링**:
    - 직접적인 `self.provider_gemini` 등 **제거**
    - Factory를 호출하는 `self.get_model(tier: LLMTier)` **추가**
    - **오류 처리**: `run_judge_scoring`을 try/except 블록으로 감쌈. `LocalModelFailure` 발생 시 경고 로그 후 `Tier.THINKING_CLOUD`로 재시도
    - **중앙화**: `generate_daily_briefing` 로직을 `JennieBrain` 내부로 이동

#### [MODIFY] [services/daily-briefing/reporter.py](file:///home/youngs75/projects/my-ultra-jennie/services/daily-briefing/reporter.py)
- `JennieBrain.generate_daily_briefing` 호출로 단순화

### 4. 설정
- **`infrastructure/env-vars-wsl.yaml`**:
    - `TIER_FAST_PROVIDER`: `ollama`
    - `TIER_REASONING_PROVIDER`: `ollama`
    - `TIER_THINKING_PROVIDER`: `openai`
    - `LOCAL_MODEL_FAST`: `qwen2.5:3b`
    - `LOCAL_MODEL_REASONING`: `qwen2.5:14b`
    - `LOCAL_MODEL_THINKING`: `deepseek-r1:32b`

## 검증 계획

### 지표 (정량화 가능)
1.  **점수 편차**: 로컬(DeepSeek)과 Cloud(GPT/Claude) 모두에서 10개 샘플 Judge 작업 실행. 평균 점수 차이 계산. (차이 < 15%면 통과)
2.  **신뢰성 비율**: 50개 Hunter 작업 실행. JSON 실패/타임아웃 카운트. (실패율 < 5%면 통과)
3.  **지연 시간**: Hunter 작업의 평균 시간 측정. (14b에서 10초 미만이면 통과)

### 수동 테스트 단계
1.  **하이브리드 흐름**: `scout.py` 실행. Hunter가 로컬 (Ollama 로그) 사용하고 Judge가 Cloud 사용하는지 확인
2.  **지연 시간 확인**: 하이브리드 모드에서 32초 모델 스와핑 일시 중지가 없는지 확인
3.  **폴백 테스트**: 수동으로 Ollama 서비스 중지 (`docker stop ollama`), `scout.py` 실행. JennieBrain이 연결 오류를 잡고 Hunter 작업을 Cloud로 에스컬레이션하는지 확인 (또는 엄격한 로컬이면 정상적으로 실패)
