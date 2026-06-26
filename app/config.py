"""
Configuration management via environment variables.
"""

import os
from dotenv import load_dotenv

# Load .env file if present (for local development)
load_dotenv()


class Settings:
    """Application settings loaded from environment variables."""

    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "gemini")
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gemini-2.0-flash")
    LLM_TIMEOUT: int = int(os.getenv("LLM_TIMEOUT", "25"))
    PORT: int = int(os.getenv("PORT", "8000"))


settings = Settings()
