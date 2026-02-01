#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/collect_enhanced_macro.py
---------------------------------
Enhanced Macro Data 수집 스크립트.

여러 소스에서 글로벌 매크로 데이터를 수집하고
GlobalMacroSnapshot으로 통합합니다.

Usage:
    python scripts/collect_enhanced_macro.py              # 전체 수집
    python scripts/collect_enhanced_macro.py --quick      # 빠른 수집 (핵심 지표만)
    python scripts/collect_enhanced_macro.py --dry-run    # 수집만 (저장 안함)
    python scripts/collect_enhanced_macro.py --sources finnhub,fred  # 특정 소스만
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

# 프로젝트 루트 설정
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("EnhancedMacroCollector")


async def collect_macro_data(
    sources: Optional[List[str]] = None,
    quick: bool = False,
    dry_run: bool = False,
) -> int:
    """
    매크로 데이터 수집.

    Args:
        sources: 수집할 소스 목록 (None이면 전체)
        quick: 빠른 수집 모드 (핵심 지표만)
        dry_run: True면 저장 안함

    Returns:
        0: 성공, 1: 실패
    """
    from shared.macro_data import (
        EnhancedMacroAggregator,
        AggregatorConfig,
        save_snapshot_to_db,
        get_macro_cache,
    )

    logger.info("=" * 60)
    logger.info("🌍 Enhanced Macro Data Collection 시작")
    logger.info("=" * 60)

    # Aggregator 설정
    config = AggregatorConfig(
        enable_finnhub=sources is None or "finnhub" in sources,
        enable_fred=sources is None or "fred" in sources,
        enable_bok_ecos=sources is None or "bok_ecos" in sources,
        enable_pykrx=sources is None or "pykrx" in sources,
        enable_rss=sources is None or "rss" in sources,
        allow_partial_failure=True,
        use_cache=not dry_run,
    )

    if quick:
        # 빠른 수집: pykrx + rss만 (API 키 불필요)
        config.enable_finnhub = False
        config.enable_fred = False
        config.enable_bok_ecos = False
        logger.info("⚡ Quick 모드: pykrx, rss만 수집")

    # Aggregator 생성
    aggregator = EnhancedMacroAggregator(config)

    try:
        # 사용 가능한 소스 확인
        available = aggregator.get_available_sources()
        logger.info(f"사용 가능한 소스: {available}")

        if not available:
            logger.error("사용 가능한 데이터 소스가 없습니다.")
            logger.error("API 키 설정을 확인하세요:")
            logger.error("  - FINNHUB_API_KEY")
            logger.error("  - FRED_API_KEY")
            logger.error("  - BOK_ECOS_API_KEY")
            return 1

        # 데이터 수집 및 통합
        start_time = datetime.now()
        snapshot = await aggregator.collect_and_aggregate()
        collection_time = (datetime.now() - start_time).total_seconds()

        if snapshot is None:
            logger.error("스냅샷 생성 실패")
            return 1

        # 결과 출력
        print("\n" + "=" * 60)
        print("📊 수집 결과")
        print("=" * 60)
        print(f"  스냅샷 날짜: {snapshot.snapshot_date}")
        print(f"  스냅샷 시간: {snapshot.snapshot_time.strftime('%Y-%m-%d %H:%M:%S KST')}")
        print(f"  수집 시간: {collection_time:.2f}초")
        print(f"  데이터 소스: {snapshot.data_sources}")
        print(f"  완성도: {snapshot.get_completeness_score():.0%}")
        print(f"  신선도: {snapshot.data_freshness:.0%}")

        print("\n--- 주요 지표 ---")
        if snapshot.vix is not None:
            print(f"  VIX: {snapshot.vix:.2f} ({snapshot.vix_regime})")
        if snapshot.fed_rate is not None:
            print(f"  Fed Rate: {snapshot.fed_rate:.2f}%")
        if snapshot.bok_rate is not None:
            print(f"  BOK Rate: {snapshot.bok_rate:.2f}%")
        if snapshot.rate_differential is not None:
            print(f"  금리차: {snapshot.rate_differential:+.2f}%")
        if snapshot.usd_krw is not None:
            print(f"  USD/KRW: {snapshot.usd_krw:.2f}")
        if snapshot.kospi_index is not None:
            change = f" ({snapshot.kospi_change_pct:+.2f}%)" if snapshot.kospi_change_pct else ""
            print(f"  KOSPI: {snapshot.kospi_index:.2f}{change}")
        if snapshot.kosdaq_index is not None:
            change = f" ({snapshot.kosdaq_change_pct:+.2f}%)" if snapshot.kosdaq_change_pct else ""
            print(f"  KOSDAQ: {snapshot.kosdaq_index:.2f}{change}")

        if snapshot.missing_indicators:
            print(f"\n⚠️ 누락된 지표: {snapshot.missing_indicators}")

        if snapshot.is_risk_off_environment:
            print("\n🚨 RISK-OFF 환경 감지!")

        # 저장
        if not dry_run:
            logger.info("DB에 스냅샷 저장 중...")
            save_success = save_snapshot_to_db(snapshot)

            if save_success:
                logger.info("✅ 스냅샷 저장 완료")
            else:
                logger.error("❌ 스냅샷 저장 실패")
                return 1

            # Redis 캐시도 저장
            cache = get_macro_cache()
            cache.set_snapshot(snapshot)
            logger.info("✅ Redis 캐시 저장 완료")
        else:
            logger.info("[DRY RUN] 저장 스킵")

        print("=" * 60)
        print("✅ 수집 완료")
        print("=" * 60)

        return 0

    except Exception as e:
        logger.error(f"수집 실패: {e}", exc_info=True)
        return 1

    finally:
        await aggregator.close()


