#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Version: v2.0
"""
재무 데이터 수집 모듈
작업 LLM: Claude Sonnet 4.5, Claude Opus 4.5

목적:
- WatchList 종목의 재무 데이터 수집 (ROE, 매출성장률, EPS성장률, PBR, PER)
- FINANCIAL_DATA 테이블에서 데이터 조회 및 계산
- KIS API 또는 네이버 증권에서 PBR/PER 수집 (shared.crawlers.naver 사용)
- MariaDB 단일 지원 (Oracle/분기 제거)
"""

import logging
import time
from datetime import datetime, timezone
from shared.crawlers.naver import scrape_pbr_per_roe

logger = logging.getLogger(__name__)

def _is_mariadb() -> bool:
    """단일화: MariaDB만 사용"""
    return True

def calculate_roe_from_financial_data(connection, stock_code):
    """
    FINANCIAL_DATA 테이블에서 ROE 계산
    
    ROE = (당기순이익 / 자기자본) * 100
    
    Args:
        connection: DB 연결 (SQLAlchemy Session 또는 raw connection)
        stock_code: 종목 코드
    
    Returns:
        float: ROE (%), 없으면 None
    """
    try:
        from sqlalchemy import text
        
        # MariaDB 호환 SQL (LIMIT 사용)
        sql = text("""
            SELECT NET_INCOME, TOTAL_EQUITY, TOTAL_ASSETS, TOTAL_LIABILITIES
            FROM FINANCIAL_DATA
            WHERE STOCK_CODE = :stock_code
            ORDER BY REPORT_DATE DESC
            LIMIT 1
        """)
        
        result = connection.execute(sql, {"stock_code": stock_code})
        row = result.fetchone()
        
        if row and row[0] is not None:  # NET_INCOME이 있어야 함
            net_income = float(row[0])
            total_equity = row[1]
            total_assets = row[2]
            total_liabilities = row[3]
            
            # TOTAL_EQUITY가 NULL이면 ASSETS - LIABILITIES로 계산
            if total_equity is None:
                if total_assets is not None and total_liabilities is not None:
                    total_equity = float(total_assets) - float(total_liabilities)
                else:
                    return None
            else:
                total_equity = float(total_equity)
            
            if total_equity > 0:
                roe = (net_income / total_equity) * 100
                return round(roe, 2)
        
        return None
        
    except Exception as e:
        logger.debug(f"   (Financial) {stock_code} ROE 계산 실패: {e}")
        return None


def get_growth_rates_from_financial_data(connection, stock_code):
    """
    FINANCIAL_DATA 테이블에서 매출 성장률 및 EPS 성장률 조회
    
    Args:
        connection: DB 연결 (SQLAlchemy Session 또는 raw connection)
        stock_code: 종목 코드
    
    Returns:
        tuple: (sales_growth, eps_growth), 없으면 (None, None)
    """
    try:
        from sqlalchemy import text
        
        # MariaDB 호환 SQL (LIMIT 사용)
        sql = text("""
            SELECT SALES_GROWTH, EPS_GROWTH
            FROM FINANCIAL_DATA
            WHERE STOCK_CODE = :stock_code
            ORDER BY REPORT_DATE DESC
            LIMIT 1
        """)
        
        result = connection.execute(sql, {"stock_code": stock_code})
        row = result.fetchone()
        
        if row:
            sales_growth = float(row[0]) if row[0] is not None else None
            eps_growth = float(row[1]) if row[1] is not None else None
            return sales_growth, eps_growth
        
        return None, None
        
    except Exception as e:
        logger.debug(f"   (Financial) {stock_code} 성장률 조회 실패: {e}")
        return None, None


