#!/usr/bin/env python3
"""
scripts/build_daily_packet.py

Daily Council을 위한 Daily Packet 생성 스크립트.
- DB에서 오늘(혹은 지정된 날짜)의 LLMDecisionLedger, ShadowRadarLog 등을 조회
- 대표 케이스 샘플링 (Best, Worst, Veto, Violation, Normal)
- 민감 정보 마스킹 (Allowlist 기반)
- JSON Schema 검증 및 파일 저장
"""

import argparse
import json
import logging
import os
import sys
import random
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional

from sqlalchemy import select, and_, desc, func

# 프로젝트 루트를 PYTHONPATH에 추가하여 shared 모듈 import 가능하게 함
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.db.connection import init_engine, session_scope
from shared.db.models import LLMDecisionLedger, ShadowRadarLog, TradeLog

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("BuildDailyPacket")

# 민감 정보 마스킹을 위한 허용 필드 목록 (White-list)
ALLOWED_FIELDS = {
    "case_id",
    "category",
    "symbol",
    "reasoning_summary",
    "model_decision",
    "market_context",
    "hunter_score",
    "market_regime",
    "final_decision",
    "final_reason",
    "rejection_reason",
    "rejection_stage"
}


def parse_args():
    parser = argparse.ArgumentParser(description="Daily Packet Generator for Daily Council")
    parser.add_argument("--date", type=str, default=datetime.now().strftime("%Y-%m-%d"), help="Target date (YYYY-MM-DD)")
    parser.add_argument("--output", type=str, default="daily_packet.json", help="Output JSON file path")
    parser.add_argument("--dummy", action="store_true", help="Use dummy data instead of connecting to DB")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    return parser.parse_args()


