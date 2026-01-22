# scripts/verify_redis_fix.py
import sys
import os
import logging
import json

# 프로젝트 루트 경로 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from shared.redis_cache import (
    update_high_watermark, 
    get_high_watermark, 
    reset_trading_state_for_stock,
    set_scale_out_level,
    get_scale_out_level,
    get_redis_connection
)

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

def verify_fix():
    print("🚀 Redis 버그 수정 검증 시작...\n")
    
    # Redis 연결 확인
    r = get_redis_connection()
    if not r:
        print("❌ Redis 연결 실패. Docker가 실행 중인지 확인하세요.")
        return

    test_code = "TEST_9999"
    
    # ---------------------------------------------------------
    # Scenario 1: 새 포지션 감지 (High Watermark 리셋) 검증
    # ---------------------------------------------------------
    print("Scenario 1: 새 포지션 감지 (Auto Reset) 검증")
    
    # 1. 이전 포지션 상황 연출 (매수가 50,000, 고가 60,000)
    print("   1. 이전 포지션 데이터 설정 (매수가 50,000, 고가 60,000)")
    update_high_watermark(test_code, 60000, 50000)
    
    data = get_high_watermark(test_code)
    if data['high_price'] != 60000 or data['buy_price'] != 50000:
        print(f"❌ 설정 실패: {data}")
        return
        
    # 2. 새 포지션 진입 (매수가 40,000으로 변경)
    # 기존 버그라면 high_price는 여전히 60,000일 것임.
    # 수정된 로직에서는 41,000으로 리셋되어야 함.
    print("   2. 새 포지션 진입 (매수가 40,000, 현재가 41,000)")
    result = update_high_watermark(test_code, 41000, 40000)
    
    if result['high_price'] == 41000 and result['buy_price'] == 40000 and result['updated'] == True:
        print("   ✅ 검증 성공: High Price가 41,000원으로 정상 리셋됨!")
    else:
        print(f"   ❌ 검증 실패: {result}")
        print("      (기대값: high_price=41000, updated=True)")
        return

    print("\n---------------------------------------------------------")

    # ---------------------------------------------------------
    # Scenario 2: 일괄 초기화 (Reset All) 검증
    # ---------------------------------------------------------
    print("Scenario 2: 일괄 초기화 (Reset All) 검증")
    
    # 1. 잔여 데이터 생성
    print("   1. 잔여 데이터 생성 (Scale-out Level 2)")
    set_scale_out_level(test_code, 2)
    
    # 2. 초기화 호출
    print("   2. reset_trading_state_for_stock() 호출")
    reset_trading_state_for_stock(test_code)
    
    # 3. 확인
    hw = get_high_watermark(test_code)
    sl = get_scale_out_level(test_code)
    
    if hw['high_price'] is None and sl == 0:
        print("   ✅ 검증 성공: 모든 상태가 깨끗하게 삭제됨!")
    else:
        print(f"   ❌ 검증 실패: HW={hw}, SL={sl}")
        return

    print("\n🎉 모든 검증 완료! 정상 동작함.")

if __name__ == "__main__":
    verify_fix()
