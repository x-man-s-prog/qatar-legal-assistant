# -*- coding: utf-8 -*-
"""
Professional Advocate Style Layer (PASL) — regression tests.

Verifies the NON-NEGOTIABLE rules:
  • No facts, no statute, no argument spine are altered
  • Section count, citation count, fact-bullet count are preserved
  • Conditional/fallback sections retain hedged language
  • Weak/hedged phrasing in primary sections is replaced
  • Prayer gets a canonical opener
  • Conclusion gets a strong synthesis marker (or keeps MQE's if present)
  • Burden-of-proof gets a high-impact line (once)
  • Style score does NOT regress below the original
  • Integration with build_memo → MQE → PASL

Run: pytest tests/test_pasl.py -v
"""
from __future__ import annotations

import re
import pytest

from core.drafting.drafting_engine import (
    DraftingRequest, DocumentType, ClientSide, DraftingSafetyMode,
    build_memo,
)
from core.drafting.pasl import (
    polish, PASLResult,
    StyleScore, score_style, STYLE_FLOOR, STRONG_STYLE_CEILING,
    parse_memo, rebuild_memo, section_count, citation_count,
    fact_bullet_count,
)
from core.drafting.pasl.section_parser import (
    KIND_APPLICATION, KIND_CONDITIONAL, KIND_CONCLUSION,
    KIND_PRAYER, KIND_PROOF_BURDEN, KIND_OPPONENT,
)
from core.drafting.pasl import (
    precision, emphasis, flow, opponent_pressure, burden_emphasis,
    conclusion_power, prayer_polish, conditional_tone, anti_pattern,
)


# ═════════════════════════════════════════════════════════════════
# Synthetic memo fixture (avoids retrieval cost in style-only tests)
# ═════════════════════════════════════════════════════════════════

SYNTHETIC_MEMO = """\
**مذكرة دفاع**

**أولاً — الأطراف والصفة الإجرائية:**

مقدَّمة من المتّهم

**ثانياً — موجز الوقائع ذات الصلة:**

(1) حرر الموكّل شيكاً بتاريخ 2026/01/01
(2) الشيك سُلّم على سبيل الضمان لا الوفاء

**ثالثاً — المسائل القانونية المطروحة:**

(1) (جوهرية) هل تحقق الشرط قبل الصرف؟
(2) (تمهيدية) هل الشيك ضمان أم أداة وفاء؟

**رابعاً — السند القانوني الحاكم:**

• المادة 357 من قانون العقوبات القطري
• حكم قضائي — 1607

**خامساً — التطبيق على الوقائع:**

**(1) بشأن: الشيك ضمان لا أداة وفاء**
من المستقر أن الشيك ضمان لا أداة وفاء بمقتضى المادة 357.
وبإنزال هذه القاعدة على الوقائع، ظهر أن الشيك سُلّم كضمان.
ولذلك فإن انتفاء القصد ثابت.

**(2) بشأن: الصرف قبل الشرط إساءة استعمال**
من المستقر أن الصرف قبل الشرط يعدّ إساءة استعمال بمقتضى حكم قضائي — 1607.
يبدو أن المستفيد قام بالصرف قبل تحقق الشرط.
ولذلك فإن الفعل غير مشروع.

**سادساً — عبء الإثبات:**

الأصل أن عبء إثبات ادعاء الخصم يقع على عاتقه.

**سابعاً — الخلاصة القانونية:**

ادعاء الخصم لا ينهض.

**ثامناً — الطلبات:**

— أصلياً:
 • الحكم ببراءة المتّهم.
 • إلزام الطرف الآخر بالمصاريف.
— احتياطياً:
 • ندب خبير مختص.
"""


# ═════════════════════════════════════════════════════════════════
# SECTION A — Section parser
# ═════════════════════════════════════════════════════════════════

