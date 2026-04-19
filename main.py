# -*- coding: utf-8 -*-
"""المساعد القانوني القطري v9.0 — Main entry point."""
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from core import app_state
from core.config import ALLOWED_ORIGINS
from core.middleware import security_middleware
from core.modules import load_all
from core.startup import lifespan

# ── Logging ──
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ── Load all optional intelligence modules into app_state ──
load_all()

# ══════════════════════════════════════════════════════════
# FastAPI application
# ══════════════════════════════════════════════════════════
app = FastAPI(lifespan=lifespan, title="المساعد القانوني القطري v9.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "X-Session-ID", "X-API-Key"],
)
log.info("CORS origins: %s", ALLOWED_ORIGINS)

# Security + failed-request logging middleware
app.middleware("http")(security_middleware)

# Beta runtime middleware (must run AFTER security so auth is already handled)
try:
    from core.beta_middleware import beta_http_middleware
    app.middleware("http")(beta_http_middleware)
    log.info("✓ beta_middleware مُهيَّأ")
except Exception as _bm_err:
    log.debug("beta_middleware not loaded: %s", _bm_err)

# ── Static files & templates ──
_BASE = Path(__file__).parent
app.mount("/static", StaticFiles(directory=_BASE / "static"), name="static")
_templates = Jinja2Templates(directory=str(_BASE / "templates"))


# ── Page routes ──
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return _templates.TemplateResponse(request, "dashboard.html", {})


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return _templates.TemplateResponse(request, "login.html")


# ── Code version verification (confirms latest deploy is active) ──
@app.get("/debug/code-version")
async def debug_code_version():
    """Temporary endpoint to confirm latest code is running after deploy."""
    from core.refusal_engine import STRUCTURED_INTENTS, generate_refusal
    test_refusal = generate_refusal("salary_query", "الدرجة العاشرة")
    return {
        "status": "REFUSAL_ENGINE_ACTIVE",
        "version": "v9.1-refusal-engine",
        "structured_intents": sorted(STRUCTURED_INTENTS),
        "test_refusal": test_refusal,
        "features": [
            "deterministic_refusal_engine",
            "grade_8_9_10_support",
            "grade_miss_refusal_not_full_table",
            "no_llm_fallback_for_structured",
            "context_aware_refusals",
            "hint_mode_nearest_grade",
        ],
    }


# ── Failure log inspection (self-improvement foundation) ──
@app.get("/debug/failures")
async def debug_failures(limit: int = 200):
    """Return aggregated failure summary + repeated-query targets."""
    from core.failure_logger import summarize_failures, find_repeated_failures
    return {
        "summary": summarize_failures(limit=limit),
        "repeated": find_repeated_failures(min_count=2, limit=limit),
    }


@app.get("/debug/evidence-registry")
async def debug_evidence_registry():
    """Return evidence registry stats and loaded packs."""
    from core.evidence_registry import get_registry
    registry = get_registry()
    return registry.stats()


@app.get("/debug/improvement-report")
async def debug_improvement_report():
    """Return self-improvement report: patterns, gaps, candidates, debts."""
    from core.improvement_memory import generate_improvement_report
    return generate_improvement_report()


@app.get("/debug/reasoning")
async def debug_reasoning(query: str = "كم مربوط الدرجة السابعة"):
    """Debug: run the reasoning engine on a query and return the internal reasoning object."""
    from core.reasoning_engine import get_engine
    engine = get_engine()
    result = engine.reason(query, session_id="debug")
    return result.to_dict()


@app.get("/debug/self-diagnostic")
async def debug_self_diagnostic():
    """PHASE 9-10: Running telemetry + auto-alert state.
    Shows rolling window stats: block_rate, cross_domain_rate, avg_confidence,
    per-domain distribution, recent alerts.
    """
    from core.self_diagnostic import snapshot as _sd_snapshot
    return _sd_snapshot()


@app.get("/debug/knowledge-activation")
async def debug_knowledge_activation():
    """Return live DB-knowledge activation state + store coverage + snapshot info.

    Consumed by operators to verify:
      - mode selected by env
      - DB availability
      - snapshot presence + size
      - per-source / per-domain coverage in the live KnowledgeStore
      - quarantine breakdown
    """
    from core.knowledge.db_activation import get_activation_state
    from core.knowledge.persistence import snapshot_info
    from core.knowledge import coverage_stats, get_quarantine

    return {
        "activation": get_activation_state().to_dict(),
        "snapshot":   snapshot_info(),
        "store":      coverage_stats(),
        "quarantine": {
            "total":   get_quarantine().count(),
            "reasons": get_quarantine().reasons_breakdown(),
            "stages":  get_quarantine().stages_breakdown(),
        },
    }


# ── API routers ──
from routers.query_router   import router as _query_router
from routers.admin_router   import router as _admin_router
from routers.session_router import router as _session_router
from routers.auth_router    import router as _auth_router

app.include_router(_query_router)
app.include_router(_admin_router)
app.include_router(_session_router)
app.include_router(_auth_router)
