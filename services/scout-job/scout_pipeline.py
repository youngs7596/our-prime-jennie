# services/scout-job/scout_pipeline.py
# Version: v1.0
# Scout Job Pipeline Tasks - 종목 분석 파이프라인 함수
#
# scout.py에서 분리된 파이프라인 태스크 함수들

import os
import re
import time
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

import shared.database as database
from shared.config import ConfigManager
from shared.monitoring_alerts import get_monitoring_alerts

logger = logging.getLogger(__name__)
_cfg = ConfigManager()


def _utcnow() -> datetime:
    """UTC 현재 시간"""
    return datetime.now(timezone.utc)


def is_hybrid_scoring_enabled() -> bool:
    """Scout v1.0 하이브리드 스코어링 활성화 여부 확인 (SCOUT_V5_ENABLED)"""
    return _cfg.get_bool("SCOUT_V5_ENABLED", default=False)


def process_quant_scoring_task(stock_info, quant_scorer, db_conn, kospi_prices_df=None):
    """
    Step 1: 정량 점수 계산 (LLM 호출 없음, 비용 0원)
    
    세 설계의 핵심 아이디어 구현:
    - Claude: 정량 점수를 LLM과 독립적으로 계산
    - Gemini: 비용 0원으로 1차 필터링
    - GPT: 조건부 승률 기반 점수 산출
    
    Args:
        stock_info: {'code': str, 'info': dict, 'snapshot': dict}
        quant_scorer: QuantScorer 인스턴스
        db_conn: DB 연결 (일봉 데이터 조회용)
        kospi_prices_df: KOSPI 일봉 데이터
    
    Returns:
        QuantScoreResult 객체
    """
    code = stock_info['code']
    info = stock_info['info']
    snapshot = stock_info.get('snapshot', {}) or {}
    
    try:
        # 일봉 데이터 조회
        daily_prices_df = database.get_daily_prices(db_conn, code, limit=150)

        # 데이터 부족 시 is_valid=False 설정 (묻어가기 방지)
        if daily_prices_df.empty or len(daily_prices_df) < 30:
            data_len = len(daily_prices_df) if not daily_prices_df.empty else 0
            logger.debug(f"   ⚠️ [Quant] {info['name']}({code}) 일봉 데이터 부족 ({data_len}일) → is_valid=False")
            from shared.hybrid_scoring import QuantScoreResult
            return QuantScoreResult(
                stock_code=code,
                stock_name=info['name'],
                total_score=0.0,
                momentum_score=0.0,
                quality_score=0.0,
                value_score=0.0,
                technical_score=0.0,
                news_stat_score=0.0,
                supply_demand_score=0.0,
                matched_conditions=[],
                condition_win_rate=None,
                condition_sample_count=0,
                condition_confidence='LOW',
                is_valid=False,
                invalid_reason=f'데이터 부족 ({data_len}일)',
                details={'note': f'데이터 부족 ({data_len}일)'},
            )

        # 투자자 매매 동향 조회 (smart_money_5d 계산용)
        investor_trading_df = None
        try:
            from shared.database.market import get_investor_trading
            investor_trading_df = get_investor_trading(db_conn, code, limit=10)
        except Exception as inv_err:
            logger.debug(f"   ⚠️ [Quant] {code} 투자자 매매 동향 조회 실패: {inv_err}")

        # 정량 점수 계산
        result = quant_scorer.calculate_total_quant_score(
            stock_code=code,
            stock_name=info['name'],
            daily_prices_df=daily_prices_df,
            kospi_prices_df=kospi_prices_df,
            pbr=snapshot.get('pbr'),
            per=snapshot.get('per'),
            current_sentiment_score=info.get('sentiment_score', 50),
            foreign_net_buy=snapshot.get('foreign_net_buy'),
            # 섹터 정보 전달 (scout_universe에서 옴)
            sector=info.get('sector'),
            # 투자자 매매 동향 (smart_money_5d 계산용)
            investor_trading_df=investor_trading_df,
        )
        
        # 역신호 카테고리 체크 로직 제거 (분석 결과 기각됨)
        
        logger.debug(f"   ✅ [Quant] {info['name']}({code}) - {result.total_score:.1f}점")
        return result
        
    except Exception as e:
        logger.error(f"   ❌ [Quant] {code} 정량 점수 계산 오류: {e}")
        from shared.hybrid_scoring import QuantScoreResult
        return QuantScoreResult(
            stock_code=code,
            stock_name=info['name'],
            total_score=0.0,
            momentum_score=0.0,
            quality_score=0.0,
            value_score=0.0,
            technical_score=0.0,
            news_stat_score=0.0,
            supply_demand_score=0.0,
            matched_conditions=[],
            condition_win_rate=None,
            condition_sample_count=0,
            condition_confidence='LOW',
            is_valid=False,
            invalid_reason=f'계산 오류: {str(e)[:30]}',
            details={'error': str(e)},
        )


