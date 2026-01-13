
def get_trade_logs(session, date: str) -> List[Dict]:
    """
    특정 날짜의 거래 내역 조회 (SQLAlchemy)
    Args:
        date (str): 'YYYYMMDD' or 'YYYY-MM-DD'
    """
    from .models import TradeLog
    from sqlalchemy import func
    
    try:
        if len(date) == 8:
            dt = datetime.strptime(date, "%Y%m%d")
        else:
            dt = datetime.strptime(date, "%Y-%m-%d")
        
        start_dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        rows = session.query(
            TradeLog.stock_code,
            TradeLog.trade_type,
            TradeLog.quantity,
            TradeLog.price,
            func.json_extract(TradeLog.key_metrics_json, '$.profit_amount').label('profit_amount'),
            TradeLog.trade_timestamp
        ).filter(TradeLog.trade_timestamp >= start_dt, TradeLog.trade_timestamp <= end_dt)\
         .order_by(TradeLog.trade_timestamp.asc()).all()
        
        trades = []
        for row in rows:
            if isinstance(row, dict):
                 trades.append(row)
            else:
                trades.append({
                    "stock_code": row[0],
                    "trade_type": row[1],
                    "quantity": row[2],
                    "price": row[3],
                    "profit_amount": float(row[4]) if row[4] else 0.0,
                    "trade_time": row[5]
                })
        return trades
        
    except Exception as e:
        logger.error(f"❌ DB: get_trade_logs 실패! (에러: {e})")
        return []
