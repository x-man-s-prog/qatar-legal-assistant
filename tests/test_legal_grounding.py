# -*- coding: utf-8 -*-
"""
PHASE LEGAL GROUNDING FIX — Test Suite
========================================
35 tests for zero-hallucination legal citation system.

Verifies:
 - real Qatari laws are recognized
 - fake law names are blocked
 - fake article numbers are blocked
 - cross-domain citations are blocked
 - safe mode preserves analysis without citations
 - real-query replays remain useful with no fake citations
"""
from __future__ import annotations


def run_legal_grounding_tests() -> dict:
    from core.legal_grounding import (
        LegalGroundingEngine, LegalDomainValidator, CitationConfidence,
        LegalCitation, GroundingResult,
        ground_legal_text, safe_filter,
    )

    engine = LegalGroundingEngine()
    validator = LegalDomainValidator()

    results = []

    def test(name: str, passed: bool, detail: str = ""):
        results.append({"name": name, "passed": passed, "detail": detail})
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}" + (f" — {detail}" if detail and not passed else ""))

    # ══════════════════════════════════════════════════════════════
    # A. verify_law_exists (T01-T05)
    # ══════════════════════════════════════════════════════════════

    # T01: real Qatari labor law recognized
    test("T01: 'قانون العمل' verified",
         engine.verify_law_exists("قانون العمل"))

    # T02: real penal code recognized
    test("T02: 'قانون العقوبات' verified",
         engine.verify_law_exists("قانون العقوبات"))

    # T03: alias recognized
    test("T03: 'قانون الأحوال الشخصية' alias verified",
         engine.verify_law_exists("قانون الأحوال الشخصية"))

    # T04: fake law name BLOCKED
    test("T04: fake 'قانون السرعة الإلكترونية' blocked",
         not engine.verify_law_exists("قانون السرعة الإلكترونية"))

    # T05: empty/garbage input safe
    test("T05: empty/garbage input not verified",
         not engine.verify_law_exists("")
         and not engine.verify_law_exists("لا يوجد قانون"))

    # ══════════════════════════════════════════════════════════════
    # B. verify_article_exists (T06-T10)
    # ══════════════════════════════════════════════════════════════

    # T06: in-range article verified
    test("T06: article 50 of labor law verified",
         engine.verify_article_exists("قانون العمل", "50"))

    # T07: out-of-range article blocked
    test("T07: article 9999 of labor law blocked",
         not engine.verify_article_exists("قانون العمل", "9999"))

    # T08: article in unknown law blocked
    test("T08: article 5 of fake law blocked",
         not engine.verify_article_exists("قانون لا يوجد", "5"))

    # T09: invalid article (non-numeric) blocked
    test("T09: non-numeric article blocked",
         not engine.verify_article_exists("قانون العمل", "abc"))

    # T10: zero/negative article blocked
    test("T10: zero/negative article blocked",
         not engine.verify_article_exists("قانون العمل", "0")
         and not engine.verify_article_exists("قانون العمل", "-1"))

    # ══════════════════════════════════════════════════════════════
    # C. is_verified_reference + confidence levels (T11-T13)
    # ══════════════════════════════════════════════════════════════

    # T11: known law + valid article → VERIFIED
    conf = engine.is_verified_reference("قانون العمل", "50")
    test("T11: real law + in-range article → VERIFIED",
         conf == CitationConfidence.VERIFIED, f"got={conf.value}")

    # T12: known law without article → PARTIAL
    conf = engine.is_verified_reference("قانون العمل", "")
    test("T12: real law alone → PARTIAL",
         conf == CitationConfidence.PARTIAL, f"got={conf.value}")

    # T13: unknown law → UNVERIFIED
    conf = engine.is_verified_reference("قانون مزيف", "10")
    test("T13: fake law → UNVERIFIED",
         conf == CitationConfidence.UNVERIFIED, f"got={conf.value}")

    # ══════════════════════════════════════════════════════════════
    # D. domain validation (T14-T17)
    # ══════════════════════════════════════════════════════════════

    # T14: labor law in employment issue → compatible
    test("T14: labor law domain ↔ employment issue",
         validator.is_compatible("employment", "employment"))

    # T15: criminal code in employment issue → INCOMPATIBLE
    test("T15: criminal law domain blocked in employment issue",
         not validator.is_compatible("employment", "criminal"))

    # T16: civil law in debt issue → compatible
    test("T16: civil law in debt issue",
         validator.is_compatible("debt", "civil"))

    # T17: family law in debt issue → INCOMPATIBLE
    test("T17: family law in debt issue blocked",
         not validator.is_compatible("debt", "family"))

    # ══════════════════════════════════════════════════════════════
    # E. extract_citations from text (T18-T22)
    # ══════════════════════════════════════════════════════════════

    # T18: extract real citation from text
    text = "وفقاً لقانون العمل رقم 14 لسنة 2004، فإن المادة 50 تنص على..."
    cites = engine.extract_citations(text)
    test("T18: extract real labor law + article",
         any(c.law_name == "قانون العمل" for c in cites)
         and any(c.article_number == "50" for c in cites),
         f"cites={[(c.law_name, c.article_number, c.confidence.value) for c in cites]}")

    # T19: extract fake law from text → marked UNVERIFIED
    text = "بموجب قانون التشريع الإلكتروني رقم 99 لسنة 2050"
    cites = engine.extract_citations(text)
    test("T19: fake law extracted as UNVERIFIED",
         any(c.confidence == CitationConfidence.UNVERIFIED for c in cites))

    # T20: extract law name without number/year → PARTIAL
    text = "ينظم قانون العمل العلاقة بين العامل وصاحب العمل"
    cites = engine.extract_citations(text)
    test("T20: law name alone → PARTIAL",
         any(c.law_name == "قانون العمل"
             and c.confidence == CitationConfidence.PARTIAL for c in cites))

    # T21: orphan article (no law context) → UNVERIFIED
    text = "حسب المادة (304) فإن العقوبة هي الحبس"
    cites = engine.extract_citations(text)
    art_cites = [c for c in cites if c.article_number == "304"]
    test("T21: orphan article → UNVERIFIED",
         any(c.confidence == CitationConfidence.UNVERIFIED for c in art_cites))

    # T22: out-of-range article in real law → UNVERIFIED
    text = "وفقاً لقانون الإيجار رقم 4 لسنة 2008، المادة 9999 تنص"
    cites = engine.extract_citations(text)
    art_cites = [c for c in cites if c.article_number == "9999"]
    test("T22: out-of-range article in real law → UNVERIFIED",
         any(c.confidence == CitationConfidence.UNVERIFIED for c in art_cites))

    # ══════════════════════════════════════════════════════════════
    # F. block_if_unverified — actual filtering (T23-T28)
    # ══════════════════════════════════════════════════════════════

    # T23: fake law citation gets stripped
    text = "وفقاً لقانون التشريع الإلكتروني رقم 99 لسنة 2050، يحق للعامل المطالبة"
    res = engine.block_if_unverified(text)
    test("T23: fake law replaced with safe placeholder",
         "قانون التشريع الإلكتروني" not in res.text
         and ("[مرجع غير موثّق]" in res.text or "النص القانوني المنظِّم" in res.text or "القانون المختص" in res.text),
         f"text={res.text}")

    # T24: real law passes through unchanged (PARTIAL = law name allowed)
    text = "وفقاً لقانون العمل، يحق للعامل مكافأة نهاية الخدمة"
    res = engine.block_if_unverified(text)
    test("T24: real law passes through (PARTIAL)",
         "قانون العمل" in res.text and len(res.citations_blocked) == 0)

    # T25: real law + fake article → article gets blocked
    text = "وفقاً لقانون الإيجار رقم 4 لسنة 2008، المادة 9999 تنص"
    res = engine.block_if_unverified(text)
    test("T25: real law + out-of-range article → article blocked",
         len(res.citations_blocked) >= 1
         and ("[مرجع غير موثّق]" in res.text or "النص القانوني المنظِّم" in res.text or "القانون المختص" in res.text),
         f"blocked={len(res.citations_blocked)} text={res.text[:120]}")

    # T26: cross-domain citation blocked
    text = ("في قضية الفصل من العمل، وفقاً لقانون العقوبات رقم 11 لسنة 2004، "
            "يحق للعامل التعويض")
    res = engine.block_if_unverified(text, issue_domain="employment")
    test("T26: cross-domain citation (penal in employment) blocked",
         any("domain mismatch" in c.block_reason for c in res.citations_blocked),
         f"blocked={[c.block_reason[:60] for c in res.citations_blocked]}")

    # T27: real law + valid article → both pass
    text = "وفقاً لقانون العمل رقم 14 لسنة 2004، فإن المادة 50 تنظم"
    res = engine.block_if_unverified(text, issue_domain="employment")
    test("T27: real law + valid article → both pass",
         len(res.citations_blocked) == 0
         and "قانون العمل" in res.text
         and "المادة 50" in res.text,
         f"text={res.text}")

    # T28: orphan article gets stripped
    text = "حسب المادة 304 فإن العقوبة هي الحبس"
    res = engine.block_if_unverified(text)
    test("T28: orphan article stripped (no law context)",
         "المادة 304" not in res.text
         and ("[مرجع غير موثّق]" in res.text
              or "النص القانوني المنظِّم" in res.text
              or "القانون المختص" in res.text
              or "[مادة بدون مرجع موثّق]" in res.text),
         f"text={res.text}")

    # ══════════════════════════════════════════════════════════════
    # G. Safe analysis mode (T29-T31)
    # ══════════════════════════════════════════════════════════════

    # T29: safe mode strips ALL articles
    text = ("بموجب المادة (50) من قانون العمل ومادة (75) من قانون مجهول "
            "يحق للعامل التعويض")
    safe = engine.convert_to_safe_analysis_mode(text)
    test("T29: safe mode removes all article numbers",
         "المادة (50)" not in safe and "مادة (75)" not in safe
         and "[مرجع موضوعي عام]" in safe,
         f"safe={safe}")

    # T30: safe mode preserves the substantive analysis
    text = ("يحق للعامل التعويض بموجب المادة (50) إذا ثبت الفصل التعسفي "
            "وعدم وجود مبرر مشروع")
    safe = engine.convert_to_safe_analysis_mode(text)
    test("T30: safe mode preserves substantive analysis",
         "يحق للعامل التعويض" in safe
         and "الفصل التعسفي" in safe
         and "مبرر مشروع" in safe)

    # T31: safe mode handles unknown law gracefully
    text = "بموجب قانون مزيف رقم 999 لسنة 2050، فإن المادة 5 تقول"
    safe = engine.convert_to_safe_analysis_mode(text)
    test("T31: safe mode replaces fake law",
         "قانون مزيف رقم 999 لسنة 2050" not in safe
         and ("[قانون متخصص]" in safe or "[مرجع موضوعي عام]" in safe))

    # ══════════════════════════════════════════════════════════════
    # H. End-to-end ground_text + integration (T32-T35)
    # ══════════════════════════════════════════════════════════════

    # T32: ground_text returns useful structure
    text = "وفقاً لقانون العمل رقم 14 لسنة 2004، المادة 50 تنظم"
    res = ground_legal_text(text, issue_domain="employment")
    test("T32: ground_text returns structured GroundingResult",
         isinstance(res, GroundingResult)
         and isinstance(res.text, str)
         and isinstance(res.citations_found, list))

    # T33: safe_filter convenience returns just text
    text = "وفقاً لقانون مزيف، يحق المطالبة"
    out = safe_filter(text)
    test("T33: safe_filter returns clean text",
         isinstance(out, str)
         and "قانون مزيف" not in out)

    # T34: empty input handled
    res = ground_legal_text("", "employment")
    test("T34: empty input handled safely",
         res.text == "" and not res.citations_found)

    # T35: text with no citations passes through unchanged
    text = "هذا تحليل قانوني عام بدون أي إشارة لقانون أو مادة محددة"
    res = ground_legal_text(text)
    test("T35: text without citations passes unchanged",
         res.text == text and len(res.citations_found) == 0)

    # ══════════════════════════════════════════════════════════════
    # Summary
    # ══════════════════════════════════════════════════════════════
    passed = sum(1 for r in results if r["passed"])
    failed = sum(1 for r in results if not r["passed"])
    print(f"\n{'='*50}")
    print(f"LEGAL GROUNDING TESTS: {passed}/{len(results)} passed")
    if failed:
        print("FAILURES:")
        for r in results:
            if not r["passed"]:
                print(f"  - {r['name']}: {r['detail']}")
    print(f"{'='*50}")

    return {"total": len(results), "passed": passed, "failed": failed, "results": results}


if __name__ == "__main__":
    run_legal_grounding_tests()
