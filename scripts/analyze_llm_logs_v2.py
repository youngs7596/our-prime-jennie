import json
import statistics
from collections import Counter
import re

log_path = "/docker_data/llm_debug_logs/llm_interactions.jsonl"

def analyze_logs_v2():
    hunter_logs = []
    debate_logs = []
    judge_logs = []
    errors = []

    print(f"--- Analyzing V2 Logs: {log_path} ---")

    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                try:
                    entry = json.loads(line)
                    if entry['type'] == 'generate_json':
                        # 구분을 위해 request prompt 확인
                        prompt = entry.get('request', {}).get('prompt', '')
                        if "최종 판결자" in prompt:
                            judge_logs.append(entry)
                        else:
                            hunter_logs.append(entry)
                    elif entry['type'] == 'generate_chat':
                        debate_logs.append(entry)
                except Exception as e:
                    errors.append(f"Line {i+1}: {e}")
    except FileNotFoundError:
        print("Log file not found.")
        return

    print(f"Total Lines: {len(hunter_logs) + len(debate_logs) + len(judge_logs)}")
    print(f"Hunter Logs: {len(hunter_logs)}")
    print(f"Debate Logs: {len(debate_logs)}")
    print(f"Judge Logs: {len(judge_logs)}")

    # 1. Model Name Verification
    print("\n--- [Model Verification] ---")
    models = Counter()
    for log in hunter_logs + debate_logs + judge_logs:
        models[log.get('model', 'Unknown')] += 1
    print(f"Detected Models: {dict(models)}")

    # 2. Debate Grounding Check
    print("\n--- [Debate Grounding Check] ---")
    if debate_logs:
        tagged_count = 0
        total_len = 0
        hallucination_warning = 0
        
        for log in debate_logs:
            content = log['response'].get('content', '')
            total_len += len(content)
            # Check for tags like [뉴스], [정량], [펀더멘털]
            if re.search(r'\[.*?(뉴스|정량|펀더멘털|재무|공시).*?\]', content):
                tagged_count += 1
            
            # Check for specific hallucinated numbers (simple heuristic)
            if "RSI" in content and any(c.isdigit() for c in content.split("RSI")[1][:5]):
                # RSI 뒤에 숫자가 바로 따라오면 의심 (프롬프트에 없으면 창조한 것)
                pass 

        print(f"Avg Length: {total_len / len(debate_logs):.1f} chars")
        print(f"Entries with Source Tags: {tagged_count}/{len(debate_logs)} ({tagged_count/len(debate_logs)*100:.1f}%)")
    
    # 3. Judge Logic Check
    print("\n--- [Judge Logic Check] ---")
    if judge_logs:
        scores = []
        double_penalty_suspects = []
        
        for log in judge_logs:
            resp_content = log['response'].get('content', '')
            # Try parsing JSON (should be clean now)
            try:
                if isinstance(resp_content, str):
                    parsed = json.loads(resp_content)
                else:
                    parsed = resp_content # Already parsed?
                
                score = parsed.get('score')
                reason = parsed.get('reason', '')
                
                if score is not None: scores.append(float(score))
                
                # Check for double penalty keywords
                if "RSI" in reason and ("감점" in reason or "낮춤" in reason or "하락" in reason or "부정적" in reason):
                     double_penalty_suspects.append(reason)
                     
            except Exception as e:
                print(f"Judge Parse Error: {e}")

        if scores:
            print(f"Valid Judge Scores: {len(scores)}")
            print(f"Avg Score: {statistics.mean(scores):.2f}")
            print(f"Double Penalty Suspects: {len(double_penalty_suspects)}")
            if double_penalty_suspects:
                print(f"[Suspect Reason]: {double_penalty_suspects[0]}")
        else:
             print("No valid scores parsed.")

if __name__ == "__main__":
    analyze_logs_v2()
