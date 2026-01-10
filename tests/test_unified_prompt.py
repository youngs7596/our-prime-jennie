
import unittest
from unittest.mock import MagicMock, patch
import json
import sys
import os

# Adjust path to find modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from shared.llm_prompts import build_unified_analysis_prompt
from shared.llm import JennieBrain

class TestUnifiedPrompt(unittest.TestCase):
    def test_prompt_generation(self):
        items = [
            {"id": 1, "title": "A사, 북미 대규모 수주…실적 상향 기대", "summary": "A사가 북미에서 대형 계약을 체결하며 매출 증가가 예상된다."},
            {"id": 2, "title": "B사 핵심 공장 화재로 생산 중단", "summary": "B사 핵심 생산라인이 화재로 멈추며 공급 차질이 우려된다."},
            {"id": 3, "title": "삼성화재 배구단, 접전 끝에 승리", "summary": "삼성화재가 리그 경기에서 승리했다."}
        ]
        prompt = build_unified_analysis_prompt(items)
        print("\n=== Generated Prompt Preview ===")
        print(prompt[:500] + "...") 
        self.assertIn("A사, 북미 대규모 수주", prompt)
        self.assertIn('"id": 1', prompt)
    
    @patch('shared.llm.LLMFactory.get_provider')
    def test_unified_analysis_parsing(self, mock_get_provider):
        # Mock LLM response
        mock_provider = MagicMock()
        mock_get_provider.return_value = mock_provider
        
        mock_response_json = {
            "results": [
                {
                    "id": 1,
                    "sentiment": { "score": 86, "reason": "북미 대규모 수주로 매출·이익 개선 기대" },
                    "competitor_risk": { "is_detected": False, "type": "NONE", "benefit_score": 0, "reason": "치명적 리스크 아님" }
                },
                {
                    "id": 2,
                    "sentiment": { "score": 12, "reason": "공장 화재로 생산 차질 우려" },
                    "competitor_risk": { "is_detected": True, "type": "FIRE", "benefit_score": 15, "reason": "생산 중단으로 경쟁사 반사이익 가능" }
                },
                {
                    "id": 3,
                    "sentiment": { "score": 50, "reason": "스포츠 뉴스" },
                    "competitor_risk": { "is_detected": False, "type": "NONE", "benefit_score": 0, "reason": "스포츠 뉴스임" }
                }
            ]
        }
        
        mock_provider.generate_json.return_value = mock_response_json
        
        jennie = JennieBrain(project_id="test", gemini_api_key_secret="test")
        items = [{"id": 1, "title": "t1", "summary": "s1"}, {"id": 2, "title": "t2", "summary": "s2"}, {"id": 3, "title": "t3", "summary": "s3"}]
        results = jennie.analyze_news_unified(items)
        
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0]['id'], 1)
        self.assertEqual(results[1]['competitor_risk']['type'], "FIRE")
        self.assertTrue(results[1]['competitor_risk']['is_detected'])
        self.assertEqual(results[2]['sentiment']['score'], 50)
        
        print("\n=== Parsed Results ===")
        print(json.dumps(results, indent=2, ensure_ascii=False))

if __name__ == '__main__':
    unittest.main()
