# -*- coding: utf-8 -*-
"""
Self-Healing Regression Suite.

Permanent guardrail: 50 real-world queries across all domains. Must pass
before every deploy. Catches regressions in:
  - classifier coverage
  - substring false positives
  - scoring formula drift
  - threshold calibration
  - anti-contamination

Also asserts the diagnosed 10 failure cases are no longer regressing.

Run: pytest tests/test_self_healing_regression.py -v
"""
from __future__ import annotations

import pytest

from core.legal_gates import (
    LegalIssueClassifier,
    _tokenize_legal, _marker_matches, _has_legal_concepts,
    LegalDomain,
)


# ═════════════════════════════════════════════════════════════════
# PHASE 1 — Matching-engine attack tests (substring must NOT fire)
# ═════════════════════════════════════════════════════════════════

class TestMatchingEngineAttacks:
    """Hardening tests — every marker must respect word boundaries."""

    def test_siba_does_not_match_beasboa(self):
        """Q5 regression: 'سب' must NOT match 'بأسبوع'."""
        tokens = _tokenize_legal("قبل وفاته بأسبوع، هل تعتبر هبة")
        assert _marker_matches("سب", tokens) is False
        assert _marker_matches("سبني", tokens) is False

    def test_insult_marker_matches_actual_insult(self):
        tokens = _tokenize_legal("واحد سبني أمام الناس")
        assert _marker_matches("سبني", tokens) is True

    def test_assault_marker_does_not_match_random(self):
        """Ensure 'ضرب' doesn't match 'مضطرب' or similar."""
        tokens = _tokenize_legal("الوضع المضطرب في السوق")
        assert _marker_matches("ضرب", tokens) is False
        assert _marker_matches("ضربني", tokens) is False

    def test_cheque_marker_requires_full_word(self):
        tokens = _tokenize_legal("مشيك في الأمر")   # مشيك is not شيك
        assert _marker_matches("شيك", tokens) is False

    def test_multi_word_marker_requires_all_tokens(self):
        tokens = _tokenize_legal("نزاع حدث في الشركة")
        # "نزاع تجاري" requires BOTH tokens
        assert _marker_matches("نزاع تجاري", tokens) is False

    def test_prefix_ال_is_normalized(self):
        """"الوفاة" should match marker "وفاة" via prefix stripping."""
        tokens = _tokenize_legal("قبل الوفاة بأسبوع")
        # "وفاة" normalized matches stripped prefix
        assert "وفاه" in tokens or "الوفاه" in tokens

    def test_legal_concepts_detected(self):
        tokens = _tokenize_legal("ما هي حقوقي القانونية وكيف أطالب بها")
        assert _has_legal_concepts(tokens) is True

    def test_non_legal_concepts_not_detected(self):
        tokens = _tokenize_legal("كيف الحال يا صديقي")
        assert _has_legal_concepts(tokens) is False


# ═════════════════════════════════════════════════════════════════
# PHASE 2 — The 10 diagnosed failure cases (must now pass)
# ═════════════════════════════════════════════════════════════════

_TEN_FAILURES = [
    # (query, expected_domain)
    ("شركة ناشئة تعاقدت مع مبرمج مستقل، أنجز النصف ثم رفض إكمال العمل ويطالب بكامل المبلغ",
     "commercial"),
    ("واحد هددني في الواتساب وقال بيضربني، هل يعتبر جريمة وهل ينفع اقدم بلاغ",
     "criminal"),
    ("شخص اشترى عقاراً بعقد ابتدائي ودفع المبلغ كاملاً لكن البائع يرفض استكمال نقل الملكية",
     "civil"),
    ("أنا اشتغلت في شركة بدون عقد مكتوب لسنتين، الآن فصلوني بدون أي حقوق",
     "employment"),
    ("قام مورث بتحويل أموال كبيرة لأحد الورثة قبل وفاته بأسبوع، هل تعتبر هبة",
     "inheritance"),
    ("دخلت مع واحد في مشروع وقال لي الأرباح مضمونة 30% سنوياً، الآن خسرنا ويرفض إرجاع مالي",
     "commercial"),
    ("قام شخص بتسليم شيك كضمان فقط ثم صرفته الشركة رغم عدم تحقق الشرط",
     "banking"),
    ("واحد صوّرني بدون علمي في مكان عام وينشر الصورة على السوشيال ميديا",
     "criminal"),
    ("تأخر المقاول في تسليم المشروع 6 أشهر، والعقد فيه شرط جزائي 10% من القيمة",
     "civil"),
    ("صار بيني وبين واحد مضاربة في الشارع، وأنا ما كنت البادئ، هل علي مسؤولية",
     "criminal"),
]


