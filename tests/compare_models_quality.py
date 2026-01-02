
import json
import logging
import os
from shared.llm_factory import LLMFactory, LLMTier
from shared.llm_providers import OllamaLLMProvider
from shared.llm_constants import ANALYSIS_RESPONSE_SCHEMA

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Real News Data (Fetched 2026-01-02 via Search) ---
REAL_NEWS_ITEMS = [
    {
        "id": "SAMSUNG_001",
        "stock_name": "삼성전자",
        "title": "삼성전자, 4분기 영업이익 20조원 전망... 사상 최고가 경신",
        "summary": """삼성전자 주가는 최근 반도체 슈퍼 사이클에 대한 기대감과 인공지능(AI) 반도체 수요 증가에 힘입어 사상 최고가를 경신하는 등 긍정적인 흐름을 보이고 있습니다.
        
[주요 내용]
1. 애널리스트 투자의견 및 목표주가:
   - 대부분의 증권사들은 삼성전자에 대해 "적극 매수" 또는 "매수" 의견을 제시하고 있습니다.
   - 2025년 12월 30일 기준, 35명의 애널리스트가 제시한 삼성전자의 12개월 평균 목표주가는 약 137,232원이며, 최고 목표주가는 175,000원입니다.
   - 다올투자증권은 목표주가를 16만원으로, IBK투자증권은 15만 5천원으로 상향했습니다.

2. 최근 주가 동향:
   - 2025년 12월 26일 전 거래일 대비 5.31% 상승한 11만 7천 원에 거래를 마감하며 사상 최고가를 기록했습니다.

3. 실적 전망 및 상승 요인:
   - 2025년 4분기 영업이익이 시장 예상치(컨센서스 16조 원)를 크게 상회하는 20조 4천억 원에 달할 것으로 전망됩니다.
   - 2026년 연간 영업이익은 100조 원을 넘어설 것이라는 전망도 나옵니다.
   - 이는 범용 D램 및 낸드 가격의 큰 폭 상승과 HBM 출하량 증가에 기인합니다.

4. 향후 전망:
   - 메모리 반도체 업종은 2025년 4분기를 기점으로 분위기 전환에 진입하여 연초부터 주가 재평가가 이루어질 것으로 예상됩니다.
   - 2026년 말까지 메모리 가격 상승세가 이어질 것으로 보입니다.
"""
    },
    {
        "id": "SKHYNIX_001",
        "stock_name": "SK하이닉스",
        "title": "SK하이닉스, 2026년 영업이익 100조원 시대 예고... 목표가 줄상향",
        "summary": """SK하이닉스는 2026년 새해 첫 거래일부터 장중 신고가를 경신하는 등 긍정적인 주가 흐름을 보이고 있으며, 여러 증권사로부터 목표주가 상향과 함께 '매수' 투자의견을 받고 있습니다.

[주요 내용]
1. 주가 전망 및 목표주가 상향:
   - 국내외 증권사들은 SK하이닉스의 2026년 실적 전망치를 큰 폭으로 상향 조정하며 목표주가를 높이고 있습니다.
   - IBK투자증권은 목표주가를 86만원으로, 대신증권은 84만원으로, 다올투자증권은 95만원으로 상향했습니다.

2. 메모리 슈퍼사이클 및 AI 투자 확대 수혜:
   - 증권가에서는 '메모리 슈퍼사이클' 도래에 대한 기대감이 커지고 있습니다.
   - 인공지능(AI) 투자 확대와 고대역폭 메모리(HBM) 수요 증가가 주가 상승을 견인하는 핵심 요인입니다.
   - 특히 HBM 시장에서의 기술 우위와 시장 협상력을 바탕으로 성장세를 이어갈 것으로 전망됩니다.

3. 기록적인 실적 전망:
   - 2026년에는 사상 최초로 영업이익 100조원 시대를 열 것으로 예상됩니다.
   - HBM 출하량이 2025년 대비 54% 성장할 것으로 보이며, 낸드 부문도 흑자 전환이 기대됩니다.

4. 경영진의 비전:
   - 곽노정 사장은 신년사를 통해 2025년을 역대 최고의 성과를 달성한 해로 평가하고, "AI는 상수가 됐다"며 선행 기술 개발의 중요성을 강조했습니다.
"""
    },
    {
        "id": "HYUNDAI_001",
        "stock_name": "현대차",
        "title": "현대차, 2025년 역대 최대 매출 전망에도 영업이익 감소 우려",
        "summary": """현대자동차는 2025년에 역대 최대 매출을 달성할 것으로 예상되지만, 미국 관세 부담, 원자재 가격 상승 등으로 인해 영업이익은 감소할 것으로 전망됩니다. 하지만 2026년에는 실적 반등을 기대하고 있습니다.

[주요 내용]
1. 2025년 실적 전망:
   - 매출: 2025년 연간 매출은 사상 최대치인 188조원을 기록할 것으로 예상됩니다.
   - 영업이익: 미국 관세 비용 증가(약 4.6조원 추산) 등으로 전년 대비 11.3% 감소한 12조 6천억원 수준이 예상됩니다.
   - 4분기에는 관세 부담이 일부 해소되며 전년 동기 대비 소폭 증가한 2.8조원의 영업이익이 예상됩니다.

2. 2026년 실적 전망 및 성장 전략:
   - 실적 반등 기대: 신차 효과, 모빌리티 사업 재편을 바탕으로 반등이 기대됩니다.
   - 미국 관세 완화: 한미 무역협정 타결 시 2026년 실적 개선에 긍정적입니다.
   - 신차 슈퍼사이클: 2026년에 제네시스 포함 9종의 신차가 출시될 예정입니다.
   - 하이브리드차 판매 호조: 미국 시장 하이브리드 수요 증가가 실적을 견인할 것입니다.

3. 미래 모빌리티 전환:
   - SDV(소프트웨어 중심 자동차), 로보틱스, AI 분야 투자를 통해 기업가치 재평가를 노리고 있습니다.
   - 2030년까지 국내 125조원 투자 계획을 발표했습니다.
"""
    }
]