class TestSectionParser:
    def test_parses_all_sections(self):
        parsed = parse_memo(SYNTHETIC_MEMO)
        kinds = parsed.all_kinds()
        assert "parties"      in kinds
        assert "facts"        in kinds
        assert "issues"       in kinds
        assert "statute"      in kinds
        assert "application"  in kinds
        assert "proof_burden" in kinds
        assert "conclusion"   in kinds
        assert "prayer"       in kinds

    def test_rebuild_is_idempotent(self):
        parsed = parse_memo(SYNTHETIC_MEMO)
        rebuilt = rebuild_memo(parsed)
        # Section count preserved
        assert section_count(rebuilt) == section_count(SYNTHETIC_MEMO)

    def test_handles_empty_input(self):
        parsed = parse_memo("")
        assert parsed.segments == []

    def test_unstructured_text_has_no_segments(self):
        parsed = parse_memo("فقرة حرة بدون هيكل قانوني.")
        assert parsed.segments == []


# ═════════════════════════════════════════════════════════════════
# SECTION B — Invariant preservation (CRITICAL)
# ═════════════════════════════════════════════════════════════════

class TestInvariants:
    def test_section_count_preserved(self):
        r = polish(SYNTHETIC_MEMO, client_side="accused")
        assert section_count(r.text) == section_count(SYNTHETIC_MEMO)

    def test_citation_count_preserved(self):
        r = polish(SYNTHETIC_MEMO, client_side="accused")
        assert citation_count(r.text) >= citation_count(SYNTHETIC_MEMO)

    def test_fact_bullets_preserved(self):
        r = polish(SYNTHETIC_MEMO, client_side="accused")
        assert fact_bullet_count(r.text) >= fact_bullet_count(SYNTHETIC_MEMO)

    def test_no_rollback_on_standard_memo(self):
        r = polish(SYNTHETIC_MEMO, client_side="accused")
        assert r.rolled_back is False

    def test_empty_input_short_circuits(self):
        r = polish("", client_side="neutral")
        assert r.text == ""
        assert r.applied_passes == []

    def test_not_draftable_text_not_mangled(self):
        msg = (
            "**تعذّر صياغة مذكرة دفاع في الوقت الحالي — المسار غير مكتمل.**\n\n"
            "**ما ينقص حالياً:**\n"
            "• لم يتحدَّد المجال القانوني."
        )
        r = polish(msg, client_side="accused")
        # Text is either passed-through or gently tightened, never destroyed
        assert r.text != ""
        # Structure markers preserved
        assert "تعذّر" in r.text
        assert "ما ينقص" in r.text


# ═════════════════════════════════════════════════════════════════
# SECTION C — Precision (weak → decisive)
# ═════════════════════════════════════════════════════════════════

class TestPrecision:
    def test_tightens_weak_phrasing(self):
        text = "من الواضح أن الواقعة ثابتة، ومن المعلوم أن القصد منتفٍ."
        out = precision.tighten(text, is_conditional_context=False)
        assert "من الواضح" not in out
        assert "من المعلوم" not in out
        assert "الثابت" in out or "المستقر" in out

    def test_colloquial_intensifiers_replaced(self):
        text = "الفعل واضح بشكل كبير وجلي بشكل واضح."
        out = precision.tighten(text)
        assert "بشكل كبير" not in out
        assert "بشكل واضح" not in out
        assert "جوهرية" in out or "بوضوح" in out

    def test_conditional_context_exempt(self):
        text = "من الواضح أن المسار البديل قائم."
        out = precision.tighten(text, is_conditional_context=True)
        # Nothing changed
        assert out == text

    def test_preserves_arabic_prefix(self):
        text = "ومن الواضح أن القصد منتفٍ."
        out = precision.tighten(text)
        # "و" must stay
        assert out.startswith("و")


# ═════════════════════════════════════════════════════════════════
# SECTION D — Emphasis (argument leads)
# ═════════════════════════════════════════════════════════════════

