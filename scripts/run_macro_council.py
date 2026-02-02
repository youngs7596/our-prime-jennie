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

MACRO_ANALYSIS_QUERY = """아래 '장 시작 전 브리핑' 메시지와 글로벌 매크로 데이터, 그리고 **글로벌 정치/지정학적 뉴스**를 종합 분석하여 **한국 주식시장(KOSPI/KOSDAQ) 트레이딩**에 대한 인사이트를 추출해주세요.

## 중요 원칙
- VIX 등 미국 지표는 **참고용**으로만 활용 (한국 시장에 직접 적용 X)
- 한국 시장 고유의 수급, 모멘텀, 실적 등을 우선 고려
- 트레이딩 권고는 **한국 시장 맥락**에서 판단
- **정치/지정학적 리스크**가 한국 시장에 미치는 영향을 반드시 평가

## 반드시 포함해야 할 항목 (JSON 형식)

### 시장 분석
1. **overall_sentiment**: bullish, neutral_to_bullish, neutral, neutral_to_bearish, bearish 중 하나
2. **sentiment_score**: 0-100 (50=중립, 70+=강세, 30-=약세)
3. **regime_hint**: 시장 레짐 힌트 (예: KOSDAQ_Momentum, Trend_Following, Mean_Reversion, Defensive 등)
4. **key_themes**: 핵심 테마 3-5개 (rank, theme, description, impact, duration)
5. **sector_signals**: 섹터별 신호 (semiconductor, automotive, bio, battery, financials, shipbuilding, defense 등)
   - signal: bullish/neutral/bearish
   - confidence: 0-100
   - drivers: 상승 요인
   - risks: 하락 요인
6. **risk_factors**: 리스크 요인 리스트
7. **opportunity_factors**: 기회 요인 리스트
8. **key_stocks**: 주목할 종목명 리스트

### 정치/지정학적 리스크 분석
9. **political_risk_level**: low, medium, high, critical 중 하나
   - 미국 행정부 정책 변화 (관세, 제재, 연준 인사 등)
   - 지정학적 긴장 (북한, 중국-대만, 러시아-우크라이나 등)
   - 한국 시장에 직접적 영향이 있는지 판단
10. **political_risk_summary**: 정치 리스크 요약 (1-2문장)
    - 구체적인 이벤트명과 한국 시장 영향 명시

### 트레이딩 권고 (Council이 직접 판단)
11. **position_size_pct**: 권장 포지션 사이즈 (50~130, 기본값 100)
    - 100 = 평소대로, 80 = 20% 축소, 120 = 20% 확대
    - 정치 리스크가 high/critical이면 축소 고려
12. **stop_loss_adjust_pct**: 손절폭 조정 (80~150, 기본값 100)
    - 100 = 평소대로, 130 = 30% 확대 (변동성 대비)
13. **strategies_to_favor**: 오늘 유리한 전략 (아래 목록에서 선택, 이유 포함)
    - GOLDEN_CROSS, RSI_REBOUND, MOMENTUM, RECON_BULL_ENTRY
    - MOMENTUM_CONTINUATION, SHORT_TERM_HIGH_BREAKOUT, VOLUME_BREAKOUT_1MIN
    - BULL_PULLBACK, VCP_BREAKOUT, INSTITUTIONAL_ENTRY
14. **strategies_to_avoid**: 오늘 피해야 할 전략 (위 목록에서 선택, 이유 포함)
15. **sectors_to_favor**: 오늘 유망 섹터 (한국어로)
16. **sectors_to_avoid**: 오늘 회피 섹터 (한국어로)
17. **trading_reasoning**: 위 권고에 대한 종합 근거 (2-3문장, 정치 리스크 포함)

JSON 형식으로 정리해주세요."""


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
        # 메시지의 published_at을 KST로 변환하여 비교
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
            # 여러 메시지 통합
            combined_content = f"=== {target_date} 키움증권 한지영 브리핑 ({len(daily_messages)}건) ===\n\n"
            for i, m in enumerate(daily_messages, 1):
                msg_time = m.published_at.astimezone(KST).strftime('%H:%M')
                combined_content += f"--- [{i}] {msg_time} ({len(m.content)}자) ---\n"
                combined_content += m.content + "\n\n"

        logger.info(f"브리핑 수집 완료: {target_date}, {len(daily_messages)}건, 총 {len(combined_content)} chars")

        return {
            "content": combined_content,
            "published_at": daily_messages[0].published_at,
            "raw_messages": daily_messages,  # DB 저장용
        }

    except Exception as e:
        logger.error(f"브리핑 수집 실패: {e}", exc_info=True)
        return None


