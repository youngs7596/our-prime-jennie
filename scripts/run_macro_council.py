#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/run_macro_council.py
----------------------------
일일 매크로 인사이트 분석 작업.

매일 07:30 KST에 실행:
1. @hedgecat0301 채널에서 최신 "장 시작 전 브리핑" 수집
2. 3현자 Council 분석 실행
3. 구조화된 인사이트를 DB/Redis에 저장

Usage:
    python scripts/run_macro_council.py              # 오늘 분석
    python scripts/run_macro_council.py --dry-run    # 분석만 (저장 안함)
    python scripts/run_macro_council.py --date 2026-01-29  # 특정 날짜 (테스트용)
"""

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

# 프로젝트 루트 설정
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "services" / "telegram-collector"))

from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("MacroCouncil")

# ==============================================================================
# 분석 프롬프트
# ==============================================================================

MACRO_ANALYSIS_QUERY = """아래 '장 시작 전 브리핑' 메시지를 분석하여 오늘 시장의 매크로 인사이트를 추출해주세요.

## 반드시 포함해야 할 항목 (JSON 형식)

1. **overall_sentiment**: bullish, neutral_to_bullish, neutral, neutral_to_bearish, bearish 중 하나
2. **sentiment_score**: 0-100 (50=중립, 70+=강세, 30-=약세)
3. **regime_hint**: MarketRegimeDetector용 힌트 (예: HighVolatility_KOSDAQ_Led, Trend_Following, Mean_Reversion 등)
4. **key_themes**: 핵심 테마 3-5개 (rank, theme, description, impact, duration)
5. **sector_signals**: 섹터별 신호 (semiconductor, automotive, bio, battery, financials 등)
   - signal: bullish/neutral/bearish
   - confidence: 0-100
   - drivers: 상승 요인
   - risks: 하락 요인
6. **risk_factors**: 리스크 요인 리스트
7. **opportunity_factors**: 기회 요인 리스트
8. **key_stocks**: 언급된 주요 종목명 리스트

JSON 형식으로 정리해주세요."""


# ==============================================================================
# 텔레그램 메시지 수집
# ==============================================================================

async def fetch_morning_briefing(hours_ago: int = 24) -> Optional[Dict[str, Any]]:
    """
    @hedgecat0301에서 최신 "장 시작 전 브리핑" 메시지 수집.

    Args:
        hours_ago: 몇 시간 이내 메시지 검색

    Returns:
        {"content": str, "published_at": datetime} 또는 None
    """
    try:
        from collector import collect_channel_messages

        messages = await collect_channel_messages(
            channel_username="hedgecat0301",
            max_messages=5,
            hours_ago=hours_ago,
        )

        # "장 시작 전 생각" 또는 "장 시작 전" 포함 메시지 필터링
        briefings = [
            m for m in messages
            if ("장 시작 전" in m.content) and len(m.content) > 500
        ]

        if not briefings:
            logger.warning("장 시작 전 브리핑 메시지를 찾을 수 없습니다.")
            return None

        latest = briefings[0]
        logger.info(f"브리핑 수집 완료: {latest.published_at.strftime('%Y-%m-%d %H:%M')}, {len(latest.content)} chars")

        return {
            "content": latest.content,
            "published_at": latest.published_at,
        }

    except Exception as e:
        logger.error(f"브리핑 수집 실패: {e}", exc_info=True)
        return None


# ==============================================================================
# 3현자 Council 실행
# ==============================================================================

def run_council_analysis(message_content: str, target_file: str) -> Dict[str, Any]:
    """
    3현자 Council 분석 실행.

    Args:
        message_content: 분석할 메시지 내용
        target_file: 임시 파일 경로

    Returns:
        Council 분석 결과
    """
    import subprocess

    # 요청 파일 생성
    request_content = f"""# Macro Analysis Request

## 분석 대상
- Source: @hedgecat0301 (키움 한지영)
- Type: 장 시작 전 브리핑

---

## 원문 메시지

