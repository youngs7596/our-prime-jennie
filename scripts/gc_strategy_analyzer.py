#!/usr/bin/env python3
"""
Golden Cross 전략 분석기
========================
1. Minji 제안: GC 전 10일 수익률 vs 거래 결과 상관관계
2. Junho 제안: MAE/MFE 분석으로 스탑 파라미터 최적화

Usage:
    source .venv/bin/activate
    python scripts/gc_strategy_analyzer.py
"""

import sys
import os
from datetime import datetime, timedelta
from typing import List, Dict, Tuple
import statistics

sys.path.append(os.getcwd())

from shared.db.connection import init_engine, session_scope
from shared.db.models import TradeLog
from sqlalchemy import select, text


def get_gc_trades(session, days: int = 90) -> List[Dict]:
    """최근 N일간 Golden Cross 매수 거래 조회"""
    start_date = datetime.utcnow() - timedelta(days=days)
    
    stmt = select(TradeLog).where(
        TradeLog.trade_timestamp >= start_date,
        TradeLog.strategy_signal.like('%GOLDEN_CROSS%'),
        TradeLog.trade_type == 'BUY'
    ).order_by(TradeLog.trade_timestamp)
    
    buy_trades = session.execute(stmt).scalars().all()
    
    results = []
    for buy in buy_trades:
        # 매도 거래 찾기
        stmt_sell = select(TradeLog).where(
            TradeLog.stock_code == buy.stock_code,
            TradeLog.trade_type == 'SELL',
            TradeLog.trade_timestamp > buy.trade_timestamp
        ).order_by(TradeLog.trade_timestamp).limit(1)
        
        sell = session.execute(stmt_sell).scalars().first()
        
        if sell:
            profit_pct = (sell.price - buy.price) / buy.price * 100
            status = "CLOSED"
            sell_price = sell.price
            sell_date = sell.trade_timestamp.date()
        else:
            profit_pct = None
            status = "OPEN"
            sell_price = None
            sell_date = None
        
        results.append({
            "stock_code": buy.stock_code,
            "buy_date": buy.trade_timestamp.date(),
            "buy_price": buy.price,
            "sell_date": sell_date,
            "sell_price": sell_price,
            "profit_pct": profit_pct,
            "status": status
        })
    
    return results


def get_price_context(session, stock_code: str, buy_date, days_before: int = 10, days_after: int = 20) -> Dict:
    """GC 전후 주가 데이터 조회"""
    ctx_start = buy_date - timedelta(days=days_before + 5)  # 주말 고려
    ctx_end = buy_date + timedelta(days=days_after + 5)
    
    stmt = text("""
        SELECT PRICE_DATE, CLOSE_PRICE, HIGH_PRICE, LOW_PRICE
        FROM STOCK_DAILY_PRICES_3Y
        WHERE STOCK_CODE = :code 
          AND PRICE_DATE BETWEEN :start AND :end
        ORDER BY PRICE_DATE ASC
    """)
    
    rows = session.execute(stmt, {"code": stock_code, "start": ctx_start, "end": ctx_end}).fetchall()
    
    prices = {}
    for r in rows:
        prices[r.PRICE_DATE.date()] = {
            "close": float(r.CLOSE_PRICE),
            "high": float(r.HIGH_PRICE),
            "low": float(r.LOW_PRICE)
        }
    
    return prices


