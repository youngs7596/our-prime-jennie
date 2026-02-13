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


def process_quant_scoring_task(stock_info, quant_scorer, db_conn, kospi_prices_df=None,
                               v2_caches=None):
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
        v2_caches: v2 사전 조회 데이터 (Optional)
            {'financial_trend': {code: {...}},
             'sentiment_momentum': {code: float},
             'investor_trading_ext': {code: DataFrame}}

    Returns:
        QuantScoreResult 객체
    """
    code = stock_info['code']
    info = stock_info['info']
    snapshot = stock_info.get('snapshot', {}) or {}
    v2_caches = v2_caches or {}
    
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

        # v2 캐시에서 데이터 추출
        financial_trend = v2_caches.get('financial_trend', {}).get(code)
        sentiment_momentum = v2_caches.get('sentiment_momentum', {}).get(code)

        # 수급 데이터: Phase 1.8에서 수집된 market_flow 데이터 활용
        market_flow = info.get('market_flow', {}) or {}
        flow_foreign = market_flow.get('foreign_net_buy')
        flow_institution = market_flow.get('institution_net_buy')

        # 외인 보유비율 추세 계산 (v2용)
        foreign_ratio_trend = None
        ext_trading_df = v2_caches.get('investor_trading_ext', {}).get(code)
        if ext_trading_df is not None and not ext_trading_df.empty:
            if 'FOREIGN_HOLDING_RATIO' in ext_trading_df.columns and len(ext_trading_df) >= 20:
                ratios = ext_trading_df['FOREIGN_HOLDING_RATIO'].dropna()
                if len(ratios) >= 20:
                    foreign_ratio_trend = float(ratios.iloc[-1] - ratios.iloc[-20])

        # 정량 점수 계산
        result = quant_scorer.calculate_total_quant_score(
            stock_code=code,
            stock_name=info['name'],
            daily_prices_df=daily_prices_df,
            kospi_prices_df=kospi_prices_df,
            pbr=snapshot.get('pbr') if snapshot else None,
            per=snapshot.get('per') if snapshot else None,
            current_sentiment_score=info.get('sentiment_score', 50),
            foreign_net_buy=flow_foreign,
            institution_net_buy=flow_institution,
            # 섹터 정보 전달 (scout_universe에서 옴)
            sector=info.get('sector'),
            # 투자자 매매 동향 (smart_money_5d 계산용)
            investor_trading_df=investor_trading_df,
            # v2 신규 파라미터
            financial_trend=financial_trend,
            sentiment_momentum=sentiment_momentum,
            foreign_ratio_trend=foreign_ratio_trend,
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
