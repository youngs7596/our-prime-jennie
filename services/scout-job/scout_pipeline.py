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

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """UTC 현재 시간"""
    return datetime.now(timezone.utc)


def is_hybrid_scoring_enabled() -> bool:
    """Scout v1.0 하이브리드 스코어링 활성화 여부 확인 (SCOUT_V5_ENABLED 환경변수 - 하위호환)"""
    return os.getenv("SCOUT_V5_ENABLED", "false").lower() == "true"


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
            sector=info.get('sector')
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

# 설정값 (환경변수로 조절 가능) - 보수적 기준
# "최대치를 받아도 커트라인(60점)을 못 넘을 종목만 스킵"
SMART_SKIP_QUANT_MIN = float(os.getenv("SMART_SKIP_QUANT_MIN", "25"))  # 매우 낮은 정량 점수만
SMART_SKIP_RSI_MAX = float(os.getenv("SMART_SKIP_RSI_MAX", "80"))  # 극단적 과매수만
SMART_SKIP_SENTIMENT_MIN = float(os.getenv("SMART_SKIP_SENTIMENT_MIN", "-50"))  # 극심한 악재만
SMART_SKIP_CACHED_HUNTER_MIN = float(os.getenv("SMART_SKIP_CACHED_HUNTER_MIN", "30"))  # 아주 낮은 이전 점수만


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
    if quant_result.total_score < SMART_SKIP_QUANT_MIN:
        return True, f"Quant점수 낮음 ({quant_result.total_score:.1f}점 < {SMART_SKIP_QUANT_MIN})"
    
    # 조건 2: RSI 과매수 (기술적 점수에서 RSI 추출)
    rsi = quant_result.details.get('rsi')
    if rsi is not None and rsi > SMART_SKIP_RSI_MAX:
        return True, f"RSI 과매수 ({rsi:.1f} > {SMART_SKIP_RSI_MAX})"
    
    # 조건 3: 강한 악재 뉴스
    if news_sentiment is not None and news_sentiment < SMART_SKIP_SENTIMENT_MIN:
        return True, f"악재 뉴스 (감성점수 {news_sentiment})"
    
    # 조건 4: 이전 캐시에서 크게 탈락 (조건 변화 없을 때)
    # 단, 오늘 처음 보는 종목은 스킵하지 않음
    if cached_hunter_score is not None and cached_hunter_score < SMART_SKIP_CACHED_HUNTER_MIN:
        return True, f"이전 Hunter 낮음 ({cached_hunter_score:.0f}점 < {SMART_SKIP_CACHED_HUNTER_MIN})"
    
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
    
    news_from_chroma = news_cache.get(code, "최근 관련 뉴스 없음") if news_cache else "뉴스 캐시 없음"
    
    # 경쟁사 수혜 정보를 뉴스에 추가
    if competitor_bonus > 0:
        news_from_chroma += f"\n\n⚡ [경쟁사 수혜 기회] {competitor_reason} (+{competitor_bonus}점)"
    
    decision_info = {
        'code': code,
        'name': info['name'],
        'technical_reason': 'N/A',
        'news_reason': news_from_chroma if news_from_chroma not in ["뉴스 DB 미연결", "뉴스 검색 오류"] else ', '.join(info.get('reasons', [])),
        'per': snapshot.get('per'),
        'pbr': snapshot.get('pbr'),
        'market_cap': snapshot.get('market_cap'),
    }
    
    # 정량 컨텍스트 포함 Hunter 호출
    hunter_result = brain.get_jennies_analysis_score_v5(decision_info, quant_context, feedback_context)
    hunter_score = hunter_result.get('score', 0)
    
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
    reason = judge_result.get('reason', '분석 실패')
    
    # 하이브리드 점수 계산 (정량 60% + 정성 40%)
    quant_score = quant_result.total_score
    llm_score = score
    
    score_diff = abs(quant_score - llm_score)
    if score_diff >= 30:
        if quant_score < llm_score:
            hybrid_score = quant_score * 0.75 + llm_score * 0.25
            logger.warning(f"   ⚠️ [Safety Lock] {info['name']} - 정량({quant_score:.0f}) << 정성({llm_score}) → 보수적 판단")
        else:
            hybrid_score = quant_score * 0.45 + llm_score * 0.55
            logger.warning(f"   ⚠️ [Safety Lock] {info['name']} - 정성({llm_score}) << 정량({quant_score:.0f}) → 보수적 판단")
    else:
        hybrid_score = quant_score * 0.60 + llm_score * 0.40
    
    is_tradable = hybrid_score >= 75
    approved = hybrid_score >= 50
    
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
        weight_info = "(60:40)" if score_diff < 30 else "(Safety Lock)"
        lines.append(f"   📊 점수 흐름: Hunter:{hunter_score} → Quant:{quant_score:.0f} + LLM:{llm_score} = Hybrid:{hybrid_score:.1f} {weight_info}")
        
        # 2. Judge 판단 이유 (reason 축약 - 최대 60자)
        reason_short = reason[:60] + "..." if len(reason) > 60 else reason
        lines.append(f"   💬 Judge 판단: {reason_short}")
        
        # 3. 거래 가능 여부
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
        # 재무 데이터 추가
        'per': snapshot.get('per'),
        'pbr': snapshot.get('pbr'),
        'roe': snapshot.get('roe'),
        'market_cap': snapshot.get('market_cap'),
        'sales_growth': snapshot.get('sales_growth'),
        'eps_growth': snapshot.get('eps_growth'),
    }


