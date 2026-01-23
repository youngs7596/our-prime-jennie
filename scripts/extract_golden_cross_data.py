
import sys
import os
from datetime import datetime, timedelta
import pandas as pd
from sqlalchemy import select, text
import json

# Add project root to sys.path
sys.path.append(os.getcwd())

from shared.db.connection import init_engine, session_scope
from shared.db.models import TradeLog, StockDailyPrice, StockInvestorTrading

def extract_data():
    print("Initializing Database Connection...")
    init_engine()

    report_path = "reports/golden_cross_deep_dive.md"
    os.makedirs("reports", exist_ok=True)

    with session_scope() as session:
        # 1. Fetch GOLDEN_CROSS trades (Last 90 days)
        start_date = datetime.utcnow() - timedelta(days=90)
        stmt = select(TradeLog).where(
            TradeLog.trade_timestamp >= start_date,
            TradeLog.strategy_signal.like('%GOLDEN_CROSS%'),
            TradeLog.trade_type == 'BUY'
        ).order_by(TradeLog.trade_timestamp)
        
        buy_trades = session.execute(stmt).scalars().all()
        
        if not buy_trades:
            print("No GOLDEN_CROSS trades found in the last 3 months.")
            return

        print(f"Found {len(buy_trades)} GOLDEN_CROSS buy trades. Extracting context...")

        report_content = ["# Golden Cross Strategy Deep Dive Report\n"]
        report_content.append(f"**Analysis Period**: {start_date.date()} ~ {datetime.utcnow().date()}")
        report_content.append(f"**Total Samples**: {len(buy_trades)}\n")
        report_content.append("## Objective")
        report_content.append("- Analyze 22 Golden Cross trades to find patterns for earlier entry and optimized exit.")
        report_content.append("- Correlate with Foreign/Institution Net Buy signals.\n")

        for buy in buy_trades:
            stock_code = buy.stock_code
            buy_date = buy.trade_timestamp.date()
            
            # Find matching sell
            stmt_sell = select(TradeLog).where(
                TradeLog.stock_code == stock_code,
                TradeLog.trade_type == 'SELL',
                TradeLog.trade_timestamp > buy.trade_timestamp
            ).order_by(TradeLog.trade_timestamp).limit(1)
            
            sell = session.execute(stmt_sell).scalars().first()
            
            # Context Window: Buy - 10 days to Sell + 5 days (or Buy + 20 days if no sell)
            ctx_start = buy_date - timedelta(days=10)
            if sell:
                ctx_end = sell.trade_timestamp.date() + timedelta(days=5)
                exit_price = sell.price
                profit_pct = (sell.price - buy.price) / buy.price * 100
                status = "CLOSED"
            else:
                ctx_end = buy_date + timedelta(days=20)
                exit_price = "N/A"
                profit_pct = 0.0
                status = "OPEN"

            report_content.append(f"### [Trade] {stock_code} ({buy_date})")
            report_content.append(f"- **Status**: {status}")
            report_content.append(f"- **Buy**: {buy.price:,.0f}")
            report_content.append(f"- **Sell**: {exit_price:,.0f} (Profit: {profit_pct:.2f}%)" if sell else f"- **Current**: Holding")
            
            # Data Fetching
            # Data Fetching - Split into two queries to avoid collation error
            # 1. Price Data
            stmt_price = text("""
                SELECT 
                    PRICE_DATE, 
                    CLOSE_PRICE, HIGH_PRICE, LOW_PRICE, VOLUME
                FROM STOCK_DAILY_PRICES_3Y
                WHERE STOCK_CODE = :code 
                  AND PRICE_DATE BETWEEN :start AND :end
                ORDER BY PRICE_DATE ASC
            """)
            
            # 2. Investor Data
            stmt_investor = text("""
                SELECT 
                    TRADE_DATE, 
                    FOREIGN_NET_BUY, INSTITUTION_NET_BUY
                FROM STOCK_INVESTOR_TRADING
                WHERE STOCK_CODE = :code 
                  AND TRADE_DATE BETWEEN :start AND :end
                ORDER BY TRADE_DATE ASC
            """)
            
            rows_price = session.execute(stmt_price, {"code": stock_code, "start": ctx_start, "end": ctx_end}).fetchall()
            rows_investor = session.execute(stmt_investor, {"code": stock_code, "start": ctx_start, "end": ctx_end}).fetchall()
            
            # Convert to Dict for easy lookup
            # TRADE_DATE is already a date object (model definition)
            investor_map = {r.TRADE_DATE: r for r in rows_investor}
            
            report_content.append("\n**Daily Data (Price & Investor Net Buy)**")
            report_content.append("| Date | Close | High | Foreign | Inst | Note |")
            report_content.append("|---|---|---|---|---|---|")
            
            for r in rows_price:
                d = r.PRICE_DATE.date()
                close = int(r.CLOSE_PRICE)
                high = int(r.HIGH_PRICE)
                
                inv = investor_map.get(d)
                foreign = int(inv.FOREIGN_NET_BUY) if inv and inv.FOREIGN_NET_BUY is not None else 0
                inst = int(inv.INSTITUTION_NET_BUY) if inv and inv.INSTITUTION_NET_BUY is not None else 0
                
                # Format numbers for readability (e.g. 1.2B, 100M)
                def fmt_money(val):
                    abs_val = abs(val)
                    if abs_val >= 100000000:
                        return f"{val/100000000:.1f}억"
                    elif abs_val >= 1000000:
                        return f"{val/1000000:.0f}백만"
                    else:
                        return f"{val:,.0f}"

                note = ""
                if d == buy_date:
                    note = "🔴 **BUY**"
                elif sell and d == sell.trade_timestamp.date():
                    note = "🔵 **SELL**"
                
                report_content.append(f"| {d} | {close:,.0f} | {high:,.0f} | {fmt_money(foreign)} | {fmt_money(inst)} | {note} |")
            
            report_content.append("\n---\n")

        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(report_content))
            
        print(f"Report generated at {report_path}")

if __name__ == "__main__":
    extract_data()
