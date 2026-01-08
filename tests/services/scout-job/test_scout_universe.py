# tests/services/scout-job/test_scout_universe.py

import pytest
from unittest.mock import MagicMock, patch
import sys
import os
import pandas as pd

# Project root setup
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
sys.path.insert(0, PROJECT_ROOT)

from services.scout_job_module import scout_universe

@pytest.fixture
def mock_kis_api():
    return MagicMock()

@pytest.fixture
def mock_session():
    return MagicMock()

class TestScoutUniverse:
    @patch('services.scout_job_module.scout_universe.requests.get')
    def test_get_dynamic_blue_chips_naver(self, mock_get):
        """Test scanning blue chips via Naver Finance scraping"""
        # Mock Naver Finance HTML response
        # scrapper looks for table.type_2 tbody tr -> td
        # Needs at least 10 columns (len(cells) < 10 continue)
        # Column 1 (index 1): Name/Link
        # Column 2 (index 2): Price
        # Column 4 (index 4): Rate (5th col)
        
        html = """
        <html>
        <body>
        <table class="type_2">
            <tbody>
                <tr></tr> <!-- Invalid row -->
                <tr>
                    <td>1</td>
                    <td><a href="/item/main.naver?code=005930" class="tltle">Samsung</a></td>
                    <td>80,000</td>
                    <td><img src="up.gif" alt="상승"></td>
                    <td>+1.25%</td>
                    <td>1000</td>
                    <td>5000000</td>
                    <td></td><td></td><td></td><td></td>
                </tr>
                <tr>
                    <td>2</td>
                    <td><a href="/item/main.naver?code=000660" class="tltle">SK Hynix</a></td>
                    <td>120,000</td>
                    <td><img src="down.gif" alt="하락"></td>
                    <td>-0.5%</td>
                    <td>2000</td>
                    <td>3000000</td>
                    <td></td><td></td><td></td><td></td>
                </tr>
            </tbody>
        </table>
        </body>
        </html>
        """
        mock_get.return_value.text = html
        
        result = scout_universe.get_dynamic_blue_chips(limit=2)
        
        assert len(result) == 2
        assert result[0]['code'] == '005930'
        assert result[0]['name'] == 'Samsung'
        assert result[0]['price'] == 80000.0
        assert result[0]['change_pct'] == 1.25
        # 005930 maps to '반도체'
        assert result[0]['sector'] == '반도체'

    def test_get_momentum_stocks(self, mock_kis_api, mock_session):
        """Test get_momentum_stocks logic"""
        
        # Mock database.get_all_stock_codes to return None (trigger fallback to watchlist)
        # Mock watchlist
        base_candidates = {
            '005930': {'stock_name': 'Samsung', 'is_tradable': True},
            '000660': {'stock_name': 'SK Hynix', 'is_tradable': True}
        }
        
        # Mock Prices
        dates = pd.date_range(end=pd.Timestamp.now(), periods=200)
        
        # KOSPI: Flat (0% return)
        kospi_prices = [100] * 200
        df_kospi = pd.DataFrame({'CLOSE_PRICE': kospi_prices, 'PRICE_DATE': dates})
        
        # Stocks: Doubling (100 -> 200, 100% return)
        stock_prices = [100 + (i * 0.5) for i in range(200)] 
        df_stock = pd.DataFrame({'CLOSE_PRICE': stock_prices, 'PRICE_DATE': dates})
        
        def get_prices_side_effect(conn, code, limit=None):
            if code == '0001':
                return df_kospi
            return df_stock

        with patch('shared.database.get_all_stock_codes', return_value=None), \
             patch('shared.database.get_active_watchlist', return_value=base_candidates), \
             patch('shared.database.get_daily_prices', side_effect=get_prices_side_effect):
             
             result = scout_universe.get_momentum_stocks(
                 mock_kis_api, mock_session, period_months=6, top_n=2, watchlist_snapshot={}
             )
             
             assert len(result) == 2
             # Stock return 100% - KOSPI 0% = 100% Momentum
             assert result[0]['momentum'] > 0


