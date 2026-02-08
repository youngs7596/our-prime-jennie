
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import logging
from sqlalchemy import text  # Add this import

from shared.db.connection import get_session
from shared.db.repository import (
    get_portfolio_summary,
    get_portfolio_with_current_prices,
)
from shared.db.models import DailyAssetSnapshot # For history
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/portfolio",
    tags=["portfolio"],
    responses={404: {"description": "Not found"}},
)

# Pydantic models (moved from main.py)
class PortfolioSummary(BaseModel):
    total_value: float
    total_invested: float
    total_profit: float
    profit_rate: float
    cash_balance: float
    positions_count: int

class Position(BaseModel):
    stock_code: str
    stock_name: str
    quantity: int
    avg_price: float
    current_price: float
    profit: float
    profit_rate: float
    weight: float

class PortfolioHistoryItem(BaseModel):
    date: str
    total_asset: float
    cash_balance: float
    stock_eval: float
    total_profit: float

@router.get("/summary", response_model=PortfolioSummary)
async def get_portfolio_summary_api():
    """포트폴리오 요약 정보"""
    try:
        with get_session() as session:
            summary = get_portfolio_summary(session)
            return PortfolioSummary(
                total_value=summary.get("total_value", 0),
                total_invested=summary.get("total_invested", 0),
                total_profit=summary.get("total_profit", 0),
                profit_rate=summary.get("profit_rate", 0),
                cash_balance=summary.get("cash_balance", 0),
                positions_count=summary.get("positions_count", 0),
            )
    except Exception as e:
        logger.error(f"포트폴리오 요약 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/positions", response_model=List[Position])
async def get_positions_api():
    """보유 종목 목록 (실시간 가격 포함)"""
    try:
        with get_session() as session:
            positions = get_portfolio_with_current_prices(session)
            return [
                Position(
                    stock_code=p["stock_code"],
                    stock_name=p["stock_name"],
                    quantity=p["quantity"],
                    avg_price=p["avg_price"],
                    current_price=p.get("current_price", p["avg_price"]),
                    profit=p.get("profit", 0),
                    profit_rate=p.get("profit_rate", 0),
                    weight=p.get("weight", 0),
                )
                for p in positions
            ]
    except Exception as e:
        logger.error(f"보유 종목 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class OrderRequest(BaseModel):
    stock_code: str
    quantity: int
    price: float = 0.0
    side: str  # "BUY" or "SELL"
    order_type: str = "LIMIT"  # "LIMIT" or "MARKET"

@router.post("/order")
async def create_order_api(order: OrderRequest):
    """
    수동 주문 실행 (Mock)
    실제 주문 실행은 AgentCommands 테이블 또는 Broker API 연동 필요
    """
    logger.info(f"Manual Order Received: {order}")
    
    # TODO: Implement actual broker connection or AgentCommand creation
    # e.g., create_agent_command("MANUAL_TRADE", payload=order.dict())
    
    return {
        "status": "accepted", 
        "order_id": f"manual_{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "message": f"{order.side} order for {order.stock_code} accepted (Mock)"
    }

@router.get("/history", response_model=List[PortfolioHistoryItem])
async def get_portfolio_history_api(days: int = 30):
    """
    포트폴리오 자산 추이 (최근 N일)
    DAILY_ASSET_SNAPSHOT 테이블 조회
    """
    try:
        with get_session() as session:
            # SQLAlchemy Query
            query = text("""
                SELECT 
                    SNAPSHOT_DATE, 
                    TOTAL_ASSET_AMOUNT, 
                    CASH_BALANCE, 
                    STOCK_EVAL_AMOUNT,
                    TOTAL_PROFIT_LOSS
                FROM DAILY_ASSET_SNAPSHOT
                ORDER BY SNAPSHOT_DATE DESC
                LIMIT :limit
            """)
            
            result = session.execute(query, {"limit": days}).fetchall()
            
            history = []
            for row in reversed(result): # Sort ASC for chart
                history.append(PortfolioHistoryItem(
                    date=row[0].strftime("%Y-%m-%d"),
                    total_asset=float(row[1] or 0),
                    cash_balance=float(row[2] or 0),
                    stock_eval=float(row[3] or 0),
                    total_profit=float(row[4] or 0)
                ))
            
            return history
            
    except Exception as e:
        logger.error(f"포트폴리오 히스토리 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))
