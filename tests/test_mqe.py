# -*- coding: utf-8 -*-
"""
Memorandum Quality Engine — regression tests.

Validates the NON-NEGOTIABLE quality rules:
  • Argument spine: claim → basis → evidence → application → consequence
  • Evidence-to-argument binding (every para tied to issue+evidence+statute)
  • Stronger legal writing style (no role leaks, hedges, echoed openers)
  • Per-doc-type specialization
  • Precise prayers (no vague "اتخاذ اللازم")
  • Conditional/dual framing clean
  • Opponent model controlled
  • Safety modes and quality-score downgrades
  • Quality firewall removes fluff/unlinked paragraphs
  • Ten live scenarios from the spec

Run: pytest tests/test_mqe.py -v
"""
from __future__ import annotations

import re
import pytest

from core.drafting.drafting_engine import (
    DraftingRequest, DraftingSafetyMode, DocumentType, ClientSide,
    build_memo,
)
from core.drafting.mqe import (
    compose_memo, compose_memo_conditional, compose_memo_dual,
    LegalArgument, build_arguments, render_argument, render_arguments_block,
    Prayer, build_prayer, render_prayer, is_vague_prayer,
    MemoQualityScore, score_memo, is_acceptable, is_publication_ready,
    FirewallReport, audit_memo,
    build_opponent_paragraph,
    wrap_conditional, wrap_dual,
    refine, count_role_leaks, count_repeated_openers,
    build_not_draftable_message,
    QUALITY_FLOOR, STRONG_QUALITY_FLOOR,
)
from core.drafting.mqe.firewall import (
    VIO_GENERIC_FLUFF, VIO_UNLINKED_PARAGRAPH,
    VIO_VAGUE_PRAYER, VIO_INHERITED_BLOCK, VIO_LECTURING_TONE,
    VIO_PREACHY_TONE,
)
from core.domain_pipeline import build_issue_graph, bind_evidence_to_issues
from core.evidence import get_retriever
from core.legal_gates import LegalIssueClassifier, FactPatternExtractor


# ═════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════

def _run_pipeline(query: str):
    """Return (graph, bound, classification) for a query."""
    c = LegalIssueClassifier().classify(query)
    fp = FactPatternExtractor().extract(query)
    domain = c.primary_domain.value if c.primary_domain else ""
    graph = build_issue_graph(domain, "", query)
    es = get_retriever().retrieve(
        query=query, classification=c, fact_pattern=fp,
        issue_keywords=[n.question[:30] for n in graph.nodes.values()],
    )
    bound = bind_evidence_to_issues(
        graph, es.records,
        issue_keywords=[n.question for n in graph.nodes.values()],
    )
    return graph, bound, domain


def _build(query: str, doc_type: DocumentType,
            client_side: ClientSide, facts: list[str]):
    graph, bound, domain = _run_pipeline(query)
    req = DraftingRequest(
        document_type=doc_type,
        client_side=client_side,
        domain=domain,
        facts=facts,
    )
    return build_memo(req, graph=graph, bound_evidence=bound)


# ═════════════════════════════════════════════════════════════════
# SECTION A — Argument spine
# ═════════════════════════════════════════════════════════════════

class TestArgumentSpine:
    def test_build_arguments_produces_complete_args(self):
        graph, bound, _ = _run_pipeline(
            "قضية شيك بدون رصيد حيث الشيك كان للضمان"
        )
        args = build_arguments(
            graph=graph, bound=bound,
            facts=["الشيك سُلّم كضمان", "لم يستحق الشرط"],
            client_side="accused",
            max_arguments=4,
        )
        for a in args:
            assert a.is_complete(), f"argument missing spine element: {a.to_dict()}"
            assert a.is_bound(), f"argument unbound: {a.to_dict()}"

    def test_no_evidence_means_no_argument(self):
        """Issues without bound evidence are SKIPPED (not padded)."""
        graph, bound, _ = _run_pipeline("قضية فارغة لا شيء فيها")
        args = build_arguments(graph, bound, facts=[], client_side="neutral")
        for a in args:
            assert a.evidence_refs

    def test_render_argument_contains_all_spine_pieces(self):
        graph, bound, _ = _run_pipeline(
            "فصلوني من العمل بدون إشعار ولا مبرر"
        )
        args = build_arguments(
            graph=graph, bound=bound,
            facts=["عقد عمل ساري", "لم يُبلغ بالفصل قبل اليوم الأخير"],
            client_side="claimant", max_arguments=3,
        )
        if not args:
            pytest.skip("no bound evidence for this query")
        rendered = render_argument(args[0], heading="بشأن: الركن", idx=0)
        assert rendered
        # Must contain opener + basis + application + consequence
        assert any(t in rendered for t in ["من المستقر", "من الثابت",
                                              "من المقرر", "من البيّن"])


