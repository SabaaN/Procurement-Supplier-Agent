"""Settings from environment variables (and a .env file in backend/)."""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()  # finds backend/.env by walking up from this file


@dataclass(frozen=True)
class Settings:
    groq_api_key: str | None = os.getenv("GROQ_API_KEY")
    tavily_api_key: str | None = os.getenv("TAVILY_API_KEY")
    groq_model_small: str = os.getenv("GROQ_MODEL_SMALL", "openai/gpt-oss-120b")
    max_queries: int = 4  # per attempt; keeps Tavily credits and Groq tokens low
    results_per_query: int = 5


settings = Settings()