class TestEmphasis:
    def test_bland_lead_replaced(self):
        text = (
            "**(1) بشأن: س**\n"
            "يثبت أن القصد منتفٍ.\n"
            "ولذلك فإن الفعل غير مجرَّم."
        )
        out = emphasis.strengthen_argument_leads(text, base_idx=0)
        # "يثبت أن" replaced
        assert not out.startswith("يثبت أن")
        assert any(lead in out for lead in [
            "الثابت من الأوراق أن",
            "ومؤدى ذلك أن",
            "والمستفاد من الوقائع أن",
        ])

    def test_count_bland_leads(self):
        text = (
            "يثبت أن الشيك ضمان.\n\n"
            "يظهر أن البينة ضعيفة."
        )
        before = emphasis.count_bland_leads(text)
        out = emphasis.strengthen_argument_leads(text)
        after = emphasis.count_bland_leads(out)
        assert after < before


# ═════════════════════════════════════════════════════════════════
# SECTION E — Flow (transitions between arguments)
# ═════════════════════════════════════════════════════════════════

class TestFlow:
    def test_adds_transition_between_arg_headings(self):
        body = (
            "**(1) بشأن: الأول**\n"
            "فقرة أولى.\n\n"
            "**(2) بشأن: الثاني**\n"
            "فقرة ثانية."
        )
        out = flow.smooth_between_arguments(body, base_idx=0)
        # A transition phrase was inserted
        assert any(t in out for t in [
            "وبالانتقال إلى", "أما عن", "وفي الشأن ذاته",
            "وعلى هذا الأساس",
        ])

    def test_does_not_touch_structural_lines(self):
        body = "• بند\n• بند آخر"
        out = flow.smooth_between_arguments(body, base_idx=0)
        assert "• بند" in out
        assert "• بند آخر" in out

    def test_conclusion_lead_skipped_if_mqe_already_has_one(self):
        body = "يتبيّن مما تقدَّم أن الموقف واضح."
        out = flow.add_section_lead(body, kind="conclusion")
        # Should NOT prepend another transition
        assert out == body

    def test_prayer_gets_lead_when_missing(self):
        body = "أصلياً: الحكم بالبراءة."
        out = flow.add_section_lead(body, kind="prayer")
        assert "ولهذه الأسباب" in out or "أصلياً" in out


# ═════════════════════════════════════════════════════════════════
# SECTION F — Opponent pressure
# ═════════════════════════════════════════════════════════════════

class TestOpponent:
    def test_insert_rebuttal_if_missing(self):
        body = "قد يتمسّك الخصم بأن الشيك أداة وفاء."
        out = opponent_pressure.polish_opponent_block(body)
        assert any(t in out for t in [
            "ويُردّ", "ومردود", "غير أن", "إلا أن", "لا ينهض",
        ])

    def test_rebuttal_preserved_when_present(self):
        body = (
            "قد يتمسّك الخصم بأن الشيك أداة وفاء.\n"
            "ومردود هذا الدفع بأن اتفاق الضمان مثبت."
        )
        out = opponent_pressure.polish_opponent_block(body)
        assert "ومردود" in out or "غير أن" in out


# ═════════════════════════════════════════════════════════════════
# SECTION G — Burden of proof
# ═════════════════════════════════════════════════════════════════

class TestBurden:
    def test_adds_high_impact_line_for_defense(self):
        body = "الأصل أن عبء إثبات ادعاء الخصم يقع على عاتقه."
        out = burden_emphasis.polish_burden_block(
            body, client_side="accused", base_idx=0,
        )
        # Should add a high-impact phrase
        assert any(t in out for t in [
            "ولم يقدِّم", "خلوُّ الأوراق", "ولمّا كان الإثبات",
            "مجرد الاحتمال",
        ])

    def test_idempotent_when_already_strong(self):
        body = (
            "الأصل أن عبء إثبات ادعاء الخصم يقع على عاتقه. "
            "ولم يقدِّم الخصم ما يثبت ركن القصد على وجه الجزم."
        )
        out = burden_emphasis.polish_burden_block(
            body, client_side="accused",
        )
        # Already has high-impact — should NOT add another
        assert out.count("ولم يقدِّم") == 1


# ═════════════════════════════════════════════════════════════════
# SECTION H — Conclusion power
# ═════════════════════════════════════════════════════════════════