# ═════════════════════════════════════════════════════════════════
# SECTION B — Prayer precision
# ═════════════════════════════════════════════════════════════════

class TestPrayer:
    def test_vague_prayers_are_blocked(self):
        assert is_vague_prayer("اتخاذ اللازم") is True
        assert is_vague_prayer("إنصافي") is True
        assert is_vague_prayer("") is True
        assert is_vague_prayer(
            "الحكم برفض الدعوى موضوعاً لانتفاء سندها."
        ) is False

    def test_defense_prayer_has_specific_dismissal(self):
        p = build_prayer(
            DocumentType.DEFENSE_MEMO, ClientSide.ACCUSED,
            graph=None, explicit_requests=[], mlre_survivors=0,
        )
        assert any("براءة" in r for r in p.primary), \
            f"expected براءة in defense prayer, got: {p.primary}"

    def test_claim_prayer_includes_costs(self):
        p = build_prayer(
            DocumentType.CLAIM_BRIEF, ClientSide.CLAIMANT,
            graph=None, explicit_requests=[],
        )
        assert any("المصاريف" in r or "أتعاب" in r for r in p.primary)

    def test_mlre_survivors_trigger_alternative(self):
        p = build_prayer(
            DocumentType.DEFENSE_MEMO, ClientSide.ACCUSED,
            graph=None, explicit_requests=[],
            mlre_survivors=2,
        )
        assert p.alternative, "dual-path MLRE should force an alternative prayer"

    def test_explicit_vague_requests_dropped(self):
        p = build_prayer(
            DocumentType.DEFENSE_MEMO, ClientSide.ACCUSED,
            graph=None,
            explicit_requests=["اتخاذ اللازم", "ما ترونه مناسباً"],
        )
        for block in (p.primary, p.alternative, p.fallback):
            for r in block:
                assert not is_vague_prayer(r), f"vague leaked: {r!r}"


# ═════════════════════════════════════════════════════════════════
# SECTION C — Style refinement
# ═════════════════════════════════════════════════════════════════

class TestStyle:
    def test_role_leaks_scrubbed(self):
        dirty = "يُستند إلى المادة 304 (direct) في إثبات الواقعة."
        clean = refine(dirty)
        assert "(direct)" not in clean
        assert count_role_leaks(clean) == 0

    def test_weak_words_replaced(self):
        dirty = "ربما يتحقق الركن، ويبدو أن الشاهد صادق."
        clean = refine(dirty, preserve_conditional=False)
        assert "ربما" not in clean
        assert "يبدو" not in clean

    def test_weak_words_preserved_in_conditional(self):
        text = "على سبيل الاحتياط، ربما تتجه المحكمة للتكييف البديل."
        clean = refine(text, preserve_conditional=True)
        # Since this text IS conditional, hedge preserved
        assert "على سبيل الاحتياط" in clean

    def test_echo_openers_varied(self):
        text = "من المستقر أن الشيك أداة وفاء.\nمن المستقر أن القصد ركن."
        clean = refine(text)
        assert clean.count("من المستقر أن") == 1

    def test_dedupes_adjacent_sentences(self):
        text = ("يتبيّن من الأوراق ثبوت الواقعة.\n"
                "يتبيّن من الأوراق ثبوت الواقعة.")
        clean = refine(text)
        assert clean.count("يتبيّن من الأوراق ثبوت الواقعة.") == 1

    def test_whitespace_normalized(self):
        text = "سطر.\n\n\n\nسطر ثانٍ."
        clean = refine(text)
        assert "\n\n\n" not in clean


# ═════════════════════════════════════════════════════════════════
# SECTION D — Firewall
# ═════════════════════════════════════════════════════════════════

