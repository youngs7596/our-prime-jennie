#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/run_macro_council.py
----------------------------
일일 매크로 인사이트 분석 작업.

매일 07:30 KST에 실행:
1. @hedgecat0301 채널에서 최신 "장 시작 전 브리핑" 수집
2. 3현자 구조화 Council 분석 (전략가→리스크분석가→수석심판)
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
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

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

PROMPTS_DIR = PROJECT_ROOT / "prompts" / "council"


# ==============================================================================
# 컨텍스트 빌더
# ==============================================================================

def _build_context_text(
    message_content: str,
    global_snapshot: Optional[Dict[str, Any]] = None,
    political_news: Optional[List[Dict]] = None,
) -> str:
    """분석 컨텍스트 텍스트 생성 (모든 단계에서 공유)."""

    sections = []

    # 글로벌 매크로 데이터
    if global_snapshot:
        sections.append(f"""## 글로벌 매크로 데이터

### US Economy
- Fed Rate: {global_snapshot.get('fed_rate', 'N/A')}%
- 10Y Treasury: {global_snapshot.get('treasury_10y', 'N/A')}%
- US CPI YoY: {global_snapshot.get('us_cpi_yoy', 'N/A')}%
- Unemployment: {global_snapshot.get('us_unemployment', 'N/A')}%

### Volatility & Risk
- VIX: {global_snapshot.get('vix', 'N/A')} (regime: {global_snapshot.get('vix_regime', 'N/A')})
- Risk-Off: {'예' if global_snapshot.get('is_risk_off') else '아니오'}

### Currency
- DXY Index: {global_snapshot.get('dxy_index', 'N/A')}
- USD/KRW: {global_snapshot.get('usd_krw', 'N/A')}
- 원화 압력: {global_snapshot.get('krw_pressure', 'neutral')}

### Korea
- BOK Rate: {global_snapshot.get('bok_rate') or 'N/A'}%
- 금리차 (Fed-BOK): {global_snapshot.get('rate_differential') or 'N/A'}%
- KOSPI: {global_snapshot.get('kospi_index') or 'N/A'} ({(global_snapshot.get('kospi_change_pct') or 0):+.2f}%)
- KOSDAQ: {global_snapshot.get('kosdaq_index') or 'N/A'} ({(global_snapshot.get('kosdaq_change_pct') or 0):+.2f}%)

### Investor Trading (투자자별 순매수, 억원)
- KOSPI 외국인: {'+' if (global_snapshot.get('kospi_foreign_net') or 0) >= 0 else ''}{(global_snapshot.get('kospi_foreign_net') or 0):,.0f}억
- KOSDAQ 외국인: {'+' if (global_snapshot.get('kosdaq_foreign_net') or 0) >= 0 else ''}{(global_snapshot.get('kosdaq_foreign_net') or 0):,.0f}억
- KOSPI 기관: {'+' if (global_snapshot.get('kospi_institutional_net') or 0) >= 0 else ''}{(global_snapshot.get('kospi_institutional_net') or 0):,.0f}억
- KOSPI 개인: {'+' if (global_snapshot.get('kospi_retail_net') or 0) >= 0 else ''}{(global_snapshot.get('kospi_retail_net') or 0):,.0f}억

### Sentiment
- 글로벌 뉴스: {global_snapshot.get('global_news_sentiment', 'N/A')}
- 한국 뉴스: {global_snapshot.get('korea_news_sentiment', 'N/A')}

### Data Quality
- 완성도: {(global_snapshot.get('completeness_score') or 0):.0%}
- 데이터 소스: {', '.join(global_snapshot.get('data_sources', []))}""")

    # 정치 뉴스
    if political_news:
        news_lines = []
        for i, news in enumerate(political_news[:15], 1):
            line = f"{i}. [{news.get('category', 'news')}] {news.get('title', '')}"
            if news.get('source'):
                line += f" (출처: {news['source']})"
            news_lines.append(line)
        sections.append("## 글로벌 정치/지정학적 뉴스 (최근 24시간)\n\n" + "\n".join(news_lines))

    # 텔레그램 브리핑
    sections.append(f"## 원문 메시지 (텔레그램 브리핑)\n\n{message_content}")

    return "\n\n---\n\n".join(sections)