class TestConclusion:
    def test_weak_conclusion_gets_closer(self):
        body = "ادعاء الخصم لا ينهض."
        out = conclusion_power.polish_conclusion(body, client_side="accused")
        assert any(m in out for m in [
            "وبناءً على ما تقدَّم",
            "تأسيساً على ما تقدَّم",
        ])

    def test_strong_conclusion_preserved(self):
        body = "يتبيّن مما تقدَّم أن المسألة واضحة."
        out = conclusion_power.polish_conclusion(body, client_side="accused")
        # Already has strong marker — pass through
        assert out == body


# ═════════════════════════════════════════════════════════════════
# SECTION I — Prayer polish
# ═════════════════════════════════════════════════════════════════

class TestPrayer:
    def test_opener_prepended_when_missing(self):
        body = "— أصلياً:\n • الحكم بالبراءة."
        out = prayer_polish.polish_prayer_block(body)
        assert out.startswith("لذلك،") or out.startswith("يلتمس")

    def test_preserves_prayer_items(self):
        body = (
            "— أصلياً:\n"
            " • الحكم بالبراءة.\n"
            " • إلزام الطرف الآخر بالمصاريف."
        )
        out = prayer_polish.polish_prayer_block(body)
        assert "الحكم بالبراءة" in out
        assert "إلزام الطرف الآخر بالمصاريف" in out


# ═════════════════════════════════════════════════════════════════
# SECTION J — Conditional tone
# ═════════════════════════════════════════════════════════════════

class TestConditionalTone:
    def test_softens_decisive_phrases_in_fallback(self):
        body = (
            "وعلى سبيل الاحتياط، الثابت أن التكييف البديل يصلح.\n"
            "من الثابت قانوناً أن الوقائع تؤيد ذلك."
        )
        out = conditional_tone.polish_conditional_block(body)
        # Decisive markers softened (not all replaced, but at least one)
        assert "الثابت أن" not in out \
            or out.count("الثابت أن") < body.count("الثابت أن")
        # Hedge preserved
        assert "على سبيل الاحتياط" in out

    def test_non_conditional_block_untouched(self):
        body = "الثابت أن الواقعة قائمة."
        out = conditional_tone.polish_conditional_block(body)
        assert out == body


# ═════════════════════════════════════════════════════════════════
# SECTION K — Anti-pattern breaker
# ═════════════════════════════════════════════════════════════════

class TestAntiPattern:
    def test_rotates_repeated_openers(self):
        body = (
            "من المستقر أن X.\n\n"
            "من المستقر أن Y.\n\n"
            "من المستقر أن Z."
        )
        out = anti_pattern.break_opener_patterns(body)
        # At least two distinct openers after rotation
        first_words = [p.split()[0:3] for p in out.split("\n\n") if p.strip()]
        first_phrases = [" ".join(w) for w in first_words]
        assert len(set(first_phrases)) >= 2

    def test_preserves_non_opener_lines(self):
        body = "**عنوان**\n\nنص عادي."
        out = anti_pattern.break_opener_patterns(body)
        assert "**عنوان**" in out


# ═════════════════════════════════════════════════════════════════
# SECTION L — Style scorer
# ═════════════════════════════════════════════════════════════════

class TestStyleScorer:
    def test_scoring_returns_all_axes(self):
        s = score_style(SYNTHETIC_MEMO)
        d = s.to_dict()
        for k in ["persuasion_strength", "clarity", "flow",
                  "variation", "professionalism", "overall"]:
            assert k in d

    def test_score_improves_after_polish(self):
        r = polish(SYNTHETIC_MEMO, client_side="accused")
        assert r.style_before is not None
        assert r.style_after is not None
        # PASL should NOT regress the score
        assert r.style_after.overall >= r.style_before.overall - 0.05

    def test_empty_text_scores_zero(self):
        s = score_style("")
        assert s.overall == 0.0


# ═════════════════════════════════════════════════════════════════
# SECTION M — Full orchestrator
# ═════════════════════════════════════════════════════════════════

