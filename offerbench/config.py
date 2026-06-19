import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")

DB_PATH = Path(os.environ.get("OFFERBENCH_DB_PATH") or (REPO_ROOT / "offerbench.db"))

LEETCODE_GRAPHQL_URL = "https://leetcode.com/graphql/"
COMPENSATION_TAG_SLUG = "compensation"

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "")

EXTRACTION_VERSION = 1

# Fixed, manually-refreshed conversion constant (no live FX API; see findings.md / plan open questions)
USD_TO_INR = 83.0
