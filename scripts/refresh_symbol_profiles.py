"""
종목별 프로파일을 생성해 symbol_overrides.json에 반영하는 스크립트.

기본 동작:
- Watchlist에 있는 종목만 대상으로 일봉(기본 120일) 조회
- RSI 분포/거래량 기반으로 TIER2 배수, RSI 임계치 등을 산출
- config/symbol_overrides.json에 병합 저장

실행 예시:
    python scripts/refresh_symbol_profiles.py --lookback 150
    python scripts/refresh_symbol_profiles.py --codes 005930 000660 --dry-run
    python scripts/refresh_symbol_profiles.py --universe   # Scout 전체 universe (KOSPI 200)
"""

import argparse
import logging
import os
import sys
from typing import List

# Scout universe 함수 import를 위해 경로 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'services', 'scout-job'))

from shared.db.connection import session_scope
from shared import database
from shared.symbol_profile import build_symbol_profile, apply_overrides_to_file

logger = logging.getLogger(__name__)


def _parse_args():
    parser = argparse.ArgumentParser(description="종목별 프로파일 생성 및 오버라이드 반영")
    parser.add_argument("--codes", nargs="*", help="대상 종목 코드 목록 (미지정 시 Watchlist 전체)")
    parser.add_argument("--universe", action="store_true", help="Scout 전체 universe (KOSPI 시총 상위 200개) 대상")
    parser.add_argument("--universe-size", type=int, default=200, help="--universe 사용 시 종목 수 (기본: 200)")
    parser.add_argument("--lookback", type=int, default=120, help="일봉 조회 기간")
    parser.add_argument("--output", type=str, default=None, help="symbol_overrides.json 경로 (기본: 프로젝트 config/)")
    parser.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않고 로그만 출력")
    return parser.parse_args()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args()

    target_path = args.output

    # DB 세션 팩토리 초기화 (Pool 생성)
    database.init_connection_pool()

    with session_scope(readonly=True) as session:
        # 대상 종목 결정: codes > universe > Watchlist 순
        if args.codes:
            codes: List[str] = args.codes
            logger.info("--codes 지정: %d개 종목", len(codes))
        elif args.universe:
            # Scout universe (KOSPI 시총 상위)
            try:
                from scout_universe import get_dynamic_blue_chips
                universe_stocks = get_dynamic_blue_chips(limit=args.universe_size)
                codes = [s['code'] for s in universe_stocks if s.get('is_tradable', True)]
                logger.info("--universe 지정: KOSPI 시총 상위 %d개 종목", len(codes))
            except ImportError as e:
                logger.error("scout_universe 모듈 로드 실패: %s", e)
                return
        else:
            watchlist = database.get_active_watchlist(session)
            codes = list(watchlist.keys())
            if not codes:
                logger.info("Watchlist가 비어있어 종료합니다.")
                return
            logger.info("Watchlist 기준: %d개 종목", len(codes))

        logger.info("대상 종목: %d개 (lookback=%d, dry_run=%s)", len(codes), args.lookback, args.dry_run)

        updated = 0
        skipped = 0
        for code in codes:
            df = database.get_daily_prices(session, code, limit=args.lookback)
            profile = build_symbol_profile(code, df, lookback=args.lookback)
            if profile.get("reason"):
                skipped += 1
                logger.info("[%s] 스킵: %s", code, profile["reason"])
                continue

            overrides = profile.get("overrides", {})
            insights = profile.get("insights", {})
            apply_overrides_to_file(code, overrides, path=target_path, dry_run=args.dry_run)
            updated += 1

            logger.info(
                "[%s] 적용: overrides=%s insights=%s",
                code,
                overrides,
                insights,
            )

        logger.info("완료: 적용 %d개, 스킵 %d개 (dry_run=%s)", updated, skipped, args.dry_run)


if __name__ == "__main__":
    main()

