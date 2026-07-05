import os
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVICE_ROOT))

# Pin test-safe settings before app.config is imported anywhere.
os.environ.setdefault("RATELIMIT_MODE", "memory")
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("RIOT_API_KEY", "RGAPI-test-key")
os.environ.setdefault("CRAWL_ENABLED", "0")  # seed crawl is opt-in per test
