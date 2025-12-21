
import logging
import os
import unittest
from unittest.mock import MagicMock, patch

# Configure logging to capture output
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("shared.llm_providers")

from shared.llm_providers import OllamaLLMProvider

class TestOllamaLogging(unittest.TestCase):
    def setUp(self):
        self.mock_state_manager = MagicMock()
        
    @patch('shared.llm_providers.requests.post')
    def test_logging_disabled(self, mock_post):
        """Loop 1: LLM_DEBUG_ENABLED=false (Default)"""
        print("\n--- Test: Logging Disabled (Default) ---")
        os.environ["LLM_DEBUG_ENABLED"] = "false"
        
        provider = OllamaLLMProvider(model="test-model", state_manager=self.mock_state_manager)
        
        # Mock successful response
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": '{"test": "ok"}'}
        mock_post.return_value = mock_response
        
        with self.assertLogs(logger, level='INFO') as cm:
            provider.generate_json("test prompt", {})
            
            # Check logs
            logs = [r for r in cm.output]
            has_prompt_log = any("Request Prompt" in log for log in logs)
            has_response_log = any("Raw Response" in log for log in logs)
            
            print(f"Logs captured: {len(logs)}")
            for log in logs:
                print(f" - {log}")
            
            if not has_prompt_log and not has_response_log:
                 print("✅ PASS: Verbose logs NOT found.")
            else:
                 print("❌ FAIL: Verbose logs found when disabled.")
                 
            self.assertFalse(has_prompt_log, "Request Prompt should not be logged")
            self.assertFalse(has_response_log, "Raw Response should not be logged")

    @patch('shared.llm_providers.requests.post')
    def test_logging_enabled(self, mock_post):
        """Loop 2: LLM_DEBUG_ENABLED=true"""
        print("\n--- Test: Logging Enabled ---")
        os.environ["LLM_DEBUG_ENABLED"] = "true"
        
        provider = OllamaLLMProvider(model="test-model", state_manager=self.mock_state_manager)
        
        # Mock successful response
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": '{"test": "ok"}'}
        mock_post.return_value = mock_response
        
        with self.assertLogs(logger, level='INFO') as cm:
            provider.generate_json("test prompt", {})
            
            # Check logs
            logs = [r for r in cm.output]
            has_prompt_log = any("Request Prompt" in log for log in logs)
            has_response_log = any("Raw Response" in log for log in logs)
            
            print(f"Logs captured: {len(logs)}")
            for log in logs:
                print(f" - {log}")
                
            if has_prompt_log and has_response_log:
                 print("✅ PASS: Verbose logs found.")
            else:
                 print("❌ FAIL: Verbose logs NOT found when enabled.")
            
            self.assertTrue(has_prompt_log, "Request Prompt should be logged")
            self.assertTrue(has_response_log, "Raw Response should be logged")

if __name__ == '__main__':
    unittest.main()