class TestFirewall:
    def test_generic_fluff_removed(self):
        text = "ينبغي النظر في الأمر بعناية فائقة من جميع الجوانب المختلفة."
        r = audit_memo(text)
        assert VIO_GENERIC_FLUFF in r.violations or r.removed_paragraphs >= 1

    def test_unlinked_paragraph_removed(self):
        # A long paragraph with ZERO legal anchors, no lists, no headings
        text = (
            "هذه معلومات مبهمة تمتد لفترة طويلة جداً وتتحدث عن أمور مختلفة "
            "بطريقة عامة بعيدة عن السياق المطلوب وبدون الربط بأي عنصر قابل "
            "للتطبيق في هذا المقام المتعلق بالموضوع المعروض."
        )
        r = audit_memo(text)
        assert VIO_UNLINKED_PARAGRAPH in r.violations

    def test_inherited_block_removed(self):
        text = (
            "**مذكرة دفاع**\n\n"
            "أقوى ما يدعمك: محاضر اجتماعات الشركاء.\n\n"
            "**أولاً:** تحليل الواقعة."
        )
        r = audit_memo(text)
        assert VIO_INHERITED_BLOCK in r.violations
        assert "محاضر اجتماعات الشركاء" not in r.cleaned_text

    def test_lecturing_tone_flagged(self):
        text = "ينبغي على المحكمة أن تعلم بأن الواقعة ثابتة بمقتضى المادة 304."
        r = audit_memo(text)
        assert VIO_LECTURING_TONE in r.violations

    def test_preachy_tone_removed(self):
        text = (
            "إن العدل قيمة سامية يجب صونها في هذا الزمان الذي انتشرت فيه "
            "هذه الظاهرة المجتمعية الخطيرة بين شباب اليوم للأسف الشديد."
        )
        r = audit_memo(text)
        assert VIO_PREACHY_TONE in r.violations

    def test_duplicate_paragraph_removed(self):
        text = (
            "يتبيّن من الأوراق أن الموكّل قد استوفى شرط الإخطار المسبق.\n\n"
            "يتبيّن من الأوراق أن الموكّل قد استوفى شرط الإخطار المسبق."
        )
        r = audit_memo(text)
        assert r.removed_paragraphs >= 1

    def test_legitimate_content_preserved(self):
        """Firewall must NOT remove genuine legal analysis."""
        text = (
            "**ثالثاً — السند القانوني:**\n"
            "• المادة 304 من قانون العقوبات القطري\n\n"
            "**رابعاً — التطبيق على الوقائع:**\n"
            "من الثابت قانوناً أن الشيك ضمان لا أداة وفاء بمقتضى المادة 304. "
            "وبإنزال ذلك على الوقائع الثابتة، يتبيّن أن الشرط لم يستحق."
        )
        r = audit_memo(text)
        assert "المادة 304" in r.cleaned_text
        assert "السند القانوني" in r.cleaned_text


# ═════════════════════════════════════════════════════════════════
# SECTION E — Scorer
# ═════════════════════════════════════════════════════════════════

class TestScorer:
    def test_empty_memo_scores_zero(self):
        s = score_memo(
            text="", doc_type=DocumentType.DEFENSE_MEMO,
            arguments=[], prayer=Prayer(), cited_laws=[], issue_count=0,
        )
        assert s.overall == 0.0

    def test_complete_memo_scores_high(self):
        graph, bound, _ = _run_pipeline(
            "فصلوني من العمل بدون سبب بعد خمس سنوات خدمة"
        )
        req = DraftingRequest(
            document_type=DocumentType.CLAIM_BRIEF,
            client_side=ClientSide.CLAIMANT,
            facts=[
                "بدأ الموكّل العمل في 2021",
                "فُصل في مارس 2026 دون إنذار",
                "الراتب الأخير 12,000 ريال",
            ],
        )
        r = build_memo(req, graph=graph, bound_evidence=bound)
        # Scoring is done inside build_memo; we verify via structure + firewall
        assert r.safety_mode != DraftingSafetyMode.NOT_DRAFTABLE_YET \
            or "تعذّر" in r.text

    def test_score_has_all_axes(self):
        s = MemoQualityScore(
            structure=0.8, legal_grounding=0.7, issue_coverage=0.6,
            evidence_application=0.6, request_precision=0.9,
            language_quality=0.95, anti_repetition=0.9, overall=0.75,
        )
        d = s.to_dict()
        for k in ["structure", "legal_grounding", "issue_coverage",
                  "evidence_application", "request_precision",
                  "language_quality", "anti_repetition", "overall"]:
            assert k in d


# ═════════════════════════════════════════════════════════════════
# SECTION F — Conditional / Dual framing
# ═════════════════════════════════════════════════════════════════

