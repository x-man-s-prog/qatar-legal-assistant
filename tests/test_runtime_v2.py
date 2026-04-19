# -*- coding: utf-8 -*-
"""
Strict tests for runtime_v2 — the four pilot cases.

Contract: every test in this file MUST pass before any adapter wiring
to the current UI is built. If ANY case fails, runtime_v2 does not ship.
"""
from __future__ import annotations

import pytest

from core.runtime_v2 import (
    answer, DomainKey, DraftingMode, Intent, ReasoningMode,
)


# ─────────────────────────────────────────────────────────────────────
# Banned phrases — runtime_v2 must emit NONE of these, ever.
# ─────────────────────────────────────────────────────────────────────

LEGACY_PHRASES = (
    "لم تتوفر شروط",
    "ما يلزم لاستكمال التحليل",
    "أقصى ما يمكن قوله الآن",
    "تعذّر صياغة",
)


def _no_legacy(text: str) -> bool:
    return all(p not in (text or "") for p in LEGACY_PHRASES)


# ═════════════════════════════════════════════════════════════════════
# CASE 1 — EMPLOYMENT vs PARTNERSHIP
# ═════════════════════════════════════════════════════════════════════

class TestEmploymentVsPartnership:
    Q_STRONG_EMPLOYMENT = (
        "أعمل منذ سنتين مع شخص، يحدد لي الدوام والمهام، ويدفع لي راتبًا "
        "شهريًا ثابتًا، هل تعتبر علاقتي به علاقة عمل أم شراكة؟"
    )
    Q_STRONG_PARTNERSHIP = (
        "ساهمت برأس المال مع صديقي، ونقتسم الأرباح والخسائر، ونتخذ "
        "القرارات معاً، ولا توجد علاقة تبعية بيننا، هل هذه شراكة؟"
    )
    Q_MIXED = (
        "أعمل عند شريكي في المكتب يوميًا بساعات محددة ويدفع لي راتبًا، "
        "لكنني ساهمت في رأس المال وأشارك في الأرباح، ما تكييف العلاقة؟"
    )

    def test_domain_resolves(self):
        r = answer(self.Q_STRONG_EMPLOYMENT)
        assert r.domain == DomainKey.EMPLOYMENT_VS_PARTNERSHIP.value

    def test_strong_employment_prefers_employment_path(self):
        r = answer(self.Q_STRONG_EMPLOYMENT)
        assert r.paths[0].label == "علاقة عمل"
        # Dominant enough to be single-path
        assert r.reasoning_mode == ReasoningMode.SINGLE_PATH

    def test_strong_partnership_prefers_partnership_path(self):
        r = answer(self.Q_STRONG_PARTNERSHIP)
        assert r.paths[0].label == "شراكة"
        assert r.reasoning_mode == ReasoningMode.SINGLE_PATH

    def test_mixed_facts_trigger_multi_or_conditional(self):
        r = answer(self.Q_MIXED)
        assert r.reasoning_mode in (
            ReasoningMode.MULTI_PATH, ReasoningMode.CONDITIONAL,
        )
        labels = {p.label for p in r.paths}
        assert "علاقة عمل" in labels and "شراكة" in labels

    def test_pivots_are_present(self):
        r = answer(self.Q_MIXED)
        assert len(r.pivots) >= 3
        qs = [p.question for p in r.pivots]
        assert any("تبعية" in q for q in qs)

    def test_evidence_is_verified(self):
        r = answer(self.Q_STRONG_EMPLOYMENT)
        assert len(r.evidence) >= 1
        for e in r.evidence:
            assert e.is_verified
            assert "قانون" in e.citation

    def test_no_legacy_phrases(self):
        for q in (self.Q_STRONG_EMPLOYMENT, self.Q_STRONG_PARTNERSHIP,
                    self.Q_MIXED):
            r = answer(q)
            assert _no_legacy(r.answer_text), \
                f"legacy phrase leaked in emp-vs-partnership answer: {q!r}"

    def test_drafting_produces_memo(self):
        r = answer("اكتب مذكرة قانونية: " + self.Q_MIXED)
        assert r.intent == Intent.DRAFTING
        assert r.memo_text and _no_legacy(r.memo_text)
        assert r.drafting_mode is not None


# ═════════════════════════════════════════════════════════════════════
# CASE 2 — GUARANTEE CHEQUE
# ═════════════════════════════════════════════════════════════════════

