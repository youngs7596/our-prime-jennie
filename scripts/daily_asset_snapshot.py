#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
daily_asset_snapshot.py
=======================
일별 자산 현황 스냅샷 스크립트

매일 장 마감 후 실행하여:
1. KIS API로 총 자산, 예수금, 주식 평가액 조회
2. DAILY_ASSET_SNAPSHOT 테이블에 저장

Airflow DAG에 의해 매일 15:45분경 실행됩니다.
"""

import sys
import os
import logging
from datetime import datetime, date
from pathlib import Path

# 프로젝트 루트 경로 설정
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# [FIX] shared.db.database가 아닌 shared.db.connection 사용
from shared.db.connection import get_session, get_engine, init_engine
from shared.db.models import Base, DailyAssetSnapshot, resolve_table_name
from shared.kis.client import KISClient
from shared.kis.trading import Trading
from sqlalchemy.dialects.mysql import insert

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(PROJECT_ROOT / 'logs' / 'daily_asset_snapshot.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

def run_snapshot():
    logger.info("=" * 60)
    # [New] 날짜 인자 처리
    import argparse
    parser = argparse.ArgumentParser(description='일별 자산 스냅샷')
    parser.add_argument('--date', type=str, help='YYYYMMDD or YYYY-MM-DD (기본값: 오늘)')
    args = parser.parse_args()
    
    target_date = date.today()
    if args.date:
        try:
            d_str = args.date.replace('-', '')
            target_date = datetime.strptime(d_str, '%Y%m%d').date()
            logger.info(f"📅 지정 날짜 모드: {target_date}")
        except ValueError:
            logger.error("❌ 날짜 형식이 올바르지 않습니다.")
            return False

    logger.info(f"📸 일별 자산 스냅샷 시작 (Target: {target_date})")
    logger.info("=" * 60)
    
    # [Local Dev Fix] 로컬 실행 시 secrets.json의 DB 포트(3307)를 환경변수에 주입
    # 단, Airflow/Docker 환경(MARIADB_HOST가 이미 설정된 경우)에서는 건너뜀
    if not os.environ.get("MARIADB_HOST"):
        try:
            from shared.auth import get_secret
            
            db_port = get_secret("mariadb-port")
            if db_port:
                os.environ["MARIADB_PORT"] = str(db_port)
                logger.info(f"🔧 로컬 환경: MARIADB_PORT={db_port} 설정 (from secrets)")
        except Exception as e:
            logger.warning(f"⚠️ 시크릿 로드 중 오류: {e}")
    else:
        logger.info(f"🐳 Docker/Airflow 환경 감지: MARIADB_HOST={os.environ.get('MARIADB_HOST')}")

    # DB 엔진 초기화
    engine = init_engine()

    # [Table Creation] 테이블이 없으면 생성
    try:
        DailyAssetSnapshot.__table__.create(bind=engine, checkfirst=True)
        # REALIZED_PROFIT_LOSS 컬럼은 모델에 정의되어 있으면 create() 시 자동 생성됨 (새 테이블인 경우)
        # 기존 테이블인 경우 스키마 마이그레이션 필요 (이미 수행함)
        logger.info(f"✅ 테이블 확인 완료 ({DailyAssetSnapshot.__tablename__})")
    except Exception as e:
        logger.warning(f"⚠️ 테이블 생성/확인 중 경고: {e}")

    # 1. KIS API 연결
    try:
        from shared.auth import get_secret
        
        trading_mode = os.getenv("TRADING_MODE", "REAL").upper()
        
        if trading_mode == "MOCK":
            app_key = get_secret("kis-v-app-key") or get_secret("mock-app-key")
            app_secret = get_secret("kis-v-app-secret") or get_secret("mock-app-secret")
            account_prefix = get_secret("kis-v-account-prefix") or get_secret("mock-account-prefix")
            account_suffix = get_secret("kis-v-account-suffix") or "00"
            base_url = "https://openapivts.koreainvestment.com:29443"
        else: # REAL
            app_key = get_secret("kis-r-app-key")
            app_secret = get_secret("kis-r-app-secret")
            
            full_account = get_secret("kis-r-account-no") or get_secret("kis-r-account-number")
            if full_account:
                full_account = str(full_account).strip()
                if "-" in full_account:
                    account_prefix, account_suffix = full_account.split("-")
                elif len(full_account) == 10:
                    account_prefix = full_account[:8]
                    account_suffix = full_account[8:]
                else:
                    account_prefix = full_account
                    account_suffix = "01"
            else:
                account_prefix = get_secret("kis-r-account-prefix")
                account_suffix = get_secret("kis-r-account-suffix")
                
            base_url = "https://openapi.koreainvestment.com:9443"

        if not all([app_key, app_secret, account_prefix, account_suffix]):
            logger.error(f"❌ KIS API 필수 정보 누락 (Mode: {trading_mode})")
            return False

        client = KISClient(
            app_key=app_key,
            app_secret=app_secret,
            base_url=base_url,
            account_prefix=account_prefix,
            account_suffix=account_suffix,
            trading_mode=trading_mode
        )
        
        if not client.authenticate():
             logger.error("❌ KIS API 인증 실패")
             return False
             
        trading = Trading(client)
        asset_summary = trading.get_asset_summary()
        
        if not asset_summary:
            logger.error("❌ 자산 현황 조회 실패 (Trading API)")
            return False
            
    except Exception as e:
        logger.error(f"❌ KIS API 연동 중 오류 발생: {e}")
        return False

    # 2. 데이터 추출
    total_asset = asset_summary['total_asset']
    cash_balance = asset_summary['cash_balance']
    stock_eval = asset_summary['stock_eval']
    total_pnl = asset_summary['total_profit_loss']
    
    # [New] 지정 날짜 실현 손익 조회
    realized_pnl = trading.get_today_realized_pnl(target_date=target_date)
    
    today = target_date # DB 저장용 날짜
    
    # [Logic Fix] KIS API가 총자산(tot_evlu_mamt)을 0으로 반환하는 경우 보정
    # 주의: 과거 날짜 조회 시 asset_summary(현재 잔고)를 사용하므로
    # 총자산/평가금액은 '오늘' 기준 값이 들어갑니다.
    # 과거의 자산 내역은 API로 조회 불가능하므로, '실현 손익'만 과거 값이고 나머지는 현재 값임.
    # 이 점을 로그로 남김.
    if target_date != date.today():
        logger.warning(f"⚠️ 과거 날짜({target_date}) 조회 모드입니다.")
        logger.warning("   - 실현 손익: 해당 날짜 기준")
        logger.warning("   - 총자산/평가금/예수금: 현재 시점 기준 (API 한계)")
    
    if total_asset == 0:
        total_asset = cash_balance + stock_eval
        logger.info(f"   (보정) 총 자산 0원 -> {total_asset:,.0f}원 (예수금 + 주식평가)")
    
    logger.info(f"   날짜: {today}")
    logger.info(f"   총 자산: {total_asset:,.0f}원")
    logger.info(f"   예수금: {cash_balance:,.0f}원")
    logger.info(f"   주식평가: {stock_eval:,.0f}원")
    logger.info(f"   평가손익: {total_pnl:,.0f}원")
    logger.info(f"   실현손익: {realized_pnl:,.0f}원")
    
    # 3. DB 저장 (Upsert via ORM merge)
    session = None
    try:
        session = get_session()
        
        # ORM 방식 upsert: 기존 레코드 조회 후 업데이트 또는 신규 생성
        existing = session.query(DailyAssetSnapshot).filter_by(snapshot_date=today).first()
        
        if existing:
            # 기존 레코드 업데이트
            existing.total_asset_amount = total_asset
            existing.cash_balance = cash_balance
            existing.stock_eval_amount = stock_eval
            existing.total_profit_loss = total_pnl
            existing.realized_profit_loss = realized_pnl
            logger.info(f"🔄 기존 레코드 업데이트 (날짜: {today})")
        else:
            # 신규 레코드 생성
            new_snapshot = DailyAssetSnapshot(
                snapshot_date=today,
                total_asset_amount=total_asset,
                cash_balance=cash_balance,
                stock_eval_amount=stock_eval,
                total_profit_loss=total_pnl,
                realized_profit_loss=realized_pnl,
            )
            session.add(new_snapshot)
            logger.info(f"➕ 신규 레코드 생성 (날짜: {today})")
        
        session.commit()
        
        logger.info(f"✅ DB 저장 완료 (테이블: {DailyAssetSnapshot.__tablename__})")
        
    except Exception as e:
        logger.error(f"❌ DB 저장 실패: {e}")
        if session:
            session.rollback()
        return False
    finally:
        if session:
            session.close()
            
    logger.info("=" * 60)
    logger.info("✨ 일별 자산 스냅샷 완료")
    logger.info("=" * 60)
    return True

if __name__ == "__main__":
    if run_snapshot():
        sys.exit(0)
    else:
        sys.exit(1)