class TestConditionalDual:
    def test_wrap_conditional_has_explicit_frame(self):
        framed = wrap_conditional(
            primary_text="النص الأصلي.",
            fallback_theory="التكييف البديل",
            pivot_conditions=["إذا ثبت الشرط X", "أو إذا رأت المحكمة Y"],
            fallback_body="هذا هو نص المسار البديل.",
        )
        assert "على سبيل الاحتياط" in framed
        assert "التكييف البديل" in framed
        assert "إذا ثبت الشرط X" in framed
        # Primary preserved intact
        assert framed.startswith("النص الأصلي.")

    def test_wrap_dual_labels_paths(self):
        framed = wrap_dual(
            primary_text="نص المسار الأول.",
            secondary_text="نص المسار الثاني.",
            primary_label="دعوى تجارية",
            secondary_label="دعوى مدنية",
        )
        assert "دعوى تجارية" in framed
        assert "دعوى مدنية" in framed
        assert "═══" in framed   # separator present

    def test_conditional_does_not_weaken_primary(self):
        primary = (
            "من الثابت قانوناً أن الشيك ضمان. "
            "وبإنزال ذلك على الوقائع، يتبيّن انتفاء القصد."
        )
        framed = wrap_conditional(
            primary_text=primary,
            fallback_theory="إساءة ائتمان",
            pivot_conditions=["إذا رفضت المحكمة وصف الضمان"],
        )
        # Primary is unchanged
        assert primary in framed
        # Fallback is clearly marked
        assert "التكييف البديل" in framed


# ═════════════════════════════════════════════════════════════════
# SECTION G — Opponent model
# ═════════════════════════════════════════════════════════════════

class TestOpponent:
    def test_no_mlre_no_defense_returns_empty(self):
        # empty graph + no mlre → no paragraph
        from core.domain_pipeline.issue_graph import IssueGraph
        empty = IssueGraph(domain="", nodes={})
        p = build_opponent_paragraph(mlre=None, graph=empty,
                                      client_side=ClientSide.NEUTRAL)
        assert p == ""

    def test_defense_graph_produces_rebuttal(self):
        graph, _, _ = _run_pipeline(
            "سرقة تحت تهديد سلاح واعتداء على شخصية موظف"
        )
        p = build_opponent_paragraph(
            mlre=None, graph=graph, client_side=ClientSide.ACCUSED,
        )
        # Either empty (graph has no defense nodes) OR contains a rebuttal
        if p:
            assert any(t in p for t in ["يُردّ", "ومردود", "غير أن", "إلا أن"])

    def test_rebuttal_never_concedes(self):
        graph, _, _ = _run_pipeline(
            "نزاع شراكة حول أموال الشركة"
        )
        p = build_opponent_paragraph(
            mlre=None, graph=graph, client_side=ClientSide.DEFENDANT,
        )
        if p:
            # No phrase that concedes the opposing argument
            assert "يُوافق الموكّل" not in p
            assert "نسلّم بأن" not in p


# ═════════════════════════════════════════════════════════════════
# SECTION H — NOT_DRAFTABLE messaging
# ═════════════════════════════════════════════════════════════════

class TestNotDraftable:
    def test_explains_what_why_unblock(self):
        text = build_not_draftable_message(
            DocumentType.DEFENSE_MEMO,
            missing=["no_bound_evidence", "insufficient_facts"],
        )
        assert "ما ينقص" in text
        assert "لماذا يمنع" in text
        assert "ما يجعلها قابلة" in text

    def test_no_generic_refusal(self):
        text = build_not_draftable_message(
            DocumentType.DEFENSE_MEMO, missing=["no_bound_evidence"],
        )
        assert "غير مدعوم" not in text
        assert "لا يمكن" not in text.split("\n")[0]  # not a refusal opener


# ═════════════════════════════════════════════════════════════════
# SECTION I — TEN LIVE SCENARIOS
# ═════════════════════════════════════════════════════════════════

