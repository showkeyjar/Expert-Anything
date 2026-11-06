"""Runtime configuration for ExpertAnything desktop app.

All settings are read from environment variables so the app stays
configuration-file-free by default, but can be overridden per machine.
"""
from __future__ import annotations

import os
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[2]


def _load_dotenv() -> None:
    """Best-effort .env loader (stdlib only, no extra dependency).

    Lets users persist EXPERTANYTHING_LLM_API_KEY etc. in a `.env` file at the
    workspace root instead of exporting it in every shell. Existing process
    env vars win; .env only fills gaps. Silently no-ops if no .env present.
    """
    for cand in (WORKSPACE / ".env", Path.cwd() / ".env"):
        if not cand.exists():
            continue
        try:
            for line in cand.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
        except Exception:
            # A broken .env must never crash startup.
            pass


_load_dotenv()

# --- LLM (OpenAI-compatible endpoint) -----------------------------------------
LLM_API_KEY = os.environ.get("EXPERTANYTHING_LLM_API_KEY", "")
LLM_BASE_URL = os.environ.get("EXPERTANYTHING_LLM_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = os.environ.get("EXPERTANYTHING_LLM_MODEL", "gpt-4o-mini")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


# Single in-flight request by default: the local llama.cpp endpoint exposes one
# decoding slot, and serialising removes one source of run-to-run jitter. Raise
# it for cloud endpoints that genuinely serve concurrent requests.
LLM_MAX_CONCURRENCY = _env_int("EXPERTANYTHING_LLM_MAX_CONCURRENCY", 1)
# Fixed sampling seed for extraction calls (0 = deterministic attempt).
LLM_SEED = os.environ.get("EXPERTANYTHING_LLM_SEED", "0")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


# Base HTTP timeout; chat_json raises it for long generations (see _call_timeout).
LLM_TIMEOUT = _env_float("EXPERTANYTHING_LLM_TIMEOUT", 60.0)

# --- Storage ----------------------------------------------------------------
DATA_DIR = Path(os.environ.get("EXPERTANYTHING_DATA_DIR", str(WORKSPACE / "data")))
ASSETS_DIR = DATA_DIR / "assets"
LEARNER_FILE = DATA_DIR / "learner.json"

# Mastery below this is considered a weakness.
WEAKNESS_THRESHOLD = 0.6


def has_llm() -> bool:
    """True when an API key is configured, i.e. real LLM calls can be made."""
    return bool(LLM_API_KEY.strip())


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
