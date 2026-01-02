
# Version: v1.0 (my-prime-jennie) - LLM 오케스트레이션 모듈
# Jennie Brain Module - LLM Orchestrator
#
# Roles:
# 1. Sentiment: News Sentiment Analysis (FAST Tier)
# 2. Hunter: Stock Analysis (REASONING Tier)
# 3. Judge: Final Decision (THINKING Tier)

import os
import logging
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union

# Factory & Enum
from shared.llm_factory import LLMFactory, LLMTier
import shared.database as database
import shared.auth as auth

# Imports from shared modules
from shared.llm_prompts import (
    build_buy_prompt_mean_reversion,
    build_buy_prompt_golden_cross, # Used as build_buy_prompt_trend_following
    build_sell_prompt, # Used as build_sell_decision_prompt
    build_news_sentiment_prompt,
    build_debate_prompt,
    build_judge_prompt, # V4 Judge
    build_hunter_prompt_v5,
    build_judge_prompt_v5
)

from shared.llm_constants import ANALYSIS_RESPONSE_SCHEMA
# Alias for compatibility if needed, or just use ANALYSIS_RESPONSE_SCHEMA
JUDGE_RESPONSE_SCHEMA = ANALYSIS_RESPONSE_SCHEMA

# "youngs75_jennie.llm" 이름으로 로거 생성
logger = logging.getLogger(__name__)