# Smart Skip Filter - LLM 호출 사전 필터링

def should_skip_hunter(quant_result, 
                       cached_hunter_score: Optional[float] = None,
                       news_sentiment: Optional[float] = None,
                       competitor_bonus: float = 0.0) -> tuple:
    """
    Smart Skip Filter - LLM Hunter 호출 전 사전 필터링
    
    "LLM을 호출해도 Hunter 커트라인(60점)을 넘기지 못할 종목"을 미리 걸러냄.
    
    Args:
        quant_result: QuantScoreResult 객체
        cached_hunter_score: 이전 캐시의 Hunter 점수
        news_sentiment: 뉴스 감성 점수 (-100 ~ +100)
        competitor_bonus: 경쟁사 수혜 가산점 (0~10)
    
    Returns:
        (should_skip: bool, skip_reason: str)
    
    Skip 조건:
    1. Quant Score < 35: 정량 점수가 너무 낮으면 LLM이 봐도 60점 못 넘음
    2. RSI > 75: 과매수 구간 - 매수 타이밍 아님
    3. 뉴스 감성 < -30: 강한 악재 존재
    4. 이전 캐시 Hunter < 40: 어제도 크게 탈락
    
    예외: 경쟁사 수혜 보너스가 있으면 Skip 하지 않음 (반사이익 기회)
    """
    # 경쟁사 수혜가 있으면 Skip 하지 않음 (반사이익 기회)
    if competitor_bonus > 0:
        return False, ""
    
    # 조건 1: Quant Score가 너무 낮음
    smart_skip_quant_min = _cfg.get_float("SMART_SKIP_QUANT_MIN", default=25)
    smart_skip_rsi_max = _cfg.get_float("SMART_SKIP_RSI_MAX", default=80)
    smart_skip_sentiment_min = _cfg.get_float("SMART_SKIP_SENTIMENT_MIN", default=-50)
    smart_skip_cached_hunter_min = _cfg.get_float("SMART_SKIP_CACHED_HUNTER_MIN", default=30)

    if quant_result.total_score < smart_skip_quant_min:
        return True, f"Quant점수 낮음 ({quant_result.total_score:.1f}점 < {smart_skip_quant_min})"
    
    # 조건 2: RSI 과매수 (기술적 점수에서 RSI 추출)
    rsi = quant_result.details.get('rsi')
    if rsi is not None and rsi > smart_skip_rsi_max:
        return True, f"RSI 과매수 ({rsi:.1f} > {smart_skip_rsi_max})"
    
    # 조건 3: 강한 악재 뉴스
    if news_sentiment is not None and news_sentiment < smart_skip_sentiment_min:
        return True, f"악재 뉴스 (감성점수 {news_sentiment})"
    
    # 조건 4: 이전 캐시에서 크게 탈락 (조건 변화 없을 때)
    # 단, 오늘 처음 보는 종목은 스킵하지 않음
    if cached_hunter_score is not None and cached_hunter_score < smart_skip_cached_hunter_min:
        return True, f"이전 Hunter 낮음 ({cached_hunter_score:.0f}점 < {smart_skip_cached_hunter_min})"
    
    return False, ""


