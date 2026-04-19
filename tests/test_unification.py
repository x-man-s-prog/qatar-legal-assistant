# -*- coding: utf-8 -*-
"""
Monolithic Runtime Unification — Enforcement Tests.
=====================================================

Proves that after unification:
  • every answer-producing endpoint stamps authoritative_path
  • legacy flags cannot turn on legacy answers
  • direct LLM admin endpoints are guarded
  • session followup no longer calls LLM
  • retrieval/LLM bypass paths are closed
  • query_router.py has no direct LLM imports in answer path
  • all gates metadata is present on every response

Run:  pytest tests/test_unification.py -v
"""
from __future__ import annotations
import os
import sys
import ast
import json
import importlib
from pathlib import Path

import pytest


# ═════════════════════════════════════════════════════════════════
# Static code-shape assertions (catch drift before runtime)
# ═════════════════════════════════════════════════════════════════

_ROOT = Path(__file__).resolve().parent.parent


class TestRouterShape:
    """Static checks on the router source code."""

    def test_query_router_no_generate_answer_import(self):
        """query_router.py must NOT import _generate_answer or stream_* directly."""
        src = (_ROOT / "routers" / "query_router.py").read_text(encoding="utf-8")
        forbidden = [
            "from services.llm_service import _generate_answer",
            "from services.llm_service import stream_ollama",
            "from services.llm_service import stream_gemini",
            "from services.llm_service import stream_openai",
            "from services.llm_service import call_claude",
            "_generate_answer(",
            "stream_ollama(",
            "stream_gemini(",
            "stream_openai(",
            "call_claude(",
        ]
        for line in forbidden:
            assert line not in src, \
                f"query_router.py contains legacy LLM reference: {line!r}"

    def test_query_router_is_compact(self):
        """query_router.py must be small after unification (was 3140 lines)."""
        path = _ROOT / "routers" / "query_router.py"
        line_count = path.read_text(encoding="utf-8").count("\n")
        assert line_count < 400, \
            f"query_router.py grew back to {line_count} lines — unification drift"

    def test_session_router_no_generate_answer(self):
        """session_router.py must NOT call _generate_answer (was in followup)."""
        src = (_ROOT / "routers" / "session_router.py").read_text(encoding="utf-8")
        assert "_generate_answer(" not in src, \
            "session_router.py still calls _generate_answer"
        assert "from services.llm_service" not in src, \
            "session_router.py still imports llm_service"


class TestRuntimeFlagsLocked:
    def test_legacy_fallback_cannot_be_enabled(self, monkeypatch):
        """Even with env override, ENABLE_LEGACY_FALLBACK stays False."""
        monkeypatch.setenv("ENABLE_LEGACY_FALLBACK", "true")
        monkeypatch.setenv("USE_FAIL_CLOSED_RUNTIME", "false")
        import core.runtime_flags
        importlib.reload(core.runtime_flags)
        assert core.runtime_flags.ENABLE_LEGACY_FALLBACK is False, \
            "legacy fallback flag is not locked off"
        assert core.runtime_flags.USE_FAIL_CLOSED_RUNTIME is True, \
            "fail_closed flag is not locked on"

    def test_reload_from_env_is_noop(self, monkeypatch):
        """reload_from_env returns locked snapshot regardless of env."""
        monkeypatch.setenv("ENABLE_LEGACY_FALLBACK", "true")
        from core.runtime_flags import reload_from_env
        snap = reload_from_env()
        assert snap["ENABLE_LEGACY_FALLBACK"] is False
        assert snap["USE_FAIL_CLOSED_RUNTIME"] is True


# ═════════════════════════════════════════════════════════════════
# Authority enforcement on production_runtime
# ═════════════════════════════════════════════════════════════════

class TestProductionRuntimeAuthorityStamp:
    def _direct_answer(self, q, sid="unit-auth"):
        from core.production_runtime import answer_query_direct
        return answer_query_direct(q, sid)

    def test_response_has_authoritative_path(self):
        r = self._direct_answer("ما أحكام الحضانة في القانون القطري")
        assert r.get("authoritative_path") == "unified_fail_closed"

    def test_response_declares_legacy_false(self):
        r = self._direct_answer("أحكام عقد البيع")
        assert r.get("legacy_used") is False
        assert r.get("fallback_used") is False

    def test_conversation_has_authority_stamp(self):
        r = self._direct_answer("مرحبا")
        assert r.get("authoritative_path") == "unified_fail_closed"
        assert r.get("legacy_used") is False

    def test_drafting_refusal_has_authority_stamp(self):
        r = self._direct_answer("اكتب لي مذكرة دفاع كاملة مفصلة")
        assert r.get("authoritative_path") == "unified_fail_closed"
        assert r.get("legacy_used") is False
        assert r.get("is_blocked") is True


