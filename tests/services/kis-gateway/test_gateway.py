# tests/services/kis-gateway/test_gateway.py

import pytest
from unittest.mock import MagicMock, patch, ANY
import sys
import os
import json
import importlib.util

# Disable auto-init in main.py
os.environ['WERKZEUG_RUN_MAIN'] = 'true'

# Project root setup
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
sys.path.insert(0, PROJECT_ROOT)

# Dynamic import of kis-gateway main module
GATEWAY_DIR = os.path.join(PROJECT_ROOT, 'services', 'kis-gateway')
MAIN_PATH = os.path.join(GATEWAY_DIR, 'main.py')

spec = importlib.util.spec_from_file_location("kis_gateway_main", MAIN_PATH)
gateway_main = importlib.util.module_from_spec(spec)
sys.modules["kis_gateway_main"] = gateway_main
spec.loader.exec_module(gateway_main)

spec.loader.exec_module(gateway_main)

from kis_gateway_main import app, kis_client, limiter

# Disable limiter for testing
limiter.enabled = False

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

@pytest.fixture
def mock_kis_client():
    # Patch the global kis_client in the module
    mock_client = MagicMock()
    gateway_main.kis_client = mock_client
    return mock_client

class TestKISGateway:
    
    def test_health(self, client):
        """Test /health endpoint"""
        response = client.get('/health')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'ok'
        assert 'circuit_breaker' in data

    def test_issue_token(self, client, mock_kis_client):
        """Test /api/token endpoint"""
        # Setup mock
        mock_kis_client.auth.get_access_token.return_value = "ACCESS_TOKEN_123"
        
        # Execute
        response = client.post('/api/token', json={})
        
        # Verify
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['access_token'] == "ACCESS_TOKEN_123"

    def test_get_snapshot_proxied(self, client, mock_kis_client):
        """Test /api/market-data/snapshot proxy"""
        # Setup mock
        mock_snapshot = {'price': 70000, 'name': 'Samsung'}
        mock_kis_client.get_stock_snapshot.return_value = mock_snapshot
        
        # Execute
        response = client.post('/api/market-data/snapshot', json={'stock_code': '005930'})
        
        # Verify
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert data['data'] == mock_snapshot
        mock_kis_client.get_stock_snapshot.assert_called_with('005930', is_index=False)

    def test_snapshot_missing_code(self, client):
        """Test snapshot validation"""
        response = client.post('/api/market-data/snapshot', json={})
        assert response.status_code == 400

    def test_buy_order_proxy(self, client, mock_kis_client):
        """Test /api/trading/buy proxy"""
        # Setup mock
        mock_kis_client.trading.place_buy_order.return_value = "ORDER_12345"
        
        # Execute
        payload = {'stock_code': '005930', 'quantity': 10, 'price': 70000}
        response = client.post('/api/trading/buy', json=payload)
        
        # Verify
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert data['order_no'] == "ORDER_12345"
        
        mock_kis_client.trading.place_buy_order.assert_called_with('005930', 10, 70000)

    def test_circuit_breaker_error(self, client, mock_kis_client):
        """Test error handling (Circuit Breaker simulation)"""
        # Simulate exception
        mock_kis_client.get_stock_snapshot.side_effect = Exception("API Error")
        
        response = client.post('/api/market-data/snapshot', json={'stock_code': '005930'})
        
        assert response.status_code == 500
        data = json.loads(response.data)
        assert "API Error" in data['error']

    def test_sell_order_proxy(self, client, mock_kis_client):
        """Test /api/trading/sell proxy"""
        mock_kis_client.trading.place_sell_order.return_value = "ORDER_999"
        
        payload = {'stock_code': '005930', 'quantity': 5, 'price': 70000}
        response = client.post('/api/trading/sell', json=payload)
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['order_no'] == "ORDER_999"
        
        mock_kis_client.trading.place_sell_order.assert_called_with('005930', 5, 70000)

    def test_get_account_balance(self, client, mock_kis_client):
        """Test /api/account/balance proxy"""
        mock_balance = [{'code': '005930', 'quantity': 10}]
        mock_kis_client.trading.get_account_balance.return_value = mock_balance
        
        response = client.post('/api/account/balance')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['data'] == mock_balance

    def test_get_cash_balance(self, client, mock_kis_client):
        """Test /api/account/cash-balance proxy"""
        mock_kis_client.trading.get_cash_balance.return_value = 5000000
        
        response = client.post('/api/account/cash-balance')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['data'] == 5000000

    def test_check_market_open(self, client, mock_kis_client):
        """Test /api/market-data/check-market-open proxy"""
        mock_kis_client.check_market_open.return_value = True
        
        response = client.get('/api/market-data/check-market-open')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['data']['is_open'] is True

    def test_get_daily_prices(self, client, mock_kis_client):
        """Test /api/market-data/daily-prices proxy"""
        # Mocking pandas DataFrame return if possible, or list of dicts if normalized
        # The gateway expects an object that has to_dict or is list/dict
        mock_prices = [{'date': '2023-01-01', 'close': 100}]
        
        # Mock behavior where KIS returns object
        mock_kis_client.get_stock_daily_prices.return_value = mock_prices
        
        payload = {'stock_code': '005930', 'num_days_to_fetch': 10}
        response = client.post('/api/market-data/daily-prices', json=payload)
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['data'] == mock_prices