def _load_prompt(filename: str) -> str:
    """prompts/council/ 디렉토리에서 프롬프트 파일 로드."""
    path = PROMPTS_DIR / filename
    return path.read_text(encoding="utf-8")


# ==============================================================================
# 프로바이더 초기화
# ==============================================================================

def _init_providers():
    """3개 LLM 프로바이더 초기화.

    Returns:
        (strategist, risk_analyst, chief_judge) 튜플
    """
    from shared.llm_providers import ClaudeLLMProvider, CloudFailoverProvider

    # 전략가: DeepSeek v3.2 (CloudFailoverProvider) — 저비용 대량 분석
    strategist = CloudFailoverProvider(tier_name="REASONING")

    # 리스크분석가: DeepSeek v3.2 (동일 프로바이더 재사용)
    risk_analyst = strategist

    # 수석심판: Claude Opus 4.6 (Extended Thinking) — 최종 판단만 수행
    chief_judge = ClaudeLLMProvider()

    return strategist, risk_analyst, chief_judge


# ==============================================================================
# 3단계 구조화 파이프라인
# ==============================================================================

def run_structured_council(
    context_text: str,
    global_snapshot: Optional[Dict[str, Any]] = None,
    political_news: Optional[List[Dict]] = None,
) -> Dict[str, Any]:
    """
    3단계 구조화 Council 파이프라인.

    Step 1: 전략가 (DeepSeek v3.2) → 시장 종합 분석 (저비용)
    Step 2: 리스크분석가 (DeepSeek v3.2) → 전략가 검증 + 리스크 보완 (저비용)
    Step 3: 수석심판 (Claude Opus 4.6, Extended Thinking) → 최종 의사결정

    Returns:
        병합된 Council 결과 dict (DailyMacroInsight 호환)
    """
    from shared.llm_constants import (
        MACRO_STRATEGIST_SCHEMA,
        MACRO_RISK_ANALYST_SCHEMA,
        MACRO_CHIEF_JUDGE_SCHEMA,
    )

    strategist, risk_analyst, chief_judge = _init_providers()
    total_cost = 0.0

    # ------------------------------------------------------------------
    # Step 1: 전략가 (DeepSeek v3.2)
    # ------------------------------------------------------------------
    logger.info("=" * 50)
    logger.info("[Step 1/3] 전략가 분석 (DeepSeek v3.2)")
    logger.info("=" * 50)

    strategist_prompt = _load_prompt("macro_strategist.txt") + "\n\n" + context_text
    strategist_output = None

    try:
        strategist_output = strategist.generate_json(
            prompt=strategist_prompt,
            response_schema=MACRO_STRATEGIST_SCHEMA,
            temperature=0.1,
            service="macro_council",
        )
        logger.info(
            f"전략가 분석 완료: sentiment={strategist_output.get('overall_sentiment')}, "
            f"score={strategist_output.get('sentiment_score')}"
        )
        # DeepSeek v3.2 예상 비용
        total_cost += 0.01
    except Exception as e:
        logger.error(f"전략가(DeepSeek) 실패: {e}")
        # Fallback: Claude Opus 4.6으로 대체
        logger.info("Fallback: Claude Opus 4.6으로 전략가 분석 대체")
        try:
            strategist_output = chief_judge.generate_json_with_thinking(
                prompt=strategist_prompt,
                response_schema=MACRO_STRATEGIST_SCHEMA,
                budget_tokens=4000,
                max_tokens=12000,
                service="macro_council",
            )
            total_cost += 0.35
            logger.info("전략가 Fallback(Claude Opus 4.6) 성공")
        except Exception as e2:
            logger.error(f"전략가 Fallback도 실패: {e2}")
            return {"error": f"전략가 분석 실패: {e} / Fallback: {e2}"}

    # ------------------------------------------------------------------
    # Step 2: 리스크분석가 (DeepSeek v3.2)
    # ------------------------------------------------------------------
    logger.info("=" * 50)
    logger.info("[Step 2/3] 리스크분석가 (DeepSeek v3.2)")
    logger.info("=" * 50)

    risk_prompt = (
        _load_prompt("macro_risk_analyst.txt")
        + "\n\n## 전략가 분석 결과\n\n```json\n"
        + json.dumps(strategist_output, ensure_ascii=False, indent=2)
        + "\n```\n\n"
        + context_text
    )
    risk_output = None

    try:
        risk_output = risk_analyst.generate_json(
            prompt=risk_prompt,
            response_schema=MACRO_RISK_ANALYST_SCHEMA,
            temperature=0.1,
            service="macro_council",
        )
        logger.info(
            f"리스크분석가 완료: political_risk={risk_output.get('political_risk_level')}, "
            f"position={risk_output.get('position_size_pct')}%"
        )
        total_cost += 0.005
    except Exception as e:
        logger.warning(f"리스크분석가(DeepSeek) 실패: {e}. 기본값 사용")
        risk_output = {
            "risk_assessment": {
                "agree_with_sentiment": True,
                "adjusted_sentiment_score": strategist_output.get("sentiment_score", 50),
                "adjustment_reason": "리스크분석가 호출 실패로 전략가 점수 그대로 사용",
            },
            "political_risk_level": "low",
            "political_risk_summary": "리스크분석가 호출 실패 (기본값)",
            "additional_risk_factors": [],
            "position_size_pct": 100,
            "stop_loss_adjust_pct": 100,
            "risk_reasoning": "리스크분석가 호출 실패로 기본값 적용",
        }

    # ------------------------------------------------------------------
    # Step 3: 수석심판 (Claude Opus 4.6, Extended Thinking)
    # ------------------------------------------------------------------
    logger.info("=" * 50)
    logger.info("[Step 3/3] 수석심판 (Claude Opus 4.6, Extended Thinking)")
    logger.info("=" * 50)

    judge_prompt = (
        _load_prompt("macro_chief_judge.txt")
        + "\n\n## 전략가 분석 결과\n\n```json\n"
        + json.dumps(strategist_output, ensure_ascii=False, indent=2)
        + "\n```\n\n## 리스크분석가 분석 결과\n\n```json\n"
        + json.dumps(risk_output, ensure_ascii=False, indent=2)
        + "\n```"
    )
    judge_output = None

    try:
        judge_output = chief_judge.generate_json_with_thinking(
            prompt=judge_prompt,
            response_schema=MACRO_CHIEF_JUDGE_SCHEMA,
            budget_tokens=4000,
            max_tokens=8000,
            service="macro_council",
        )
        logger.info(
            f"수석심판 완료: final_sentiment={judge_output.get('final_sentiment')}, "
            f"consensus={judge_output.get('council_consensus')}"
        )
        # Opus 4.6 수석심판: 입력 많지만 출력 짧음 (~1K tokens)
        total_cost += 0.20
    except Exception as e:
        logger.warning(f"수석심판(Claude) 실패: {e}. Step 1+2 직접 병합")
        # Fallback: 전략가+리스크분석가 결과를 직접 병합
        judge_output = _fallback_judge_output(strategist_output, risk_output)

    # ------------------------------------------------------------------
    # 결과 병합
    # ------------------------------------------------------------------
    merged = merge_council_outputs(strategist_output, risk_output, judge_output)
    merged["cost_usd"] = total_cost

    logger.info(f"Council 분석 완료. 총 비용: ${total_cost:.3f}")
    return merged