class TestOrchestrator:
    def test_applies_multiple_passes(self):
        r = polish(SYNTHETIC_MEMO, client_side="accused")
        assert len(r.applied_passes) >= 2

    def test_output_preserves_citations(self):
        r = polish(SYNTHETIC_MEMO, client_side="accused")
        assert "المادة 357" in r.text
        assert "حكم قضائي — 1607" in r.text

    def test_output_preserves_facts(self):
        r = polish(SYNTHETIC_MEMO, client_side="accused")
        assert "حرر الموكّل شيكاً بتاريخ 2026/01/01" in r.text
        assert "الشيك سُلّم على سبيل الضمان" in r.text

    def test_conditional_memo_preserves_fallback_frame(self):
        text = SYNTHETIC_MEMO + (
            "\n\n**تاسعاً — على سبيل الاحتياط — المسار البديل:**\n\n"
            "وعلى سبيل الاحتياط، يُلتمس إعمال التكييف البديل."
        )
        r = polish(text, is_conditional_context=True, client_side="accused")
        assert "على سبيل الاحتياط" in r.text

    def test_style_trace_in_result(self):
        r = polish(SYNTHETIC_MEMO, client_side="accused")
        d = r.to_dict()
        assert "style_before" in d
        assert "style_after" in d
        assert "applied_passes" in d


# ═════════════════════════════════════════════════════════════════
# SECTION N — Build-memo integration (end-to-end)
# ═════════════════════════════════════════════════════════════════

class TestBuildMemoIntegration:
    @pytest.fixture(scope="class")
    def defense_memo(self):
        from core.domain_pipeline import build_issue_graph, bind_evidence_to_issues
        from core.evidence import get_retriever
        from core.legal_gates import LegalIssueClassifier, FactPatternExtractor
        q = "اكتب مذكرة دفاع في قضية شيك ضمان"
        c = LegalIssueClassifier().classify(q)
        fp = FactPatternExtractor().extract(q)
        g = build_issue_graph(c.primary_domain.value, "", q)
        es = get_retriever().retrieve(
            query=q, classification=c, fact_pattern=fp,
            issue_keywords=[n.question[:30] for n in g.nodes.values()],
        )
        bound = bind_evidence_to_issues(
            g, es.records,
            issue_keywords=[n.question for n in g.nodes.values()],
        )
        req = DraftingRequest(
            document_type=DocumentType.DEFENSE_MEMO,
            client_side=ClientSide.ACCUSED,
            facts=[
                "حرر الموكّل شيكاً بتاريخ 2026/01/01",
                "الشيك سُلّم كضمان لا وفاء",
                "لم يستحق الشرط وقت التقديم",
            ],
        )
        return build_memo(req, graph=g, bound_evidence=bound)

    def test_build_memo_runs_pasl(self, defense_memo):
        has_pasl_note = any("pasl:" in n for n in defense_memo.notes)
        assert has_pasl_note

    def test_build_memo_prayer_has_opener(self, defense_memo):
        if defense_memo.safety_mode != DraftingSafetyMode.NOT_DRAFTABLE_YET:
            assert "لذلك، يلتمس" in defense_memo.text \
                or "يلتمس الموكّل" in defense_memo.text

    def test_build_memo_burden_has_high_impact(self, defense_memo):
        if defense_memo.safety_mode != DraftingSafetyMode.NOT_DRAFTABLE_YET:
            assert any(m in defense_memo.text for m in [
                "ولم يقدِّم", "خلوُّ الأوراق",
                "ولمّا كان الإثبات",
                "قرينة الأصل",
            ])

    def test_build_memo_no_repeated_consecutive_openers(self, defense_memo):
        """After PASL, anti-pattern pass should remove echoed openers."""
        if defense_memo.safety_mode == DraftingSafetyMode.NOT_DRAFTABLE_YET:
            pytest.skip("not draftable")
        repeats = anti_pattern.count_repeated_openers(defense_memo.text)
        assert repeats <= 1
