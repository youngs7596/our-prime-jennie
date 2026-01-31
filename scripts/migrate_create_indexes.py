#!/usr/bin/env python3
"""
DB 인덱스 마이그레이션 스크립트

MariaDB 테이블에 필수 인덱스를 생성합니다.
- 쿼리 패턴 분석을 통해 식별된 인덱스들
- 이미 존재하는 인덱스는 건너뜁니다

실행: python scripts/migrate_create_indexes.py [--dry-run]
"""

import argparse
import logging
import sys
from pathlib import Path

# 프로젝트 루트 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.db.connection import init_engine, get_engine, session_scope
from sqlalchemy import text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ============================================================================
# 인덱스 정의 (테이블명, 인덱스명, 컬럼)
# ============================================================================
INDEXES_TO_CREATE = [
    # ---------------------------------------------------------
    # 핵심 테이블 (매매/포트폴리오)
    # ---------------------------------------------------------

    # TRADELOG - 거래 내역 (자주 조회)
    ("TRADELOG", "ix_tradelog_trade_timestamp", "TRADE_TIMESTAMP"),
    ("TRADELOG", "ix_tradelog_stock_code", "STOCK_CODE"),
    ("TRADELOG", "ix_tradelog_trade_type", "TRADE_TYPE"),

    # WATCHLIST - 관심 종목 (정렬/필터링)
    ("WATCHLIST", "ix_watchlist_llm_score", "LLM_SCORE"),
    ("WATCHLIST", "ix_watchlist_is_tradable", "IS_TRADABLE"),
    ("WATCHLIST", "ix_watchlist_trade_tier", "TRADE_TIER"),

    # AGENT_COMMANDS - 명령 큐 (상태 기반 조회)
    ("AGENT_COMMANDS", "ix_agent_commands_status", "STATUS"),
    ("AGENT_COMMANDS", "ix_agent_commands_requested_by", "REQUESTED_BY"),
    ("AGENT_COMMANDS", "ix_agent_commands_created_at", "CREATED_AT"),

    # ---------------------------------------------------------
    # 가격 데이터 테이블
    # ---------------------------------------------------------

    # STOCK_DAILY_PRICES_3Y - 일봉 (날짜 범위 쿼리)
    ("STOCK_DAILY_PRICES_3Y", "ix_daily_prices_price_date", "PRICE_DATE"),

    # STOCK_MINUTE_PRICE - 분봉 (시간 범위 쿼리)
    ("STOCK_MINUTE_PRICE", "ix_minute_price_stock_code", "STOCK_CODE"),

    # ---------------------------------------------------------
    # 뉴스/감성 테이블
    # ---------------------------------------------------------

    # NEWS_SENTIMENT - 뉴스 감성 분석
    ("NEWS_SENTIMENT", "ix_news_sentiment_stock_code", "STOCK_CODE"),
    ("NEWS_SENTIMENT", "ix_news_sentiment_published_at", "PUBLISHED_AT"),
    ("NEWS_SENTIMENT", "ix_news_sentiment_created_at", "CREATED_AT"),

    # STOCK_NEWS_SENTIMENT - 종목별 뉴스 감성
    ("STOCK_NEWS_SENTIMENT", "ix_stock_news_stock_code", "STOCK_CODE"),
    ("STOCK_NEWS_SENTIMENT", "ix_stock_news_news_date", "NEWS_DATE"),

    # ---------------------------------------------------------
    # 수급/투자자 테이블
    # ---------------------------------------------------------

    # STOCK_INVESTOR_TRADING - 투자자별 매매 동향
    ("STOCK_INVESTOR_TRADING", "ix_investor_stock_code", "STOCK_CODE"),
    ("STOCK_INVESTOR_TRADING", "ix_investor_trade_date", "TRADE_DATE"),

    # MARKET_FLOW_SNAPSHOT - 시장 흐름
    ("MARKET_FLOW_SNAPSHOT", "ix_market_flow_stock_code", "STOCK_CODE"),
    ("MARKET_FLOW_SNAPSHOT", "ix_market_flow_timestamp", "TIMESTAMP"),
    ("MARKET_FLOW_SNAPSHOT", "ix_market_flow_data_type", "DATA_TYPE"),

    # ---------------------------------------------------------
    # 매크로/인사이트 테이블
    # ---------------------------------------------------------

    # DAILY_MACRO_INSIGHT - 매크로 인사이트
    ("DAILY_MACRO_INSIGHT", "ix_macro_insight_date", "INSIGHT_DATE"),

    # ---------------------------------------------------------
    # LLM/AI 의사결정 테이블
    # ---------------------------------------------------------

    # LLM_DECISION_LEDGER - LLM 의사결정 기록
    ("LLM_DECISION_LEDGER", "ix_llm_ledger_stock_code", "STOCK_CODE"),
    ("LLM_DECISION_LEDGER", "ix_llm_ledger_timestamp", "TIMESTAMP"),
    ("LLM_DECISION_LEDGER", "ix_llm_ledger_final_decision", "FINAL_DECISION"),

    # SHADOW_RADAR_LOG - 놓친 기회 분석
    ("SHADOW_RADAR_LOG", "ix_shadow_radar_stock_code", "STOCK_CODE"),
    ("SHADOW_RADAR_LOG", "ix_shadow_radar_timestamp", "TIMESTAMP"),

    # ---------------------------------------------------------
    # 팩터/스코어링 테이블
    # ---------------------------------------------------------

    # DAILY_QUANT_SCORE - 일별 정량 점수
    ("DAILY_QUANT_SCORE", "ix_quant_score_stock_code", "STOCK_CODE"),
    ("DAILY_QUANT_SCORE", "ix_quant_score_score_date", "SCORE_DATE"),
    ("DAILY_QUANT_SCORE", "ix_quant_score_is_passed", "IS_PASSED_FILTER"),

    # FINANCIAL_METRICS_QUARTERLY - 분기별 재무지표
    ("FINANCIAL_METRICS_QUARTERLY", "ix_fin_metrics_stock_code", "STOCK_CODE"),
    ("FINANCIAL_METRICS_QUARTERLY", "ix_fin_metrics_quarter_date", "QUARTER_DATE"),

    # FACTOR_METADATA - 팩터 메타데이터
    ("FACTOR_METADATA", "ix_factor_meta_factor_key", "FACTOR_KEY"),
    ("FACTOR_METADATA", "ix_factor_meta_market_regime", "MARKET_REGIME"),

    # FACTOR_PERFORMANCE - 팩터 성과
    ("FACTOR_PERFORMANCE", "ix_factor_perf_target_code", "TARGET_CODE"),
    ("FACTOR_PERFORMANCE", "ix_factor_perf_condition_key", "CONDITION_KEY"),

    # ---------------------------------------------------------
    # 공시/기타 테이블
    # ---------------------------------------------------------

    # STOCK_DISCLOSURES - 공시
    ("STOCK_DISCLOSURES", "ix_disclosures_stock_code", "STOCK_CODE"),
    ("STOCK_DISCLOSURES", "ix_disclosures_disclosure_date", "DISCLOSURE_DATE"),

    # WATCHLIST_HISTORY - 관심종목 히스토리
    ("WATCHLIST_HISTORY", "ix_watchlist_hist_snapshot_date", "SNAPSHOT_DATE"),

    # BACKTEST_TRADELOG - 백테스트 거래 내역
    ("BACKTEST_TRADELOG", "ix_backtest_trade_date", "TRADE_DATE"),
    ("BACKTEST_TRADELOG", "ix_backtest_stock_code", "STOCK_CODE"),

    # ---------------------------------------------------------
    # 경쟁사/섹터 분석 테이블
    # ---------------------------------------------------------

    # INDUSTRY_COMPETITORS - 산업/경쟁사 매핑
    ("INDUSTRY_COMPETITORS", "ix_competitors_sector_code", "SECTOR_CODE"),
    ("INDUSTRY_COMPETITORS", "ix_competitors_stock_code", "STOCK_CODE"),
    ("INDUSTRY_COMPETITORS", "ix_competitors_is_active", "IS_ACTIVE"),

    # SECTOR_RELATION_STATS - 섹터 관계 통계
    ("SECTOR_RELATION_STATS", "ix_sector_rel_sector_code", "SECTOR_CODE"),
    ("SECTOR_RELATION_STATS", "ix_sector_rel_leader_code", "LEADER_STOCK_CODE"),
    ("SECTOR_RELATION_STATS", "ix_sector_rel_follower_code", "FOLLOWER_STOCK_CODE"),

    # COMPETITOR_BENEFIT_EVENTS - 경쟁사 수혜 이벤트
    ("COMPETITOR_BENEFIT_EVENTS", "ix_benefit_events_affected", "AFFECTED_STOCK_CODE"),
    ("COMPETITOR_BENEFIT_EVENTS", "ix_benefit_events_beneficiary", "BENEFICIARY_STOCK_CODE"),
    ("COMPETITOR_BENEFIT_EVENTS", "ix_benefit_events_status", "STATUS"),

    # ---------------------------------------------------------
    # 자산 스냅샷
    # ---------------------------------------------------------

    # DAILY_ASSET_SNAPSHOT - 일별 자산 스냅샷 (PK가 snapshot_date이므로 추가 인덱스 불필요)
]

