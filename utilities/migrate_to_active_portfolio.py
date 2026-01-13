import os
import sys

# 프로젝트 루트 경로 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


from shared.db.connection import get_session, ensure_engine_initialized, get_engine
from shared.db.models import Portfolio, ActivePortfolio, Base


import logging 

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def migrate():
    import json
    
    # DB 연결 설정 로드 (Local 실행 시)
    if os.path.exists("secrets.json") and not os.getenv("MARIADB_PASSWORD"):
        try:
            with open("secrets.json") as f:
                secrets = json.load(f)
                os.environ["MARIADB_USER"] = secrets.get("mariadb-user", "jennie")
                os.environ["MARIADB_PASSWORD"] = secrets.get("mariadb-password", "")
                os.environ.setdefault("MARIADB_HOST", "127.0.0.1")
                os.environ.setdefault("MARIADB_PORT", "3307")
                os.environ.setdefault("MARIADB_DBNAME", "jennie_db")
            logger.info("🔑 secrets.json에서 DB 접속 정보 로드 완료")
        except Exception as e:
            logger.warning(f"⚠️ secrets.json 로드 실패: {e}")

    # 1. DB 연결 및 테이블 생성
    ensure_engine_initialized()

    
    # ActivePortfolio 테이블 생성 (없으면)
    # SQLAlchemy의 metadata.create_all은 기존 테이블은 건드리지 않고 없는것만 만듭니다.
    # 하지만 여기서는 명시적으로 엔진을 통해 실행합니다.
    try:
        ActivePortfolio.__table__.create(bind=get_engine())
        logger.info("✅ ACTIVE_PORTFOLIO 테이블 생성 완료 (혹은 이미 존재)")
    except Exception as e:
        logger.warning(f"테이블 생성 중 메시지 (이미 존재 가능성): {e}")

    with get_session() as session:
        try:
            # 2. 기존 Portfolio에서 HOLDING 아이템 모두 조회
            holdings = session.query(Portfolio).filter(Portfolio.status == 'HOLDING').all()
            
            logger.info(f"📋 기존 PORTFOLIO 테이블에서 'HOLDING' 상태 {len(holdings)}건 발견.")
            
            migrated_count = 0
            
            # 3. ActivePortfolio로 이관
            for h in holdings:
                # 중복 방지를 위해 먼저 조회 (혹시라도 스크립트 재실행 시)
                existing = session.query(ActivePortfolio).filter_by(stock_code=h.stock_code).first()
                if existing:
                    logger.info(f"  - [Skip] {h.stock_code} ({h.stock_name}): 이미 ACTIVE_PORTFOLIO에 존재함.")
                    continue
                
                new_item = ActivePortfolio(
                    stock_code=h.stock_code,
                    stock_name=h.stock_name,
                    quantity=h.quantity,
                    average_buy_price=h.average_buy_price,
                    total_buy_amount=h.total_buy_amount,
                    current_high_price=h.current_high_price,
                    stop_loss_price=h.stop_loss_price,
                    created_at=h.created_at,
                    updated_at=h.updated_at
                )
                session.add(new_item)
                logger.info(f"  - [Migrate] {h.stock_code} ({h.stock_name}): {h.quantity}주 이관")
                migrated_count += 1
            
            session.commit()
            logger.info(f"✅ 마이그레이션 완료! 총 {migrated_count}건 이관됨.")
            
        except Exception as e:
            session.rollback()
            logger.error(f"❌ 마이그레이션 실패: {e}")
            raise

if __name__ == "__main__":
    confirm = input("⚠️ 정말로 마이그레이션을 실행하시겠습니까? (ACTIVE_PORTFOLIO 테이블 생성 및 데이터 복사) [y/N]: ")
    if confirm.lower() == 'y':
        migrate()
    else:
        print("취소되었습니다.")