def build_prompt(item):
    return f"""
    [금융 뉴스 감성 분석]
    당신은 '금융 전문가'입니다. 아래 뉴스를 보고 해당 종목에 대한 호재/악재 여부를 점수로 판단해주세요.
    
    [중요] **반드시 한국어(Korean)로만 응답하세요.** 영어로 답변하면 안 됩니다.
    
    - 종목명: {item['stock_name']}
    - 뉴스 제목: {item['title']}
    - 뉴스 내용: {item['summary']}
    
    [채점 기준]
    - 80 ~ 100점 (강력 호재): 실적 서프라이즈, 대규모 수주, 목표가 상향
    - 60 ~ 79점 (호재): 긍정적 전망, 신고가 경신
    - 40 ~ 59점 (중립): 단순 시황, 긍정과 부정 혼재, 이미 반영된 뉴스
    - 20 ~ 39점 (악재): 실적 부진, 목표가 하향
    - 0 ~ 19점 (강력 악재): 어닝 쇼크, 대규모 손실
    
    [출력 형식]
    JSON으로 응답: {{ "score": 점수(int), "reason": "한 문장 요약 (한국어)" }}
    """

def run_comparison():
    output_file = "news_sentiment_comparison_optimized.txt"
    logger.info("Initializing Models...")
    
    # 1. Gemma3 (Baseline)
    try:
        model_a = OllamaLLMProvider(
            model="gemma3:27b",
            state_manager=LLMFactory._state_manager,
            is_fast_tier=True
        )
        logger.info("Model A Loaded: gemma3:27b")
    except Exception as e:
        logger.error(f"Failed to load Model A: {e}")
        return

    # 2. GPT-OSS (Candidate)
    try:
        model_b = OllamaLLMProvider(
            model="gpt-oss:20b",
            state_manager=LLMFactory._state_manager,
            is_fast_tier=True
        )
        logger.info("Model B Loaded: gpt-oss:20b")
    except Exception as e:
        logger.error(f"Failed to load Model B: {e}")
        return

    logger.info(f"Starting comparison on {len(REAL_NEWS_ITEMS)} items...")
    
    results = []
    
    for item in REAL_NEWS_ITEMS:
        logger.info(f"Processing: {item['stock_name']}")
        prompt = build_prompt(item)
        
        # Run A
        res_a = {"score": -1, "reason": "Error"}
        try:
            res_a = model_a.generate_json(prompt, ANALYSIS_RESPONSE_SCHEMA, temperature=0.0)
        except Exception as e:
            logger.error(f"Model A Error: {e}")
            res_a["reason"] = str(e)

        # Run B
        res_b = {"score": -1, "reason": "Error"}
        try:
            res_b = model_b.generate_json(prompt, ANALYSIS_RESPONSE_SCHEMA, temperature=0.0)
        except Exception as e:
            logger.error(f"Model B Error: {e}")
            res_b["reason"] = str(e)
            
        results.append({
            "news": item,
            "result_a": res_a,
            "result_b": res_b
        })

    # Generate Report File
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("========================================================\n")
        f.write("       LLM Sentiment Analysis Quality Comparison        \n")
        f.write("========================================================\n")
        f.write("Model A: gemma3:27b (Baseline)\n")
        f.write("Model B: gpt-oss:20b (Candidate - Faster)\n\n")
        
        for idx, r in enumerate(results, 1):
            news = r['news']
            a = r['result_a']
            b = r['result_b']
            
            f.write(f"[{idx}] 종목: {news['stock_name']}\n")
            f.write(f"제목: {news['title']}\n")
            f.write("-" * 60 + "\n")
            f.write(f"[Model A - Gemma3] Score: {a.get('score')} | Reason: {a.get('reason')}\n")
            f.write(f"[Model B - GPT-OSS] Score: {b.get('score')} | Reason: {b.get('reason')}\n")
            f.write("-" * 60 + "\n")
            f.write(f"원본 내용 요약:\n{news['summary'][:300]}...\n")
            f.write("=" * 60 + "\n\n")

    logger.info(f"Comparison complete. Report saved to {output_file}")
    print(f"Report generated: {output_file}")

if __name__ == "__main__":
    run_comparison()
