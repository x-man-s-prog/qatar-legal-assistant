# -*- coding: utf-8 -*-
"""
Stabilization Layer (PHASE FIX)
================================
Centralized fixes for runtime failures observed in live testing.
Addresses: context leakage, citation injection, activation gaps,
Arabic output quality, and latency safeguards.

This module does NOT redesign any existing layer. It provides:
 1. SessionIsolator        — prevents shared "default" session contamination
 2. DomainGuard            — filters cross-domain chunks / history / cache
 3. CaseAnalysisActivator  — forces strengths/weaknesses output on complex personal queries
 4. OutputCleaner          — unified filler phrase removal
 5. LatencyGuard           — timeout wrappers for upstream hangs

All fixes are deterministic, fail-safe, and append-only.
"""
from __future__ import annotations
import asyncio
import hashlib
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional, Callable, Any

log = logging.getLogger("stabilization")


# ══════════════════════════════════════════════════════════════
# 1. SessionIsolator — prevents shared session leakage
# ══════════════════════════════════════════════════════════════

_SAFE_DEFAULT_SESSIONS: set[str] = set()


def resolve_safe_session_id(session_id: Optional[str],
                              request_ip: str = "",
                              request_headers: Optional[dict] = None) -> str:
    """
    Convert a bare 'default' / empty session_id into a stable per-request ID.
    Prevents cross-user contamination when clients don't send an explicit ID.
    """
    sid = (session_id or "").strip()
    if sid and sid.lower() not in ("default", "none", "null"):
        return sid

    # Try to derive from request identity (IP + UA) for stability within a session
    if request_headers:
        ua = request_headers.get("user-agent", "") or request_headers.get("User-Agent", "")
        seed = f"{request_ip}|{ua}"
        if seed.strip("|"):
            h = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
            return f"anon_{h}"

    # Last resort: generate a fresh session ID
    return f"anon_{uuid.uuid4().hex[:12]}"


# ══════════════════════════════════════════════════════════════
# 2. DomainGuard — cross-domain filtering
# ══════════════════════════════════════════════════════════════

# Domain signals (compact, high-precision — NOT for downstream classification)
_DOMAIN_KEYWORDS = {
    "employment": [
        "فصل", "فصلوني", "طردوني", "استقالة", "راتب", "مكافأة", "عقد عمل",
        "عقدي", "شغل", "وظيفة", "كفيل", "كفيلي", "مدير", "الدوام",
        "إذن خروج", "نقل كفالة", "تحويلات راتب", "صاحب العمل",
    ],
    "criminal": [
        "متهم", "تهمة", "شرطة", "نيابة", "مخدرات", "سرقة", "ضرب",
        "جنائي", "جريمة", "سجن", "حبس", "ابتزاز", "تحرش",
        "قبض", "تحقيق",
    ],
    "family": [
        "طلاق", "حضانة", "نفقة", "زوج", "زوجة", "زوجتي", "زوجي",
        "طليقتي", "طليقي", "عيال", "عيالي", "أطفال", "الأولاد",
        "ميراث", "خلع", "عدة",
    ],
    "rental": [
        "إيجار", "مستأجر", "مالك", "شقة", "إخلاء", "عقد إيجار",
        "التأمين", "السكن", "مؤجر",
    ],
    "debt": [
        "دين", "مبلغ", "فلوس", "مال", "محادثات واتساب", "استرداد",
        "مستحقات مالية", "شيك", "قرض",
    ],
    "administrative": [
        "قرار إداري", "جهة حكومية", "إدارة", "وزارة", "تظلم",
        "اعتراض إداري",
    ],
    "procedural": [
        "طعن", "استئناف", "تمييز", "مهلة", "ميعاد", "تقادم",
        "تبليغ", "إعلان", "تنفيذ حكم",
    ],
}


def detect_query_domain(query: str) -> str:
    """Return best-match domain for a query. Empty string if no clear match."""
    if not query:
        return ""
    q = query.strip()
    best_domain = ""
    best_score = 0
    for domain, kws in _DOMAIN_KEYWORDS.items():
        score = sum(1 for kw in kws if kw in q)
        if score > best_score:
            best_score = score
            best_domain = domain
    return best_domain if best_score >= 1 else ""