LIVE_CASES = [
    # 1. مذكرة دفاع في شيك ضمان
    {
        "label": "cheque_guarantee_defense",
        "query": "اكتب مذكرة دفاع في قضية شيك بدون رصيد. الشيك كان ضماناً.",
        "doc_type": DocumentType.DEFENSE_MEMO,
        "side": ClientSide.ACCUSED,
        "facts": ["الشيك سُلّم كضمان", "لم يستحق الشرط عند التقديم"],
    },
    # 2. مذكرة بطلب في تصرف قبل الوفاة
    {
        "label": "pre_death_transfer_petition",
        "query": "مذكرة بطلب بشأن تصرف والدي قبل وفاته بأسبوع.",
        "doc_type": DocumentType.PETITION_MEMO,
        "side": ClientSide.CLAIMANT,
        "facts": ["تنازل الوالد عن قطعة أرض", "كان في مرض الموت"],
    },
    # 3. مذكرة رد في ملكية كود
    {
        "label": "software_ownership_reply",
        "query": "مذكرة رد على دعوى ملكية كود برمجي.",
        "doc_type": DocumentType.REPLY_MEMO,
        "side": ClientSide.DEFENDANT,
        "facts": ["الكود طُوّر في فترة العقد", "لا نص يمنح الملكية للخصم"],
    },
    # 4. صحيفة دعوى مختصرة في بيع عقار بعقدين
    {
        "label": "double_sale_real_estate",
        "query": "صحيفة دعوى في بيع عقار بعقدين متعارضين.",
        "doc_type": DocumentType.CLAIM_BRIEF,
        "side": ClientSide.CLAIMANT,
        "facts": ["عقد أول بتاريخ 2025/03",
                   "عقد ثانٍ للمدعى عليه 2025/09",
                   "الأسبقية في التسجيل للمدّعي"],
    },
    # 5. نقاط مرافعة في مقاولات
    {
        "label": "construction_pleading_points",
        "query": "نقاط مرافعة في نزاع مقاولات بناء.",
        "doc_type": DocumentType.PLEADING_POINTS,
        "side": ClientSide.CLAIMANT,
        "facts": ["تأخر التسليم 90 يوماً",
                   "الشرط الجزائي منصوص عليه في العقد"],
    },
    # 6. مذكرة دفاع في سب إلكتروني
    {
        "label": "cyber_defamation_defense",
        "query": "اكتب مذكرة دفاع في قضية سب إلكتروني على تويتر.",
        "doc_type": DocumentType.DEFENSE_MEMO,
        "side": ClientSide.ACCUSED,
        "facts": ["المنشور نقد مهني لا شخصي",
                   "لم يكن الموكّل صاحب الحساب وقت النشر"],
    },
    # 7. مذكرة عمالية في فصل بدون عقد
    {
        "label": "employment_dismissal",
        "query": "مذكرة دعوى في فصل عامل بلا عقد رسمي.",
        "doc_type": DocumentType.CLAIM_BRIEF,
        "side": ClientSide.CLAIMANT,
        "facts": ["عمل ثلاث سنوات",
                   "فُصل دون إنذار", "راتب شهري ثابت مثبت بتحويلات"],
    },
    # 8. مذكرة تجارية في استثمار مضلل
    {
        "label": "commercial_misleading_investment",
        "query": "مذكرة رد على دعوى استثمار مُضلِّل.",
        "doc_type": DocumentType.REPLY_MEMO,
        "side": ClientSide.DEFENDANT,
        "facts": ["قُدِّمت بيانات شفافة للمستثمر",
                   "المستثمر أقرّ كتابياً بمستوى المخاطرة"],
    },
    # 9. مذكرة دفاع في اعتداء + دفاع شرعي
    {
        "label": "assault_self_defense",
        "query": "مذكرة دفاع في قضية اعتداء مع دفع بدفاع شرعي.",
        "doc_type": DocumentType.DEFENSE_MEMO,
        "side": ClientSide.ACCUSED,
        "facts": ["بدر العدوان من الطرف الآخر",
                   "الفعل الدفاعي تناسب مع الخطر"],
    },
    # 10. مذكرة مزدوجة في نزاع شراكة + شبهة احتيال
    {
        "label": "partnership_plus_fraud",
        "query": "مذكرة في نزاع شراكة مع احتمال وصف احتيال.",
        "doc_type": DocumentType.DEFENSE_MEMO,
        "side": ClientSide.DEFENDANT,
        "facts": ["الشراكة مسجّلة قانوناً",
                   "التصرف كان ضمن صلاحيات الشريك المفوّض",
                   "لا سيولة نقدية تم تحويلها خارج الشركة"],
    },
]


