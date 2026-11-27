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
    groq_model_small: str = os.getenv("GROQ_MODEL_SMALL", "openai/gpt-oss-20b")
    max_queries: int = 4  # per attempt; keeps Tavily credits and Groq tokens low
    results_per_query: int = 5

    # page fetching
    # new pages fetched per search attempt. Each one costs a Groq extraction call: lower this
    # if the progress panel shows many "failed" extractions (Groq rate limits on the free tier).
    max_pages_per_attempt: int = int(os.getenv("MAX_PAGES_PER_ATTEMPT", "12"))
    fetch_workers: int = int(os.getenv("FETCH_WORKERS", "10"))  # parallel downloads
    # seconds to wait for a site. A slow site holds up its whole batch, and few product pages that
    # take longer than this to answer are worth the wait.
    fetch_timeout: float = float(os.getenv("FETCH_TIMEOUT", "8"))
    robots_timeout: float = 4.0  # robots.txt is small: a site that can't send it quickly is treated as allowing
    max_page_bytes: int = 2_000_000  # stop downloading a page after this
    # cleaned text sent to the model per page: about 1 token per 4 characters. Spec tables and the price
    # box are kept first, so most product pages need far less than this.
    max_page_chars: int = int(os.getenv("MAX_PAGE_CHARS", "6000"))
    min_page_chars: int = 200  # less than this = probably a JavaScript-only page
    respect_robots: bool = True
    user_agent: str = "ProcurementAgent/0.1 (product research)"

    # filtering. Off: a required spec the page doesn't mention keeps the product, flagged and ranked
    # lower. On (STRICT_REQUIREMENTS=1): such products are dropped, as before.
    strict_requirements: bool = os.getenv("STRICT_REQUIREMENTS", "0").lower() in ("1", "true", "yes")

    # sites that never sell the product: their links are dropped before any page is read
    skip_domains: tuple[str, ...] = tuple(
        d.strip().lower()
        for d in os.getenv(
            "SKIP_DOMAINS",
            "youtube.com,youtu.be,facebook.com,instagram.com,tiktok.com,twitter.com,x.com,linkedin.com,"
            "pinterest.com,reddit.com,quora.com,wikipedia.org,medium.com",
        ).split(",")
        if d.strip()
    )

    # how far "Flexible" stretches
    flexible_tolerance: float = float(os.getenv("FLEXIBLE_TOLERANCE", "0.2"))  # 5 MP flexible accepts 4 MP
    budget_tolerance: float = float(os.getenv("BUDGET_TOLERANCE", "0.15"))  # flexible budget: up to 15% over
    cheap_ratio: float = float(os.getenv("CHEAP_RATIO", "0.5"))  # below half the minimum budget: flagged
    closest_matches: int = int(os.getenv("CLOSEST_MATCHES", "5"))  # shown when nothing matches fully

    # listing pages ("5MP cameras - 24 items"): product links read one level deeper
    listing_links_per_page: int = int(os.getenv("LISTING_LINKS_PER_PAGE", "4"))
    max_followed_per_attempt: int = int(os.getenv("MAX_FOLLOWED_PER_ATTEMPT", "12"))

    # cache
    cache_ttl_hours: float = 24  # downloaded pages: fetched again after a day (no model call)
    # what the model read off a page: specs rarely change, so readings are reused for days. Prices in
    # them can be up to this old; lower it if prices move fast.
    extraction_cache_hours: float = float(os.getenv("EXTRACTION_CACHE_DAYS", "7")) * 24
    # Reasoning models (gpt-oss) think before answering, and those hidden tokens count towards the
    # daily limit. "low" is plenty for reading specs off a page; "" sends nothing (Groq's default).
    groq_reasoning_effort: str = os.getenv("GROQ_REASONING_EFFORT", "low")
    # Used when a model hits its daily limit; it has its own allowance. "" turns the backup off.
    groq_fallback_model: str = os.getenv("GROQ_FALLBACK_MODEL", "openai/gpt-oss-120b")
    extract_retry_wait: float = 5.0  # seconds to wait before retrying a failed Groq call
    # Groq's per-minute token limit for each model (free tier: 8,000). Calls wait for room under it
    # instead of hitting it and failing. 0 turns the pacing off (e.g. on a paid plan).
    groq_tokens_per_minute: int = int(os.getenv("GROQ_TOKENS_PER_MINUTE", "8000"))
    # Use GROQ_FALLBACK_MODEL too whenever the main model is at its per-minute limit. Each model has its
    # own per-minute allowance, so pages are read about twice as fast. 0: the backup is used only once
    # the main model's daily allowance is gone.
    groq_spread_models: bool = os.getenv("GROQ_SPREAD_MODELS", "1").lower() in ("1", "true", "yes")
    db_path: Path = BACKEND_DIR / "data" / "app.db"

settings = Settings()