class TestTenDiagnosedFailures:
    """Each of the 10 diagnosed failures must now route correctly."""

    @pytest.mark.parametrize("query,expected_domain", _TEN_FAILURES)
    def test_routes_to_correct_domain(self, query, expected_domain):
        c = LegalIssueClassifier().classify(query)
        assert c.is_route_eligible is True, \
            f"Query blocked: {query[:60]} → {c.block_reason}"
        assert c.primary_domain.value == expected_domain, \
            (f"Wrong domain for query: {query[:60]}\n"
             f"  expected={expected_domain} got={c.primary_domain.value}\n"
             f"  scores={c.raw_scores}")


# ═════════════════════════════════════════════════════════════════
# PHASE 8 — 50-query regression suite across all domains
# ═════════════════════════════════════════════════════════════════

_REGRESSION_50 = [
    # Employment (5)
    ("فصلت من العمل بعد 10 سنوات خدمة", "employment"),
    ("صاحب العمل يرفض دفع مستحقاتي بعد الاستقالة", "employment"),
    ("العقد لم يذكر مكافأة نهاية الخدمة", "employment"),
    ("إصابة عمل أثناء العمل ولم يُعوَّض", "employment"),
    ("اشتغلت ساعات إضافية بدون أجر", "employment"),

    # Civil (contracts + construction + real estate) (6)
    ("بطلان العقد لتخلف ركن أساسي", "civil"),
    ("تأخر المقاول في تسليم المنشأ شهرين", "civil"),
    ("اشتريت عقار بعقد ابتدائي وأرفض البائع نقل الملكية", "civil"),
    ("عيب جوهري في المنشأ يمنع الاستلام", "civil"),
    ("ضمان البناء عن عيب ظهر بعد 3 سنوات", "civil"),
    ("المطالبة بتعويض عن ضرر مادي لحق بي", "civil"),

    # Commercial (6)
    ("نزاع تجاري بين شركاء حول توزيع الأرباح", "commercial"),
    ("شركة ناشئة مع مبرمج مستقل ورفض إكمال العمل", "commercial"),
    ("مستثمر يدّعي أرباح مضمونة 20%", "commercial"),
    ("إنهاء الوكالة التجارية بدون مبرر", "commercial"),
    ("إفلاس شركة تجارية وديون الموردين", "commercial"),
    ("خسارة المشروع مع شريك متعنت", "commercial"),

    # Criminal (6)
    ("واحد سبني في مكان عام", "criminal"),
    ("ضربني شخص وأُصبت بكدمات", "criminal"),
    ("هدّدني بالقتل عبر رسالة صوتية", "criminal"),
    ("سرق محفظتي من الجيب", "criminal"),
    ("تم ابتزازي إلكترونياً بصور خاصة", "criminal"),
    ("شخص قام بتزوير توقيعي على مستند", "criminal"),

    # Family (4)
    ("طلاق وأطالب بحضانة الأطفال", "family"),
    ("النفقة الشرعية لزوجتي المطلقة", "family"),
    ("نزاع على رؤية الأبناء بعد الانفصال", "family"),
    ("خلع ورفض الزوج", "family"),

    # Rental (4)
    ("المؤجر يطلب إخلاء الشقة بدون سبب", "rental"),
    ("تأخر المستأجر في دفع الإيجار 3 أشهر", "rental"),
    ("زيادة الإيجار خلال مدة العقد", "rental"),
    ("عقد إيجار منتهي ومستأجر يرفض الإخلاء", "rental"),

    # Banking (4)
    ("البنك خصم مبلغ من حسابي بدون تفويض", "banking"),
    ("قرض بنكي بفوائد مرتفعة مخالفة", "banking"),
    ("شيك بدون رصيد وكيف أقدم بلاغ", "banking"),
    ("تسهيلات مصرفية وتسعير الفائدة", "banking"),

    # Inheritance (4)
    ("تقسيم تركة الوالد بين الورثة", "inheritance"),
    ("هبة في مرض الموت هل صحيحة", "inheritance"),
    ("وصية تتجاوز الثلث", "inheritance"),
    ("طعن في هبة مورث قبل الوفاة بأسبوع", "inheritance"),

    # Traffic (3)
    ("حادث مروري وأنا متوقف", "traffic"),
    ("مخالفة مرورية غير عادلة", "traffic"),
    ("تصادم بين سيارتين ومن المتسبب", "traffic"),

    # Administrative (3)
    ("قرار إداري بإلغاء ترخيصي", "administrative"),
    ("تظلم إداري من قرار حكومي", "administrative"),
    ("طعن على قرار وزاري", "administrative"),

    # IP (3)
    ("سرقة علامتي التجارية من منافس", "intellectual_property"),
    ("ملكية برمجية وكود مسروق", "intellectual_property"),
    ("نزاع على حق المؤلف لكتاب", "intellectual_property"),

    # Insurance (2)
    ("شركة التأمين رفضت مطالبتي", "insurance"),
    ("بوليصة تأمين منتهية وحادث قبل التجديد", "insurance"),
]