class JennieBrain:
    """
    LLM을 사용하여 'BUY' 또는 'SELL' 신호에 대한 최종 결재를 수행합니다.
    LLM Factory Pattern 도입 - Hybrid Strategy (Local/Cloud)
    """
    
    def __init__(self, project_id=None, gemini_api_key_secret=None):
        # Factory를 통해 Provider는 필요할 때 동적으로 가져옵니다.
        # 기존 __init__에서의 복잡한 초기화는 제거하고, Factory에 위임합니다.
        logger.info("--- [JennieBrain] v6.0 Initialized (Factory Pattern) ---")
        
        # 레거시 호환성을 위해 필드만 남겨둠 (실제로는 사용하지 않음)
        self.provider_gemini = None 
        self.provider_claude = None
        self.provider_openai = None

    def _get_provider(self, tier: LLMTier):
        """Helper to get provider from Factory with error handling"""
        try:
            return LLMFactory.get_provider(tier)
        except Exception as e:
            logger.error(f"❌ [JennieBrain] Provider 로드 실패 ({tier}): {e}")
            return None

    def _calculate_grade(self, score: float) -> str:
        """
        정확한 등급 산정을 위한 코드 로직
        LLM의 할루시네이션(점수-등급 불일치) 방지
        """
        try:
            score = float(score)
        except (ValueError, TypeError):
            return 'D' # Default on error
            
        if score >= 80: return 'S'
        elif score >= 70: return 'A'
        elif score >= 60: return 'B'
        elif score >= 50: return 'C'
        elif score >= 40: return 'D'
        else: return 'F'

    # -----------------------------------------------------------------
    # '제니' 결재 실행
    # -----------------------------------------------------------------
    def get_jennies_decision(self, trade_type, stock_info, **kwargs):
        """
        LLM을 호출하여 최종 결재를 받습니다.
        Trade Decision = Critical Task -> THINKING Tier
        """
        provider = self._get_provider(LLMTier.THINKING)
        if provider is None:
            return {"decision": "REJECT", "reason": "JennieBrain 초기화 실패 (Thinking Tier)", "quantity": 0}

        try:
            if trade_type == 'BUY_MR':
                buy_signal_type = kwargs.get('buy_signal_type', 'UNKNOWN')
                prompt = build_buy_prompt_mean_reversion(stock_info, buy_signal_type)
            elif trade_type == 'BUY_TREND':
                buy_signal_type = kwargs.get('buy_signal_type', 'GOLDEN_CROSS')
                # Use aliased function
                prompt = build_buy_prompt_golden_cross(stock_info, buy_signal_type)
            elif trade_type == 'SELL':
                market_status = kwargs.get('market_status', 'N/A') # build_sell_prompt expects stock_info mainly
                # build_sell_prompt signature: (stock_info). market_status implies prompt builder change?
                # Assuming build_sell_prompt only takes stock_info for now based on outline.
                prompt = build_sell_prompt(stock_info)
            else:
                return {"decision": "REJECT", "reason": "알 수 없는 거래 유형", "quantity": 0}

            logger.info(f"--- [JennieBrain] 결재 요청 ({trade_type}) via {provider.name} ---")
            
            # JSON 응답 스키마
            DECISION_SCHEMA = {
                "type": "object",
                "properties": {
                    "decision": {"type": "string", "enum": ["APPROVE", "REJECT", "HOLD"]},
                    "reason": {"type": "string"},
                    "quantity": {"type": "integer"}
                },
                "required": ["decision", "reason", "quantity"]
            }

            result = provider.generate_json(
                prompt,
                DECISION_SCHEMA,
                temperature=0.1
            )
            
            logger.info(f"   👑 제니의 결재: {result.get('decision')} ({result.get('reason')})")
            return result

        except Exception as e:
            logger.error(f"❌ [JennieBrain] 결재 중 오류: {e}")
            return {"decision": "REJECT", "reason": f"System Error: {e}", "quantity": 0}

    # -----------------------------------------------------------------
    # 뉴스 감성 분석
    # -----------------------------------------------------------------
    def analyze_news_sentiment(self, title, description):
        """
        뉴스 제목과 요약을 분석하여 긍정/부정 점수를 매깁니다.
        High Volume / Low Risk -> FAST Tier (Local LLM)
        [2026-01] Cloud Fallback 제거 - Local LLM 전용 (비용 ₩0)
        """
        provider = self._get_provider(LLMTier.FAST)
        if provider is None:
             return {'score': 50, 'reason': '모델 미초기화 (기본값)'}

        try:
            # build_news_sentiment_prompt args: news_title, news_summary
            prompt = build_news_sentiment_prompt(title, description)
            
            # [Optimization] Use Flash model for FAST tier if available (e.g. Gemini 2.5 Flash)
            model_name = None
            if hasattr(provider, 'flash_model_name'):
                 model_name = provider.flash_model_name()

            result = provider.generate_json(
                prompt,
                ANALYSIS_RESPONSE_SCHEMA,
                temperature=0.0, # Deterministic
                model_name=model_name
            )
            return result
        except Exception as e:
            # [2026-01] Cloud Fallback 제거 - Local LLM 실패 시 기본값 반환
            logger.warning(f"⚠️ [News] Local LLM 분석 실패 (Skip): {e}")
            return {'score': 50, 'reason': f'Local LLM 분석 실패: {str(e)[:50]}'}

    def analyze_news_sentiment_batch(self, items: list) -> list:
        """
        뉴스 배치 분석 (다건 처리로 속도 향상)
        [2026-01] gpt-oss:20b + 배치 처리 도입
        
        Args:
            items: List of dicts with 'id', 'title', 'summary' keys
        Returns:
            List of dicts with 'id', 'score', 'reason' keys
        """
        provider = self._get_provider(LLMTier.FAST)
        if provider is None:
            return [{'id': item['id'], 'score': 50, 'reason': '모델 미초기화'} for item in items]

        # Build batched prompt
        items_text = ""
        for item in items:
            items_text += f"""
        [ID: {item['id']}]
        - 제목: {item['title']}
        - 내용: {item['summary']}
        """
        
        prompt = f"""
        [금융 뉴스 다건 감성 분석]
        당신은 '금융 전문가'입니다. 아래 {len(items)}개의 뉴스를 각각 분석하여 호재/악재 점수를 매기세요.
        
        [중요] 반드시 한국어(Korean)로만 응답하세요. 영어로 출력하면 안 됩니다.
        
        {items_text}
        
        [채점 기준]
        - 80 ~ 100점: 강력 호재
        - 60 ~ 79점: 호재
        - 40 ~ 59점: 중립
        - 20 ~ 39점: 악재
        - 0 ~ 19점: 강력 악재
        
        [출력 형식]
        반드시 아래와 같은 JSON 객체로 응답하세요. ID는 입력된 것과 일치해야 합니다.
        {{
            "results": [
                {{ "id": 0, "score": 85, "reason": "판단 이유(한국어)" }},
                {{ "id": 1, "score": 30, "reason": "판단 이유(한국어)" }},
                ...
            ]
        }}
        """
        
        BATCH_SCHEMA = {
            "type": "object",
            "properties": {
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "score": {"type": "integer"},
                            "reason": {"type": "string"}
                        },
                        "required": ["id", "score", "reason"]
                    }
                }
            },
            "required": ["results"]
        }

        try:
            result = provider.generate_json(prompt, BATCH_SCHEMA, temperature=0.0)
            return result.get('results', [])
        except Exception as e:
            logger.warning(f"⚠️ [News Batch] 배치 분석 실패: {e}")
            # Fallback: 기본값 반환
            return [{'id': item['id'], 'score': 50, 'reason': '배치 분석 실패'} for item in items]


    # -----------------------------------------------------------------
    # 토론 (Bull vs Bear)
    # -----------------------------------------------------------------
    def run_debate_session(self, stock_info: dict, analysis_context: str = "", hunter_score: int = 0) -> str:
        """
        Bull vs Bear 토론 생성 (Dynamic Role Allocation)
        Complex Creative Task -> REASONING Tier
        """
        provider = self._get_provider(LLMTier.REASONING)
        if provider is None:
             return "Debate Skipped (Model Error)"

        try:
            # Extract keywords for Dynamic Debate Context
            keywords = stock_info.get('dominant_keywords', [])
            
            # Pass hunter_score and keywords to build_debate_prompt
            prompt = build_debate_prompt(stock_info, hunter_score, keywords) 
            
            # generate_chat requires list of dicts, not str
            chat_history = [{"role": "user", "content": prompt}]
            
            logger.info(f"--- [JennieBrain/Debate] 토론 시작 via {provider.name} (HunterScore: {hunter_score}, KW: {keywords}) ---")
            
            result = provider.generate_chat(chat_history, temperature=0.7)
            # If result is dict (e.g. from structured output), extracting text. 
            # generate_chat usually returns dict with 'text' or json. 
            # But the caller expects str. 
            if isinstance(result, dict):
                return result.get('text') or result.get('content') or str(result)
            return str(result)

        except Exception as e:
            logger.warning(f"⚠️ [Debate] Local LLM failed: {e}. Attempting Cloud Fallback (Tier-Adaptive)...")
            try:
                fallback_provider = LLMFactory.get_fallback_provider(LLMTier.REASONING)
                if fallback_provider is None:
                    raise ValueError("No fallback provider for REASONING tier")

                logger.info(f"--- [JennieBrain/Debate] Cloud Fallback via {fallback_provider.name} ---")
                chat_history = [{"role": "user", "content": prompt}]
                result = fallback_provider.generate_chat(chat_history, temperature=0.7)
                
                if isinstance(result, dict):
                    return result.get('text') or result.get('content') or str(result)
                return str(result)
            except Exception as fb_e:
                logger.error(f"❌ [Debate] Fallback failed: {fb_e}")
                return f"Debate Error: {e}"

    # -----------------------------------------------------------------
    # Check if stock exists (Optional)
    # -----------------------------------------------------------------
    def verify_parameter_change(self, stock_info: dict, param_name: str, old_val, new_val) -> dict:
        # Simple task -> FAST Tier
        provider = self._get_provider(LLMTier.FAST)
        if not provider: return {"authorized": False}
        return {"authorized": True, "reason": "Auto-approved by FAST tier"}

    # -----------------------------------------------------------------
    # Judge (Supreme Jennie) 최종 판결
    # -----------------------------------------------------------------
    def run_judge_scoring(self, stock_info: dict, debate_log: str) -> dict:
        """
        Judge Scoring = Critical Decision -> THINKING Tier
        """
        provider = self._get_provider(LLMTier.THINKING)
        if provider is None:
             return {'score': 0, 'grade': 'D', 'reason': 'Provider Error'}

        try:
            prompt = build_judge_prompt(stock_info, debate_log)
            logger.info(f"--- [JennieBrain/Judge] 판결 via {provider.name} ---")
            
            result = provider.generate_json(
                prompt,
                JUDGE_RESPONSE_SCHEMA, 
                temperature=0.1
            )
            return result
        except Exception as e:
            logger.error(f"❌ [Judge] 판결 실패: {e}")
            return {'score': 0, 'grade': 'D', 'reason': f"오류: {e}"}

    # -----------------------------------------------------------------
    # Scout Hybrid Scoring
    # -----------------------------------------------------------------
    def get_jennies_analysis_score_v5(self, stock_info: dict, quant_context: str = None, feedback_context: str = None) -> dict:
        """
        v5 Hunter = Reasoning Task -> REASONING Tier
        """
        provider = self._get_provider(LLMTier.REASONING)
        if provider is None:
            return {'score': 0, 'grade': 'D', 'reason': 'Provider Error'}
        
        try:
            prompt = build_hunter_prompt_v5(stock_info, quant_context, feedback_context)
            logger.info(f"--- [JennieBrain/v5-Hunter] 분석 via {provider.name} ---")
            
            result = provider.generate_json(
                prompt,
                ANALYSIS_RESPONSE_SCHEMA,
                temperature=0.2
            )
            logger.info(f"   ✅ v5 Hunter 완료: {stock_info.get('name')} - {result.get('score')}점")
            return result
        except Exception as e:
            logger.warning(f"⚠️ [Hunter] Local LLM failed: {e}. Attempting Cloud Fallback (Tier-Adaptive)...")
            try:
                fallback_provider = LLMFactory.get_fallback_provider(LLMTier.REASONING)
                if fallback_provider is None:
                    raise ValueError("No fallback provider for REASONING tier")

                logger.info(f"--- [JennieBrain/v5-Hunter] Cloud Fallback via {fallback_provider.name} ---")
                result = fallback_provider.generate_json(
                    prompt,
                    ANALYSIS_RESPONSE_SCHEMA,
                    temperature=0.2
                )
                return result
            except Exception as fb_e:
                logger.error(f"❌ [Hunter] Fallback failed: {fb_e}")
                return {'score': 0, 'grade': 'D', 'reason': f"오류(Local+Cloud): {e}"}

    def run_judge_scoring_v5(self, stock_info: dict, debate_log: str, quant_context: str = None, feedback_context: str = None) -> dict:
        """
        v5 Judge = Critical Decision -> THINKING Tier
        [Strategy Gate]: Hunter score < 70 (Grade B) will be auto-rejected to save Cloud costs and avoid weak signals.
        """
        # 1. Strategy Gate Check (Junho's Condition)
        hunter_score = stock_info.get('hunter_score', 0)
        # Default Threshold: 70 (B Grade)
        JUDGE_THRESHOLD = 70 
        
        if hunter_score < JUDGE_THRESHOLD:
            logger.info(f"🚫 [Gatekeeper] Judge Skipped. Hunter Score {hunter_score} < {JUDGE_THRESHOLD}. Auto-Reject.")
            return {
                'score': hunter_score, 
                'grade': self._calculate_grade(hunter_score), 
                'reason': f"Hunter Score({hunter_score}) failed to meet Judge Threshold({JUDGE_THRESHOLD}). Auto-Rejected."
            }

        provider = self._get_provider(LLMTier.THINKING)
        if provider is None:
            return {'score': 0, 'grade': 'D', 'reason': 'Provider Error'}
            
        try:
            # 2. Structured Logging (Minji's Request)
            call_reason = "HighConviction_Verification"
            logger.info(json.dumps({
                "event": "ThinkingTier_Call",
                "tier": "THINKING",
                "task": "Judge_v5",
                "model": provider.client.__class__.__name__ if hasattr(provider, 'client') else provider.name,
                "reason": call_reason,
                "input_score": hunter_score
            }))
            
            prompt = build_judge_prompt_v5(stock_info, debate_log, quant_context, feedback_context)
            logger.info(f"--- [JennieBrain/v5-Judge] 판결 via {provider.name} (Why: {call_reason}) ---")
            
            # [Debug] Log critical inputs for Score Discrepancy Investigation
            logger.info(f"🔎 [Judge-Debug] Input Hunter Score: {hunter_score}")
            logger.debug(f"🔎 [Judge-Debug] Full Prompt Context: {prompt[:500]}...") # Log start of prompt securely
            
            result = provider.generate_json(
                prompt,
                ANALYSIS_RESPONSE_SCHEMA,
                temperature=0.1
            )
            
            # 등급 강제 산정 (LLM 출력 오버라이드)
            raw_score = result.get('score', 0)
            calculated_grade = self._calculate_grade(raw_score)
            
            # 등급 불일치 로깅
            llm_grade = result.get('grade', 'N/A')
            if llm_grade != calculated_grade and llm_grade != 'N/A':
                logger.warning(f"⚠️ [Judge] Grade Mismatch Corrected: LLM({llm_grade}) -> Code({calculated_grade}) for Score {raw_score}")
                
            result['grade'] = calculated_grade
            
            return result
        except Exception as e:
            logger.error(f"❌ [Judge] 오류: {e}")
            return {'score': 0, 'grade': 'D', 'reason': f"오류: {e}"}

    # -----------------------------------------------------------------
    # [New] Daily Briefing (Centralized from reporter.py)
    # -----------------------------------------------------------------
    def generate_daily_briefing(self, market_summary: str, execution_log: str) -> str:
        """
        Generate Daily Briefing Report.
        Task Type: REASONING or THINKING (depending on desired quality).
        Let's use THINKING for high quality report.
        """
        provider = self._get_provider(LLMTier.THINKING) 
        if provider is None:
            return "보고서 생성 실패: 모델 초기화 오류"

        # [Prompt Engineering]
        # Role: Jennie (Smart, Friendly, Professional AI Investment Assistant)
        # Goal: Provide a clear, structured, and actionable daily briefing.
        # Constraints: 
        # 1. Use Data: Do NOT make up market conditions. If data is missing (e.g. market_summary is empty), state it clearly.
        # 2. Tone: Friendly, reliable, and encouraging (like a trusted partner).
        # 3. Format: Clean Markdown for Telegram.

        prompt = f"""
        안녕하세요! 당신은 사용자의 똑똑하고 다정항 주식 투자 파트너 '제니(Jennie)'입니다.
        오늘의 시장 상황과 자동매매 수행 기록을 바탕으로 사용자가 퇴근길(또는 하루 마무리)에 보기 좋은 '일일 브리핑 리포트'를 작성해주세요.

        ---
        [입력 데이터]
        1. 📊 시장 요약 (Market Summary):
        {market_summary if market_summary and market_summary.strip() else "정보 없음 (수집된 시장 지표가 없습니다)"}

        2. 📜 오늘 매매 로그 (Execution Log):
        {execution_log if execution_log and execution_log.strip() else "거래 기록 없음 (오늘은 매매가 발생하지 않았습니다)"}
        ---

        [작성 가이드라인]
        1. **톤앤매너**: 
           - 다정하고 따뜻한 어조 ("~했어요", "~보입니다" 등).
           - 전문성은 유지하되, 딱딱하지 않게 작성해주세요.
           - 사용자를 격려하는 멘트를 자연스럽게 포함하세요.

        2. **구조 (Telegram Markdown)**:
           # 📅 [YYYY-MM-DD] 제니의 일일 브리핑

           ## 1. 🌍 시장 현황 (Market Pulse)
           - 시장 요약 데이터를 바탕으로 주요 지수(KOSPI, KOSDAC 등)의 흐름과 특징을 요약해주세요.
           - *주의*: 데이터가 '정보 없음'이라면, "오늘은 시장 데이터를 불러오지 못했어요. 😢"라고 솔직하게 적어주세요. 
           - *절대* "특이 사항 없이 안정적"이라는 멘트를 데이터 없이 사용하지 마세요.

           ## 2. 💼 포트폴리오 및 매매 분석
           - 오늘 발생한 매수/매도 내역을 간략히 정리해주세요.
           - 매매가 없었다면 "오늘은 쉬어가는 하루였어요. 현금을 보유하며 기회를 엿보고 있습니다." 처럼 긍정적으로 작성해주세요.
           
           ## 3. 📰 주요 뉴스 및 이슈 (Highlights)
           - 시장 요약에 포함된 뉴스나 특징주가 있다면 2~3줄로 요약해주세요.
           - 정보가 없다면 이 섹션은 생략해도 좋습니다.

           ## 4. 💡 내일의 투자 전략 (Jennie's Note)
           - 현재 상황을 바탕으로 간단한 조언이나 다짐을 적어주세요.
           - 예: "내일도 변동성을 주시하며 안전하게 대응할게요!"
           
           ## 5. 마무리 인사
           - 따뜻한 하루 마무리를 위한 인사말.

        3. **주의사항**:
           - 없는 내용을 지어내지 마세요.
           - 긍정적이고 희망적인 에너지를 전달하세요.
           - 이모지(📊, 📈, 💰, ✨)를 적절히 사용하여 가독성을 높여주세요.
        """
        try:
            logger.info(f"--- [JennieBrain/Briefing] 리포트 생성 via {provider.name} ---")
            # generate_chat requires list of dicts.
            # Gemini expects 'parts': [{'text': ...}] structure for 'user' role
            # However, BaseLLMProvider.generate_chat implementations (like GeminiLLMProvider) usually handle normalization from standard role/content.
            # Let's check GeminiLLMProvider.generate_chat. It uses history[-1]['parts'][0]['text'] implies it expects 'parts'.
            # But the Provider implementation should ideally handle 'content' -> 'parts' mapping.
            # Looking at logs: "provided dictionary has keys: ['role', 'content']".
            # It seems GeminiLLMProvider passes `history` directly to `model.start_chat(history=history)`?
            # Yes, `chat = model.start_chat(history=history)`.
            # Google GenAI `start_chat` expects standard Google format: role='user'|'model', parts=[{'text': '...'}]
            
            chat_history = [{"role": "user", "parts": [{"text": prompt}]}]
            result = provider.generate_chat(chat_history, temperature=0.7)
            
            if isinstance(result, dict):
                return result.get('text') or result.get('content') or str(result)
            return str(result)
        except Exception as e:
            logger.error(f"❌ [Briefing] 실패: {e}")
            return "보고서 생성 중 오류가 발생했습니다."

    # -----------------------------------------------------------------
    # [New] Strategic Feedback Generator
    # -----------------------------------------------------------------
    def generate_strategic_feedback(self, performance_summary: str) -> str:
        """
        Analyst 성과 보고서를 분석하여 '전략적 교훈(Feedback)'을 도출합니다.
        Task Type: THINKING Tier (Deep Reflection)
        """
        provider = self._get_provider(LLMTier.THINKING)
        if provider is None:
            return ""

        prompt = f"""
        [시스템 지침]
        당신은 제니의 'AI 전략 회고 담당관'입니다. 
        최근 AI Analyst의 투자 성과 보고서를 깊이 있게 분석하여, 향후 의사결정을 개선할 수 있는 '구체적이고 실천적인 교훈(Feedback)'을 도출해주세요.

        ---
        [성과 보고서 요약]
        {performance_summary}
        ---

        [분석 목표]
        위 보고서에서 드러나는 '패배 패턴(Failure Patterns)'과 '성공 요인(Success Factors)'을 파악하고,
        Scout AI(Hunter/Judge)가 다음 종목 선정 시 **반드시 지켜야 할 가이드라인**을 작성하세요.

        [작성 원칙]
        1. **구체성**: "조심해라" 같은 모호한 조언 금지. "하락장에서 RSI > 70 종목 매수 금지" 처럼 구체적으로.
        2. **간결성**: 핵심만 3~5개 항목으로 요약.
        3. **어조**: 엄격하고 분석적인 톤.

        [출력 예시]
        1. [시장 국면] 하락장(Bear Market)에서는 '모멘텀' 팩터의 신뢰도가 낮으므로, 펀더멘털(PER<10) 비중을 높일 것.
        2. [기술적 지표] RSI 75 이상 구간에서의 추격 매수는 승률 20% 미만이므로 절대 금지.
        3. [섹터] 바이오 섹터는 뉴스 호재만으로 매수 시 손실 리스크가 큼. 수급 동반 여부 필수 확인.
        """
        
        try:
            logger.info(f"--- [JennieBrain/Feedback] 전략 회고 via {provider.name} ---")
            
            # Use generate_chat for thinking models usually, or generate_json/text depending on provider capabilities.
            # Assuming generate_chat is robust for this.
            chat_history = [{"role": "user", "parts": [{"text": prompt}]}]
            result = provider.generate_chat(chat_history, temperature=0.2)
            
            if isinstance(result, dict):
                return result.get('text') or result.get('content') or str(result)
            return str(result)
            
        except Exception as e:
            logger.error(f"❌ [Feedback] 생성 실패: {e}")
            return ""



    # -----------------------------------------------------------------
    # Competitor Benefit Analysis (LLM-First)
    # -----------------------------------------------------------------
    def analyze_competitor_benefit(self, news_title: str) -> dict:
        """
        뉴스 제목을 분석하여 경쟁사 수혜(악재) 여부를 판단합니다.
        REASONING Tier (gpt-oss:20b 등)를 사용하여 맥락을 파악하고 스포츠 뉴스 등을 필터링합니다.
        """
        provider = self._get_provider(LLMTier.FAST)
        if provider is None:
            return {'is_risk': False, 'reason': 'Provider Error'}

        try:
            # Import prompt builder locally to avoid circular imports if any
            from shared.llm_prompts import build_competitor_benefit_prompt
            
            prompt = build_competitor_benefit_prompt(news_title)
            
            # Define Schema
            SCHEMA = {
                "type": "object",
                "properties": {
                    "is_risk": {"type": "boolean"},
                    "event_type": {"type": "string"},
                    "competitor_benefit_score": {"type": "integer"},
                    "reason": {"type": "string"}
                },
                "required": ["is_risk", "event_type", "competitor_benefit_score", "reason"]
            }

            logger.info(f"--- [JennieBrain/Competitor] 뉴스 분석 via {provider.name} ---")
            logger.debug(f"   Target: {news_title[:50]}...")

            # [Optimization] Use Flash model for FAST tier if available (e.g. Gemini 2.5 Flash)
            model_name = None
            if hasattr(provider, 'flash_model_name'):
                 model_name = provider.flash_model_name()

            result = provider.generate_json(
                prompt,
                SCHEMA,
                temperature=0.1, # Deterministic for classification
                model_name=model_name
            )
            return result
            
        except Exception as e:
            logger.error(f"❌ [Competitor] 분석 실패: {e}")
            return {'is_risk': False, 'reason': f"Error: {e}"}

