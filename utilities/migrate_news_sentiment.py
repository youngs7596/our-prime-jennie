#!/usr/bin/env python3
"""
NEWS_SENTIMENT → STOCK_NEWS_SENTIMENT 마이그레이션 스크립트

1. STOCK_NEWS_SENTIMENT에 SENTIMENT_REASON, PUBLISHED_AT 컬럼 추가 (DDL)
2. ARTICLE_URL collation 통일 (utf8mb4_uca1400_ai_ci → utf8mb4_unicode_ci)
3. Python 메모리 기반 batch 복사 (HASH 인덱스 JOIN 불가 우회)
4. 정합성 검증

실행:
  python utilities/migrate_news_sentiment.py --dry-run          # 건수만 확인
  python utilities/migrate_news_sentiment.py --limit 1000       # 소량 테스트 + 시간 예측
  python utilities/migrate_news_sentiment.py                    # 전체 실행

날짜: 2026-02-18
"""

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from shared.db.connection import init_engine, session_scope

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

BATCH_SIZE = 5000  # INSERT 배치 크기

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

# collation 통일
DDL_FIX_COLLATION = """
    ALTER TABLE STOCK_NEWS_SENTIMENT
    MODIFY COLUMN ARTICLE_URL VARCHAR(2000) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL
"""

INSERT_SQL = """
    INSERT INTO STOCK_NEWS_SENTIMENT
        (STOCK_CODE, NEWS_DATE, ARTICLE_URL, HEADLINE, SENTIMENT_SCORE,
         SENTIMENT_REASON, PUBLISHED_AT, SOURCE, SCRAPED_AT)
    VALUES (:stock_code, :news_date, :article_url, :headline, :sentiment_score,
            :sentiment_reason, :published_at, 'ANALYZER', :scraped_at)
"""


def _fix_collation(session):
    """ARTICLE_URL collation을 utf8mb4_unicode_ci로 통일 (이미 완료된 경우 skip)"""
    row = session.execute(text("""
        SELECT COLLATION_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = 'STOCK_NEWS_SENTIMENT' AND COLUMN_NAME = 'ARTICLE_URL'
    """)).fetchone()

    current = row[0] if row else "unknown"
    if current == "utf8mb4_unicode_ci":
        logger.info("[COLLATION] ARTICLE_URL 이미 utf8mb4_unicode_ci (skip)")
        return

    logger.info(f"[COLLATION] ARTICLE_URL: {current} → utf8mb4_unicode_ci 변경 시작...")
    t0 = time.time()
    session.execute(text(DDL_FIX_COLLATION))
    session.commit()
    logger.info(f"[COLLATION] 변경 완료 ({time.time() - t0:.1f}초)")


def _load_existing_urls(session) -> set:
    """STOCK_NEWS_SENTIMENT의 ARTICLE_URL을 메모리 set으로 로드"""
    t0 = time.time()
    rows = session.execute(text(
        "SELECT ARTICLE_URL FROM STOCK_NEWS_SENTIMENT WHERE ARTICLE_URL IS NOT NULL"
    )).fetchall()
    url_set = {r[0] for r in rows}
    logger.info(f"[LOAD] 기존 URL {len(url_set):,}개 로드 ({time.time() - t0:.1f}초, ~{len(url_set) * 100 // 1024 // 1024}MB)")
    return url_set


def _fetch_source_rows(session, limit: int = 0):
    """NEWS_SENTIMENT에서 복사 대상 행 조회"""
    sql = """
        SELECT STOCK_CODE, SOURCE_URL, NEWS_TITLE, SENTIMENT_SCORE,
               SENTIMENT_REASON, PUBLISHED_AT, CREATED_AT
        FROM NEWS_SENTIMENT
        WHERE SOURCE_URL IS NOT NULL
    """
    if limit > 0:
        sql += f" LIMIT {limit}"
    return session.execute(text(sql)).fetchall()