def domains_compatible(d1: str, d2: str) -> bool:
    """Check if two domains are compatible for context carryover."""
    if not d1 or not d2:
        return True  # neutral/unknown domain is always compatible
    if d1 == d2:
        return True
    # Known compatible pairs — only procedural overlays are compatible with substantive domains.
    # Substantive domains (family/debt/employment/rental/criminal) are NOT compatible with each other.
    _COMPATIBLE = {
        ("employment", "procedural"), ("procedural", "employment"),
        ("family", "procedural"), ("procedural", "family"),
        ("rental", "procedural"), ("procedural", "rental"),
        ("criminal", "procedural"), ("procedural", "criminal"),
        ("debt", "procedural"), ("procedural", "debt"),
        ("administrative", "procedural"), ("procedural", "administrative"),
    }
    return (d1, d2) in _COMPATIBLE


def should_enrich_followup(current_query: str, prior_query: str) -> bool:
    """
    Decide whether the current query is safe to enrich with prior context.
    Returns False if cross-domain leakage risk is high.
    """
    d_curr = detect_query_domain(current_query)
    d_prior = detect_query_domain(prior_query)
    if not domains_compatible(d_curr, d_prior):
        log.info("[DOMAIN_GUARD] followup blocked: curr_domain=%s prior_domain=%s",
                 d_curr, d_prior)
        return False
    return True


def filter_chunks_by_domain(chunks: list[dict], target_domain: str,
                              min_keep_ratio: float = 0.3) -> list[dict]:
    """
    Remove chunks whose textual content matches a DIFFERENT clear domain
    from target_domain. If all chunks get filtered, returns top-N original
    (soft-fail: don't starve the LLM of context).
    """
    if not target_domain or not chunks:
        return chunks

    kept = []
    dropped = []
    for ch in chunks:
        content = str(ch.get("content", "") or ch.get("text", ""))[:1500]
        chunk_domain = detect_query_domain(content)
        if not chunk_domain or domains_compatible(chunk_domain, target_domain):
            kept.append(ch)
        else:
            dropped.append(ch)

    # Soft-fail: if we dropped too many, keep original order.
    # Only trigger soft-fail when NONE match OR we'd be below the absolute floor.
    min_absolute = max(1, int(len(chunks) * min_keep_ratio))
    if len(kept) < min_absolute:
        log.info("[DOMAIN_GUARD] keeping original chunks (filter would leave %d < floor %d)",
                 len(kept), min_absolute)
        return chunks

    if dropped:
        log.info("[DOMAIN_GUARD] filtered %d/%d chunks for domain=%s",
                 len(dropped), len(chunks), target_domain)
    return kept


def citation_is_relevant(cited_article: str, cited_law: str,
                          target_domain: str, chunks: list[dict]) -> bool:
    """
    Check that a cited article (number, law) is actually supported by
    a chunk that belongs to the target domain.
    """
    if not target_domain:
        return True  # no domain to filter by
    for ch in chunks:
        if str(ch.get("article_number", "")) == cited_article:
            ch_domain = detect_query_domain(str(ch.get("content", "")))
            if not ch_domain or domains_compatible(ch_domain, target_domain):
                return True
    return False


# ══════════════════════════════════════════════════════════════
# 3. CaseAnalysisActivator — force strengths/weaknesses output
# ══════════════════════════════════════════════════════════════

# Triggers that indicate the user wants case analysis (not a pure info query)
_CASE_ANALYSIS_TRIGGERS = [
    # Strength/weakness request
    "نقاط ضعفي", "نقاط قوتي", "نقاط ضعف", "نقاط قوة",
    "ما موقفي", "كيف موقفي", "وضعي القانوني", "وضعي",
    "هل أقدر أطالب", "هل أستطيع", "هل يحق لي",
    # Opposing party
    "ممكن يحتج به", "يحتج به", "سيحتج به", "ممكن يستخدمه", "يستخدمه ضدي",
    "الطرف الآخر", "الطرف الثاني", "صاحب العمل",
    # Personal situation with evidence concerns
    "ما عندي عقد", "ما عندي أوراق", "محادثات واتساب",
    "ما أعرف بالضبط", "ما أدري متى",
    # Multi-party complexity
    "يحمّلني المسؤولية", "موقفي",
]