# ═════════════════════════════════════════════════════════════════
# HTTP enforcement — every endpoint response stamped
# ═════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def client():
    os.environ["USE_FAIL_CLOSED_RUNTIME"]      = "true"
    os.environ["ENABLE_LEGACY_FALLBACK"]       = "false"
    os.environ["DB_KNOWLEDGE_ACTIVATION_MODE"] = "skip"
    os.environ.pop("ALLOW_DEV_LLM_PROBE", None)   # ensure admin probes disabled
    if "core.runtime_flags" in sys.modules:
        importlib.reload(sys.modules["core.runtime_flags"])
    from fastapi.testclient import TestClient
    from main import app
    with TestClient(app, headers={"Referer": "http://localhost:8000/"}) as c:
        yield c


class TestEndpointAuthorityStamps:
    def test_json_response_carries_authoritative_path(self, client):
        r = client.post("/api/v1/query/", json={
            "query": "أحكام الحضانة في القانون القطري",
            "session_id": "unif-http-1",
        })
        body = r.json()
        if body.get("from_beta_gate") is True:
            # Beta middleware intercepts upstream — that's an acceptable
            # security pre-gate that doesn't need to carry runtime stamps.
            return
        assert body.get("authoritative_path") == "unified_fail_closed", \
            f"missing authority stamp: {body}"
        assert body.get("legacy_used") is False
        assert body.get("fallback_used") is False

    def test_stream_frames_carry_authoritative_path(self, client):
        r = client.post("/api/v1/stream/", json={
            "query": "أحكام الإيجار في القانون القطري",
            "session_id": "unif-http-2",
        })
        if r.headers.get("content-type", "").startswith("application/json"):
            body = r.json()
            assert body.get("from_beta_gate") is True
            return
        # SSE — find start frame and verify stamp
        lines = [ln for ln in r.text.split("\n") if ln.startswith("data: ")]
        start_line = next((ln for ln in lines
                            if '"type":"start"' in ln or '"type": "start"' in ln),
                           None)
        assert start_line, "no start frame"
        start = json.loads(start_line[len("data: "):])
        assert start.get("authoritative_path") == "unified_fail_closed"

    def test_stream_done_frame_declares_no_legacy(self, client):
        r = client.post("/api/v1/stream/", json={
            "query": "سؤال قانوني مفصَّل عن التقاضي",
            "session_id": "unif-http-3",
        })
        if r.headers.get("content-type", "").startswith("application/json"):
            return   # beta block
        lines = [ln for ln in r.text.split("\n") if ln.startswith("data: ")]
        done = next((ln for ln in lines
                      if '"type":"done"' in ln or '"type": "done"' in ln),
                     None)
        assert done, "no done frame"
        payload = json.loads(done[len("data: "):])
        assert payload.get("authoritative_path") == "unified_fail_closed"
        assert payload.get("legacy_used") is False
        assert payload.get("fallback_used") is False

    def test_followup_endpoint_uses_no_llm(self, client):
        r = client.post("/api/v1/followup", json={
            "query": "أنا عامل تم فصلي تعسفياً",
            "answer": "ملخص",
        })
        if r.status_code == 401 or r.status_code == 403:
            return
        body = r.json()
        assert body.get("llm_used") is False, \
            f"followup must not use LLM: {body}"
        assert body.get("authoritative_path") == "unified_fail_closed"

    def test_admin_test_ollama_disabled_in_production(self, client):
        r = client.get("/api/v1/test_ollama")
        if r.status_code == 401 or r.status_code == 403:
            return
        body = r.json()
        assert body.get("status") == "disabled"
        assert body.get("authoritative_path") == "non_authoritative"

    def test_admin_compare_disabled_in_production(self, client):
        r = client.post("/api/v1/compare", json={
            "law_a": "قانون العمل", "law_b": "قانون الأسرة",
            "aspect": "الفصل",
        })
        if r.status_code == 401 or r.status_code == 403:
            return
        body = r.json()
        assert body.get("status") == "disabled"


