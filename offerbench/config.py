import json
import os
from dataclasses import dataclass
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

LLM_PROVIDERS_PATH = REPO_ROOT / "llm_providers.json"

EXTRACTION_VERSION = 2  # v2: monetary fields are now lakhs-native for INR, not absolute rupees

# Fixed, approximate conversion constant (no live FX API; exact precision isn't the goal here)
USD_TO_INR = 94.0


@dataclass(frozen=True)
class Provider:
    label: str
    base_url: str
    api_key: str
    model: str


def load_llm_providers() -> list[Provider]:
    """Loads the provider failover list from llm_providers.json if present;
    otherwise falls back to a single provider built from LLM_BASE_URL/
    LLM_API_KEY/LLM_MODEL for backward compatibility."""
    if LLM_PROVIDERS_PATH.exists():
        entries = json.loads(LLM_PROVIDERS_PATH.read_text())
        return [
            Provider(
                label=e.get("label", e["model"]),
                base_url=e["base_url"],
                api_key=e["api_key"],
                model=e["model"],
            )
            for e in entries
        ]
    if LLM_BASE_URL and LLM_API_KEY and LLM_MODEL:
        return [Provider(label=LLM_MODEL, base_url=LLM_BASE_URL, api_key=LLM_API_KEY, model=LLM_MODEL)]
    return []
