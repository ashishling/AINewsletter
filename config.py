"""
Configuration for the RSS Feed Scorer tool.
"""
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# LLM Provider: "gemini" or "zhipu"
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")

# Google Gemini API Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-3-flash-preview"

# Z.ai (GLM 4.7) API Configuration
ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY", "")
ZHIPU_API_ENDPOINT = "https://api.z.ai/api/paas/v4/chat/completions"
ZHIPU_MODEL = "glm-4.7"  # GLM 4.7 model

# Topics (used by newsletter_generator and curator patterns)
TOPICS = [
    "AI Applications",
    "AI for Consumer",
    "AI for Healthcare",
    "AI for Finance",
    "AI for Operators",
]

# RSS Feed Discovery - common patterns to try
RSS_PATTERNS = [
    "/feed",
    "/rss",
    "/atom.xml",
    "/feed.xml",
    "/rss.xml",
    "/feed/",
    "/rss/",
    "/blog/feed",
    "/blog/rss",
    "/blog/feed.xml",
    "/blog/rss.xml",
    "/index.xml",
    "/feeds/posts/default",
]

# RSS sources to exclude from curation (e.g. general news sites)
EXCLUDED_RSS_DOMAINS = ["wired.com", "nytimes.com"]

# File paths (absolute so cron doesn't depend on working directory)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CRAWL_RESULTS_FILE = os.path.join(BASE_DIR, "browser_crawl_results.json")
FEEDS_CACHE_FILE = os.path.join(BASE_DIR, "feeds_cache.json")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATABASE_PATH = os.path.join(BASE_DIR, "newsletter.db")
NEWSLETTER_OUTPUT_DIR = os.path.join(OUTPUT_DIR, "newsletters")

# Request configuration
REQUEST_TIMEOUT = 10  # seconds
USER_AGENT = "Mozilla/5.0 (compatible; AINewsletterBot/1.0)"

# Feed parsing configuration
MAX_FEED_ITEMS = 50  # Maximum items to fetch per feed
DAYS_LOOKBACK = 7  # Only consider items from the last N days (manual/full sync)

# Cron configuration
CRON_FIRST_RUN_DAYS = 1  # On first run (no last_run), fetch articles from last N days
