#!/usr/bin/env python3
"""
scripts/build_daily_packet.py
Daily Packet 생성 스크립트.
로그 데이터를 분석하여 Daily Council이 리뷰할 요약 정보를 생성합니다.
"""

import argparse
import json
import logging
import os
import random
import sys
import os

# Add project root to sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from datetime import datetime
from typing import Dict, List, Any

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

try:
    import jsonschema
except ImportError:
    logger.warning("jsonschema module not found. Schema validation will be skipped.")
    jsonschema = None

def load_schema(schema_path: str) -> Dict[str, Any]:
    """JSON 스키마 파일을 로드합니다."""
    if not os.path.exists(schema_path):
        raise FileNotFoundError(f"Schema file not found: {schema_path}")
    with open(schema_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def validate_data(data: Dict[str, Any], schema_path: str):
    """데이터를 스키마에 대해 검증합니다."""
    if jsonschema is None:
        return

    schema = load_schema(schema_path)
    try:
        jsonschema.validate(instance=data, schema=schema)
        logger.info("Schema validation passed.")
    except jsonschema.ValidationError as e:
        logger.error(f"Schema validation failed: {e}")
        sys.exit(1)

def generate_dummy_data() -> Dict[str, Any]:
    """테스트용 더미 데이터를 생성합니다."""
    logger.info("Generating dummy data...")
    
    categories = ["VETO", "VIOLATION", "WORST", "BEST", "NORMAL", "NORMAL"]
    cases = []
    
    for i, category in enumerate(categories):
        symbol = f"{random.randint(1000, 99999):06d}"
        decision = "BUY" if category in ["BEST", "NORMAL"] else "HOLD"
        if category == "VETO":
            decision = "REJECT"
            
        cases.append({
            "case_id": f"CASE-{datetime.now().strftime('%Y%m%d')}-{i+1:03d}",
            "category": category,
            "symbol": symbol,
            "reasoning_summary": f"Sample reasoning for {symbol} ({category}). Market conditions were favorable but risk factors detected.",
            "model_decision": decision,
            "market_context": "KOSPI bullish, sector momentum high."
        })

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "summary_stats": {
            "veto_count": 2,
            "no_trade_ratio": 0.35,
            "total_scanned": 150,
            "selected_candidates": 12
        },
        "representative_cases": cases
    }

def gather_real_data() -> Dict[str, Any]:
    """
    DB에서 실제 로그 데이터를 수집합니다.
    - ShadowRadarLog: 필터링 탈락 (VETO)
    - LLMDecisionLedger: LLM 분석 결과 (DECISION)
    """
    logger.info("Connecting to DB to gather real data...")
    
    # Import necessary modules
    try:
        from shared.db.connection import session_scope
        from shared.db.models import ShadowRadarLog, LLMDecisionLedger
        from sqlalchemy import text
    except ImportError as e:
        logger.error(f"Failed to import shared modules: {e}")
        return generate_dummy_data()

    cases = []
    summary_stats = {
        "veto_count": 0,
        "no_trade_ratio": 0.0,
        "total_scanned": 0,
        "selected_candidates": 0
    }
    
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    try:
        with session_scope(readonly=True) as session:
            # 1. Total Scanned Count (Approximate from Shadow + Decision)
            veto_count = session.query(ShadowRadarLog).filter(
                ShadowRadarLog.timestamp >= today_start
            ).count()
            
            decision_count = session.query(LLMDecisionLedger).filter(
                LLMDecisionLedger.timestamp >= today_start
            ).count()
            
            summary_stats["total_scanned"] = veto_count + decision_count
            summary_stats["selected_candidates"] = decision_count
            
            if summary_stats["total_scanned"] > 0:
                summary_stats["no_trade_ratio"] = veto_count / summary_stats["total_scanned"]
                summary_stats["veto_count"] = veto_count
                
            # 2. ShadowRadarLog (VETO Cases)
            veto_logs = session.query(ShadowRadarLog).filter(
                ShadowRadarLog.timestamp >= today_start
            ).all()

            for log in veto_logs:
                cases.append({
                    "case_id": f"VETO-{log.log_id}",
                    "category": "VETO",
                    "symbol": log.stock_code,
                    "reasoning_summary": log.rejection_reason or "No reason recorded",
                    "model_decision": "REJECT",
                    "market_context": f"Trigger: {log.trigger_type}, Stage: {log.rejection_stage}"
                })

            # 3. LLMDecisionLedger (DECISION Cases)
            decisions = session.query(LLMDecisionLedger).filter(
                LLMDecisionLedger.timestamp >= today_start
            ).all()

            for dec in decisions:
                cat = "NORMAL"
                if dec.final_decision == "BUY" and (dec.hunter_score or 0) > 80:
                    cat = "BEST"
                elif dec.gate_result == "REJECT" and (dec.hunter_score or 0) > 70:
                    cat = "VIOLATION"
                elif dec.final_decision == "HOLD" and (dec.hunter_score or 0) > 50:
                    cat = "WORST"
                
                cases.append({
                    "case_id": f"DEC-{dec.log_id}",
                    "category": cat,
                    "symbol": dec.stock_code,
                    "reasoning_summary": dec.final_reason or "No reason recorded",
                    "model_decision": dec.final_decision,
                    "market_context": f"Regime: {dec.market_regime}, Score: {dec.hunter_score}"
                })

    except Exception as e:
        logger.error(f"Failed to gather data from DB: {e}")
        # import traceback
        # logger.error(traceback.format_exc())
        logger.warning("Falling back to dummy data generation.")
        return generate_dummy_data()

    logger.info(f"Gathered {len(cases)} cases from DB.")
    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "summary_stats": summary_stats,
        "representative_cases": cases
    }

def main():
    parser = argparse.ArgumentParser(description="Build Daily Packet for Council Review")
    parser.add_argument("--output", required=True, help="Path to save the output JSON")
    parser.add_argument("--dummy", action="store_true", help="Use dummy data instead of real logs")
    parser.add_argument("--schema", default="schemas/daily_packet.schema.json", help="Path to schema file")
    
    args = parser.parse_args()

    # DB 초기화 (실제 데이터 모드일 때만 필요)
    if not args.dummy:
        from dotenv import load_dotenv
        from shared.db.connection import ensure_engine_initialized
        
        load_dotenv(override=True)
        
        # DB params debugging
        host = os.getenv("MARIADB_HOST", "N/A")
        port = os.getenv("MARIADB_PORT", "N/A")
        user = os.getenv("MARIADB_USER", "N/A")
        logger.info(f"DB Connection Params: HOST={host}, PORT={port}, USER={user}")
        
        ensure_engine_initialized()

    # 데이터 생성
    if args.dummy:
        packet_data = generate_dummy_data()
    else:
        packet_data = gather_real_data()

    # 스키마 검증
    # 프로젝트 루트 기준 상대 경로 처리
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    schema_full_path = os.path.join(project_root, args.schema)
    
    if os.path.exists(schema_full_path):
        validate_data(packet_data, schema_full_path)
    else:
        logger.warning(f"Schema file not found at {schema_full_path}. Skipping validation.")

    # 파일 저장
    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(packet_data, f, indent=2, ensure_ascii=False)
        
    logger.info(f"Daily packet saved to {args.output}")

if __name__ == "__main__":
    main()
