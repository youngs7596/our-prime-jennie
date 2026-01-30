
import os
import sys
import json
from sqlalchemy import create_engine, text
from urllib.parse import quote_plus
from datetime import datetime, timedelta

sys.path.append(os.getcwd())

def get_db_url_from_secrets():
    with open("secrets.json", "r") as f:
        secrets = json.load(f)
        user = secrets.get("mariadb-user", "root")
        password = secrets.get("mariadb-password", "")
        host = secrets.get("mariadb-host", "localhost")
        port = secrets.get("mariadb-port", 3306)
        dbname = secrets.get("mariadb-database", "jennie_db")
        return f"mysql+pymysql://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{dbname}?charset=utf8mb4"

def analyze_hyundai_wia_entry():
    """현대위아 09:20 매수 시점의 상세 분석"""
    DATABASE_URL = get_db_url_from_secrets()
    engine = create_engine(DATABASE_URL)
    
    stock_code = "011210"
    trade_date = "2026-01-29"
    
    print("=" * 60)
    print("현대위아 (011210) 매수 건 상세 분석")
    print("=" * 60)
    
    with engine.connect() as conn:
        # 1. Trade Log 확인
        print("\n[1] 매수 거래 로그")
        trade_sql = text("""
            SELECT TRADE_TIMESTAMP, TRADE_TYPE, PRICE, QUANTITY, KEY_METRICS_JSON
            FROM TRADELOG
            WHERE STOCK_CODE = :code 
              AND DATE(TRADE_TIMESTAMP) = :tdate
              AND TRADE_TYPE = 'BUY'
            ORDER BY TRADE_TIMESTAMP
        """)
        trades = conn.execute(trade_sql, {"code": stock_code, "tdate": trade_date}).mappings().all()
        
        for t in trades:
            print(f"   시각: {t['TRADE_TIMESTAMP']}")
            print(f"   체결가: {t['PRICE']:,.0f}원")
            print(f"   수량: {t['QUANTITY']}주")
            if t['KEY_METRICS_JSON']:
                metrics = json.loads(t['KEY_METRICS_JSON']) if isinstance(t['KEY_METRICS_JSON'], str) else t['KEY_METRICS_JSON']
                print(f"   신호타입: {metrics.get('buy_signal_type', 'N/A')}")
                print(f"   LLM점수: {metrics.get('llm_score', 'N/A')}")
                print(f"   Factor점수: {metrics.get('factor_score', 'N/A')}")
                print(f"   Tier: {metrics.get('tier', 'N/A')}")
        
        # 2. 분봉 데이터 분석 (09:00 ~ 09:30)
        print("\n[2] 분봉 추이 (09:00 ~ 09:30)")
        minute_sql = text("""
            SELECT TRADE_DATETIME, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, CLOSE_PRICE, VOLUME
            FROM STOCK_MINUTE_PRICE
            WHERE STOCK_CODE = :code 
              AND DATE(TRADE_DATETIME) = :tdate
              AND TIME(TRADE_DATETIME) BETWEEN '09:00:00' AND '09:35:00'
            ORDER BY TRADE_DATETIME
        """)
        minutes = conn.execute(minute_sql, {"code": stock_code, "tdate": trade_date}).mappings().all()
        
        if not minutes:
            print("   분봉 데이터 없음")
        else:
            closes = []
            for m in minutes:
                closes.append(m['CLOSE_PRICE'])
                change_pct = ((m['CLOSE_PRICE'] - minutes[0]['CLOSE_PRICE']) / minutes[0]['CLOSE_PRICE'] * 100) if closes else 0
                print(f"   {m['TRADE_DATETIME'].strftime('%H:%M')} | 종가: {m['CLOSE_PRICE']:,.0f} | 변화: {change_pct:+.2f}%")
            
            # RSI 계산 시뮬레이션
            if len(closes) >= 15:
                gains = []
                losses = []
                for i in range(1, len(closes)):
                    diff = closes[i] - closes[i-1]
                    if diff >= 0:
                        gains.append(diff)
                        losses.append(0)
                    else:
                        gains.append(0)
                        losses.append(abs(diff))
                
                if len(gains) >= 14:
                    avg_gain = sum(gains[-14:]) / 14
                    avg_loss = sum(losses[-14:]) / 14
                    if avg_loss > 0:
                        rs = avg_gain / avg_loss
                        rsi = 100 - (100 / (1 + rs))
                        print(f"\n   [계산된 RSI(14)]: {rsi:.1f}")
            
            # MA5/MA20 계산 시뮬레이션
            if len(closes) >= 20:
                ma5 = sum(closes[-5:]) / 5
                ma20 = sum(closes[-20:]) / 20
                print(f"   [MA5]: {ma5:,.0f}")
                print(f"   [MA20]: {ma20:,.0f}")
                print(f"   [정배열]: {'예' if ma5 > ma20 else '아니오'}")
        
        # 3. 일봉 데이터 (맥락)
        print("\n[3] 일봉 맥락 (최근 3일)")
        daily_sql = text("""
            SELECT TRADE_DATE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, CLOSE_PRICE, VOLUME
            FROM STOCK_DAILY_PRICE
            WHERE STOCK_CODE = :code
            ORDER BY TRADE_DATE DESC
            LIMIT 5
        """)
        dailies = conn.execute(daily_sql, {"code": stock_code}).mappings().all()
        
        for d in dailies:
            print(f"   {d['TRADE_DATE']} | 시가:{d['OPEN_PRICE']:,.0f} 고가:{d['HIGH_PRICE']:,.0f} 저가:{d['LOW_PRICE']:,.0f} 종가:{d['CLOSE_PRICE']:,.0f}")
        
        # 4. 09:20 매수 시점의 문제점 분석
        print("\n" + "=" * 60)
        print("[결론] 왜 09:20에 매수가 발생했는가?")
        print("=" * 60)
        print("""
1. 타이밍 문제:
   - 09:20은 'No-Trade Window (09:00~09:30)' 해제 직후
   - 장 초반 변동성이 극대화되는 구간
   - 모멘텀 전략은 '상승 중'인 것만 확인, '고점' 여부 미확인

2. 전략 로직 문제:
   - MOMENTUM_CONTINUATION_BULL 조건:
     * MA5 > MA20 (O) - 정배열 상태
     * 상승률 >= 2% (O) - 장초부터 급등
     * LLM Score >= 65 (O) - 83.25점
   - 누락된 체크: RSI 과열 확인 (당시 RSI Guard 없었음)

3. 데이터 갭:
   - RSI 계산에 필요한 14개 바 = 14분
   - 09:00 시작, 09:14 이후에야 RSI 계산 가능
   - 09:20 시점엔 RSI가 계산되었지만, 필터가 없었음

4. 해결 방안 (이미 구현됨):
   - RSI Guard (RSI > 75 차단) ✅
   - Danger Zone (14:00~15:00 차단) ✅
   - No-Trade Window 30분 확대 (09:30까지) ✅
""")

if __name__ == "__main__":
    analyze_hyundai_wia_entry()