def should_activate_case_analysis(query: str, domain: str = "") -> bool:
    """True if this query calls for explicit strengths/weaknesses analysis."""
    if not query:
        return False
    # Must be in a legal domain
    if domain and domain in ("greeting", "chat", "filler"):
        return False
    # Must be long enough (short queries = direct info, not case analysis)
    if len(query.split()) < 8:
        return False
    # Trigger phrase match
    return any(t in query for t in _CASE_ANALYSIS_TRIGGERS)


@dataclass
class CaseAnalysisReport:
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    opponent_arguments: list[str] = field(default_factory=list)
    what_is_needed: list[str] = field(default_factory=list)
    primary_domain: str = ""

    def has_content(self) -> bool:
        return bool(self.strengths or self.weaknesses or
                    self.opponent_arguments or self.what_is_needed)


# Pattern library — map evidence markers to strength/weakness analysis
_EVIDENCE_STRONG_MARKERS = [
    ("تحويلات راتب", "strength", "تحويلات الراتب تُعد قرينة قوية على وجود علاقة عمل فعلية",
     "employment"),
    ("شهود", "strength", "وجود شهود يقوي الموقف أمام المحكمة", ""),
    ("مراسلات رسمية", "strength", "المراسلات الرسمية تعزز إثبات الحق", ""),
    ("عقد مكتوب", "strength", "العقد المكتوب يحدد الالتزامات بوضوح", ""),
    ("إقرار", "strength", "الإقرار بالدين أو الالتزام قرينة قاطعة عند إثباته",
     "debt"),
    ("معترف", "strength", "اعتراف الطرف الآخر يُعد من أقوى وسائل الإثبات", ""),
    ("حكم قضائي", "strength", "صدور حكم قضائي يمنح حق التنفيذ",
     "procedural"),
]

_EVIDENCE_WEAK_MARKERS = [
    ("ما عندي عقد", "weakness",
     "غياب العقد المكتوب يُضعف الإثبات ويحتاج تعزيز بقرائن أخرى", "employment"),
    ("ما عندي عقد مكتوب", "weakness",
     "غياب العقد المكتوب يُضعف الإثبات ويحتاج تعزيز بقرائن أخرى", "employment"),
    ("بدون عقد", "weakness",
     "عدم وجود عقد يجعل إثبات الحق أصعب", ""),
    ("ما عندي إلا محادثات", "weakness",
     "الاعتماد على محادثات واتساب فقط قد لا يكون كافياً بدون دعم", "debt"),
    ("محادثات واتساب", "weakness",
     "حجية محادثات واتساب تحتاج توثيق إلكتروني وتصديق", ""),
    ("ما أرسلت إنذار", "weakness",
     "عدم إرسال إنذار رسمي قد يُعيق قبول الدعوى", "rental"),
    ("ما أرسلت له إنذار", "weakness",
     "عدم إرسال إنذار رسمي قد يُعيق قبول الدعوى", "rental"),
    ("بدون إنذار رسمي", "weakness",
     "عدم إرسال إنذار رسمي قد يُعيق قبول الدعوى", ""),
    ("ما صار تبليغ", "weakness",
     "عدم إتمام التبليغ الرسمي يُوقف إجراءات التنفيذ", "procedural"),
    ("تأخرت", "weakness",
     "التأخر قد يُفقد الحق في الطعن أو الاعتراض", "procedural"),
    ("ما أعرف بالضبط متى", "weakness",
     "عدم معرفة تاريخ التبليغ يُصعب احتساب المدة القانونية", "procedural"),
    ("ما عندي كل الأوراق", "weakness",
     "نقص المستندات يُضعف موقف الإثبات", ""),
    ("ما أدري هل باقي", "weakness",
     "الشك في سريان المدة يتطلب التحقق الفوري من تاريخ التبليغ",
     "procedural"),
]

