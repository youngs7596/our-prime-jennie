#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
설정값 덤프 스크립트
우선순위: env > DB CONFIG > default
"""
import os
import sys
import json
from typing import Any

sys.path.append(os.getcwd())

from shared.config import ConfigManager
from shared.db.connection import get_session
from shared.db import repository


def main():
    cfg = ConfigManager()
    with get_session() as session:
        rows = []
        for key, meta in cfg._defaults.items():
            default_val = meta["value"] if isinstance(meta, dict) and "value" in meta else meta
            desc = meta.get("desc", "") if isinstance(meta, dict) else ""
            category = meta.get("category", "General") if isinstance(meta, dict) else "General"

            env_val = os.getenv(key)
            db_val = repository.get_config(session, key, silent=True)

            if env_val is not None:
                value = cfg._convert_type(key, env_val)
                source = "env"
            elif db_val is not None:
                value = cfg._convert_type(key, db_val)
                source = "db"
            else:
                value = default_val
                source = "default"

            rows.append({
                "key": key,
                "value": value,
                "source": source,
                "default": default_val,
                "category": category,
                "desc": desc,
                "env_value": env_val,
                "db_value": db_val,
            })

    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

