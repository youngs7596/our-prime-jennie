#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WATCHLIST.TRADE_TIER 컬럼 마이그레이션 스크립트 (Project Recon v1.1)

목표:
- WATCHLIST 테이블에 TRADE_TIER 컬럼을 추가합니다.
- 기존 데이터는 IS_TRADABLE 값을 기반으로 기본값을 채웁니다.
  - IS_TRADABLE=1 -> 'TIER1'
  - IS_TRADABLE=0 -> 'BLOCKED'

주의:
- 운영 DB에서 실행하기 전에는 반드시 백업/점검하세요.
- 본 스크립트는 "컬럼이 이미 있으면" 아무 것도 하지 않습니다(idempotent).
"""

import os
import sys
import logging

from sqlalchemy import text

# Add project root to path
sys.path.append(os.getcwd())

from shared.db.connection import ensure_engine_initialized, session_scope

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _column_exists(session, table_name: str, column_name: str) -> bool:
    sql = text(
        """
        SELECT COUNT(*)
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = :table_name
          AND COLUMN_NAME = :column_name
        """
    )
    cnt = session.execute(
        sql,
        {"table_name": table_name, "column_name": column_name},
    ).scalar_one()
    return int(cnt or 0) > 0


def migrate_watchlist_trade_tier() -> None:
    # Force use of local port/host if not set (WSL 기본값)
    os.environ.setdefault("MARIADB_PORT", "3307")
    os.environ.setdefault("MARIADB_HOST", "127.0.0.1")

    logger.info("Starting WATCHLIST.TRADE_TIER migration...")
    ensure_engine_initialized()

    with session_scope() as session:
        if _column_exists(session, "WATCHLIST", "TRADE_TIER"):
            logger.info("✅ WATCHLIST.TRADE_TIER already exists. Nothing to do.")
            return

        logger.info("🔧 Adding WATCHLIST.TRADE_TIER column...")
        session.execute(
            text(
                """
                ALTER TABLE WATCHLIST
                ADD COLUMN TRADE_TIER VARCHAR(16) NOT NULL DEFAULT 'BLOCKED'
                """
            )
        )

        logger.info("🔧 Backfilling TRADE_TIER from IS_TRADABLE...")
        session.execute(
            text(
                """
                UPDATE WATCHLIST
                SET TRADE_TIER = CASE
                    WHEN IS_TRADABLE = 1 THEN 'TIER1'
                    ELSE 'BLOCKED'
                END
                """
            )
        )

        session.commit()
        logger.info("✅ Migration completed.")


if __name__ == "__main__":
    migrate_watchlist_trade_tier()