_OPPONENT_MARKERS = [
    ("فصلوني", "employment",
     "قد يحتج صاحب العمل بوجود مبرر مشروع للفصل أو بعدم استكمال مدة التجربة"),
    ("فصل", "employment",
     "قد يحتج صاحب العمل بوجود مبرر مشروع للفصل"),
    ("مبلغ مالي", "debt",
     "قد يحتج الطرف الآخر بعدم اكتمال الأدلة الكتابية أو باختلاف قيمة المبلغ"),
    ("محادثات واتساب", "debt",
     "قد يطعن الطرف الآخر في صحة محادثات واتساب أو ينكرها"),
    ("مستأجر", "rental",
     "قد يحتج المستأجر بعدم استلام إنذار رسمي أو بعدم استحقاق المبالغ"),
    ("إيجار", "rental",
     "قد يُدفع بعدم تسليم العين أو بوجود عيوب تُخل بالانتفاع"),
    ("حضانة", "family",
     "قد يدفع الطرف الآخر بعدم الأهلية أو بتغير الظروف"),
    ("قرار إداري", "administrative",
     "قد تدفع الجهة الإدارية بسبب مشروع وبانقضاء مدة الطعن"),
    ("طعن", "procedural",
     "قد يُدفع بانقضاء المدة أو بعدم توافر شروط الطعن"),
    ("حكم", "procedural",
     "قد يُطعن في صحة الحكم أو في إجراءات التبليغ"),
    ("تنفيذ", "procedural",
     "قد يُعترض على التنفيذ بعدم اكتمال التبليغ أو بالسداد"),
]

_WHAT_NEEDED_MARKERS = [
    ("ما عندي عقد", "احصل على ما يقوم مقام العقد: خطاب تعيين، تحويلات راتب، شهود زملاء"),
    ("ما عندي إلا محادثات", "وثّق محادثات واتساب رسمياً عبر كاتب عدل أو خبير إلكتروني"),
    ("ما أرسلت إنذار", "أرسل إنذاراً رسمياً عبر كاتب العدل قبل رفع دعوى الإخلاء"),
    ("ما أرسلت له إنذار", "أرسل إنذاراً رسمياً عبر كاتب العدل قبل رفع دعوى الإخلاء"),
    ("ما صار تبليغ", "أكمل إجراءات التبليغ الرسمي قبل طلب التنفيذ"),
    ("تأخرت", "تحقق فوراً من تاريخ التبليغ الرسمي لمعرفة إن كانت المدة لم تنقضِ بعد"),
    ("ما أعرف متى", "اطلب نسخة من محضر التبليغ من إدارة التنفيذ أو قلم المحكمة"),
    ("قرار إداري", "قدّم تظلماً إدارياً أولاً قبل اللجوء للقضاء الإداري"),
    ("حضانة", "احصل على تقارير اجتماعية وشهادات تدعم أهليتك للحضانة"),
]


def build_case_analysis(query: str, domain: str = "") -> CaseAnalysisReport:
    """
    Deterministically extract case analysis from query markers.
    Does NOT invent facts — only connects user-stated markers to known legal principles.
    """
    report = CaseAnalysisReport(primary_domain=domain or detect_query_domain(query))

    # Strengths
    for marker, _kind, text, marker_domain in _EVIDENCE_STRONG_MARKERS:
        if marker in query and (not marker_domain or
                                   domains_compatible(report.primary_domain, marker_domain)):
            if text not in report.strengths:
                report.strengths.append(text)

    # Weaknesses
    for marker, _kind, text, marker_domain in _EVIDENCE_WEAK_MARKERS:
        if marker in query and (not marker_domain or
                                   domains_compatible(report.primary_domain, marker_domain)):
            if text not in report.weaknesses:
                report.weaknesses.append(text)

    # Opponent arguments
    for marker, marker_domain, text in _OPPONENT_MARKERS:
        if marker in query and (not marker_domain or
                                   domains_compatible(report.primary_domain, marker_domain)):
            if text not in report.opponent_arguments:
                report.opponent_arguments.append(text)

    # What is needed
    for marker, text in _WHAT_NEEDED_MARKERS:
        if marker in query and text not in report.what_is_needed:
            report.what_is_needed.append(text)

    return report


