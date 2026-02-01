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


def _is_sqlite(session):
    """Check if the current session is using SQLite"""
    try:
        bind = session.get_bind()
        return bind.dialect.name == 'sqlite'
    except Exception:
        return False



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
    def _parse_llm_reason(raw_reason: str):
        marker = "[LLM_METADATA]"
        metadata = {}
        clean = raw_reason or ""
        if raw_reason and marker in raw_reason:
            base, metadata_raw = raw_reason.split(marker, 1)
            clean = base.strip()
            try:
                metadata = json.loads(metadata_raw.strip())
            except Exception:
                metadata = {}
        return clean, metadata

    if isinstance(connection, Session):
        # TRADE_TIER 컬럼은 Project Recon v1.1 이후 존재합니다. (없으면 NULL)
        result = connection.execute(
            text(
                f"SELECT STOCK_CODE, STOCK_NAME, IS_TRADABLE, LLM_SCORE, LLM_REASON, "
                f"TRADE_TIER FROM {db_models.resolve_table_name('WATCHLIST')}"
            )
        )
        rows = result.fetchall()
        for row in rows:
            code = row[0]
            name = row[1]
            is_tradable = row[2]
            llm_score = row[3]
            llm_reason_raw = row[4]
            trade_tier_db = row[5] if len(row) > 5 else None
            llm_reason, llm_metadata = _parse_llm_reason(llm_reason_raw)
            trade_tier = (
                trade_tier_db
                or llm_metadata.get("trade_tier")
                or ("TIER1" if bool(is_tradable) else "BLOCKED")
            )
            watchlist[code] = {
                "code": code,
                "name": name,
                "is_tradable": is_tradable,
                "llm_score": llm_score,
                "llm_reason": llm_reason,
                "llm_metadata": llm_metadata,
                "trade_tier": trade_tier,
            }
    else:
        # Legacy: raw connection with cursor
        cursor = connection.cursor()
        cursor.execute(
            f"SELECT STOCK_CODE, STOCK_NAME, IS_TRADABLE, LLM_SCORE, LLM_REASON, TRADE_TIER "
            f"FROM {db_models.resolve_table_name('WATCHLIST')}"
        )
        rows = cursor.fetchall()
        cursor.close()
        
        for row in rows:
            if isinstance(row, dict):
                code = row.get('STOCK_CODE') or row.get('stock_code')
                name = row.get('STOCK_NAME') or row.get('stock_name')
                is_tradable = row.get('IS_TRADABLE', True)
                llm_score = row.get('LLM_SCORE', None)
                llm_reason_raw = row.get('LLM_REASON', None)
                trade_tier_db = row.get('TRADE_TIER', None)
            else:
                # 컬럼 존재 여부에 따라 튜플 길이가 달라질 수 있어 안전하게 처리
                code = row[0]
                name = row[1]
                is_tradable = row[2]
                llm_score = row[3]
                llm_reason_raw = row[4] if len(row) > 4 else None
                trade_tier_db = row[5] if len(row) > 5 else None

            llm_reason, llm_metadata = _parse_llm_reason(llm_reason_raw)
            trade_tier = (
                trade_tier_db
                or llm_metadata.get("trade_tier")
                or ("TIER1" if bool(is_tradable) else "BLOCKED")
            )
            watchlist[code] = {
                "code": code,
                "name": name,
                "is_tradable": is_tradable,
                "llm_score": llm_score,
                "llm_reason": llm_reason,
                "llm_metadata": llm_metadata,
                "trade_tier": trade_tier,
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
        DELETE FROM WATCHLIST 
        WHERE LLM_UPDATED_AT < DATE_SUB(NOW(), INTERVAL 24 HOUR)
    """))
    
    logger.info(f"   (DB) 2. 우량주 후보 {len(candidates)}건 UPSERT...")
    
    now = datetime.now(timezone.utc)
    
    # UPSERT 쿼리 (MariaDB 단일화)
    sql_upsert = """
        INSERT INTO WATCHLIST (
            STOCK_CODE, STOCK_NAME, CREATED_AT, IS_TRADABLE,
            TRADE_TIER, LLM_SCORE, LLM_REASON, LLM_UPDATED_AT,
            PER, PBR, ROE, MARKET_CAP, SALES_GROWTH, EPS_GROWTH, FINANCIAL_UPDATED_AT
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            STOCK_NAME = VALUES(STOCK_NAME),
            IS_TRADABLE = VALUES(IS_TRADABLE),
            TRADE_TIER = VALUES(TRADE_TIER),
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
        
    insert_count = 0
    update_count = 0
    metadata_marker = "[LLM_METADATA]"
    
    for c in candidates:
        llm_score = c.get('llm_score', 0)
        llm_reason = c.get('llm_reason', '') or ''
        llm_metadata = c.get('llm_metadata')
        trade_tier = c.get("trade_tier") or (llm_metadata or {}).get("trade_tier")
        if not trade_tier:
            trade_tier = "TIER1" if c.get("is_tradable", True) else "BLOCKED"

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
                'trade_tier': trade_tier,
                'llm_score': llm_score,
                'llm_reason': llm_reason,
                'llm_updated_at': now,
                'per': c.get('per'), 'pbr': c.get('pbr'), 'roe': c.get('roe'),
                'market_cap': c.get('market_cap'), 'sales_growth': c.get('sales_growth'), 'eps_growth': c.get('eps_growth'),
                'financial_updated_at': now
            }
            if _is_sqlite(session):
                # SQLite: INSERT OR REPLACE (REPLACE INTO)
                # Note: This technically replaces the row, potentially resetting unlisted columns if any.
                # But for WATCHLIST, we usually update all key columns.
                # However, ON DUPLICATE KEY UPDATE syntax is specific to MySQL/MariaDB.
                # For basic testing, we can check existence or use REPLACE.
                # Let's use simple UPSERT logic (Check -> Insert/Update) for safety in tests.
                
                check_sql = text(f"SELECT 1 FROM WATCHLIST WHERE STOCK_CODE = :code")
                exists = session.execute(check_sql, {'code': params['code']}).fetchone()
                
                if exists:
                    # UPDATE
                    update_sql = text("""
                        UPDATE WATCHLIST SET
                            STOCK_NAME = :name, IS_TRADABLE = :is_tradable, TRADE_TIER = :trade_tier,
                            LLM_SCORE = :llm_score, LLM_REASON = :llm_reason, LLM_UPDATED_AT = :llm_updated_at,
                            PER = :per, PBR = :pbr, ROE = :roe, MARKET_CAP = :market_cap,
                            SALES_GROWTH = :sales_growth, EPS_GROWTH = :eps_growth, FINANCIAL_UPDATED_AT = :financial_updated_at
                        WHERE STOCK_CODE = :code
                    """)
                    session.execute(update_sql, params)
                    update_count += 1
                else:
                    # INSERT
                    insert_sql = text("""
                        INSERT INTO WATCHLIST (
                            STOCK_CODE, STOCK_NAME, CREATED_AT, IS_TRADABLE,
                            TRADE_TIER, LLM_SCORE, LLM_REASON, LLM_UPDATED_AT,
                            PER, PBR, ROE, MARKET_CAP, SALES_GROWTH, EPS_GROWTH, FINANCIAL_UPDATED_AT
                        ) VALUES (:code, :name, :created_at, :is_tradable, :trade_tier, :llm_score, 
                                  :llm_reason, :llm_updated_at, :per, :pbr, :roe, :market_cap, 
                                  :sales_growth, :eps_growth, :financial_updated_at)
                    """)
                    session.execute(insert_sql, params)
                    insert_count += 1
                
                # Mock result for logic below
                class MockResult:
                    rowcount = 1
                result = MockResult()
                
            else:
                # MariaDB UPSERT syntax
                result = session.execute(text("""
                    INSERT INTO WATCHLIST (
                        STOCK_CODE, STOCK_NAME, CREATED_AT, IS_TRADABLE,
                        TRADE_TIER, LLM_SCORE, LLM_REASON, LLM_UPDATED_AT,
                        PER, PBR, ROE, MARKET_CAP, SALES_GROWTH, EPS_GROWTH, FINANCIAL_UPDATED_AT
                    ) VALUES (:code, :name, :created_at, :is_tradable, :trade_tier, :llm_score, :llm_reason, :llm_updated_at,
                              :per, :pbr, :roe, :market_cap, :sales_growth, :eps_growth, :financial_updated_at)
                    ON DUPLICATE KEY UPDATE
                        STOCK_NAME = VALUES(STOCK_NAME), IS_TRADABLE = VALUES(IS_TRADABLE),
                        TRADE_TIER = VALUES(TRADE_TIER),
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
    
    table_name = "WATCHLIST_HISTORY"
    
    try:
        if snapshot_date is None:
            snapshot_date = datetime.now().strftime('%Y-%m-%d')

        session.execute(
            text(f"DELETE FROM {table_name} WHERE SNAPSHOT_DATE = :snapshot_date"),
            {"snapshot_date": snapshot_date},
        )
        
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
    활성 포트폴리오 조회 (ACTIVE_PORTFOLIO 테이블 사용)
    """
    from sqlalchemy import text
    from sqlalchemy.orm import Session
    from shared.db.models import resolve_table_name, ActivePortfolio
    
    try:
        if isinstance(session, Session):
            from sqlalchemy import select
            rows = session.scalars(select(ActivePortfolio)).all()
            portfolio = []
            for row in rows:
                portfolio.append({
                    "id": str(row.stock_code), # ID는 이제 stock_code와 동일 취급 (PK)
                    "code": row.stock_code,
                    "stock_code": row.stock_code,
                    "name": row.stock_name,
                    "stock_name": row.stock_name,
                    "quantity": row.quantity,
                    "buy_price": row.average_buy_price,
                    "avg_price": row.average_buy_price,
                    "current_price": row.current_high_price, 
                    "buy_date": row.created_at,
                    "stop_loss_price": row.stop_loss_price,
                    "high_price": row.current_high_price,
                })
            return portfolio
        else:
            # Legacy raw connection support
            table_name = resolve_table_name("ACTIVE_PORTFOLIO")
            sql = f"""
                SELECT STOCK_CODE, STOCK_NAME, QUANTITY, AVERAGE_BUY_PRICE, 
                       CREATED_AT, STOP_LOSS_PRICE, CURRENT_HIGH_PRICE
                FROM {table_name}
            """
            cursor = session.cursor()
            cursor.execute(sql)
            rows = cursor.fetchall()
            cursor.close()
            
            portfolio = []
            for row in rows:
                portfolio.append({
                    "id": row[0],
                    "code": row[0],
                    "stock_code": row[0],
                    "name": row[1],
                    "stock_name": row[1],
                    "quantity": row[2],
                    "buy_price": row[3],
                    "avg_price": row[3],
                    "current_price": row[6],
                    "buy_date": row[4],
                    "stop_loss_price": row[5],
                    "high_price": row[6],
                })
            return portfolio
    except Exception as e:
        logger.error(f"❌ DB: get_active_portfolio 실패! (에러: {e})")
        return []


def remove_from_portfolio(session, stock_code, quantity):
    """
    포트폴리오에서 종목 매도 처리 (ACTIVE_PORTFOLIO 사용)
    """
    from sqlalchemy import text
    from shared.db.models import resolve_table_name
    
    try:
        table_name = resolve_table_name("ACTIVE_PORTFOLIO")
        
        # 보유 수량 확인
        row = session.execute(text(f"""
            SELECT QUANTITY, AVERAGE_BUY_PRICE 
            FROM {table_name} 
            WHERE STOCK_CODE = :stock_code
            FOR UPDATE
        """), {"stock_code": stock_code}).fetchone()
        
        if not row:
            logger.warning(f"⚠️ DB: 매도 처리 실패 - 보유 중인 종목이 아님 ({stock_code})")
            return False
        
        current_qty, avg_price = row[0], row[1]
        
        if current_qty <= quantity:
            # 전량 매도 -> 레코드 삭제
            session.execute(text(f"""
                DELETE FROM {table_name} WHERE STOCK_CODE = :stock_code
            """), {"stock_code": stock_code})
            logger.info(f"✅ DB: 전량 매도 및 ACTIVE_PORTFOLIO 삭제 완료 ({stock_code}, {current_qty}주)")
        else:
            # 부분 매도 -> 수량 업데이트
            new_qty = current_qty - quantity
            new_total_amount = new_qty * avg_price
            session.execute(text(f"""
                UPDATE {table_name} 
                SET QUANTITY = :new_qty, TOTAL_BUY_AMOUNT = :new_total_amount, UPDATED_AT = NOW() 
                WHERE STOCK_CODE = :stock_code
            """), {"new_qty": new_qty, "new_total_amount": new_total_amount, "stock_code": stock_code})
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
    거래 실행 및 로깅 구현부 (ACTIVE_PORTFOLIO + TRADELOG)
    """
    from sqlalchemy import text
    from shared.db.models import resolve_table_name
    
    # 1. Trade Log 저장 (항상 실행)
    try:
        tradelog_table = resolve_table_name("TRADELOG")
        active_table = resolve_table_name("ACTIVE_PORTFOLIO")
        
        now = datetime.now(timezone.utc)
        
        # 메타데이터 준비
        key_metrics_json = json.dumps(key_metrics_dict) if key_metrics_dict else None
        market_context_json = json.dumps(market_context_dict) if market_context_dict else None
        
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
        
        # 2. Active Portfolio 업데이트
        if trade_type == 'BUY':
            total_amount = quantity * price
            
            if _is_sqlite(session):
                # SQLite Implementation (SELECT -> UPDATE/INSERT)
                existing = session.execute(
                    text(f"SELECT QUANTITY, TOTAL_BUY_AMOUNT FROM {active_table} WHERE STOCK_CODE = :code"), 
                    {"code": stock_info['code']}
                ).fetchone()
                
                if existing:
                    # UPDATE
                    current_qty = existing[0]
                    current_total = existing[1]
                    new_qty = current_qty + quantity
                    new_total = current_total + total_amount
                    avg_price = new_total / new_qty if new_qty > 0 else 0
                    
                    session.execute(text(f"""
                        UPDATE {active_table}
                        SET QUANTITY = :qty, 
                            TOTAL_BUY_AMOUNT = :total, 
                            AVERAGE_BUY_PRICE = :avg, 
                            UPDATED_AT = :now
                        WHERE STOCK_CODE = :code
                    """), {
                        "qty": new_qty, 
                        "total": new_total, 
                        "avg": avg_price, 
                        "now": now, 
                        "code": stock_info['code']
                    })
                else:
                    # INSERT
                    session.execute(text(f"""
                        INSERT INTO {active_table}
                        (STOCK_CODE, STOCK_NAME, QUANTITY, AVERAGE_BUY_PRICE, TOTAL_BUY_AMOUNT,
                         STOP_LOSS_PRICE, CURRENT_HIGH_PRICE, CREATED_AT, UPDATED_AT)
                        VALUES 
                        (:code, :name, :qty, :price, :total, 
                         :stop_loss, :high_price, :now, :now)
                    """), {
                        "code": stock_info['code'],
                        "name": stock_info['name'],
                        "qty": quantity,
                        "price": price,
                        "total": total_amount,
                        "stop_loss": initial_stop_loss_price if initial_stop_loss_price is not None else 0.0,
                        "high_price": price,
                        "now": now
                    })
            else:
                # MariaDB UPSERT syntax (Atomic)
                session.execute(text(f"""
                    INSERT INTO {active_table}
                    (STOCK_CODE, STOCK_NAME, QUANTITY, AVERAGE_BUY_PRICE, TOTAL_BUY_AMOUNT,
                     STOP_LOSS_PRICE, CURRENT_HIGH_PRICE, CREATED_AT, UPDATED_AT)
                    VALUES 
                    (:code, :name, :qty, :price, :total, 
                     :stop_loss, :high_price, :now, :now)
                    ON DUPLICATE KEY UPDATE
                        QUANTITY = QUANTITY + :qty,
                        TOTAL_BUY_AMOUNT = TOTAL_BUY_AMOUNT + :total,
                        AVERAGE_BUY_PRICE = (TOTAL_BUY_AMOUNT + :total) / (QUANTITY + :qty),
                        UPDATED_AT = :now
                """), {
                    "code": stock_info['code'],
                    "name": stock_info['name'],
                    "qty": quantity,
                    "price": price,
                    "total": total_amount,
                    "stop_loss": initial_stop_loss_price if initial_stop_loss_price is not None else 0.0,
                    "high_price": price,
                    "now": now
                })
            
                
        elif trade_type == 'SELL':
            # 매도 처리 (감소 또는 삭제)
            row = session.execute(text(f"""
                SELECT QUANTITY, AVERAGE_BUY_PRICE 
                FROM {active_table} 
                WHERE STOCK_CODE = :code
            """), {"code": stock_info['code']}).fetchone()
            
            if row:
                curr_qty, avg_price = row[0], row[1]
                
                if curr_qty <= quantity:
                    # 전량 매도 -> 삭제
                    session.execute(text(f"DELETE FROM {active_table} WHERE STOCK_CODE = :code"), 
                                    {"code": stock_info['code']})
                else:
                    # 부분 매도 -> 업데이트
                    new_qty = curr_qty - quantity
                    new_total_amt = new_qty * avg_price
                    session.execute(text(f"""
                        UPDATE {active_table} 
                        SET QUANTITY = :qty, TOTAL_BUY_AMOUNT = :total, UPDATED_AT = :now 
                        WHERE STOCK_CODE = :code
                    """), {"qty": new_qty, "total": new_total_amt, "now": now, "code": stock_info['code']})
            else:
                logger.warning(f"⚠️ 매도 처리 중 ActivePortfolio 미발견: {stock_info['code']}")
                
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
    
    Args:
        connection: 호출자의 SQLAlchemy 세션. 제공되면 해당 세션을 재사용하여
                   동일 트랜잭션 내에서 PORTFOLIO UPSERT를 실행합니다.
                   None이면 새 세션을 생성합니다.
    """
    if _is_sqlalchemy_ready():
        try:
            # [FIX] 호출자의 세션이 제공되면 재사용 (동일 트랜잭션 유지 = 중복 INSERT 방지)
            if connection is not None:
                return _execute_trade_and_log_sqlalchemy(
                    connection, trade_type, stock_info, quantity, price, llm_decision,
                    initial_stop_loss_price, strategy_signal, key_metrics_dict, market_context_dict
                )
            else:
                # Fallback: 세션이 제공되지 않으면 새로 생성
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
    
    table_name = db_models.resolve_table_name("TRADELOG")
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
    from sqlalchemy import func, select

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    stmt = select(
        TradeLog.stock_code,
        TradeLog.trade_type,
        TradeLog.quantity,
        TradeLog.price,
        func.json_extract(TradeLog.key_metrics_json, '$.profit_amount').label('profit_amount'),
        TradeLog.trade_timestamp
    ).where(TradeLog.trade_timestamp >= today_start).order_by(TradeLog.trade_timestamp.desc())
    rows = session.execute(stmt).all()
    
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
        tradelog_table = db_models.resolve_table_name("TRADELOG")
        result = session.execute(text(f"""
            SELECT LOG_ID, STOCK_CODE, TRADE_TYPE, QUANTITY, PRICE, REASON, TRADE_TIMESTAMP
            FROM {tradelog_table}
            ORDER BY TRADE_TIMESTAMP DESC
            LIMIT :limit
        """), {"limit": limit})
        rows = result.fetchall()
        
        if rows:
            return pd.DataFrame(rows, columns=['LOG_ID', 'STOCK_CODE', 'TRADE_TYPE', 'QUANTITY', 'PRICE', 'REASON', 'TRADE_TIMESTAMP'])
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
        tradelog_table = db_models.resolve_table_name("TRADELOG")
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
        tradelog_table = db_models.resolve_table_name("TRADELOG")
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
        tradelog_table = db_models.resolve_table_name("TRADELOG")
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
    
    Returns:
        List[Dict]: 거래 내역 리스트
            - stock_code, stock_name, action (BUY/SELL), quantity, price, amount
            - profit_amount, reason, trade_time, strategy_signal
    """
    TradeLog = db_models.TradeLog
    ActivePortfolio = db_models.ActivePortfolio  # 보유 종목에서 종목명 조회
    from sqlalchemy import func
    
    try:
        if len(date) == 8:
            dt = datetime.strptime(date, "%Y%m%d")
        else:
            dt = datetime.strptime(date, "%Y-%m-%d")
        
        start_dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        # [Fix] Join 제거 - TradeLog만 조회 (Cartesian Product 방지)
        from sqlalchemy import select
        stmt = select(
            TradeLog.stock_code,
            TradeLog.trade_type,
            TradeLog.quantity,
            TradeLog.price,
            TradeLog.reason,
            TradeLog.strategy_signal,
            func.json_extract(TradeLog.key_metrics_json, '$.profit_amount').label('profit_amount'),
            TradeLog.trade_timestamp
        ).where(
            TradeLog.trade_timestamp >= start_dt,
            TradeLog.trade_timestamp <= end_dt
        ).order_by(TradeLog.trade_timestamp.asc())
        rows = session.execute(stmt).all()
        
        if not rows:
            return []
            
        # 종목명 별도 조회 (ActivePortfolio에서 먼저 시도, 없으면 WatchList)
        stock_codes = list(set([r[0] for r in rows]))
        name_map = {}
        if stock_codes:
            # 1. ActivePortfolio에서 종목명 조회
            ap_stmt = select(ActivePortfolio.stock_code, ActivePortfolio.stock_name).where(
                ActivePortfolio.stock_code.in_(stock_codes)
            )
            ap_rows = session.execute(ap_stmt).all()
            name_map = {p[0]: p[1] for p in ap_rows}

            # 2. ActivePortfolio에 없는 종목은 WatchList에서 조회 (매도된 종목 등)
            missing_codes = [c for c in stock_codes if c not in name_map]
            if missing_codes:
                WatchList = db_models.WatchList
                wl_stmt = select(WatchList.stock_code, WatchList.stock_name).where(
                    WatchList.stock_code.in_(missing_codes)
                )
                wl_rows = session.execute(wl_stmt).all()
                for w in wl_rows:
                    name_map[w[0]] = w[1]
        
        trades = []
        for row in rows:
            code = row[0]
            quantity = int(row[2] or 0)
            price = float(row[3] or 0)
            
            trades.append({
                "stock_code": code,
                "stock_name": name_map.get(code, code),  # 종목명 없으면 코드
                "action": row[1],
                "quantity": quantity,
                "price": price,
                "amount": quantity * price,
                "reason": row[4] or "",
                "strategy_signal": row[5] or "",
                "profit_amount": float(row[6]) if row[6] else 0.0,
                "trade_time": row[7]
            })
        
        logger.info(f"📋 거래 내역 조회: {date} - {len(trades)}건")
        return trades
        
    except Exception as e:
        logger.error(f"❌ DB: get_trade_logs 실패! (에러: {e})")
        return []
