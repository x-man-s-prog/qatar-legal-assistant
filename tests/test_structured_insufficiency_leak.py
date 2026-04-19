# -*- coding: utf-8 -*-
"""
TARGETED LEAK FIX — STRUCTURED INSUFFICIENCY LEGACY SIGNATURE LEAK
====================================================================

Regression suite for the specific leak where
`core.legal_gates.StructuredInsufficiencyResponse.to_arabic()` used to
emit three legacy refusal phrases that bypassed REUP and reached the
user as if they were valid analytical output:

    • "لم تتوفر شروط إصدار جواب قانوني نهائي حالياً"
    • "ما يلزم لاستكمال التحليل"
    • "أقصى ما يمكن قوله الآن"

These phrases originated in the fail-closed pipeline's block paths
(G1, G2, G3, G5, canonical_verification_failed, governor_blocked) via
`FailClosedPipeline._build_insufficiency` → `to_arabic()`.

Guarantees this suite enforces, permanently:

  1. `StructuredInsufficiencyResponse.to_arabic()` never returns any
     of the three legacy phrases or close variants, for ANY reason
     and for ANY payload shape (empty, partial, full).

  2. `core.runtime.legacy_detector.detect_legacy_signatures` HARD-BLOCKS
     each of the three phrases and each close variant — no context
     gating, no regex softening.

  3. `AuthoritativeOutputGate.emit(...)` refuses to release any response
     whose `answer` contains any of the three phrases, regardless of
     which composer authored it.

  4. Analytical blocked cases that have MLRE survivors surface the
     MLRE-composed reality text — not the pipeline insufficiency text
     — as the primary answer (see test_production_runtime integration).

  5. Regression immunity: if a future edit to `to_arabic()` reintroduces
     any legacy phrasing, THIS FILE fails CI.
"""
from __future__ import annotations

import pytest

from core.legal_gates import StructuredInsufficiencyResponse
from core.runtime.legacy_detector import (
    detect_legacy_signatures, is_output_legacy_free,
)


# ════════════════════════════════════════════════════════════════════
# THE THREE LEGACY PHRASES — the exact strings that used to leak.
# Close variants are listed too: any reintroduction of ANY of these
# must be caught by both `to_arabic()` self-check AND the detector.
# ════════════════════════════════════════════════════════════════════

LEGACY_PHRASES = (
    "لم تتوفر شروط",
    "لم تتوفر شروط إصدار جواب",
    "لم تتوفر شروط إصدار جواب قانوني نهائي",
    "لم تتوفر شروط إصدار جواب قانوني نهائي حالياً",
    "ما يلزم لاستكمال التحليل",
    "أقصى ما يمكن قوله الآن",
)


# ════════════════════════════════════════════════════════════════════
# SECTION A — to_arabic() regression immunity
# ════════════════════════════════════════════════════════════════════

class TestToArabicIsLegacyFree:
    """Every shape of StructuredInsufficiencyResponse.to_arabic() output
    must be clean of legacy signatures — permanently."""

    def test_empty_response_is_legacy_free(self):
        r = StructuredInsufficiencyResponse()
        text = r.to_arabic()
        for phrase in LEGACY_PHRASES:
            assert phrase not in text, (
                f"LEAK: to_arabic() reintroduced legacy phrase {phrase!r}"
            )

    def test_full_response_is_legacy_free(self):
        r = StructuredInsufficiencyResponse(
            issue_domain="inheritance",
            what_is_established=["وجود عقد موثّق", "الدين ثابت"],
            what_is_unestablished=["حالة مرض الموت وقت التصرف"],
            documents_or_info_needed=["تقرير طبي", "شهود"],
            maximum_allowed_conclusion="الإطار القانوني المدني محتمل.",
            block_reasons=["canonical_verification_failed"],
        )
        text = r.to_arabic()
        for phrase in LEGACY_PHRASES:
            assert phrase not in text, (
                f"LEAK: to_arabic() reintroduced legacy phrase {phrase!r} "
                f"in full-response form"
            )

    @pytest.mark.parametrize("reason", [
        "domain_unclear",
        "insufficient_facts",
        "routing_failed",
        "governor_blocked",
        "evidence_failure",
        "canonical_verification_failed",
    ])
    def test_block_paths_all_produce_legacy_free_text(self, reason):
        """Every primary_reason the fail_closed pipeline uses must route
        through to_arabic() without emitting legacy phrases."""
        from core.fail_closed_pipeline import FailClosedPipeline
        from core.legal_gates import (
            ClassificationResult, LegalDomain, FactPattern, BurdenMap,
        )
        p = FailClosedPipeline()
        cls = ClassificationResult(
            primary_domain=LegalDomain.UNKNOWN,
            confidence=0.0,
            is_route_eligible=False,
            block_reason="test",
        )
        resp = p._build_insufficiency(
            cls, fact_pattern=None, burden=None,
            primary_reason=reason,
        )
        text = resp.to_arabic()
        for phrase in LEGACY_PHRASES:
            assert phrase not in text, (
                f"LEAK via block path {reason!r}: legacy phrase {phrase!r} "
                f"re-emerged in to_arabic() output"
            )

    def test_modern_header_is_present(self):
        """The new output MUST open with the modern 'تحليل أولي' header
        so that future refactors cannot silently strip the REUP-clean
        framing and fall back to a refusal register."""
        r = StructuredInsufficiencyResponse(issue_domain="civil")
        assert "تحليل أولي" in r.to_arabic()