# ==============================================================================
# 3현자 Council 실행
# ==============================================================================

def run_council_analysis(
    message_content: str,
    target_file: str,
    global_snapshot: Optional[Dict[str, Any]] = None,
    political_news: Optional[list] = None,
) -> Dict[str, Any]:
    """
    3현자 Council 분석 실행.

    Args:
        message_content: 분석할 메시지 내용
        target_file: 임시 파일 경로
        global_snapshot: 글로벌 매크로 스냅샷 (Enhanced Macro)
        political_news: 정치/지정학적 뉴스 헤드라인 리스트

    Returns:
        Council 분석 결과
    """
    import subprocess

    # 글로벌 매크로 데이터 섹션 생성
    global_data_section = ""
    if global_snapshot:
        global_data_section = f"""
## 글로벌 매크로 데이터 (Enhanced Macro Insight)

> 아래 데이터는 자동 수집된 글로벌 경제 지표입니다.
> 텔레그램 브리핑과 함께 종합적으로 분석해주세요.

### US Economy
- Fed Rate: {global_snapshot.get('fed_rate', 'N/A')}%
- 10Y Treasury: {global_snapshot.get('treasury_10y', 'N/A')}%
- US CPI YoY: {global_snapshot.get('us_cpi_yoy', 'N/A')}%
- Unemployment: {global_snapshot.get('us_unemployment', 'N/A')}%

### Volatility & Risk
- VIX: {global_snapshot.get('vix', 'N/A')} (regime: {global_snapshot.get('vix_regime', 'N/A')})
- Risk-Off 환경: {'예' if global_snapshot.get('is_risk_off') else '아니오'}

### Currency
- DXY Index: {global_snapshot.get('dxy_index', 'N/A')}
- USD/KRW: {global_snapshot.get('usd_krw', 'N/A')}
- 원화 압력: {global_snapshot.get('krw_pressure', 'neutral')}

### Korea
- BOK Rate: {global_snapshot.get('bok_rate') or 'N/A'}%
- 금리차 (Fed-BOK): {global_snapshot.get('rate_differential') or 'N/A'}%
- KOSPI: {global_snapshot.get('kospi_index') or 'N/A'} ({(global_snapshot.get('kospi_change_pct') or 0):+.2f}%)
- KOSDAQ: {global_snapshot.get('kosdaq_index') or 'N/A'} ({(global_snapshot.get('kosdaq_change_pct') or 0):+.2f}%)

### Sentiment
- 글로벌 뉴스 센티먼트: {global_snapshot.get('global_news_sentiment', 'N/A')}
- 한국 뉴스 센티먼트: {global_snapshot.get('korea_news_sentiment', 'N/A')}

### Data Quality
- 완성도: {(global_snapshot.get('completeness_score') or 0):.0%}
- 데이터 소스: {', '.join(global_snapshot.get('data_sources', []))}
- 누락 지표: {', '.join(global_snapshot.get('missing_indicators', [])) or '없음'}

---
"""

    # 정치/지정학적 뉴스 섹션 추가
    political_news_section = ""
    if political_news:
        political_news_section = """
## 글로벌 정치/지정학적 뉴스 (최근 24시간)

> 아래는 시장에 영향을 줄 수 있는 정치/지정학적 뉴스 헤드라인입니다.
> 한국 시장에 미치는 영향을 평가해주세요.

"""
        for i, news in enumerate(political_news[:15], 1):  # 최대 15개
            political_news_section += f"{i}. [{news.get('category', 'news')}] {news.get('title', '')}\n"
            if news.get('source'):
                political_news_section += f"   - 출처: {news['source']}\n"
        political_news_section += "\n---\n"

    # 요청 파일 생성
    request_content = f"""# Macro Analysis Request

## 분석 대상
- Source: @hedgecat0301 (키움 한지영)
- Type: 장 시작 전 브리핑
{global_data_section}{political_news_section}
## 원문 메시지 (텔레그램 브리핑)

```
{message_content}
```
"""
    with open(target_file, "w", encoding="utf-8") as f:
        f.write(request_content)

    # Council 스크립트 실행
    # 명시적으로 sys.executable 사용 (비어있으면 기본 경로 사용)
    python_cmd = sys.executable or "/usr/local/bin/python"
    council_script = str(PROJECT_ROOT / "scripts" / "ask_prime_council.py")

    cmd = [
        python_cmd,
        council_script,
        "--query", MACRO_ANALYSIS_QUERY,
        "--file", str(target_file),
    ]

    logger.info(f"3현자 Council 분석 시작... (python={python_cmd})")

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
        # Trading recommendations (Council이 직접 판단)
        "position_size_pct": 100,  # 기본값 100%
        "stop_loss_adjust_pct": 100,  # 기본값 100%
        "strategies_to_favor": [],
        "strategies_to_avoid": [],
        "sectors_to_favor": [],
        "sectors_to_avoid": [],
        "trading_reasoning": "",
        # Political Risk (Council이 직접 판단)
        "political_risk_level": "low",
        "political_risk_summary": "",
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

        # ========== Trading Recommendations (Council 직접 판단) ==========

        # position_size_pct 추출 (50~130)
        pos_match = re.search(r'"position_size_pct":\s*(\d+)', report_content)
        if pos_match:
            pct = int(pos_match.group(1))
            result["position_size_pct"] = max(50, min(130, pct))  # 범위 제한

        # stop_loss_adjust_pct 추출 (80~150)
        sl_match = re.search(r'"stop_loss_adjust_pct":\s*(\d+)', report_content)
        if sl_match:
            pct = int(sl_match.group(1))
            result["stop_loss_adjust_pct"] = max(80, min(150, pct))

        # strategies_to_favor 추출
        favor_match = re.search(r'"strategies_to_favor":\s*\[(.*?)\]', report_content, re.DOTALL)
        if favor_match:
            strategies = re.findall(r'"([A-Z_]+)"', favor_match.group(1))
            result["strategies_to_favor"] = strategies

        # strategies_to_avoid 추출
        avoid_match = re.search(r'"strategies_to_avoid":\s*\[(.*?)\]', report_content, re.DOTALL)
        if avoid_match:
            strategies = re.findall(r'"([A-Z_]+)"', avoid_match.group(1))
            result["strategies_to_avoid"] = strategies

        # sectors_to_favor 추출
        sec_favor_match = re.search(r'"sectors_to_favor":\s*\[(.*?)\]', report_content, re.DOTALL)
        if sec_favor_match:
            sectors = re.findall(r'"([^"]+)"', sec_favor_match.group(1))
            result["sectors_to_favor"] = [s for s in sectors if s]

        # sectors_to_avoid 추출
        sec_avoid_match = re.search(r'"sectors_to_avoid":\s*\[(.*?)\]', report_content, re.DOTALL)
        if sec_avoid_match:
            sectors = re.findall(r'"([^"]+)"', sec_avoid_match.group(1))
            result["sectors_to_avoid"] = [s for s in sectors if s]

        # trading_reasoning 추출
        reason_match = re.search(r'"trading_reasoning":\s*"([^"]+)"', report_content, re.DOTALL)
        if reason_match:
            result["trading_reasoning"] = reason_match.group(1).strip()

        # ========== Political Risk (Council 직접 판단) ==========

        # political_risk_level 추출 (low, medium, high, critical)
        pol_level_match = re.search(r'"political_risk_level":\s*"([^"]+)"', report_content)
        if pol_level_match:
            level = pol_level_match.group(1).lower().strip()
            if level in ["low", "medium", "high", "critical"]:
                result["political_risk_level"] = level

        # political_risk_summary 추출
        pol_summary_match = re.search(r'"political_risk_summary":\s*"([^"]+)"', report_content, re.DOTALL)
        if pol_summary_match:
            result["political_risk_summary"] = pol_summary_match.group(1).strip()

        logger.info(f"파싱 결과: sentiment={result['sentiment']}, score={result['sentiment_score']}, position={result['position_size_pct']}%, political_risk={result['political_risk_level']}")

    except Exception as e:
        logger.error(f"파싱 오류: {e}", exc_info=True)

    return result


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
    """
    텔레그램 브리핑 메시지를 DB에 저장.

    Args:
        insight_date: 인사이트 날짜
        raw_messages: 수집된 메시지 리스트 (CollectedMessage 객체)
        channel_username: 채널 username
        channel_name: 채널 이름
        analyst_name: 분석가 이름

    Returns:
        저장된 메시지 수
    """
    if not raw_messages:
        return 0

    try:
        from shared.db.connection import get_session
        from sqlalchemy import text

        saved_count = 0
        with get_session() as session:
            for msg in raw_messages:
                try:
                    # UTC -> KST 변환 (Telegram API는 UTC로 반환)
                    published_at_kst = msg.published_at.astimezone(KST) if msg.published_at.tzinfo else msg.published_at
                    collected_at_kst = msg.collected_at.astimezone(KST) if msg.collected_at.tzinfo else msg.collected_at

                    # UPSERT: 이미 있으면 스킵
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
                        "published_at": published_at_kst.replace(tzinfo=None),  # KST로 저장 (timezone 없이)
                        "collected_at": collected_at_kst.replace(tzinfo=None),
                        "insight_date": insight_date,
                    })
                    saved_count += 1
                except Exception as e:
                    logger.warning(f"메시지 저장 실패 (ID={msg.message_id}): {e}")

            session.commit()

        logger.info(f"✅ 텔레그램 메시지 {saved_count}건 저장 완료")
        return saved_count

    except Exception as e:
        logger.error(f"텔레그램 메시지 저장 실패: {e}")
        return 0