# 복합 인덱스 (자주 함께 조회되는 컬럼 조합)
COMPOSITE_INDEXES = [
    # (테이블명, 인덱스명, (컬럼1, 컬럼2, ...))
    ("STOCK_INVESTOR_TRADING", "ix_investor_stock_date", ("STOCK_CODE", "TRADE_DATE")),
    ("STOCK_NEWS_SENTIMENT", "ix_stock_news_stock_date", ("STOCK_CODE", "NEWS_DATE")),
    ("DAILY_QUANT_SCORE", "ix_quant_score_date_stock", ("SCORE_DATE", "STOCK_CODE")),
    ("FINANCIAL_METRICS_QUARTERLY", "ix_fin_metrics_stock_quarter", ("STOCK_CODE", "QUARTER_DATE")),
    ("TRADELOG", "ix_tradelog_stock_timestamp", ("STOCK_CODE", "TRADE_TIMESTAMP")),
]


def get_existing_indexes(engine) -> set:
    """현재 DB에 존재하는 인덱스 목록을 조회합니다."""
    existing = set()

    with engine.connect() as conn:
        # MariaDB: information_schema에서 인덱스 조회
        result = conn.execute(text("""
            SELECT DISTINCT INDEX_NAME
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE()
        """))
        for row in result:
            existing.add(row[0].upper())

    return existing


