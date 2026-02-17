#!/usr/bin/env python3
"""
NEWS_SENTIMENT → STOCK_NEWS_SENTIMENT 마이그레이션 스크립트

1. STOCK_NEWS_SENTIMENT에 SENTIMENT_REASON, PUBLISHED_AT 컬럼 추가 (DDL)
2. NEWS_SENTIMENT 데이터를 STOCK_NEWS_SENTIMENT로 복사 (중복 방지)
3. 정합성 검증

실행: python utilities/migrate_news_sentiment.py [--dry-run]
날짜: 2026-02-17
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from shared.db.connection import init_engine, session_scope

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


DDL_ADD_COLUMNS = [
    """
    ALTER TABLE STOCK_NEWS_SENTIMENT
    ADD COLUMN IF NOT EXISTS SENTIMENT_REASON VARCHAR(2000) DEFAULT NULL
    """,
    """
    ALTER TABLE STOCK_NEWS_SENTIMENT
    ADD COLUMN IF NOT EXISTS PUBLISHED_AT DATETIME DEFAULT NULL
    """,
]

# NEWS_SENTIMENT에만 존재하는 레코드를 STOCK_NEWS_SENTIMENT로 복사
# SOURCE_URL → ARTICLE_URL, NEWS_TITLE → HEADLINE, SENTIMENT_REASON → SENTIMENT_REASON
# CREATED_AT → SCRAPED_AT, PUBLISHED_AT → PUBLISHED_AT
MIGRATE_DATA_SQL = """
    INSERT INTO STOCK_NEWS_SENTIMENT
        (STOCK_CODE, NEWS_DATE, ARTICLE_URL, HEADLINE, SENTIMENT_SCORE,
         SENTIMENT_REASON, PUBLISHED_AT, SOURCE, SCRAPED_AT)
    SELECT
        ns.STOCK_CODE,
        DATE(ns.PUBLISHED_AT) AS NEWS_DATE,
        ns.SOURCE_URL AS ARTICLE_URL,
        ns.NEWS_TITLE AS HEADLINE,
        ns.SENTIMENT_SCORE,
        ns.SENTIMENT_REASON,
        ns.PUBLISHED_AT,
        'ANALYZER' AS SOURCE,
        ns.CREATED_AT AS SCRAPED_AT
    FROM NEWS_SENTIMENT ns
    WHERE ns.SOURCE_URL IS NOT NULL
      AND ns.SOURCE_URL NOT IN (
          SELECT ARTICLE_URL FROM STOCK_NEWS_SENTIMENT WHERE ARTICLE_URL IS NOT NULL
      )
"""


def run_migration(dry_run: bool = False):
    init_engine()

    with session_scope() as session:
        # Step 0: 사전 카운트
        ns_count = session.execute(text("SELECT COUNT(*) FROM NEWS_SENTIMENT")).scalar()
        sns_count_before = session.execute(text("SELECT COUNT(*) FROM STOCK_NEWS_SENTIMENT")).scalar()
        logger.info(f"[사전] NEWS_SENTIMENT: {ns_count}건, STOCK_NEWS_SENTIMENT: {sns_count_before}건")

        if dry_run:
            # dry-run: 복사 대상 건수만 확인
            pending_count = session.execute(text("""
                SELECT COUNT(*)
                FROM NEWS_SENTIMENT ns
                WHERE ns.SOURCE_URL IS NOT NULL
                  AND ns.SOURCE_URL NOT IN (
                      SELECT ARTICLE_URL FROM STOCK_NEWS_SENTIMENT WHERE ARTICLE_URL IS NOT NULL
                  )
            """)).scalar()
            logger.info(f"[DRY-RUN] 복사 대상: {pending_count}건 (실제 실행하지 않음)")
            return

        # Step 1: DDL - 컬럼 추가
        for ddl in DDL_ADD_COLUMNS:
            try:
                session.execute(text(ddl))
                logger.info(f"[DDL] 실행 완료: {ddl.strip()[:60]}...")
            except Exception as e:
                if "Duplicate column" in str(e) or "already exists" in str(e):
                    logger.info(f"[DDL] 이미 존재 (skip): {ddl.strip()[:60]}...")
                else:
                    raise
        session.commit()

        # Step 2: 데이터 복사
        logger.info("[DATA] NEWS_SENTIMENT → STOCK_NEWS_SENTIMENT 복사 시작...")
        result = session.execute(text(MIGRATE_DATA_SQL))
        copied = result.rowcount
        session.commit()
        logger.info(f"[DATA] 복사 완료: {copied}건")

        # Step 3: PUBLISHED_AT 백필 — 기존 STOCK_NEWS_SENTIMENT 행 중 PUBLISHED_AT이 NULL인 경우
        backfill_result = session.execute(text("""
            UPDATE STOCK_NEWS_SENTIMENT
            SET PUBLISHED_AT = SCRAPED_AT
            WHERE PUBLISHED_AT IS NULL AND SCRAPED_AT IS NOT NULL
        """))
        backfilled = backfill_result.rowcount
        session.commit()
        logger.info(f"[BACKFILL] PUBLISHED_AT NULL → SCRAPED_AT 복사: {backfilled}건")

        # Step 4: 정합성 검증
        sns_count_after = session.execute(text("SELECT COUNT(*) FROM STOCK_NEWS_SENTIMENT")).scalar()
        logger.info(f"[검증] STOCK_NEWS_SENTIMENT: {sns_count_before}건 → {sns_count_after}건 (+{sns_count_after - sns_count_before})")

        # URL 기준 누락 검사
        missing = session.execute(text("""
            SELECT COUNT(*)
            FROM NEWS_SENTIMENT ns
            WHERE ns.SOURCE_URL IS NOT NULL
              AND ns.SOURCE_URL NOT IN (
                  SELECT ARTICLE_URL FROM STOCK_NEWS_SENTIMENT WHERE ARTICLE_URL IS NOT NULL
              )
        """)).scalar()
        if missing > 0:
            logger.warning(f"[검증] 아직 미복사 레코드 {missing}건 존재 (NULL URL 등)")
        else:
            logger.info("[검증] 모든 NEWS_SENTIMENT 레코드가 STOCK_NEWS_SENTIMENT에 존재합니다.")

    logger.info("마이그레이션 완료.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NEWS_SENTIMENT → STOCK_NEWS_SENTIMENT 마이그레이션")
    parser.add_argument("--dry-run", action="store_true", help="실제 실행 없이 대상 건수만 확인")
    args = parser.parse_args()

    run_migration(dry_run=args.dry_run)