def process_phase1_hunter_v5_task(stock_info, brain, quant_result, snapshot_cache=None, news_cache=None, archivist=None, feedback_context=None):
    """
    Phase 1 Hunter - 정량 컨텍스트 포함 LLM 분석
    경쟁사 수혜 점수 반영 포함
    """
    from shared.hybrid_scoring import format_quant_score_for_prompt
    
    code = stock_info['code']
    info = stock_info['info']
    
    # 정량 컨텍스트 생성
    quant_context = format_quant_score_for_prompt(quant_result)
    
    # 경쟁사 수혜 점수 조회
    competitor_benefit = database.get_competitor_benefit_score(code)
    competitor_bonus = competitor_benefit.get('score', 0)
    competitor_reason = competitor_benefit.get('reason', '')
    
    snapshot = snapshot_cache.get(code) if snapshot_cache else None
    if not snapshot:
        return {
            'code': code,
            'name': info['name'],
            'info': info,
            'snapshot': None,
            'quant_result': quant_result,
            'hunter_score': 0,
            'hunter_reason': '스냅샷 조회 실패',
            'passed': False,
            'competitor_bonus': competitor_bonus,
        }
    
    news_from_vectorstore = news_cache.get(code, "최근 관련 뉴스 없음") if news_cache else "뉴스 캐시 없음"
    
    # 경쟁사 수혜 정보를 뉴스에 추가
    if competitor_bonus > 0:
        news_from_vectorstore += f"\n\n⚡ [경쟁사 수혜 기회] {competitor_reason} (+{competitor_bonus}점)"
    
    decision_info = {
        'code': code,
        'name': info['name'],
        'technical_reason': 'N/A',
        'news_reason': news_from_vectorstore if news_from_vectorstore not in ["뉴스 DB 미연결", "뉴스 검색 오류"] else ', '.join(info.get('reasons', [])),
        'per': snapshot.get('per'),
        'pbr': snapshot.get('pbr'),
        'market_cap': snapshot.get('market_cap'),
    }
    
    # 정량 컨텍스트 포함 Hunter 호출
    hunter_result = brain.get_jennies_analysis_score_v5(decision_info, quant_context, feedback_context)
    hunter_score = hunter_result.get('score', 0)
    hunter_reason = hunter_result.get('reason', '')
    
    # [AI Auditor 제거됨] Cloud LLM 비용 절감을 위해 Fact-Checker 기능 비활성화
    
    # 경쟁사 수혜 가산점 적용 (최대 +10점)
    if competitor_bonus > 0:
        hunter_score = min(100, hunter_score + competitor_bonus)
        # 로그는 아래 상세 로그에서 출력
    
    passed = hunter_score >= 60
    if hunter_score == 0: passed = False
    
    # 상세 로그 생성
    def _build_hunter_detail_log():
        """Hunter 분석 상세 로그 생성 (옵션 B 스타일)"""
        lines = []
        
        # 1. 정량 점수 분해
        quant_breakdown = (
            f"모멘텀:{quant_result.momentum_score:.1f}/25 | "
            f"품질:{quant_result.quality_score:.1f}/20 | "
            f"가치:{quant_result.value_score:.1f}/15 | "
            f"기술:{quant_result.technical_score:.1f}/10 | "
            f"뉴스:{quant_result.news_stat_score:.1f}/15 | "
            f"수급:{quant_result.supply_demand_score:.1f}/15"
        )
        lines.append(f"   📊 정량점수 분해: {quant_breakdown}")
        
        # 2. 핵심 지표 (details에서 추출)
        details = quant_result.details or {}
        tech_details = details.get('technical', {})
        value_details = details.get('value', {})
        supply_details = details.get('supply_demand', {})
        
        rsi = tech_details.get('rsi')
        per = value_details.get('per')
        pbr = value_details.get('pbr')
        foreign_ratio = supply_details.get('foreign_ratio')  # 거래량 대비 %
        
        indicators = []
        if per is not None:
            indicators.append(f"PER:{per:.1f}")
        if pbr is not None:
            indicators.append(f"PBR:{pbr:.2f}")
        if rsi is not None:
            indicators.append(f"RSI:{rsi:.0f}")
        if foreign_ratio is not None:
            sign = "+" if foreign_ratio > 0 else ""
            indicators.append(f"외인순매수:{sign}{foreign_ratio:.1f}%")
        
        if indicators:
            lines.append(f"   📈 핵심지표: {' | '.join(indicators)}")
        
        # 3. 경쟁사 수혜 (있는 경우)
        if competitor_bonus > 0:
            lines.append(f"   🎯 경쟁사 수혜: +{competitor_bonus}점 ({competitor_reason})")
        
        return "\n".join(lines)
    
    if passed:
        logger.info(f"   ✅ [Hunter 통과] {info['name']}({code}) - Hunter: {hunter_score}점 (Quant: {quant_result.total_score:.0f}점)")
        logger.info(_build_hunter_detail_log())
    else:
        logger.debug(f"   ❌ [Hunter 탈락] {info['name']}({code}) - Hunter: {hunter_score}점 (Quant: {quant_result.total_score:.0f}점)")
        logger.debug(_build_hunter_detail_log())
        
        # [Priority 2] Shadow Radar Logging
        if archivist and hunter_score > 0: # 0점은 에러/데이터부족일 수 있으므로 제외할지 고민 -> 일단 0점도 기록하되 reason 확인
            try:
                shadow_data = {
                    'stock_code': code,
                    'stock_name': info['name'],
                    'rejection_stage': 'HUNTER',
                    'rejection_reason': hunter_result.get('reason', 'Hunter Score 미달'),
                    'hunter_score_at_time': hunter_score,
                    'trigger_type': 'FILTER_REJECT',
                    'trigger_value': float(hunter_score)
                }
                archivist.log_shadow_radar(shadow_data)
            except Exception as e:
                logger.warning(f"Failed to log shadow radar for {code}: {e}")
    
    return {
        'code': code,
        'name': info['name'],
        'info': info,
        'snapshot': snapshot,
        'decision_info': decision_info,
        'quant_result': quant_result,
        'hunter_score': hunter_score,
        'hunter_reason': hunter_result.get('reason', ''),
        'passed': passed,
        'competitor_bonus': competitor_bonus,
        'competitor_reason': competitor_reason,
    }


