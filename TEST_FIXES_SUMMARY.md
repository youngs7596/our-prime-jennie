# Jenkins Test Fixes Summary

## Problem
Jenkins CI/CD pipeline failing with 27 test failures preventing deployment.

## Root Causes Identified

### 1. Critical Mocking Issues (Phase 1)
- **pandas DataFrame**: Tests creating DataFrames with `pd.Timestamp()` causing MagicMock issues
- **Environment Variables**: Jenkins environment had `LOCAL_MODEL_FAST=qwen2.5:3b` leaking into tests
- **datetime Mocking**: Inconsistent datetime mocking not returning real datetime objects

### 2. Data/Calculation Issues (Phase 2)
- **scipy/numpy**: Version incompatibility causing `ImportError: cannot import name '__version__'`
- **Insufficient Test Data**: Fixtures providing 20 rows but MA20 calculations need 30+ for reliability
- **Missing sys Import**: `test_pipeline_smoke.py` missing `import sys`

### 3. Test Isolation Issues
- Tests pass individually but fail in full suite run
- Likely caused by mock/patch cleanup issues between tests
-環境변수나 module-level mocks not properly reset

## Fixes Applied

### Phase 1: Critical Mocking (6 tests fixed)

#### [test_scanner.py](file:///home/youngs75/projects/my-prime-jennie/tests/services/buy-scanner/test_scanner.py)
```python
# Before: pd.Timestamp('2024-12-31') causing MagicMock
# After: pd.date_range(end='2024-12-31', periods=1)
daily_prices = pd.DataFrame({
    'PRICE_DATE': pd.date_range(end='2024-12-31', periods=1),
    'CLOSE_PRICE': [100.0],
    ...
})
```

#### [test_llm_factory.py](file:///home/youngs75/projects/my-prime-jennie/tests/shared/test_llm_factory.py)
```python
# Explicitly override Jenkins environment
with patch.dict(os.environ, {
    "TIER_FAST_PROVIDER": "ollama",
    "LOCAL_MODEL_FAST": "gemma3:27b"  # Override Jenkins env
}):
    provider = LLMFactory.get_provider(LLMTier.FAST)
```

#### [test_utils.py](file:///home/youngs75/projects/my-prime-jennie/tests/shared/test_utils.py)
```python
# Use real_datetime to avoid MagicMock comparison issues
from datetime import datetime as real_datetime
mock_dt = real_datetime(2025, 12, 22, 10, 0, 0)
kst = pytz.timezone('Asia/Seoul')
mock_dt = kst.localize(mock_dt)
```

### Phase 2: Data/Calculation (7 tests fixed)

#### [requirements.txt](file:///home/youngs75/projects/my-prime-jennie/requirements.txt)
```text
# Pin versions to avoid compatibility issues
scipy>=1.10.0,<2.0.0
numpy>=1.24.0,<2.0.0
pandas>=1.4.0
```

#### [test_market_regime.py](file:///home/youngs75/projects/my-prime-jennie/tests/shared/test_market_regime.py)
```python
# Increase from 20 to 30 rows for reliable MA20 calculation
@pytest.fixture
def sample_kospi_df():
    \"\"\"샘플 KOSPI 데이터프레임 (30일 - MA20 계산 충분)\"\"\"
    base_price = 2500
    prices = [base_price + i * 5 for i in range(30)]  # 30 days
   return pd.DataFrame({'CLOSE_PRICE': prices})
```

#### [test_pipeline_smoke.py](file:///home/youngs75/projects/my-prime-jennie/tests/test_pipeline_smoke.py)
```python
# Add missing import
import sys

# Use current Python executable instead of hardcoded path
sys.executable  # instead of "./venv/bin/python"
```

## Test Results

### Individual Test Execution
✅ All identified tests pass when run individually
- test_scanner.py (2/2 passing)
- test_llm_factory.py (1/1 passing)
- test_strategy.py (3/3 passing)
- test_factor_analyzer.py (2/2 passing)
- test_market_regime.py (8/8 passing)
- test_utils.py (8/8 passing)

### Full Test Suite Execution
⚠️ 25 tests still failing when run as full suite
- Indicates test isolation/interference issues
- Mocks or environment variables not properly cleaned up between tests
- Requires further investigation or pytest isolation configuration

## Recommendations

### Short-term (For Jenkins)
1. **Run tests in isolated processes**: Add `pytest-forked` and use `--forked` flag
2. **Increase test timeouts**: Some tests may need more time in CI environment
3. **Split test execution**: Run test files separately instead of all at once

### Long-term (Code Quality)
1. **Improve test isolation**: Use `autouse=True` fixtures for cleanup
2. **Avoid module-level mocks**: Use function-scoped mocks where possible
3. **Add test markers**: Separate unit/integration/slow tests

## Files Modified
- `tests/services/buy-scanner/test_scanner.py`
- `tests/shared/test_llm_factory.py`
- `tests/shared/test_utils.py`
- `tests/shared/test_strategy.py`
- `tests/shared/test_market_regime.py`
- `tests/test_pipeline_smoke.py`
- `requirements.txt`

## Commits
1. `fix(tests): Phase 1 - resolve critical mocking issues`
2. `fix(tests): Phase 2 - data/calculation issues`
3. `fix: add sys import and improve datetime mocking in tests`
