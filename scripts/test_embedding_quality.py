import requests
import numpy as np
import json
import os

# Configuration
OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
# WSL/Linux Localhost adjustment
if OLLAMA_URL == "http://host.docker.internal:11434":
    # Try localhost if running directly on host or checks
    if os.system("curl -s http://localhost:11434/api/tags > /dev/null") == 0:
        OLLAMA_URL = "http://localhost:11434"

MODEL_NAME = "daynice/kure-v1"

def get_embedding(text):
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={"model": MODEL_NAME, "prompt": text},
            timeout=10
        )
        if response.status_code != 200:
            print(f"Error {response.status_code}: {response.text}")
        response.raise_for_status()
        return response.json()["embedding"]
    except Exception as e:
        print(f"Error getting embedding for '{text}': {e}")
        return None

def cosine_similarity(v1, v2):
    return np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))

def run_test():
    print(f"🧪 Testing Embedding Model: {MODEL_NAME}")
    print(f"📡 Connecting to: {OLLAMA_URL}")

    query = "삼성전자 주가 전망"
    documents = [
        "반도체 업황 개선 기대감에 외국인 매수세 유입",  # Highly Relevant
        "삼성전자, 차세대 HBM 메모리 양산 시작",        # Relevant
        "오늘 점심 메뉴는 김치찌개와 계란말이",          # Irrelevant
        "주말 서울 날씨는 맑고 포근할 예정"             # Irrelevant
    ]

    print(f"\n🔍 Query: '{query}'")
    print("-" * 50)

    query_vec = get_embedding(query)
    if not query_vec:
        print("❌ Failed to get query embedding. Is Ollama running and model pulled?")
        return

    for doc in documents:
        doc_vec = get_embedding(doc)
        if doc_vec:
            score = cosine_similarity(query_vec, doc_vec)
            print(f"📄 Doc: '{doc}'")
            print(f"   📊 Similarity: {score:.4f}")
    
    print("-" * 50)
    print("✅ Test Complete")

if __name__ == "__main__":
    run_test()
