"""Settings from environment variables (and a .env file in backend/)."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # finds backend/.env by walking up from this file

BACKEND_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    groq_api_key: str | None = os.getenv("GROQ_API_KEY")
    tavily_api_key: str | None = os.getenv("TAVILY_API_KEY")
    groq_model_small: str = os.getenv("GROQ_MODEL_SMALL", "llama-3.1-8b-instant")
    max_queries: int = 4  # per attempt; keeps Tavily credits and Groq tokens low
    results_per_query: int = 5

    # page fetching
    max_pages_per_attempt: int = 8  # new pages fetched per search attempt
    fetch_workers: int = 5  # parallel downloads
    fetch_timeout: float = 15.0  # seconds
    max_page_bytes: int = 2_000_000  # stop downloading a page after this
    max_page_chars: int = 12_000  # cleaned text kept per page (keeps LLM tokens down)
    min_page_chars: int = 200  # less than this = probably a JavaScript-only page
    respect_robots: bool = True
    user_agent: str = "ProcurementAgent/0.1 (product research)"

    # cache
    cache_ttl_hours: float = 24
    db_path: Path = BACKEND_DIR / "data" / "app.db"


settings = Settings()