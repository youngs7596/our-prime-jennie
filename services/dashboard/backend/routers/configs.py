from typing import List, Literal, Optional, Any
import os

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from shared.config import ConfigManager
from shared.db.connection import get_session
from shared.db import repository
from shared.secret_manager import SecretManager

router = APIRouter(
    prefix="/api/config",
    tags=["config"],
    responses={404: {"description": "Not found"}},
)

_secret_mgr = SecretManager()


class ConfigItem(BaseModel):
    key: str
    value: Any
    default: Any
    type: str
    category: str
    desc: str
    source: Literal["env", "db", "default", "secret"]
    env_value: Optional[str] = None
    db_value: Optional[str] = None
    sensitive: bool = False


class ConfigUpdateRequest(BaseModel):
    value: Any
    description: Optional[str] = None


def _detect_source(key: str, cfg: ConfigManager, session) -> ConfigItem:
    defaults = cfg._defaults
    info = defaults.get(key, {})
    default_val = info["value"] if isinstance(info, dict) and "value" in info else info
    desc = info.get("desc", "") if isinstance(info, dict) else ""
    category = info.get("category", "General") if isinstance(info, dict) else "General"
    typ = info.get("type", type(default_val).__name__) if isinstance(info, dict) else type(default_val).__name__
    sensitive = bool(info.get("sensitive")) if isinstance(info, dict) else False

    if sensitive:
        # 시크릿은 값 노출 금지: 존재 여부만 표시
        env_val = os.getenv(key)
        has_env = env_val is not None
        has_secret_file = _secret_mgr.exists(key)

        if has_env:
            source = "env"
        elif has_secret_file:
            source = "secret"
        else:
            source = "default"

        masked = "***" if (has_env or has_secret_file) else "(unset)"
        return ConfigItem(
            key=key,
            value=masked,
            default="",
            type=str(typ),
            category=category,
            desc=desc,
            source=source,
            env_value="***" if has_env else None,
            db_value=None,
            sensitive=True,
        )

    env_val = os.getenv(key)
    if env_val is not None:
        return ConfigItem(
            key=key,
            value=cfg._convert_type(key, env_val),
            default=default_val,
            type=str(typ),
            category=category,
            desc=desc,
            source="env",
            env_value=env_val,
            db_value=None,
            sensitive=False,
        )

    db_val = repository.get_config(session, key, silent=True)
    if db_val is not None:
        return ConfigItem(
            key=key,
            value=cfg._convert_type(key, db_val),
            default=default_val,
            type=str(typ),
            category=category,
            desc=desc,
            source="db",
            env_value=None,
            db_value=str(db_val),
            sensitive=False,
        )

    return ConfigItem(
        key=key,
        value=default_val,
        default=default_val,
        type=str(typ),
        category=category,
        desc=desc,
        source="default",
        env_value=None,
        db_value=None,
        sensitive=False,
    )


@router.get("/", response_model=List[ConfigItem])
async def list_config():
    cfg = ConfigManager()
    with get_session() as session:
        items = []
        for key in cfg._defaults.keys():
            items.append(_detect_source(key, cfg, session))
    items.sort(key=lambda x: (x.category, x.key))
    return items


@router.put("/{config_key}", response_model=ConfigItem)
async def update_config(config_key: str, payload: ConfigUpdateRequest):
    cfg = ConfigManager()

    # 기본값 존재 여부 확인 (레지스트리/기본에 없는 키면 거부)
    defaults = cfg._defaults
    if config_key not in defaults:
        raise HTTPException(status_code=400, detail=f"Unknown config key: {config_key}")

    # 시크릿/민감 키는 UI 수정 불가
    info = defaults[config_key]
    if isinstance(info, dict) and info.get("sensitive"):
        raise HTTPException(status_code=400, detail="Sensitive key cannot be edited. Set via env/secrets.")

    # 타입 검증 및 문자열 변환(저장은 문자열, 읽을 때 변환)
    target_info = defaults[config_key]
    default_val = target_info["value"] if isinstance(target_info, dict) and "value" in target_info else target_info
    target_type = target_info.get("type") if isinstance(target_info, dict) else type(default_val).__name__

    def _cast(val):
        if target_type in ("int", int):
            return int(val)
        if target_type in ("float", float):
            return float(val)
        if target_type in ("bool", bool):
            if isinstance(val, str):
                return val.lower() in ("true", "1", "yes", "on")
            return bool(val)
        return str(val)

    try:
        casted_value = _cast(payload.value)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid value for type {target_type}")

    with get_session() as session:
        ok = repository.set_config(session, config_key, str(casted_value), payload.description)
        if not ok:
            raise HTTPException(status_code=500, detail="Failed to persist config to DB")
        # 갱신된 값 조회 (env가 있으면 env가 우선)
        item = _detect_source(config_key, cfg, session)
        return item

