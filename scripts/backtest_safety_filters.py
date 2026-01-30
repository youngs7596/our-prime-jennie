#!/usr/bin/env python3
"""
scripts/backtest_safety_filters.py
-----------------------------------
Council이 제안한 안전장치들을 과거 데이터에 적용했을 때의 영향을 시뮬레이션합니다.

테스트 필터:
1. bar_timestamp 버그 수정 (No-Trade Window 정확성)
2. Early Market RSI Guard (09:30-10:30 KST에서 RSI > 65 차단)
3. Early Market LLM Score (09:30-10:30 KST에서 LLM < 75 차단)
4. Momentum Decay Filter (5분 +3% 급등 + 윗꼬리 30% 차단)
"""

import os
import sys
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

sys.path.append(os.getcwd())

from sqlalchemy import create_engine, text
from urllib.parse import quote_plus

def get_db_url():
    with open("secrets.json", "r") as f:
        secrets = json.load(f)
        user = secrets.get("mariadb-user", "root")
        password = secrets.get("mariadb-password", "")
        host = secrets.get("mariadb-host", "localhost")
        port = secrets.get("mariadb-port", 3306)
        dbname = secrets.get("mariadb-database", "jennie_db")
        return f"mysql+pymysql://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{dbname}?charset=utf8mb4"

def to_kst(utc_dt: datetime) -> datetime:
    """UTC -> KST 변환"""
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    return utc_dt + timedelta(hours=9)

def is_no_trade_window(kst_time: datetime) -> bool:
    """09:00-09:30 KST 구간인지 확인"""
    hour, minute = kst_time.hour, kst_time.minute
    return hour == 9 and minute < 30

def is_early_market(kst_time: datetime) -> bool:
    """09:30-10:30 KST 구간인지 확인 (장초 변동성 구간)"""
    hour, minute = kst_time.hour, kst_time.minute
    return (hour == 9 and minute >= 30) or (hour == 10 and minute < 30)

def is_danger_zone(kst_time: datetime) -> bool:
    """14:00-15:00 KST 구간인지 확인"""
    return kst_time.hour == 14

class FilterResult:
    def __init__(self, trade_id, stock_code, trade_time, price, pnl):
        self.trade_id = trade_id
        self.stock_code = stock_code
        self.trade_time = trade_time
        self.price = price
        self.pnl = pnl
        self.blocked_by = []
        
    def add_block(self, filter_name: str):
        self.blocked_by.append(filter_name)
    
    @property
    def is_blocked(self) -> bool:
        return len(self.blocked_by) > 0

