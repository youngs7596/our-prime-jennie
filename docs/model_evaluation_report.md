# LLM Comparative Evaluation Request: Financial Sentiment Analysis

**To the Evaluator:**
Values "Model A" and "Model B" below represent two different local LLMs being tested for a Korean financial news sentiment analysis agent.
Please evaluate their performance based on the **Original News** provided for each case.

## 🟢 Models Under Test
- **Model A**: `gemma3:27b` (Baseline) - 27B Parameters
- **Model B**: `gpt-oss:20b` (Candidate) - 20B Parameters (Faster)

## 🎯 Evaluation Criteria
1.  **Accuracy (Score)**: Does the score (0-100) accurately reflect the sentiment of the news text?
2.  **Reasoning (Logic)**: Is the reasoning sound, grounded in the text, and logical?
3.  **Language (Korean)**: Is the output in natural, correct Korean? (Critical requirement)
4.  **Alignment**: Does the model follow the "Financial Expert" persona?

---

## 📂 Test Cases

### Case 1: Samsung Electronics (삼성전자)
**Original News Summary**:
> 삼성전자 주가는 최근 반도체 슈퍼 사이클에 대한 기대감과 AI 반도체 수요 증가에 힘입어 사상 최고가를 경신했습니다. 2025년 4분기 영업이익은 컨센서스를 상회하는 20조원, 2026년은 100조원을 돌파할 것으로 전망됩니다. 다수의 증권사가 "적극 매수" 의견과 목표주가 상향을 제시했습니다.

**Model A Output**:
- **Score**: 75
- **Reason**: "사상 최고가 경신, 4분기 영업이익 서프라이즈 전망, 증권사 목표가 상향 등 긍정적인 요인이 많아 호재로 판단되지만, 향후 가격 상승세 지속 여부에 대한 불확실성이 존재하여 강력 호재보다는 호재로 평가합니다."

**Model B Output**:
- **Score**: 90
- **Reason**: "삼성전자의 실적 서프라이즈와 목표가 상향, 사상 최고가 기록으로 강력 호재"

---

### Case 2: SK Hynix (SK하이닉스)
**Original News Summary**:
> SK하이닉스는 2026년 영업이익 100조원 시대를 예고하며 목표주가가 상향되고 있습니다. 메모리 슈퍼사이클 및 AI/HBM 투자 확대의 핵심 수혜주로 꼽히며, 2025년 대비 HBM 출하량이 54% 성장할 것으로 보입니다.

**Model A Output**:
- **Score**: 85
- **Reason**: "SK하이닉스는 2026년 100조원 영업이익을 예고하며 증권사들의 목표가 상향 및 매수 투자의견을 받고 있고, 메모리 슈퍼사이클과 AI 투자 확대의 수혜가 예상되어 강력 호재로 판단됩니다."

**Model B Output**:
- **Score**: 90
- **Reason**: "SK하이닉스의 2026년 실적 전망과 목표가 상향, 메모리 슈퍼사이클·AI 수혜가 강력 호재로 평가됩니다."

---

### Case 3: Hyundai Motor (현대차)
**Original News Summary**:
> 현대차는 2025년 역대 최대 매출이 예상되지만, 미국 관세 부담과 원자재 가격 상승으로 영업이익은 11.3% 감소할 것으로 우려됩니다. 그러나 2026년에는 신차 슈퍼사이클과 하이브리드 판매 호조로 실적 반등이 기대됩니다.

**Model A Output**:
- **Score**: 55
- **Reason**: "2025년 매출은 증가하지만 영업이익 감소 우려가 있고, 2026년 반등 기대감이 있어 긍정과 부정적인 요소가 혼재된 중립적인 뉴스입니다."

**Model B Output**:
- **Score**: 65
- **Reason**: "2025 매출 사상 최대치와 2026년 실적 반등 기대가 긍정적이지만, 2025 영업이익 감소는 부정적 요인으로 중립적이면서도 약간 호재에 기울어짐"

---

## ❓ Final Question to Evaluator
Based on the 3 cases above, please answer:
1.  **Which model provided better reasoning?** (Consider the Hyundai case specifically)
2.  **Which model followed the language requirement better?**
3.  **Conclusion**: Should I choose Model A (Slower but stable) or Model B (Faster but aggressive)?
