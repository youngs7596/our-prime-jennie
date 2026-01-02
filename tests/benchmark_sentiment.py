
import time
import json
import logging
import concurrent.futures
from typing import List, Dict
import random
from shared.llm_factory import LLMFactory, LLMTier
from shared.llm_constants import ANALYSIS_RESPONSE_SCHEMA

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Mock Data ---
SAMPLE_HEADLINES = [
    ("삼성전자, 4분기 영업이익 10조원 돌파 전망", "반도체 업황 회복에 따른 실적 개선 기대감 고조"),
    ("SK하이닉스, HBM3E 양산 개시... 엔비디아 공급", "AI 반도체 수요 폭증에 대응, 주가 상승 모멘텀"),
    ("LG에너지솔루션, 북미 배터리 공장 증설 보류", "전기차 수요 둔화 우려에 투자 속도 조절"),
    ("현대차, 역대 최고 실적 달성... 주주환원 확대", "고부가가치 차량 판매 호조, 배당 성향 상향"),
    ("네이버, 생성형 AI '하이퍼클로바X' B2B 시장 공략", "기업용 솔루션 출시로 수익화 본격화"),
    ("카카오, 경영진 사법 리스크 확산... 주가 급락", "SM엔터 인수 관련 시세 조종 의혹 수사 가속화"),
    ("포스코홀딩스, 리튬 가격 하락에 실적 부진 우려", "2차전지 소재 부문 수익성 악화 전망"),
    ("KB금융, 홍콩 ELS 배상안 확정... 불확실성 해소", "일회성 비용 발생하지만 장기적 리스크 완화"),
    ("셀트리온, 짐펜트라 미국 처방목록 등재 성공", "미국 시장 점유율 확대 기대감에 강세"),
    ("에코프로비엠, 코스피 이전 상장 추진", "주주 가치 제고 및 자금 조달 용이성 확보 목적"),
]


def generate_mock_news(count=100) -> List[Dict]:
    """Generates a list of mock news items with LONG context (~2000 chars)."""
    # 500 chars of dummy text
    DUMMY_TEXT = " ".join(["금융 시장의 불확실성이 지속되는 가운데, 투자자들의 이목이 집중되고 있다." for _ in range(10)])
    
    news_items = []
    for i in range(count):
        title, summary = random.choice(SAMPLE_HEADLINES)
        
        # Make it long: Summary + 4x Dummy Text (~2000 chars total)
        long_body = f"{summary}\n\n[상세 내용]\n" + (DUMMY_TEXT + "\n") * 4
        
        suffix = f" [{random.randint(1000, 9999)}]"
        news_items.append({
            "id": i,
            "title": title + suffix,
            "summary": long_body # Injecting long body into summary field
        })
    return news_items


# --- Prompt Builders ---
def build_single_prompt(title, summary):
    return f"""
    [금융 뉴스 감성 분석]
    당신은 '금융 전문가'입니다. 아래 뉴스를 보고 해당 종목에 대한 호재/악재 여부를 점수로 판단해주세요.
    
    - 뉴스 제목: {title}
    - 뉴스 내용: {summary}
    
    [채점 기준]
    - 80 ~ 100점 (강력 호재): 실적 서프라이즈, 대규모 수주
    - 60 ~ 79점 (호재): 긍정적 전망
    - 40 ~ 59점 (중립): 단순 시황
    - 20 ~ 39점 (악재): 실적 부진
    - 0 ~ 19점 (강력 악재): 악재성 이슈
    
    [출력 형식]
    JSON으로 응답: {{ "score": 점수(int), "reason": "판단 이유" }}
    """

def build_batched_prompt(items: List[Dict]):
    items_text = ""
    for item in items:
        items_text += f"""
        [ID: {item['id']}]
        - 제목: {item['title']}
        - 내용: {item['summary']}
        """
        
    return f"""
    [금융 뉴스 다건 감성 분석]
    당신은 '금융 전문가'입니다. 아래 {len(items)}개의 뉴스를 각각 분석하여 호재/악재 점수를 매기세요.
    
    {items_text}
    
    [채점 기준]
    - 80 ~ 100점: 강력 호재
    - 60 ~ 79점: 호재
    - 40 ~ 59점: 중립
    - 20 ~ 39점: 악재
    - 0 ~ 19점: 강력 악재
    
    [출력 형식]
    반드시 아래와 같은 JSON 객체로 응답하세요. ID는 입력된 것과 일치해야 합니다.
    {{
        "results": [
            {{ "id": 0, "score": 85, "reason": "..." }},
            {{ "id": 1, "score": 30, "reason": "..." }},
            ...
        ]
    }}
    """

# --- Runners ---

