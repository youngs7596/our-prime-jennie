#!/usr/bin/env python3
"""
데이터 보관 정책에 따른 오래된 데이터 정리 스크립트

보관 기간: 1년 (365일) - 모든 테이블 동일
- NEWS_SENTIMENT, STOCK_NEWS_SENTIMENT: 뉴스 감성 분석
- STOCK_MINUTE_PRICE: 분봉 데이터
- MARKET_FLOW_SNAPSHOT: 시장 흐름
- SHADOW_RADAR_LOG, LLM_DECISION_LEDGER: AI 분석 로그
- COMPETITOR_BENEFIT_EVENTS: 경쟁사 수혜 이벤트

영구 보관 (정리 안 함):
- STOCK_DAILY_PRICES_3Y, BACKTEST_TRADELOG, TRADELOG
- WATCHLIST_HISTORY, DAILY_ASSET_SNAPSHOT, FINANCIAL_DATA

실행: python scripts/cleanup_old_data.py [--dry-run]
스케줄: 매주 일요일 03:00 KST (Airflow DAG)
"""

import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 프로젝트 루트 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.db.connection import init_engine, session_scope
from sqlalchemy import text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ============================================================================
# 보관 정책 정의 (테이블명, 날짜 컬럼, 보관 일수)
# 모든 데이터 1년 보관 - 백테스팅 및 AI 분석용
# ============================================================================
RETENTION_DAYS = 365  # 1년

RETENTION_POLICIES = [
    # 뉴스/감성 데이터
    ("NEWS_SENTIMENT", "CREATED_AT", RETENTION_DAYS),
    ("STOCK_NEWS_SENTIMENT", "NEWS_DATE", RETENTION_DAYS),

    # 장중 데이터 (분봉)
    ("STOCK_MINUTE_PRICE", "PRICE_TIME", RETENTION_DAYS),

    # 시장 흐름 데이터
    ("MARKET_FLOW_SNAPSHOT", "TIMESTAMP", RETENTION_DAYS),

    # AI/분석 로그
    ("SHADOW_RADAR_LOG", "TIMESTAMP", RETENTION_DAYS),
    ("LLM_DECISION_LEDGER", "TIMESTAMP", RETENTION_DAYS),

    # 경쟁사 수혜 이벤트
    ("COMPETITOR_BENEFIT_EVENTS", "DETECTED_AT", RETENTION_DAYS),
]

# 보관하지 않는 테이블 (명시적으로 제외)
EXCLUDED_TABLES = [
    "STOCK_DAILY_PRICES_3Y",  # 3년치 일봉 - 백테스팅용
    "BACKTEST_TRADELOG",      # 백테스트 결과 - 분석용
    "TRADELOG",               # 실거래 내역 - 영구 보관
    "WATCHLIST_HISTORY",      # 관심종목 히스토리 - 영구 보관
    "DAILY_ASSET_SNAPSHOT",   # 자산 스냅샷 - 영구 보관
    "FINANCIAL_DATA",         # 재무 데이터 - 영구 보관
]


def get_table_count(session, table: str) -> int:
    """테이블 레코드 수 조회"""
    try:
        result = session.execute(text(f"SELECT COUNT(*) FROM `{table}`"))
        return result.scalar()
    except Exception:
        return -1


def cleanup_table(session, table: str, date_column: str, retention_days: int, dry_run: bool = False) -> tuple:
    """
    테이블의 오래된 데이터 삭제

    Returns:
        (삭제 대상 수, 삭제 완료 수)
    """
    cutoff_date = datetime.now() - timedelta(days=retention_days)

    # 삭제 대상 수 조회
    count_sql = text(f"""
        SELECT COUNT(*) FROM `{table}`
        WHERE `{date_column}` < :cutoff_date
    """)
    try:
        result = session.execute(count_sql, {"cutoff_date": cutoff_date})
        target_count = result.scalar()
    except Exception as e:
        logger.error(f"❌ {table} 카운트 실패: {e}")
        return (0, 0)

    if target_count == 0:
        return (0, 0)

    if dry_run:
        logger.info(f"   [DRY-RUN] {table}: {target_count:,}건 삭제 예정 (기준일: {cutoff_date.strftime('%Y-%m-%d')})")
        return (target_count, 0)

    # 실제 삭제 (배치 처리)
    delete_sql = text(f"""
        DELETE FROM `{table}`
        WHERE `{date_column}` < :cutoff_date
        LIMIT 10000
    """)

    deleted_total = 0
    while True:
        result = session.execute(delete_sql, {"cutoff_date": cutoff_date})
        deleted = result.rowcount
        session.commit()

        if deleted == 0:
            break

        deleted_total += deleted
        logger.info(f"   {table}: {deleted:,}건 삭제 (누적: {deleted_total:,}건)")

    return (target_count, deleted_total)


def main():
    parser = argparse.ArgumentParser(description="오래된 데이터 정리")
    parser.add_argument("--dry-run", action="store_true", help="실제 삭제 없이 대상만 확인")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("데이터 정리 작업 시작")
    logger.info(f"모드: {'DRY-RUN' if args.dry_run else 'EXECUTE'}")
    logger.info("=" * 60)

    # DB 연결
    init_engine()

    total_target = 0
    total_deleted = 0

    with session_scope() as session:
        # 현재 상태 출력
        logger.info("\n📊 정리 전 테이블 상태:")
        for table, date_col, days in RETENTION_POLICIES:
            count = get_table_count(session, table)
            if count >= 0:
                logger.info(f"   - {table}: {count:,}건 (보관: {days}일)")

        # 정리 실행
        logger.info("\n🧹 데이터 정리 시작...")
        for table, date_col, days in RETENTION_POLICIES:
            logger.info(f"\n[{table}] 보관 기간: {days}일")
            target, deleted = cleanup_table(session, table, date_col, days, dry_run=args.dry_run)
            total_target += target
            total_deleted += deleted

        # 결과 출력
        logger.info("\n" + "=" * 60)
        logger.info(f"{'[DRY-RUN] ' if args.dry_run else ''}정리 완료")
        logger.info(f"   - 삭제 대상: {total_target:,}건")
        logger.info(f"   - 실제 삭제: {total_deleted:,}건")
        logger.info("=" * 60)

        # 정리 후 상태 (실행 모드일 때만)
        if not args.dry_run and total_deleted > 0:
            logger.info("\n📊 정리 후 테이블 상태:")
            for table, date_col, days in RETENTION_POLICIES:
                count = get_table_count(session, table)
                if count >= 0:
                    logger.info(f"   - {table}: {count:,}건")


if __name__ == "__main__":
    main()