def format_case_analysis(report: CaseAnalysisReport) -> str:
    """Format case analysis as Arabic user-facing text."""
    if not report.has_content():
        return ""

    sections = []

    if report.strengths:
        sections.append("**ما يقوي موقفك:**")
        for s in report.strengths[:4]:
            sections.append(f"• {s}")

    if report.weaknesses:
        sections.append("\n**ما قد يُضعف موقفك:**")
        for w in report.weaknesses[:4]:
            sections.append(f"• {w}")

    if report.opponent_arguments:
        sections.append("\n**ما قد يستند إليه الطرف الآخر:**")
        for o in report.opponent_arguments[:3]:
            sections.append(f"• {o}")

    if report.what_is_needed:
        sections.append("\n**ما تحتاج إتمامه:**")
        for n in report.what_is_needed[:4]:
            sections.append(f"• {n}")

    return "\n".join(sections)


# ══════════════════════════════════════════════════════════════
# 4. OutputCleaner — unified filler removal
# ══════════════════════════════════════════════════════════════

# Filler phrases observed in real output (all variants). Applied mid-text.
_FILLER_PHRASES = [
    "من الجدير بالذكر أن ",
    "من الجدير بالذكر أنه ",
    "من الجدير بالذكر ",
    "تجدر الإشارة إلى أن ",
    "تجدر الإشارة إلى أنه ",
    "تجدر الإشارة إلى ",
    "وتجدر الإشارة إلى أن ",
    "من خلال ما سبق ",
    "بناءً على ما سبق ",
    "في ضوء ما تقدم ",
    "وعليه يمكن القول ",
    "كما ذكرنا سابقاً ",
    "كما أشرنا آنفاً ",
    "هذا ويلاحظ أن ",
    "بحسب النصوص القانونية ",
    "وخلاصة القول ",
    "في الختام نؤكد ",
    "كمساعد قانوني ",
    "بصفتي مساعداً قانونياً ",
    "أهلاً بكم في مكتب ",
    "أهلا بكم في مكتب ",
    "السلام عليكم ورحمة الله وبركاته",
    "السلام عليكم ورحمة الله",
    "بسم الله الرحمن الرحيم",
    "والله أعلم بالصواب",
]

# Robotic/memo openings to strip only when they're the FIRST line
_ROBOTIC_OPENERS = [
    "بسم الله الرحمن الرحيم",
    "السلام عليكم ورحمة الله وبركاته",
    "السلام عليكم ورحمة الله",
    "السلام عليكم",
    "أهلاً بكم في مكتب",
    "أهلا بكم في مكتب",
    "أهلاً بك في مكتب",
    "أهلا بك في مكتب",
]


