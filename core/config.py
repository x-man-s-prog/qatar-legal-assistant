# -*- coding: utf-8 -*-
"""
core/config.py — All environment variables and constants.
No local module imports here.
"""
import os
import secrets
from pathlib import Path

# ── Load .env if present (for local development) ──
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8-sig").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            if _v.strip():
                # setdefault: don't override vars already set by docker-compose / OS
                os.environ.setdefault(_k.strip(), _v.strip())

# ── API Keys ──
# Filter out placeholder values so downstream routing treats them as empty.
# Prevents the system from trying remote APIs with "CHANGE_ME" / test keys.
_PLACEHOLDER_VALUES = {"", "CHANGE_ME", "changeme", "TODO", "your-key-here", "xxx", "none"}

def _clean_key(val: str) -> str:
    v = (val or "").strip()
    if v in _PLACEHOLDER_VALUES:
        return ""
    if v.startswith("CHANGE") or v.startswith("YOUR_"):
        return ""
    return v

ANTHROPIC_KEY = _clean_key(os.getenv("ANTHROPIC_API_KEY", ""))
GEMINI_KEY    = _clean_key(os.getenv("GEMINI_API_KEY", ""))
OPENAI_KEY    = _clean_key(os.getenv("OPENAI_API_KEY", ""))
OLLAMA_HOST   = os.getenv("OLLAMA_HOST", "http://localhost:11434")

# LOCAL_ONLY_MODE: set to true to disable all remote LLM providers unconditionally.
# When true, all legal queries are handled by the local pipeline (Ollama + deterministic layers).
LOCAL_ONLY_MODE = os.getenv("LOCAL_ONLY_MODE", "").lower() in ("1", "true", "yes", "on")
if LOCAL_ONLY_MODE:
    ANTHROPIC_KEY = ""
    GEMINI_KEY = ""
    OPENAI_KEY = ""

# ── Service API Key (optional in dev — leave empty to disable auth) ──
API_KEY = os.getenv("API_KEY", "")   # set in production: API_KEY=some-secret-token

# ── JWT secret ──
# No hardcoded default. Expected to be set via .env or docker env.
# If missing OR a known placeholder (CHANGE_ME, TODO, …), generate a
# cryptographically strong random secret for THIS process only — so dev
# keeps working but no stable weak default ever ships in the codebase.
_JWT_RAW = os.getenv("JWT_SECRET", "").strip()
_JWT_PLACEHOLDERS = {"", "CHANGE_ME", "changeme", "TODO", "your-jwt-secret"}
if _JWT_RAW in _JWT_PLACEHOLDERS:
    JWT_SECRET = secrets.token_hex(32)
    import logging as _log
    _log.getLogger(__name__).warning(
        "JWT_SECRET is missing or a placeholder — generated an ephemeral "
        "random secret for this process. Set JWT_SECRET in .env "
        "(openssl rand -hex 32) for production — tokens will not persist "
        "across restarts otherwise."
    )
else:
    JWT_SECRET = _JWT_RAW

# ── Model names ──
MODEL_CLAUDE_MAIN = os.getenv("MODEL_MAIN",  "claude-3-5-sonnet-20241022")
MODEL_CLAUDE_FAST = os.getenv("MODEL_FAST",  "claude-3-haiku-20240307")
MODEL_GEMINI      = os.getenv("MODEL_GEMINI","gemini-2.0-flash")
MODEL_OPENAI      = os.getenv("MODEL_OPENAI","gpt-4o")
MODEL_OLLAMA_LLM  = os.getenv("MODEL_OLLAMA_LLM", "qwen2.5:3b")

# ── Primary model selection: OpenAI → Gemini → Claude → Ollama ──
def _primary_model() -> str:
    if OPENAI_KEY:      return "openai"
    if GEMINI_KEY:      return "gemini"
    if ANTHROPIC_KEY:   return "claude"
    return "ollama"

PRIMARY_MODEL = _primary_model()

# ── Mizan legal portal base URL ──
MIZAN_BASE = "https://www.almeezan.qa/LawPage.aspx"

# ── Session constants ──
SESSION_TTL = 30 * 60   # 30 minutes

# ── CORS ──
_raw_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000")
ALLOWED_ORIGINS: list[str] = [o.strip() for o in _raw_origins.split(",") if o.strip()]

# ── DB connection settings ──
DB_HOST     = os.getenv("DB_HOST", "localhost")
DB_PORT     = int(os.getenv("DB_PORT", "5432"))
DB_NAME     = os.getenv("DB_NAME", "ragdb")
DB_USER     = os.getenv("DB_USER", "raguser")
# No hardcoded default — DB_PASSWORD MUST be provided via docker env or .env.
# Fail fast at import time if missing so the app can't silently fall back to
# a known password.
DB_PASSWORD = os.getenv("DB_PASSWORD", "").strip()
if not DB_PASSWORD:
    raise RuntimeError(
        "DB_PASSWORD is not set. Configure it via docker-compose environment "
        "or a .env file at the project root. No insecure default is used."
    )

# ── Base directory ──
BASE_DIR = Path(__file__).parent.parent