class TestGuaranteeCheque:
    Q_CLEAR_GUARANTEE = (
        "أعطيت شيكًا لصديقي كشيك ضمان لقرض أخذته منه، ولدينا إقرار مكتوب "
        "بأن الشيك للضمان فقط وتاريخه مؤرخ بعد شهر."
    )
    Q_CLEAR_PAYMENT = (
        "حررت شيكًا بتاريخ اليوم مقابل بضاعة استلمتها، ثم عاد الشيك من "
        "البنك بدون رصيد."
    )
    Q_AMBIGUOUS = (
        "الشيك الذي أعطيته للمستفيد لم يتم صرفه، ولا أعرف هل كان ضمانًا "
        "أم وفاء فوريًا."
    )

    def test_domain_resolves(self):
        r = answer(self.Q_CLEAR_GUARANTEE)
        assert r.domain == DomainKey.GUARANTEE_CHEQUE.value

    def test_guarantee_facts_surface_guarantee_path(self):
        r = answer(self.Q_CLEAR_GUARANTEE)
        assert r.paths[0].label.startswith("شيك ضمان")

    def test_payment_facts_surface_payment_path(self):
        r = answer(self.Q_CLEAR_PAYMENT)
        assert r.paths[0].label.startswith("شيك وفاء")

    def test_ambiguous_mode_is_conditional_or_skeleton(self):
        r = answer(self.Q_AMBIGUOUS)
        assert r.reasoning_mode in (
            ReasoningMode.CONDITIONAL,
            ReasoningMode.MULTI_PATH,
            ReasoningMode.SKELETON,
        )

    def test_pivots_include_written_acknowledgment(self):
        r = answer(self.Q_AMBIGUOUS)
        qs = [p.question for p in r.pivots]
        assert any(
            ("اتفاق" in q) or ("إقرار" in q) or ("مكتوب" in q)
            for q in qs
        )

    def test_evidence_carries_cheque_and_penal(self):
        r = answer(self.Q_CLEAR_PAYMENT)
        joined = " | ".join(e.citation for e in r.evidence)
        assert "التجارة" in joined
        assert "العقوبات" in joined

    def test_no_legacy_phrases(self):
        for q in (self.Q_CLEAR_GUARANTEE, self.Q_CLEAR_PAYMENT,
                    self.Q_AMBIGUOUS):
            r = answer(q)
            assert _no_legacy(r.answer_text)

    def test_drafting_produces_memo(self):
        r = answer("اكتب مذكرة قانونية: " + self.Q_CLEAR_GUARANTEE)
        assert r.intent == Intent.DRAFTING
        assert r.memo_text and _no_legacy(r.memo_text)


# ═════════════════════════════════════════════════════════════════════
# CASE 3 — DEATH-ILLNESS vs DEBT
# ═════════════════════════════════════════════════════════════════════

class TestDeathIllnessVsDebt:
    Q_CLEAR_DEBT = (
        "والدي توفي قبل شهرين، وكان عليه دين موثق بوثيقة رسمية قبل مرضه، "
        "وقبل وفاته بأيام باع عقارًا لسداد الدين بنفس قيمة السوق."
    )
    Q_CLEAR_DEATH_ILLNESS = (
        "والدي كان في مرض قاضٍ وقبل وفاته بأسبوع وهب منزله لوارث واحد بلا "
        "مقابل ولا دين سابق موثق."
    )
    Q_MIXED = (
        "قبل وفاة والدي بشهرين تصرف في بعض أمواله، وكان يعاني من مرض "
        "شديد، لكن بعض التصرفات كانت لسداد ديون قديمة."
    )

    def test_domain_resolves(self):
        r = answer(self.Q_MIXED)
        assert r.domain == DomainKey.DEATH_ILLNESS_VS_DEBT.value

    def test_clear_debt_path_is_top(self):
        r = answer(self.Q_CLEAR_DEBT)
        assert "وفاء دين" in r.paths[0].label

    def test_clear_death_illness_path_is_top(self):
        r = answer(self.Q_CLEAR_DEATH_ILLNESS)
        assert "مرض الموت" in r.paths[0].label

    def test_mixed_triggers_conditional_or_multi(self):
        r = answer(self.Q_MIXED)
        assert r.reasoning_mode in (
            ReasoningMode.CONDITIONAL, ReasoningMode.MULTI_PATH,
        )

    def test_pivots_cover_debt_illness_and_heir(self):
        r = answer(self.Q_MIXED)
        joined = " | ".join(p.question for p in r.pivots)
        assert "دين" in joined
        assert ("مرض" in joined) or ("هلاك" in joined)
        assert "وارث" in joined

    def test_both_paths_returned(self):
        r = answer(self.Q_MIXED)
        labels = {p.label for p in r.paths}
        assert any("وفاء" in l for l in labels)
        assert any(("مرض الموت" in l) or ("الوصية" in l) for l in labels)

    def test_no_legacy_phrases(self):
        for q in (self.Q_CLEAR_DEBT, self.Q_CLEAR_DEATH_ILLNESS,
                    self.Q_MIXED):
            r = answer(q)
            assert _no_legacy(r.answer_text)

    def test_drafting_produces_memo(self):
        r = answer("اكتب مذكرة قانونية: " + self.Q_MIXED)
        assert r.intent == Intent.DRAFTING
        assert r.memo_text and _no_legacy(r.memo_text)


