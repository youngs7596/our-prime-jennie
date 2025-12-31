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
    실제 로그 파일에서 데이터를 수집합니다.
    (현재는 미구현, 추후 로그 파일 파싱 로직 추가 필요)
    """
    logger.warning("Real data gathering is not fully implemented yet. Using dummy data structure for now.")
    # TODO: Implement log parsing logic here
    return generate_dummy_data()

def main():
    parser = argparse.ArgumentParser(description="Build Daily Packet for Council Review")
    parser.add_argument("--output", required=True, help="Path to save the output JSON")
    parser.add_argument("--dummy", action="store_true", help="Use dummy data instead of real logs")
    parser.add_argument("--schema", default="schemas/daily_packet.schema.json", help="Path to schema file")
    
    args = parser.parse_args()

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
