import sys
import os
import logging
from datetime import datetime, timedelta
from sqlalchemy import func
# from tabulate import tabulate (Removed)

# 프로젝트 루트를 sys.path에 추가 (scripts 폴더 상위)
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from shared.db.connection import init_engine, session_scope
from shared.db.models import TradeLog, ActivePortfolio, AgentCommands


# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def inspect_trades():
    # DB 초기화
    init_engine()
    
    # 시간대 설정 (KST to UTC)
    kst_now = datetime.now() # 일단 로컬 시간(KST)을 가져온다고 가정
    target_date_kst_start = datetime(2026, 1, 15, 0, 0, 0)
    target_date_kst_end = datetime(2026, 1, 15, 23, 59, 59)
    
    # UTC 변환
    utc_start = target_date_kst_start - timedelta(hours=9)
    utc_end = target_date_kst_end - timedelta(hours=9)
    
    print(f"Ref Date (KST): {target_date_kst_start} ~ {target_date_kst_end}")
    print(f"Ref Date (UTC): {utc_start} ~ {utc_end}")
    
    with session_scope(readonly=True) as session:
        # 1. 거래 내역 조회
        trades = session.query(TradeLog).filter(
            TradeLog.trade_timestamp >= utc_start,
            TradeLog.trade_timestamp <= utc_end
        ).order_by(TradeLog.trade_timestamp.asc()).all()
        
        print(f"\n[TradeLog] Total Count: {len(trades)}")
        
        trade_data = []
        for t in trades:
            # UTC -> KST 변환 for display
            trade_time_kst = t.trade_timestamp + timedelta(hours=9)
            trade_data.append([
                t.log_id,
                t.stock_code,
                t.trade_type,
                t.quantity,
                t.price,
                trade_time_kst.strftime('%H:%M:%S'),
                t.reason[:50] + "..." if t.reason else ""
            ])
            
        # print(tabulate(trade_data, headers=["ID", "Stock", "Type", "Qty", "Price", "Time(KST)", "Reason"], tablefmt="grid"))
        print(f"{'ID':<8} {'Stock':<10} {'Type':<6} {'Qty':<6} {'Price':<10} {'Time(KST)':<10} {'Reason'}")
        print("-" * 80)
        for row in trade_data:
            print(f"{row[0]:<8} {row[1]:<10} {row[2]:<6} {row[3]:<6} {row[4]:<10} {row[5]:<10} {row[6]}")
        
        # 2. 종목별 집계
        print("\n[Summary by Stock]")
        summary_data = {}
        for t in trades:
            code = t.stock_code
            if code not in summary_data:
                summary_data[code] = {'BUY': 0, 'SELL': 0, 'BUY_QTY': 0, 'SELL_QTY': 0}
            
            summary_data[code][t.trade_type] += 1
            if t.trade_type == 'BUY':
                summary_data[code]['BUY_QTY'] += t.quantity
            else:
                summary_data[code]['SELL_QTY'] += t.quantity
        
        summary_list = []
        for code, stats in summary_data.items():
            summary_list.append([code, stats['BUY'], stats['BUY_QTY'], stats['SELL'], stats['SELL_QTY']])
            
        # print(tabulate(summary_list, headers=["Stock", "Buy Count", "Buy Qty", "Sell Count", "Sell Qty"], tablefmt="grid"))
        print(f"{'Stock':<10} {'BuyCnt':<8} {'BuyQty':<8} {'SellCnt':<8} {'SellQty':<8}")
        print("-" * 60)
        for row in summary_list:
            print(f"{row[0]:<10} {row[1]:<8} {row[2]:<8} {row[3]:<8} {row[4]:<8}")

        # 3. 현재 포트폴리오 상태
        print("\n[Active Portfolio]")
        portfolios = session.query(ActivePortfolio).all()
        portfolio_data = []
        for p in portfolios:
            portfolio_data.append([p.stock_code, p.stock_name, p.quantity, p.average_buy_price])
        
        # print(tabulate(portfolio_data, headers=["Stock", "Name", "Qty", "Avg Price"], tablefmt="grid"))
        print(f"{'Stock':<10} {'Name':<20} {'Qty':<6} {'Avg Price':<10}")
        print("-" * 60)
        for row in portfolio_data:
            print(f"{row[0]:<10} {row[1]:<20} {row[2]:<6} {row[3]:<10}")
            
        # 4. Agent Commands 조회 (Telegram 명령 확인)
        print("\n[Agent Commands]")
        commands = session.query(AgentCommands).filter(
            AgentCommands.created_at >= utc_start,
            AgentCommands.created_at <= utc_end
        ).order_by(AgentCommands.created_at.asc()).all()
        
        print(f"{'ID':<6} {'Type':<12} {'Status':<10} {'Cmd/Msg':<30} {'Time(KST)'}")
        print("-" * 80)
        
        cmd_cnt = 0
        for cmd in commands:
            cmd_time_kst = cmd.created_at + timedelta(hours=9)
            # command_type이 'Telegram' 인지 'System' 인지 구분 확인 필요하나 일단 다 출력
            # AgentCommands 테이블 구조상 payload에 JSON이 들어가거나 result_msg가 있음
            # command_type이나 payload 내용을 좀 보고싶음
            payload_snippet = (cmd.payload[:28] + "..") if cmd.payload else ""
            print(f"{cmd.command_id:<6} {cmd.command_type:<12} {cmd.status:<10} {payload_snippet:<30} {cmd_time_kst.strftime('%H:%M:%S')}")
            cmd_cnt += 1
            
        if cmd_cnt == 0:
            print("No agent commands found for today.")

if __name__ == "__main__":
    inspect_trades()