```
{message_content}
```
"""
    with open(target_file, "w", encoding="utf-8") as f:
        f.write(request_content)

    # Council 스크립트 실행
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "ask_prime_council.py"),
        "--query", MACRO_ANALYSIS_QUERY,
        "--file", target_file,
    ]

    logger.info("3현자 Council 분석 시작...")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=300,  # 5분 타임아웃
    )

    if result.returncode != 0:
        logger.error(f"Council 실행 실패: {result.stderr}")
        return {"error": result.stderr}

    # 생성된 리포트 파일 찾기
    reports_dir = PROJECT_ROOT / ".ai" / "reviews"
    report_files = sorted(reports_dir.glob("council_report_*.md"), reverse=True)

    if not report_files:
        logger.error("Council 리포트 파일을 찾을 수 없습니다.")
        return {"error": "Report not found"}

    latest_report = report_files[0]
    logger.info(f"Council 리포트 생성: {latest_report.name}")

    # 리포트 파싱
    with open(latest_report, "r", encoding="utf-8") as f:
        report_content = f.read()

    # 비용 추출
    cost_match = re.search(r'\*\*\$([0-9.]+)\*\*', report_content)
    cost_usd = float(cost_match.group(1)) if cost_match else 0.0

    return {
        "report_path": str(latest_report),
        "report_content": report_content,
        "cost_usd": cost_usd,
    }


# ==============================================================================
# 결과 파싱
# ==============================================================================

def parse_council_output(report_content: str) -> Dict[str, Any]:
    """
    Council 리포트에서 구조화된 데이터 추출.

    Args:
        report_content: 리포트 마크다운 내용

    Returns:
        파싱된 인사이트 데이터
    """
    result = {
        "sentiment": "neutral",
        "sentiment_score": 50,
        "regime_hint": "",
        "sector_signals": {},
        "key_themes": [],
        "risk_factors": [],
        "opportunity_factors": [],
        "key_stocks": [],
    }

    try:
        # Appendix에서 JSON 추출 시도
        # Minji의 출력에서 구조화된 JSON 찾기
        json_patterns = [
            r'"overall_sentiment":\s*"([^"]+)"',
            r'"sentiment":\s*"([^"]+)"',
        ]

        for pattern in json_patterns:
            match = re.search(pattern, report_content)
            if match:
                result["sentiment"] = match.group(1)
                break

        # sentiment_score 추출
        score_match = re.search(r'"sentiment_score":\s*(\d+)', report_content)
        if score_match:
            result["sentiment_score"] = int(score_match.group(1))

        # regime_hint 추출
        regime_patterns = [
            r'"regime_hint":\s*"([^"]+)"',
            r'Regime Hint[^:]*:\s*[`"]?([^`"\n]+)',
        ]
        for pattern in regime_patterns:
            match = re.search(pattern, report_content, re.IGNORECASE)
            if match:
                result["regime_hint"] = match.group(1).strip()
                break

        # sector_signals 추출 (JSON 블록에서)
        sector_match = re.search(r'"sector_signals":\s*(\{[^}]+\})', report_content, re.DOTALL)
        if sector_match:
            try:
                # 불완전한 JSON 처리
                sector_json = sector_match.group(1)
                # 간단한 파싱 시도
                result["sector_signals"] = json.loads(sector_json)
            except json.JSONDecodeError:
                pass

        # key_themes 추출 (패턴 매칭)
        theme_matches = re.findall(
            r'\*\*Key Theme \d+[^*]*\*\*[:\s-]*([^\n]+)',
            report_content,
            re.IGNORECASE
        )
        if theme_matches:
            result["key_themes"] = [
                {"rank": i + 1, "theme": t.strip(), "impact": "high"}
                for i, t in enumerate(theme_matches[:5])
            ]

        # risk_factors 추출
        risk_section = re.search(
            r'[Rr]isk[s_]*[Ff]actors?[:\s]*\n(.*?)(?=\n\n|\n##|\Z)',
            report_content,
            re.DOTALL
        )
        if risk_section:
            risks = re.findall(r'[-*]\s*\*?\*?([^*\n]+)', risk_section.group(1))
            result["risk_factors"] = [r.strip() for r in risks[:5]]

        # opportunity_factors 추출
        opp_section = re.search(
            r'[Oo]pportunity[_\s]*[Ff]actors?[:\s]*\n(.*?)(?=\n\n|\n##|\Z)',
            report_content,
            re.DOTALL
        )
        if opp_section:
            opps = re.findall(r'[-*]\s*\*?\*?([^*\n]+)', opp_section.group(1))
            result["opportunity_factors"] = [o.strip() for o in opps[:5]]

        # key_stocks 추출 (종목코드 패턴)
        stock_codes = re.findall(r'([가-힣]+)\s*\(\d{6}\.KS\)', report_content)
        stock_names = re.findall(r'(삼성전자|SK하이닉스|현대차|LG에너지솔루션|삼성바이오|카카오|네이버|셀트리온|현대모비스|기아|POSCO홀딩스|KB금융|신한지주|하나금융|삼성SDI|LG화학|엔비디아|메타|애플|MS|마이크론|샌디스크)', report_content)
        result["key_stocks"] = list(set(stock_codes + stock_names))[:10]

        logger.info(f"파싱 결과: sentiment={result['sentiment']}, score={result['sentiment_score']}, regime={result['regime_hint']}")

    except Exception as e:
        logger.error(f"파싱 오류: {e}", exc_info=True)

    return result


# ==============================================================================
# 저장
# ==============================================================================

def save_macro_insight(
    insight_date: date,
    briefing: Dict[str, Any],
    council_result: Dict[str, Any],
    parsed_data: Dict[str, Any],
    dry_run: bool = False,
) -> bool:
    """
    매크로 인사이트 저장 (DB + Redis).

    Args:
        insight_date: 인사이트 날짜
        briefing: 원본 브리핑 데이터
        council_result: Council 분석 결과
        parsed_data: 파싱된 데이터
        dry_run: True면 저장 안함

    Returns:
        저장 성공 여부
    """
    from shared.macro_insight import (
        DailyMacroInsight,
        save_insight_to_db,
        save_insight_to_redis,
    )

    insight = DailyMacroInsight(
        insight_date=insight_date,
        source_channel="hedgecat0301",
        source_analyst="키움 한지영",
        sentiment=parsed_data.get("sentiment", "neutral"),
        sentiment_score=parsed_data.get("sentiment_score", 50),
        regime_hint=parsed_data.get("regime_hint", ""),
        sector_signals=parsed_data.get("sector_signals", {}),
        key_themes=parsed_data.get("key_themes", []),
        risk_factors=parsed_data.get("risk_factors", []),
        opportunity_factors=parsed_data.get("opportunity_factors", []),
        key_stocks=parsed_data.get("key_stocks", []),
        raw_message=briefing.get("content", ""),
        raw_council_output={
            "report_content": council_result.get("report_content", "")[:10000],  # 10KB 제한
        },
        council_cost_usd=council_result.get("cost_usd", 0.0),
    )

    if dry_run:
        logger.info("[DRY RUN] 저장 스킵")
        print("\n" + "=" * 60)
        print("📊 분석 결과 미리보기")
        print("=" * 60)
        print(json.dumps(insight.to_dict(), ensure_ascii=False, indent=2, default=str))
        return True

    # DB 저장
    db_success = save_insight_to_db(insight)

    # Redis 저장
    redis_success = save_insight_to_redis(insight)

    if db_success and redis_success:
        logger.info(f"✅ 매크로 인사이트 저장 완료: {insight_date}")
        return True
    else:
        logger.error(f"저장 실패: DB={db_success}, Redis={redis_success}")
        return False


# ==============================================================================
# Main
# ==============================================================================

async def main(args):
    """메인 실행"""
    logger.info("=" * 60)
    logger.info("🏛️ 3현자 Council 매크로 분석 시작")
    logger.info("=" * 60)

    # 날짜 결정
    if args.date:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        hours_ago = (datetime.now(KST).date() - target_date).days * 24 + 24
    else:
        target_date = datetime.now(KST).date()
        hours_ago = 24

    logger.info(f"분석 대상 날짜: {target_date}")

    # 1. 브리핑 수집
    briefing = await fetch_morning_briefing(hours_ago=hours_ago)
    if not briefing:
        logger.error("브리핑 수집 실패. 종료합니다.")
        return 1

    # 2. Council 분석
    temp_file = PROJECT_ROOT / ".ai" / "reviews" / f"council_request_macro_{target_date}.md"
    council_result = run_council_analysis(briefing["content"], str(temp_file))

    if "error" in council_result:
        logger.error(f"Council 분석 실패: {council_result['error']}")
        return 1

    # 3. 결과 파싱
    parsed_data = parse_council_output(council_result["report_content"])

    # 4. 저장
    save_success = save_macro_insight(
        insight_date=target_date,
        briefing=briefing,
        council_result=council_result,
        parsed_data=parsed_data,
        dry_run=args.dry_run,
    )

    # 결과 출력
    print("\n" + "=" * 60)
    print("📋 매크로 인사이트 요약")
    print("=" * 60)
    print(f"  날짜: {target_date}")
    print(f"  Sentiment: {parsed_data['sentiment']} (Score: {parsed_data['sentiment_score']})")
    print(f"  Regime Hint: {parsed_data['regime_hint']}")
    print(f"  Key Themes: {len(parsed_data['key_themes'])}개")
    print(f"  Sector Signals: {list(parsed_data['sector_signals'].keys())}")
    print(f"  Risk Factors: {parsed_data['risk_factors'][:2]}")
    print(f"  Key Stocks: {parsed_data['key_stocks'][:5]}")
    print(f"  Council Cost: ${council_result.get('cost_usd', 0):.4f}")
    print("=" * 60)

    return 0 if save_success else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="일일 매크로 Council 분석")
    parser.add_argument("--dry-run", action="store_true", help="분석만 실행 (저장 안함)")
    parser.add_argument("--date", type=str, help="분석 날짜 (YYYY-MM-DD, 기본: 오늘)")
    args = parser.parse_args()

    exit_code = asyncio.run(main(args))
    sys.exit(exit_code)