def analyze_pre_gc_returns(trades: List[Dict], session) -> Dict:
    """Minji 제안: GC 전 10일 수익률 분석"""
    print("\n" + "=" * 60)
    print("📊 Minji 분석: GC 전 10일 수익률 vs 거래 결과")
    print("=" * 60)
    
    results = []
    
    for trade in trades:
        if trade["status"] != "CLOSED":
            continue
            
        prices = get_price_context(session, trade["stock_code"], trade["buy_date"])
        
        # GC 10일 전 종가 찾기
        target_date = trade["buy_date"] - timedelta(days=10)
        
        # 정확히 10일 전이 없으면 가장 가까운 과거 날짜
        pre_gc_price = None
        for i in range(5):  # 최대 5일 추가로 찾기
            check_date = target_date - timedelta(days=i)
            if check_date in prices:
                pre_gc_price = prices[check_date]["close"]
                break
        
        if pre_gc_price is None or trade["buy_date"] not in prices:
            continue
        
        gc_price = prices[trade["buy_date"]]["close"]
        pre_gc_return = (gc_price - pre_gc_price) / pre_gc_price * 100
        
        results.append({
            "stock_code": trade["stock_code"],
            "buy_date": trade["buy_date"],
            "pre_gc_return": pre_gc_return,
            "profit_pct": trade["profit_pct"],
            "is_profitable": trade["profit_pct"] > 0
        })
    
    # 분석
    profitable = [r for r in results if r["is_profitable"]]
    losers = [r for r in results if not r["is_profitable"]]
    
    print(f"\n📌 총 분석 거래: {len(results)}건 (수익: {len(profitable)}, 손실: {len(losers)})")
    
    if profitable:
        avg_pre_gc_profitable = statistics.mean([r["pre_gc_return"] for r in profitable])
        print(f"✅ 수익 거래 - GC 전 10일 평균 수익률: {avg_pre_gc_profitable:.2f}%")
    
    if losers:
        avg_pre_gc_losers = statistics.mean([r["pre_gc_return"] for r in losers])
        print(f"❌ 손실 거래 - GC 전 10일 평균 수익률: {avg_pre_gc_losers:.2f}%")
    
    # 임계값 테스트 (과열 > +10%, +15%, +20%)
    print("\n📊 임계값 테스트 (과열 시 필터링 효과):")
    for threshold in [10, 15, 20]:
        filtered_out = [r for r in results if r["pre_gc_return"] > threshold]
        filtered_out_losers = [r for r in filtered_out if not r["is_profitable"]]
        filtered_out_winners = [r for r in filtered_out if r["is_profitable"]]
        
        if filtered_out:
            print(f"  - 임계값 +{threshold}%: 필터링 {len(filtered_out)}건 "
                  f"(손실 {len(filtered_out_losers)}, 수익 {len(filtered_out_winners)})")
    
    return {
        "total": len(results),
        "profitable_avg_pre_gc": statistics.mean([r["pre_gc_return"] for r in profitable]) if profitable else 0,
        "loser_avg_pre_gc": statistics.mean([r["pre_gc_return"] for r in losers]) if losers else 0,
        "details": results
    }


def analyze_mae_mfe(trades: List[Dict], session) -> Dict:
    """Junho 제안: MAE/MFE 분석"""
    print("\n" + "=" * 60)
    print("📈 Junho 분석: MAE/MFE (Maximum Adverse/Favorable Excursion)")
    print("=" * 60)
    
    results = []
    
    for trade in trades:
        if trade["status"] != "CLOSED":
            continue
        
        prices = get_price_context(session, trade["stock_code"], trade["buy_date"], days_before=0, days_after=30)
        
        buy_price = trade["buy_price"]
        sell_date = trade["sell_date"]
        
        # 진입일부터 청산일까지의 High/Low
        max_high = buy_price
        min_low = buy_price
        
        for d, p in prices.items():
            if trade["buy_date"] <= d <= sell_date:
                max_high = max(max_high, p["high"])
                min_low = min(min_low, p["low"])
        
        mae = (buy_price - min_low) / buy_price * 100  # 최대 하락폭 (%)
        mfe = (max_high - buy_price) / buy_price * 100  # 최대 상승폭 (%)
        
        results.append({
            "stock_code": trade["stock_code"],
            "buy_date": trade["buy_date"],
            "buy_price": buy_price,
            "profit_pct": trade["profit_pct"],
            "mae": mae,
            "mfe": mfe,
            "is_profitable": trade["profit_pct"] > 0
        })
    
    if not results:
        print("분석 가능한 거래가 없습니다.")
        return {}
    
    # 분석
    profitable = [r for r in results if r["is_profitable"]]
    losers = [r for r in results if not r["is_profitable"]]
    
    print(f"\n📌 총 분석 거래: {len(results)}건 (수익: {len(profitable)}, 손실: {len(losers)})")
    
    all_mae = [r["mae"] for r in results]
    all_mfe = [r["mfe"] for r in results]
    
    print(f"\n📉 MAE (Maximum Adverse Excursion - 최대 하락폭):")
    print(f"   전체 평균: {statistics.mean(all_mae):.2f}%")
    print(f"   전체 중앙값: {statistics.median(all_mae):.2f}%")
    print(f"   최대: {max(all_mae):.2f}%")
    
    print(f"\n📈 MFE (Maximum Favorable Excursion - 최대 상승폭):")
    print(f"   전체 평균: {statistics.mean(all_mfe):.2f}%")
    print(f"   전체 중앙값: {statistics.median(all_mfe):.2f}%")
    print(f"   최대: {max(all_mfe):.2f}%")
    
    # 손익별 MAE 분석
    if profitable:
        profitable_mae = [r["mae"] for r in profitable]
        print(f"\n✅ 수익 거래 MAE 평균: {statistics.mean(profitable_mae):.2f}%")
    
    if losers:
        loser_mae = [r["mae"] for r in losers]
        print(f"❌ 손실 거래 MAE 평균: {statistics.mean(loser_mae):.2f}%")
    
    # 스탑 파라미터 추천
    print("\n💡 스탑 파라미터 추천:")
    
    # Hard Stop: 손실 거래의 MAE 중앙값 기준
    if losers:
        loser_mae_median = statistics.median([r["mae"] for r in losers])
        recommended_hard_stop = min(loser_mae_median * 0.8, 6)  # 80% 수준, 최대 6%
        print(f"   - Hard Stop: -{recommended_hard_stop:.1f}% (손실 거래 MAE 중앙값 기반)")
    
    # Trailing Stop: 수익 거래의 MFE 기반
    if profitable:
        profitable_mfe = [r["mfe"] for r in profitable]
        recommended_trailing = statistics.median(profitable_mfe) * 0.3  # MFE의 30% 수준
        print(f"   - Trailing Stop: {recommended_trailing:.1f}% (수익 거래 MFE 기반)")
    
    return {
        "total": len(results),
        "avg_mae": statistics.mean(all_mae),
        "avg_mfe": statistics.mean(all_mfe),
        "details": results
    }


