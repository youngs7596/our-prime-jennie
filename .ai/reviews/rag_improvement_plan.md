# RAG 검색 품질 개선 계획서

> Prime Council 리뷰 요청 문서
> 작성일: 2026-02-06

## 1. 현재 문제점 분석

### 1.1 page_content에 뉴스 제목만 저장 (Critical)

**현재 코드** (`shared/crawlers/naver.py:177`, `collector.py:122`):
```python
# 종목별 뉴스 (naver.py)
"page_content": f"뉴스 제목: {title}\n링크: {href}"

# 일반 RSS 뉴스 (collector.py)
"page_content": f"뉴스 제목: {title}\n링크: {link}"
```

**문제**:
- 시맨틱 검색의 핵심인 page_content가 뉴스 제목(1줄)과 URL로만 구성
- 임베딩 벡터가 제목 텍스트만 반영 → 검색 품질 근본적 한계
- 예: "삼성전자, 2분기 실적 발표" 제목만으로는 실적이 좋았는지 나빴는지 알 수 없음

### 1.2 하드코딩된 단일 검색 쿼리 (High)

**Scout 종목별 뉴스 검색** (`scout.py:326`):
```python
docs = vectorstore.similarity_search(
    query=f"{stock_name} 실적 수주 호재",  # 항상 같은 쿼리
    k=k,
    filter={"$and": [
        {"stock_code": stock_code},
        {"created_at_utc": {"$gte": recency_timestamp}}
    ]}
)
```

**Scout RAG 후보 발굴** (`scout.py:547`):
```python
rag_results = vectorstore.similarity_search(
    query="실적 호재 계약 수주",  # 항상 같은 쿼리
    k=50
)
```

**문제**:
- "실적 수주 호재" 단일 쿼리로 모든 종목의 뉴스를 검색
- 기술주, 바이오, 금융 등 섹터별 중요 키워드가 다름
- 부정적 뉴스(리스크)를 놓침 → 리스크 관리 실패

### 1.3 RAG 후보 발굴의 낮은 정밀도 (Medium)

- `k=50`으로 대량 검색하지만, 중복 종목이 많아 실질적 다양성 낮음
- stock_code 필터 없이 검색하여 잡음(noise) 문서 다수 포함
- created_at_utc 필터 없어 오래된 뉴스도 혼입

## 2. 개선 방안

### Phase 1: page_content 보강 (뉴스 본문 크롤링)

**목표**: 뉴스 본문(또는 요약)을 page_content에 포함하여 임베딩 품질 향상

**방안 A: 뉴스 본문 직접 크롤링** (권장)
- `crawl_stock_news()`에서 각 뉴스 링크를 따라가 본문 텍스트 추출
- Naver 뉴스 본문은 `<div id="news_read">` 또는 `<div class="articleCont">` 등에 위치
- page_content = f"제목: {title}\n본문: {body_text[:500]}"
- **장점**: 시맨틱 검색 품질 대폭 향상
- **단점**: 크롤링 시간 증가 (요청 수 2~3배), 네이버 rate limit 리스크
- **완화**: ThreadPoolExecutor 활용, request_delay 조정, 본문 500자 제한

**방안 B: LLM 요약 후 저장**
- 뉴스 제목 배치로 LLM(FAST tier)에 요약 요청
- page_content에 요약 텍스트 포함
- **장점**: 정제된 텍스트
- **단점**: LLM 비용 발생, 아키버 처리 속도 저하

**방안 C: 메타데이터 강화 (최소 변경)**
- page_content에 종목명, 섹터, 날짜 등 메타데이터를 텍스트로 병합
- page_content = f"[{stock_name}({stock_code})] {title} | 출처: {source} | 날짜: {date}"
- **장점**: 구현 간단, 기존 크롤링 로직 변경 없음
- **단점**: 본문 없이는 근본적 개선 한계

### Phase 2: 다중 쿼리 검색 전략