def _fallback_judge_output(
    strategist: Dict[str, Any],
    risk: Dict[str, Any],
) -> Dict[str, Any]:
    """수석심판 실패 시 전략가+리스크분석가 결과를 직접 병합."""
    risk_assessment = risk.get("risk_assessment", {})
    return {
        "final_sentiment": strategist.get("overall_sentiment", "neutral"),
        "final_sentiment_score": risk_assessment.get(
            "adjusted_sentiment_score",
            strategist.get("sentiment_score", 50),
        ),
        "final_regime_hint": strategist.get("regime_hint", ""),
        "strategies_to_favor": [],
        "strategies_to_avoid": [],
        "sectors_to_favor": [],
        "sectors_to_avoid": [],
        "final_position_size_pct": risk.get("position_size_pct", 100),
        "final_stop_loss_adjust_pct": risk.get("stop_loss_adjust_pct", 100),
        "trading_reasoning": risk.get("risk_reasoning", "수석심판 실패로 리스크분석가 판단 기준 적용"),
        "council_consensus": "partial_disagree",
    }


def merge_council_outputs(
    strategist: Dict[str, Any],
    risk: Dict[str, Any],
    judge: Dict[str, Any],
) -> Dict[str, Any]:
    """3단계 출력을 DailyMacroInsight 호환 dict로 병합.

    수석심판이 최종 권한 (sentiment, strategies, sectors, position).
    전략가 원본 유지 (risk_factors, opportunity_factors).
    리스크분석가 (political_risk, additional_risk_factors).
    """
    from shared.llm_constants import TRADING_STRATEGIES, SECTOR_GROUPS

    # 전략가 데이터 (원본)
    sector_signals = strategist.get("sector_signals", {})
    risk_factors = strategist.get("risk_factors", [])
    opportunity_factors = strategist.get("opportunity_factors", [])

    # 리스크분석가 추가 리스크
    additional_risks = risk.get("additional_risk_factors", [])
    if additional_risks:
        risk_factors = risk_factors + additional_risks

    # 수석심판 최종 결정
    final_sentiment = judge.get("final_sentiment", "neutral")
    final_score = judge.get("final_sentiment_score", 50)

    # 범위 클램핑
    final_score = max(0, min(100, final_score))
    position_pct = max(50, min(130, judge.get("final_position_size_pct", 100)))
    stop_loss_pct = max(80, min(150, judge.get("final_stop_loss_adjust_pct", 100)))

    # 전략 유효성 검증
    valid_strategies = set(TRADING_STRATEGIES)
    strategies_favor = [s for s in judge.get("strategies_to_favor", []) if s in valid_strategies]
    strategies_avoid = [s for s in judge.get("strategies_to_avoid", []) if s in valid_strategies]

    # 섹터 유효성 검증
    valid_sectors = set(SECTOR_GROUPS)
    sectors_favor = [s for s in judge.get("sectors_to_favor", []) if s in valid_sectors]
    sectors_avoid = [s for s in judge.get("sectors_to_avoid", []) if s in valid_sectors]

    # 정치 리스크 (리스크분석가 판단)
    political_level = risk.get("political_risk_level", "low")
    if political_level not in ("low", "medium", "high", "critical"):
        political_level = "low"

    # regime_hint: DB VARCHAR(50) 안전장치 — 50자 초과 시 truncate
    raw_regime_hint = judge.get("final_regime_hint", strategist.get("regime_hint", ""))
    if len(raw_regime_hint) > 50:
        # 영문 코드라면 50자면 충분. 긴 한국어면 잘라냄
        raw_regime_hint = raw_regime_hint[:47] + "..."

    return {
        # 핵심 sentiment (수석심판 결정)
        "sentiment": final_sentiment,
        "sentiment_score": final_score,
        "regime_hint": raw_regime_hint,
        # 전략가 원본 데이터
        "sector_signals": sector_signals,
        "risk_factors": risk_factors[:10],
        "opportunity_factors": opportunity_factors[:5],
        # 수석심판 트레이딩 권고
        "position_size_pct": position_pct,
        "stop_loss_adjust_pct": stop_loss_pct,
        "strategies_to_favor": strategies_favor,
        "strategies_to_avoid": strategies_avoid,
        "sectors_to_favor": sectors_favor,
        "sectors_to_avoid": sectors_avoid,
        "trading_reasoning": judge.get("trading_reasoning", ""),
        # 리스크분석가 정치 리스크
        "political_risk_level": political_level,
        "political_risk_summary": risk.get("political_risk_summary", ""),
        # Council 메타
        "council_consensus": judge.get("council_consensus", ""),
        "investor_flow_analysis": strategist.get("investor_flow_analysis", ""),
        # 원본 JSON (디버깅용)
        "raw_council_output": {
            "strategist": strategist,
            "risk_analyst": risk,
            "chief_judge": judge,
        },
    }