# ═════════════════════════════════════════════════════════════════════
# CASE 4 — CODE OWNERSHIP (prior libraries)
# ═════════════════════════════════════════════════════════════════════

class TestCodeOwnershipPriorLibs:
    Q_COMPANY_OWNS = (
        "أعمل مطورًا في شركة برمجة، عقدي ينص على نقل ملكية كل ما أكتبه "
        "أثناء الدوام للشركة، وكتبت الكود باستخدام أجهزة الشركة."
    )
    Q_DEV_OWNS = (
        "كتبت مكتبات كود قبل الالتحاق بالشركة بسنوات ثم ضمّنتها في مشروع "
        "الشركة، العقد لا ينص على نقل الأعمال السابقة."
    )
    Q_CONTESTED = (
        "كتبت بعض الكود في المشروع أثناء الدوام وبعضه قبل الالتحاق "
        "بالشركة، العقد يذكر IP assignment لكن بصيغة عامة."
    )

    def test_domain_resolves(self):
        r = answer(self.Q_COMPANY_OWNS)
        assert r.domain == DomainKey.CODE_OWNERSHIP_PRIOR_LIBS.value

    def test_company_path_wins_on_company_facts(self):
        r = answer(self.Q_COMPANY_OWNS)
        assert "للشركة" in r.paths[0].label
        assert r.reasoning_mode == ReasoningMode.SINGLE_PATH

    def test_dev_path_wins_on_prior_facts(self):
        r = answer(self.Q_DEV_OWNS)
        assert "للمطور" in r.paths[0].label

    def test_contested_triggers_multi_or_conditional(self):
        r = answer(self.Q_CONTESTED)
        assert r.reasoning_mode in (
            ReasoningMode.MULTI_PATH, ReasoningMode.CONDITIONAL,
        )

    def test_pivots_cover_ip_clause_and_prior_work(self):
        r = answer(self.Q_CONTESTED)
        joined = " | ".join(p.question for p in r.pivots)
        assert ("IP" in joined) or ("ملكية" in joined)
        assert ("قبل" in joined) or ("سابق" in joined)

    def test_evidence_references_copyright_law(self):
        r = answer(self.Q_COMPANY_OWNS)
        joined = " | ".join(e.citation for e in r.evidence)
        assert "حق المؤلف" in joined

    def test_no_legacy_phrases(self):
        for q in (self.Q_COMPANY_OWNS, self.Q_DEV_OWNS, self.Q_CONTESTED):
            r = answer(q)
            assert _no_legacy(r.answer_text)

    def test_drafting_produces_memo(self):
        r = answer("اكتب مذكرة قانونية: " + self.Q_CONTESTED)
        assert r.intent == Intent.DRAFTING
        assert r.memo_text and _no_legacy(r.memo_text)


# ═════════════════════════════════════════════════════════════════════
# UNIVERSAL CONTRACT TESTS — apply to every response, every case
# ═════════════════════════════════════════════════════════════════════

ALL_IN_SCOPE_QUERIES = [
    TestEmploymentVsPartnership.Q_STRONG_EMPLOYMENT,
    TestEmploymentVsPartnership.Q_STRONG_PARTNERSHIP,
    TestEmploymentVsPartnership.Q_MIXED,
    TestGuaranteeCheque.Q_CLEAR_GUARANTEE,
    TestGuaranteeCheque.Q_CLEAR_PAYMENT,
    TestGuaranteeCheque.Q_AMBIGUOUS,
    TestDeathIllnessVsDebt.Q_CLEAR_DEBT,
    TestDeathIllnessVsDebt.Q_CLEAR_DEATH_ILLNESS,
    TestDeathIllnessVsDebt.Q_MIXED,
    TestCodeOwnershipPriorLibs.Q_COMPANY_OWNS,
    TestCodeOwnershipPriorLibs.Q_DEV_OWNS,
    TestCodeOwnershipPriorLibs.Q_CONTESTED,
]