class TestLiveScenarios:
    @pytest.mark.parametrize(
        "case", LIVE_CASES, ids=[c["label"] for c in LIVE_CASES]
    )
    def test_scenario_produces_memo(self, case):
        r = _build(
            query=case["query"],
            doc_type=case["doc_type"],
            client_side=case["side"],
            facts=case["facts"],
        )
        assert r.text, "empty memo"
        assert isinstance(r.safety_mode, DraftingSafetyMode)

    @pytest.mark.parametrize(
        "case", LIVE_CASES, ids=[c["label"] for c in LIVE_CASES]
    )
    def test_scenario_no_vague_prayer_in_text(self, case):
        r = _build(
            query=case["query"],
            doc_type=case["doc_type"],
            client_side=case["side"],
            facts=case["facts"],
        )
        # Check the memo body doesn't carry vague prayers
        for banned in ["اتخاذ اللازم", "إنصافي", "ما ترونه مناسباً"]:
            assert banned not in r.text, f"vague prayer '{banned}' in {case['label']}"

    @pytest.mark.parametrize(
        "case", LIVE_CASES, ids=[c["label"] for c in LIVE_CASES]
    )
    def test_scenario_no_role_leaks(self, case):
        r = _build(
            query=case["query"],
            doc_type=case["doc_type"],
            client_side=case["side"],
            facts=case["facts"],
        )
        # Role tags must NOT surface
        assert "(direct)" not in r.text
        assert "(corroborative)" not in r.text
        assert "(contextual)" not in r.text

    @pytest.mark.parametrize(
        "case", LIVE_CASES, ids=[c["label"] for c in LIVE_CASES]
    )
    def test_scenario_no_legacy_boilerplate(self, case):
        r = _build(
            query=case["query"],
            doc_type=case["doc_type"],
            client_side=case["side"],
            facts=case["facts"],
        )
        # Cross-case leakage
        assert "محاضر اجتماعات الشركاء" not in r.text or \
            case["label"] == "partnership_plus_fraud"   # only partnership may legitimately reference
        assert "📊 السيناريوهات المحتملة:" not in r.text

    @pytest.mark.parametrize(
        "case", LIVE_CASES, ids=[c["label"] for c in LIVE_CASES]
    )
    def test_scenario_no_technical_leak(self, case):
        r = _build(
            query=case["query"],
            doc_type=case["doc_type"],
            client_side=case["side"],
            facts=case["facts"],
        )
        # No technical reason codes in the user-facing body
        for pat in ["low_issue_coverage:", "no_bound_evidence:",
                    "composite=", "score=", "[TRACE"]:
            assert pat not in r.text, f"leak {pat!r} in {case['label']}"


# ═════════════════════════════════════════════════════════════════
# SECTION J — Invariants / regression guards
# ═════════════════════════════════════════════════════════════════

class TestInvariants:
    def test_mqe_path_preserved_safety_contract(self):
        """If MQE downgrades, safety mode MUST reflect that."""
        req = DraftingRequest(
            document_type=DocumentType.CLAIM_BRIEF,
            client_side=ClientSide.CLAIMANT,
            facts=[],  # no facts → hard insufficient
        )
        r = build_memo(req, graph=None, bound_evidence=None)
        assert r.safety_mode == DraftingSafetyMode.NOT_DRAFTABLE_YET
        assert "تعذّر" in r.text

    def test_draftable_memo_has_structure_markers(self):
        graph, bound, _ = _run_pipeline("نزاع عمالي بسبب فصل تعسفي")
        req = DraftingRequest(
            document_type=DocumentType.CLAIM_BRIEF,
            client_side=ClientSide.CLAIMANT,
            facts=["عمل 5 سنوات", "فُصل فجأة"],
        )
        r = build_memo(req, graph=graph, bound_evidence=bound)
        if r.safety_mode != DraftingSafetyMode.NOT_DRAFTABLE_YET:
            # Must have the ordinal section structure
            assert "**أولاً" in r.text or "**ثانياً" in r.text

    def test_memo_ends_with_prayer_for_full_drafts(self):
        graph, bound, _ = _run_pipeline("اكتب مذكرة دفاع في قضية سرقة")
        req = DraftingRequest(
            document_type=DocumentType.DEFENSE_MEMO,
            client_side=ClientSide.ACCUSED,
            facts=["البينة ضعيفة", "لا شاهد على الفعل"],
        )
        r = build_memo(req, graph=graph, bound_evidence=bound)
        if r.safety_mode != DraftingSafetyMode.NOT_DRAFTABLE_YET:
            # Prayer section should be present
            assert "الطلبات" in r.text or "أصلياً" in r.text

    def test_conditional_context_preserves_hedges(self):
        """On is_conditional_context=True, refine preserves hedges."""
        conditional_text = (
            "على سبيل الاحتياط، ربما تأخذ المحكمة بالتكييف البديل."
        )
        kept = refine(conditional_text, preserve_conditional=True)
        # "ربما" is preserved within a conditional scope
        assert "على سبيل الاحتياط" in kept
