#!/usr/bin/env python3
"""
utilities/sync_portfolio_from_account.py
=========================================

KIS 계좌의 실제 보유 종목과 DB ACTIVE_PORTFOLIO 테이블을 동기화합니다.

[v2.0] ActivePortfolio 모델로 업데이트 (2026-01)
- 기존 Portfolio(status=HOLDING/SOLD) → ActivePortfolio(존재=보유, 삭제=청산)
- 더 단순해진 동기화 로직

기능:
1. KIS Gateway에서 실제 계좌 보유 종목 조회
2. DB ACTIVE_PORTFOLIO 테이블과 비교 (미스매치 리포트)
3. 동기화:
   - DB에 없는 보유 종목 → 추가
   - DB에 있지만 실제로는 청산된 종목 → 삭제
   - 수량/평단가 불일치 → 수정

사용법:
    python utilities/sync_portfolio_from_account.py [--dry-run] [--auto-confirm]
    
옵션:
    --dry-run       실제 DB 변경 없이 리포트만 출력
    --auto-confirm  확인 없이 자동 적용 (주의!)
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from typing import Dict, List

# 프로젝트 루트 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# 환경변수 설정 (CLI 실행 시)
if not os.getenv('KIS_GATEWAY_URL'):
    os.environ['KIS_GATEWAY_URL'] = 'http://127.0.0.1:8080'
if not os.getenv('SECRETS_FILE'):
    os.environ['SECRETS_FILE'] = os.path.join(os.path.dirname(__file__), '..', 'secrets.json')

from sqlalchemy.orm import Session

from shared.db.connection import session_scope, ensure_engine_initialized
from shared.db.models import ActivePortfolio
from shared.kis.gateway_client import KISGatewayClient

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# DB 엔진 초기화
if os.path.exists(os.environ.get('SECRETS_FILE', '')):
    import json
    try:
        with open(os.environ['SECRETS_FILE'], 'r') as f:
            secrets = json.load(f)
            if 'mariadb-user' in secrets:
                os.environ['MARIADB_USER'] = secrets['mariadb-user']
            if 'mariadb-password' in secrets:
                os.environ['MARIADB_PASSWORD'] = secrets['mariadb-password']
            if not os.getenv('MARIADB_HOST'):
                os.environ['MARIADB_HOST'] = '127.0.0.1'
            if not os.getenv('MARIADB_PORT'):
                os.environ['MARIADB_PORT'] = '3307'
            if not os.getenv('MARIADB_DBNAME'):
                os.environ['MARIADB_DBNAME'] = 'jennie_db'
    except Exception as e:
        logger.warning(f"⚠️ secrets.json 로드 실패: {e}")

ensure_engine_initialized()


def get_kis_holdings() -> List[Dict]:
    """KIS Gateway에서 실제 계좌 보유 종목 조회"""
    logger.info("🔍 KIS Gateway에서 계좌 보유 종목 조회 중...")
    
    try:
        client = KISGatewayClient()
        holdings = client.get_account_balance()
        
        if holdings is None:
            logger.error("❌ KIS Gateway 계좌 조회 실패")
            return []
        
        logger.info(f"✅ KIS 계좌 보유 종목: {len(holdings)}개")
        return holdings
    except Exception as e:
        logger.error(f"❌ KIS Gateway 오류: {e}")
        return []


def get_db_portfolio(session: Session) -> List[ActivePortfolio]:
    """DB에서 ActivePortfolio 조회"""
    logger.info("🔍 DB에서 ACTIVE_PORTFOLIO 조회 중...")
    
    holdings = session.query(ActivePortfolio).all()
    
    logger.info(f"✅ DB 포트폴리오: {len(holdings)}개")
    return holdings


def compare_holdings(kis_holdings: List[Dict], db_portfolio: List[ActivePortfolio]) -> Dict:
    """KIS 보유 종목과 DB 포트폴리오 비교"""
    result = {
        'only_in_kis': [],      # KIS에만 있음 → DB 추가 필요
        'only_in_db': [],       # DB에만 있음 → 청산됨, 삭제 필요
        'quantity_mismatch': [],  # 수량 불일치
        'price_mismatch': [],     # 평단가 불일치
        'matched': [],          # 완전 일치
    }
    
    # KIS 보유 종목을 코드별로 매핑
    kis_map = {h['code']: h for h in kis_holdings}
    
    # DB 포트폴리오를 코드별로 매핑
    db_map = {p.stock_code: p for p in db_portfolio}
    
    kis_codes = set(kis_map.keys())
    db_codes = set(db_map.keys())
    
    # 1. KIS에만 있는 종목 (DB 추가 필요)
    for code in kis_codes - db_codes:
        kis_item = kis_map[code]
        result['only_in_kis'].append({
            'code': code,
            'name': kis_item['name'],
            'quantity': kis_item['quantity'],
            'avg_price': kis_item['avg_price'],
            'current_price': kis_item['current_price']
        })
    
    # 2. DB에만 있는 종목 (청산됨, 삭제 필요)
    for code in db_codes - kis_codes:
        db_item = db_map[code]
        result['only_in_db'].append({
            'code': code,
            'name': db_item.stock_name,
            'db_quantity': db_item.quantity,
            'db_avg_price': db_item.average_buy_price,
        })
    
    # 3. 양쪽에 있는 종목 비교
    for code in kis_codes & db_codes:
        kis_item = kis_map[code]
        db_item = db_map[code]
        
        qty_match = kis_item['quantity'] == db_item.quantity
        price_match = abs(kis_item['avg_price'] - (db_item.average_buy_price or 0)) < 1
        
        if not qty_match:
            result['quantity_mismatch'].append({
                'code': code,
                'name': kis_item['name'],
                'kis_quantity': kis_item['quantity'],
                'db_quantity': db_item.quantity,
                'kis_avg_price': kis_item['avg_price'],
            })
        elif not price_match:
            result['price_mismatch'].append({
                'code': code,
                'name': kis_item['name'],
                'quantity': kis_item['quantity'],
                'kis_avg_price': kis_item['avg_price'],
                'db_avg_price': db_item.average_buy_price,
            })
        else:
            result['matched'].append({
                'code': code,
                'name': kis_item['name'],
                'quantity': kis_item['quantity'],
                'avg_price': kis_item['avg_price']
            })
    
    return result


def print_report(comparison: Dict):
    """미스매치 리포트 출력"""
    
    print("\n" + "=" * 70)
    print("📊 포트폴리오 동기화 리포트 (ActivePortfolio)")
    print("=" * 70)
    
    # 일치하는 종목
    if comparison['matched']:
        print(f"\n✅ 일치하는 종목 ({len(comparison['matched'])}개):")
        for item in comparison['matched']:
            print(f"   - {item['code']} {item['name']}: {item['quantity']}주 @ {item['avg_price']:,.0f}원")
    
    # KIS에만 있는 종목
    if comparison['only_in_kis']:
        print(f"\n⚠️ KIS 계좌에만 있는 종목 (DB 추가 필요) ({len(comparison['only_in_kis'])}개):")
        for item in comparison['only_in_kis']:
            print(f"   - {item['code']} {item['name']}: {item['quantity']}주 @ {item['avg_price']:,.0f}원")
    
    # DB에만 있는 종목 (청산됨)
    if comparison['only_in_db']:
        print(f"\n🚨 DB에만 있는 종목 (청산됨, 삭제 필요) ({len(comparison['only_in_db'])}개):")
        for item in comparison['only_in_db']:
            print(f"   - {item['code']} {item['name']}: {item['db_quantity']}주 @ {item['db_avg_price']:,.0f}원")
    
    # 수량 불일치
    if comparison['quantity_mismatch']:
        print(f"\n⚠️ 수량 불일치 ({len(comparison['quantity_mismatch'])}개):")
        for item in comparison['quantity_mismatch']:
            diff = item['kis_quantity'] - item['db_quantity']
            diff_str = f"+{diff}" if diff > 0 else str(diff)
            print(f"   - {item['code']} {item['name']}: KIS {item['kis_quantity']}주 vs DB {item['db_quantity']}주 ({diff_str})")
    
    # 평단가 불일치
    if comparison['price_mismatch']:
        print(f"\n💰 평단가 불일치 ({len(comparison['price_mismatch'])}개):")
        for item in comparison['price_mismatch']:
            print(f"   - {item['code']} {item['name']}: KIS {item['kis_avg_price']:,.0f}원 vs DB {item['db_avg_price']:,.0f}원")
    
    print("\n" + "=" * 70)
    
    total_issues = (len(comparison['only_in_kis']) + len(comparison['only_in_db']) + 
                   len(comparison['quantity_mismatch']) + len(comparison['price_mismatch']))
    if total_issues == 0:
        print("✅ 모든 종목이 일치합니다!")
    else:
        print(f"⚠️ 총 {total_issues}개 불일치 발견")
    print("=" * 70 + "\n")


def apply_sync(session: Session, comparison: Dict, kis_holdings: List[Dict], dry_run: bool = True):
    """동기화 적용"""
    changes_made = 0
    kis_map = {h['code']: h for h in kis_holdings}
    
    # 1. DB에만 있는 종목 → 삭제 (청산됨)
    for item in comparison['only_in_db']:
        if dry_run:
            logger.info(f"[DRY RUN] {item['code']} {item['name']}: 삭제 예정 (청산됨)")
        else:
            deleted = session.query(ActivePortfolio).filter(
                ActivePortfolio.stock_code == item['code']
            ).delete()
            if deleted:
                logger.info(f"✅ {item['code']} {item['name']}: 삭제 완료 (청산됨)")
                changes_made += 1
    
    # 2. 수량 불일치 → 업데이트
    for item in comparison['quantity_mismatch']:
        if dry_run:
            logger.info(f"[DRY RUN] {item['code']} {item['name']}: 수량 {item['db_quantity']} → {item['kis_quantity']}")
        else:
            portfolio = session.query(ActivePortfolio).filter(
                ActivePortfolio.stock_code == item['code']
            ).first()
            if portfolio:
                portfolio.quantity = item['kis_quantity']
                portfolio.average_buy_price = item['kis_avg_price']
                portfolio.total_buy_amount = item['kis_quantity'] * item['kis_avg_price']
                portfolio.updated_at = datetime.now()
                logger.info(f"✅ {item['code']} {item['name']}: 수량 업데이트 완료")
                changes_made += 1
    
    # 3. 평단가 불일치 → 업데이트
    for item in comparison['price_mismatch']:
        if dry_run:
            logger.info(f"[DRY RUN] {item['code']} {item['name']}: 평단가 {item['db_avg_price']:,.0f} → {item['kis_avg_price']:,.0f}원")
        else:
            portfolio = session.query(ActivePortfolio).filter(
                ActivePortfolio.stock_code == item['code']
            ).first()
            if portfolio:
                portfolio.average_buy_price = item['kis_avg_price']
                portfolio.total_buy_amount = portfolio.quantity * item['kis_avg_price']
                portfolio.updated_at = datetime.now()
                logger.info(f"✅ {item['code']} {item['name']}: 평단가 업데이트 완료")
                changes_made += 1
    
    # 4. KIS에만 있는 종목 → 추가
    for item in comparison['only_in_kis']:
        if dry_run:
            logger.info(f"[DRY RUN] {item['code']} {item['name']}: 신규 추가 예정 ({item['quantity']}주 @ {item['avg_price']:,.0f}원)")
        else:
            new_portfolio = ActivePortfolio(
                stock_code=item['code'],
                stock_name=item['name'],
                quantity=item['quantity'],
                average_buy_price=item['avg_price'],
                total_buy_amount=item['quantity'] * item['avg_price'],
                current_high_price=item['current_price'],
                stop_loss_price=item['avg_price'] * 0.97,  # 기본 손절 -3%
            )
            session.add(new_portfolio)
            logger.info(f"✅ {item['code']} {item['name']}: 신규 추가 완료")
            changes_made += 1
    
    if not dry_run and changes_made > 0:
        try:
            session.commit()
            logger.info(f"✅ 총 {changes_made}개 항목 동기화 완료")
        except Exception as e:
            session.rollback()
            logger.error(f"❌ 동기화 실패: {e}")
            raise
    elif dry_run:
        total = (len(comparison['only_in_db']) + len(comparison['quantity_mismatch']) + 
                len(comparison['price_mismatch']) + len(comparison['only_in_kis']))
        logger.info(f"[DRY RUN] 총 {total}개 항목 변경 예정")


def main():
    parser = argparse.ArgumentParser(description='KIS 계좌와 DB 포트폴리오 동기화 (ActivePortfolio)')
    parser.add_argument('--dry-run', action='store_true', help='실제 변경 없이 리포트만 출력')
    parser.add_argument('--auto-confirm', action='store_true', help='확인 없이 자동 적용')
    args = parser.parse_args()
    
    print("\n🔄 KIS 계좌 ↔ DB ActivePortfolio 동기화 시작\n")
    
    # 1. KIS 계좌 보유 종목 조회
    kis_holdings = get_kis_holdings()
    if not kis_holdings:
        logger.warning("⚠️ KIS 계좌에 보유 종목이 없거나 조회 실패")
    
    # 2. DB 포트폴리오 조회 및 비교
    with session_scope() as session:
        db_portfolio = get_db_portfolio(session)
        
        if not db_portfolio and not kis_holdings:
            print("✅ KIS 계좌와 DB 모두 보유 종목이 없습니다.")
            return
        
        # 3. 비교
        comparison = compare_holdings(kis_holdings, db_portfolio)
        
        # 4. 리포트 출력
        print_report(comparison)
        
        # 5. 동기화 적용
        total_changes = (len(comparison['only_in_db']) + len(comparison['quantity_mismatch']) + 
                        len(comparison['price_mismatch']) + len(comparison['only_in_kis']))
        
        if total_changes == 0:
            print("✅ 동기화할 항목이 없습니다.\n")
            return
        
        if args.dry_run:
            print("📋 DRY RUN 모드: 실제 변경 없이 예상 결과만 표시합니다.\n")
            apply_sync(session, comparison, kis_holdings, dry_run=True)
        else:
            if args.auto_confirm:
                confirm = 'y'
            else:
                confirm = input(f"\n⚠️ {total_changes}개 항목을 동기화 하시겠습니까? (y/N): ").strip().lower()
            
            if confirm == 'y':
                apply_sync(session, comparison, kis_holdings, dry_run=False)
                print("\n✅ 동기화 완료!\n")
            else:
                print("\n❌ 동기화가 취소되었습니다.\n")


if __name__ == '__main__':
    main()