def run_migration(dry_run: bool = False, limit: int = 0):
    init_engine()

    with session_scope() as session:
        # Step 0: 사전 카운트
        ns_count = session.execute(text("SELECT COUNT(*) FROM NEWS_SENTIMENT")).scalar()
        sns_count_before = session.execute(text("SELECT COUNT(*) FROM STOCK_NEWS_SENTIMENT")).scalar()
        logger.info(f"[사전] NEWS_SENTIMENT: {ns_count:,}건, STOCK_NEWS_SENTIMENT: {sns_count_before:,}건")

        # Step 1: collation 통일
        _fix_collation(session)

        # Step 2: 기존 URL set 로드 (메모리 기반 중복 체크)
        existing_urls = _load_existing_urls(session)

        # Step 3: NEWS_SENTIMENT 행 조회
        logger.info("[FETCH] NEWS_SENTIMENT 소스 데이터 조회 중...")
        t0 = time.time()
        source_rows = _fetch_source_rows(session, limit=limit)
        logger.info(f"[FETCH] {len(source_rows):,}건 조회 ({time.time() - t0:.1f}초)")

        # Step 4: 중복 필터링 (메모리 set 기반 — O(1) lookup)
        to_insert = []
        for row in source_rows:
            url = row[1]  # SOURCE_URL
            if url not in existing_urls:
                to_insert.append({
                    "stock_code": row[0],
                    "news_date": row[5].date() if row[5] else None,  # PUBLISHED_AT → date
                    "article_url": url,
                    "headline": row[2],
                    "sentiment_score": row[3],
                    "sentiment_reason": row[4],
                    "published_at": row[5],
                    "scraped_at": row[6],
                })

        logger.info(f"[FILTER] 전체 {len(source_rows):,}건 중 복사 대상: {len(to_insert):,}건 (이미 존재: {len(source_rows) - len(to_insert):,}건)")

        if dry_run:
            if limit > 0:
                # LIMIT 건수 비율로 전체 예측
                total_source = session.execute(text(
                    "SELECT COUNT(*) FROM NEWS_SENTIMENT WHERE SOURCE_URL IS NOT NULL"
                )).scalar()
                ratio = len(to_insert) / max(len(source_rows), 1)
                est_total = int(total_source * ratio)
                logger.info(f"[DRY-RUN] 전체 추정 복사 대상: ~{est_total:,}건 (비율 {ratio:.2%})")
            logger.info("[DRY-RUN] 실제 실행하지 않음")
            return

        if not to_insert:
            logger.info("[SKIP] 복사 대상 없음")
        else:
            # Step 5: DDL - 컬럼 추가
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

            # Step 6: 배치 INSERT
            total = len(to_insert)
            copied = 0
            t0 = time.time()
            for i in range(0, total, BATCH_SIZE):
                batch = to_insert[i:i + BATCH_SIZE]
                session.execute(text(INSERT_SQL), batch)
                session.commit()
                copied += len(batch)
                elapsed = time.time() - t0
                rate = copied / elapsed if elapsed > 0 else 0
                logger.info(f"[INSERT] {copied:,}/{total:,} ({copied*100//total}%) — {rate:.0f}건/초")

            elapsed = time.time() - t0
            logger.info(f"[DATA] 복사 완료: {copied:,}건 ({elapsed:.1f}초, {copied/elapsed:.0f}건/초)")

            if limit > 0:
                # 전체 시간 예측
                total_pending = int(ns_count * (len(to_insert) / max(len(source_rows), 1)))
                est_seconds = (total_pending / max(copied, 1)) * elapsed
                logger.info(f"[예측] 전체 ~{total_pending:,}건, 예상 시간: {est_seconds:.0f}초 ({est_seconds/60:.1f}분)")
                return

        # Step 7: PUBLISHED_AT 백필
        backfill_result = session.execute(text("""
            UPDATE STOCK_NEWS_SENTIMENT
            SET PUBLISHED_AT = SCRAPED_AT
            WHERE PUBLISHED_AT IS NULL AND SCRAPED_AT IS NOT NULL
        """))
        backfilled = backfill_result.rowcount
        session.commit()
        logger.info(f"[BACKFILL] PUBLISHED_AT NULL → SCRAPED_AT 복사: {backfilled:,}건")

        # Step 8: 정합성 검증 (메모리 기반)
        sns_count_after = session.execute(text("SELECT COUNT(*) FROM STOCK_NEWS_SENTIMENT")).scalar()
        logger.info(f"[검증] STOCK_NEWS_SENTIMENT: {sns_count_before:,}건 → {sns_count_after:,}건 (+{sns_count_after - sns_count_before:,})")

        # URL 기준 누락 검사 (메모리 기반)
        updated_urls = _load_existing_urls(session)
        ns_urls = session.execute(text(
            "SELECT SOURCE_URL FROM NEWS_SENTIMENT WHERE SOURCE_URL IS NOT NULL"
        )).fetchall()
        missing = sum(1 for r in ns_urls if r[0] not in updated_urls)
        if missing > 0:
            logger.warning(f"[검증] 아직 미복사 레코드 {missing:,}건 존재")
        else:
            logger.info("[검증] 모든 NEWS_SENTIMENT 레코드가 STOCK_NEWS_SENTIMENT에 존재합니다.")

    logger.info("마이그레이션 완료.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NEWS_SENTIMENT → STOCK_NEWS_SENTIMENT 마이그레이션")
    parser.add_argument("--dry-run", action="store_true", help="실제 실행 없이 대상 건수만 확인")
    parser.add_argument("--limit", type=int, default=0, help="소량 테스트: N건만 복사 후 전체 시간 예측")
    args = parser.parse_args()

    run_migration(dry_run=args.dry_run, limit=args.limit)