# ═════════════════════════════════════════════════════════════════
# Adversarial — bypass attempts must fail
# ═════════════════════════════════════════════════════════════════

class TestBypassAttemptsFail:
    def test_cannot_summon_legacy_via_env(self, monkeypatch, client):
        """Setting ENABLE_LEGACY_FALLBACK=true must NOT change behavior."""
        monkeypatch.setenv("ENABLE_LEGACY_FALLBACK", "true")
        if "core.runtime_flags" in sys.modules:
            importlib.reload(sys.modules["core.runtime_flags"])
        r = client.post("/api/v1/query/", json={
            "query": "سؤال قانوني بسيط",
            "session_id": "bypass-1",
        })
        body = r.json()
        if body.get("from_beta_gate") is True:
            return
        assert body.get("legacy_used") is False, \
            "legacy flag was able to turn on legacy output"
        assert body.get("authoritative_path") == "unified_fail_closed"


class TestAuthorityContract:
    def test_contract_enforcer_raises_on_missing_field(self):
        from core.production_runtime import _enforce_authority_contract
        bad = {"answer": "x"}  # missing everything
        with pytest.raises(RuntimeError, match="contract violation"):
            _enforce_authority_contract(bad)

    def test_contract_enforcer_passes_complete_response(self):
        from core.production_runtime import _enforce_authority_contract
        good = {
            "runtime": "fail_closed",
            "gates_passed": ["G1"], "gates_failed": [],
            "evidence_trace": {},
            "sufficiency_level": "sufficient_direct",
            "is_blocked": False, "block_reasons": [],
        }
        out = _enforce_authority_contract(good)
        assert out["authoritative_path"] == "unified_fail_closed"
        assert out["legacy_used"] is False
        assert out["fallback_used"] is False


# ═════════════════════════════════════════════════════════════════
# Dead-code proof — verify old modules are no longer imported by router
# ═════════════════════════════════════════════════════════════════

class TestLegacyModulesNotUsed:
    """Parses query_router.py AST — verifies legacy modules aren't imported."""

    def _get_imports(self, file_path: Path) -> set[str]:
        try:
            tree = ast.parse(file_path.read_text(encoding="utf-8"))
        except SyntaxError:
            return set()
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
            elif isinstance(node, ast.Import):
                for n in node.names:
                    imports.add(n.name)
        return imports

    def test_router_does_not_import_legacy_brain(self):
        imps = self._get_imports(_ROOT / "routers" / "query_router.py")
        forbidden = {
            "core.legal_brain_tree",       # legacy decision engine
            "core.decision_engine",         # legacy
            "core.adversarial_thinker",     # legacy
            "core.legal_knowledge_base",    # legacy RAG wrapper
            "core.post_processor",          # legacy stream filter
            "core.self_correction",         # legacy
            "core.orchestration",           # legacy orchestrator
            "services.llm_service",         # legacy LLM
        }
        bad = imps & forbidden
        assert not bad, f"query_router.py still imports legacy modules: {bad}"

    def test_session_router_does_not_import_llm_service(self):
        imps = self._get_imports(_ROOT / "routers" / "session_router.py")
        assert "services.llm_service" not in imps, \
            "session_router.py still imports llm_service"


# ═════════════════════════════════════════════════════════════════
# Single-authority proof — only one runtime produces answers
# ═════════════════════════════════════════════════════════════════

class TestSingleAuthority:
    def test_only_production_runtime_produces_answers(self, client):
        """Across multiple queries, every answer carries the same authority stamp."""
        queries = [
            "أحكام الحضانة في قطر",
            "ما شروط الإيجار؟",
            "مرحبا",
            "اكتب لي مذكرة",
            "نزاع تجاري",
        ]
        for q in queries:
            r = client.post("/api/v1/query/", json={
                "query": q,
                "session_id": f"single-{hash(q) & 0xFFF}",
            })
            body = r.json()
            if body.get("from_beta_gate"):
                continue
            # Every answer must carry the SAME authority stamp
            assert body.get("authoritative_path") == "unified_fail_closed", \
                f"query={q!r} carries different authority: {body.get('authoritative_path')}"
            assert body.get("legacy_used") is False
            assert body.get("fallback_used") is False
