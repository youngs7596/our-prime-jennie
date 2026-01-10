"""
간단한 시크릿 관리 유틸 (env > secrets.json)
------------------------------------------------
- 값을 노출하지 않고 존재 여부만 확인할 때도 사용할 수 있습니다.
"""

import json
import os
from pathlib import Path
from typing import Optional

import logging

logger = logging.getLogger(__name__)


class SecretManager:
    def __init__(self, secrets_path: Optional[str] = None):
        self.secrets_path = secrets_path or os.getenv("SECRETS_FILE", "/app/config/secrets.json")
        self._cache = None

    def _load_secrets(self) -> dict:
        if self._cache is not None:
            return self._cache

        path = Path(self.secrets_path)
        if not path.exists():
            # 로컬 개발 시 프로젝트 루트에 있는 secrets.json도 시도
            project_root = Path(__file__).resolve().parent.parent
            alt_path = project_root / "secrets.json"
            path = alt_path if alt_path.exists() else path

        if not path.exists():
            logger.debug(f"[SecretManager] secrets.json 없음: {path}")
            self._cache = {}
            return self._cache

        try:
            with path.open("r", encoding="utf-8") as fp:
                data = json.load(fp)
                if not isinstance(data, dict):
                    raise ValueError("secrets.json must be a JSON object")
                # 문자열로만 저장
                self._cache = {str(k): str(v) for k, v in data.items()}
                return self._cache
        except Exception as exc:
            logger.warning(f"[SecretManager] secrets.json 로드 실패({path}): {exc}")
            self._cache = {}
            return self._cache

    def get(self, key: str, default=None) -> Optional[str]:
        """env > secrets.json 순으로 조회하여 값을 반환합니다."""
        if not key:
            return default

        if key in os.environ:
            return os.environ.get(key)

        secrets = self._load_secrets()
        if key in secrets:
            return secrets[key]

        # 하이픈/언더스코어 변환 키도 허용
        alt_key = key.replace("_", "-") if "_" in key else key.replace("-", "_")
        if alt_key in secrets:
            return secrets[alt_key]

        return default

    def exists(self, key: str) -> bool:
        """값은 반환하지 않고 존재 여부만 확인합니다."""
        val = self.get(key, default=None)
        return val is not None

