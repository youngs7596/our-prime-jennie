# shared/crawlers/__init__.py
"""
Naver Finance 크롤러 패키지
"""

from .naver import (
    # 공통 상수
    NAVER_HEADERS,
    NOISE_KEYWORDS,
    
    # 뉴스 크롤링
    crawl_stock_news,
    
    # 시총 상위 종목
    get_kospi_top_stocks,
    get_kosdaq_top_stocks,
    
    # 재무제표
    scrape_financial_data,
    scrape_pbr_per_roe,
)

__all__ = [
    'NAVER_HEADERS',
    'NOISE_KEYWORDS',
    'crawl_stock_news',
    'get_kospi_top_stocks',
    'get_kosdaq_top_stocks',
    'scrape_financial_data',
    'scrape_pbr_per_roe',
]
