# -*- coding: utf-8 -*-
"""
DLP — SKELETON_DRAFT builder.

Produces a REAL preliminary legal document when the system can't commit
to a full memo yet. This is NOT a refusal. It delivers:

  أولاً   — الوقائع المتاحة حتى الآن
  ثانياً  — المسائل القانونية الظاهرة
  ثالثاً  — المسار الأقوى مبدئياً
  رابعاً  — المسار البديل (إن وجد)
  خامساً  — ما يحسم بين المسارين
  سادساً  — العناصر الناقصة
  سابعاً  — ما المطلوب لاستكمال الصياغة النهائية
  ثامناً  — طلبات مبدئية منضبطة
  تاسعاً  — تنبيه صريح بطبيعة الصياغة الأولية

Every section is written to be useful to a lawyer reading it — never a
"we can't draft" tone wearing a different hat.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.drafting.drafting_engine import DocumentType, ClientSide
from core.domain_pipeline.issue_graph import IssueGraph, IssueKind
from core.drafting.mqe.prayer import build_prayer, render_prayer
from core.drafting.mqe.not_draftable import _DOC_LABEL  # doc → Arabic label
from core.drafting.dlp.humanize import humanize_gaps


# ═════════════════════════════════════════════════════════════════
# Skeleton result container
# ═════════════════════════════════════════════════════════════════

@dataclass
class SkeletonDraftResult:
    text:               str = ""
    cited_laws:         list[str] = field(default_factory=list)
    missing:            list[str] = field(default_factory=list)
    user_safe_gaps:     list[str] = field(default_factory=list)
    notes:              list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "text_len":       len(self.text),
            "cited_laws":     self.cited_laws[:5],
            "missing":        self.missing[:5],
            "user_safe_gaps": self.user_safe_gaps[:5],
            "notes":          self.notes[:5],
        }


# ═════════════════════════════════════════════════════════════════
# Section builders
# ═════════════════════════════════════════════════════════════════

def _facts_block(facts: list[str]) -> str:
    """Render facts as a compact numbered block, or a neutral placeholder."""
    cleaned = [f.strip() for f in (facts or []) if f and f.strip()]
    if not cleaned:
        return (
            "لم تُقدَّم وقائع تفصيلية حتى الآن. "
            "يُبنى الهيكل أدناه على طبيعة المسألة كما وُصفت."
        )
    lines = []
    for i, f in enumerate(cleaned[:8], 1):
        short = f if len(f) <= 240 else f[:240].rstrip() + "…"
        lines.append(f"({i}) {short}")
    return "\n".join(lines)


def _issues_block(graph: Optional[IssueGraph]) -> str:
    if graph is None or not graph.nodes:
        return ""
    lines: list[str] = []
    if graph.primary_issue and graph.primary_issue in graph.nodes:
        lines.append(
            f"(1) (جوهرية) {graph.nodes[graph.primary_issue].question}"
        )
    idx = 2
    for t in graph.by_kind(IssueKind.THRESHOLD)[:2]:
        lines.append(f"({idx}) (تمهيدية) {t.question}")
        idx += 1
    for s in graph.by_kind(IssueKind.SECONDARY)[:2]:
        lines.append(f"({idx}) (فرعية) {s.question}")
        idx += 1
    return "\n".join(lines)


def _primary_path_block(mlre, graph: Optional[IssueGraph]) -> str:
    """Summarize the primary MLRE path in prose — no raw scores."""
    if mlre is None:
        # Fall back to graph primary issue if MLRE is absent
        if graph is not None and graph.primary_issue:
            q = graph.nodes[graph.primary_issue].question
            return (
                f"المسار الأقوى مبدئياً يتمحور حول: {q.rstrip('؟?')}. "
                "يُبنى الموقف عليه ما لم تطرأ وقائع تغيّر التكييف."
            )
        return ""

    reality = getattr(mlre, "reality", None)
    if reality is None or not getattr(reality, "paths", []):
        return ""

    p = reality.paths[0]
    theory = getattr(p, "legal_theory", "") or ""
    must_prove = list(getattr(p, "what_must_be_proven", []) or [])
    weak = getattr(p, "weakest_point", "") or ""

    parts = []
    if theory:
        parts.append(f"المسار الأقوى مبدئياً: {theory}.")
    if must_prove:
        parts.append("ما يلزم إثباته لتثبيته:")
        for mp in must_prove[:3]:
            parts.append(f"• {mp}")
    if weak:
        parts.append(f"أخطر نقطة ضعف: {weak}.")
    return "\n".join(parts) if parts else ""


def _alternative_path_block(mlre) -> str:
    if mlre is None:
        return ""
    reality = getattr(mlre, "reality", None)
    if reality is None or len(getattr(reality, "paths", []) or []) < 2:
        return ""
    alt = reality.paths[1]
    theory = getattr(alt, "legal_theory", "") or ""
    weak = getattr(alt, "weakest_point", "") or ""
    parts = []
    if theory:
        parts.append(f"يوجد تكييف بديل معتبر: {theory}.")
    if weak:
        parts.append(f"نقطة ضعف هذا المسار: {weak}.")
    return "\n".join(parts) if parts else ""


def _pivots_block(mlre) -> str:
    if mlre is None:
        return ""
    reality = getattr(mlre, "reality", None)
    if reality is None:
        return ""
    pivots = list(getattr(reality, "pivot_conditions", []) or [])
    tests  = list(getattr(reality, "decisive_tests", []) or [])
    if not pivots and not tests:
        return ""
    lines: list[str] = []
    if pivots:
        lines.append("متى ينتقل المسار الأول إلى البديل:")
        for pc in pivots[:2]:
            lines.append(f"• {pc}")
    if tests:
        lines.append("ما يحسم بين المسارين:")
        for t in tests[:3]:
            lines.append(f"• {t}")
    return "\n".join(lines)


def _cited_laws_block(bound) -> tuple[str, list[str]]:
    """Statute basis — direct links only. Returns (text, cited_laws)."""
    cited: list[str] = []
    if bound is not None:
        for L in getattr(bound, "links", []) or []:
            if getattr(L, "evidence_role", "") != "direct":
                continue
            try:
                c = L.record.public_citation()
            except Exception:
                c = ""
            if c and c not in cited:
                cited.append(c)
            if len(cited) >= 5:
                break
    if not cited:
        return ("", [])
    return ("\n".join(f"• {c}" for c in cited), cited)


def _missing_block(user_safe_gaps: list[str]) -> str:
    if not user_safe_gaps:
        return ""
    return "\n".join(f"• {g}" for g in user_safe_gaps[:5])


def _next_steps_block(user_safe_gaps: list[str],
                        mlre) -> str:
    """What the user must add to move from SKELETON to FULL."""
    lines: list[str] = []
    if user_safe_gaps:
        lines.append("لإكمال الصياغة النهائية، يُحبَّذ توفير ما يلي:")
        for g in user_safe_gaps[:4]:
            lines.append(f"• {g}")
    # Also surface MLRE decisive tests — they double as "what would clinch it"
    if mlre is not None:
        reality = getattr(mlre, "reality", None)
        if reality is not None:
            tests = list(getattr(reality, "decisive_tests", []) or [])
            if tests:
                if lines:
                    lines.append("")
                lines.append("ومن النقاط التي يحسم توفرها الموقف القانوني:")
                for t in tests[:3]:
                    lines.append(f"• {t}")
    return "\n".join(lines)


def _interim_prayer_block(doc_type: DocumentType,
                              client_side: ClientSide,
                              graph: Optional[IssueGraph]) -> str:
    prayer = build_prayer(
        doc_type=doc_type,
        client_side=client_side,
        graph=graph,
        explicit_requests=None,
        mlre_survivors=0,
    )
    rendered = render_prayer(prayer)
    # Prepend SKELETON-appropriate header
    if rendered.strip():
        return (
            "يُقدَّم ما يلي على سبيل الطلبات المبدئية دون المساس بما قد "
            "يستجد عند اكتمال الصياغة النهائية:\n" + rendered
        )
    return ""


def _disclaimer_block() -> str:
    return (
        "⚠️ هذه الصياغة أولية ومبنية على ما توفَّر حتى الآن من وقائع وأدلة. "
        "لا يُعتمد عليها في الإيداع قبل استكمال العناصر المشار إليها، "
        "ومراجعتها مع محامٍ مختص."
    )


# ═════════════════════════════════════════════════════════════════
# Public entry
# ═════════════════════════════════════════════════════════════════

def build_skeleton(
    *,
    doc_type: DocumentType = DocumentType.DEFENSE_MEMO,
    client_side: ClientSide = ClientSide.NEUTRAL,
    facts: Optional[list[str]] = None,
    graph: Optional[IssueGraph] = None,
    bound=None,
    mlre=None,
    raw_gaps: Optional[list[str]] = None,
) -> SkeletonDraftResult:
    """Compose a useful preliminary legal document.

    Every section is optional — empty sections are dropped so the
    skeleton never shows hollow headings.
    """
    result = SkeletonDraftResult()
    label = _DOC_LABEL.get(doc_type, "مذكرة قانونية")

    user_safe_gaps = humanize_gaps(raw_gaps or [])
    result.missing = list(raw_gaps or [])
    result.user_safe_gaps = user_safe_gaps

    # ── Gather section bodies ──
    facts_body     = _facts_block(facts or [])
    issues_body    = _issues_block(graph)
    primary_body   = _primary_path_block(mlre, graph)
    alt_body       = _alternative_path_block(mlre)
    pivots_body    = _pivots_block(mlre)
    statute_body, cited_laws = _cited_laws_block(bound)
    result.cited_laws = cited_laws
    missing_body   = _missing_block(user_safe_gaps)
    next_body      = _next_steps_block(user_safe_gaps, mlre)
    prayer_body    = _interim_prayer_block(doc_type, client_side, graph)
    disclaimer     = _disclaimer_block()

    # ── Assemble with Arabic ordinals, skipping empty bodies ──
    ordinals = [
        "أولاً", "ثانياً", "ثالثاً", "رابعاً", "خامساً",
        "سادساً", "سابعاً", "ثامناً", "تاسعاً", "عاشراً",
    ]

    ordered: list[tuple[str, str]] = []
    ordered.append(("موجز الوقائع المتاحة",         facts_body))
    ordered.append(("المسائل القانونية الظاهرة",   issues_body))
    ordered.append(("المسار الأقوى مبدئياً",       primary_body))
    ordered.append(("المسار البديل المعتبر",       alt_body))
    ordered.append(("ما يحسم بين المسارين",        pivots_body))
    ordered.append(("السند القانوني الأولي",       statute_body))
    ordered.append(("العناصر الناقصة حالياً",      missing_body))
    ordered.append(("المطلوب لاستكمال الصياغة",    next_body))
    ordered.append(("طلبات مبدئية منضبطة",          prayer_body))

    lines: list[str] = [
        f"**{label} — صياغة أولية (SKELETON DRAFT)**",
        "",
        disclaimer,
        "",
    ]

    idx = 0
    for title, body in ordered:
        body = (body or "").strip()
        if not body:
            continue
        lines.append(f"**{ordinals[idx]} — {title}:**")
        lines.append("")
        lines.append(body)
        lines.append("")
        idx += 1
        if idx >= len(ordinals):
            break

    # Closing reminder
    lines.append(
        "يُلتمس تقديم المستندات والتفاصيل المذكورة أعلاه لإنتاج الصياغة "
        "النهائية الكاملة."
    )

    text = "\n".join(lines).rstrip() + "\n"
    result.text = text
    result.notes.append(
        f"skeleton:sections_rendered={idx} "
        f"cited={len(cited_laws)} "
        f"gaps={len(user_safe_gaps)}"
    )
    return result