def process_phase1_hunter_task(stock_info, brain, snapshot_cache=None, news_cache=None, archivist=None):
    """
    Phase 1 Hunter만 실행하는 태스크 (병렬 처리용)
    
    변경사항:
    - KIS API 스냅샷: 사전 캐시에서 조회 (API 호출 X)
    - ChromaDB 뉴스: 사전 캐시에서 조회 (HTTP 요청 X)
    - LLM 호출만 수행 → Rate Limit 대응 용이
    """
    code = stock_info['code']
    info = stock_info['info']
    
    snapshot = snapshot_cache.get(code) if snapshot_cache else None
    if not snapshot:
        logger.debug(f"   ⚠️ [Phase 1] {info['name']}({code}) Snapshot 캐시 미스")
        return {
            'code': code,
            'name': info['name'],
            'info': info,
            'snapshot': None,
            'hunter_score': 0,
            'hunter_reason': '스냅샷 조회 실패',
            'passed': False,
        }

    factor_info = ""
    momentum_value = None
    for reason in info.get('reasons', []):
        if '모멘텀' in reason:
            factor_info = reason
            try:
                match = re.search(r'([\d.-]+)%', reason)
                if match:
                    momentum_value = float(match.group(1))
            except Exception:
                pass
            break
    
    news_from_chroma = news_cache.get(code, "최근 관련 뉴스 없음") if news_cache else "뉴스 캐시 없음"
    
    all_reasons = info.get('reasons', []).copy()
    if news_from_chroma and news_from_chroma not in ["뉴스 DB 미연결", "최근 관련 뉴스 없음", "뉴스 검색 오류", "뉴스 조회 실패", "뉴스 캐시 없음"]:
        all_reasons.append(news_from_chroma)
    
    decision_info = {
        'code': code,
        'name': info['name'],
        'technical_reason': 'N/A (전략 변경)',
        'news_reason': news_from_chroma if news_from_chroma not in ["뉴스 DB 미연결", "뉴스 검색 오류"] else ', '.join(info['reasons']),
        'per': snapshot.get('per'),
        'pbr': snapshot.get('pbr'),
        'market_cap': snapshot.get('market_cap'),
        'factor_info': factor_info,
        'momentum_score': momentum_value
    }

    hunter_result = brain.get_jennies_analysis_score(decision_info)
    hunter_score = hunter_result.get('score', 0)
    
    passed = hunter_score >= 60
    if passed:
        logger.info(f"   ✅ [Phase 1 통과] {info['name']}({code}) - Hunter: {hunter_score}점")
    else:
        logger.debug(f"   ❌ [Phase 1 탈락] {info['name']}({code}) - Hunter: {hunter_score}점")

        # [Priority 2] Shadow Radar Logging
        if archivist:
            try:
                shadow_data = {
                    'stock_code': code,
                    'stock_name': info['name'],
                    'rejection_stage': 'HUNTER_V4',
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
        'hunter_score': hunter_score,
        'hunter_reason': hunter_result.get('reason', ''),
        'passed': passed,
    }


def process_phase23_debate_judge_task(phase1_result, brain, archivist=None):
    """
    Phase 2-3 (Debate + Judge) 실행하는 태스크 (Phase 1 통과 종목만)
    GPT-5-mini로 심층 분석
    """
    code = phase1_result['code']
    info = phase1_result['info']
    decision_info = phase1_result['decision_info']
    hunter_score = phase1_result['hunter_score']
    
    logger.info(f"   🔄 [Phase 2-3] {info['name']}({code}) Debate-Judge 시작...")
    
    debate_log = brain.run_debate_session(decision_info, hunter_score=hunter_score)
    
    judge_result = brain.run_judge_scoring(decision_info, debate_log)
    score = judge_result.get('score', 0)
    grade = judge_result.get('grade', 'D')
    reason = judge_result.get('reason', '분석 실패')
    
    is_tradable = score >= 75
    approved = score >= 50
    
    if approved:
        logger.info(f"   ✅ [Judge 승인] {info['name']}({code}) - 최종: {score}점 ({grade})")
    else:
        logger.info(f"   ❌ [Judge 거절] {info['name']}({code}) - 최종: {score}점 ({grade})")
        
        # [Priority 2] Shadow Radar Logging
        if archivist:
            try:
                shadow_data = {
                    'stock_code': code,
                    'stock_name': info['name'],
                    'rejection_stage': 'JUDGE_V4',
                    'rejection_reason': reason,
                    'hunter_score_at_time': hunter_score,
                    'trigger_type': 'JUDGE_REJECT',
                    'trigger_value': float(score)
                }
                archivist.log_shadow_radar(shadow_data)
            except Exception as e:
                logger.warning(f"Failed to log shadow radar for {code}: {e}")
    
    metadata = {
        'llm_grade': grade,
        'llm_updated_at': _utcnow().isoformat(),
        'source': 'llm_judge',
        'hunter_score': hunter_score,
    }
    
    return {
        'code': code,
        'name': info['name'],
        'is_tradable': is_tradable,
        'llm_score': score,
        'llm_reason': reason,
        'approved': approved,
        'llm_metadata': metadata,
    }


def fetch_kis_data_task(stock, kis_api):
    """KIS API로부터 종목 데이터 조회"""
    try:
        stock_code = stock['code']
        
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
                fundamentals = {
                    'code': stock_code,
                    'per': snapshot.get('per'),
                    'pbr': snapshot.get('pbr'),
                    'market_cap': snapshot.get('market_cap')
                }
        
        return daily_prices, fundamentals
    except Exception as e:
        logger.error(f"   (DW) ❌ {stock.get('name', 'N/A')} 처리 중 오류 발생: {e}")
        return [], None
