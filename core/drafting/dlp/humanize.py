# -*- coding: utf-8 -*-
"""
DLP — Raw Gap Humanizer.

Converts internal reason codes like:

    low_issue_coverage:0.25
    no_bound_evidence
    insufficient_facts
    claim_brief_needs_detailed_facts
    issue_graph_unavailable

Into user-safe Arabic phrases. Used by both SKELETON_DRAFT and the
NOT_DRAFTABLE_YET fallback so the user never sees raw codes.

Each phrase is:
  • specific (not "معلومات ناقصة")
  • actionable (says what supplying the fact would unlock)
  • neutral in tone (no blame on the user)
"""
from __future__ import annotations


# ── (key, user_safe_phrase) ──
_GAP_EXPLANATIONS: dict[str, str] = {
    "low_issue_coverage":
        "الوقائع الحالية لا تكفي لحسم بعض المسائل القانونية على نحو نهائي.",
    "no_bound_evidence":
        "لا يوجد حتى الآن ما يربط بعض المسائل بسند قانوني موثَّق ومباشر.",
    "issue_graph_unavailable":
        "لم يتحدَّد المجال القانوني بالدقة اللازمة لبناء الصياغة.",
    "no_primary_issue":
        "لم تتضح المسألة الجوهرية التي تُبنى عليها المذكرة.",
    "insufficient_facts":
        "الوقائع المقدَّمة لا تصل إلى الحد الأدنى الذي يُبنى عليه الموقف.",
    "claim_brief_needs_detailed_facts":
        "صحيفة الدعوى تحتاج إلى تفاصيل دقيقة (الأطراف، التاريخ، المبلغ، محل النزاع).",
    "engine_exception":
        "حدث خلل تقني أثناء إعداد الصياغة ويُعاد المحاولة على المسار الأقوى.",
    "mlre_no_surviving_hypothesis":
        "لم يرجح أي تكييف قانوني على غيره بدرجة تسمح بالحسم.",
    "memo_quality_score":
        "جودة الصياغة الأولية لم تبلغ العتبة المطلوبة، ويُنصح باستكمال العناصر قبل الإيداع.",
}


def humanize_gap(code: str) -> str:
    """Return a single user-safe phrase for a raw gap code."""
    if not code:
        return ""
    key = code.split(":", 1)[0].strip() if ":" in code else code.strip()
    return _GAP_EXPLANATIONS.get(key, _default_phrase(code))


def humanize_gaps(codes: list[str], *, limit: int = 5) -> list[str]:
    """De-duplicated list of user-safe phrases."""
    seen: set[str] = set()
    out: list[str] = []
    for c in (codes or []):
        phrase = humanize_gap(c)
        if phrase and phrase not in seen:
            seen.add(phrase)
            out.append(phrase)
        if len(out) >= limit:
            break
    return out


def _default_phrase(code: str) -> str:
    """Fallback when an unknown code shows up. Never leak the raw code."""
    # Drop any numeric suffix (e.g. 0.25, 0.61)
    base = code.split(":", 1)[0] if ":" in code else code
    base = base.strip().replace("_", " ")
    if not base:
        return "توجد عناصر يحتاج النظام إلى استكمالها."
    return (
        "توجد عناصر تتعلق بـ «"
        + base
        + "» يحتاج النظام إلى استكمالها."
    )
