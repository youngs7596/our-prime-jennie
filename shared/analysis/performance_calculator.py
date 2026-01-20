#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
performance_calculator.py
=========================
투자 성과 계산 모듈

가족 법인 자산운용 관점의 수익 계산:
- 실현 손익 (Realized Profit): 매도 완료 거래의 순수익
- 평가 손익 (Unrealized Profit): 현재 보유 종목의 미실현 손익
- MDD (Maximum Drawdown): 최대 낙폭
- Profit Factor: 수익팩터

수수료/거래세 반영:
- 거래세: 0.23% (매도 시에만)
- 증권사 수수료: 0.015% (매수/매도 양쪽)
"""

import logging
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any, Tuple
from collections import defaultdict

from sqlalchemy import func, and_, text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# 수수료/세금 비율 (한국투자증권 기준)
TRADING_TAX_RATE = 0.0023      # 거래세 0.23% (매도 시에만)
BROKER_FEE_RATE = 0.000015     # 증권사 수수료 0.0015% (매수/매도 양쪽) - 한투 기준 낮음


def calculate_net_profit_for_trade(
    buy_price: float,
    sell_price: float,
    quantity: int
) -> Dict[str, float]:
    """
    단일 거래의 순수익 계산 (수수료/세금 차감)
    
    Returns:
        {
            'gross_profit': 총손익 (세전),
            'buy_fee': 매수 수수료,
            'sell_fee': 매도 수수료,
            'tax': 거래세,
            'net_profit': 순수익 (세후)
        }
    """
    buy_amount = buy_price * quantity
    sell_amount = sell_price * quantity
    
    gross_profit = sell_amount - buy_amount
    buy_fee = buy_amount * BROKER_FEE_RATE
    sell_fee = sell_amount * BROKER_FEE_RATE
    tax = sell_amount * TRADING_TAX_RATE
    
    net_profit = gross_profit - buy_fee - sell_fee - tax
    
    return {
        'gross_profit': gross_profit,
        'buy_fee': buy_fee,
        'sell_fee': sell_fee,
        'tax': tax,
        'total_fees': buy_fee + sell_fee + tax,
        'net_profit': net_profit
    }


def get_performance_data(
    session: Session,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None
) -> Dict[str, Any]:
    """
    기간별 투자 성과 데이터 조회
    
    Args:
        session: DB 세션
        start_date: 시작일 (None이면 전체)
        end_date: 종료일 (None이면 오늘)
    
    Returns:
        성과 데이터 딕셔너리
    """
    from shared.db.models import TradeLog, ActivePortfolio, WatchList
    
    if end_date is None:
        end_date = date.today()
    
    # 기간 필터 조건
    date_filter = []
    if start_date:
        date_filter.append(TradeLog.trade_timestamp >= datetime.combine(start_date, datetime.min.time()))
    if end_date:
        date_filter.append(TradeLog.trade_timestamp <= datetime.combine(end_date, datetime.max.time()))
    
    # 1. 기간 내 거래 조회
    query = session.query(TradeLog)
    if date_filter:
        query = query.filter(and_(*date_filter))
    trades = query.order_by(TradeLog.trade_timestamp).all()
    
    # 2. 매수/매도 분리
    buys = [t for t in trades if t.trade_type == 'BUY']
    sells = [t for t in trades if t.trade_type == 'SELL']
    
    # 3. 종목별 매칭 및 손익 계산 (FIFO 방식)
    # 종목별 매수 큐
    buy_queue = defaultdict(list)  # {stock_code: [(price, qty, timestamp), ...]}
    
    for buy in buys:
        buy_queue[buy.stock_code].append({
            'price': buy.price,
            'quantity': buy.quantity,
            'timestamp': buy.trade_timestamp
        })
    
    # 실현 손익 계산
    realized_trades = []
    total_gross_profit = 0
    total_fees = 0
    total_taxes = 0
    total_buy_amount = 0
    total_sell_amount = 0
    wins = 0
    losses = 0
    total_profit_amount = 0  # 총 이익금 (승리 거래)
    total_loss_amount = 0    # 총 손실금 (패배 거래)
    
    for sell in sells:
        code = sell.stock_code
        sell_qty = sell.quantity
        sell_price = sell.price
        sell_amount = sell_price * sell_qty
        
        matched_buy_amount = 0
        matched_qty = 0
        
        # FIFO 매칭
        while sell_qty > 0 and buy_queue[code]:
            buy = buy_queue[code][0]
            match_qty = min(sell_qty, buy['quantity'])
            
            matched_buy_amount += buy['price'] * match_qty
            matched_qty += match_qty
            sell_qty -= match_qty
            buy['quantity'] -= match_qty
            
            if buy['quantity'] == 0:
                buy_queue[code].pop(0)
        
        if matched_qty > 0:
            # 손익 계산
            result = calculate_net_profit_for_trade(
                matched_buy_amount / matched_qty,
                sell_price,
                matched_qty
            )
            
            total_gross_profit += result['gross_profit']
            total_fees += result['buy_fee'] + result['sell_fee']
            total_taxes += result['tax']
            total_buy_amount += matched_buy_amount
            total_sell_amount += sell_price * matched_qty
            
            if result['net_profit'] > 0:
                wins += 1
                total_profit_amount += result['net_profit']
            else:
                losses += 1
                total_loss_amount += abs(result['net_profit'])
            
            realized_trades.append({
                'stock_code': code,
                'sell_timestamp': sell.trade_timestamp,
                'buy_amount': matched_buy_amount,
                'sell_amount': sell_price * matched_qty,
                'quantity': matched_qty,
                'net_profit': result['net_profit'],
                'profit_rate': (result['net_profit'] / matched_buy_amount * 100) if matched_buy_amount > 0 else 0
            })
    
    # 4. 현재 보유 종목 평가손익 (Unrealized)
    holdings = session.query(ActivePortfolio).all()
    unrealized_cost = 0
    unrealized_value = 0
    
    # 실시간 현재가 조회 준비
    stock_codes = [h.stock_code for h in holdings]
    current_prices = {}
    if stock_codes:
        try:
            from shared.db.repository import fetch_current_prices_from_kis
            current_prices = fetch_current_prices_from_kis(stock_codes)
        except Exception as e:
            logger.warning(f"실시간 현재가 조회 실패: {e}")

    # 현재가 반영 및 계산
    for h in holdings:
        cost = h.average_buy_price * h.quantity
        unrealized_cost += cost
        
        # 실시간 가격 적용 (없으면 매수가 사용)
        current_price = current_prices.get(h.stock_code, h.average_buy_price)
        unrealized_value += current_price * h.quantity
    
    unrealized_profit = unrealized_value - unrealized_cost
    
    # 5. MDD 계산 (Equity Curve 기준)
    # [Fix] 단순히 누적 수익(cumulative)만으로 계산하면 분모가 작아 MDD가 과장됨 (-80% 등)
    # 따라서 가상의 초기 자본금(Initial Capital)을 더해 전체 자산(Equity)의 변동폭으로 계산
    INITIAL_CAPITAL = 200_000_000  # 기본 자본금 2억 가정 (추후 Config 화 가능)
    
    cumulative_profits = []
    cumulative = 0
    peak_equity = INITIAL_CAPITAL
    mdd = 0
    
    for trade in realized_trades:
        cumulative += trade['net_profit']
        current_equity = INITIAL_CAPITAL + cumulative
        
        cumulative_profits.append({
            'date': trade['sell_timestamp'].strftime('%Y-%m-%d'),
            'profit': cumulative
        })
        
        if current_equity > peak_equity:
            peak_equity = current_equity
        
        # Peak 대비 현재 자산의 감소폭
        drawdown = (current_equity - peak_equity) / peak_equity * 100
        if drawdown < mdd:
            mdd = drawdown
    
    # 6. Profit Factor
    profit_factor = (total_profit_amount / total_loss_amount) if total_loss_amount > 0 else float('inf')
    
    # 7. 종목별 합산
    by_stock = defaultdict(lambda: {
        'buy_amount': 0,
        'sell_amount': 0,
        'net_profit': 0,
        'quantity': 0
    })
    
    for trade in realized_trades:
        code = trade['stock_code']
        by_stock[code]['buy_amount'] += trade['buy_amount']
        by_stock[code]['sell_amount'] += trade['sell_amount']
        by_stock[code]['net_profit'] += trade['net_profit']
        by_stock[code]['quantity'] += trade['quantity']
    
    # 종목명 조회
    stock_names = {}
    codes = list(by_stock.keys())
    if codes:
        name_rows = session.query(WatchList.stock_code, WatchList.stock_name).filter(
            WatchList.stock_code.in_(codes)
        ).all()
        stock_names = {r.stock_code: r.stock_name for r in name_rows}
    
    by_stock_list = []
    for code, data in sorted(by_stock.items(), key=lambda x: x[1]['net_profit'], reverse=True):
        if data['buy_amount'] > 0:
            by_stock_list.append({
                'stock_code': code,
                'stock_name': stock_names.get(code, code),
                'buy_amount': data['buy_amount'],
                'sell_amount': data['sell_amount'],
                'net_profit': data['net_profit'],
                'profit_rate': (data['net_profit'] / data['buy_amount'] * 100) if data['buy_amount'] > 0 else 0
            })
    
    # 8. 결과 조합
    net_profit = total_gross_profit - total_fees - total_taxes
    net_profit_rate = (net_profit / total_buy_amount * 100) if total_buy_amount > 0 else 0
    win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
    
    return {
        'period': {
            'start': start_date.isoformat() if start_date else None,
            'end': end_date.isoformat() if end_date else None
        },
        'realized': {
            'total_buy_amount': total_buy_amount,
            'total_sell_amount': total_sell_amount,
            'gross_profit': total_gross_profit,
            'fees': total_fees,
            'taxes': total_taxes,
            'net_profit': net_profit,
            'net_profit_rate': net_profit_rate
        },
        'unrealized': {
            'total_value': unrealized_value,
            'total_cost': unrealized_cost,
            'unrealized_profit': unrealized_profit,
            'unrealized_profit_rate': (unrealized_profit / unrealized_cost * 100) if unrealized_cost > 0 else 0
        },
        'stats': {
            'trade_count': {'buy': len(buys), 'sell': len(sells)},
            'win_count': wins,
            'loss_count': losses,
            'win_rate': win_rate,
            'profit_factor': profit_factor if profit_factor != float('inf') else None,
            'mdd': mdd
        },
        'cumulative_profit_curve': cumulative_profits,
        'by_stock': by_stock_list
    }
