# -*- coding: utf-8 -*-
"""
End-to-end cutover tests for runtime_v2.

These tests prove — from the HTTP layer inward, not from the package
directly — that:

  1. Every answer-producing endpoint routes through runtime_v2.
  2. The response shape the UI expects is preserved.
  3. Every response is stamped as runtime_v2 (runtime="runtime_v2",
     runtime_authority="runtime_v2", legacy_runtime_used=False).
  4. The legacy runtime entry points are hard-sealed — any call raises
     LegacyRuntimeDecommissionedError.
  5. The router source no longer imports the legacy runtime.

Scenarios covered (via POST /api/v1/query/ and POST /api/v1/stream/):

  • عمل vs شراكة
  • شيك ضمان
  • مرض الموت vs وفاء دين
  • ملكية الكود / المكتبات السابقة
  • سؤال خارج النطاق (generic skeleton, NOT a refusal)
  • طلب drafting داخل النطاق
  • طلب drafting خارج النطاق (skeleton memo)
"""
from __future__ import annotations

import ast
import json
import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.query_router import router as query_router


# ═════════════════════════════════════════════════════════════════════
# Shared fixtures
# ═════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def client() -> TestClient:
    app = FastAPI()
    app.include_router(query_router)
    return TestClient(app)


LEGACY_PHRASES = (
    "لم تتوفر شروط",
    "ما يلزم لاستكمال التحليل",
    "أقصى ما يمكن قوله الآن",
    "تعذّر صياغة",
)


def _no_legacy(text: str) -> bool:
    return all(p not in (text or "") for p in LEGACY_PHRASES)


def _post_query(client: TestClient, query: str) -> dict:
    r = client.post("/api/v1/query/", json={
        "query": query, "session_id": "cutover_e2e",
    })
    assert r.status_code == 200, r.text
    return r.json()


def _assert_v2_stamped(resp: dict) -> None:
    """Every response must carry the v2 authority stamp."""
    assert resp["runtime"]            == "runtime_v2"
    assert resp["runtime_version"]    == "v2"
    assert resp["runtime_authority"]  == "runtime_v2"
    assert resp["legacy_runtime_used"] is False
    assert resp["legacy_used"]         is False
    assert resp["fallback_used"]       is False
    assert resp["authoritative_path"] == "runtime_v2"


# ═════════════════════════════════════════════════════════════════════
# SECTION 1 — E2E through the HTTP layer for all seven scenarios
# ═════════════════════════════════════════════════════════════════════

class TestE2EHttpQueryRuntimeV2:

    def test_case_1_employment_vs_partnership(self, client):
        q = ("أعمل منذ سنتين مع شخص، يحدد لي الدوام والمهام، ويدفع لي "
             "راتبًا شهريًا ثابتًا، هل تعتبر علاقتي به علاقة عمل أم شراكة؟")
        resp = _post_query(client, q)
        _assert_v2_stamped(resp)
        assert resp["domain"] == "employment_vs_partnership"
        assert resp["reasoning_mode"] == "single_path"
        assert resp["paths"], "expected at least one path"
        assert resp["paths"][0]["label"] == "علاقة عمل"
        assert _no_legacy(resp["answer"])

    def test_case_2_guarantee_cheque(self, client):
        q = ("أعطيت شيكًا لصديقي كشيك ضمان لقرض أخذته منه، ولدينا إقرار "
             "مكتوب بأن الشيك للضمان فقط وتاريخه مؤرخ بعد شهر.")
        resp = _post_query(client, q)
        _assert_v2_stamped(resp)
        assert resp["domain"] == "guarantee_cheque"
        assert resp["paths"][0]["label"].startswith("شيك ضمان")
        assert _no_legacy(resp["answer"])

    def test_case_3_death_illness_vs_debt(self, client):
        q = ("قبل وفاة والدي بشهرين تصرف في بعض أمواله، وكان يعاني من مرض "
             "شديد، لكن بعض التصرفات كانت لسداد ديون قديمة.")
        resp = _post_query(client, q)
        _assert_v2_stamped(resp)
        assert resp["domain"] == "death_illness_vs_debt"
        assert resp["reasoning_mode"] in ("conditional", "multi_path")
        assert resp["pivots"], "conditional mode must expose pivots"
        assert _no_legacy(resp["answer"])

    def test_case_4_code_ownership(self, client):
        q = ("كتبت بعض الكود في المشروع أثناء الدوام وبعضه قبل الالتحاق "
             "بالشركة، العقد يذكر IP assignment لكن بصيغة عامة.")
        resp = _post_query(client, q)
        _assert_v2_stamped(resp)
        assert resp["domain"] == "code_ownership_prior_libs"
        labels = {p["label"] for p in resp["paths"]}
        assert any("للشركة" in l for l in labels)
        assert any("للمطور" in l for l in labels)
        assert _no_legacy(resp["answer"])

    def test_case_5_out_of_scope_returns_value(self, client):
        """Out-of-scope MUST NOT be a rigid refusal — it must give
        real value (universal gaps + supported-domain directory)."""
        # A trademark/administrative query — none of the 7 pilot domains.
        q = "كيف أسجّل علامة تجارية جديدة في وزارة التجارة القطرية؟"
        resp = _post_query(client, q)
        _assert_v2_stamped(resp)
        assert resp["domain"] == "general_skeleton"
        assert resp["reasoning_mode"] == "skeleton"
        ans = resp["answer"]
        assert "الأطراف" in ans                 # universal gap
        assert "علاقة عمل" in ans               # pilot-domain directory
        assert _no_legacy(ans)
        # Must NOT carry any legacy refusal markers
        assert "ILLEGAL" not in ans
        assert "DECOMMISSIONED" not in ans

    def test_case_6_drafting_in_scope(self, client):
        q = ("اكتب مذكرة قانونية: شيك أعطيته ضمانًا لقرض ولدينا إقرار "
             "مكتوب بأنه ضمان، ثم قدّمه المستفيد للصرف.")
        resp = _post_query(client, q)
        _assert_v2_stamped(resp)
        assert resp["intent"] == "drafting"
        assert resp["drafting_mode"] in (
            "single_draft", "conditional_draft", "dual_draft",
        )
        assert resp["memo"], "memo text must be present for drafting intent"
        assert _no_legacy(resp["memo"])

    def test_case_7_drafting_out_of_scope_yields_skeleton_memo(self, client):
        q = "اكتب مذكرة بطلب وقف تنفيذ قرار إداري بسحب رخصة مهنية."
        resp = _post_query(client, q)
        _assert_v2_stamped(resp)
        assert resp["domain"] == "general_skeleton"
        assert resp["intent"] == "drafting"
        assert resp["drafting_mode"] == "skeleton_draft"
        assert resp["memo"] and _no_legacy(resp["memo"])


