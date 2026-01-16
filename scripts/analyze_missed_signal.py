#!/usr/bin/env python3
"""
에스엘(005850) 매수 신호 누락 분석 스크립트
- 오늘 분봉 데이터로 Golden Cross / RSI Rebound 조건 재현
- 왜 신호를 잡지 못했는지 분석
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from datetime import datetime, timedelta
from dotenv import load_dotenv
import pandas as pd

load_dotenv()

from shared.db.connection import session_scope, ensure_engine_initialized
from shared.db.models import StockMinutePrice, StockInvestorTrading, StockDailyPrice

STOCK_CODE = "005850"  # 에스엘
TODAY = datetime.now().strftime('%Y-%m-%d')

def calculate_rsi(closes, period=14):
    """RSI 계산"""
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    recent_deltas = deltas[-(period):]
    gains = [d for d in recent_deltas if d > 0]
    losses = [-d for d in recent_deltas if d < 0]
    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def check_golden_cross(closes, short_w=5, long_w=20):
    """Golden Cross 체크"""
    if len(closes) < long_w:
        return False, None, None, None
    ma_short = sum(closes[-short_w:]) / short_w
    ma_long = sum(closes[-long_w:]) / long_w
    
    prev_closes = closes[:-1]
    prev_ma_short = sum(prev_closes[-short_w:]) / short_w if len(prev_closes) >= short_w else ma_short
    
    triggered = (prev_ma_short <= ma_long) and (ma_short > ma_long)
    return triggered, ma_short, ma_long, ma_short - ma_long

def check_rsi_rebound(closes, threshold=30):
    """RSI Rebound 체크"""
    curr_rsi = calculate_rsi(closes, period=14)
    if curr_rsi is None or len(closes) < 2:
        return False, None, None
    prev_closes = closes[:-1]
    prev_rsi = calculate_rsi(prev_closes, period=14)
    if prev_rsi is None:
        return False, None, None
    triggered = prev_rsi < threshold and curr_rsi >= threshold
    return triggered, prev_rsi, curr_rsi

def analyze_minute_data():
    """분봉 데이터 분석"""
    print(f"\n{'='*60}")
    print(f"🔍 에스엘(005850) 매수 신호 누락 분석 - {TODAY}")
    print(f"{'='*60}\n")
    
    ensure_engine_initialized()
    
    with session_scope(readonly=True) as session:
        # 1. 오늘 분봉 데이터 조회
        today_start = datetime.strptime(TODAY, '%Y-%m-%d')
        today_end = today_start + timedelta(days=1)
        
        minute_data = session.query(StockMinutePrice).filter(
            StockMinutePrice.stock_code == STOCK_CODE,
            StockMinutePrice.price_time >= today_start,
            StockMinutePrice.price_time < today_end
        ).order_by(StockMinutePrice.price_time).all()
        
        print(f"📊 오늘 분봉 데이터: {len(minute_data)}개")
        
        if not minute_data:
            print("❌ 분봉 데이터가 없습니다!")
            
            # 대안: 일봉 데이터 확인
            daily_data = session.query(StockDailyPrice).filter(
                StockDailyPrice.stock_code == STOCK_CODE
            ).order_by(StockDailyPrice.price_date.desc()).limit(30).all()
            
            print(f"\n📈 대신 일봉 데이터 확인: 최근 {len(daily_data)}일")
            
            if daily_data:
                df = pd.DataFrame([{
                    'date': d.price_date,
                    'open': d.open_price,
                    'high': d.high_price,
                    'low': d.low_price,
                    'close': d.close_price,
                    'volume': d.volume
                } for d in reversed(daily_data)])
                
                print(df.tail(10).to_string())
                
                closes = df['close'].tolist()
                gc_triggered, ma5, ma20, gap = check_golden_cross(closes)
                print(f"\n🔄 Golden Cross (Daily): {gc_triggered}")
                print(f"   MA5={ma5:.0f}, MA20={ma20:.0f}, Gap={gap:.0f}")
                
                rsi = calculate_rsi(closes)
                print(f"📊 RSI(14): {rsi:.1f}" if rsi else "RSI: N/A")
            return
        
        # 2. 분봉 데이터를 DataFrame으로 변환
        df = pd.DataFrame([{
            'time': m.price_time,
            'open': m.open_price,
            'high': m.high_price,
            'low': m.low_price,
            'close': m.close_price,
            'volume': m.volume,
            'accum_vol': m.accum_volume
        } for m in minute_data])
        
        print(f"\n📈 가격 범위: {df['low'].min():,.0f} ~ {df['high'].max():,.0f}원")
        print(f"   시가: {df.iloc[0]['open']:,.0f}원")
        print(f"   현재가: {df.iloc[-1]['close']:,.0f}원")
        print(f"   상승률: {((df.iloc[-1]['close'] / df.iloc[0]['open']) - 1) * 100:.2f}%")
        
        # 3. 시간대별 신호 조건 분석
        print(f"\n{'='*60}")
        print("⏰ 시간대별 신호 조건 분석")
        print(f"{'='*60}\n")
        
        # 20분봉 이상 누적되면 체크 시작
        for i in range(20, len(df)):
            sub_df = df.iloc[:i+1]
            closes = sub_df['close'].tolist()
            time_str = sub_df.iloc[-1]['time'].strftime('%H:%M')
            price = sub_df.iloc[-1]['close']
            
            # Golden Cross 체크
            gc_triggered, ma5, ma20, gap = check_golden_cross(closes)
            
            # RSI 체크
            rsi = calculate_rsi(closes)
            rb_triggered, prev_rsi, curr_rsi = check_rsi_rebound(closes, threshold=30)
            
            # 신호 트리거되면 출력
            if gc_triggered:
                print(f"🔔 {time_str} | Golden Cross 발생! | Price={price:,.0f} | MA5={ma5:.0f} > MA20={ma20:.0f}")
            
            if rb_triggered:
                print(f"🔔 {time_str} | RSI Rebound 발생! | Price={price:,.0f} | RSI: {prev_rsi:.1f} → {curr_rsi:.1f}")
            
            # 주요 시간대 정보 출력 (10분마다)
            if i % 10 == 0 or gc_triggered or rb_triggered:
                rsi_str = f"{rsi:.1f}" if rsi else "N/A"
                print(f"   {time_str} | Price={price:,.0f} | RSI={rsi_str} | MA5-MA20={gap:.0f}" if gap else f"   {time_str} | Price={price:,.0f} | RSI={rsi_str}")
        
        # 4. 수급 데이터 확인
        print(f"\n{'='*60}")
        print("💰 수급 데이터 (최근 5일)")
        print(f"{'='*60}\n")
        
        supply_data = session.query(StockInvestorTrading).filter(
            StockInvestorTrading.stock_code == STOCK_CODE
        ).order_by(StockInvestorTrading.trade_date.desc()).limit(5).all()
        
        if supply_data:
            for s in supply_data:
                foreign = int(s.foreign_net_buy or 0)
                inst = int(s.institution_net_buy or 0)
                indiv = int(s.individual_net_buy or 0)
                print(f"   {s.trade_date} | 외국인: {foreign:>12,}원 | 기관: {inst:>12,}원 | 개인: {indiv:>12,}원")
        else:
            print("   수급 데이터 없음")
        
        # 5. 결론
        print(f"\n{'='*60}")
        print("🎯 분석 결론")
        print(f"{'='*60}\n")
        
        # buy-scanner 조건 요약
        print("📋 buy-scanner 매수 신호 조건:")
        print("   1. Golden Cross: MA(5) > MA(20) 상향 돌파")
        print("   2. RSI Rebound: RSI가 30 이하에서 30 이상으로 복귀")
        print("   3. 최소 20개 분봉 데이터 필요")
        print()
        
        if not minute_data:
            print("❌ 문제점: 분봉 데이터가 수집되지 않음")
            print("   → buy-scanner가 실시간 가격을 수신하지 못했거나")
            print("   → BarAggregator에서 분봉이 완성되지 않았을 가능성")
        else:
            print("⚠️ 추가 확인 필요:")
            print("   → buy-scanner 로그에서 에스엘(005850) 가격 수신 여부 확인")
            print("   → Hot Watchlist에 에스엘이 포함되어 있었는지 확인")

if __name__ == "__main__":
    analyze_minute_data()
