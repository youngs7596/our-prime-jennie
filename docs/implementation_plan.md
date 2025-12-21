# Daily Council Pipeline Implementation Plan

## Phase 0: Project Migration (carbon-silicons-council)
**Goal**: Establish a clean slate environment for the Daily Council V2 system, removing legacy artifacts.

### 0.1 Initialization
- Create new repository: `carbon-silicons-council`
- Initialize Git and Python environment (`.venv`)

### 0.2 Selective Migration (Assets to Transfer)
- **Shared Libraries (`shared/`)**:
    - Core: `database/`, `db/`, `kis/`, `llm/` (JennieBrain), `utils/`
    - Logic: `hybrid_scoring/`, `market_regime/`, `strategies/`, `archivist.py`
    - *Exclude*: Deprecated modules or temp scripts.
- **Services (`services/`)**:
    - `scout-job/`, `daily-briefing/`, `news-crawler/`, `kis-gateway/`
    - *Exclude*: Legacy services if any.
- **Scripts (`scripts/`)**:
    - `run_daily_council.py` (New), `build_daily_packet.py` (New)
    - Ops: `collect_*.py` (Data collectors), `scheduler_*.py`
- **Config**: `.env.example`, `requirements.txt`, `.gitignore`
- **Docs**: `daily_council_spec.md`

### 0.3 verification
- Verify `shared` imports work in the new structure.
- Run `scout-job` locally (dry-run) to confirm environment health.

## Phase 1: Daily Council Implementation Plan

## Goal Description
Implement the "Daily Council" pipeline where a local Qwen model generates a daily summary (`daily_packet`), which is then reviewed by a 3-agent council (Jennie/Gemini, Minji/Claude, Junho/GPT) via API. The final output is a `patch_bundle` that is automatically applied to the codebase.

## User Review Required
> [!IMPORTANT]
> **API Keys**: Ensure `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, and `OPENAI_API_KEY` are set in the environment or `secrets.json` for the council members to function.

> [!NOTE]
> **Data Source**: The `build_daily_packet.py` script will initially use dummy data or sample from existing logs if available. The user specified "representative cases" sampling logic which will be implemented.

## Critical Principles (Junho's Mandate)
> [!IMPORTANT]
> 1. "daily_packet은 원천 로그를 덤프하지 않으며, 대표 케이스 6~10개만 포함한다."
> 2. "외부 API로 전송되는 모든 데이터는 민감정보 allowlist 기반으로 추출한다."
> 3. "리뷰 응답은 JSON 스키마 검증을 통과해야 하며, 실패 시 1회 재요청 후 중단한다."
> 4. "patch_bundle 자동 적용은 안전 범위(스키마/프롬프트/룰/테스트)로 제한하고, 핵심 실행 로직은 금지한다."
> 5. "confidence 최종 산수는 코드에서 수행하며 모델에게 산수를 맡기지 않는다."

## Proposed Changes

### Schemas
#### [NEW] [daily_packet.schema.json](file:///home/youngs75/projects/carbon-silicons-council/schemas/daily_packet.schema.json)
Schema for the daily summary. **Must include `summary_stats` (veto_count, no_trade_ratio, etc.).**
#### [NEW] [jennie_review.schema.json](file:///home/youngs75/projects/carbon-silicons-council/schemas/jennie_review.schema.json)
#### [NEW] [minji_review.schema.json](file:///home/youngs75/projects/carbon-silicons-council/schemas/minji_review.schema.json)
#### [NEW] [patch_bundle.schema.json](file:///home/youngs75/projects/carbon-silicons-council/schemas/patch_bundle.schema.json)
Must support unified diff format and explicit target file paths.

### Prompts
#### [NEW] [qwen_system.txt](file:///home/youngs75/projects/carbon-silicons-council/prompts/qwen_system.txt)
Instructs Qwen to output `confidence_breakdown` only (no final math).
#### [NEW] [jennie_system.txt](file:///home/youngs75/projects/carbon-silicons-council/prompts/council/jennie_system.txt)
#### [NEW] [minji_system.txt](file:///home/youngs75/projects/carbon-silicons-council/prompts/council/minji_system.txt)
#### [NEW] [junho_system.txt](file:///home/youngs75/projects/carbon-silicons-council/prompts/council/junho_system.txt)
Moderator prompt to synthesize reviews into a structured `patch_bundle`.

### Scripts
#### [NEW] [build_daily_packet.py](file:///home/youngs75/projects/carbon-silicons-council/scripts/build_daily_packet.py)
- **Sampling Logic**: 6-10 cases (2 veto, 2 violations, 1 worst, 1 best, 1-2 normal).
- **Security**: Allowlist-based masking for sensitive fields.
- **Stats**: Generate `summary_stats`.
- **Validation**: Strict schema check (exit on failure).

#### [NEW] [run_daily_council.py](file:///home/youngs75/projects/carbon-silicons-council/scripts/run_daily_council.py)
- **Orchestration**: Jennie -> Minji -> Junho.
- **Robustness**: 1 retry on schema failure. Stop on 2nd failure. Save errors to `reviews/.../errors/`.
- **JSON Enforcement**: Force JSON output via system prompt + strict parser.
- **Rate Limits**: Handle 429/5xx with backoff.

#### [NEW] [apply_patch_bundle.py](file:///home/youngs75/projects/carbon-silicons-council/scripts/apply_patch_bundle.py)
- **Safety**:
    - Default to `--dry-run`. Explicit `--apply` required.
    - **Allowed Targets**: `schemas/`, `prompts/`, `rules/`, `tests/` only. Core logic blocked.
    - **Backup**: Create git branch or backup before applying.
    - **Rollback**: Automatic rollback on failure.
- **Diff Format**: Unified diff application.

### Tests
#### [NEW] [test_schema_validation.py](file:///home/youngs75/projects/carbon-silicons-council/tests/test_schema_validation.py)
#### [NEW] [test_pipeline_smoke.py](file:///home/youngs75/projects/carbon-silicons-council/tests/test_pipeline_smoke.py)
End-to-end smoke test:
1. `build_daily_packet --dummy` -> passes schema?
2. `run_daily_council` (mocked) -> produces valid reviews?
3. `apply_patch_bundle --dry-run` -> parses diffs correctly?

## Verification Plan

### Automated Tests
```bash
# Unit tests
pytest tests/test_schema_validation.py

# Smoke test (End-to-End)
pytest tests/test_pipeline_smoke.py
```

### Manual Verification
1. **Full Flow w/ Dummy Data**:
   ```bash
   # 1. Build Packet
   python3 scripts/build_daily_packet.py --output runs/test_run/daily_packet.json --dummy
   
   # 2. Run Council
   python3 scripts/run_daily_council.py --input runs/test_run/daily_packet.json --output-dir reviews/test_run
   
   # 3. Dry-Run Patch
   python3 scripts/apply_patch_bundle.py --input reviews/test_run/patch_bundle.json --dry-run
   ```
2. **Review Artifacts**: Check `reviews/test_run/` for generated JSONs and `README.md`.
3. **Verify Safety**: Try to include a patch for a forbidden file (e.g., `main.py`) in `patch_bundle` and ensure `apply_patch_bundle.py` rejects it.
