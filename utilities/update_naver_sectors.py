#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
utilities/update_naver_sectors.py
---------------------------------
네이버 업종 크롤링 → STOCK_MASTER.SECTOR_NAVER + SECTOR_NAVER_GROUP 업데이트

사용:
    python utilities/update_naver_sectors.py            # 기본 실행
    python utilities/update_naver_sectors.py --delay 0.5 # 요청 간격 0.5초
    python utilities/update_naver_sectors.py --dry-run    # DB 업데이트 없이 결과만 확인
"""

import argparse
import logging
import sys
import os

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()

from shared.crawlers.naver import build_naver_sector_mapping
from shared.sector_taxonomy import get_sector_group
from shared.db.connection import ensure_engine_initialized

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def ensure_columns_exist(session):
    """SECTOR_NAVER, SECTOR_NAVER_GROUP 컬럼이 없으면 추가"""
    from sqlalchemy import text

    for col_name, col_type in [
        ("SECTOR_NAVER", "VARCHAR(64)"),
        ("SECTOR_NAVER_GROUP", "VARCHAR(64)"),
    ]:
        try:
            session.execute(text(
                f"ALTER TABLE STOCK_MASTER ADD COLUMN {col_name} {col_type} DEFAULT NULL"
            ))
            session.commit()
            logger.info(f"컬럼 추가 완료: {col_name}")
        except Exception:
            session.rollback()
            # 이미 존재하면 무시
            logger.debug(f"컬럼 {col_name} 이미 존재 (또는 추가 실패)")


def update_naver_sectors(request_delay: float = 0.3, dry_run: bool = False):
    """네이버 업종 크롤링 → STOCK_MASTER 업데이트"""

    # 1. 네이버 업종 매핑 구축
    logger.info("=" * 60)
    logger.info("네이버 업종 매핑 구축 시작...")
    logger.info("=" * 60)

    mapping = build_naver_sector_mapping(request_delay=request_delay)

    if not mapping:
        logger.error("매핑 결과가 비어 있습니다. 종료합니다.")
        return

    logger.info(f"총 {len(mapping)}개 종목 매핑 완료")

    # 대분류별 통계
    group_counts = {}
    for code, sector in mapping.items():
        group = get_sector_group(sector)
        group_counts[group] = group_counts.get(group, 0) + 1

    logger.info("\n[대분류별 종목 수]")
    for group, count in sorted(group_counts.items(), key=lambda x: -x[1]):
        logger.info(f"  {group:20s}: {count}개")

    if dry_run:
        logger.info("\n[Dry Run] DB 업데이트를 건너뜁니다.")
        # 샘플 출력
        logger.info("\n[샘플 매핑 (처음 20개)]")
        for i, (code, sector) in enumerate(list(mapping.items())[:20]):
            group = get_sector_group(sector)
            logger.info(f"  {code}: {sector} → {group}")
        return

    # 2. DB 업데이트
    from shared.db.connection import session_scope
    from sqlalchemy import text

    ensure_engine_initialized()
    logger.info("\nDB 업데이트 시작...")

    updated = 0
    not_found = 0

    with session_scope() as session:
        # 컬럼 확인/추가
        ensure_columns_exist(session)

        for code, sector in mapping.items():
            group = get_sector_group(sector)
            try:
                result = session.execute(
                    text("""
                        UPDATE STOCK_MASTER
                        SET SECTOR_NAVER = :sector, SECTOR_NAVER_GROUP = :group
                        WHERE STOCK_CODE = :code
                    """),
                    {"sector": sector, "group": group, "code": code}
                )
                if result.rowcount > 0:
                    updated += 1
                else:
                    not_found += 1
            except Exception as e:
                logger.warning(f"업데이트 실패 ({code}): {e}")

        session.commit()

    logger.info(f"\n업데이트 완료: {updated}개 성공, {not_found}개 STOCK_MASTER 미등록")


def main():
    parser = argparse.ArgumentParser(description="네이버 업종 → STOCK_MASTER 업데이트")
    parser.add_argument("--delay", type=float, default=0.3, help="요청 간 지연(초)")
    parser.add_argument("--dry-run", action="store_true", help="DB 업데이트 없이 결과만 확인")
    args = parser.parse_args()

    update_naver_sectors(request_delay=args.delay, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
