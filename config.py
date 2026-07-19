"""
Configuration — all settings loaded from environment variables or .env file.
Never hard-code secrets; every key has a safe default or raises a clear error.
"""

from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

# ─── Resolve paths ───────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent          # api-research/
ROOT_DIR   = BASE_DIR                       # api-research/
DATA_DIR   = BASE_DIR / "data"
OUTPUT_DIR = ROOT_DIR / "output"
LOG_DIR    = ROOT_DIR / "logs"

for _d in (DATA_DIR, OUTPUT_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ─── Load .env ───────────────────────────────────────────────────────────────
load_dotenv(ROOT_DIR / ".env", override=True)

# ─── API Keys ─────────────────────────────────────────────────────────────────
COMPOSIO_API_KEY: str | None = os.getenv("COMPOSIO_API_KEY")

if COMPOSIO_API_KEY:
    masked_key = f"{COMPOSIO_API_KEY[:6]}...{COMPOSIO_API_KEY[-4:]}"
    print(f"Using Composio key: {masked_key}")

GITHUB_TOKEN:     str | None = os.getenv("GITHUB_TOKEN")     # For GitHub Models API
TAVILY_API_KEY:   str | None = os.getenv("TAVILY_API_KEY")
OPENAI_API_KEY:   str | None = os.getenv("OPENAI_API_KEY")   # fallback

# ─── Model settings ───────────────────────────────────────────────────────────
GITHUB_MODEL_BASE_URL = os.getenv("GITHUB_MODEL_BASE_URL", "https://models.github.ai/inference")
LLM_MODEL         = os.getenv("LLM_MODEL", "openai/gpt-5")
LLM_TEMPERATURE   = float(os.getenv("LLM_TEMPERATURE", "0.1"))
LLM_MAX_TOKENS    = int(os.getenv("LLM_MAX_TOKENS", "4096"))

VERIFIER_LLM_PROVIDER    = os.getenv("VERIFIER_LLM_PROVIDER", "github").lower()
VERIFIER_LLM_MODEL       = os.getenv("VERIFIER_LLM_MODEL", "gpt-4o-mini")
VERIFIER_LLM_TEMPERATURE = float(os.getenv("VERIFIER_LLM_TEMPERATURE", "0.0"))

# ─── Pipeline settings ────────────────────────────────────────────────────────
BATCH_SIZE          = int(os.getenv("BATCH_SIZE", "10"))       # concurrent app batches
MAX_SEARCH_RESULTS  = int(os.getenv("MAX_SEARCH_RESULTS", "5"))
HTTP_TIMEOUT        = int(os.getenv("HTTP_TIMEOUT", "20"))     # seconds per request
MAX_RETRIES         = int(os.getenv("MAX_RETRIES", "3"))
LANGGRAPH_RECURSION = int(os.getenv("LANGGRAPH_RECURSION", "10"))  # hard cap on graph steps

# ─── Output paths ────────────────────────────────────────────────────────────
APPS_JSON_PATH      = DATA_DIR / "apps.json"
RAW_PASS1_PATH      = OUTPUT_DIR / "raw_pass1.json"
PASS2_PATH          = OUTPUT_DIR / "pass2_verified.json"
INSIGHTS_PATH       = OUTPUT_DIR / "insights.json"
VERIFY_LOG_PATH     = OUTPUT_DIR / "verification_log.json"
REPORT_HTML_PATH    = ROOT_DIR / "report" / "report.html"
PIPELINE_LOG_PATH   = LOG_DIR / "pipeline.log"

# ─── Composio user id ────────────────────────────────────────────────────────
COMPOSIO_USER_ID = os.getenv("COMPOSIO_USER_ID", "agentforge-researcher")

USE_COMPOSIO_SEARCH = bool(COMPOSIO_API_KEY)   # fall back to Tavily if not set
USE_TAVILY_SEARCH   = bool(TAVILY_API_KEY)
