# tests/e2e/mock_server/kis_mock_server.py
"""
Mock KIS Gateway Server for E2E Testing

Flask-based HTTP server that simulates the KIS Gateway API
with configurable scenarios and state management.
"""

import json
import time
import logging
import threading
import random
from typing import Optional, Dict, Any
from dataclasses import asdict
from flask import Flask, request, jsonify

from .scenarios import Scenario, ScenarioManager, ResponseMode, StockState

logger = logging.getLogger(__name__)


class KISMockServer:
    """
    Mock KIS Gateway HTTP Server

    Provides fake endpoints for testing without real API calls.
    Supports scenario-based configuration for different test cases.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8080):
        self.host = host
        self.port = port
        self.app = Flask(__name__)
        self.scenario_manager = ScenarioManager()
        self._server_thread: Optional[threading.Thread] = None
        self._shutdown_event = threading.Event()

        # Request tracking for assertions
        self._request_history: list = []
        self._order_history: list = []

        self._register_routes()

    def _register_routes(self):
        """Register all API endpoints"""

        @self.app.route('/health', methods=['GET'])
        def health():
            return jsonify({"status": "healthy", "mock": True})

        @self.app.route('/api/trading/buy', methods=['POST'])
        def buy():
            return self._handle_buy_order(request.json)

        @self.app.route('/api/trading/sell', methods=['POST'])
        def sell():
            return self._handle_sell_order(request.json)

        @self.app.route('/api/trading/cancel', methods=['POST'])
        def cancel():
            return self._handle_cancel_order(request.json)

        @self.app.route('/api/market-data/snapshot/<stock_code>', methods=['GET'])
        def snapshot(stock_code: str):
            return self._handle_snapshot(stock_code)

        @self.app.route('/api/account/cash-balance', methods=['GET'])
        def cash_balance():
            return self._handle_cash_balance()

        @self.app.route('/api/account/balance', methods=['GET'])
        def account_balance():
            return self._handle_account_balance()

        @self.app.route('/api/market-data/check-market-open', methods=['GET'])
        def check_market_open():
            return self._handle_check_market_open()

        # Admin endpoints for test control
        @self.app.route('/admin/scenario', methods=['POST'])
        def set_scenario():
            return self._handle_set_scenario(request.json)

        @self.app.route('/admin/reset', methods=['POST'])
        def reset():
            return self._handle_reset()

        @self.app.route('/admin/set-price', methods=['POST'])
        def set_price():
            return self._handle_set_price(request.json)

        @self.app.route('/admin/history', methods=['GET'])
        def get_history():
            return jsonify({
                "requests": self._request_history[-100:],
                "orders": self._order_history[-50:]
            })

    def _apply_response_mode(self) -> Optional[tuple]:
        """Apply response mode effects (errors, delays)"""
        scenario = self.scenario_manager.current
        if not scenario:
            return None

        # Apply delay
        if scenario.response_delay_ms > 0:
            time.sleep(scenario.response_delay_ms / 1000.0)

        # Apply error modes
        if scenario.response_mode == ResponseMode.ERROR_500:
            return jsonify({"error": "Internal Server Error", "code": "ERR500"}), 500

        if scenario.response_mode == ResponseMode.ERROR_400:
            return jsonify({"error": "Bad Request", "code": "ERR400"}), 400

        if scenario.response_mode == ResponseMode.TIMEOUT:
            time.sleep(30)  # Force timeout
            return jsonify({"error": "Timeout"}), 504

        return None

    def _track_request(self, endpoint: str, method: str, data: Any = None):
        """Track request for test assertions"""
        self._request_history.append({
            "timestamp": time.time(),
            "endpoint": endpoint,
            "method": method,
            "data": data
        })

    def _handle_buy_order(self, data: dict) -> tuple:
        """Handle buy order request"""
        self._track_request("/api/trading/buy", "POST", data)

        error_response = self._apply_response_mode()
        if error_response:
            return error_response

        scenario = self.scenario_manager.current
        if not scenario:
            return jsonify({"error": "No scenario active"}), 500

        stock_code = data.get('stock_code')
        quantity = data.get('quantity', 0)
        price = data.get('price', 0)

        # Check emergency stop
        if scenario.emergency_stop:
            return jsonify({"error": "Trading stopped", "code": "EMERGENCY_STOP"}), 403

        # Check trading paused
        if scenario.trading_paused:
            return jsonify({"error": "Trading paused", "code": "TRADING_PAUSED"}), 403

        # Check market open
        if not scenario.market_open:
            return jsonify({"error": "Market closed", "code": "MARKET_CLOSED"}), 400

        # Check daily limit
        if scenario.today_buy_count >= scenario.max_buy_count_per_day:
            return jsonify({"error": "Daily limit reached", "code": "DAILY_LIMIT"}), 400

        # Get stock price if not specified
        stock = scenario.get_stock(stock_code)
        if price == 0 and stock:
            price = stock.price

        # Check cash balance
        order_amount = price * quantity
        if order_amount > scenario.cash_balance:
            return jsonify({"error": "Insufficient funds", "code": "INSUFFICIENT_FUNDS"}), 400

        # Check order success rate
        if random.random() > scenario.order_success_rate:
            return jsonify({"error": "Order rejected", "code": "ORDER_REJECTED"}), 400

        # Execute order
        order_no = scenario.get_next_order_no("BUY")
        scenario.cash_balance -= order_amount
        scenario.today_buy_count += 1

        # Add to portfolio
        stock_name = stock.name if stock else stock_code
        scenario.add_to_portfolio(stock_code, stock_name, quantity, price)

        self._order_history.append({
            "type": "BUY",
            "order_no": order_no,
            "stock_code": stock_code,
            "quantity": quantity,
            "price": price,
            "amount": order_amount,
            "timestamp": time.time()
        })

        return jsonify({
            "status": "success",
            "order_no": order_no,
            "stock_code": stock_code,
            "quantity": quantity,
            "price": price,
            "amount": order_amount
        })

    def _handle_sell_order(self, data: dict) -> tuple:
        """Handle sell order request"""
        self._track_request("/api/trading/sell", "POST", data)

        error_response = self._apply_response_mode()
        if error_response:
            return error_response

        scenario = self.scenario_manager.current
        if not scenario:
            return jsonify({"error": "No scenario active"}), 500

        stock_code = data.get('stock_code')
        quantity = data.get('quantity', 0)
        price = data.get('price', 0)

        # Check emergency stop (allow manual sells)
        is_manual = data.get('is_manual', False)
        if scenario.emergency_stop and not is_manual:
            return jsonify({"error": "Trading stopped", "code": "EMERGENCY_STOP"}), 403

        # Check market open
        if not scenario.market_open:
            return jsonify({"error": "Market closed", "code": "MARKET_CLOSED"}), 400

        # Check portfolio
        portfolio_item = scenario.get_portfolio_item(stock_code)
        if not portfolio_item:
            return jsonify({"error": "Not in portfolio", "code": "NO_POSITION"}), 400

        if portfolio_item.quantity < quantity:
            return jsonify({"error": "Insufficient quantity", "code": "INSUFFICIENT_QTY"}), 400

        # Get current price if not specified
        stock = scenario.get_stock(stock_code)
        if price == 0 and stock:
            price = stock.price
        elif price == 0 and portfolio_item:
            price = portfolio_item.current_price or portfolio_item.avg_price

        # Check order success rate
        if random.random() > scenario.order_success_rate:
            return jsonify({"error": "Order rejected", "code": "ORDER_REJECTED"}), 400

        # Execute order
        order_no = scenario.get_next_order_no("SELL")
        sell_amount = price * quantity
        scenario.cash_balance += sell_amount

        # Remove from portfolio
        scenario.remove_from_portfolio(stock_code, quantity)

        self._order_history.append({
            "type": "SELL",
            "order_no": order_no,
            "stock_code": stock_code,
            "quantity": quantity,
            "price": price,
            "amount": sell_amount,
            "timestamp": time.time()
        })

        return jsonify({
            "status": "success",
            "order_no": order_no,
            "stock_code": stock_code,
            "quantity": quantity,
            "price": price,
            "amount": sell_amount
        })

    def _handle_cancel_order(self, data: dict) -> tuple:
        """Handle cancel order request"""
        self._track_request("/api/trading/cancel", "POST", data)

        error_response = self._apply_response_mode()
        if error_response:
            return error_response

        scenario = self.scenario_manager.current
        if not scenario:
            return jsonify({"error": "No scenario active"}), 500

        order_no = data.get('order_no')
        if not order_no:
            return jsonify({"error": "Missing order_no"}), 400

        # Check pre-configured cancel results
        if order_no in scenario.cancel_results:
            cancelled = scenario.cancel_results[order_no]
        else:
            # Default: cancel succeeds (order was not filled)
            cancelled = True

        return jsonify({
            "status": "success",
            "order_no": order_no,
            "cancelled": cancelled,
        })

    def _handle_snapshot(self, stock_code: str) -> tuple:
        """Handle stock snapshot request"""
        self._track_request(f"/api/market-data/snapshot/{stock_code}", "GET")

        error_response = self._apply_response_mode()
        if error_response:
            return error_response

        scenario = self.scenario_manager.current
        if not scenario:
            return jsonify({"error": "No scenario active"}), 500

        # Per-stock snapshot errors (e.g. KIS API failure for specific stock)
        if stock_code in scenario.snapshot_errors:
            err = scenario.snapshot_errors[stock_code]
            return jsonify({
                "error": err.get("message", "Snapshot error"),
                "code": err.get("code", "SNAPSHOT_ERROR"),
            }), err.get("status", 500)

        stock = scenario.get_stock(stock_code)
        if not stock:
            # Return default values for unknown stocks
            return jsonify({
                "price": 10000,
                "open": 10000,
                "high": 10000,
                "low": 10000,
                "volume": 10000,
                "change_pct": 0.0
            })

        return jsonify(stock.to_snapshot())

    def _handle_cash_balance(self) -> tuple:
        """Handle cash balance request"""
        self._track_request("/api/account/cash-balance", "GET")

        error_response = self._apply_response_mode()
        if error_response:
            return error_response

        scenario = self.scenario_manager.current
        if not scenario:
            return jsonify({"error": "No scenario active"}), 500

        return jsonify({
            "cash_balance": scenario.cash_balance,
            "currency": "KRW"
        })

    def _handle_account_balance(self) -> tuple:
        """Handle account balance request (includes portfolio)"""
        self._track_request("/api/account/balance", "GET")

        error_response = self._apply_response_mode()
        if error_response:
            return error_response

        scenario = self.scenario_manager.current
        if not scenario:
            return jsonify({"error": "No scenario active"}), 500

        portfolio_value = sum(
            item.quantity * (item.current_price or item.avg_price)
            for item in scenario.portfolio
        )

        return jsonify({
            "cash_balance": scenario.cash_balance,
            "portfolio_value": portfolio_value,
            "total_assets": scenario.cash_balance + portfolio_value,
            "holdings": [item.to_dict() for item in scenario.portfolio]
        })

    def _handle_check_market_open(self) -> tuple:
        """Handle market open check"""
        self._track_request("/api/market-data/check-market-open", "GET")

        error_response = self._apply_response_mode()
        if error_response:
            return error_response

        scenario = self.scenario_manager.current
        if not scenario:
            return jsonify({"is_open": False})

        return jsonify({
            "is_open": scenario.market_open,
            "market_regime": scenario.market_regime
        })

    def _handle_set_scenario(self, data: dict) -> tuple:
        """Admin: Activate a scenario"""
        scenario_name = data.get('name')
        if not scenario_name:
            return jsonify({"error": "Missing scenario name"}), 400

        try:
            scenario = self.scenario_manager.activate(scenario_name)
            return jsonify({
                "status": "success",
                "scenario": scenario.name,
                "description": scenario.description
            })
        except ValueError as e:
            return jsonify({"error": str(e)}), 404

    def _handle_reset(self) -> tuple:
        """Admin: Reset current scenario and history"""
        self.scenario_manager.reset_current()
        self._request_history.clear()
        self._order_history.clear()
        return jsonify({"status": "reset"})

    def _handle_set_price(self, data: dict) -> tuple:
        """Admin: Set stock price dynamically"""
        stock_code = data.get('stock_code')
        price = data.get('price')

        if not stock_code or price is None:
            return jsonify({"error": "Missing stock_code or price"}), 400

        scenario = self.scenario_manager.current
        if not scenario:
            return jsonify({"error": "No scenario active"}), 500

        scenario.set_stock_price(stock_code, price)

        # Also update portfolio item's current price
        item = scenario.get_portfolio_item(stock_code)
        if item:
            item.current_price = price

        return jsonify({
            "status": "success",
            "stock_code": stock_code,
            "price": price
        })

    def start(self, threaded: bool = True):
        """Start the mock server"""
        if threaded:
            self._server_thread = threading.Thread(
                target=self._run_server,
                daemon=True
            )
            self._server_thread.start()
            # Wait for server to start
            time.sleep(0.5)
            logger.info(f"Mock KIS server started on {self.host}:{self.port}")
        else:
            self._run_server()

    def _run_server(self):
        """Run the Flask server"""
        from werkzeug.serving import make_server
        self._wsgi_server = make_server(self.host, self.port, self.app, threaded=True)
        self._wsgi_server.serve_forever()

    def stop(self):
        """Stop the mock server"""
        if hasattr(self, '_wsgi_server'):
            self._wsgi_server.shutdown()
        if self._server_thread:
            self._server_thread.join(timeout=5)
        logger.info("Mock KIS server stopped")

    @property
    def base_url(self) -> str:
        """Get base URL for the server"""
        return f"http://{self.host}:{self.port}"

    def activate_scenario(self, name: str) -> Scenario:
        """Activate a scenario by name"""
        return self.scenario_manager.activate(name)

    def get_scenario(self, name: str) -> Optional[Scenario]:
        """Get a scenario by name"""
        return self.scenario_manager.get(name)

    @property
    def current_scenario(self) -> Optional[Scenario]:
        """Get currently active scenario"""
        return self.scenario_manager.current

    def get_order_history(self) -> list:
        """Get order history for assertions"""
        return self._order_history.copy()

    def get_request_history(self) -> list:
        """Get request history for assertions"""
        return self._request_history.copy()

    def clear_history(self):
        """Clear request and order history"""
        self._request_history.clear()
        self._order_history.clear()


class MockKISClient:
    """
    Client wrapper that mimics the real KIS API client interface.
    Connects to the KISMockServer.
    """

    def __init__(self, server: KISMockServer):
        self.server = server
        self.base_url = server.base_url

    def get_cash_balance(self) -> float:
        """Get available cash balance"""
        import requests
        resp = requests.get(f"{self.base_url}/api/account/cash-balance")
        if resp.ok:
            return resp.json().get('cash_balance', 0)
        return 0

    def get_stock_snapshot(self, stock_code: str) -> Optional[dict]:
        """Get stock snapshot"""
        import requests
        resp = requests.get(f"{self.base_url}/api/market-data/snapshot/{stock_code}")
        if resp.ok:
            return resp.json()
        return None

    def place_buy_order(self, stock_code: str, quantity: int, price: float = 0) -> Optional[str]:
        """Place buy order"""
        import requests
        resp = requests.post(f"{self.base_url}/api/trading/buy", json={
            "stock_code": stock_code,
            "quantity": quantity,
            "price": price
        })
        if resp.ok:
            return resp.json().get('order_no')
        return None

    def place_sell_order(self, stock_code: str, quantity: int, price: float = 0) -> Optional[str]:
        """Place sell order"""
        import requests
        resp = requests.post(f"{self.base_url}/api/trading/sell", json={
            "stock_code": stock_code,
            "quantity": quantity,
            "price": price
        })
        if resp.ok:
            return resp.json().get('order_no')
        return None

    def cancel_order(self, order_no: str, quantity: int = 0) -> bool:
        """Cancel an order. Returns True if cancelled (not filled), False if already filled."""
        import requests
        resp = requests.post(f"{self.base_url}/api/trading/cancel", json={
            "order_no": order_no,
            "quantity": quantity,
        })
        if resp.ok:
            return resp.json().get('cancelled', True)
        return True  # Default: assume cancelled on error

    def check_market_open(self) -> bool:
        """Check if market is open"""
        import requests
        resp = requests.get(f"{self.base_url}/api/market-data/check-market-open")
        if resp.ok:
            return resp.json().get('is_open', False)
        return False

    def get_account_balance(self) -> dict:
        """Get full account balance including portfolio"""
        import requests
        resp = requests.get(f"{self.base_url}/api/account/balance")
        if resp.ok:
            return resp.json()
        return {}
