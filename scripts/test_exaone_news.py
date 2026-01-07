#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
scripts/test_exaone_news.py
Test script to compare 'LG Exaone 3.5' vs 'GPT-OSS 20B' for Korean news sentiment analysis.
"""

import os
import sys
import json
import requests
import time
from datetime import datetime
import textwrap

# Ensure project root is in path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)

from bs4 import BeautifulSoup

# --- Configuration ---
TARGET_STOCK_CODE = "005930" # Samsung Electronics
TARGET_STOCK_NAME = "삼성전자"
OLLAMA_HOST = "http://localhost:11434"
MODELS = {
    "Baseline (GPT-OSS)": "gpt-oss:20b",
    "Challenger (Exaone)": "exaone3.5:7.8b" # Assuming this tag, will verify
}
OUTPUT_FILE = "test_exaone_results_output.txt"
NEWS_LIMIT = 5

# --- Helper Functions ---

def build_news_sentiment_prompt(news_title, news_summary):
    """(Copy from shared/llm_prompts.py)"""
    prompt = f"""
    [금융 뉴스 감성 분석]
    당신은 '금융 전문가'입니다. 아래 뉴스를 보고 해당 종목에 대한 호재/악재 여부를 점수로 판단해주세요.
    
    [중요] 반드시 한국어(Korean)로만 응답하세요. 영어로 출력하면 안 됩니다.
    
    - 뉴스 제목: {news_title}
    - 뉴스 내용: {news_summary}
    
    [채점 기준]
    - 80 ~ 100점 (강력 호재): 실적 서프라이즈, 대규모 수주, 신기술 개발, 인수합병, 배당 확대
    - 60 ~ 79점 (호재): 긍정적 전망 리포트, 목표가 상향
    - 40 ~ 59점 (중립): 단순 시황, 일반적인 소식, 이미 반영된 뉴스
    - 20 ~ 39점 (악재): 실적 부진, 목표가 하향
    - 0 ~ 19점 (강력 악재): 어닝 쇼크, 유상증자(악재성), 횡령/배임, 계약 해지, 규제 강화
    
    [출력 형식]
    JSON으로 응답: {{ "score": 점수(int), "reason": "판단 이유(한 문장, 한국어)" }}
    """
    return prompt.strip()

def crawl_naver_news_sample(code, limit=5):
    """Simple crawler for testing"""
    print(f"[*] Crawling Naver Finance news for {code}...")
    url = f"https://finance.naver.com/item/news_news.naver?code={code}&page=1"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': f'https://finance.naver.com/item/news.naver?code={code}'
    }
    
    try:
        resp = requests.get(url, headers=headers)
        resp.encoding = 'euc-kr'
        print(f"    - Status: {resp.status_code}")
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        news_table = soup.select_one('table.type5')
        
        if not news_table:
            print("    - No news table found.")
            return []

        news_items = []
        for row in news_table.select('tr'):
            title_td = row.select_one('td.title')
            if not title_td: continue
            
            link = title_td.select_one('a')
            if link:
                title = link.text.strip()
                href = link['href']
                if href.startswith('/'):
                    href = "https://finance.naver.com" + href
                    
                news_items.append({
                    "title": title,
                    "summary": title, 
                    "link": href
                })
                print(f"    - Found: {title[:20]}...")
                if len(news_items) >= limit:
                    break
        return news_items
    except Exception as e:
        print(f"[!] Naver Crawl failed: {e}")
        return []

def crawl_google_news_sample(code, name, limit=5):
    """Fallback: Google News RSS"""
    import feedparser
    import urllib.parse
    
    print(f"[*] Crawling Google News RSS for {name}({code})...")
    query = f'"{name}" OR "{code}"'
    encoded_query = urllib.parse.quote(query)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"
    
    try:
        feed = feedparser.parse(rss_url)
        news_items = []
        for entry in feed.entries[:limit]:
            news_items.append({
                "title": entry.title,
                "summary": entry.title,
                "link": entry.link
            })
            print(f"    - Found: {entry.title[:20]}...")
        return news_items
    except Exception as e:
        print(f"[!] Google Crawl failed: {e}")
        return []

def query_ollama(model, prompt):
    """Direct Ollama API call"""
    url = f"{OLLAMA_HOST}/api/generate"
    data = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_ctx": 2048
        }
    }
    try:
        start_t = time.time()
        resp = requests.post(url, json=data)
        duration = time.time() - start_t
        
        if resp.status_code == 200:
            result = resp.json()['response']
            return result, duration
        else:
            return f"Error: {resp.status_code} - {resp.text}", 0
    except Exception as e:
        return f"Exception: {e}", 0

# --- Main Execution ---

def main():
    print("=== LG Exaone vs GPT-OSS News Analysis Test ===")
    
    # 1. Fetch Data
    news_list = crawl_naver_news_sample(TARGET_STOCK_CODE, NEWS_LIMIT)
    if not news_list:
        print("Naver failed, trying Google News...")
        news_list = crawl_google_news_sample(TARGET_STOCK_CODE, TARGET_STOCK_NAME, NEWS_LIMIT)
        
    if not news_list:
        print("No news found from any source. Aborting.")
        return

    results_buffer = []
    results_buffer.append(f"Test Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    results_buffer.append(f"Target: {TARGET_STOCK_NAME} ({TARGET_STOCK_CODE})")
    results_buffer.append("="*60 + "\n")

    # 2. Run Tests
    for i, news in enumerate(news_list):
        print(f"\n[{i+1}/{len(news_list)}] Processing: {news['title'][:30]}...")
        
        item_block = f"### News {i+1}: {news['title']}\n"
        item_block += f"Link: {news['link']}\n"
        
        prompt = build_news_sentiment_prompt(news['title'], news['summary'])
        
        for model_label, model_name in MODELS.items():
            print(f"  - Querying {model_label} ({model_name})...")
            response_text, duration = query_ollama(model_name, prompt)
            
            # Clean up JSON markdown block code
            cleaned_resp = response_text.replace("```json", "").replace("```", "").strip()
            
            item_block += f"\n**[{model_label}]** ({duration:.2f}s)\n"
            item_block += f"- Raw Output: {cleaned_resp}\n"
            
            # Validation Check
            try:
                parsed = json.loads(cleaned_resp)
                score = parsed.get("score")
                reason = parsed.get("reason")
                item_block += f"- Status: ✅ Valid JSON (Score: {score})\n"
            except:
                item_block += f"- Status: ❌ Invalid JSON\n"
        
        item_block += "\n" + "-"*40 + "\n"
        results_buffer.append(item_block)

    # 3. Generate Review Prompt
    review_prompt = """
================================================================================
*** COPY BELOW FOR WEB GEMINI REVIEW ***
================================================================================

[Review Request: LG Exaone vs GPT-OSS Performance]

I have conducted a test to compare 'LG Exaone 3.5 (7.8B)' and 'GPT-OSS (20B)' on Korean financial news sentiment analysis.
Please review the raw outputs below and evaluate:

1. **Korean Nuance**: Which model understands the subtle context of Korean finance news better?
2. **Logic & Reasoning**: Is the score and reason aligned logically?
3. **JSON Adherence**: Did both models strictly follow JSON format?
4. **Recommendation**: Should we switch our 'LOCAL_MODEL_FAST' to LG Exaone?

[Test Data & Results]
"""
    full_content = "\n".join(results_buffer) + review_prompt + "\n".join(results_buffer) # Append results again for the prompt
    
    # 3. Save to File
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(results_buffer))
        f.write(review_prompt)
        # We append the results AGAIN after the prompt marker so the user can just copy the bottom part
        # Actually let's just write the whole thing clearly.
        f.write("\n(Paste the content above this line if needed, or see full log below)\n") 
        f.write("\n--- [Begin Raw Log for Review] ---\n")
        f.write("\n".join(results_buffer))

    print(f"\nDone! Results saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