async def show_status():
    """현재 상태 표시"""
    from shared.macro_data import (
        EnhancedMacroAggregator,
        get_macro_cache,
        get_today_snapshot,
    )

    print("\n" + "=" * 60)
    print("📈 Enhanced Macro Data 상태")
    print("=" * 60)

    # 캐시 상태
    cache = get_macro_cache()
    stats = cache.get_stats()
    print(f"\n--- 캐시 상태 ---")
    print(f"  데이터 포인트: {stats.get('data_points', 0)}")
    print(f"  스냅샷: {stats.get('snapshots', 0)}")
    print(f"  뉴스: {stats.get('news', 0)}")
    print(f"  소스: {stats.get('sources', [])}")

    # 오늘 스냅샷
    snapshot = get_today_snapshot()
    if snapshot:
        print(f"\n--- 오늘 스냅샷 ---")
        print(f"  시간: {snapshot.snapshot_time}")
        print(f"  완성도: {snapshot.get_completeness_score():.0%}")
        print(f"  신선도: {snapshot.data_freshness:.0%}")
        print(f"  소스: {snapshot.data_sources}")
    else:
        print("\n⚠️ 오늘 스냅샷 없음")

    # Aggregator 상태
    aggregator = EnhancedMacroAggregator()
    source_status = aggregator.get_source_status()
    print(f"\n--- 소스 상태 ---")
    for source, status in source_status.items():
        available = "✅" if status["available"] else "❌"
        last_fetch = status.get("last_fetch", "N/A")
        print(f"  {available} {source}: {last_fetch}")

    await aggregator.close()


def main():
    parser = argparse.ArgumentParser(description="Enhanced Macro Data 수집")
    parser.add_argument("--quick", action="store_true", help="빠른 수집 (pykrx, rss만)")
    parser.add_argument("--dry-run", action="store_true", help="수집만 (저장 안함)")
    parser.add_argument("--sources", type=str, help="수집할 소스 (콤마 구분)")
    parser.add_argument("--status", action="store_true", help="현재 상태 표시")
    args = parser.parse_args()

    if args.status:
        asyncio.run(show_status())
        return 0

    sources = None
    if args.sources:
        sources = [s.strip() for s in args.sources.split(",")]

    exit_code = asyncio.run(collect_macro_data(
        sources=sources,
        quick=args.quick,
        dry_run=args.dry_run,
    ))

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
