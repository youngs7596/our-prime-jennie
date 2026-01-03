#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
네이버 금융 종목 뉴스 크롤러 통합 테스트
실제 API 호출하여 crawl_naver_finance_news() 함수 검증
"""

import sys
import os

# 프로젝트 루트 추가
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'services', 'news-crawler'))

# 환경 변수 설정 (테스트용)
os.environ["NEWS_CRAWLER_SOURCE"] = "naver"
os.environ["NAVER_NEWS_MAX_PAGES"] = "1"

# crawler 모듈 직접 import
import crawler

def test_real_crawl():
    """실제 네이버 금융 API 호출 테스트"""
    print("="*60)
    print("네이버 금융 뉴스 크롤러 통합 테스트")
    print("="*60)
    
    # 테스트 종목
    test_stocks = [
        ("005930", "삼성전자"),
        ("000660", "SK하이닉스"),
    ]
    
    total_docs = []
    
    for stock_code, stock_name in test_stocks:
        print(f"\n[테스트] {stock_name}({stock_code})")
        docs = crawler.crawl_naver_finance_news(stock_code, stock_name, max_pages=1)
        print(f"  수집된 문서 수: {len(docs)}")
        
        if docs:
            # 첫 번째 문서 상세 출력
            doc = docs[0]
            print(f"  첫 번째 문서:")
            print(f"    - 제목: {doc.page_content.split(chr(10))[0][:60]}...")
            print(f"    - 소스: {doc.metadata.get('source')}")
            print(f"    - 링크: {doc.metadata.get('source_url')[:80]}...")
        
        total_docs.extend(docs)
    
    print("\n" + "="*60)
    print(f"총 수집 문서 수: {len(total_docs)}")
    print("="*60)
    
    if len(total_docs) > 0:
        print("\n✅ 네이버 금융 뉴스 크롤러 통합 테스트 성공!")
    else:
        print("\n⚠️ 문서 수집 실패 - 추가 확인 필요")
    
    return len(total_docs) > 0


if __name__ == "__main__":
    success = test_real_crawl()
    sys.exit(0 if success else 1)