def update_watchlist_financial_data(connection, stock_code):
    """
    WatchList 종목의 재무 데이터 업데이트
    
    Args:
        connection: DB 연결 (SQLAlchemy Session)
        stock_code: 종목 코드
    
    Returns:
        bool: 성공 여부
    """
    try:
        from sqlalchemy import text
        
        # 1. ROE 계산 (FINANCIAL_DATA 기반)
        roe_from_db = calculate_roe_from_financial_data(connection, stock_code)
        
        # 2. 성장률 조회 (FINANCIAL_DATA 기반)
        sales_growth, eps_growth_from_db = get_growth_rates_from_financial_data(connection, stock_code)
        
        # 3. PBR, PER, ROE, EPS 크롤링 (네이버 증권 - Shared Module)
        # shared.crawlers.naver.scrape_pbr_per_roe 사용
        pbr, per, roe_from_naver, eps_list_from_naver, market_cap = scrape_pbr_per_roe(stock_code, debug=False)
        
        # 4. ROE 우선순위: 네이버 크롤링 > DB 계산
        roe = roe_from_naver if roe_from_naver is not None else roe_from_db
        
        # 5. EPS_GROWTH 직접 계산 (네이버 크롤링 데이터 기반)
        eps_growth_from_naver = None
        if eps_list_from_naver and len(eps_list_from_naver) > 0:
            # EPS_GROWTH 직접 계산 (2023년 vs 2024년)
            eps_2023 = None
            eps_2024 = None
            for eps_data in eps_list_from_naver:
                if eps_data['year'] == 2023:
                    eps_2023 = eps_data['eps']
                elif eps_data['year'] == 2024:
                    eps_2024 = eps_data['eps']
            
            # EPS_GROWTH 계산: ((2024 - 2023) / 2023) * 100
            if eps_2023 is not None and eps_2024 is not None and eps_2023 != 0:
                eps_growth_from_naver = ((eps_2024 - eps_2023) / eps_2023) * 100
        
        eps_growth = eps_growth_from_naver  # EPS_GROWTH 사용 (네이버 크롤링 기반)
        
        # 6. WatchList 업데이트 (SQLAlchemy)
        now = datetime.now(timezone.utc)
        
        # 동적 UPDATE 쿼리 생성
        update_parts = []
        params = {'stock_code': stock_code}
        
        if roe is not None:
            update_parts.append("ROE = :roe")
            params['roe'] = roe
        if sales_growth is not None:
            update_parts.append("SALES_GROWTH = :sales_growth")
            params['sales_growth'] = sales_growth
        if eps_growth is not None:
            update_parts.append("EPS_GROWTH = :eps_growth")
            params['eps_growth'] = eps_growth
        if pbr is not None:
            update_parts.append("PBR = :pbr")
            params['pbr'] = pbr
        if per is not None:
            update_parts.append("PER = :per")
            params['per'] = per
        if market_cap is not None:
            update_parts.append("MARKET_CAP = :market_cap")
            params['market_cap'] = market_cap
        
        # 항상 업데이트할 필드
        update_parts.append("FINANCIAL_UPDATED_AT = :updated_at")
        params['updated_at'] = now
        
        if len(update_parts) == 1:  # FINANCIAL_UPDATED_AT만 있는 경우
            return False
        
        sql = text(f"""
            UPDATE WATCHLIST
            SET {', '.join(update_parts)}
            WHERE STOCK_CODE = :stock_code
        """)
        
        connection.execute(sql, params)
        connection.commit()
        
        logger.info(f"   (Financial) {stock_code} ✅ WATCHLIST 업데이트 완료")
        return True
        
    except Exception as e:
        logger.error(f"   (Financial) {stock_code} 재무 데이터 업데이트 실패: {e}")
        try:
            connection.rollback()
        except:
            pass
        return False


def batch_update_watchlist_financial_data(connection, stock_codes, max_workers=1):
    """
    WatchList 종목들의 재무 데이터 일괄 업데이트
    
    Args:
        connection: DB 연결
        stock_codes: 종목 코드 리스트
        max_workers: 동시 처리 스레드 수 (기본값 1 - 네이버 차단 방지)
    
    Returns:
        dict: {'success': 성공 개수, 'failed': 실패 개수}
    """
    success_count = 0
    failed_count = 0
    
    logger.info(f"   (Financial) {len(stock_codes)}개 종목 재무 데이터 업데이트 시작... (순차 처리)")
    
    # 순차 처리 (병렬 처리 제거)
    for idx, stock_code in enumerate(stock_codes):
        try:
            if update_watchlist_financial_data(connection, stock_code):
                success_count += 1
            else:
                failed_count += 1
        except Exception as e:
            logger.error(f"   (Financial) {stock_code} 처리 중 예외: {e}")
            failed_count += 1
        
        # 매 요청마다 0.5초 대기 (네이버 차단 방지)
        if idx < len(stock_codes) - 1:
            time.sleep(0.5)
        
        # 10개마다 진행 상황 로그
        if (idx + 1) % 10 == 0:
            logger.info(f"   (Financial) 진행 상황: {idx + 1}/{len(stock_codes)} 완료")
    
    logger.info(f"   (Financial) 재무 데이터 업데이트 완료 (성공: {success_count}, 실패: {failed_count})")
    
    return {'success': success_count, 'failed': failed_count}