def process_phase23_judge_v5_task(phase1_result, brain, archivist=None, market_regime="UNKNOWN", feedback_context=None):
    """
    Phase 2-3: Debate + Judge (정량 컨텍스트 포함)
    
    정량 분석 결과를 Judge 프롬프트에 포함하여
    하이브리드 점수를 산출합니다.
    """
    from shared.hybrid_scoring import format_quant_score_for_prompt
    
    code = phase1_result['code']
    info = phase1_result['info']
    decision_info = phase1_result['decision_info']
    quant_result = phase1_result['quant_result']
    hunter_score = phase1_result['hunter_score']
    
    logger.info(f"   🔄 [Phase 2-3] {info['name']}({code}) Debate-Judge 시작...")
    
    # 정량 컨텍스트 생성
    quant_context = format_quant_score_for_prompt(quant_result)
    
    # Phase 2: Debate (Bull vs Bear) - Dynamic Roles based on Hunter Score
    debate_log = brain.run_debate_session(decision_info, hunter_score=hunter_score)
    
    # Phase 3: Judge (정량 컨텍스트 포함)
    # Inject hunter_score into decision_info for Gatekeeper Check
    decision_info['hunter_score'] = hunter_score
    judge_result = brain.run_judge_scoring_v5(decision_info, debate_log, quant_context, feedback_context)
    score = judge_result.get('score', 0)
    grade = judge_result.get('grade', 'D')
    risk_tag = judge_result.get('risk_tag', 'NEUTRAL')
    reason = judge_result.get('reason', '분석 실패')

    # risk_tag 유효성 검증 (LLM이 잘못된 값 반환 시 NEUTRAL로 폴백)
    valid_risk_tags = {'BULLISH', 'NEUTRAL', 'CAUTION', 'DISTRIBUTION_RISK'}
    if risk_tag not in valid_risk_tags:
        logger.warning(f"   ⚠️ [risk_tag] 유효하지 않은 값 '{risk_tag}' → NEUTRAL로 폴백")
        risk_tag = 'NEUTRAL'

    # 하이브리드 점수 계산 (정량 60% + 정성 40%)
    quant_score = quant_result.total_score
    llm_score = score

    # [P2-2] Safety Lock 비대칭 구조
    score_diff = abs(quant_score - llm_score)
    if score_diff >= 30:
        if quant_score < llm_score:
            # LLM이 지나치게 낙관 → 정량 중심 (과잉 낙관 억제)
            hybrid_score = quant_score * 0.75 + llm_score * 0.25
            logger.warning(f"   ⚠️ [Safety Lock] {info['name']} - 정량({quant_score:.0f}) << 정성({llm_score}) → 과잉낙관 억제")
        else:
            # LLM이 경고 (낮은 점수) → LLM 의견 존중 (경고 무시 방지)
            hybrid_score = quant_score * 0.40 + llm_score * 0.60
            logger.warning(f"   ⚠️ [Safety Lock] {info['name']} - 정성({llm_score}) << 정량({quant_score:.0f}) → LLM 경고 존중")
    elif llm_score < 40:
        # LLM이 명시적 경고 (40점 미만) → LLM 가중치 상향
        hybrid_score = quant_score * 0.45 + llm_score * 0.55
        logger.info(f"   ⚠️ [LLM Warning] {info['name']} - LLM({llm_score})<40 → LLM 경고 가중")
    else:
        hybrid_score = quant_score * 0.60 + llm_score * 0.40

    is_tradable = hybrid_score >= 75
    approved = hybrid_score >= 50

    # [P2-1] Veto Power: DISTRIBUTION_RISK → 워치리스트 제외
    veto_applied = False
    if risk_tag == 'DISTRIBUTION_RISK':
        veto_applied = True
        is_tradable = False
        approved = False
        logger.warning(
            f"   🚫 [VETO] {info['name']}({code}) - DISTRIBUTION_RISK 감지 → 거래 차단 "
            f"(hybrid={hybrid_score:.1f}, LLM={llm_score})"
        )

    # -------------------------------------------------------------------------
    # [Project Recon] Trade Tier 산정
    # - TIER1: Judge 통과 (is_tradable=True, hybrid >= 75)
    # - RECON: hybrid 60~74 + "추세 신호" 존재 → 소액 정찰 진입 후보
    # - BLOCKED: 그 외
    #
    # NOTE:
    # - is_tradable의 의미(=Judge 통과)는 유지합니다.
    # - trade_tier는 llm_metadata에 저장되어 buy-scanner/buy-executor에서 활용합니다.
    # -------------------------------------------------------------------------
    recon_signals: list[str] = []
    try:
        details = getattr(quant_result, "details", {}) or {}
        tech_details = details.get("technical", {}) or {}

        volume_ratio = tech_details.get("volume_ratio")
        ma20_slope_5d = tech_details.get("ma20_slope_5d")

        if tech_details.get("golden_cross_5_20"):
            recon_signals.append("GOLDEN_CROSS_5_20")
        recon_volume_min = _cfg.get_float("RECON_VOLUME_RATIO_MIN", default=1.5)
        if isinstance(volume_ratio, (int, float)) and volume_ratio >= recon_volume_min:
            recon_signals.append(f"VOLUME_TREND_{float(volume_ratio):.2f}x")
        if isinstance(ma20_slope_5d, (int, float)) and float(ma20_slope_5d) > 0:
            recon_signals.append("MA20_SLOPE_UP")

        mom = getattr(quant_result, "momentum_score", None)
        recon_mom_min = _cfg.get_float("RECON_MOMENTUM_MIN", default=20)
        if mom is not None and float(mom) >= recon_mom_min:
            recon_signals.append(f"MOMENTUM_{float(mom):.1f}/25")
    except Exception:
        recon_signals = []

    is_recon = (60 <= hybrid_score < 75) and bool(recon_signals)

    # [Project Recon] RECON tier도 거래 가능(is_tradable=True)으로 설정
    # 단, trade_tier로 TIER1과 구분하여 buy-executor에서 비중/손절 차등 적용
    if is_recon and not veto_applied:
        is_tradable = True

    # Veto가 적용되면 무조건 BLOCKED
    if veto_applied:
        trade_tier = "BLOCKED"
    else:
        trade_tier = "TIER1" if (hybrid_score >= 75) else ("RECON" if is_recon else "BLOCKED")
    
    # [Market Regime] 하락장/횡보장은 기준을 낮추는 대신, 오히려 관망(No Trade)이 최선일 수 있음.
    # 사용자의 지적대로 "억지로 거래를 만드는 것"은 리스크를 키우므로 원복함.
    
    if hybrid_score >= 80:
        final_grade = 'S'
    elif hybrid_score >= 70:
        final_grade = 'A'
    elif hybrid_score >= 60:
        final_grade = 'B'
    elif hybrid_score >= 50:
        final_grade = 'C'
    else:
        final_grade = 'D'
    
    # 상세 로그 생성
    def _build_judge_detail_log():
        """Judge 분석 상세 로그 생성 (옵션 B 스타일)"""
        lines = []

        # 1. 점수 흐름
        if llm_score < 40 and score_diff < 30:
            weight_info = "(LLM Warning 45:55)"
        elif score_diff >= 30:
            weight_info = "(Safety Lock)"
        else:
            weight_info = "(60:40)"
        lines.append(f"   📊 점수 흐름: Hunter:{hunter_score} → Quant:{quant_score:.0f} + LLM:{llm_score} = Hybrid:{hybrid_score:.1f} {weight_info}")

        # 2. risk_tag 표시
        tag_emoji = {"BULLISH": "🟢", "NEUTRAL": "⚪", "CAUTION": "🟡", "DISTRIBUTION_RISK": "🔴"}.get(risk_tag, "⚪")
        veto_str = " → VETO 발동!" if veto_applied else ""
        lines.append(f"   🏷️ Risk Tag: {tag_emoji} {risk_tag}{veto_str}")

        # 3. Judge 판단 이유 (reason 축약 - 최대 60자)
        reason_short = reason[:60] + "..." if len(reason) > 60 else reason
        lines.append(f"   💬 Judge 판단: {reason_short}")

        # 4. 거래 가능 여부
        tradable_emoji = "✅" if is_tradable else "❌"
        lines.append(f"   ⚡ 거래 가능: {tradable_emoji} (75점 기준)")

        return "\n".join(lines)
    
    if approved:
        logger.info(f"   ✅ [Judge 승인] {info['name']}({code}) - 최종: {hybrid_score:.1f}점 ({final_grade}등급)")
        logger.info(_build_judge_detail_log())
    else:
        logger.info(f"   ❌ [Judge 거절] {info['name']}({code}) - 최종: {hybrid_score:.1f}점 ({final_grade}등급)")
        logger.info(_build_judge_detail_log())
        
        # [Priority 2] Shadow Radar Logging (Judge Reject)
        if archivist:
            try:
                shadow_data = {
                    'stock_code': code,
                    'stock_name': info['name'],
                    'rejection_stage': 'JUDGE',
                    'rejection_reason': f"Hybrid Score 미달 ({hybrid_score:.1f}) - {reason}",
                    'hunter_score_at_time': hunter_score,
                    'trigger_type': 'JUDGE_REJECT',
                    'trigger_value': float(hybrid_score)
                }
                archivist.log_shadow_radar(shadow_data)
            except Exception as e:
                logger.warning(f"Failed to log shadow radar for {code}: {e}")
    
    metadata = {
        'llm_grade': final_grade,
        'llm_updated_at': _utcnow().isoformat(),
        'source': 'hybrid_scorer_v5',
        'quant_score': quant_score,
        'llm_raw_score': llm_score,
        'hybrid_score': hybrid_score,
        'hunter_score': hunter_score,
        'condition_win_rate': quant_result.condition_win_rate,
        # Project Recon
        'trade_tier': trade_tier,
        'recon_signals': recon_signals,
        # P2-1: risk_tag & Veto
        'risk_tag': risk_tag,
        'veto_applied': veto_applied,
    }
    
    # 스냅샷에서 재무 데이터 추출
    snapshot = phase1_result.get('snapshot') or {}
    
    # [Priority 1] Log to Decision Ledger (Archivist)
    if archivist:
        try:
            # Determine Final Decision
            final_decision = "HOLD"
            if approved:
                final_decision = "BUY"
            
            # Extract keywords from info['reasons'] (simple heuristic)
            reasons = info.get('reasons', [])
            keywords = []
            for r in reasons:
                keywords.extend([w for w in r.split() if len(w) > 1][:3])

            ledger_data = {
                'stock_code': code,
                'stock_name': info['name'],
                'hunter_score': hunter_score,
                'market_regime': market_regime,
                'dominant_keywords': keywords,
                'debate_log': debate_log,
                'counter_position_logic': debate_log[:500] if debate_log else None, # Placeholder for explicit extraction
                'thinking_called': 1 if judge_result.get('grade') != 'D' else 0, # Rough proxy
                'thinking_reason': "Judge_v5",
                'cost_estimate': 0.0, # Placeholder
                'gate_result': 'PASS' if score > 0 else 'REJECT',
                'final_decision': final_decision,
                'final_reason': reason
            }
            archivist.log_decision_ledger(ledger_data)
        except Exception as e:
            logger.error(f"   ⚠️ [Archivist] Failed to log decision: {e}")

    return {
        'code': code,
        'name': info['name'],
        'is_tradable': is_tradable,
        'llm_score': hybrid_score,
        'llm_reason': reason,
        'approved': approved,
        'llm_metadata': metadata,
        'trade_tier': trade_tier,
        # 재무 데이터 추가
        'per': snapshot.get('per'),
        'pbr': snapshot.get('pbr'),
        'roe': snapshot.get('roe'),
        'market_cap': snapshot.get('market_cap'),
        'sales_growth': snapshot.get('sales_growth'),
        'eps_growth': snapshot.get('eps_growth'),
    }