def run_baseline_single_item(provider, item):
    """Process a single item (Baseline)"""
    try:
        prompt = build_single_prompt(item['title'], item['summary'])
        result = provider.generate_json(prompt, ANALYSIS_RESPONSE_SCHEMA, temperature=0.0)
        return 1
    except Exception as e:
        logger.error(f"Error processing item {item['id']}: {e}")
        return 0

def run_batched_items(provider, batch_items):
    """Process a batch of items"""
    try:
        prompt = build_batched_prompt(batch_items)
        # Using generate_text and parsing manually since schema enforcement for list might be tricky with generate_json depending on implementation
        # Actually, let's try generate_json with a list schema if possible, or just text.
        # Most providers expect an object schema. Let's ask for an object containing a list.
        
        BATCH_SCHEMA = {
            "type": "object",
            "properties": {
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "score": {"type": "integer"},
                            "reason": {"type": "string"}
                        },
                        "required": ["id", "score", "reason"]
                    }
                }
            },
            "required": ["results"]
        }
        
        result = provider.generate_json(prompt, BATCH_SCHEMA, temperature=0.0)
        return len(result.get('results', []))
    except Exception as e:
        logger.error(f"Error processing batch: {e}")
        return 0


# --- Benchmark Orchestrator ---

def run_benchmark():
    logger.info("Starting Benchmark for Local LLM Sentiment Analysis...")
    
    # Initialize Provider (FAST Tier -> Ollama)
    try:
        # LLMFactory now returns gpt-oss:20b for FAST tier
        provider = LLMFactory.get_provider(LLMTier.FAST)
        logger.info(f"Loaded Provider: {provider.name} (Model: {getattr(provider, 'model', 'Unknown')})")
    except Exception as e:
        logger.error(f"Failed to load provider: {e}")
        return


    # Generate Data
    TOTAL_ITEMS = 10 # FAST TEST: Reduced from 50 to 10
    news_data = generate_mock_news(TOTAL_ITEMS)
    logger.info(f"Generated {TOTAL_ITEMS} mock news items.")

    # Check connection
    try:
        logger.info("Checking connection...")
        # Use first item from generated data
        run_baseline_single_item(provider, news_data[0])
        logger.info("Connection OK.")
    except Exception as e:
        logger.error(f"Connection failed: {e}")
        return


    results = []

    # 1. Baseline: Single Item Parallel
    worker_counts = [1, 5, 10]
    
    for workers in worker_counts:
        logger.info(f"Testing Baseline (Workers={workers})...")
        start_time = time.time()
        completed = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(run_baseline_single_item, provider, item) for item in news_data]
            for future in concurrent.futures.as_completed(futures):
                completed += future.result()
        
        duration = time.time() - start_time
        throughput = completed / duration
        logger.info(f"-> Baseline (Workers={workers}): {duration:.2f}s ({throughput:.2f} items/sec)")
        results.append({
            "Mode": "Baseline (Single)",
            "Workers": workers,
            "BatchSize": 1,
            "Time": duration,
            "Throughput": throughput
        })

    # 2. Batched Parallel
    batch_sizes = [5, 10]
    # For batching, reduce workers to avoid OOM or overload since each context is larger
    batch_worker_counts = [1, 3] 

    for batch_size in batch_sizes:
        for workers in batch_worker_counts:
            logger.info(f"Testing Batched (Batch={batch_size}, Workers={workers})...")
            
            # Prepare batches
            batches = [news_data[i:i + batch_size] for i in range(0, len(news_data), batch_size)]
            
            start_time = time.time()
            completed = 0
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [executor.submit(run_batched_items, provider, batch) for batch in batches]
                for future in concurrent.futures.as_completed(futures):
                    completed += future.result()
            
            duration = time.time() - start_time
            throughput = completed / duration
            logger.info(f"-> Batched (Batch={batch_size}, Workers={workers}): {duration:.2f}s ({throughput:.2f} items/sec)")
            results.append({
                "Mode": "Batched",
                "Workers": workers,
                "BatchSize": batch_size,
                "Time": duration,
                "Throughput": throughput
            })

    # Print Summary Table
    print("\n\n" + "="*60)
    print(f"{'Mode':<20} | {'Workers':<8} | {'Batch':<6} | {'Time(s)':<8} | {'Item/s':<8}")
    print("-" * 60)
    for r in sorted(results, key=lambda x: x['Throughput'], reverse=True):
        print(f"{r['Mode']:<20} | {r['Workers']:<8} | {r['BatchSize']:<6} | {r['Time']:.2f}     | {r['Throughput']:.2f}")
    print("="*60 + "\n")

if __name__ == "__main__":
    run_benchmark()
