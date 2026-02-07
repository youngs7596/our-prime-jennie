"""
Unit tests for shared.crawlers.naver module
"""
import unittest
from unittest.mock import patch, MagicMock
from shared.crawlers.naver import (
    crawl_stock_news, get_kospi_top_stocks, scrape_financial_data, scrape_pbr_per_roe,
    get_naver_sector_list, get_naver_sector_stocks, build_naver_sector_mapping,
)

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

class TestNaverSectorCrawler(unittest.TestCase):
    """네이버 업종 크롤링 테스트"""

    @patch('shared.crawlers.naver.requests.get')
    def test_get_naver_sector_list(self, mock_get):
        """업종 목록 조회"""
        html_content = """
        <table class="type_1">
            <tr>
                <td><a href="/sise/sise_group_detail.naver?type=upjong&no=278">반도체와반도체장비</a></td>
                <td>150</td>
                <td>2.5%</td>
            </tr>
            <tr>
                <td><a href="/sise/sise_group_detail.naver?type=upjong&no=273">자동차</a></td>
                <td>100</td>
                <td>-1.0%</td>
            </tr>
        </table>
        """
        mock_response = MagicMock()
        mock_response.text = html_content
        mock_get.return_value = mock_response

        sectors = get_naver_sector_list()

        self.assertEqual(len(sectors), 2)
        self.assertEqual(sectors[0]['sector_no'], '278')
        self.assertEqual(sectors[0]['sector_name'], '반도체와반도체장비')
        self.assertAlmostEqual(sectors[0]['change_pct'], 2.5)
        self.assertEqual(sectors[1]['sector_no'], '273')
        self.assertEqual(sectors[1]['sector_name'], '자동차')

    @patch('shared.crawlers.naver.requests.get')
    def test_get_naver_sector_stocks(self, mock_get):
        """업종별 종목 목록 조회"""
        html_content = """
        <table class="type_5">
            <tr>
                <td><a href="/item/main.naver?code=005930">삼성전자</a></td>
                <td>80,000</td>
            </tr>
            <tr>
                <td><a href="/item/main.naver?code=000660">SK하이닉스</a></td>
                <td>150,000</td>
            </tr>
        </table>
        """
        mock_response = MagicMock()
        mock_response.text = html_content
        mock_get.return_value = mock_response

        stocks = get_naver_sector_stocks('278')

        self.assertEqual(len(stocks), 2)
        self.assertEqual(stocks[0]['code'], '005930')
        self.assertEqual(stocks[0]['name'], '삼성전자')
        self.assertEqual(stocks[1]['code'], '000660')
        self.assertEqual(stocks[1]['name'], 'SK하이닉스')

    @patch('shared.crawlers.naver.get_naver_sector_stocks')
    @patch('shared.crawlers.naver.get_naver_sector_list')
    def test_build_naver_sector_mapping(self, mock_list, mock_stocks):
        """전체 매핑 구축"""
        mock_list.return_value = [
            {'sector_no': '278', 'sector_name': '반도체와반도체장비', 'change_pct': 1.0},
            {'sector_no': '273', 'sector_name': '자동차', 'change_pct': -0.5},
        ]
        mock_stocks.side_effect = [
            [{'code': '005930', 'name': '삼성전자'}, {'code': '000660', 'name': 'SK하이닉스'}],
            [{'code': '005380', 'name': '현대차'}, {'code': '000270', 'name': '기아'}],
        ]

        mapping = build_naver_sector_mapping(request_delay=0)

        self.assertEqual(len(mapping), 4)
        self.assertEqual(mapping['005930'], '반도체와반도체장비')
        self.assertEqual(mapping['000660'], '반도체와반도체장비')
        self.assertEqual(mapping['005380'], '자동차')
        self.assertEqual(mapping['000270'], '자동차')

    @patch('shared.crawlers.naver.get_naver_sector_stocks')
    @patch('shared.crawlers.naver.get_naver_sector_list')
    def test_build_mapping_first_sector_wins(self, mock_list, mock_stocks):
        """중복 종목은 첫 업종이 우선"""
        mock_list.return_value = [
            {'sector_no': '1', 'sector_name': '업종A', 'change_pct': 0},
            {'sector_no': '2', 'sector_name': '업종B', 'change_pct': 0},
        ]
        mock_stocks.side_effect = [
            [{'code': '005930', 'name': '삼성전자'}],
            [{'code': '005930', 'name': '삼성전자'}],  # 중복
        ]

        mapping = build_naver_sector_mapping(request_delay=0)

        self.assertEqual(mapping['005930'], '업종A')  # 첫 업종 유지

    @patch('shared.crawlers.naver.requests.get')
    def test_get_sector_list_empty_on_error(self, mock_get):
        """에러 시 빈 리스트"""
        mock_get.side_effect = Exception("Network error")

        sectors = get_naver_sector_list()

        self.assertEqual(sectors, [])

    @patch('shared.crawlers.naver.get_naver_sector_list')
    def test_build_mapping_empty_on_no_sectors(self, mock_list):
        """업종 목록 없으면 빈 매핑"""
        mock_list.return_value = []

        mapping = build_naver_sector_mapping(request_delay=0)

        self.assertEqual(mapping, {})


class TestSectorTaxonomy(unittest.TestCase):
    """shared.sector_taxonomy 테스트"""

    def test_get_sector_group_known(self):
        """알려진 업종 대분류 변환"""
        from shared.sector_taxonomy import get_sector_group

        self.assertEqual(get_sector_group('반도체와반도체장비'), '반도체/IT')
        self.assertEqual(get_sector_group('자동차'), '자동차')
        self.assertEqual(get_sector_group('은행'), '금융')
        self.assertEqual(get_sector_group('제약'), '바이오')
        self.assertEqual(get_sector_group('조선'), '조선/방산')
        self.assertEqual(get_sector_group('화학'), '에너지/화학')

    def test_get_sector_group_unknown(self):
        """매핑 없는 업종은 원본 반환"""
        from shared.sector_taxonomy import get_sector_group

        self.assertEqual(get_sector_group('미지의업종'), '미지의업종')

    def test_naver_to_group_completeness(self):
        """NAVER_TO_GROUP에 주요 업종 포함 확인"""
        from shared.sector_taxonomy import NAVER_TO_GROUP

        expected_keys = [
            '반도체와반도체장비', '자동차', '자동차부품', '조선',
            '은행', '증권', '제약', '생물공학', '화학', '건설',
            '철강', '소프트웨어', '게임엔터테인먼트',
        ]
        for key in expected_keys:
            self.assertIn(key, NAVER_TO_GROUP, f"'{key}' not in NAVER_TO_GROUP")


if __name__ == '__main__':
    unittest.main()
