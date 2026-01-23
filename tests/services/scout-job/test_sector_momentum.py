
import pytest
from unittest.mock import MagicMock
import pandas as pd
from datetime import date, timedelta
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Handle hyphen in directory name for import
import importlib.util
# Assuming we run from project root
project_root = os.getcwd()
scout_universe_path = os.path.join(project_root, "services/scout-job/scout_universe.py")
spec = importlib.util.spec_from_file_location("scout_universe", scout_universe_path)
scout_universe = importlib.util.module_from_spec(spec)
sys.modules["scout_universe"] = scout_universe
spec.loader.exec_module(scout_universe)
from scout_universe import analyze_sector_momentum


# Mock KIS API and DB
@pytest.fixture
def mock_kis_api():
    return MagicMock()

@pytest.fixture
def mock_db_conn():
    return MagicMock()

@pytest.fixture
def falling_sector_data():
    """Generates mock data for a falling sector"""
    # Create falling price series (5 days down > 3%)
    dates = [date.today() - timedelta(days=i) for i in range(30)]
    dates.sort()
    
    # Simulate a crash: Price 100 -> 90 over last 5 days
    prices = [100.0] * 25 + [98.0, 96.0, 94.0, 92.0, 90.0] 
    
    df = pd.DataFrame({
        'PRICE_DATE': dates,
        'CLOSE_PRICE': prices
    })
    return df

def test_analyze_sector_momentum_penalty(mock_kis_api, mock_db_conn, falling_sector_data):
    # 1. Mock Naver Scraping (Top Stocks)
    # We mock internal _scrape_naver_finance_top_stocks, but it's easier to mock the caller or the scraping function if exported.
    # Since analyze_sector_momentum imports it, we can patch it using unittest.mock.patch
    
    with pytest.MonkeyPatch.context() as m:
        # Mocking the scraping function
        def mock_scrape(limit=200):
            return [
                {'code': '000001', 'name': 'FallingStock1', 'sector': 'FallingSector', 'change_pct': -5.0},
                {'code': '000002', 'name': 'FallingStock2', 'sector': 'FallingSector', 'change_pct': -4.0},
            ]
        
        # We utilize the module name we manually registered
        m.setattr('scout_universe._scrape_naver_finance_top_stocks', mock_scrape)
        
        # Patch database.get_daily_prices in scout_universe
        m.setattr('scout_universe.database.get_daily_prices', lambda conn, code, limit: falling_sector_data)

        # Run Analysis
        result = analyze_sector_momentum(mock_kis_api, mock_db_conn)
        
        # Verify
        assert 'FallingSector' in result
        sector_info = result['FallingSector']
        
        print(f"Sector Info: {sector_info}")
        
        # Check Trend Status
        # 5-day return: (90 - 100)/100 = -10%  (Should be < -3%)
        # MA5: avg(90,92,94,96,98) = 94
        # MA20: (100*15 + 98+96+94+92+90)/20 = (1500 + 470)/20 = 98.5
        # MA5 (94) < MA20 (98.5) -> True (Inverse alignment)
        
        assert sector_info['penalty_score'] == -10
        assert sector_info['trend_status'] == 'FALLING_KNIFE'

if __name__ == "__main__":
    sys.exit(pytest.main(["-v", __file__]))