def generate_report(pre_gc_result: Dict, mae_mfe_result: Dict):
    """분석 리포트 생성"""
    os.makedirs("reports", exist_ok=True)
    
    # Pre-GC 리포트
    with open("reports/gc_pre_return_analysis.md", "w", encoding="utf-8") as f:
        f.write("# GC 전 10일 수익률 분석 (Minji 제안)\n\n")
        f.write(f"**분석일**: {datetime.now().strftime('%Y-%m-%d')}\n\n")
        f.write(f"## 요약\n")
        f.write(f"- 분석 대상: {pre_gc_result.get('total', 0)}건 청산 거래\n")
        f.write(f"- 수익 거래 GC 전 평균 수익률: {pre_gc_result.get('profitable_avg_pre_gc', 0):.2f}%\n")
        f.write(f"- 손실 거래 GC 전 평균 수익률: {pre_gc_result.get('loser_avg_pre_gc', 0):.2f}%\n\n")
        
        f.write("## 상세 데이터\n")
        f.write("| 종목코드 | GC일 | GC 전 10일 수익률 | 거래 결과 |\n")
        f.write("|----------|------|------------------|----------|\n")
        for d in pre_gc_result.get("details", []):
            result_emoji = "✅" if d["is_profitable"] else "❌"
            f.write(f"| {d['stock_code']} | {d['buy_date']} | {d['pre_gc_return']:.2f}% | {result_emoji} {d['profit_pct']:.2f}% |\n")
    
    # MAE/MFE 리포트
    with open("reports/gc_mae_mfe_analysis.md", "w", encoding="utf-8") as f:
        f.write("# MAE/MFE 분석 (Junho 제안)\n\n")
        f.write(f"**분석일**: {datetime.now().strftime('%Y-%m-%d')}\n\n")
        f.write(f"## 요약\n")
        f.write(f"- 분석 대상: {mae_mfe_result.get('total', 0)}건 청산 거래\n")
        f.write(f"- 평균 MAE (최대 하락폭): {mae_mfe_result.get('avg_mae', 0):.2f}%\n")
        f.write(f"- 평균 MFE (최대 상승폭): {mae_mfe_result.get('avg_mfe', 0):.2f}%\n\n")
        
        f.write("## 상세 데이터\n")
        f.write("| 종목코드 | GC일 | MAE | MFE | 거래 결과 |\n")
        f.write("|----------|------|-----|-----|----------|\n")
        for d in mae_mfe_result.get("details", []):
            result_emoji = "✅" if d["is_profitable"] else "❌"
            f.write(f"| {d['stock_code']} | {d['buy_date']} | -{d['mae']:.2f}% | +{d['mfe']:.2f}% | {result_emoji} {d['profit_pct']:.2f}% |\n")
    
    print("\n✅ 리포트 생성 완료:")
    print("   - reports/gc_pre_return_analysis.md")
    print("   - reports/gc_mae_mfe_analysis.md")


def main():
    print("Golden Cross 전략 분석기")
    print("=" * 60)
    
    init_engine()
    
    with session_scope() as session:
        # 거래 데이터 조회
        trades = get_gc_trades(session)
        print(f"📦 조회된 GC 거래: {len(trades)}건")
        
        closed_trades = [t for t in trades if t["status"] == "CLOSED"]
        print(f"   - 청산 완료: {len(closed_trades)}건")
        print(f"   - 보유 중: {len(trades) - len(closed_trades)}건")
        
        if not closed_trades:
            print("분석 가능한 청산 거래가 없습니다.")
            return
        
        # 분석 실행
        pre_gc_result = analyze_pre_gc_returns(trades, session)
        mae_mfe_result = analyze_mae_mfe(trades, session)
        
        # 리포트 생성
        generate_report(pre_gc_result, mae_mfe_result)
        
        print("\n" + "=" * 60)
        print("🎯 분석 완료!")
        print("=" * 60)


if __name__ == "__main__":
    main()