# ════════════════════════════════════════════════════════════════════
# SECTION B — detector must HARD-BLOCK every legacy phrase
# ════════════════════════════════════════════════════════════════════

class TestLegacyDetectorBlocksLeakPhrases:
    """Each of the three phrases is a REUP hard-signature — no context
    gating may let it through."""

    @pytest.mark.parametrize("phrase,expected_id", [
        ("لم تتوفر شروط",
            "legacy_insufficiency_header"),
        ("لم تتوفر شروط إصدار جواب قانوني نهائي حالياً",
            "legacy_insufficiency_header"),
        ("ما يلزم لاستكمال التحليل",
            "legacy_insufficiency_needed"),
        ("أقصى ما يمكن قوله الآن",
            "legacy_insufficiency_max_conclusion"),
    ])
    def test_each_phrase_is_flagged(self, phrase, expected_id):
        rep = detect_legacy_signatures(phrase, domain="inheritance")
        assert not rep.is_clean, (
            f"detector missed legacy phrase {phrase!r}"
        )
        assert expected_id in rep.hits, (
            f"detector flagged phrase but did not emit id {expected_id!r}: "
            f"got {rep.hits!r}"
        )

    @pytest.mark.parametrize("domain", [
        "", "inheritance", "criminal", "civil", "banking",
        "employment", "commercial", "real_estate",
    ])
    def test_phrases_blocked_in_every_domain(self, domain):
        """Domain context must NOT be able to clear these signatures."""
        for phrase in ("لم تتوفر شروط",
                        "ما يلزم لاستكمال التحليل",
                        "أقصى ما يمكن قوله الآن"):
            assert not is_output_legacy_free(phrase, domain=domain), (
                f"legacy phrase {phrase!r} cleared detector in domain "
                f"{domain!r}"
            )

    def test_close_variants_caught_together(self):
        """The header + variant form should both trip hits so a rename
        to a near-synonym cannot slip through."""
        text = (
            "📌 لم تتوفر شروط إصدار جواب قانوني نهائي حالياً. "
            "ما يلزم لاستكمال التحليل واضح. "
            "أقصى ما يمكن قوله الآن أن الأمر يحتاج مستندات."
        )
        rep = detect_legacy_signatures(text)
        assert not rep.is_clean
        assert "legacy_insufficiency_header" in rep.hits
        assert "legacy_insufficiency_needed" in rep.hits
        assert "legacy_insufficiency_max_conclusion" in rep.hits

    def test_clean_text_passes(self):
        """The new to_arabic() output must pass the detector cleanly."""
        r = StructuredInsufficiencyResponse(
            issue_domain="inheritance",
            what_is_established=["A"],
            what_is_unestablished=["B"],
            documents_or_info_needed=["C"],
            maximum_allowed_conclusion="D",
        )
        assert is_output_legacy_free(r.to_arabic(), domain="inheritance")


# ════════════════════════════════════════════════════════════════════
# SECTION C — AuthoritativeOutputGate refuses to release leaked text
# ════════════════════════════════════════════════════════════════════

