#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KIS API Mock Server
로컬 테스트용 가짜 KIS API 서버 (HTTP REST API + WebSocket)

WebSocket 기능:
- '/socket.io' 네임스페이스로 연결
- 'subscribe' 이벤트: 종목 구독
- 'price_update' 이벤트: 실시간 가격 전송
"""

from flask import Flask, request, jsonify
from flask_socketio import SocketIO, emit
import random
import time
import threading
from datetime import datetime

app = Flask(__name__)

# SocketIO 초기화 (CORS 허용)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Mock 데이터
STOCK_DATA = {
    "005930": {"name": "삼성전자", "base_price": 70000},
    "000660": {"name": "SK하이닉스", "base_price": 130000},
    "035420": {"name": "NAVER", "base_price": 210000},
    "035720": {"name": "카카오", "base_price": 45000},
    "0001": {"name": "KOSPI", "base_price": 2500},
}

# 토큰 저장소
tokens = {}

# WebSocket 구독 상태
subscribed_clients = {}  # sid -> list of stock codes
streaming_threads = {}   # sid -> thread
stop_events = {}         # sid -> Event


# =============================================================================
# HTTP REST API Endpoints
# =============================================================================

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "service": "kis-mock", "websocket": True}), 200

@app.route('/oauth2/tokenP', methods=['POST'])
def token():
    """OAuth 토큰 발급"""
    data = request.json
    app_key = data.get('appkey')
    app_secret = data.get('appsecret')
    
    # 간단한 토큰 생성
    token = f"mock_token_{int(time.time())}"
    tokens[token] = {
        "app_key": app_key,
        "created_at": datetime.now(),
        "expires_in": 86400
    }
    
    return jsonify({
        "access_token": token,
        "access_token_token_expired": "2099-12-31 23:59:59",
        "token_type": "Bearer",
        "expires_in": 86400
    }), 200

@app.route('/uapi/domestic-stock/v1/quotations/inquire-price', methods=['GET'])
@app.route('/uapi/domestic-stock/v1/quotations/inquire-price-2', methods=['GET'])
def inquire_price():
    """현재가 조회"""
    # 대소문자 모두 지원
    stock_code = request.args.get('FID_INPUT_ISCD') or request.args.get('fid_input_iscd')
    
    if not stock_code:
        return jsonify({
            "rt_cd": "1",
            "msg1": "종목코드 파라미터 누락"
        }), 400
    
    if stock_code not in STOCK_DATA:
        return jsonify({
            "rt_cd": "1",
            "msg1": "종목코드 없음"
        }), 404
    
    stock = STOCK_DATA[stock_code]
    
    # 랜덤 가격 변동 (-3% ~ +3%)
    price_change = random.uniform(-0.03, 0.03)
    current_price = int(stock["base_price"] * (1 + price_change))
    
    # 다른 데이터도 랜덤 생성
    open_price = int(current_price * random.uniform(0.98, 1.02))
    high_price = int(current_price * random.uniform(1.00, 1.05))
    low_price = int(current_price * random.uniform(0.95, 1.00))
    volume = random.randint(1000000, 50000000)
    
    return jsonify({
        "rt_cd": "0",
        "msg_cd": "MCA00000",
        "msg1": "정상처리 되었습니다.",
        "output": {
            "stck_prpr": str(current_price),  # 현재가
            "stck_oprc": str(open_price),     # 시가
            "stck_hgpr": str(high_price),     # 고가
            "stck_lwpr": str(low_price),      # 저가
            "acml_vol": str(volume),          # 누적거래량
            "prdy_vrss": str(int(current_price * price_change)),  # 전일 대비
            "prdy_vrss_sign": "2" if price_change >= 0 else "5",  # 등락 기호
            "prdy_ctrt": f"{price_change * 100:.2f}",  # 전일 대비율
            "per": "12.34",
            "pbr": "1.23",
            "eps": "5000",
            "bps": "57000",
            "hts_kor_isnm": stock["name"]
        }
    }), 200

@app.route('/uapi/domestic-stock/v1/trading/order-cash', methods=['POST'])
def order_cash():
    """현금 주문 (매수/매도)"""
    data = request.json
    stock_code = data.get('PDNO')
    order_qty = data.get('ORD_QTY')
    order_price = data.get('ORD_UNPR', '0')
    order_type = data.get('ORD_DVSN')  # 00: 지정가, 01: 시장가
    
    # Mock 주문번호 생성
    order_no = f"MOCK{int(time.time())}{random.randint(1000, 9999)}"
    
    return jsonify({
        "rt_cd": "0",
        "msg_cd": "MCA00000",
        "msg1": "정상처리 되었습니다.",
        "output": {
            "KRX_FWDG_ORD_ORGNO": "00001",
            "ODNO": order_no,  # 주문번호
            "ORD_TMD": datetime.now().strftime("%H%M%S")
        }
    }), 200

@app.route('/uapi/domestic-stock/v1/trading/inquire-balance', methods=['GET'])
def inquire_balance():
    """잔고 조회"""
    # 빈 잔고 반환 (또는 테스트용 Mock 데이터)
    return jsonify({
        "rt_cd": "0",
        "msg_cd": "MCA00000",
        "msg1": "정상처리 되었습니다.",
        "output1": [],  # 보유 종목 목록
        "output2": [{
            "dnca_tot_amt": "10000000",  # 예수금 총액
            "nxdy_excc_amt": "10000000",  # 익일 정산 금액
            "prvs_rcdl_excc_amt": "10000000",  # 전일 정산 금액
            "tot_evlu_amt": "0",  # 총 평가금액
            "pchs_amt_smtl_amt": "0",  # 매입금액합계
            "evlu_amt_smtl_amt": "0",  # 평가금액합계
            "evlu_pfls_smtl_amt": "0"  # 평가손익합계
        }]
    }), 200

@app.route('/uapi/domestic-stock/v1/quotations/inquire-daily-price', methods=['GET'])
def inquire_daily_price():
    """일별 시세 조회"""
    stock_code = request.args.get('fid_input_iscd')
    
    if stock_code not in STOCK_DATA:
        return jsonify({"rt_cd": "1", "msg1": "종목코드 없음"}), 404
    
    stock = STOCK_DATA[stock_code]
    base_price = stock["base_price"]
    
    # 최근 30일 데이터 생성
    output = []
    for i in range(30):
        date = datetime.now()
        date_str = date.strftime("%Y%m%d")
        
        # 랜덤 데이터
        close = int(base_price * random.uniform(0.95, 1.05))
        open_p = int(close * random.uniform(0.98, 1.02))
        high = int(close * random.uniform(1.00, 1.03))
        low = int(close * random.uniform(0.97, 1.00))
        volume = random.randint(1000000, 50000000)
        
        output.append({
            "stck_bsop_date": date_str,
            "stck_clpr": str(close),
            "stck_oprc": str(open_p),
            "stck_hgpr": str(high),
            "stck_lwpr": str(low),
            "acml_vol": str(volume)
        })
    
    return jsonify({
        "rt_cd": "0",
        "msg_cd": "MCA00000",
        "msg1": "정상처리 되었습니다.",
        "output": output
    }), 200


# =============================================================================
# 테스트용 API (E2E 테스트 지원)
# =============================================================================

@app.route('/api/trigger-buy-signal', methods=['POST'])
def trigger_buy_signal():
    """
    테스트용: 매수 신호 직접 발행
    
    사용법:
    curl -X POST http://localhost:9443/api/trigger-buy-signal \
         -H "Content-Type: application/json" \
         -d '{"stock_code": "005930", "signal_type": "GOLDEN_CROSS"}'
    """
    data = request.json or {}
    stock_code = data.get('stock_code', '005930')
    signal_type = data.get('signal_type', 'TEST_SIGNAL')
    
    stock = STOCK_DATA.get(stock_code, {"name": "테스트종목", "base_price": 50000})
    current_price = int(stock["base_price"] * random.uniform(0.98, 1.02))
    
    # 매수 신호 메시지 생성
    buy_signal = {
        'stock_code': stock_code,
        'stock_name': stock.get('name', '테스트종목'),
        'signal_type': signal_type,
        'signal_reason': f'[TEST] {signal_type} 신호 발생',
        'current_price': current_price,
        'llm_score': 80,
        'market_regime': 'BULL',
        'source': 'mock_test_api',
        'timestamp': datetime.now().isoformat()
    }
    
    # 모든 구독 클라이언트에게 buy_signal 이벤트 발행
    socketio.emit('buy_signal', buy_signal)
    print(f"[TEST API] 🎯 매수 신호 발행: {stock_code} ({signal_type})")
    
    return jsonify({
        "success": True,
        "message": f"매수 신호 발행 완료: {stock_code}",
        "signal": buy_signal
    }), 200


@app.route('/api/trigger-price-burst', methods=['POST'])
def trigger_price_burst():
    """
    테스트용: 특정 종목에 빠른 가격 업데이트 발행 (캔들 완성 시뮬레이션)
    
    사용법:
    curl -X POST http://localhost:9443/api/trigger-price-burst \
         -H "Content-Type: application/json" \
         -d '{"stock_code": "005930", "count": 60, "interval_ms": 100}'
    """
    data = request.json or {}
    stock_code = data.get('stock_code', '005930')
    count = min(data.get('count', 60), 120)  # 최대 120회
    interval_ms = max(data.get('interval_ms', 100), 50)  # 최소 50ms
    
    stock = STOCK_DATA.get(stock_code, {"name": "테스트종목", "base_price": 50000})
    
    def send_burst():
        for i in range(count):
            price_change = random.uniform(-0.02, 0.02)
            current_price = int(stock["base_price"] * (1 + price_change))
            
            socketio.emit('price_update', {
                'stock_code': stock_code,
                'stock_name': stock.get('name', '테스트종목'),
                'current_price': current_price,
                'high': int(current_price * 1.01),
                'low': int(current_price * 0.99),
                'volume': random.randint(10000, 100000),
                'timestamp': datetime.now().isoformat()
            })
            time.sleep(interval_ms / 1000.0)
        print(f"[TEST API] 💰 가격 버스트 완료: {stock_code} ({count}회)")
    
    thread = threading.Thread(target=send_burst, daemon=True)
    thread.start()
    
    return jsonify({
        "success": True,
        "message": f"가격 버스트 시작: {stock_code} ({count}회, {interval_ms}ms 간격)",
        "stock_code": stock_code,
        "count": count,
        "interval_ms": interval_ms
    }), 200


# =============================================================================
# WebSocket (SocketIO) Events
# =============================================================================

@socketio.on('connect')
def handle_connect():
    """클라이언트 연결"""
    from flask import request as flask_request
    sid = flask_request.sid
    print(f"[WS] 클라이언트 연결: {sid}")
    subscribed_clients[sid] = []
    stop_events[sid] = threading.Event()
    emit('connected', {'message': 'Mock KIS WebSocket 연결 성공', 'sid': sid})


@socketio.on('disconnect')
def handle_disconnect():
    """클라이언트 연결 해제"""
    from flask import request as flask_request
    sid = flask_request.sid
    print(f"[WS] 클라이언트 연결 해제: {sid}")
    
    # 스트리밍 중지
    if sid in stop_events:
        stop_events[sid].set()
        del stop_events[sid]
    
    if sid in subscribed_clients:
        del subscribed_clients[sid]
    
    if sid in streaming_threads:
        del streaming_threads[sid]


@socketio.on('subscribe')
def handle_subscribe(data):
    """종목 구독 요청"""
    from flask import request as flask_request
    sid = flask_request.sid
    codes = data.get('codes', [])
    
    # 등록된 종목만 구독
    valid_codes = [c for c in codes if c in STOCK_DATA]
    
    subscribed_clients[sid] = valid_codes
    print(f"[WS] 종목 구독: {valid_codes} (클라이언트: {sid})")
    
    emit('subscribed', {
        'total': len(valid_codes),
        'codes': valid_codes,
        'invalid': [c for c in codes if c not in STOCK_DATA]
    })
    
    # 가격 스트리밍 시작
    if valid_codes:
        start_price_streaming(sid, valid_codes)


def start_price_streaming(sid, codes):
    """가격 스트리밍 스레드 시작"""
    stop_event = stop_events.get(sid)
    if not stop_event:
        return
    
    def stream_prices():
        print(f"[WS] 가격 스트리밍 시작: {codes}")
        tick_count = 0
        
        while not stop_event.is_set():
            for code in codes:
                if stop_event.is_set():
                    break
                
                stock = STOCK_DATA.get(code)
                if not stock:
                    continue
                
                # 랜덤 가격 생성 (기준가 ± 5%)
                price_change = random.uniform(-0.05, 0.05)
                current_price = int(stock["base_price"] * (1 + price_change))
                high_price = int(current_price * random.uniform(1.00, 1.03))
                low_price = int(current_price * random.uniform(0.97, 1.00))
                volume = random.randint(10000, 500000)
                
                # 가격 업데이트 전송
                socketio.emit('price_update', {
                    'stock_code': code,
                    'stock_name': stock["name"],
                    'current_price': current_price,
                    'high': high_price,
                    'low': low_price,
                    'volume': volume,
                    'timestamp': datetime.now().isoformat()
                }, room=sid)
                
                tick_count += 1
                if tick_count % 10 == 0:
                    print(f"[WS] 가격 업데이트 #{tick_count}: {code} = {current_price:,}원")
            
            # 5초마다 가격 업데이트 (테스트용으로 빠르게)
            time.sleep(5)
        
        print(f"[WS] 가격 스트리밍 종료: {codes}")
    
    thread = threading.Thread(target=stream_prices, daemon=True)
    thread.start()
    streaming_threads[sid] = thread


# =============================================================================
# Main
# =============================================================================

if __name__ == '__main__':
    print("🚀 KIS Mock Server 시작 (REST + WebSocket)...")
    print("   포트: 9443")
    print("   Health Check: http://localhost:9443/health")
    print("   WebSocket: ws://localhost:9443/socket.io")
    
    # SocketIO로 실행 (일반 Flask run 대신)
    socketio.run(app, host='0.0.0.0', port=9443, debug=True, allow_unsafe_werkzeug=True)