async def get_political_news_headlines(max_items: int = 15) -> list:
    """
    정치/지정학적 뉴스 헤드라인 수집.

    PoliticalNewsClient의 키워드 감지 기능을 활용하여
    시장 영향력 있는 뉴스만 필터링합니다.

    Returns:
        [{"title": str, "source": str, "category": str}, ...]
    """
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
    """
    오늘의 글로벌 매크로 스냅샷 조회.

    Returns:
        스냅샷 딕셔너리 또는 None
    """
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
    parsed_data: Dict[str, Any],
    global_snapshot: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
) -> bool:
    """
    매크로 인사이트 저장 (DB + Redis).

    Args:
        insight_date: 인사이트 날짜
        briefing: 원본 브리핑 데이터
        council_result: Council 분석 결과
        parsed_data: 파싱된 데이터
        global_snapshot: 글로벌 매크로 스냅샷 (미리 조회된 경우)
        dry_run: True면 저장 안함

    Returns:
        저장 성공 여부
    """
    from shared.macro_insight import (
        DailyMacroInsight,
        save_insight_to_db,
        save_insight_to_redis,
    )

    # 글로벌 스냅샷이 없으면 조회 시도
    if global_snapshot is None:
        global_snapshot = get_global_macro_snapshot()

    # VIX regime 및 금리차 추출
    vix_regime = ""
    rate_differential = None
    data_sources_used = []

    if global_snapshot:
        vix_regime = global_snapshot.get("vix_regime", "")
        rate_differential = global_snapshot.get("rate_differential")
        data_sources_used = global_snapshot.get("data_sources", [])

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
        # Enhanced fields
        global_snapshot=global_snapshot,
        data_sources_used=data_sources_used,
        vix_regime=vix_regime,
        rate_differential=rate_differential,
        # Trading Recommendations (Council이 직접 판단)
        position_size_pct=parsed_data.get("position_size_pct", 100),
        stop_loss_adjust_pct=parsed_data.get("stop_loss_adjust_pct", 100),
        strategies_to_favor=parsed_data.get("strategies_to_favor", []),
        strategies_to_avoid=parsed_data.get("strategies_to_avoid", []),
        sectors_to_favor=parsed_data.get("sectors_to_favor", []),
        sectors_to_avoid=parsed_data.get("sectors_to_avoid", []),
        trading_reasoning=parsed_data.get("trading_reasoning", ""),
        # Political Risk (Council이 직접 판단)
        political_risk_level=parsed_data.get("political_risk_level", "low"),
        political_risk_summary=parsed_data.get("political_risk_summary", ""),
    )

    if dry_run:
        logger.info("[DRY RUN] 저장 스킵")
        print("\n" + "=" * 60)
        print("📊 분석 결과 미리보기")
        print("=" * 60)
        print(json.dumps(insight.to_dict(), ensure_ascii=False, indent=2, default=str))
        return True

    # DB 저장 (필수)
    db_success = save_insight_to_db(insight)

    # Redis 저장 (선택 - 실패해도 성공으로 처리)
    redis_success = save_insight_to_redis(insight)

    if db_success:
        logger.info(f"✅ 매크로 인사이트 저장 완료: {insight_date}")
        if not redis_success:
            logger.warning("⚠️ Redis 캐시 저장 실패 (DB 저장은 성공)")
        return True
    else:
        logger.error(f"❌ DB 저장 실패")
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

    # 1. 글로벌 매크로 스냅샷 수집 (Enhanced Macro)
    global_snapshot = get_global_macro_snapshot()
    if global_snapshot:
        logger.info(f"✅ 글로벌 매크로 스냅샷 로드 완료")
        logger.info(f"   - VIX: {global_snapshot.get('vix', 'N/A')} ({global_snapshot.get('vix_regime', 'N/A')})")
        logger.info(f"   - 금리차: {global_snapshot.get('rate_differential', 'N/A')}%")
        logger.info(f"   - KOSPI: {global_snapshot.get('kospi_index', 'N/A')}")
    else:
        logger.warning("⚠️ 글로벌 매크로 스냅샷 없음 (텔레그램 브리핑만 분석)")

    # 2. 텔레그램 브리핑 수집 (날짜 기준)
    briefing = await fetch_morning_briefing(target_date=target_date, hours_ago=hours_ago)
    if not briefing:
        logger.error("브리핑 수집 실패. 종료합니다.")
        return 1

    # 2-1. 텔레그램 메시지 DB 저장 (대시보드 표시용)
    if not args.dry_run and briefing.get("raw_messages"):
        save_telegram_briefings(
            insight_date=target_date,
            raw_messages=briefing["raw_messages"],
        )

    # 2-2. 정치/지정학적 뉴스 수집
    political_news = await get_political_news_headlines(max_items=15)
    if political_news:
        logger.info(f"✅ 정치 뉴스 수집: {len(political_news)}건")
        critical_count = sum(1 for n in political_news if n.get("severity") == "critical")
        if critical_count > 0:
            logger.warning(f"⚠️ Critical 뉴스 {critical_count}건 감지!")
    else:
        logger.info("ℹ️ 정치 뉴스 없음 (또는 수집 실패)")

    # 3. Council 분석 (글로벌 데이터 + 텔레그램 브리핑 + 정치 뉴스 통합)
    reviews_dir = PROJECT_ROOT / ".ai" / "reviews"
    reviews_dir.mkdir(parents=True, exist_ok=True)
    temp_file = reviews_dir / f"council_request_macro_{target_date}.md"
    council_result = run_council_analysis(
        briefing["content"],
        str(temp_file),
        global_snapshot=global_snapshot,  # 글로벌 데이터 전달
        political_news=political_news,  # 정치 뉴스 전달
    )

    if "error" in council_result:
        logger.error(f"Council 분석 실패: {council_result['error']}")
        return 1

    # 4. 결과 파싱
    parsed_data = parse_council_output(council_result["report_content"])

    # 5. 저장 (글로벌 스냅샷 포함)
    save_success = save_macro_insight(
        insight_date=target_date,
        briefing=briefing,
        council_result=council_result,
        parsed_data=parsed_data,
        global_snapshot=global_snapshot,  # 이미 조회한 스냅샷 전달
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

    # Trading Recommendations (Council 직접 판단)
    print("\n--- Trading Recommendations (Council 판단) ---")
    print(f"  Position Size: {parsed_data.get('position_size_pct', 100)}%")
    print(f"  Stop Loss Adjust: {parsed_data.get('stop_loss_adjust_pct', 100)}%")
    print(f"  유리한 전략: {parsed_data.get('strategies_to_favor', [])}")
    print(f"  피해야 할 전략: {parsed_data.get('strategies_to_avoid', [])}")
    print(f"  유망 섹터: {parsed_data.get('sectors_to_favor', [])}")
    print(f"  회피 섹터: {parsed_data.get('sectors_to_avoid', [])}")
    print(f"  근거: {(parsed_data.get('trading_reasoning', '') or 'N/A')[:100]}...")

    # Political Risk (Council 직접 판단)
    print("\n--- Political Risk (Council 판단) ---")
    pol_level = parsed_data.get('political_risk_level', 'low')
    pol_emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}.get(pol_level, "⚪")
    print(f"  Risk Level: {pol_emoji} {pol_level.upper()}")
    print(f"  요약: {(parsed_data.get('political_risk_summary', '') or 'N/A')[:150]}")

    # Enhanced Macro 정보
    if global_snapshot:
        print("\n--- Enhanced Macro Data ---")
        print(f"  VIX: {global_snapshot.get('vix', 'N/A')} ({global_snapshot.get('vix_regime', 'N/A')})")
        print(f"  금리차 (Fed-BOK): {global_snapshot.get('rate_differential', 'N/A')}%")
        print(f"  USD/KRW: {global_snapshot.get('usd_krw', 'N/A')}")
        print(f"  데이터 소스: {', '.join(global_snapshot.get('data_sources', []))}")
    else:
        print("\n⚠️ Enhanced Macro 데이터 없음")

    print("=" * 60)

    return 0 if save_success else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="일일 매크로 Council 분석")
    parser.add_argument("--dry-run", action="store_true", help="분석만 실행 (저장 안함)")
    parser.add_argument("--date", type=str, help="분석 날짜 (YYYY-MM-DD, 기본: 오늘)")
    args = parser.parse_args()

    exit_code = asyncio.run(main(args))
    sys.exit(exit_code)
