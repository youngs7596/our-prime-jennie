import sys
import os

# Create shared directory mock if needed, but we are in project root
sys.path.append(os.getcwd())

from shared.llm_prompts import build_hunter_prompt_v5, build_judge_prompt_v5, build_buy_prompt_ranking

def test_feedback_injection():
    print("Testing Feedback Injection...")
    
    # Feedback Context
    feedback = "- Avoid buying Bio stocks when RSI > 70 in Bear Market."
    
    # 1. Test Hunter Prompt
    hunter_prompt = build_hunter_prompt_v5(
        stock_info={'name': 'TestStock', 'code': '000660'}, 
        quant_context="Quant Score: 80", 
        feedback_context=feedback
    )
    if feedback in hunter_prompt and "[Strategic Feedback (Lessons Learned)]" in hunter_prompt:
        print("[Pass] Hunter Prompt contains feedback.")
    else:
        print("[Fail] Hunter Prompt missing feedback.")
        print(hunter_prompt[:500])

    # 2. Test Judge Prompt
    judge_prompt = build_judge_prompt_v5(
        stock_info={'name': 'TestStock', 'hunter_score': 60}, 
        debate_log="Bull: Good. Bear: Bad.", 
        quant_context="Quant Score: 80",
        feedback_context=feedback
    )
    if feedback in judge_prompt and "[Analyst Feedback (Past Mistakes)]" in judge_prompt:
        print("[Pass] Judge Prompt contains feedback.")
    else:
        print("[Fail] Judge Prompt missing feedback.")
        print(judge_prompt[:500])

    # 3. Test Ranking Prompt
    ranking_prompt = build_buy_prompt_ranking(
        candidates_data=[
            {
                'stock_name': 'Test1', 'stock_code': '001', 
                'factors': {}, 'rag_context': '', 
                'stock_info': {}, 'factor_score': 100, 'buy_signal_type': 'TEST', 'current_price': 1000
            }
        ],
        feedback_context=feedback
    )
    if feedback in ranking_prompt and "[Strategic Guidelines (from Analyst)]" in ranking_prompt:
        print("[Pass] Ranking Prompt contains feedback.")
    else:
        print("[Fail] Ranking Prompt missing feedback.")
        print(ranking_prompt[:500])

if __name__ == "__main__":
    test_feedback_injection()
