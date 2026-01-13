"""
shared/version.py - Project Identity & Versioning
"""

PROJECT_NAME = "my-prime-jennie"
VERSION = "v1.0"
DESCRIPTION = "자율 진화형 AI 트레이딩 에이전트"

def get_service_title(service_name: str) -> str:
    """Generate standardized service title."""
    return f"{PROJECT_NAME} - {service_name}"
