"""
tests/shared/test_settings_registry.py - Registry 설정 테스트
================================================================

Registry의 구조, sensitive 필드, 기본값 반환을 테스트합니다.
"""

import pytest
from pathlib import Path
import sys

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    # sys.path.insert(0, str(PROJECT_ROOT))
    pass

from shared.settings.registry import REGISTRY, get_registry_defaults


class TestRegistryStructure:
    """REGISTRY 딕셔너리 구조 테스트"""

    def test_registry_is_dict(self):
        """REGISTRY는 dict 타입"""
        assert isinstance(REGISTRY, dict)
        assert len(REGISTRY) > 0

    def test_each_entry_has_required_fields(self):
        """각 항목은 value, type, desc 필드를 가져야 함"""
        required_fields = ["value", "type", "desc"]

        for key, info in REGISTRY.items():
            assert isinstance(info, dict), f"{key}는 dict여야 함"
            for field in required_fields:
                assert field in info, f"{key}에 '{field}' 필드 누락"

    def test_each_entry_has_category(self):
        """각 항목은 category 필드를 가져야 함"""
        for key, info in REGISTRY.items():
            assert "category" in info, f"{key}에 'category' 필드 누락"
            assert isinstance(info["category"], str)

    def test_type_field_is_valid(self):
        """type 필드는 int, float, bool, str 중 하나"""
        valid_types = {"int", "float", "bool", "str"}

        for key, info in REGISTRY.items():
            assert info["type"] in valid_types, f"{key}의 type이 잘못됨: {info['type']}"


class TestRegistrySensitiveField:
    """sensitive 필드 관련 테스트"""

    def test_secrets_category_has_sensitive_true(self):
        """Secrets 카테고리 항목은 sensitive=True"""
        secrets_keys = [k for k, v in REGISTRY.items() if v.get("category") == "Secrets"]

        assert len(secrets_keys) > 0, "Secrets 카테고리 항목이 없음"

        for key in secrets_keys:
            info = REGISTRY[key]
            assert info.get("sensitive") is True, f"{key}는 sensitive=True여야 함"

    def test_non_secrets_category_has_no_sensitive_or_false(self):
        """Secrets가 아닌 카테고리는 sensitive가 없거나 False"""
        non_secrets_keys = [k for k, v in REGISTRY.items() if v.get("category") != "Secrets"]

        for key in non_secrets_keys:
            info = REGISTRY[key]
            sensitive_val = info.get("sensitive")
            assert sensitive_val is None or sensitive_val is False, \
                f"{key}는 Secrets가 아니므로 sensitive=True면 안 됨"

    def test_expected_secret_keys_exist(self):
        """예상되는 시크릿 키들이 존재하는지 확인"""
        expected_secret_keys = [
            "OPENAI_API_KEY",
            "GEMINI_API_KEY",
            "ANTHROPIC_API_KEY",
            "KIS_APP_KEY",
            "KIS_APP_SECRET",
            "TELEGRAM_BOT_TOKEN",
            "JWT_SECRET",
        ]

        for key in expected_secret_keys:
            assert key in REGISTRY, f"{key}가 REGISTRY에 없음"
            assert REGISTRY[key].get("sensitive") is True, f"{key}는 sensitive=True여야 함"


class TestRegistryCategories:
    """카테고리별 그룹화 테스트"""

    def test_llm_category_exists(self):
        """LLM 카테고리 항목 존재 확인"""
        llm_keys = [k for k, v in REGISTRY.items() if v.get("category") == "LLM"]
        assert len(llm_keys) >= 2, "LLM 카테고리에 최소 2개 항목 필요"

    def test_risk_category_exists(self):
        """Risk 카테고리 항목 존재 확인"""
        risk_keys = [k for k, v in REGISTRY.items() if v.get("category") == "Risk"]
        assert len(risk_keys) >= 3, "Risk 카테고리에 최소 3개 항목 필요"

    def test_secrets_category_exists(self):
        """Secrets 카테고리 항목 존재 확인"""
        secrets_keys = [k for k, v in REGISTRY.items() if v.get("category") == "Secrets"]
        assert len(secrets_keys) >= 5, "Secrets 카테고리에 최소 5개 항목 필요"


class TestGetRegistryDefaults:
    """get_registry_defaults() 함수 테스트"""

    def test_returns_registry_dict(self):
        """REGISTRY와 동일한 dict 반환"""
        defaults = get_registry_defaults()
        assert defaults is REGISTRY

    def test_contains_all_keys(self):
        """모든 키 포함"""
        defaults = get_registry_defaults()
        assert "MIN_LLM_SCORE" in defaults
        assert "MAX_BUY_COUNT_PER_DAY" in defaults
        assert "OPENAI_API_KEY" in defaults


class TestRegistryDefaultValues:
    """기본값 타입 일관성 테스트"""

    def test_int_type_has_int_value(self):
        """type이 int인 항목은 value도 int"""
        for key, info in REGISTRY.items():
            if info["type"] == "int":
                # 시크릿은 빈 문자열 허용
                if info.get("sensitive"):
                    continue
                assert isinstance(info["value"], int), f"{key}의 value는 int여야 함"

    def test_float_type_has_float_value(self):
        """type이 float인 항목은 value도 float (또는 int)"""
        for key, info in REGISTRY.items():
            if info["type"] == "float":
                assert isinstance(info["value"], (int, float)), f"{key}의 value는 float여야 함"

    def test_bool_type_has_bool_value(self):
        """type이 bool인 항목은 value도 bool"""
        for key, info in REGISTRY.items():
            if info["type"] == "bool":
                assert isinstance(info["value"], bool), f"{key}의 value는 bool이어야 함"

    def test_str_type_has_str_value(self):
        """type이 str인 항목은 value도 str"""
        for key, info in REGISTRY.items():
            if info["type"] == "str":
                assert isinstance(info["value"], str), f"{key}의 value는 str이어야 함"

