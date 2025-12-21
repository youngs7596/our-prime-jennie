# Daily Council Pipeline Implementation

- [x] **Project Migration: carbon-silicons-council**
    - [x] Initialize new project directory: `/home/youngs75/projects/carbon-silicons-council`
    - [x] **Selective Migration (Cleanup Decision)**:
        - [x] Migrate `shared/` (Core libs, excluding deprecated modules)
        - [x] Migrate `services/` (Active services only: Scout, Briefing, Crawler, Gateway, etc.)
        - [x] Migrate `scripts/` (Essential ops scripts only)
        - [x] Migrate Configs (`.env` template, `requirements.txt`, `.gitignore`)
    - [x] **Verification**:
        - [x] Setup virtual environment and install dependencies
        - [x] Run smoke tests in new environment to ensure `shared` imports work
    - [x] **Git Setup**: Initialize git and prepare for push

- [x] **Daily Council Implementation (Post-Migration)**
    - [x] Create `schemas/daily_packet.schema.json`
    - [x] Create `schemas/jennie_review.schema.json`
    - [x] Create `schemas/minji_review.schema.json`
    - [x] Create `schemas/patch_bundle.schema.json`
    - [x] **Data Suitability Check**: Verified that `ShadowRadarLog` (Veto/Viols), `LLMDecisionLedger` (General), and `TradeLog` (Best/Worst) provide sufficient data for the Daily Council.

- [ ] **Planning & Documentation**
    - [x] Create `task.md`
    - [ ] Update `implementation_plan.md` with user feedback (10 points)
    - [ ] Create `docs/daily_council_spec.md` (Project Specification in Korean)
    - [x] **Data Generation**: Create dummy data if necessary (for smoke tests).
    - [x] Create prompt templates in `prompts/council/` and `prompts/qwen_system.txt`

- [x] **Daily Packet Generator**
    - [x] Implement `scripts/build_daily_packet.py`
        - [x] Sampling logic (6-10 representative cases)
        - [x] Sensitive data masking (Allowlist)
        - [x] Summary statistics generation
        - [x] Schema validation

- [x] **Daily Council Runner**
    - [x] Implement `scripts/run_daily_council.py`
        - [x] 3-Agent Council Interaction (Jennie -> Minji -> Junho)
        - [x] JSON enforcement & Retry logic (1 retry on failure)
        - [x] Rate limiting & Error handling

- [x] **Patch Bundle Applicator**
    - [x] Implement `scripts/apply_patch_bundle.py`
        - [x] Unified diff application
        - [x] Safety checks (Allowed file targets only)
        - [x] Backup & Rollback mechanism
        - [x] Human Gate (dry-run by default)

- [x] **Verification & Testing**
    - [ ] Create `tests/test_schema_validation.py`
    - [x] Create `tests/test_pipeline_smoke.py` (End-to-End Smoke Test)
    - [x] Run manual verification (build -> council -> dry-run patch)