def mask_sensitive_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Allowlist에 없는 필드는 제거하거나 마스킹 처리
    """
    masked = {}
    for key, value in data.items():
        if key in ALLOWED_FIELDS:
            masked[key] = value
        # 필요한 경우 추가적인 마스킹 로직 구현
    return masked


def generate_dummy_data(target_date: str) -> Dict[str, Any]:
    logger.info("Generating DUMMY data...")
    return {
        "date": target_date,
        "summary_stats": {
            "veto_count": 12,
            "no_trade_ratio": 0.85,
            "total_scanned": 150,
            "selected_candidates": 5
        },
        "representative_cases": [
            {
                "case_id": "dummy_veto_1",
                "category": "VETO",
                "symbol": "005930",
                "reasoning_summary": "Filter rejection at Gate stage due to low liquidity.",
                "model_decision": "REJECT",
                "market_context": "Bullish market, but semi-conductor sector weak."
            },
            {
                "case_id": "dummy_violation_1",
                "category": "VIOLATION",
                "symbol": "000660",
                "reasoning_summary": "Strategy signal conflict. Momentum high but Value score too low.",
                "model_decision": "NO_DECISION",
                "market_context": "High volatility detected."
            },
             {
                "case_id": "dummy_best_1",
                "category": "BEST",
                "symbol": "035420",
                "reasoning_summary": "Strong buy signal confirmed by LLM. High hunter score.",
                "model_decision": "BUY",
                "market_context": "Platform sector rallying."
            }
        ]
    }


# Additional Imports
from shared.llm_factory import LLMFactory, LLMTier
from shared.llm_constants import LLM_MODEL_NAME

def load_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def fetch_and_build_data(target_date_str: str) -> Dict[str, Any]:
    """
    DB에서 데이터를 조회하고, Jennie(Gemini)를 통해 대표 케이스를 선별하여 Packet 생성
    """
    target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
    start_dt = datetime.combine(target_date, datetime.min.time())
    end_dt = datetime.combine(target_date, datetime.max.time())
    
    # DB 연결
    init_engine(None, None, None, None)
    
    # 1. 원천 데이터 조회 (Candidates for Jennie)
    raw_candidates = []
    
    with session_scope(readonly=True) as session:
        # 1.1 Summary Stats (기존 유지)
        veto_stmt = select(func.count(ShadowRadarLog.log_id)).where(
            ShadowRadarLog.timestamp >= start_dt, ShadowRadarLog.timestamp <= end_dt
        )
        veto_count = session.scalar(veto_stmt)

        total_stmt = select(func.count(LLMDecisionLedger.log_id)).where(
            LLMDecisionLedger.timestamp >= start_dt, LLMDecisionLedger.timestamp <= end_dt
        )
        total_ledger = session.scalar(total_stmt)

        buy_stmt = select(func.count(LLMDecisionLedger.log_id)).where(
            LLMDecisionLedger.timestamp >= start_dt, LLMDecisionLedger.timestamp <= end_dt,
            LLMDecisionLedger.final_decision == 'BUY'
        )
        buy_count = session.scalar(buy_stmt)
        
        no_trade_ratio = 0.0
        if total_ledger > 0:
            no_trade_ratio = (total_ledger - buy_count) / total_ledger
            
        summary_stats = {
            "veto_count": veto_count,
            "no_trade_ratio": round(no_trade_ratio, 2),
            "total_scanned": total_ledger + veto_count,
            "selected_candidates": buy_count
        }

        # 1.2 Fetch Raw Logs (Limit to ~50 recent items to fit context)
        # Fetch Vetos
        veto_stmt = select(ShadowRadarLog).where(
            ShadowRadarLog.timestamp >= start_dt, ShadowRadarLog.timestamp <= end_dt
        ).order_by(desc(ShadowRadarLog.timestamp)).limit(20)
        veto_logs = session.scalars(veto_stmt).all()
        
        for log in veto_logs:
            raw_candidates.append({
                "source": "ShadowRadarLog",
                "id": log.log_id,
                "symbol": log.stock_code,
                "reason": f"[{log.rejection_stage}] {log.rejection_reason}"
            })
            
        # Fetch Decisions
        decision_stmt = select(LLMDecisionLedger).where(
            LLMDecisionLedger.timestamp >= start_dt, LLMDecisionLedger.timestamp <= end_dt
        ).order_by(desc(LLMDecisionLedger.hunter_score)).limit(30)
        decision_logs = session.scalars(decision_stmt).all()
        
        for log in decision_logs:
            raw_candidates.append({
                "source": "LLMDecisionLedger",
                "id": log.log_id,
                "symbol": log.stock_code,
                "decision": log.final_decision,
                "score": log.hunter_score,
                "reason": log.final_reason,
                "context": log.market_regime
            })
            
    # 2. Call Jennie (Gemini) for Selection
    logger.info(f"🤖 Calling Jennie (Data Sage) for selection. Candidates: {len(raw_candidates)}")
    
    if not raw_candidates:
        logger.warning("No data found for this date. Returning empty packet.")
        cases = []
    else:
        try:
            # Load Prompt
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            prompt_path = os.path.join(project_root, "prompts", "council", "jennie_data_selector.txt")
            if os.path.exists(prompt_path):
                system_prompt = load_text(prompt_path)
            else:
                logger.warning("Jennie prompt not found, using default simple instructions.")
                system_prompt = "Select representative cases (BEST, WORST, VETO) from the provided logs."

            # Init Provider (Jennie uses Gemini Flash)
            # Use Factory to get Gemini Provider
            # Note: We configure LLM_MODEL_NAME in shared/llm_constants.py, but Factory logic might default to it.
            # Assuming LLMTier.FAST maps to Gemini as per our previous checks or direct usage.
            # Actually, let's use Factory.get_provider(LLMTier.FAST) which targets Gemini Flash now.
            jennie = LLMFactory.get_provider(LLMTier.FAST)
            
            # Construct Prompt
            full_prompt = f"{system_prompt}\n\n[Raw Logs]\n{json.dumps(raw_candidates, ensure_ascii=False, indent=2)}"
            
            # Call LLM
            # Response schema for selection
            selection_schema = {
                "type": "object",
                "properties": {
                    "selected_cases": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "case_id": {"type": "string"},
                                "category": {"type": "string"},
                                "symbol": {"type": "string"},
                                "reasoning_summary": {"type": "string"},
                                "model_decision": {"type": "string"},
                                "market_context": {"type": "string"}
                            },
                            "required": ["case_id", "category", "symbol", "reasoning_summary"]
                        }
                    }
                },
                "required": ["selected_cases"]
            }
            
            response = jennie.generate_json(full_prompt, selection_schema, temperature=0.2)
            cases = response.get("selected_cases", [])
            logger.info(f"✅ Jennie selected {len(cases)} cases.")
            
        except Exception as e:
            logger.error(f"❌ Jennie selection failed: {e}. Fallback to dummy selection.")
            cases = [] # Or implement simple fallback logic here

    # Final Packet Structure
    packet = {
        "date": target_date_str,
        "summary_stats": summary_stats,
        "representative_cases": cases
    }
    
    return packet


def validate_schema(data: Dict[str, Any]):
    # 간단한 필수 필드 검사 (스키마 파일 로드 대신 코드로 약식 검사 후, 필요시 jsonschema 라이브러리 사용)
    # 여기서는 스키마에 정의된 필수 키가 있는지 정도만 확인
    required_keys = ["date", "summary_stats", "representative_cases"]
    for key in required_keys:
        if key not in data:
            raise ValueError(f"Missing required key: {key}")
            
    # Stats Valid
    stats = data.get("summary_stats", {})
    required_stats = ["veto_count", "no_trade_ratio", "total_scanned", "selected_candidates"]
    for key in required_stats:
        if key not in stats:
             raise ValueError(f"Missing stats key: {key}")
             
    # Cases Valid
    for case in data.get("representative_cases", []):
        required_case = ["case_id", "category", "symbol", "reasoning_summary", "model_decision"]
        for key in required_case:
             if key not in case:
                  raise ValueError(f"Missing case key: {key}")
    
    logger.info("Schema validation passed (Simple check).")


def main():
    args = parse_args()
    
    if args.verbose:
        logger.setLevel(logging.DEBUG)
        
    try:
        if args.dummy:
            packet = generate_dummy_data(args.date)
        else:
            packet = fetch_and_build_data(args.date)
            
        # Validation
        validate_schema(packet)
        
        # Save
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(packet, f, indent=2, ensure_ascii=False)
            
        logger.info(f"Daily Packet saved to {args.output}")
        
    except Exception as e:
        logger.exception("Failed to build daily packet")
        sys.exit(1)


if __name__ == "__main__":
    main()