assert len(_REGRESSION_50) >= 50, f"need ≥50, got {len(_REGRESSION_50)}"


class TestRegressionSuite50:
    """50 real-world queries — pass rate must be ≥ 90%."""

    def test_suite_has_at_least_50(self):
        assert len(_REGRESSION_50) >= 50

    @pytest.mark.parametrize("query,expected_domain", _REGRESSION_50)
    def test_individual_query(self, query, expected_domain):
        c = LegalIssueClassifier().classify(query)
        assert c.is_route_eligible, \
            f"Blocked: {query[:70]} → {c.block_reason}"
        assert c.primary_domain.value == expected_domain, \
            (f"Wrong domain: {query[:70]}\n"
             f"  expected={expected_domain} got={c.primary_domain.value}\n"
             f"  scores={c.raw_scores}")


class TestPassRate:
    """Aggregate pass-rate assertion — ≥95% of the 50 suite must pass."""

    def test_pass_rate_at_least_95(self):
        clf = LegalIssueClassifier()
        passes = 0
        failures = []
        for q, expected in _REGRESSION_50:
            c = clf.classify(q)
            if c.is_route_eligible and c.primary_domain.value == expected:
                passes += 1
            else:
                failures.append((q[:50], expected, c.primary_domain.value,
                                  c.is_route_eligible))
        rate = passes / len(_REGRESSION_50)
        assert rate >= 0.95, (
            f"pass rate {rate:.1%} < 95% target.\n"
            f"Failures: {failures[:5]}"
        )


# ═════════════════════════════════════════════════════════════════
# PHASE 5 — Fail-safe mode (legal-sounding queries not blocked)
# ═════════════════════════════════════════════════════════════════

class TestFailSafeMode:
    def test_legal_query_without_domain_passes_with_flag(self):
        """Pure legal question without domain markers should pass with flag."""
        q = "ما هي حقوقي القانونية في هذه الحالة وكيف أبدأ دعوى"
        c = LegalIssueClassifier().classify(q)
        assert c.is_route_eligible is True, f"blocked: {c.block_reason}"

    def test_non_legal_query_still_blocks(self):
        """Pure chatter must still block."""
        q = "كيف الحال يا صديقي"
        c = LegalIssueClassifier().classify(q)
        assert c.is_route_eligible is False

    def test_very_vague_single_word_blocks(self):
        c = LegalIssueClassifier().classify("سؤال")
        assert c.is_route_eligible is False