# ==============================================================================
# 텔레그램 메시지 수집
# ==============================================================================

async def fetch_morning_briefing(target_date: date = None, hours_ago: int = 48) -> Optional[Dict[str, Any]]:
    """
    @hedgecat0301에서 특정 날짜의 브리핑 메시지 수집.

    Args:
        target_date: 분석 대상 날짜 (KST 기준)
        hours_ago: 검색 범위 (기본 48시간)

    Returns:
        {"content": str, "published_at": datetime, "raw_messages": list} 또는 None
    """
    try:
        from collector import collect_channel_messages

        if target_date is None:
            target_date = datetime.now(KST).date()

        messages = await collect_channel_messages(
            channel_username="hedgecat0301",
            max_messages=10,
            hours_ago=hours_ago,
        )

        # 날짜 기준 필터링 (KST 기준으로 target_date에 해당하는 메시지)
        daily_messages = []
        for m in messages:
            msg_date_kst = m.published_at.astimezone(KST).date()
            if msg_date_kst == target_date and len(m.content) > 300:
                daily_messages.append(m)

        if not daily_messages:
            logger.warning(f"{target_date} 날짜의 브리핑 메시지를 찾을 수 없습니다.")
            return None

        # 여러 메시지가 있으면 합쳐서 분석 (가장 긴 것 우선 정렬)
        daily_messages.sort(key=lambda m: len(m.content), reverse=True)

        if len(daily_messages) == 1:
            combined_content = daily_messages[0].content
        else:
            combined_content = f"=== {target_date} 키움증권 한지영 브리핑 ({len(daily_messages)}건) ===\n\n"
            for i, m in enumerate(daily_messages, 1):
                msg_time = m.published_at.astimezone(KST).strftime('%H:%M')
                combined_content += f"--- [{i}] {msg_time} ({len(m.content)}자) ---\n"
                combined_content += m.content + "\n\n"

        logger.info(f"브리핑 수집 완료: {target_date}, {len(daily_messages)}건, 총 {len(combined_content)} chars")

        return {
            "content": combined_content,
            "published_at": daily_messages[0].published_at,
            "raw_messages": daily_messages,
        }

    except Exception as e:
        logger.error(f"브리핑 수집 실패: {e}", exc_info=True)
        return None


