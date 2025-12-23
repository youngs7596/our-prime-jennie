"""
shared/database/trading.py

거래(Trade), 포트폴리오(Portfolio), 관심종목(Watchlist), 거래로그(TradeLog)
관련 기능을 담당합니다.
(기존 database_trade.py + database_portfolio.py + database_watchlist.py + database_tradelog.py 통합)
"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

import pandas as pd
import numpy as np

from shared.db import connection as sa_connection
from shared.db import models as db_models
from .core import _get_table_name, _is_mariadb, _is_sqlalchemy_ready

logger = logging.getLogger(__name__)


# ============================================================================
# [Watchlist] 관심 종목 관리
# ============================================================================

def get_active_watchlist(connection) -> Dict[str, Dict]:
    """
    WatchList에서 활성 종목 조회
    SQLAlchemy Session과 raw connection 모두 지원
    """
    from sqlalchemy.orm import Session
    from sqlalchemy import text
    
    watchlist = {}
    
    # SQLAlchemy Session인지 확인
    if isinstance(connection, Session):
        result = connection.execute(text("SELECT STOCK_CODE, STOCK_NAME, IS_TRADABLE, LLM_SCORE, LLM_REASON FROM WatchList"))
        rows = result.fetchall()
        for row in rows:
            code = row[0]
            name = row[1]
            is_tradable = row[2]
            llm_score = row[3]
            llm_reason = row[4]
            watchlist[code] = {
                "code": code,
                "name": name,
                "is_tradable": is_tradable,
                "llm_score": llm_score,
                "llm_reason": llm_reason,
            }
    else:
        # Legacy: raw connection with cursor
        cursor = connection.cursor()
        cursor.execute("SELECT STOCK_CODE, STOCK_NAME, IS_TRADABLE, LLM_SCORE, LLM_REASON FROM WatchList")
        rows = cursor.fetchall()
        cursor.close()
        
        for row in rows:
            if isinstance(row, dict):
                code = row.get('STOCK_CODE') or row.get('stock_code')
                name = row.get('STOCK_NAME') or row.get('stock_name')
                is_tradable = row.get('IS_TRADABLE', True)
                llm_score = row.get('LLM_SCORE', None)
                llm_reason = row.get('LLM_REASON', None)
            else:
                code, name, is_tradable, llm_score, llm_reason = row
            watchlist[code] = {
                "code": code,
                "name": name,
                "is_tradable": is_tradable,
                "llm_score": llm_score,
                "llm_reason": llm_reason,
            }
    return watchlist


def save_to_watchlist(session, candidates: List[Dict]):
    """
    WatchList 저장 (SQLAlchemy Session 전용)
    """
    from sqlalchemy import text
    
    if not candidates:
        return
    
    # Step 1: 24시간 지난 오래된 종목 삭제 (TTL)
    logger.info("   (DB) 1. 24시간 지난 오래된 종목 정리 중...")
    session.execute(text("""
        DELETE FROM WatchList 
        WHERE LLM_UPDATED_AT < DATE_SUB(NOW(), INTERVAL 24 HOUR)
    """))
    
    logger.info(f"   (DB) 2. 우량주 후보 {len(candidates)}건 UPSERT...")
    
    now = datetime.now(timezone.utc)
    
    # UPSERT 쿼리
    if _is_mariadb():
        sql_upsert = """
        INSERT INTO WatchList (
            STOCK_CODE, STOCK_NAME, CREATED_AT, IS_TRADABLE,
            LLM_SCORE, LLM_REASON, LLM_UPDATED_AT,
            PER, PBR, ROE, MARKET_CAP, SALES_GROWTH, EPS_GROWTH, FINANCIAL_UPDATED_AT
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            STOCK_NAME = VALUES(STOCK_NAME),
            IS_TRADABLE = VALUES(IS_TRADABLE),
            LLM_SCORE = VALUES(LLM_SCORE),
            LLM_REASON = VALUES(LLM_REASON),
            LLM_UPDATED_AT = VALUES(LLM_UPDATED_AT),
            PER = VALUES(PER),
            PBR = VALUES(PBR),
            ROE = VALUES(ROE),
            MARKET_CAP = VALUES(MARKET_CAP),
            SALES_GROWTH = VALUES(SALES_GROWTH),
            EPS_GROWTH = VALUES(EPS_GROWTH),
            FINANCIAL_UPDATED_AT = VALUES(FINANCIAL_UPDATED_AT)
        """
    else:
        # Oracle: MERGE (간소화를 위해 생략하거나 필요시 추가 구현)
        # 일단 MariaDB만 지원하는 것으로 구현 (기존 파일 참고 필요하면 추가)
        pass 
        
    insert_count = 0
    update_count = 0
    metadata_marker = "[LLM_METADATA]"
    
    for c in candidates:
        llm_score = c.get('llm_score', 0)
        llm_reason = c.get('llm_reason', '') or ''
        llm_metadata = c.get('llm_metadata')

        if llm_metadata:
            try:
                metadata_json = json.dumps(llm_metadata, ensure_ascii=False)
                llm_reason = f"{llm_reason}\n\n{metadata_marker}{metadata_json}"
            except Exception as e:
                logger.warning(f"⚠️ WatchList 메타데이터 직렬화 실패: {e}")

        # REASON 길이 제한
        if len(llm_reason) > 60000:
            llm_reason = llm_reason[:60000] + "..."
        
        if _is_mariadb():
            params = {
                'code': c['code'], 
                'name': c['name'],
                'created_at': now,
                'is_tradable': 1 if c.get('is_tradable', True) else 0,
                'llm_score': llm_score,
                'llm_reason': llm_reason,
                'llm_updated_at': now,
                'per': c.get('per'), 'pbr': c.get('pbr'), 'roe': c.get('roe'),
                'market_cap': c.get('market_cap'), 'sales_growth': c.get('sales_growth'), 'eps_growth': c.get('eps_growth'),
                'financial_updated_at': now
            }
            result = session.execute(text("""
                INSERT INTO WatchList (
                    STOCK_CODE, STOCK_NAME, CREATED_AT, IS_TRADABLE,
                    LLM_SCORE, LLM_REASON, LLM_UPDATED_AT,
                    PER, PBR, ROE, MARKET_CAP, SALES_GROWTH, EPS_GROWTH, FINANCIAL_UPDATED_AT
                ) VALUES (:code, :name, :created_at, :is_tradable, :llm_score, :llm_reason, :llm_updated_at,
                          :per, :pbr, :roe, :market_cap, :sales_growth, :eps_growth, :financial_updated_at)
                ON DUPLICATE KEY UPDATE
                    STOCK_NAME = VALUES(STOCK_NAME), IS_TRADABLE = VALUES(IS_TRADABLE),
                    LLM_SCORE = VALUES(LLM_SCORE), LLM_REASON = VALUES(LLM_REASON), LLM_UPDATED_AT = VALUES(LLM_UPDATED_AT),
                    PER = VALUES(PER), PBR = VALUES(PBR), ROE = VALUES(ROE), MARKET_CAP = VALUES(MARKET_CAP),
                    SALES_GROWTH = VALUES(SALES_GROWTH), EPS_GROWTH = VALUES(EPS_GROWTH), FINANCIAL_UPDATED_AT = VALUES(FINANCIAL_UPDATED_AT)
            """), params)
            if result.rowcount == 1:
                insert_count += 1
            elif result.rowcount == 2:
                update_count += 1
    
    session.commit()
    logger.info(f"   (DB) ✅ WatchList UPSERT 완료! (신규 {insert_count}건, 갱신 {update_count}건)")


def save_to_watchlist_history(session, candidates_to_save, snapshot_date=None):
    """
    WatchList 스냅샷을 히스토리 테이블에 저장합니다. (SQLAlchemy)
    """
    from sqlalchemy import text
    
    is_mariadb = _is_mariadb()
    table_name = "WATCHLIST_HISTORY"
    
    try:
        if snapshot_date is None:
            snapshot_date = datetime.now().strftime('%Y-%m-%d')

        if is_mariadb:
            session.execute(text(f"DELETE FROM {table_name} WHERE SNAPSHOT_DATE = :snapshot_date"), {"snapshot_date": snapshot_date})
        else:
            session.execute(text(f"DELETE FROM {table_name} WHERE SNAPSHOT_DATE = TO_DATE(:snapshot_date, 'YYYY-MM-DD')"), {"snapshot_date": snapshot_date})
        
        if not candidates_to_save:
            session.commit()
            return
            
        for c in candidates_to_save:
            llm_score = c.get('llm_score', 0)
            llm_reason = c.get('llm_reason', '')
            if len(llm_reason) > 3950:
                llm_reason = llm_reason[:3950] + "..."
            
            params = {
                "snapshot_date": snapshot_date,
                "code": c['code'],
                "name": c['name'],
                "is_tradable": 1 if c.get('is_tradable', True) else 0,
                "llm_score": llm_score,
                "llm_reason": llm_reason
            }
            session.execute(text(f"""
                INSERT INTO {table_name} (
                    SNAPSHOT_DATE, STOCK_CODE, STOCK_NAME, IS_TRADABLE, LLM_SCORE, LLM_REASON
                ) VALUES (:snapshot_date, :code, :name, :is_tradable, :llm_score, :llm_reason)
            """), params)
            
        session.commit()
        logger.info(f"   (DB) ✅ WatchList History 저장 완료")
        
    except Exception as e:
        logger.error(f"❌ DB: save_to_watchlist_history 실패! (에러: {e})")
        session.rollback()


def get_watchlist_history(session, snapshot_date):
    """
    특정 날짜의 WatchList 히스토리를 조회합니다. (SQLAlchemy)
    """
    from sqlalchemy import text
    
    watchlist = {}
    
    try:
        result = session.execute(text("""
            SELECT STOCK_CODE, STOCK_NAME, IS_TRADABLE, LLM_SCORE, LLM_REASON
            FROM WATCHLIST_HISTORY
            WHERE SNAPSHOT_DATE = :snapshot_date
        """), {"snapshot_date": snapshot_date})
        rows = result.fetchall()
        
        for row in rows:
            watchlist[row[0]] = {
                "name": row[1], 
                "is_tradable": bool(row[2]),
                "llm_score": row[3] if row[3] is not None else 0,
                "llm_reason": row[4] if row[4] is not None else ""
            }
        return watchlist
    except Exception as e:
        logger.error(f"❌ DB: get_watchlist_history 실패! (에러: {e})")
        return {}


# ============================================================================
# [Portfolio] 포트폴리오 관리
# ============================================================================

def get_active_portfolio(session) -> List[Dict]:
    """
    활성 포트폴리오 조회 (SQLAlchemy)
    """
    from sqlalchemy import text
    
    table_name = _get_table_name("Portfolio")
    result = session.execute(text(f"""
        SELECT ID, STOCK_CODE, STOCK_NAME, QUANTITY, AVERAGE_BUY_PRICE, AVERAGE_BUY_PRICE, 0,
               CREATED_AT, STOP_LOSS_PRICE, CURRENT_HIGH_PRICE
        FROM {table_name}
        WHERE QUANTITY > 0
    """))
    rows = result.fetchall()
    
    portfolio = []
    for row in rows:
        portfolio.append({
            "id": row[0],
            "code": row[1],
            "stock_code": row[1],
            "name": row[2],
            "stock_name": row[2],
            "quantity": row[3],
            "buy_price": row[4],
            "avg_price": row[5],
            "current_price": row[6],
            "buy_date": row[7],
            "stop_loss_price": row[8],
            "high_price": row[9],
        })
    return portfolio


def remove_from_portfolio(session, stock_code, quantity):
    """
    포트폴리오에서 종목 매도 처리 (SQLAlchemy)
    """
    from sqlalchemy import text
    
    try:
        portfolio_table = _get_table_name("Portfolio")
        
        result = session.execute(text(f"""
            SELECT ID, QUANTITY, AVERAGE_BUY_PRICE 
            FROM {portfolio_table} 
            WHERE STOCK_CODE = :stock_code AND STATUS = 'HOLDING'
            FOR UPDATE
        """), {"stock_code": stock_code})
        row = result.fetchone()
        
        if not row:
            logger.warning(f"⚠️ DB: 매도 처리 실패 - 보유 중인 종목이 아님 ({stock_code})")
            return False
        
        portfolio_id, current_qty, avg_price = row[0], row[1], row[2]
        
        if current_qty <= quantity:
            # 전량 매도
            session.execute(text(f"""
                UPDATE {portfolio_table} 
                SET STATUS = 'SOLD', SELL_STATE = 'SOLD', QUANTITY = 0, UPDATED_AT = NOW() 
                WHERE ID = :portfolio_id
            """), {"portfolio_id": portfolio_id})
            logger.info(f"✅ DB: 전량 매도 처리 완료 ({stock_code}, {current_qty}주)")
        else:
            # 부분 매도
            new_qty = current_qty - quantity
            new_total_amount = new_qty * avg_price
            session.execute(text(f"""
                UPDATE {portfolio_table} 
                SET QUANTITY = :new_qty, TOTAL_BUY_AMOUNT = :new_total_amount, UPDATED_AT = NOW() 
                WHERE ID = :portfolio_id
            """), {"new_qty": new_qty, "new_total_amount": new_total_amount, "portfolio_id": portfolio_id})
            logger.info(f"✅ DB: 부분 매도 처리 완료 ({stock_code}, {quantity}주 매도, 잔여 {new_qty}주)")
            
        session.commit()
        return True
    except Exception as e:
        logger.error(f"❌ DB: remove_from_portfolio 실패! (에러: {e})")
        session.rollback()
        return False


# ============================================================================
# [Trade] 거래 실행 및 로깅
# ============================================================================

def _execute_trade_and_log_sqlalchemy(
    session, trade_type, stock_info, quantity, price, llm_decision,
    initial_stop_loss_price=None, strategy_signal: str = None,
    key_metrics_dict: dict = None, market_context_dict: dict = None
):
    """
    거래 실행 및 로깅 구현부 (SQLAlchemy Transaction 내에서 실행됨)
    """
    from sqlalchemy import text
    
    # 1. Trade Log 저장
    try:
        tradelog_table = _get_table_name("TradeLog")
        portfolio_table = _get_table_name("Portfolio")
        
        now = datetime.now(timezone.utc)
        
        # 메타데이터 준비
        key_metrics_json = json.dumps(key_metrics_dict) if key_metrics_dict else None
        market_context_json = json.dumps(market_context_dict) if market_context_dict else None
        
        # Trade Log Insert
        session.execute(text(f"""
            INSERT INTO {tradelog_table} 
            (STOCK_CODE, TRADE_TYPE, QUANTITY, PRICE, REASON, 
             STRATEGY_SIGNAL, KEY_METRICS_JSON, MARKET_CONTEXT_JSON, TRADE_TIMESTAMP)
            VALUES 
            (:code, :type, :qty, :price, :reason, 
             :strategy, :metrics, :context, :ts)
        """), {
            "code": stock_info['code'],
            "type": trade_type,
            "qty": quantity,
            "price": price,
            "reason": llm_decision.get('reason', ''),
            "strategy": strategy_signal,
            "metrics": key_metrics_json,
            "context": market_context_json,
            "ts": now
        })
        
        # 2. Portfolio 업데이트 (매수인 경우)
        if trade_type == 'BUY':
            # 기존 보유 종목 확인
            pf_check = session.execute(text(f"""
                SELECT ID, QUANTITY, AVERAGE_BUY_PRICE, TOTAL_BUY_AMOUNT 
                FROM {portfolio_table} 
                WHERE STOCK_CODE = :code AND STATUS = 'HOLDING'
            """), {"code": stock_info['code']}).fetchone()
            
            total_amount = quantity * price
            
            if pf_check:
                # 추가 매수 (평단가 수정)
                pf_id, curr_qty, curr_avg, curr_total = pf_check
                new_qty = curr_qty + quantity
                new_total_amt = float(curr_total or 0) + total_amount
                new_avg = new_total_amt / new_qty
                
                session.execute(text(f"""
                    UPDATE {portfolio_table}
                    SET QUANTITY = :qty, 
                        AVERAGE_BUY_PRICE = :avg, 
                        TOTAL_BUY_AMOUNT = :total,
                        UPDATED_AT = :now
                    WHERE ID = :id
                """), {
                    "qty": new_qty, "avg": new_avg, "total": new_total_amt, 
                    "now": now, "id": pf_id
                })
            else:
                # 신규 매수
                session.execute(text(f"""
                    INSERT INTO {portfolio_table}
                    (STOCK_CODE, STOCK_NAME, QUANTITY, AVERAGE_BUY_PRICE, TOTAL_BUY_AMOUNT,
                     STATUS, CREATED_AT, UPDATED_AT, STOP_LOSS_PRICE)
                    VALUES 
                    (:code, :name, :qty, :price, :total, 
                     'HOLDING', :now, :now, :stop_loss)
                """), {
                    "code": stock_info['code'],
                    "name": stock_info['name'],
                    "qty": quantity,
                    "price": price,
                    "total": total_amount,
                    "now": now,
                    "stop_loss": initial_stop_loss_price if initial_stop_loss_price is not None else 0.0
                })
                
        elif trade_type == 'SELL':
            # 매도 처리 (Portfolio 업데이트)
            pf_check = session.execute(text(f"""
                SELECT ID, QUANTITY, AVERAGE_BUY_PRICE 
                FROM {portfolio_table} 
                WHERE STOCK_CODE = :code AND (STATUS = 'HOLDING' OR STATUS = 'PARTIAL')
            """), {"code": stock_info['code']}).fetchone()
            
            if pf_check:
                pf_id, curr_qty, avg_price = pf_check
                
                if curr_qty <= quantity:
                    # 전량 매도
                    session.execute(text(f"""
                        UPDATE {portfolio_table} 
                        SET STATUS = 'SOLD', SELL_STATE = 'SOLD', QUANTITY = 0, UPDATED_AT = :now
                        WHERE ID = :id
                    """), {"id": pf_id, "now": now})
                else:
                    # 부분 매도
                    new_qty = curr_qty - quantity
                    new_total_amt = new_qty * avg_price
                    session.execute(text(f"""
                        UPDATE {portfolio_table} 
                        SET QUANTITY = :qty, TOTAL_BUY_AMOUNT = :total, 
                            STATUS = 'PARTIAL', UPDATED_AT = :now 
                        WHERE ID = :id
                    """), {"qty": new_qty, "total": new_total_amt, "now": now, "id": pf_id})
            else:
                logger.warning(f"⚠️ 매도 처리 중 Portfolio 미발견: {stock_info['code']}")
                
        return True
        
    except Exception as e:
        logger.error(f"❌ DB Transaction Failed: {e}", exc_info=True)
        raise e


def execute_trade_and_log(
    connection, trade_type, stock_info, quantity, price, llm_decision,
    initial_stop_loss_price=None,
    strategy_signal: str = None,
    key_metrics_dict: dict = None,
    market_context_dict: dict = None
):
    """
    거래 실행 및 로깅 (SQLAlchemy)
    """
    if _is_sqlalchemy_ready():
        try:
            with sa_connection.session_scope() as session:
                return _execute_trade_and_log_sqlalchemy(
                    session, trade_type, stock_info, quantity, price, llm_decision,
                    initial_stop_loss_price, strategy_signal, key_metrics_dict, market_context_dict
                )
        except Exception as e:
            logger.error(f"❌ [SQLAlchemy] execute_trade_and_log 실패: {e}", exc_info=True)
            return False
    
    logger.error("❌ DB: SQLAlchemy not ready, cannot execute trade.")
    return False


def record_trade(session, stock_code: str, trade_type: str, quantity: int,
                 price: float, reason: str = "", extra: Dict = None):
    """
    단순 거래 로그 저장 (SQLAlchemy)
    """
    from sqlalchemy import text
    
    table_name = _get_table_name("TradeLog")
    extra_json = json.dumps(extra, default=str) if extra else None
    now_ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    
    session.execute(text(f"""
        INSERT INTO {table_name}
        (STOCK_CODE, TRADE_TYPE, QUANTITY, PRICE, REASON, EXTRA, TRADE_TIME_UTC)
        VALUES (:stock_code, :trade_type, :quantity, :price, :reason, :extra, :now_ts)
    """), {
        "stock_code": stock_code, "trade_type": trade_type, "quantity": quantity,
        "price": price, "reason": reason, "extra": extra_json, "now_ts": now_ts
    })
    session.commit()


def get_today_trades(session) -> List[Dict]:
    """오늘의 거래 내역 조회"""
    from .models import TradeLog
    from sqlalchemy import func
    
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    
    rows = session.query(
        TradeLog.stock_code,
        TradeLog.trade_type,
        TradeLog.quantity,
        TradeLog.price,
        func.json_extract(TradeLog.key_metrics_json, '$.profit_amount').label('profit_amount'),
        TradeLog.trade_timestamp
    ).filter(TradeLog.trade_timestamp >= today_start).order_by(TradeLog.trade_timestamp.desc()).all()
    
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


def get_trade_log(session, limit=50):
    """
    최근 거래 로그 조회 (SQLAlchemy)
    """
    from sqlalchemy import text
    
    try:
        tradelog_table = _get_table_name("TradeLog")
        result = session.execute(text(f"""
            SELECT LOG_ID, PORTFOLIO_ID, STOCK_CODE, TRADE_TYPE, QUANTITY, PRICE, REASON, TRADE_TIMESTAMP
            FROM {tradelog_table}
            ORDER BY TRADE_TIMESTAMP DESC
            LIMIT :limit
        """), {"limit": limit})
        rows = result.fetchall()
        
        if rows:
            return pd.DataFrame(rows, columns=['LOG_ID', 'PORTFOLIO_ID', 'STOCK_CODE', 'TRADE_TYPE', 'QUANTITY', 'PRICE', 'REASON', 'TRADE_TIMESTAMP'])
        return None
    except Exception as e:
        logger.error(f"❌ DB: get_trade_log 실패! (에러: {e})")
        return None


def was_traded_recently(session, stock_code, hours=24):
    """
    특정 종목이 최근 N시간 이내에 거래되었는지 확인 (SQLAlchemy)
    """
    from sqlalchemy import text
    
    try:
        tradelog_table = _get_table_name("TradeLog")
        result = session.execute(text(f"""
            SELECT 1 FROM {tradelog_table}
            WHERE STOCK_CODE = :stock_code 
              AND TRADE_TIMESTAMP >= DATE_SUB(NOW(), INTERVAL :hours HOUR)
            LIMIT 1
        """), {"stock_code": stock_code, "hours": hours})
        row = result.fetchone()
        return row is not None
    except Exception as e:
        logger.error(f"❌ DB: was_traded_recently 실패! (에러: {e})")
        return False


def get_recently_traded_stocks_batch(session, stock_codes: list, hours: int = 24):
    """
    여러 종목의 최근 거래 여부를 한 번에 조회 (SQLAlchemy)
    """
    from sqlalchemy import text
    
    if not stock_codes:
        return set()
    
    try:
        tradelog_table = _get_table_name("TradeLog")
        placeholder = ','.join([f':code{i}' for i in range(len(stock_codes))])
        params = {f'code{i}': code for i, code in enumerate(stock_codes)}
        params['hours'] = hours
        
        result = session.execute(text(f"""
            SELECT DISTINCT STOCK_CODE 
            FROM {tradelog_table}
            WHERE STOCK_CODE IN ({placeholder}) 
              AND TRADE_TIMESTAMP >= DATE_SUB(NOW(), INTERVAL :hours HOUR)
        """), params)
        rows = result.fetchall()
        
        return {row[0] for row in rows}
    except Exception as e:
        logger.error(f"❌ DB: get_recently_traded_stocks_batch 실패! (에러: {e})")
        return set()


def check_duplicate_order(session, stock_code, trade_type, time_window_minutes=5):
    """
    최근 N분 이내에 동일한 종목/유형의 주문이 있었는지 확인 (SQLAlchemy)
    """
    from sqlalchemy import text
    
    try:
        tradelog_table = _get_table_name("TradeLog")
        result = session.execute(text(f"""
            SELECT 1 FROM {tradelog_table}
            WHERE STOCK_CODE = :stock_code 
              AND TRADE_TYPE = :trade_type
              AND TRADE_TIMESTAMP >= DATE_SUB(NOW(), INTERVAL :minutes MINUTE)
            LIMIT 1
        """), {"stock_code": stock_code, "trade_type": trade_type, "minutes": time_window_minutes})
        row = result.fetchone()
        
        if row:
            logger.warning(f"⚠️ DB: 중복 주문 감지! ({stock_code}, {trade_type})")
            return True
        return False
    except Exception as e:
        logger.error(f"❌ DB: check_duplicate_order 실패! (에러: {e})")
        return False

def get_trade_logs(session, date: str) -> List[Dict]:
    """
    특정 날짜의 거래 내역 조회 (SQLAlchemy)
    Args:
        date (str): 'YYYYMMDD' or 'YYYY-MM-DD'
    """
    # from .models import TradeLog  <-- Incorrect
    TradeLog = db_models.TradeLog
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
