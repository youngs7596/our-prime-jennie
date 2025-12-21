#!/usr/bin/env python3
"""List available Gemini models"""
import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared import auth

import google.generativeai as genai

secret_id = os.getenv("SECRET_ID_GEMINI_API_KEY", "gemini-api-key")
api_key = auth.get_secret(secret_id)
genai.configure(api_key=api_key)

print("Available Gemini Models:")
print("=" * 60)
for model in genai.list_models():
    if "gemini" in model.name.lower():
        print(f"  {model.name}")