# ==============================================================================
# 저장
# ==============================================================================

def save_telegram_briefings(
    insight_date: date,
    raw_messages: list,
    channel_username: str = "hedgecat0301",
    channel_name: str = "한지영 - 키움증권",
    analyst_name: str = "한지영",
) -> int:
    """텔레그램 브리핑 메시지를 DB에 저장."""
    if not raw_messages:
        return 0

    try:
        from shared.db.connection import get_session
        from sqlalchemy import text

        saved_count = 0
        with get_session() as session:
            for msg in raw_messages:
                try:
                    published_at_kst = msg.published_at.astimezone(KST) if msg.published_at.tzinfo else msg.published_at
                    collected_at_kst = msg.collected_at.astimezone(KST) if msg.collected_at.tzinfo else msg.collected_at

                    session.execute(text("""
                        INSERT IGNORE INTO TELEGRAM_BRIEFINGS
                        (MESSAGE_ID, CHANNEL_USERNAME, CHANNEL_NAME, ANALYST_NAME,
                         CONTENT, PUBLISHED_AT, COLLECTED_AT, INSIGHT_DATE)
                        VALUES
                        (:message_id, :channel_username, :channel_name, :analyst_name,
                         :content, :published_at, :collected_at, :insight_date)
                    """), {
                        "message_id": msg.message_id,
                        "channel_username": channel_username,
                        "channel_name": channel_name,
                        "analyst_name": analyst_name,
                        "content": msg.content,
                        "published_at": published_at_kst.replace(tzinfo=None),
                        "collected_at": collected_at_kst.replace(tzinfo=None),
                        "insight_date": insight_date,
                    })
                    saved_count += 1
                except Exception as e:
                    logger.warning(f"메시지 저장 실패 (ID={msg.message_id}): {e}")

            session.commit()

        logger.info(f"텔레그램 메시지 {saved_count}건 저장 완료")
        return saved_count

    except Exception as e:
        logger.error(f"텔레그램 메시지 저장 실패: {e}")
        return 0


