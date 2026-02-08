#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Performance API Router
======================
투자 성과 조회 API

GET /api/performance
- 기간별 실현/평가 손익
- MDD, Profit Factor 등 리스크 지표
- 누적 수익 그래프 데이터
- 종목별 상세 분석
"""

import logging
from datetime import date, datetime, timedelta
from typing import Optional
from enum import Enum

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel

import sys
import os
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(current_dir))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.db.connection import get_session
from shared.analysis.performance_calculator import get_performance_data

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/performance", tags=["performance"])


class PeriodPreset(str, Enum):
    TODAY = "today"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"
    ALL = "all"


class PeriodInfo(BaseModel):
    start: Optional[str]
    end: Optional[str]


class RealizedProfit(BaseModel):
    total_buy_amount: float
    total_sell_amount: float
    gross_profit: float
    fees: float
    taxes: float
    net_profit: float
    net_profit_rate: float


class UnrealizedProfit(BaseModel):
    total_value: float
    total_cost: float
    unrealized_profit: float
    unrealized_profit_rate: float


class TradeStats(BaseModel):
    trade_count: dict
    win_count: int
    loss_count: int
    win_rate: float
    profit_factor: Optional[float]
    mdd: float


class CumulativePoint(BaseModel):
    date: str
    profit: float


class StockPerformance(BaseModel):
    stock_code: str
    stock_name: str
    buy_amount: float
    sell_amount: float
    net_profit: float
    profit_rate: float


class PerformanceResponse(BaseModel):
    period: PeriodInfo
    realized: RealizedProfit
    unrealized: UnrealizedProfit
    stats: TradeStats
    cumulative_profit_curve: list[CumulativePoint]
    by_stock: list[StockPerformance]


def get_date_range(preset: Optional[PeriodPreset], start_date: Optional[date], end_date: Optional[date]):
    """프리셋 또는 직접 입력된 날짜 범위 계산"""
    today = date.today()
    
    if preset:
        if preset == PeriodPreset.TODAY:
            return today, today
        elif preset == PeriodPreset.WEEK:
            start = today - timedelta(days=today.weekday())  # 이번 주 월요일
            return start, today
        elif preset == PeriodPreset.MONTH:
            start = today.replace(day=1)  # 이번 달 1일
            return start, today
        elif preset == PeriodPreset.YEAR:
            start = today.replace(month=1, day=1)  # 올해 1월 1일
            return start, today
        elif preset == PeriodPreset.ALL:
            return None, today
    
    # 직접 입력
    return start_date, end_date or today


@router.get("", response_model=PerformanceResponse)
async def get_performance(
    preset: Optional[PeriodPreset] = Query(None, description="기간 프리셋 (today/week/month/year/all)"),
    start_date: Optional[date] = Query(None, description="시작일 (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="종료일 (YYYY-MM-DD)"),
):
    """
    투자 성과 조회 API
    
    - **preset**: 기간 프리셋 (today/week/month/year/all)
    - **start_date**: 시작일 (프리셋이 없을 때)
    - **end_date**: 종료일 (프리셋이 없을 때)
    
    Returns:
        실현 손익, 평가 손익, 통계, 누적 수익 그래프, 종목별 상세
    """
    try:
        start, end = get_date_range(preset, start_date, end_date)
        
        with get_session() as session:
            data = get_performance_data(session, start, end)
            
            return PerformanceResponse(
                period=PeriodInfo(**data['period']),
                realized=RealizedProfit(**data['realized']),
                unrealized=UnrealizedProfit(**data['unrealized']),
                stats=TradeStats(**data['stats']),
                cumulative_profit_curve=[CumulativePoint(**p) for p in data['cumulative_profit_curve']],
                by_stock=[StockPerformance(**s) for s in data['by_stock']]
            )
            
    except Exception as e:
        logger.error(f"Performance 조회 실패: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary")
async def get_performance_summary():
    """
    간단한 성과 요약 (Overview 페이지용)
    
    Returns:
        이번 달 순수익, 수익률, 승률
    """
    try:
        today = date.today()
        start = today.replace(day=1)  # 이번 달 1일
        
        with get_session() as session:
            data = get_performance_data(session, start, today)
            
            return {
                "period": "month",
                "net_profit": data['realized']['net_profit'],
                "profit_rate": data['realized']['net_profit_rate'],
                "win_rate": data['stats']['win_rate'],
                "trade_count": data['stats']['trade_count']['sell'],
                "mdd": data['stats']['mdd']
            }
            
    except Exception as e:
        logger.error(f"Performance Summary 조회 실패: {e}")
        return {
            "period": "month",
            "net_profit": 0,
            "profit_rate": 0,
            "win_rate": 0,
            "trade_count": 0,
            "mdd": 0,
            "error": str(e)
        }