# ═════════════════════════════════════════════════════════════════════
# SECTION 2 — HTTP streaming endpoint also routes through v2
# ═════════════════════════════════════════════════════════════════════

class TestE2EHttpStreamRuntimeV2:

    def _stream_frames(self, client: TestClient, query: str) -> list[dict]:
        with client.stream(
            "POST", "/api/v1/stream/",
            json={"query": query, "session_id": "cutover_stream"},
        ) as r:
            assert r.status_code == 200
            frames: list[dict] = []
            for raw in r.iter_lines():
                if not raw or not raw.startswith("data: "):
                    continue
                frames.append(json.loads(raw[len("data: "):]))
            return frames

    def test_stream_is_v2_stamped_from_start_to_done(self, client):
        q = ("أعمل منذ سنتين مع شخص، يحدد لي الدوام والمهام، ويدفع لي "
             "راتبًا شهريًا ثابتًا.")
        frames = self._stream_frames(client, q)
        # Must have at least start, 1+ chunks, done
        kinds = [f.get("type") for f in frames]
        assert kinds[0]  == "start"
        assert kinds[-1] == "done"
        # start must show runtime_v2 authority
        assert frames[0]["authoritative_path"] == "runtime_v2"
        assert frames[0]["runtime_authority"]  == "runtime_v2"
        # done must be fully v2-stamped
        _assert_v2_stamped(frames[-1])


# ═════════════════════════════════════════════════════════════════════
# SECTION 3 — Legacy runtime entry points are hard-sealed
# ═════════════════════════════════════════════════════════════════════

class TestLegacySealed:

    def test_get_production_runtime_raises(self):
        from core.production_runtime import (
            get_production_runtime, LegacyRuntimeDecommissionedError,
        )
        with pytest.raises(LegacyRuntimeDecommissionedError):
            get_production_runtime()

    def test_answer_query_direct_raises(self):
        from core.production_runtime import (
            answer_query_direct, LegacyRuntimeDecommissionedError,
        )
        with pytest.raises(LegacyRuntimeDecommissionedError):
            answer_query_direct("سؤال", "sid")

    def test_production_runtime_init_raises(self):
        from core.production_runtime import (
            ProductionRuntime, LegacyRuntimeDecommissionedError,
        )
        with pytest.raises(LegacyRuntimeDecommissionedError):
            ProductionRuntime()

    def test_answer_fail_closed_raises(self):
        from core.fail_closed_pipeline import (
            answer_fail_closed, LegacyRuntimeDecommissionedError,
        )
        with pytest.raises(LegacyRuntimeDecommissionedError):
            answer_fail_closed("سؤال")

    def test_get_fail_closed_pipeline_raises(self):
        from core.fail_closed_pipeline import (
            get_fail_closed_pipeline, LegacyRuntimeDecommissionedError,
        )
        with pytest.raises(LegacyRuntimeDecommissionedError):
            get_fail_closed_pipeline()

    def test_fail_closed_pipeline_init_raises(self):
        from core.fail_closed_pipeline import (
            FailClosedPipeline, LegacyRuntimeDecommissionedError,
        )
        with pytest.raises(LegacyRuntimeDecommissionedError):
            FailClosedPipeline()

    def test_structured_insufficiency_to_arabic_is_sealed(self):
        """The old refusal composer must no longer emit user-facing text."""
        from core.legal_gates import StructuredInsufficiencyResponse
        from core.production_runtime import LegacyRuntimeDecommissionedError
        resp = StructuredInsufficiencyResponse()
        with pytest.raises(LegacyRuntimeDecommissionedError):
            resp.to_arabic()