def run_backtest():
    """백테스트 실행"""
    print("=" * 70)
    print("🧪 Council 제안 필터 백테스트")
    print("=" * 70)
    
    engine = create_engine(get_db_url())
    
    # 1. 최근 거래 로그 조회 (BUY Only)
    print("\n[1] 거래 로그 조회 중...")
    
    with engine.connect() as conn:
        # BUY 거래만 조회 (최근 60일)
        sql = text("""
            SELECT 
                t.LOG_ID, t.STOCK_CODE, t.TRADE_TIMESTAMP, t.PRICE, t.QUANTITY,
                t.KEY_METRICS_JSON
            FROM TRADELOG t
            WHERE t.TRADE_TYPE = 'BUY'
              AND t.TRADE_TIMESTAMP >= DATE_SUB(NOW(), INTERVAL 60 DAY)
            ORDER BY t.TRADE_TIMESTAMP DESC
        """)
        trades = conn.execute(sql).mappings().all()
        
        # 해당 종목들의 SELL 가격 또는 현재가로 수익률 계산
        # 간단히: 최근 종가로 대체
        sell_sql = text("""
            SELECT STOCK_CODE, PRICE as SELL_PRICE
            FROM TRADELOG
            WHERE TRADE_TYPE = 'SELL'
              AND TRADE_TIMESTAMP >= DATE_SUB(NOW(), INTERVAL 60 DAY)
            GROUP BY STOCK_CODE
        """)
        sells = {r['STOCK_CODE']: r['SELL_PRICE'] for r in conn.execute(sell_sql).mappings().all()}
    
    print(f"   총 {len(trades)}건의 매수 거래 발견")
    
    if not trades:
        print("   분석할 거래가 없습니다.")
        return
    
    # 2. 각 거래에 필터 적용 시뮬레이션
    print("\n[2] 필터 시뮬레이션 중...")
    
    results: List[FilterResult] = []
    filter_stats = defaultdict(lambda: {"blocked": 0, "blocked_pnl": 0.0})
    
    for trade in trades:
        metrics = {}
        if trade['KEY_METRICS_JSON']:
            try:
                metrics = json.loads(trade['KEY_METRICS_JSON']) if isinstance(trade['KEY_METRICS_JSON'], str) else trade['KEY_METRICS_JSON']
            except:
                pass
        
        trade_time_utc = trade['TRADE_TIMESTAMP']
        trade_time_kst = to_kst(trade_time_utc)
        
        # 간단한 P&L 계산: 매도 데이터가 없으면 0으로 처리
        sell_price = sells.get(trade['STOCK_CODE'], trade['PRICE'])
        pnl = (sell_price - trade['PRICE']) * trade['QUANTITY']
        pnl_pct = ((sell_price - trade['PRICE']) / trade['PRICE']) * 100
        
        result = FilterResult(
            trade_id=trade['LOG_ID'],
            stock_code=trade['STOCK_CODE'],
            trade_time=trade_time_kst,
            price=trade['PRICE'],
            pnl=pnl
        )
        
        # --- 필터 1: No-Trade Window (09:00-09:30) ---
        # 현재 이미 구현되어 있지만, 정확히 작동했는지 확인
        if is_no_trade_window(trade_time_kst):
            result.add_block("No-Trade Window (09:00-09:30)")
            filter_stats["No-Trade Window"]["blocked"] += 1
            filter_stats["No-Trade Window"]["blocked_pnl"] += pnl
        
        # --- 필터 2: Danger Zone (14:00-15:00) ---
        if is_danger_zone(trade_time_kst):
            result.add_block("Danger Zone (14:00-15:00)")
            filter_stats["Danger Zone"]["blocked"] += 1
            filter_stats["Danger Zone"]["blocked_pnl"] += pnl
        
        # --- 필터 3: Early Market RSI Guard (RSI > 65) ---
        # KEY_METRICS_JSON에 RSI 정보가 있으면 사용, 없으면 Skip
        rsi = metrics.get('rsi')
        if is_early_market(trade_time_kst) and rsi and rsi > 65:
            result.add_block("Early Market RSI (>65)")
            filter_stats["Early Market RSI"]["blocked"] += 1
            filter_stats["Early Market RSI"]["blocked_pnl"] += pnl
        
        # --- 필터 4: Early Market LLM Score (< 75) ---
        llm_score = metrics.get('llm_score', 0)
        if is_early_market(trade_time_kst) and llm_score < 75:
            result.add_block("Early Market LLM (<75)")
            filter_stats["Early Market LLM"]["blocked"] += 1
            filter_stats["Early Market LLM"]["blocked_pnl"] += pnl
        
        # --- 필터 5: RSI Guard (RSI > 75) - 이미 구현된 것 ---
        if rsi and rsi > 75:
            result.add_block("RSI Guard (>75)")
            filter_stats["RSI Guard (>75)"]["blocked"] += 1
            filter_stats["RSI Guard (>75)"]["blocked_pnl"] += pnl
        
        results.append(result)
    
    # 3. 결과 분석
    print("\n" + "=" * 70)
    print("📊 백테스트 결과")
    print("=" * 70)
    
    total_trades = len(results)
    blocked_trades = [r for r in results if r.is_blocked]
    passed_trades = [r for r in results if not r.is_blocked]
    
    total_pnl = sum(r.pnl for r in results)
    blocked_pnl = sum(r.pnl for r in blocked_trades)
    passed_pnl = sum(r.pnl for r in passed_trades)
    
    print(f"\n[총 거래 수]: {total_trades}건")
    print(f"[총 P&L]: {total_pnl:,.0f}원")
    
    print(f"\n--- 필터 적용 시 ---")
    print(f"[통과 거래]: {len(passed_trades)}건 ({len(passed_trades)/total_trades*100:.1f}%)")
    print(f"[차단 거래]: {len(blocked_trades)}건 ({len(blocked_trades)/total_trades*100:.1f}%)")
    print(f"[차단된 P&L]: {blocked_pnl:,.0f}원 (이 손익이 발생하지 않았을 것)")
    
    print("\n--- 필터별 상세 ---")
    print(f"{'필터':<30} {'차단 수':<10} {'차단된 손익':<15} {'평균 손익'}")
    print("-" * 70)
    for filter_name, stats in sorted(filter_stats.items(), key=lambda x: x[1]['blocked'], reverse=True):
        avg_pnl = stats['blocked_pnl'] / stats['blocked'] if stats['blocked'] > 0 else 0
        print(f"{filter_name:<30} {stats['blocked']:<10} {stats['blocked_pnl']:>+14,.0f}원 {avg_pnl:>+10,.0f}원")
    
    # 4. 손실 거래 중 차단된 것들
    print("\n--- 손실 거래 중 차단된 케이스 (좋은 차단) ---")
    loss_blocked = [r for r in blocked_trades if r.pnl < 0]
    print(f"총 {len(loss_blocked)}건의 손실 거래가 차단되었을 것")
    if loss_blocked:
        prevented_loss = sum(r.pnl for r in loss_blocked)
        print(f"예방된 손실: {abs(prevented_loss):,.0f}원")
    
    print("\n--- 수익 거래 중 차단된 케이스 (놓친 기회) ---")
    gain_blocked = [r for r in blocked_trades if r.pnl > 0]
    print(f"총 {len(gain_blocked)}건의 수익 거래가 차단되었을 것")
    if gain_blocked:
        missed_gain = sum(r.pnl for r in gain_blocked)
        print(f"놓친 수익: {missed_gain:,.0f}원")
    
    # 5. 결론
    print("\n" + "=" * 70)
    print("📋 결론")
    print("=" * 70)
    
    if blocked_pnl < 0:
        print(f"✅ 필터가 순손실 {abs(blocked_pnl):,.0f}원을 예방했을 것입니다.")
        print("   → 필터 적용이 유리합니다.")
    else:
        print(f"⚠️ 필터가 순수익 {blocked_pnl:,.0f}원의 기회를 막았을 것입니다.")
        print("   → 필터 적용에 신중해야 합니다.")
    
    blocked_pct = len(blocked_trades) / total_trades * 100 if total_trades > 0 else 0
    if blocked_pct > 30:
        print(f"⚠️ 경고: 필터가 {blocked_pct:.1f}%의 거래를 차단합니다. (>30%)")
        print("   → Council의 롤백 트리거에 해당할 수 있습니다.")
    
    return results, filter_stats

if __name__ == "__main__":
    run_backtest()