def remove_fillers(text: str) -> str:
    """Remove filler phrases from text. Returns cleaned text."""
    if not text:
        return text
    result = text
    for filler in _FILLER_PHRASES:
        result = result.replace(filler, "")
    # Clean up double spaces + orphaned punctuation
    result = re.sub(r" {2,}", " ", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    result = re.sub(r"[،,]\s*[،,]", "،", result)
    return result.strip()


def strip_robotic_opener(text: str) -> str:
    """Remove robotic/memo openings from the first line of text."""
    if not text:
        return text
    lines = text.split("\n", 1)
    first = lines[0].strip()
    rest = lines[1] if len(lines) > 1 else ""
    for opener in _ROBOTIC_OPENERS:
        if first.startswith(opener):
            first = first[len(opener):].lstrip(" ،.:\t")
            break
    if first or rest:
        if rest and first:
            return first + "\n" + rest
        return first or rest
    return text


def dedupe_repetitive_phrases(text: str) -> str:
    """
    Detect and remove 2nd+ occurrence of short phrases that repeat too often.
    Targets mid-text style repetition (e.g. same clause 3+ times).
    """
    if not text or len(text) < 80:
        return text
    # Detect short phrases (6-18 Arabic words) that appear 3+ times
    sentences = re.split(r'[.\n]', text)
    seen = {}
    for s in sentences:
        key = s.strip()[:80]
        if 15 <= len(key) <= 160:
            seen[key] = seen.get(key, 0) + 1

    result = text
    for key, count in seen.items():
        if count >= 3:
            # Keep first occurrence, drop ALL subsequent copies
            first_idx = result.find(key)
            if first_idx >= 0:
                # Keep text up through first occurrence + key length,
                # then remove all other copies from the remainder.
                after = result[first_idx + len(key):]
                after = after.replace(key, "")
                result = result[:first_idx] + key + after
    return result


def clean_output(text: str, strip_opener: bool = True) -> str:
    """Full output cleaning pipeline."""
    if not text:
        return text
    out = text
    if strip_opener:
        out = strip_robotic_opener(out)
    out = remove_fillers(out)
    out = dedupe_repetitive_phrases(out)
    return out.strip()


# ══════════════════════════════════════════════════════════════
# 5. LatencyGuard — timeout wrappers
# ══════════════════════════════════════════════════════════════

async def with_timeout(coro, timeout: float, fallback_value: Any = None,
                        label: str = "operation") -> Any:
    """
    Run an async operation with a hard timeout. Returns fallback on timeout.
    Use this to prevent hangs from upstream external calls.
    """
    try:
        start = time.time()
        result = await asyncio.wait_for(coro, timeout=timeout)
        elapsed = time.time() - start
        if elapsed > timeout * 0.8:
            log.info("[LATENCY] %s took %.1fs (near timeout %.1fs)",
                     label, elapsed, timeout)
        return result
    except asyncio.TimeoutError:
        log.warning("[LATENCY] %s timed out after %.1fs — returning fallback",
                    label, timeout)
        return fallback_value
    except Exception as e:
        log.warning("[LATENCY] %s failed: %s — returning fallback", label, e)
        return fallback_value


async def gather_with_timeout(*coros, timeout: float,
                                default_per_coro: Any = None,
                                label: str = "parallel") -> list:
    """Run coroutines in parallel with a shared timeout."""
    try:
        start = time.time()
        results = await asyncio.wait_for(
            asyncio.gather(*coros, return_exceptions=True),
            timeout=timeout,
        )
        elapsed = time.time() - start
        # Replace exceptions with default_per_coro
        cleaned = []
        for r in results:
            if isinstance(r, Exception):
                log.warning("[LATENCY] %s: one coro failed: %s", label, r)
                cleaned.append(default_per_coro)
            else:
                cleaned.append(r)
        log.info("[LATENCY] %s completed in %.1fs (%d coros)",
                 label, elapsed, len(coros))
        return cleaned
    except asyncio.TimeoutError:
        log.warning("[LATENCY] %s batch timed out after %.1fs", label, timeout)
        return [default_per_coro] * len(coros)


# ══════════════════════════════════════════════════════════════
# Convenience API for orchestrator/router integration
# ══════════════════════════════════════════════════════════════

def enhance_with_case_analysis(answer: str, query: str,
                                 domain: str = "",
                                 force: bool = False) -> tuple[str, bool]:
    """
    If the query triggers case analysis, append a deterministic analysis section.
    Returns (enhanced_answer, applied_flag).
    """
    if not force and not should_activate_case_analysis(query, domain):
        return answer, False
    report = build_case_analysis(query, domain)
    if not report.has_content():
        return answer, False
    section = format_case_analysis(report)
    if not section:
        return answer, False
    enhanced = f"{answer.rstrip()}\n\n---\n\n{section}"
    log.info("[CASE_ANALYSIS] activated: strengths=%d weaknesses=%d opponent=%d needed=%d",
             len(report.strengths), len(report.weaknesses),
             len(report.opponent_arguments), len(report.what_is_needed))
    return enhanced, True


def safe_clean(text: str) -> str:
    """Public entry point for output cleaning. Safe to call on any text."""
    try:
        return clean_output(text)
    except Exception as e:
        log.warning("safe_clean failed: %s", e)
        return text