# ═════════════════════════════════════════════════════════════════════
# SECTION 4 — Router no longer imports the legacy runtime
# ═════════════════════════════════════════════════════════════════════

class TestRouterIsRuntimeV2Only:
    """The HTTP router module MUST NOT import the legacy runtime (not
    even for type hints). Verified via AST so docstring mentions do
    not trip the check."""

    FORBIDDEN_IMPORTS = (
        "core.production_runtime",
        "core.fail_closed_pipeline",
        "core.answer_builder",
        "core.answer_mode",
        "core.drafting",
    )

    def test_query_router_ast_imports(self):
        import routers.query_router as q_router
        path = q_router.__file__
        with open(path, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=path)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    imported.add(a.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        for forbidden in self.FORBIDDEN_IMPORTS:
            hit = [m for m in imported
                    if m == forbidden or m.startswith(forbidden + ".")]
            assert not hit, (
                f"routers/query_router.py still imports legacy "
                f"{forbidden!r}: {hit}"
            )

    def test_query_router_imports_v2_adapter(self):
        """Positive assertion: the router DOES pull in the adapter."""
        import routers.query_router as q_router
        path = q_router.__file__
        with open(path, "r", encoding="utf-8") as fh:
            src = fh.read()
        assert "from core.runtime_v2.adapter" in src
        assert "answer_json as _v2_answer_json" in src


# ═════════════════════════════════════════════════════════════════════
# SECTION 5 — Migration proof: a concrete set of live HTTP calls
# ═════════════════════════════════════════════════════════════════════

class TestMigrationProof:
    """One compact proof run that exercises every pilot domain + the
    out-of-scope path + drafting, over the HTTP interface, and asserts
    runtime_v2 is the engine for every call."""

    PROOF_QUERIES = [
        ("emp_strong",
         "أعمل منذ سنتين، يحدد لي الدوام والمهام ويدفع لي راتبًا شهريًا."),
        ("partnership_strong",
         "ساهمت برأس المال مع صديقي ونقتسم الأرباح والخسائر، لا توجد تبعية."),
        ("cheque_guarantee",
         "أعطيته شيكًا كشيك ضمان لقرض ولدينا إقرار مكتوب بذلك."),
        ("death_mixed",
         "قبل وفاة والدي بشهرين تصرف في أمواله، وكان يعاني من مرض شديد، "
         "وبعض التصرفات كانت لسداد ديون قديمة."),
        ("code_contested",
         "كتبت بعض الكود أثناء الدوام وبعضه قبل الالتحاق بالشركة، العقد "
         "يذكر IP assignment بصيغة عامة."),
        ("family_out_of_scope",
         "هل أستطيع رفع دعوى حضانة على زوجي المسافر؟"),
        ("drafting_in_scope",
         "اكتب مذكرة: أريد إثبات أن علاقتي بشريكي شراكة وليست عمل."),
    ]

    def test_all_seven_proof_queries_are_v2(self, client):
        results: list[dict] = []
        for tag, q in self.PROOF_QUERIES:
            r = client.post("/api/v1/query/", json={
                "query": q, "session_id": f"proof_{tag}",
            })
            assert r.status_code == 200, r.text
            resp = r.json()
            _assert_v2_stamped(resp)
            assert _no_legacy(resp["answer"])
            results.append({
                "tag":            tag,
                "domain":         resp["domain"],
                "reasoning_mode": resp["reasoning_mode"],
                "intent":         resp["intent"],
                "drafting_mode":  resp["drafting_mode"],
                "is_skeleton":    resp["is_skeleton"],
                "runtime":        resp["runtime"],
            })
        # Full proof table: every entry must name runtime_v2
        for row in results:
            assert row["runtime"] == "runtime_v2", row
