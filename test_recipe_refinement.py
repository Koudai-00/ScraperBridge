
import unittest
from unittest.mock import MagicMock
import sys
import os

# Add the directory to path so we can import
sys.path.append(r'c:\Users\kk-19\案件管理\27.料理キュレーションアプリ\ScraperBridge\ScraperBridge')

# Mock logic
mock_genai = MagicMock()
mock_bs4 = MagicMock()
mock_requests = MagicMock()
mock_yt_dlp = MagicMock()

sys.modules['google.generativeai'] = mock_genai
sys.modules['bs4'] = mock_bs4
sys.modules['requests'] = mock_requests
sys.modules['yt_dlp'] = mock_yt_dlp

# Also mock genai at top level if needed (though sys.modules handles imports)
# But recipe_extractor does `import google.generativeai as genai`

# Now import
from recipe_extractor import RecipeExtractor

class TestRecipeRefinement(unittest.TestCase):
    def setUp(self):
        self.extractor = RecipeExtractor()
        # Mock ensure_gemini_initialized to do nothing
        self.extractor.gemini_api_key = "dummy_key"
        self.extractor._ensure_gemini_initialized = MagicMock()

    def test_refine_recipe_text_success(self):
        # We need to mock the GenerativeModel class on the mocked module
        mock_model_class = mock_genai.GenerativeModel
        mock_model_instance = mock_model_class.return_value
        
        mock_response = MagicMock()
        mock_response.text = '''
        ```json
        {
            "dish_name": "Test Curry",
            "ingredients": ["Carrot: 1", "Potato: 2"],
            "steps": ["Cut vegetables", "Boil them"],
            "tips": ["Cook slowly"]
        }
        ```
        '''
        # Mock token estimation logic which accesses usage_metadata
        mock_response.usage_metadata.prompt_token_count = 100
        mock_response.usage_metadata.candidates_token_count = 50
        
        mock_model_instance.generate_content.return_value = mock_response

        # Input text
        input_text = "Here is the recipe for Test Curry. \nIngredients:\nCarrot: 1\nPotato: 2\nSteps:\nCut vegetables\nBoil them\n\nCheck out my instagram!"
        
        # Call the method
        result = self.extractor._refine_recipe_text_with_ai(input_text)
        
        # Verify result structure
        self.assertIn('recipe_text', result)
        self.assertEqual(result['ai_model'], 'gemini-2.0-flash-exp')
        self.assertEqual(result['tokens_used'], 150)
        
        # Verify content conversion
        # Note: _convert_json_to_text adds a leading newline to section headers, plus join('\n')
        # Result has double newlines between sections.
        expected_text = "【料理名】\nTest Curry\n\n【材料】\n- Carrot: 1\n- Potato: 2\n\n【作り方】\n1. Cut vegetables\n2. Boil them\n\n【コツ・ポイント】\n- Cook slowly"
        self.assertEqual(result['recipe_text'], expected_text)
        
    def test_refine_recipe_text_short_text(self):
        # Very short text should return as is
        input_text = "Short text"
        result = self.extractor._refine_recipe_text_with_ai(input_text)
        
        self.assertEqual(result['recipe_text'], "Short text")
        self.assertEqual(result['tokens_used'], 0)
        # Should not have called generate_content
        mock_genai.GenerativeModel.return_value.generate_content.assert_not_called()

if __name__ == '__main__':
    unittest.main()
