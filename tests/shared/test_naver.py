"""
Unit tests for shared.crawlers.naver module
"""
import unittest
from unittest.mock import patch, MagicMock
from shared.crawlers.naver import crawl_stock_news, get_kospi_top_stocks, scrape_financial_data, scrape_pbr_per_roe

class TestNaverCrawler(unittest.TestCase):
    
    @patch('requests.get')
    def test_crawl_stock_news_success(self, mock_get):
        """Test crawl_stock_news with mocked HTML response"""
        # Mock HTML with EUC-KR encoding expectation (though mock returns unicode string)
        html_content = """
        <table class="type5">
            <tr>
                <td class="title"><a href="/news/test">Test News Title</a></td>
                <td class="info">Test Source</td>
                <td class="date">2026.01.20 10:00</td>
            </tr>
        </table>
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html_content
        mock_get.return_value = mock_response
        
        results = crawl_stock_news("005930", "Samsung", max_pages=1, deduplicate=False)
        
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['metadata']['stock_code'], "005930")
        self.assertIn("Test News Title", results[0]['page_content'])
        self.assertIn("https://finance.naver.com/news/test", results[0]['metadata']['source_url'])

    @patch('requests.get')
    def test_crawl_stock_news_filter_noise(self, mock_get):
        """Test noise filtering in crawl_stock_news"""
        html_content = """
        <table class="type5">
            <tr>
                <td class="title"><a href="/news/1">특징주 삼성전자 급등</a></td> <!-- Noise -->
            </tr>
             <tr>
                <td class="title"><a href="/news/2">Valid News</a></td>
            </tr>
        </table>
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html_content
        mock_get.return_value = mock_response
        
        results = crawl_stock_news("005930", "Samsung", max_pages=1, deduplicate=False)
        
        self.assertEqual(len(results), 1) 
        self.assertIn("Valid News", results[0]['page_content'])

    @patch('requests.get')
    def test_get_kospi_top_stocks(self, mock_get):
        """Test get_kospi_top_stocks parsing"""
        html_content = """
        <table class="type_2">
            <tbody>
                <tr>
                    <td>N/A</td>
                    <td><a href="/item/main.naver?code=005930">Samsung Elec</a></td>
                    <td>80,000</td> <!-- Price -->
                    <td><img src="up.gif"></td>
                    <td>1.5%</td> <!-- Change -->
                     <td>...</td><td>...</td><td>...</td><td>...</td><td>...</td>
                </tr>
            </tbody>
        </table>
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html_content
        mock_get.return_value = mock_response
        
        stocks = get_kospi_top_stocks(limit=1)
        
        self.assertEqual(len(stocks), 1)
        self.assertEqual(stocks[0]['code'], '005930')
        self.assertEqual(stocks[0]['price'], 80000.0)
        self.assertEqual(stocks[0]['change_pct'], 1.5)

    @patch('requests.get')
    def test_scrape_financial_data(self, mock_get):
        """Test scrape_financial_data parsing"""
        html_content = """
        <table class="tb_type1">
            <tr>
                <th>주요재무정보</th>
                <th>2023.12</th>
                <th>2024.12</th>
                <th>...</th><th>...</th><th>...</th>
            </tr>
            <tr>
                <td>매출액</td>
                <td>1,000</td>
                <td>2,000</td>
                 <td>...</td><td>...</td><td>...</td>
            </tr>
        </table>
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html_content
        mock_get.return_value = mock_response
        
        data = scrape_financial_data("005930")
        
        # Should populate data for available years
        self.assertTrue(len(data) >= 2)
        self.assertEqual(data[0]['year'], 2023)
        self.assertEqual(data[0]['value'], 1000.0)
        self.assertEqual(data[1]['year'], 2024)
        self.assertEqual(data[1]['value'], 2000.0)

if __name__ == '__main__':
    unittest.main()
