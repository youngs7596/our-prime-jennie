# services/daily-briefing/reporter.py
# Version: v1.0
# Daily Briefing Service - LLM 기반 일일 보고서 생성
# Centralized LLM using JennieBrain (Factory Pattern)

import os
import logging
from datetime import datetime
from typing import Dict, List, Optional

import shared.database as database
import shared.auth as auth
from shared.llm import JennieBrain

logger = logging.getLogger(__name__)


class DailyReporter:
    """LLM 기반 일일 브리핑 리포터 (Powered by JennieBrain)"""
    
    def __init__(self, kis_client, telegram_bot):
        self.kis = kis_client
        self.bot = telegram_bot
        # JennieBrain 초기화 (Factory/Tier 자동 처리)
        try:
            secrets = auth._load_local_secrets()
            project_id = secrets.get("project_id", "my-prime-jennie")
            gemini_key_secret = "gemini-api-key" # Legacy init param, not strictly used in v6 Factory
            
            self.jennie_brain = JennieBrain(project_id, gemini_key_secret)
            logger.info("✅ DailyReporter: JennieBrain 연결 완료")
        except Exception as e:
            logger.error(f"❌ DailyReporter JennieBrain 초기화 실패: {e}")
            self.jennie_brain = None
        
    def create_and_send_report(self):
        """리포트를 생성하고 텔레그램으로 발송합니다."""
        try:
            from shared.db.connection import session_scope
            
            with session_scope() as session:
                # 1. 데이터 수집
                report_data = self._collect_report_data(session)
                
                # 2. LLM 기반 보고서 생성 (Centralized)
                if self.jennie_brain:
                    # 데이터 요약 생성
                    market_summary_text = self._format_market_summary(report_data)
                    execution_log_text = self._format_execution_log(report_data)
                    
                    message = self.jennie_brain.generate_daily_briefing(
                        market_summary_text, 
                        execution_log_text
                    )
                else:
                    message = self._format_basic_message(report_data)
                
                # 3. 발송
                return self.bot.send_message(message)
                
        except Exception as e:
            logger.error(f"리포트 생성 중 오류: {e}", exc_info=True)
            return False
    
    def _collect_report_data(self, session) -> Dict:
        """보고서 생성에 필요한 모든 데이터 수집"""
        # 리포트 생성 전 실계좌 잔고와 동기화 (Data Drift 방지)
        try:
            self._sync_portfolio_with_live_data(session)
        except Exception as e:
            logger.error(f"⚠️ 포트폴리오 동기화 실패 (기존 데이터로 진행): {e}")

        today_str = datetime.now().strftime('%Y-%m-%d')
        
        # 0. 시장 지수 (KOSPI/KOSDAQ)
        market_indices = {}
        try:
            kospi = self.kis.get_stock_snapshot("0001", is_index=True)
            kosdaq = self.kis.get_stock_snapshot("1001", is_index=True)
            if kospi: market_indices['KOSPI'] = kospi
            if kosdaq: market_indices['KOSDAQ'] = kosdaq
        except Exception as e:
            logger.error(f"⚠️ 시장 지수 조회 실패: {e}")

        # 1. 현금 잔고
        cash_balance = self.kis.get_cash_balance()
        
        # 2. 포트폴리오 현황
        portfolio = database.get_active_portfolio(session)
        stock_valuation = 0
        portfolio_details = []
        
        for item in portfolio:
            stock_code = item['code']
            snapshot = self.kis.get_stock_snapshot(stock_code)
            current_price = float(snapshot.get('price', item['avg_price'])) if snapshot else float(item['avg_price'])
            
            quantity = int(item['quantity'])
            valuation = current_price * quantity
            stock_valuation += valuation
            
            profit_pct = ((current_price - item['avg_price']) / item['avg_price']) * 100
            profit_amount = (current_price - item['avg_price']) * quantity
            
            portfolio_details.append({
                'name': item['name'],
                'code': stock_code,
                'quantity': quantity,
                'avg_price': item['avg_price'],
                'current_price': current_price,
                'valuation': valuation,
                'profit_pct': profit_pct,
                'profit_amount': profit_amount
            })
        
        total_aum = cash_balance + stock_valuation
        
        # 3. 금일 거래 내역
        today_trades = database.get_trade_logs(session, date=today_str)
        trade_summary = self._summarize_trades(today_trades)
        
        # 3-1. Tier2 주간 성과 (최근 7일) - Scout 미통과 매수의 품질/리스크 모니터링
        try:
            tier2_weekly = self._get_tier2_weekly_summary(session, portfolio_details)
        except Exception as e:
            logger.error(f"⚠️ Tier2 주간 성과 집계 실패: {e}")
            tier2_weekly = None
        
        # 4. Watchlist 현황
        try:
            watchlist_data = database.get_active_watchlist(session)
            watchlist = list(watchlist_data.values())
            watchlist_summary = [{
                'name': w.get('name', 'N/A'),
                'code': w.get('code', 'N/A'),
                'llm_score': w.get('llm_score', 0),
                'filter_reason': w.get('filter_reason', 'N/A')[:100] if w.get('filter_reason') else 'N/A'
            } for w in watchlist[:10]]
        except:
            watchlist_summary = []
        
        # 5. 최근 뉴스 (Top Global Sentiment)
        try:
            recent_news = self._get_recent_news_sentiment(session)
        except:
            recent_news = []
            
        # 6. 어제 대비 AUM 변동
        try:
            yesterday_aum = self._get_yesterday_aum(session)
            daily_change_pct = ((total_aum - yesterday_aum) / yesterday_aum * 100) if yesterday_aum > 0 else 0
        except:
            yesterday_aum = total_aum
            daily_change_pct = 0
            
        return {
            'date': today_str,
            'market_indices': market_indices, # Added
            'total_aum': total_aum,
            'cash_balance': cash_balance,
            'stock_valuation': stock_valuation,
            'cash_ratio': (cash_balance / total_aum * 100) if total_aum > 0 else 0,
            'portfolio': portfolio_details,
            'trades': trade_summary,
            'tier2_weekly': tier2_weekly,
            'watchlist': watchlist_summary,
            'recent_news': recent_news,
            'daily_change_pct': daily_change_pct,
            'yesterday_aum': yesterday_aum
        }

    def _format_market_summary(self, data: Dict) -> str:
        """시장 정보 데이터 (LLM 입력용 Text)"""
        # [Market Indices]
        indices_text = ""
        if data.get('market_indices'):
            for name, info in data['market_indices'].items():
                change_rate = (info['price'] - info['open']) / info['open'] * 100 # Approx intraday change
                # Or use proper change if avail. current snapshot doesn't have change pct usually directly? 
                # check dict keys: 'price', 'high', 'low', 'open'.
                # Let's just show Price and Open.
                indices_text += f"- {name}: {info['price']:,.2f} (Open: {info['open']:,.2f})\n"
        else:
            indices_text = "지수 정보 수집 실패"

        # [News]
        if data['recent_news']:
            # Top 3 news
            news_text = "\n".join([f"- {n['name']}: {n['headline']} (감성: {n['score']}점)" for n in data['recent_news'][:5]])
        else:
            news_text = "특이 뉴스 없음 (감성 분석 데이터 부족)"
        
        summary = f"""
        [지수 현황]
        {indices_text}

        [자산 현황]
        - 날짜: {data['date']}
        - 총 운용자산: {data['total_aum']:,.0f}원 (변동: {data['daily_change_pct']:+.2f}%)
        - 현금 비중: {data['cash_ratio']:.1f}%

        [주요 뉴스 (Top Sentiment)]
        {news_text}
        """
        return summary

    def _format_execution_log(self, data: Dict) -> str:
        """실행 로그 데이터 (LLM 입력용 Text)"""
        trades = data['trades']
        portfolio = data['portfolio']
        tier2_weekly = data.get('tier2_weekly')
        
        trade_logs = []
        if trades['buy_count'] > 0 or trades['sell_count'] > 0:
            for t in trades['details']:
                action = "매수" if t['action'] == "BUY" else "매도"
                trade_logs.append(f"- {action}: {t['name']} {t['quantity']}주 ({t['reason']})")
        else:
            trade_logs.append("금일 체결된 매매 없음")
            
        pf_logs = []
        for p in portfolio:
            status = "수익중" if p['profit_pct'] > 0 else "손실중"
            pf_logs.append(f"- {p['name']}: {status} ({p['profit_pct']:+.2f}%)")
        
        tier2_logs = []
        if tier2_weekly and tier2_weekly.get("buy_count", 0) > 0:
            tier2_logs.append(f"- 최근 7일 Tier2 매수: {tier2_weekly['buy_count']}건 ({tier2_weekly['unique_codes']}종목)")
            held = tier2_weekly.get("held_count", 0)
            if held > 0:
                tier2_logs.append(f"- 현재 보유중(Tier2 유래): {held}종목, 평균 수익률: {tier2_weekly.get('avg_profit_pct_held', 0):+.2f}%")
                tier2_logs.append(f"- 승/패(보유 기준): {tier2_weekly.get('winners_held', 0)}/{held}")
            # 상위/하위 3개 요약
            top = tier2_weekly.get("top_held", [])
            if top:
                tier2_logs.append("- 상위(보유): " + ", ".join([f"{x['name']}({x['code']}) {x['profit_pct']:+.2f}%" for x in top]))
            bottom = tier2_weekly.get("bottom_held", [])
            if bottom:
                tier2_logs.append("- 하위(보유): " + ", ".join([f"{x['name']}({x['code']}) {x['profit_pct']:+.2f}%" for x in bottom]))
            
        return f"""
        [매매 수행]
        {chr(10).join(trade_logs)}
        
        [현재 포트폴리오]
        {chr(10).join(pf_logs) if pf_logs else "보유 종목 없음"}
        
        [Tier2 주간 성과(최근 7일)]
        {chr(10).join(tier2_logs) if tier2_logs else "Tier2 매수 없음"}
        """

    def _get_tier2_weekly_summary(self, session, portfolio_details: List[Dict]) -> Optional[Dict]:
        """
        최근 7일 Tier2(Scout Judge 미통과) 매수 성과 요약.
        - BUY 트레이드의 key_metrics_json에 tier='TIER2'가 기록된 건을 기준으로 집계
        - 실현손익은 포괄적으로 계산하기 어렵기 때문에, '현재 보유중 종목의 평가손익' 중심으로 보여줍니다.
        """
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import text
        import json
        from shared.db import models as db_models
        
        tradelog_table = db_models.resolve_table_name("TRADELOG")
        since = datetime.now(timezone.utc) - timedelta(days=7)
        
        rows = session.execute(text(f"""
            SELECT STOCK_CODE, TRADE_TYPE, QUANTITY, PRICE, KEY_METRICS_JSON, TRADE_TIMESTAMP
            FROM {tradelog_table}
            WHERE TRADE_TIMESTAMP >= :since
            ORDER BY TRADE_TIMESTAMP DESC
        """), {"since": since}).fetchall()
        
        tier2_buys = []
        for r in rows:
            stock_code, trade_type, qty, price, km_json, ts = r
            if trade_type != "BUY":
                continue
            try:
                km = json.loads(km_json or "{}")
            except Exception:
                km = {}
            if km.get("tier") == "TIER2":
                tier2_buys.append({
                    "code": stock_code,
                    "quantity": int(qty or 0),
                    "price": float(price or 0),
                    "ts": ts,
                    "llm_score": km.get("llm_score"),
                    "buy_signal_type": km.get("buy_signal_type"),
                })
        
        if not tier2_buys:
            return {"buy_count": 0, "unique_codes": 0, "held_count": 0}
        
        # 보유중 종목 평가손익 매핑 (portfolio_details 기반)
        pf_map = {p["code"]: p for p in (portfolio_details or [])}
        held_items = []
        for b in tier2_buys:
            if b["code"] in pf_map:
                p = pf_map[b["code"]]
                held_items.append({
                    "code": p["code"],
                    "name": p["name"],
                    "profit_pct": float(p["profit_pct"]),
                    "profit_amount": float(p["profit_amount"]),
                })
        
        held_items_sorted = sorted(held_items, key=lambda x: x["profit_pct"], reverse=True)
        held_count = len(held_items_sorted)
        avg_profit_pct_held = (sum(x["profit_pct"] for x in held_items_sorted) / held_count) if held_count else 0.0
        winners_held = sum(1 for x in held_items_sorted if x["profit_pct"] > 0)
        
        return {
            "buy_count": len(tier2_buys),
            "unique_codes": len({b["code"] for b in tier2_buys}),
            "held_count": held_count,
            "avg_profit_pct_held": avg_profit_pct_held,
            "winners_held": winners_held,
            "top_held": held_items_sorted[:3],
            "bottom_held": list(reversed(held_items_sorted[-3:])) if held_items_sorted else [],
        }

    def _summarize_trades(self, trades: List) -> Dict:
        """거래 내역 요약"""
        buy_count = 0
        sell_count = 0
        total_buy_amount = 0
        total_sell_amount = 0
        realized_profit = 0
        trade_details = []
        
        for trade in trades:
            action = trade.get('action', '')
            amount = float(trade.get('amount', 0))
            
            if action == 'BUY':
                buy_count += 1
                total_buy_amount += amount
            elif action == 'SELL':
                sell_count += 1
                total_sell_amount += amount
                realized_profit += float(trade.get('profit_amount', 0))
            
            trade_details.append({
                'action': action,
                'name': trade.get('stock_name', 'N/A'),
                'quantity': trade.get('quantity', 0),
                'price': trade.get('price', 0),
                'amount': amount,
                'reason': trade.get('reason', 'N/A')[:50] if trade.get('reason') else 'N/A'
            })
        
        return {
            'buy_count': buy_count,
            'sell_count': sell_count,
            'total_buy_amount': total_buy_amount,
            'total_sell_amount': total_sell_amount,
            'realized_profit': realized_profit,
            'details': trade_details[:10]  # 최근 10건만
        }
    
    def _get_recent_news_sentiment(self, session) -> List[Dict]:
        """최근 뉴스 감성 점수 조회"""
        from sqlalchemy import text
        try:
            result = session.execute(text("""
                SELECT STOCK_CODE, STOCK_NAME, SENTIMENT_SCORE, HEADLINE
                FROM NEWS_SENTIMENT 
                WHERE CREATED_AT >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
                ORDER BY SENTIMENT_SCORE DESC
                LIMIT 5
            """))
            rows = result.fetchall()
            
            return [{
                'code': row[0],
                'name': row[1],
                'score': row[2],
                'headline': row[3][:50] if row[3] else 'N/A'
            } for row in rows]
        except:
            return []
    


    def _sync_portfolio_with_live_data(self, session):
        """KIS 실계좌 잔고를 조회하여 로컬 DB(Portfolio)와 동기화"""
        from sqlalchemy import text
        
        # 1. 실계좌 잔고 조회
        balance_data = self.kis.get_account_balance()
        if not balance_data:
            logger.warning("⚠️ KIS 등기화 실패: 잔고 조회 데이터 없음")
            return

        live_holdings = {} # {code: {qty, avg_price, name}}
        if isinstance(balance_data, list):
            items = balance_data
        elif isinstance(balance_data, dict):
            # API 응답 구조에 따라 다를 수 있음 (output1 등)
            # GatewayClient.get_account_balance 구현에 따라 list 가정
            items = balance_data.get('output1', []) if 'output1' in balance_data else []
        else:
            items = []

        # Gateway가 직접 리스트를 반환하는 경우 (Mock/Real 통일됨)
        # 위 curl 응답 예시: [{"avg_price":..., "code":...}, ...]
        if isinstance(balance_data, list):
             items = balance_data

        # [Manual Management] 수동 관리 종목 동기화 제외 (필요시 추가)
        MANUAL_MANAGED_CODES = []

        for item in items:
            code = item.get('code') or item.get('pdno')
            name = item.get('name') or item.get('prdt_name')
            qty = int(float(item.get('quantity') or item.get('hldg_qty') or 0))
            avg_price = float(item.get('avg_price') or item.get('pchs_avg_pric') or 0)
            
            if code in MANUAL_MANAGED_CODES:
                logger.info(f"⏭️ 수동 관리 종목 동기화 건너뜀: {name}({code})")
                continue

            if code and qty > 0:
                live_holdings[code] = {'qty': qty, 'avg_price': avg_price, 'name': name}

        if not live_holdings:
            logger.info("ℹ️ 실계좌 보유 종목 없음")
            # DB의 모든 HOLDING 상태 종목을 SOLD로 처리해야 할 수도 있음 (전량 매도 시)
            # 안전을 위해 여기서는 pass

        logger.info(f"🔄 포트폴리오 동기화 시작 (실계좌: {len(live_holdings)}종목)")

        # 2. DB 업데이트
        table_name = database._get_table_name("Portfolio")
        
        
        # 2-1. 기존 DB 보유 종목 확인 (Status가 SOLD라도 존재하는지 확인하여 중복 Insert 방지)
        # STOCK_CODE에 Unique Constraint가 없으므로 로직으로 처리해야 함
        result = session.execute(text(f"SELECT STOCK_CODE FROM {table_name}"))
        existing_codes = {row[0] for row in result.fetchall()}
        
        # 2-2. Update & Insert
        for code, info in live_holdings.items():
            if code in existing_codes:
                # 이미 존재하는 종목 (HOLDING 또는 SOLD) -> UPDATE
                # 중복된 행이 있을 경우 모두 업데이트됨 (데이터 정합성 유지)
                session.execute(text(f"""
                    UPDATE {table_name}
                    SET QUANTITY = :qty, AVERAGE_BUY_PRICE = :price, STATUS = 'HOLDING', UPDATED_AT = NOW()
                    WHERE STOCK_CODE = :code
                """), {'qty': info['qty'], 'price': info['avg_price'], 'code': code})
            else:
                # DB에 아예 없는 신규 종목 -> INSERT
                session.execute(text(f"""
                    INSERT INTO {table_name} (STOCK_CODE, STOCK_NAME, QUANTITY, AVERAGE_BUY_PRICE, STATUS, CREATED_AT, UPDATED_AT)
                    VALUES (:code, :name, :qty, :price, 'HOLDING', NOW(), NOW())
                """), {'code': code, 'name': info['name'], 'qty': info['qty'], 'price': info['avg_price']})
        
        # 2-3. Delete (Mark as SOLD) - DB에는 있는데 실계좌에 없는 경우
        for db_code in existing_codes:
            if db_code in MANUAL_MANAGED_CODES:
                continue
                
            if db_code not in live_holdings:
                logger.info(f"📉 외부 매도 감지: {db_code} (DB 보유 -> 실계좌 부재)")
                session.execute(text(f"""
                    UPDATE {table_name}
                    SET QUANTITY = 0, STATUS = 'SOLD', UPDATED_AT = NOW()
                    WHERE STOCK_CODE = :code
                """), {'code': db_code})
        
        session.commit()
        logger.info("✅ 포트폴리오 동기화 완료")
    
    def _get_yesterday_aum(self, session) -> float:
        """어제의 총 자산 조회"""
        from sqlalchemy import text
        try:
            result = session.execute(text("SELECT CONFIG_VALUE FROM CONFIG WHERE CONFIG_KEY = 'DAILY_AUM_YESTERDAY'"))
            row = result.fetchone()
            return float(row[0]) if row else 0
        except:
            return 0
    
    def _format_basic_message(self, data: Dict) -> str:
        """LLM 없이 기본 메시지 포맷팅 (폴백)"""
        
        profit = data['trades']['realized_profit']
        profit_emoji = "🔴" if profit > 0 else ("🔵" if profit < 0 else "⚪")
        
        lines = []
        lines.append(f"📅 *Daily Briefing ({data['date']})*")
        lines.append("")
        
        lines.append("💰 *자산 현황*")
        lines.append(f"• 총 운용 자산: *{data['total_aum']:,.0f}원*")
        lines.append(f"• 현금: {data['cash_balance']:,.0f}원 ({data['cash_ratio']:.1f}%)")
        lines.append(f"• 주식: {data['stock_valuation']:,.0f}원")
        lines.append(f"• 어제 대비: {data['daily_change_pct']:+.2f}%")
        lines.append("")
        
        lines.append(f"📊 *금일 성과*")
        lines.append(f"• 실현 손익: {profit_emoji} *{profit:,.0f}원*")
        lines.append(f"• 거래: 매수 {data['trades']['buy_count']}건 / 매도 {data['trades']['sell_count']}건")
        lines.append("")
        
        if data['portfolio']:
            lines.append("💼 *보유 종목*")
            for item in data['portfolio'][:5]:
                p_emoji = "🔴" if item['profit_pct'] > 0 else ("🔵" if item['profit_pct'] < 0 else "⚪")
                lines.append(f"{p_emoji} {item['name']}: {item['profit_pct']:+.2f}%")
        
        lines.append("")
        lines.append("🤖 *Jennie's Comment (Basic Mode)*")
        lines.append("오늘은 기본적인 요약만 전달드려요. 그래도 화이팅입니다! 💪")
            
        return "\n".join(lines)
