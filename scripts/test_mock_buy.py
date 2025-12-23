#!/usr/bin/env python3
"""
scripts/test_mock_buy.py
========================
Mock 매수 테스트 스크립트

1. buy-executor-mock 서비스에 HTTP POST로 매수 신호를 전송합니다.
2. 잠시 대기 후 DB를 조회하여 정상적으로 기록되었는지 확인합니다.
"""

import sys
import os
import time
import requests
import json
from datetime import datetime, timedelta
import logging

# 프로젝트 루트 경로 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.db.connection import session_scope, init_engine
from shared.db.models import TradeLog, Portfolio

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BUY_EXECUTOR_URL = "http://localhost:9082/process"
MOCK_STOCK_CODE = "005930" # 삼성전자 (Mock Server에 정의됨)
MOCK_STOCK_NAME = "삼성전자"

def send_buy_signal(stock_code=MOCK_STOCK_CODE, stock_name=MOCK_STOCK_NAME, score=85):
    """매수 신호 전송"""
    logger.info(f"📤 매수 신호 전송: {stock_name}({stock_code}), 점수: {score}")
    
    # Buy Scanner가 보내는 형식과 동일하게 구성
    payload = {
        "message": {
            "data": "ewogICAgImNhbmRpZGF0ZXMiOiBbCiAgICAgICAgewogICAgICAg     ImNvZGUiOiAiMDA1OTMwIiwKICAgICAgICAibmFtZSI6ICJcdWMyMDZcdWIyZTFcdWMyMTAiLAogICAgICAgICJsbG1fc2NvcmUiOiA4NSwKICAgICAgICAibGxtX3JlYXNvbiI6ICJNb2NrIFRlc3QgU2lnbmFsIiwKICAgICAgICAiYnV5X3NpZ25hbF90eXBlIjogIlRFU1RfU0lHTkFMIiwKICAgICAgICAiY3VycmVudF9wcmljZSI6IDcwMDAwCiAgICAgICAgfQogICAgXSwKICAgICJtYXJrZXRfcmVnaW1lIjogIk5FVVRSQUwiLAogICAgInJpc2tfc2V0dGluZyI6IHsKICAgICAgICAicG9zaXRpb25fc2l6ZV9yYXRpbyI6IDEuMAogICAgfSwKICAgICJzdHJhdGVneV9wcmVzZXQiOiB7CiAgICAgICAgIm5hbWUiOiAiTU9DS19QUkVTRVQiLAogICAgICAgICJwYXJhbXMiOiB7fQogICAgfQp9" 
            # 위 base64 문자열은 아래 JSON을 인코딩한 것임:
            # {
            #     "candidates": [
            #         {
            #             "code": "005930",
            #             "name": "삼성전자",
            #             "llm_score": 85,
            #             "llm_reason": "Mock Test Signal",
            #             "buy_signal_type": "TEST_SIGNAL",
            #             "current_price": 70000
            #         }
            #     ],
            #     "market_regime": "NEUTRAL",
            #     "risk_setting": {
            #         "position_size_ratio": 1.0
            #     },
            #     "strategy_preset": {
            #         "name": "MOCK_PRESET",
            #         "params": {}
            #     }
            # }
        }
    }
    
    # 직접 JSON 데이터를 Base64 인코딩해서 보내는 것이 정확함
    import base64
    real_data = {
        "candidates": [
            {
                "code": stock_code,
                "name": stock_name,
                "llm_score": score,
                "llm_reason": f"Mock Test Signal {datetime.now().strftime('%H:%M:%S')}",
                "buy_signal_type": "TEST_SIGNAL",
                "current_price": 70000,
                "factor_score": 90.5
            }
        ],
        "market_regime": "NEUTRAL",
        "risk_setting": {
            "position_size_ratio": 1.0
        },
        "strategy_preset": {
            "name": "MOCK_PRESET",
            "params": {}
        }
    }
    
    encoded_data = base64.b64encode(json.dumps(real_data).encode('utf-8')).decode('utf-8')
    payload['message']['data'] = encoded_data
    
    try:
        response = requests.post(BUY_EXECUTOR_URL, json=payload, timeout=10)
        logger.info(f"📥 응답: {response.status_code} - {response.text}")
        return response.json()
    except Exception as e:
        logger.error(f"❌ 요청 실패: {e}")
        return None

def verify_db_records(stock_code=MOCK_STOCK_CODE):
    """DB 레코드 검증"""
    logger.info("🔍 DB 검증 시작...")
    
    with session_scope() as session:
        # 1. TRADE_LOG 확인
        # 최근 1분 내 기록 확인
        since = datetime.now() - timedelta(minutes=1)
        trades = session.query(TradeLog).filter(
            TradeLog.stock_code == stock_code,
            TradeLog.trade_timestamp >= since
        ).all()
        
        if trades:
            logger.info(f"✅ TRADE_LOG 발견: {len(trades)}건")
            for t in trades:
                logger.info(f"   - ID: {t.log_id}, Type: {t.trade_type}, Qty: {t.quantity}, Reason: {t.reason[:30]}...")
        else:
            # Check if skipped due to holding
            portfolio = session.query(Portfolio).filter(
                Portfolio.stock_code == stock_code
            ).first()
            if portfolio and portfolio.quantity > 0:
                 logger.info(f"⚠️ TRADE_LOG 미발견 (이미 보유중): {portfolio.stock_name}, Qty: {portfolio.quantity}")
            else:
                 logger.error("❌ TRADE_LOG가 발견되지 않았습니다!")
        
        # 2. PORTFOLIO 확인
        portfolio = session.query(Portfolio).filter(
            Portfolio.stock_code == stock_code
        ).first()
        
        if portfolio:
            logger.info(f"✅ PORTFOLIO 발견: {portfolio.stock_name}, Qty: {portfolio.quantity}")
        else:
            logger.error("❌ PORTFOLIO에 해당 종목이 없습니다!")

def main():
    logger.info("=== Mock Buy Test Start ===")
    init_engine()
    
    # 1. Send Signal
    result = send_buy_signal()
    
    if result:
        status = result.get("status")
        if status == "success":
            logger.info("⏳ DB 기록 대기 (3초)...")
            time.sleep(3)
            verify_db_records()
        elif status == "skipped":
            logger.info(f"ℹ️ 매수 스킵됨: {result.get('reason')}")
            # 스킵되어도 포트폴리오 확인
            verify_db_records()
        else:
            logger.warning(f"⚠️ 알 수 없는 상태: {status}")
    else:
        logger.error("매수 신호 전송 실패로 검증 중단")

if __name__ == "__main__":
    main()