async def get_political_news_headlines(max_items: int = 15) -> list:
    """정치/지정학적 뉴스 헤드라인 수집."""
    try:
        from shared.macro_data.clients.political_news_client import PoliticalNewsClient

        client = PoliticalNewsClient()
        try:
            alerts = await client.fetch_alerts(max_age_hours=24, min_severity="medium")

            headlines = []
            seen_titles = set()
            for alert in alerts[:max_items]:
                if alert.title not in seen_titles:
                    headlines.append({
                        "title": alert.title,
                        "source": alert.source,
                        "category": alert.category,
                        "severity": alert.severity,
                    })
                    seen_titles.add(alert.title)

            logger.info(f"정치 뉴스 수집: {len(headlines)}건 (critical: {sum(1 for h in headlines if h.get('severity') == 'critical')})")
            return headlines

        finally:
            await client.close()

    except ImportError:
        logger.warning("PoliticalNewsClient 모듈 없음")
        return []
    except Exception as e:
        logger.warning(f"정치 뉴스 수집 실패: {e}")
        return []


def get_global_macro_snapshot() -> Optional[Dict[str, Any]]:
    """오늘의 글로벌 매크로 스냅샷 조회."""
    try:
        from shared.macro_data import get_today_snapshot

        snapshot = get_today_snapshot()
        if snapshot:
            logger.info(f"글로벌 스냅샷 로드: 완성도 {snapshot.get_completeness_score():.0%}")
            return snapshot.to_dict()
        else:
            logger.warning("오늘 글로벌 스냅샷 없음")
            return None
    except ImportError:
        logger.warning("shared.macro_data 모듈 없음 (글로벌 데이터 스킵)")
        return None
    except Exception as e:
        logger.warning(f"글로벌 스냅샷 조회 실패: {e}")
        return None