def process_unified_analyst_task(stock_info, brain, quant_result, snapshot_cache=None,
                                 news_cache=None, archivist=None, feedback_context=None,
                                 market_regime="UNKNOWN"):
    """
    통합 Analyst 1-pass 파이프라인 — Hunter+Debate+Judge를 1회 LLM 호출로 통합

    기존 process_phase1_hunter_v5_task() + process_phase23_judge_v5_task() 통합.
    비용 1/3, 토큰 1/3, risk_tag는 코드 기반.

    Args:
        stock_info: {'code': str, 'info': dict}
        brain: JennieBrain 인스턴스
        quant_result: QuantScoreResult
        snapshot_cache: 스냅샷 캐시 dict
        news_cache: 뉴스 캐시 dict
        archivist: Archivist 인스턴스 (선택)
        feedback_context: 전략 피드백 (선택)
        market_regime: 시장 국면 문자열

    Returns:
        dict with keys: code, name, is_tradable, llm_score, llm_reason, approved,
                        llm_metadata, trade_tier, per, pbr, roe, market_cap, ...
    """
    from shared.hybrid_scoring import format_quant_score_for_prompt, classify_risk_tag

    code = stock_info['code']
    info = stock_info['info']

    # --- 1. 데이터 준비 (기존 Phase 1 로직) ---
    quant_context = format_quant_score_for_prompt(quant_result)

    # 경쟁사 수혜 점수 조회
    competitor_benefit = database.get_competitor_benefit_score(code)
    competitor_bonus = competitor_benefit.get('score', 0)
    competitor_reason = competitor_benefit.get('reason', '')

    snapshot = snapshot_cache.get(code) if snapshot_cache else None
    if not snapshot:
        return {
            'code': code, 'name': info['name'], 'is_tradable': False,
            'llm_score': 0, 'llm_reason': '스냅샷 조회 실패', 'approved': False,
            'llm_metadata': {'source': 'unified_analyst_error'}, 'trade_tier': 'BLOCKED',
        }

    news_from_vectorstore = news_cache.get(code, "최근 관련 뉴스 없음") if news_cache else "뉴스 캐시 없음"

    if competitor_bonus > 0:
        news_from_vectorstore += f"\n\n⚡ [경쟁사 수혜 기회] {competitor_reason} (+{competitor_bonus}점)"

    decision_info = {
        'code': code,
        'name': info['name'],
        'technical_reason': 'N/A',
        'news_reason': news_from_vectorstore if news_from_vectorstore not in [
            "뉴스 DB 미연결", "뉴스 검색 오류"] else ', '.join(info.get('reasons', [])),
        'per': snapshot.get('per'),
        'pbr': snapshot.get('pbr'),
        'market_cap': snapshot.get('market_cap'),
    }

    # --- 2. 통합 Analyst 1회 호출 ---
    analyst_result = brain.run_analyst_scoring(decision_info, quant_context, feedback_context)
    raw_llm_score = analyst_result.get('score', 0)
    reason = analyst_result.get('reason', '분석 실패')

    # --- 3. ±15pt 가드레일 ---
    quant_score = quant_result.total_score
    llm_score = max(quant_score - 15, min(quant_score + 15, raw_llm_score))

    # 경쟁사 수혜 가산점 적용 (가드레일 이후)
    if competitor_bonus > 0:
        llm_score = min(100, llm_score + competitor_bonus)

    # --- 4. 코드 기반 risk_tag ---
    risk_tag = classify_risk_tag(quant_result)

    # --- 5. 하이브리드 점수 (기존 Safety Lock / Veto 동일) ---
    score_diff = abs(quant_score - llm_score)
    if score_diff >= 30:
        if quant_score < llm_score:
            hybrid_score = quant_score * 0.75 + llm_score * 0.25
            logger.warning(f"   ⚠️ [Safety Lock] {info['name']} - 정량({quant_score:.0f}) << 정성({llm_score}) → 과잉낙관 억제")
        else:
            hybrid_score = quant_score * 0.40 + llm_score * 0.60
            logger.warning(f"   ⚠️ [Safety Lock] {info['name']} - 정성({llm_score}) << 정량({quant_score:.0f}) → LLM 경고 존중")
    elif llm_score < 40:
        hybrid_score = quant_score * 0.45 + llm_score * 0.55
        logger.info(f"   ⚠️ [LLM Warning] {info['name']} - LLM({llm_score})<40 → LLM 경고 가중")
    else:
        hybrid_score = quant_score * 0.60 + llm_score * 0.40

    is_tradable = hybrid_score >= 75
    approved = hybrid_score >= 50

    # [Veto Power] DISTRIBUTION_RISK → 거래 차단
    veto_applied = False
    if risk_tag == 'DISTRIBUTION_RISK':
        veto_applied = True
        is_tradable = False
        approved = False
        logger.warning(
            f"   🚫 [VETO] {info['name']}({code}) - DISTRIBUTION_RISK 감지 → 거래 차단 "
            f"(hybrid={hybrid_score:.1f}, LLM={llm_score})"
        )

    # --- 6. Trade Tier 산정 (기존 로직 동일) ---
    recon_signals: list = []
    try:
        details = getattr(quant_result, "details", {}) or {}
        tech_details = details.get("technical", {}) or {}

        volume_ratio = tech_details.get("volume_ratio")
        ma20_slope_5d = tech_details.get("ma20_slope_5d")

        if tech_details.get("golden_cross_5_20"):
            recon_signals.append("GOLDEN_CROSS_5_20")
        recon_volume_min = _cfg.get_float("RECON_VOLUME_RATIO_MIN", default=1.5)
        if isinstance(volume_ratio, (int, float)) and volume_ratio >= recon_volume_min:
            recon_signals.append(f"VOLUME_TREND_{float(volume_ratio):.2f}x")
        if isinstance(ma20_slope_5d, (int, float)) and float(ma20_slope_5d) > 0:
            recon_signals.append("MA20_SLOPE_UP")

        mom = getattr(quant_result, "momentum_score", None)
        recon_mom_min = _cfg.get_float("RECON_MOMENTUM_MIN", default=20)
        if mom is not None and float(mom) >= recon_mom_min:
            recon_signals.append(f"MOMENTUM_{float(mom):.1f}/25")
    except Exception:
        recon_signals = []

    is_recon = (60 <= hybrid_score < 75) and bool(recon_signals)

    if is_recon and not veto_applied:
        is_tradable = True

    if veto_applied:
        trade_tier = "BLOCKED"
    else:
        trade_tier = "TIER1" if (hybrid_score >= 75) else ("RECON" if is_recon else "BLOCKED")

    # 등급
    if hybrid_score >= 80:
        final_grade = 'S'
    elif hybrid_score >= 70:
        final_grade = 'A'
    elif hybrid_score >= 60:
        final_grade = 'B'
    elif hybrid_score >= 50:
        final_grade = 'C'
    else:
        final_grade = 'D'

    # 로그
    tag_emoji = {"BULLISH": "🟢", "NEUTRAL": "⚪", "CAUTION": "🟡", "DISTRIBUTION_RISK": "🔴"}.get(risk_tag, "⚪")
    veto_str = " → VETO 발동!" if veto_applied else ""
    if approved:
        logger.info(f"   ✅ [Analyst 승인] {info['name']}({code}) - 최종: {hybrid_score:.1f}점 ({final_grade}등급) | {tag_emoji}{risk_tag}{veto_str}")
    else:
        logger.info(f"   ❌ [Analyst 거절] {info['name']}({code}) - 최종: {hybrid_score:.1f}점 ({final_grade}등급) | {tag_emoji}{risk_tag}{veto_str}")

    # Shadow Radar Logging
    if archivist and not approved:
        try:
            shadow_data = {
                'stock_code': code,
                'stock_name': info['name'],
                'rejection_stage': 'UNIFIED_ANALYST',
                'rejection_reason': f"Hybrid Score 미달 ({hybrid_score:.1f}) - {reason}",
                'hunter_score_at_time': llm_score,
                'trigger_type': 'ANALYST_REJECT',
                'trigger_value': float(hybrid_score)
            }
            archivist.log_shadow_radar(shadow_data)
        except Exception as e:
            logger.warning(f"Failed to log shadow radar for {code}: {e}")

    metadata = {
        'llm_grade': final_grade,
        'llm_updated_at': _utcnow().isoformat(),
        'source': 'unified_analyst',
        'quant_score': quant_score,
        'llm_raw_score': raw_llm_score,
        'llm_clamped_score': llm_score,
        'hybrid_score': hybrid_score,
        'hunter_score': llm_score,  # 하위호환: hunter_score = clamped llm_score
        'condition_win_rate': quant_result.condition_win_rate,
        'trade_tier': trade_tier,
        'recon_signals': recon_signals,
        'risk_tag': risk_tag,
        'veto_applied': veto_applied,
    }

    # Decision Ledger
    if archivist:
        try:
            reasons = info.get('reasons', [])
            keywords = []
            for r in reasons:
                keywords.extend([w for w in r.split() if len(w) > 1][:3])

            ledger_data = {
                'stock_code': code,
                'stock_name': info['name'],
                'hunter_score': llm_score,
                'market_regime': market_regime,
                'dominant_keywords': keywords,
                'debate_log': None,  # Debate 없음
                'counter_position_logic': None,
                'thinking_called': 0,
                'thinking_reason': "Unified_Analyst",
                'cost_estimate': 0.0,
                'gate_result': 'PASS' if approved else 'REJECT',
                'final_decision': 'BUY' if approved else 'HOLD',
                'final_reason': reason
            }
            archivist.log_decision_ledger(ledger_data)
        except Exception as e:
            logger.error(f"   ⚠️ [Archivist] Failed to log decision: {e}")

    return {
        'code': code,
        'name': info['name'],
        'is_tradable': is_tradable,
        'llm_score': hybrid_score,
        'llm_reason': reason,
        'approved': approved,
        'llm_metadata': metadata,
        'trade_tier': trade_tier,
        'per': snapshot.get('per'),
        'pbr': snapshot.get('pbr'),
        'roe': snapshot.get('roe'),
        'market_cap': snapshot.get('market_cap'),
        'sales_growth': snapshot.get('sales_growth'),
        'eps_growth': snapshot.get('eps_growth'),
    }