class TestAuthoritativeGateBlocksLeak:
    """Direct guard: even if some rogue upstream constructs text with
    the banned phrases, the gate must refuse to release it."""

    @pytest.mark.parametrize("phrase", [
        "لم تتوفر شروط إصدار جواب قانوني نهائي حالياً",
        "ما يلزم لاستكمال التحليل",
        "أقصى ما يمكن قوله الآن",
    ])
    def test_gate_raises_on_legacy_phrase(self, phrase):
        from core.runtime.authoritative_output import (
            AuthoritativeOutputGate, UnifiedArtifacts, ResponseAuthor,
            AuthoritativeOutputViolation,
        )
        artifacts = UnifiedArtifacts(
            author=ResponseAuthor.FAIL_CLOSED_PIPELINE,
            text=f"تحليل أولي ... {phrase} ... وبعض الشرح.",
            domain="inheritance",
            is_blocked=True,
        )
        with pytest.raises(AuthoritativeOutputViolation) as exc:
            AuthoritativeOutputGate.emit(artifacts)
        # Violation must point to the legacy signature check, not some
        # unrelated invariant.
        assert exc.value.reason == "legacy_signature_in_output"

    def test_gate_accepts_modern_insufficiency_text(self):
        """A real StructuredInsufficiencyResponse.to_arabic() output
        MUST pass the gate — otherwise the pipeline is broken for
        every legitimate block path."""
        from core.runtime.authoritative_output import (
            AuthoritativeOutputGate, UnifiedArtifacts, ResponseAuthor,
        )
        r = StructuredInsufficiencyResponse(
            issue_domain="inheritance",
            what_is_established=["A"],
            what_is_unestablished=["B"],
            documents_or_info_needed=["C"],
            maximum_allowed_conclusion="D",
        )
        artifacts = UnifiedArtifacts(
            author=ResponseAuthor.FAIL_CLOSED_PIPELINE,
            text=r.to_arabic(),
            domain="inheritance",
            is_blocked=True,
            gates_passed=["G1_classification"],
            gates_failed=["G5_no_verified_evidence"],
        )
        # Should not raise
        response = AuthoritativeOutputGate.emit(artifacts)
        assert response["output_author"] == "fail_closed_pipeline"
        assert response["answer"] == r.to_arabic()


# ════════════════════════════════════════════════════════════════════
# SECTION D — End-to-end: the exact leaking case
# ════════════════════════════════════════════════════════════════════

class TestEndToEndLeakIsSealed:
    """Re-create the exact conditions that used to leak and prove the
    final user-facing text is legacy-free."""

    def test_g1_block_path_text_is_clean(self):
        """A query with ambiguous domain lands in the G1 block path.
        The resulting FailClosedResult.text (which feeds the gate) must
        be free of all three legacy phrases."""
        from core.fail_closed_pipeline import answer_fail_closed
        result = answer_fail_closed("سؤال")
        for phrase in LEGACY_PHRASES:
            assert phrase not in (result.text or ""), (
                f"LEAK via G1 path: {phrase!r} appeared in final result.text"
            )

    def test_pre_death_inheritance_text_is_clean(self):
        """'مرض الموت + الدين' is one of the cases that used to surface
        the legacy refusal. The pipeline text must not carry any of
        the banned phrases — even if the block fires."""
        from core.fail_closed_pipeline import answer_fail_closed
        q = ("والد توفي قبل شهرين وكان عليه دين كبير قبل وفاته وتصرف في "
             "بعض أمواله، هل يدخل هذا في مرض الموت ويبطل التصرف؟")
        result = answer_fail_closed(q)
        for phrase in LEGACY_PHRASES:
            assert phrase not in (result.text or ""), (
                f"LEAK via pre-death analytical path: {phrase!r} "
                f"appeared in final result.text"
            )

    def test_governor_blocked_text_is_clean(self):
        """The governor_blocked reason routes through to_arabic() too."""
        from core.fail_closed_pipeline import FailClosedPipeline
        from core.legal_gates import ClassificationResult, LegalDomain
        p = FailClosedPipeline()
        cls = ClassificationResult(
            primary_domain=LegalDomain.CIVIL,
            confidence=0.9,
            is_route_eligible=True,
        )
        resp = p._build_insufficiency(
            cls, fact_pattern=None, burden=None,
            primary_reason="governor_blocked",
            extra_blocks=["fabricated_legal_text"],
        )
        text = resp.to_arabic()
        for phrase in LEGACY_PHRASES:
            assert phrase not in text, (
                f"LEAK via governor_blocked: {phrase!r}"
            )


# ════════════════════════════════════════════════════════════════════
# SECTION E — Regression immunity metadata
# ════════════════════════════════════════════════════════════════════

class TestRegressionImmunityMetadata:
    """Freeze the contract: the three signature IDs and phrases are
    part of the REUP legacy contract. If they disappear from the
    detector, this test fails loudly."""

    def test_detector_bank_still_carries_the_three_ids(self):
        from core.runtime.legacy_detector import _HARD_SIGNATURES
        ids = {sig_id for _, sig_id, _ in _HARD_SIGNATURES}
        assert "legacy_insufficiency_header" in ids
        assert "legacy_insufficiency_needed" in ids
        assert "legacy_insufficiency_max_conclusion" in ids
        assert "legacy_insufficiency_header_variant" in ids

    def test_authoritative_gate_invokes_legacy_detector(self):
        """Defense-in-depth: the gate must pass answers through the
        detector even when the pipeline already sanitized them."""
        from core.runtime.authoritative_output import AuthoritativeOutputGate
        import inspect
        src = inspect.getsource(AuthoritativeOutputGate)
        assert "detect_legacy_signatures" in src, (
            "AuthoritativeOutputGate no longer wires in the legacy "
            "signature detector — the leak guard was removed"
        )