def save_macro_insight(
    insight_date: date,
    briefing: Dict[str, Any],
    council_result: Dict[str, Any],
    global_snapshot: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
) -> bool:
    """매크로 인사이트 저장 (DB + Redis)."""
    from shared.macro_insight import (
        DailyMacroInsight,
        save_insight_to_db,
        save_insight_to_redis,
    )

    if global_snapshot is None:
        global_snapshot = get_global_macro_snapshot()

    vix_regime = ""
    rate_differential = None
    data_sources_used = []

    if global_snapshot:
        vix_regime = global_snapshot.get("vix_regime", "")
        rate_differential = global_snapshot.get("rate_differential")
        data_sources_used = global_snapshot.get("data_sources", [])

    # raw_council_output 크기 제한 (10KB)
    raw_output = council_result.get("raw_council_output", {})
    raw_output_str = json.dumps(raw_output, ensure_ascii=False, default=str)
    if len(raw_output_str) > 10000:
        raw_output = {"truncated": True, "size": len(raw_output_str)}

    insight = DailyMacroInsight(
        insight_date=insight_date,
        source_channel="hedgecat0301",
        source_analyst="키움 한지영",
        sentiment=council_result.get("sentiment", "neutral"),
        sentiment_score=council_result.get("sentiment_score", 50),
        regime_hint=council_result.get("regime_hint", ""),
        sector_signals=council_result.get("sector_signals", {}),
        key_themes=[],
        risk_factors=council_result.get("risk_factors", []),
        opportunity_factors=council_result.get("opportunity_factors", []),
        key_stocks=[],
        risk_stocks=[],
        opportunity_stocks=[],
        raw_message=briefing.get("content", ""),
        raw_council_output=raw_output,
        council_cost_usd=council_result.get("cost_usd", 0.0),
        # Enhanced fields
        global_snapshot=global_snapshot,
        data_sources_used=data_sources_used,
        vix_regime=vix_regime,
        rate_differential=rate_differential,
        # Trading Recommendations (수석심판 결정)
        position_size_pct=council_result.get("position_size_pct", 100),
        stop_loss_adjust_pct=council_result.get("stop_loss_adjust_pct", 100),
        strategies_to_favor=council_result.get("strategies_to_favor", []),
        strategies_to_avoid=council_result.get("strategies_to_avoid", []),
        sectors_to_favor=council_result.get("sectors_to_favor", []),
        sectors_to_avoid=council_result.get("sectors_to_avoid", []),
        trading_reasoning=council_result.get("trading_reasoning", ""),
        # Political Risk (리스크분석가 판단)
        political_risk_level=council_result.get("political_risk_level", "low"),
        political_risk_summary=council_result.get("political_risk_summary", ""),
    )

    if dry_run:
        logger.info("[DRY RUN] 저장 스킵")
        print("\n" + "=" * 60)
        print("분석 결과 미리보기")
        print("=" * 60)
        print(json.dumps(insight.to_dict(), ensure_ascii=False, indent=2, default=str))
        return True

    db_success = save_insight_to_db(insight)
    redis_success = save_insight_to_redis(insight)

    if db_success:
        logger.info(f"매크로 인사이트 저장 완료: {insight_date}")
        if not redis_success:
            logger.warning("Redis 캐시 저장 실패 (DB 저장은 성공)")
        return True
    else:
        logger.error("DB 저장 실패")
        return False


# ==============================================================================
# Main
# ==============================================================================