def get_existing_tables(engine) -> set:
    """현재 DB에 존재하는 테이블 목록을 조회합니다."""
    tables = set()

    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT TABLE_NAME
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = DATABASE()
        """))
        for row in result:
            tables.add(row[0].upper())

    return tables


def get_table_row_counts(engine, tables: list) -> dict:
    """테이블별 레코드 수를 조회합니다."""
    counts = {}

    with engine.connect() as conn:
        for table in tables:
            try:
                result = conn.execute(text(f"SELECT COUNT(*) FROM `{table}`"))
                counts[table] = result.scalar()
            except Exception:
                counts[table] = -1  # 테이블 없음 또는 오류

    return counts


def create_index(engine, table: str, index_name: str, columns: str | tuple, dry_run: bool = False) -> bool:
    """
    인덱스를 생성합니다.

    Args:
        engine: SQLAlchemy 엔진
        table: 테이블명
        index_name: 인덱스명
        columns: 컬럼명 (문자열) 또는 컬럼 튜플 (복합 인덱스)
        dry_run: True면 실제 생성하지 않고 SQL만 출력

    Returns:
        성공 여부
    """
    if isinstance(columns, tuple):
        col_str = ", ".join(f"`{c}`" for c in columns)
    else:
        col_str = f"`{columns}`"

    sql = f"CREATE INDEX `{index_name}` ON `{table}` ({col_str})"

    if dry_run:
        logger.info(f"[DRY-RUN] {sql}")
        return True

    try:
        with engine.connect() as conn:
            conn.execute(text(sql))
            conn.commit()
        logger.info(f"✅ 인덱스 생성 완료: {index_name} ON {table}({col_str})")
        return True
    except Exception as e:
        logger.error(f"❌ 인덱스 생성 실패: {index_name} - {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="MariaDB 인덱스 마이그레이션")
    parser.add_argument("--dry-run", action="store_true", help="실제 생성 없이 SQL만 출력")
    parser.add_argument("--check-only", action="store_true", help="현재 인덱스 상태만 확인")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("MariaDB 인덱스 마이그레이션 시작")
    logger.info("=" * 60)

    # DB 연결
    init_engine()
    engine = get_engine()

    # 현재 상태 확인
    existing_indexes = get_existing_indexes(engine)
    existing_tables = get_existing_tables(engine)

    logger.info(f"\n📊 현재 DB 상태:")
    logger.info(f"   - 테이블 수: {len(existing_tables)}")
    logger.info(f"   - 기존 인덱스 수: {len(existing_indexes)}")

    # 테이블별 레코드 수 확인
    all_tables = list(set(t for t, _, _ in INDEXES_TO_CREATE) | set(t for t, _, _ in COMPOSITE_INDEXES))
    row_counts = get_table_row_counts(engine, all_tables)

    logger.info(f"\n📈 테이블별 레코드 수:")
    for table in sorted(row_counts.keys()):
        count = row_counts[table]
        if count >= 0:
            logger.info(f"   - {table}: {count:,} rows")
        else:
            logger.info(f"   - {table}: (테이블 없음)")

    if args.check_only:
        logger.info("\n✅ 상태 확인 완료 (--check-only)")
        return

    # 생성할 인덱스 필터링
    indexes_to_create = []
    indexes_skipped = []
    tables_missing = set()

    # 단일 컬럼 인덱스
    for table, index_name, column in INDEXES_TO_CREATE:
        if table.upper() not in existing_tables:
            tables_missing.add(table)
            continue
        if index_name.upper() in existing_indexes:
            indexes_skipped.append((table, index_name, column))
        else:
            indexes_to_create.append((table, index_name, column))

    # 복합 인덱스
    for table, index_name, columns in COMPOSITE_INDEXES:
        if table.upper() not in existing_tables:
            tables_missing.add(table)
            continue
        if index_name.upper() in existing_indexes:
            indexes_skipped.append((table, index_name, columns))
        else:
            indexes_to_create.append((table, index_name, columns))

    # 결과 출력
    logger.info(f"\n📋 인덱스 분석 결과:")
    logger.info(f"   - 신규 생성 예정: {len(indexes_to_create)}")
    logger.info(f"   - 이미 존재 (스킵): {len(indexes_skipped)}")
    logger.info(f"   - 테이블 없음 (스킵): {len(tables_missing)}")

    if tables_missing:
        logger.info(f"\n⚠️ 존재하지 않는 테이블: {', '.join(sorted(tables_missing))}")

    if not indexes_to_create:
        logger.info("\n✅ 모든 인덱스가 이미 존재합니다!")
        return

    # 인덱스 생성
    logger.info(f"\n{'[DRY-RUN] ' if args.dry_run else ''}인덱스 생성 시작...")

    success_count = 0
    fail_count = 0

    for table, index_name, columns in indexes_to_create:
        if create_index(engine, table, index_name, columns, dry_run=args.dry_run):
            success_count += 1
        else:
            fail_count += 1

    # 최종 결과
    logger.info("\n" + "=" * 60)
    logger.info(f"{'[DRY-RUN] ' if args.dry_run else ''}마이그레이션 완료")
    logger.info(f"   - 성공: {success_count}")
    logger.info(f"   - 실패: {fail_count}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
