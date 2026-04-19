# -*- coding: utf-8 -*-
"""
REUP — Legacy Text Signature Detector.

Immutable signature bank that MUST NEVER appear in a user-facing
response emitted by the unified runtime. Every signature is a symptom
of a specific pre-REUP execution path (old synthesis, legacy refusal,
contamination template, raw telemetry, etc.).

If `detect_legacy_signatures(text)` returns any hits, the output gate
REJECTS the response — no matter which layer wrote it.

Some signatures have a narrow CONTEXT gate (e.g. "كشف حركة الحساب" is
fine in a banking memo; it's legacy contamination only in other
domains). `detect_legacy_signatures(text, domain=...)` respects those.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


# ═════════════════════════════════════════════════════════════════
# Hard signatures — must NEVER appear in any unified output
# ═════════════════════════════════════════════════════════════════

# Each tuple: (regex, short_id, description)
_HARD_SIGNATURES: list[tuple[re.Pattern, str, str]] = [
    # ── Old strategic reasoning blocks ──
    (re.compile(r"أقوى ما يدعمك[:：]"),           "strategic_strongest",
        "legacy strategic strongest-support block"),
    (re.compile(r"أبرز نقطة ضعف لديك[:：]"),      "strategic_weakness",
        "legacy strategic weakness block"),
    (re.compile(r"ما يُتوقع أن يدفع به الخصم"),  "strategic_opponent",
        "legacy strategic opponent-prediction block"),
    (re.compile(r"الزوايا التي قد يستخدمها ضدك"), "strategic_angles",
        "legacy strategic attack-angle block"),
    (re.compile(r"المسار المتوقع للطرف الآخر"),  "strategic_path",
        "legacy strategic opponent-path block"),
    (re.compile(r"🎯 الدليل الحاسم"),              "decorated_decisive",
        "legacy decorated 'decisive evidence' header"),
    (re.compile(r"📊 السيناريوهات المحتملة"),     "decorated_scenarios",
        "legacy decorated scenarios header"),
    (re.compile(r"⚖️ التحليل القضائي[:：]"),      "decorated_analysis",
        "legacy decorated analysis header"),
    (re.compile(r"🧭 التوصية الاستراتيجية"),     "decorated_recommendation",
        "legacy decorated recommendation header"),
    # ── Raw telemetry / reason codes ──
    (re.compile(r"\blow_issue_coverage\b"),       "raw_low_coverage",
        "raw reason code low_issue_coverage"),
    (re.compile(r"\bno_bound_evidence\b"),        "raw_no_bound",
        "raw reason code no_bound_evidence"),
    (re.compile(r"\bissue_graph_unavailable\b"),  "raw_graph_unavail",
        "raw reason code issue_graph_unavailable"),
    (re.compile(r"\bno_primary_issue\b"),         "raw_no_primary",
        "raw reason code no_primary_issue"),
    (re.compile(r"\binsufficient_facts\b"),       "raw_insufficient",
        "raw reason code insufficient_facts"),
    (re.compile(r"\bclaim_brief_needs_detailed_facts\b"),
        "raw_brief_needs_facts",
        "raw reason code claim_brief_needs_detailed_facts"),
    (re.compile(r"\bengine_exception\b"),         "raw_engine_exc",
        "raw reason code engine_exception"),
    (re.compile(r"\bfact_pattern_lacks_substance\b"),
        "raw_fact_pattern",
        "raw reason code fact_pattern_lacks_substance"),
    (re.compile(r"\bclassification_below_floor\b"),
        "raw_class_floor",
        "raw reason code classification_below_floor"),
    (re.compile(r"\bno_legal_signals\b"),         "raw_no_signals",
        "raw reason code no_legal_signals"),
    (re.compile(r"\bdomain_tie_low_confidence\b"),"raw_domain_tie",
        "raw reason code domain_tie_low_confidence"),
    (re.compile(r"\bevidence_insufficient\b"),    "raw_ev_insuf",
        "raw reason code evidence_insufficient"),
    (re.compile(r"\bmlre_quality_downgrade\b"),   "raw_mlre_downgrade",
        "raw reason code mlre_quality_downgrade"),
    (re.compile(r"\bmqe_quality_downgrade\b"),    "raw_mqe_downgrade",
        "raw reason code mqe_quality_downgrade"),
    # ── Raw enum / hypothesis tags ──
    (re.compile(r"\bprimary_expected\b"),         "raw_h_primary",
        "raw hypothesis enum primary_expected"),
    (re.compile(r"\bclosest_alternative\b"),      "raw_h_alt",
        "raw hypothesis enum closest_alternative"),
    (re.compile(r"\bhybrid_cross_domain\b"),      "raw_h_hybrid",
        "raw hypothesis enum hybrid_cross_domain"),
    (re.compile(r"\bworst_case_exposure\b"),      "raw_h_worst",
        "raw hypothesis enum worst_case_exposure"),
    (re.compile(r"\bminimalist_civil\b"),         "raw_h_minimalist",
        "raw hypothesis enum minimalist_civil"),
    # ── Raw score / chunk / id ──
    (re.compile(r"\bchunk_id\s*[:=]"),             "raw_chunk_id",
        "raw chunk_id marker"),
    (re.compile(r"\bruling_id\s*[:=]"),            "raw_ruling_id",
        "raw ruling_id marker"),
    (re.compile(r"\bcomposite\s*[:=]\s*[\d.]+"),   "raw_composite",
        "raw composite score"),
    (re.compile(r"\bscore\s*[:=]\s*[\d.]+"),       "raw_score",
        "raw score leak"),
    (re.compile(r"\bconfidence\s*[:=]\s*[\d.]+"),  "raw_confidence",
        "raw confidence leak"),
    (re.compile(r"\[TRACE[:].*?\]"),               "raw_trace",
        "internal trace marker"),
    # ── Generic refusal shells ──
    (re.compile(r"غير\s+مدعوم\s+عبر\s+المسار"),   "legacy_unsupported_msg",
        "legacy 'unsupported via this path' refusal"),
    (re.compile(r"يرجى إعادة شرح القضية"),         "legacy_reexplain",
        "legacy 're-explain your case' generic refusal"),
    # ── StructuredInsufficiencyResponse (pre-REUP) refusal phrases ──
    # These three phrases originate in
    # core/legal_gates.py::StructuredInsufficiencyResponse.to_arabic and
    # were reaching the user via the fail-closed pipeline's block paths.
    # They are now hard-banned anywhere in user-facing output.
    (re.compile(r"لم\s+تتوفر\s+شروط"),             "legacy_insufficiency_header",
        "legacy StructuredInsufficiency header ('لم تتوفر شروط...')"),
    (re.compile(r"ما\s+يلزم\s+لاستكمال\s+التحليل"),
        "legacy_insufficiency_needed",
        "legacy StructuredInsufficiency section title "
        "('ما يلزم لاستكمال التحليل')"),
    (re.compile(r"أقصى\s+ما\s+يمكن\s+قوله\s+الآن"),
        "legacy_insufficiency_max_conclusion",
        "legacy StructuredInsufficiency conclusion framing "
        "('أقصى ما يمكن قوله الآن')"),
    # Close variants frequently co-occurring with the above
    (re.compile(r"لم\s+تتوفر\s+شروط\s+إصدار\s+جواب"),
        "legacy_insufficiency_header_variant",
        "legacy variant of the insufficiency opener"),
    # ── Raw "حكم قضائي — رقم" in isolation (without domain context) ──
    # (handled via context_signatures below)
]


# Context-gated signatures — ok in some domains, legacy in others
_CONTEXT_SIGNATURES: list[tuple[re.Pattern, str, set[str]]] = [
    # pattern, id, set of ALLOWED domains
    (re.compile(r"محاضر اجتماعات الشركاء"),      "partner_minutes",
        {"commercial", "partnership"}),
    (re.compile(r"سند دين موقّع"),                 "debt_note",
        {"civil", "commercial", "banking"}),
    (re.compile(r"كشف حركة الحساب"),               "bank_statement",
        {"banking", "commercial"}),
    (re.compile(r"الدائرة المصرفية"),              "banking_circuit",
        {"banking"}),
    (re.compile(r"لجنة فض المنازعات الإيجارية"),  "rental_committee",
        {"rental", "real_estate"}),
    (re.compile(r"لجنة فض المنازعات العمالية"),   "employment_committee",
        {"employment"}),
]


# "Soft" NOT_DRAFTABLE signature — this phrase is ALLOWED in
# NOT_DRAFTABLE_YET / SKELETON_DRAFT sections, banned elsewhere.
_SOFT_REFUSAL_PATTERN = re.compile(
    r"تعذّر صياغة (?:مذكرة|مذكرة دفاع|مذكرة رد|صحيفة دعوى|نقاط مرافعة|قائمة الدفوع|تلخيص ملف القضية|مذكرة بطلب|مذكرة قانونية)"
)


# SKELETON_DRAFT marker — presence of this flips the "refusal" check to "allowed"
_SKELETON_MARKERS = (
    "صياغة أولية",
    "SKELETON DRAFT",
    "ما ينقص حالياً",
    "المطلوب لاستكمال الصياغة",
)


# ═════════════════════════════════════════════════════════════════
# Report type
# ═════════════════════════════════════════════════════════════════

@dataclass
class LegacyDetectionReport:
    hits:             list[str] = field(default_factory=list)   # signature ids
    details:          list[dict] = field(default_factory=list)  # [{id, match, snippet}]
    context_allowed:  list[str] = field(default_factory=list)   # ids cleared by context
    is_clean:         bool = True

    def to_dict(self) -> dict:
        return {
            "is_clean":         self.is_clean,
            "hits":             sorted(set(self.hits))[:10],
            "context_allowed":  sorted(set(self.context_allowed))[:5],
            "details":          self.details[:5],
        }


# ═════════════════════════════════════════════════════════════════
# Public API
# ═════════════════════════════════════════════════════════════════

def detect_legacy_signatures(
    text: str,
    *,
    domain: str = "",
    is_draftable_skeleton: bool = False,
    is_not_draftable: bool = False,
) -> LegacyDetectionReport:
    """Scan the text for legacy signatures.

    `domain` gates the context-sensitive signatures.
    `is_draftable_skeleton=True` allows the "تعذّر صياغة" phrase when the
    text is a structured SKELETON_DRAFT or a NOT_DRAFTABLE_YET message.
    """
    report = LegacyDetectionReport()
    if not text:
        return report

    # Hard-signature scan
    for pat, sig_id, desc in _HARD_SIGNATURES:
        m = pat.search(text)
        if m:
            report.hits.append(sig_id)
            report.details.append({
                "id":       sig_id,
                "desc":     desc,
                "snippet":  text[max(0, m.start() - 20):m.end() + 30],
            })

    # Context-gated signatures
    d = (domain or "").lower()
    for pat, sig_id, allowed in _CONTEXT_SIGNATURES:
        m = pat.search(text)
        if not m:
            continue
        if d in allowed:
            report.context_allowed.append(sig_id)
        else:
            report.hits.append(sig_id)
            report.details.append({
                "id":       sig_id,
                "desc":     f"legacy template for {sorted(allowed)}",
                "snippet":  text[max(0, m.start() - 20):m.end() + 30],
            })

    # Soft refusal — only ok inside a skeleton or final NOT_DRAFTABLE message
    if _SOFT_REFUSAL_PATTERN.search(text):
        if is_draftable_skeleton or is_not_draftable:
            # fine — the skeleton preamble / not-draftable message uses this
            pass
        elif any(m in text for m in _SKELETON_MARKERS):
            # Document self-identifies as skeleton
            pass
        elif "ما ينقص" in text or "ما يجعلها قابلة" in text:
            # Document self-identifies as structured not-draftable
            pass
        else:
            report.hits.append("soft_refusal_out_of_context")
            report.details.append({
                "id":       "soft_refusal_out_of_context",
                "desc":     "تعذّر صياغة outside NOT_DRAFTABLE / SKELETON context",
                "snippet":  "",
            })

    report.is_clean = len(report.hits) == 0
    return report


def is_output_legacy_free(
    text: str,
    *, domain: str = "",
    is_draftable_skeleton: bool = False,
    is_not_draftable: bool = False,
) -> bool:
    return detect_legacy_signatures(
        text,
        domain=domain,
        is_draftable_skeleton=is_draftable_skeleton,
        is_not_draftable=is_not_draftable,
    ).is_clean