async def main(args):
    """메인 실행"""
    logger.info("=" * 60)
    logger.info("3현자 Council 매크로 분석 시작 (구조화 JSON 파이프라인)")
    logger.info("=" * 60)

    # 날짜 결정
    if args.date:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        hours_ago = (datetime.now(KST).date() - target_date).days * 24 + 24
    else:
        target_date = datetime.now(KST).date()
        hours_ago = 24

    logger.info(f"분석 대상 날짜: {target_date}")

    # 1. 글로벌 매크로 스냅샷 수집
    global_snapshot = get_global_macro_snapshot()
    if global_snapshot:
        logger.info("글로벌 매크로 스냅샷 로드 완료")
        logger.info(f"   - VIX: {global_snapshot.get('vix', 'N/A')} ({global_snapshot.get('vix_regime', 'N/A')})")
        logger.info(f"   - 금리차: {global_snapshot.get('rate_differential', 'N/A')}%")
        logger.info(f"   - KOSPI: {global_snapshot.get('kospi_index', 'N/A')}")
    else:
        logger.warning("글로벌 매크로 스냅샷 없음 (텔레그램 브리핑만 분석)")

    # 2. 텔레그램 브리핑 수집
    briefing = await fetch_morning_briefing(target_date=target_date, hours_ago=hours_ago)
    if not briefing:
        if not global_snapshot:
            logger.warning("브리핑 및 글로벌 매크로 스냅샷 모두 없음. 분석 스킵. (새벽/주말)")
            return 0
        logger.warning("브리핑 없음 (주말/공휴일). 글로벌 매크로 데이터만으로 Council 분석 진행")
        briefing = {
            "content": f"[{target_date}] 텔레그램 브리핑 없음 (주말/공휴일). 글로벌 매크로 데이터만 분석.",
            "published_at": datetime.now(KST),
            "raw_messages": [],
        }

    # 2-1. 텔레그램 메시지 DB 저장
    if not args.dry_run and briefing.get("raw_messages"):
        save_telegram_briefings(
            insight_date=target_date,
            raw_messages=briefing["raw_messages"],
        )

    # 2-2. 정치/지정학적 뉴스 수집
    political_news = await get_political_news_headlines(max_items=15)
    if political_news:
        logger.info(f"정치 뉴스 수집: {len(political_news)}건")
        critical_count = sum(1 for n in political_news if n.get("severity") == "critical")
        if critical_count > 0:
            logger.warning(f"Critical 뉴스 {critical_count}건 감지!")
    else:
        logger.info("정치 뉴스 없음 (또는 수집 실패)")

    # 3. 컨텍스트 빌드 + Council 분석
    context_text = _build_context_text(
        message_content=briefing["content"],
        global_snapshot=global_snapshot,
        political_news=political_news,
    )

    council_result = run_structured_council(
        context_text=context_text,
        global_snapshot=global_snapshot,
        political_news=political_news,
    )

    if "error" in council_result:
        logger.error(f"Council 분석 실패: {council_result['error']}")
        return 1

    # 4. 저장
    save_success = save_macro_insight(
        insight_date=target_date,
        briefing=briefing,
        council_result=council_result,
        global_snapshot=global_snapshot,
        dry_run=args.dry_run,
    )

    # 결과 출력
    print("\n" + "=" * 60)
    print("매크로 인사이트 요약")
    print("=" * 60)
    print(f"  날짜: {target_date}")
    print(f"  Sentiment: {council_result['sentiment']} (Score: {council_result['sentiment_score']})")
    print(f"  Regime Hint: {council_result['regime_hint']}")
    print(f"  Key Themes: {len(council_result.get('key_themes', []))}개")
    print(f"  Sector Signals: {list(council_result.get('sector_signals', {}).keys())}")
    print(f"  Risk Factors: {council_result.get('risk_factors', [])[:2]}")
    print(f"  Risk Factors: {council_result.get('risk_factors', [])[:3]}")
    print(f"  Council Cost: ${council_result.get('cost_usd', 0):.3f}")
    print(f"  Consensus: {council_result.get('council_consensus', 'N/A')}")

    print("\n--- Trading Recommendations (수석심판 결정) ---")
    print(f"  Position Size: {council_result.get('position_size_pct', 100)}%")
    print(f"  Stop Loss Adjust: {council_result.get('stop_loss_adjust_pct', 100)}%")
    print(f"  유리한 전략: {council_result.get('strategies_to_favor', [])}")
    print(f"  피해야 할 전략: {council_result.get('strategies_to_avoid', [])}")
    print(f"  유망 섹터: {council_result.get('sectors_to_favor', [])}")
    print(f"  회피 섹터: {council_result.get('sectors_to_avoid', [])}")
    print(f"  근거: {(council_result.get('trading_reasoning', '') or 'N/A')[:100]}...")

    print("\n--- Political Risk (리스크분석가 판단) ---")
    pol_level = council_result.get('political_risk_level', 'low')
    pol_emoji = {"low": "G", "medium": "Y", "high": "O", "critical": "R"}.get(pol_level, "?")
    print(f"  Risk Level: [{pol_emoji}] {pol_level.upper()}")
    print(f"  요약: {(council_result.get('political_risk_summary', '') or 'N/A')[:150]}")

    if global_snapshot:
        print("\n--- Enhanced Macro Data ---")
        print(f"  VIX: {global_snapshot.get('vix', 'N/A')} ({global_snapshot.get('vix_regime', 'N/A')})")
        print(f"  금리차 (Fed-BOK): {global_snapshot.get('rate_differential', 'N/A')}%")
        print(f"  USD/KRW: {global_snapshot.get('usd_krw', 'N/A')}")
        print(f"  데이터 소스: {', '.join(global_snapshot.get('data_sources', []))}")
    else:
        print("\nEnhanced Macro 데이터 없음")

    print("=" * 60)

    return 0 if save_success else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="일일 매크로 Council 분석")
    parser.add_argument("--dry-run", action="store_true", help="분석만 실행 (저장 안함)")
    parser.add_argument("--date", type=str, help="분석 날짜 (YYYY-MM-DD, 기본: 오늘)")
    args = parser.parse_args()

    exit_code = asyncio.run(main(args))
    sys.exit(exit_code)
