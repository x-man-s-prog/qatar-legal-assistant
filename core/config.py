# -*- coding: utf-8 -*-
"""
core/config.py — All environment variables and constants.
No local module imports here.
"""
import os
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

# ── JWT secret — يجب تعيينه في .env للإنتاج (openssl rand -hex 32) ──
_JWT_DEFAULT = "mizan-dev-secret-change-in-prod"   # dev-only fallback — NOT for production
JWT_SECRET = os.getenv("JWT_SECRET", _JWT_DEFAULT)
if JWT_SECRET == _JWT_DEFAULT:
    import logging as _log
    _log.getLogger(__name__).warning("JWT_SECRET يستخدم القيمة الافتراضية — يُرجى تعيينه في .env قبل الإنتاج")

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
_DB_PASS_DEFAULT = "RAGsecret2024!"   # dev-only fallback — override in .env for production
DB_PASSWORD = os.getenv("DB_PASSWORD", _DB_PASS_DEFAULT)

# ── Base directory ──
BASE_DIR = Path(__file__).parent.parent