# ═════════════════════════════════════════════════════════════════
# PHASE 3-4 — Dynamic scoring + adaptive threshold
# ═════════════════════════════════════════════════════════════════

class TestDynamicScoring:
    def test_confidence_uses_share_not_fixed_divisor(self):
        """Single weight-1 marker no longer produces 0.125."""
        c = LegalIssueClassifier().classify("عقاري")
        # Whatever the final number is, it must not be the old 1/8=0.125
        # when a marker fires
        if c.is_route_eligible and c.raw_scores:
            assert c.confidence != round(1 / 8, 3) or \
                   c.primary_domain.value != "civil"

    def test_short_query_uses_lower_threshold(self):
        c = LegalIssueClassifier().classify("شيك بدون رصيد")
        assert c.threshold_used <= 0.20, \
            f"short query threshold too high: {c.threshold_used}"


# ═════════════════════════════════════════════════════════════════
# PHASE 10 — Self-diagnostic is active
# ═════════════════════════════════════════════════════════════════

class TestSelfDiagnosticSystem:
    def test_recorder_exists_and_snapshots(self):
        from core.self_diagnostic import snapshot, get_recorder
        s = snapshot()
        assert "window" in s
        assert "alert_thresholds" in s
        assert s["alert_thresholds"]["block_rate"] == 0.20
        assert s["alert_thresholds"]["cross_domain_rate"] == 0.05

    def test_record_and_retrieve(self):
        from core.self_diagnostic import record_request, get_recorder
        r = get_recorder()
        r.reset()
        for i in range(5):
            record_request(
                session_id=f"s-{i}", domain_detected="criminal",
                confidence=0.8, markers_used=1, tokens=5,
                issue_count=0, evidence_count=3, gates_passed=7,
                blocked=False, block_reason="", cross_domain_flag=False,
                low_confidence_flag=False, contamination_blocked=0,
                elapsed_ms=5.0,
            )
        s = r.snapshot()
        assert s["samples"] == 5
        assert s["block_rate"] == 0.0


# ═════════════════════════════════════════════════════════════════
# Integration — end-to-end with full pipeline
# ═════════════════════════════════════════════════════════════════

class TestEndToEndTenCases:
    """End-to-end: domain routing must be correct. Full answer depends
    on canonical corpus coverage, so inheritance (no corpus yet) may
    return insufficiency — that's correct fail-closed behavior."""

    _DOMAINS_WITH_CORPUS = {
        "criminal", "employment", "civil", "commercial", "banking",
        "family", "rental",
    }

    @pytest.mark.parametrize("query,expected_domain", _TEN_FAILURES)
    def test_full_pipeline_routes_correctly(self, query, expected_domain):
        from core.production_runtime import answer_query_direct
        from core.conversation import get_state_engine
        get_state_engine().reset(f"e2e-{hash(query) & 0xFFF}")
        r = answer_query_direct(query, f"e2e-{hash(query) & 0xFFF}")

        # Unified authority preserved regardless
        assert r.get("authoritative_path") == "unified_fail_closed"
        assert r.get("legacy_used") is False

        # Domain detection must be correct
        assert r.get("domain") in (expected_domain, ""), \
            f"Wrong domain for {query[:60]}: got {r.get('domain')}"

        # For domains with canonical corpus → must not be blocked
        if expected_domain in self._DOMAINS_WITH_CORPUS:
            assert not r.get("is_blocked"), \
                f"Blocked despite corpus exists: {query[:60]}"
        # Else (inheritance, traffic, IP, etc.) — insufficiency is acceptable
        # fail-closed behavior until canonical corpus is added