def fetch_kis_data_task(stock, kis_api):
    """KIS API로부터 종목 데이터 조회"""
    try:
        stock_code = stock['code']
        trade_date = None
        
        if hasattr(kis_api, 'API_CALL_DELAY'):
            time.sleep(kis_api.API_CALL_DELAY)
        
        price_data = kis_api.get_stock_daily_prices(stock_code, num_days_to_fetch=30)
        
        daily_prices = []
        if price_data is not None:
            if hasattr(price_data, 'empty') and not price_data.empty:
                for _, dp in price_data.iterrows():
                    close_price = dp.get('close_price') if 'close_price' in dp.index else dp.get('price')
                    high_price = dp.get('high_price') if 'high_price' in dp.index else dp.get('high')
                    low_price = dp.get('low_price') if 'low_price' in dp.index else dp.get('low')
                    date_val = dp.get('price_date') if 'price_date' in dp.index else dp.get('date')
                    
                    if close_price is not None:
                        trade_date = trade_date or date_val
                        daily_prices.append({
                            'p_date': date_val, 'p_code': stock_code,
                            'p_price': close_price, 'p_high': high_price, 'p_low': low_price
                        })
            elif isinstance(price_data, list) and len(price_data) > 0:
                for dp in price_data:
                    if isinstance(dp, dict):
                        close_price = dp.get('close_price') or dp.get('price')
                        high_price = dp.get('high_price') or dp.get('high')
                        low_price = dp.get('low_price') or dp.get('low')
                        date_val = dp.get('price_date') or dp.get('date')
                        
                        if close_price is not None:
                            trade_date = trade_date or date_val
                            daily_prices.append({
                                'p_date': date_val, 'p_code': stock_code,
                                'p_price': close_price, 'p_high': high_price, 'p_low': low_price
                            })
        
        fundamentals = None
        if stock.get("is_tradable", False):
            snapshot = kis_api.get_stock_snapshot(stock_code)
            if hasattr(kis_api, 'API_CALL_DELAY'):
                time.sleep(kis_api.API_CALL_DELAY)
            if snapshot:
                # trade_date가 없으면 오늘 날짜로 채움 (DDL 기본키 요구)
                if trade_date is None:
                    trade_date = datetime.now(timezone.utc).date()
                fundamentals = {
                    'stock_code': stock_code,
                    'trade_date': trade_date,
                    'per': snapshot.get('per'),
                    'pbr': snapshot.get('pbr'),
                    'market_cap': snapshot.get('market_cap')
                }
        
        return daily_prices, fundamentals
    except Exception as e:
        logger.error(f"   (DW) ❌ {stock.get('name', 'N/A')} 처리 중 오류 발생: {e}")
        return [], None