class TestUniversalContract:
    @pytest.mark.parametrize("q", ALL_IN_SCOPE_QUERIES)
    def test_every_answer_has_non_empty_text(self, q):
        r = answer(q)
        assert r.answer_text.strip()
        assert _no_legacy(r.answer_text)

    @pytest.mark.parametrize("q", ALL_IN_SCOPE_QUERIES)
    def test_every_answer_tagged_runtime_v2(self, q):
        d = answer(q).to_dict()
        assert d["runtime"] == "runtime_v2"
        assert d["author"]  == "runtime_v2_composer"

    @pytest.mark.parametrize("q", ALL_IN_SCOPE_QUERIES)
    def test_every_memo_is_legacy_free(self, q):
        r = answer("اكتب مذكرة قانونية: " + q)
        assert r.intent == Intent.DRAFTING
        assert r.memo_text and _no_legacy(r.memo_text)

    @pytest.mark.parametrize("q", ALL_IN_SCOPE_QUERIES)
    def test_every_drafting_mode_matches_reasoning(self, q):
        r = answer("اكتب مذكرة: " + q)
        expected = {
            ReasoningMode.SINGLE_PATH: DraftingMode.SINGLE_DRAFT,
            ReasoningMode.MULTI_PATH:  DraftingMode.DUAL_DRAFT,
            ReasoningMode.CONDITIONAL: DraftingMode.CONDITIONAL_DRAFT,
            ReasoningMode.SKELETON:    DraftingMode.SKELETON_DRAFT,
        }[r.reasoning_mode]
        assert r.drafting_mode == expected

    def test_out_of_scope_returns_generic_skeleton(self):
        # A trademark/administrative query — none of the 7 pilot domains.
        r = answer("كيف أسجّل علامة تجارية جديدة لدى الوزارة في قطر؟")
        assert r.domain == "general_skeleton"
        assert r.reasoning_mode == ReasoningMode.SKELETON
        assert _no_legacy(r.answer_text)
        # Must give real value: universal gaps + supported-domains listing
        assert "الأطراف" in r.answer_text

    def test_empty_query_returns_generic_skeleton(self):
        r = answer("")
        assert r.domain == "general_skeleton"
        assert r.reasoning_mode == ReasoningMode.SKELETON
        assert _no_legacy(r.answer_text)

    def test_out_of_scope_drafting_produces_skeleton_memo(self):
        r = answer("اكتب مذكرة بطلب استرداد رسوم رخصة قيادة.")
        assert r.domain == "general_skeleton"
        assert r.intent == Intent.DRAFTING
        assert r.drafting_mode == DraftingMode.SKELETON_DRAFT
        assert r.memo_text and _no_legacy(r.memo_text)

    def test_response_to_dict_has_required_keys(self):
        r = answer(TestEmploymentVsPartnership.Q_STRONG_EMPLOYMENT)
        d = r.to_dict()
        for key in (
            "runtime", "author", "answer", "memo", "domain", "intent",
            "reasoning_mode", "drafting_mode", "paths", "pivots",
            "evidence", "established_facts", "missing_facts", "is_skeleton",
        ):
            assert key in d, f"missing key {key!r} in Response.to_dict()"


# ═════════════════════════════════════════════════════════════════════
# ISOLATION TESTS — runtime_v2 must NOT import the legacy runtime
# ═════════════════════════════════════════════════════════════════════

class TestRuntimeV2Isolation:
    """Enforce that runtime_v2 does not depend on the legacy composer/
    pipeline modules. This is the 'no reuse' contract from the spec."""

    FORBIDDEN_IMPORTS = (
        "core.production_runtime",
        "core.fail_closed_pipeline",
        "core.answer_builder",
        "core.answer_mode",
        "core.legal_gates",
        "core.drafting",
        "core.output_sanitizer",
        "core.strategic_reasoning_engine",
    )

    def test_runtime_v2_modules_do_not_import_legacy(self):
        """AST-based check: inspect actual import statements (not
        docstrings or comments) for every runtime_v2 module."""
        import ast
        import core.runtime_v2 as pkg
        import core.runtime_v2.pipeline as p
        import core.runtime_v2.composer as c
        import core.runtime_v2.evidence as e
        import core.runtime_v2.domains as d
        import core.runtime_v2.types as t
        for mod in (pkg, p, c, e, d, t):
            src_file = getattr(mod, "__file__", "") or ""
            with open(src_file, "r", encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=src_file)
            # Walk every Import / ImportFrom node
            imported: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imported.add(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imported.add(node.module)
            for forbidden in self.FORBIDDEN_IMPORTS:
                # exact module or sub-module of a forbidden one
                hit = [m for m in imported
                        if m == forbidden or m.startswith(forbidden + ".")]
                assert not hit, (
                    f"{mod.__name__} imports legacy {forbidden!r}: {hit}"
                )

    def test_single_public_entry_point(self):
        import core.runtime_v2 as pkg
        # answer must be the ONE public function
        assert callable(pkg.answer)
        # to_dict of the Response is the only serialization path
        r = pkg.answer("")
        assert hasattr(r, "to_dict") and isinstance(r.to_dict(), dict)