**목표**: 종목별로 다양한 관점의 뉴스를 검색하여 분석 품질 향상

**구현 방안**:
```python
def _generate_search_queries(stock_name: str, stock_code: str, sector: str = None) -> list:
    """종목별 다중 검색 쿼리 생성"""
    queries = [
        f"{stock_name} 실적 매출 영업이익",      # 실적 관련
        f"{stock_name} 신규 수주 계약 사업",      # 사업 확장
        f"{stock_name} 리스크 하락 우려 소송",    # 리스크 요인
    ]

    # 섹터별 추가 쿼리
    sector_queries = {
        "반도체": f"{stock_name} 반도체 AI HBM 수요",
        "바이오": f"{stock_name} 임상 FDA 신약 승인",
        "2차전지": f"{stock_name} 배터리 전기차 수주",
        "금융": f"{stock_name} 실적 배당 이자수익",
    }
    if sector and sector in sector_queries:
        queries.append(sector_queries[sector])

    return queries
```

**적용 위치**:
1. `_search_news_for_stock()` (L325): 종목별 뉴스 검색 시 다중 쿼리 → 결과 병합 & 중복 제거
2. `gather_candidate_stocks()` (L547): RAG 후보 발굴 시 다중 쿼리

### Phase 3: RAG 후보 발굴 개선

**목표**: RAG 기반 후보 발굴의 정밀도 향상

**구현 방안**:
```python
# 현재: 단일 쿼리로 50개 검색
rag_results = vectorstore.similarity_search(query="실적 호재 계약 수주", k=50)

# 개선: 다중 쿼리 + 날짜 필터 + 결과 병합
rag_queries = [
    "실적 개선 매출 성장 영업이익 흑자전환",
    "신규 수주 대규모 계약 공급 체결",
    "신사업 진출 인수합병 전략적 투자",
    "배당 증가 자사주 매입 주주환원",
]

seen_codes = set()
for query in rag_queries:
    results = vectorstore.similarity_search(
        query=query,
        k=20,
        filter={"created_at_utc": {"$gte": recency_timestamp}}
    )
    for doc in results:
        stock_code = doc.metadata.get('stock_code')
        if stock_code and stock_code not in seen_codes:
            seen_codes.add(stock_code)
            # 후보에 추가
```

## 3. 구현 우선순위

| 순서 | 작업 | 영향도 | 난이도 | 예상 시간 |
|------|------|--------|--------|-----------|
| 1 | Phase 2: 다중 쿼리 검색 | 높음 | 낮음 | 30분 |
| 2 | Phase 1C: 메타데이터 강화 | 중간 | 낮음 | 20분 |
| 3 | Phase 3: RAG 후보 발굴 개선 | 중간 | 낮음 | 30분 |
| 4 | Phase 1A: 뉴스 본문 크롤링 | 매우 높음 | 중간 | 2시간 |

**Phase 1A (본문 크롤링)의 고려사항**:
- 네이버 뉴스 본문 구조가 다양 (네이버 뉴스, 언론사 직접 링크 등)
- 크롤링 시간 증가로 수집 주기에 영향
- 기존 저장된 뉴스는 재크롤링 필요 (마이그레이션 비용)
- Rate limit: 200종목 × 2페이지 × 10뉴스 = 4000 요청 → 본문 크롤링 시 8000 요청

## 4. 리뷰 요청 사항

Council에게 다음 사항에 대한 의견을 요청합니다:

1. **Phase 1 방안 선택**: A(본문 크롤링) vs B(LLM 요약) vs C(메타데이터 강화) 중 어떤 방안이 최적인가?
2. **구현 우선순위**: 위 순서가 적절한가?
3. **네이버 크롤링 리스크**: 본문 크롤링 시 rate limit/IP 차단 대응 전략은?
4. **임베딩 모델**: 현재 kure-v1 (1024차원) 모델이 한국어 뉴스 검색에 적합한가?
5. **추가 개선 포인트**: 놓치고 있는 개선점이 있는가?
