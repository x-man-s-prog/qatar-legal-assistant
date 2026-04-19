# -*- coding: utf-8 -*-
"""
Query Rewriting Engine
=======================
Transforms raw user input into clearer, machine-usable query forms
BEFORE downstream layers (domain detection, scenario guidance, risk, retrieval).

- Normalizes Gulf/Qatari colloquial Arabic
- Preserves user intent and legal terms
- Does NOT invent facts or resolve ambiguity
- Produces multiple safe internal representations
- Fully deterministic (no LLM)
"""
from __future__ import annotations
import re, logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("query_rewriter")


# ══════════════════════════════════════════════════════════════
# Query Rewrite Result
# ══════════════════════════════════════════════════════════════

@dataclass
class QueryRewriteResult:
    original_query: str = ""
    normalized_query: str = ""         # spelling + diacritics cleaned
    rewritten_query: str = ""          # semantically clearer form
    retrieval_query: str = ""          # keyword-optimized for search
    detected_domain_hint: str = ""     # best-guess domain
    ambiguity_flags: list[str] = field(default_factory=list)
    emotional_signals: list[str] = field(default_factory=list)
    urgency_signals: list[str] = field(default_factory=list)
    preserved_legal_terms: list[str] = field(default_factory=list)
    style: str = ""                    # formal / colloquial / fragmented / emotional
    notes_internal: list[str] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════
# Colloquial Arabic Normalizer
# ══════════════════════════════════════════════════════════════

# Gulf colloquial → clearer Arabic mappings (phrase-level, ordered longest-first)
_COLLOQUIAL_PHRASES = [
    # Action / intent phrases
    ("وش أسوي الحين", "ماذا أفعل الآن"),
    ("ايش اسوي الحين", "ماذا أفعل الآن"),
    ("شو أسوي الحين", "ماذا أفعل الآن"),
    ("وش أسوي", "ماذا أفعل"),
    ("ايش اسوي", "ماذا أفعل"),
    ("شو أسوي", "ماذا أفعل"),
    ("شسوي", "ماذا أفعل"),
    ("الحين وش", "الآن ماذا"),
    ("وش الحل", "ما الحل"),
    ("وش وضعي", "ما وضعي القانوني"),
    ("وش حقي", "ما حقي"),
    ("وش حقوقي", "ما حقوقي"),
    ("ايش حقي", "ما حقي"),
    # Knowledge / want phrases
    ("أبي أعرف", "أريد أن أعرف"),
    ("ابي اعرف", "أريد أن أعرف"),
    ("أبغى أعرف", "أريد أن أعرف"),
    ("أبي حقوقي", "أريد معرفة حقوقي"),
    ("ابي حقوقي", "أريد معرفة حقوقي"),
    ("ابغى حقوقي", "أريد معرفة حقوقي"),
    # Help phrases
    ("ساعدني بسرعة", "أحتاج مساعدة عاجلة"),
    ("محتاج مساعدة", "أحتاج مساعدة"),
    ("ساعدوني", "أحتاج مساعدة"),
    # Confusion phrases
    ("ماني فاهم", "لم أفهم"),
    ("مو فاهم", "لم أفهم"),
    ("ما فهمت شي", "لم أفهم شيئاً"),
    ("ما فهمت", "لم أفهم"),
    ("ما أدري", "لا أعلم"),
    ("مو عارف", "لا أعلم"),
    # Situation phrases
    ("بورطة", "في مشكلة"),
    ("متورط", "متورط في مشكلة"),
    ("كيف أتصرف", "كيف يجب أن أتصرف"),
    ("شلون أتصرف", "كيف يجب أن أتصرف"),
    # Negation / disappointment
    ("بس ما", "لكن لم"),
    ("بس والله", "لكن والله"),
]

# Word-level colloquial → standard mappings
_COLLOQUIAL_WORDS = {
    "أبي": "أريد",
    "ابي": "أريد",
    "ابغى": "أريد",
    "أبغى": "أريد",
    "يبي": "يريد",
    "تبي": "تريد",
    "مو": "ليس",
    "ماني": "لست",
    "والحين": "والآن",
    "الحين": "الآن",
    "وش": "ماذا",
    "ايش": "ماذا",
    "ليش": "لماذا",
    "شلون": "كيف",
    "هالشي": "هذا الشيء",
    "هالموضوع": "هذا الموضوع",
    "يبيني": "يريدني",
    "طيب": "حسناً",
    "زين": "حسناً",
    "عيالي": "أطفالي",
    "عيال": "أطفال",
    "ولد": "ابن",
    "بنت": "ابنة",
}

# Spelling normalization pairs
_SPELLING_FIXES = [
    (r"إ", "ا"),   # Keep both forms — normalize later
    (r"أ", "ا"),
    (r"آ", "ا"),
    (r"ة\b", "ه"),  # Only for matching, not for output
    (r"ى\b", "ي"),
]

# Legal terms to NEVER rewrite (preserve exactly)
_PRESERVED_LEGAL_TERMS = [
    "مادة", "قانون", "نظام", "لائحة", "مرسوم", "أمر أميري",
    "محكمة", "قاضي", "نيابة", "جلسة", "حكم", "طعن", "استئناف", "تمييز",
    "عقد", "شرط جزائي", "تعويض", "كفالة", "ضمان",
    "فصل تعسفي", "مكافأة نهاية الخدمة", "إنهاء خدمة",
    "حضانة", "نفقة", "خلع", "طلاق", "ميراث", "وصية",
    "إيجار", "إخلاء", "مستأجر", "مؤجر",
    "مخدرات", "حيازة", "تعاطي", "اتجار",
    "تقادم", "مهلة", "ميعاد",
]

# Emotional signals to detect (preserve, don't remove)
_EMOTIONAL_SIGNALS = [
    ("خايف", "fear"), ("خوف", "fear"), ("قلقان", "fear"),
    ("مظلوم", "injustice"), ("ظلم", "injustice"), ("ظالمين", "injustice"),
    ("ندمت", "regret"), ("ندمان", "regret"),
    ("ضربني", "violence"), ("ضربوني", "violence"), ("يضربني", "violence"),
    ("يهددني", "threat"), ("تهديد", "threat"),
    ("يبتزني", "blackmail"), ("يبتزوني", "blackmail"), ("ابتزاز", "blackmail"),
    ("طفشت", "frustration"), ("تعبت", "frustration"), ("يأس", "despair"),
    ("محتار", "confusion"), ("حيران", "confusion"),
]

# Urgency signals
_URGENCY_SIGNALS = [
    ("بسرعة", "rush"), ("فوراً", "immediate"), ("ضروري", "necessary"),
    ("عاجل", "urgent"), ("مستعجل", "urgent"), ("اليوم", "today"),
    ("بكرة", "tomorrow"), ("الحين", "now"), ("الآن", "now"),
    ("فات الموعد", "deadline_passed"), ("يضيع حقي", "rights_at_risk"),
    ("ينتهي", "expiring"),
]

# Domain hint keywords (broader than scenario engine — for hints only)
_DOMAIN_HINTS = {
    "employment": [
        "شغل", "وظيفة", "فصل", "طرد", "راتب", "مكافأة", "كفيل", "عقد عمل",
        "استقال", "دوام", "إذن خروج", "نقل كفالة", "شركة", "مدير",
        "موظف", "خدمة", "إقامة", "عمال", "عمالة",
    ],
    "criminal": [
        "شرطة", "نيابة", "مخدرات", "سرقة", "ضرب", "حكم", "سجن", "متهم",
        "جريمة", "ابتزاز", "تحرش", "تزوير", "قبض", "قضية", "حشيش",
        "غيابي", "تهمة", "جنائي",
    ],
    "family": [
        "طلاق", "حضانة", "نفقة", "زوج", "زوجة", "طليق", "ميراث",
        "أطفال", "عيال", "خلع", "عدة", "صداق", "زواج", "أسرة",
    ],
    "rental": [
        "إيجار", "شقة", "مالك", "مستأجر", "إخلاء", "تأمين", "سكن",
        "بيت", "عقار",
    ],
    "deadline": [
        "طعن", "اعتراض", "مهلة", "تقادم", "موعد", "مدة", "إشعار",
        "فات", "ينتهي", "يضيع",
    ],
}


class ColloquialArabicNormalizer:
    """Normalizes Gulf/Qatari colloquial Arabic to clearer standard forms."""

    def __init__(self):
        # Pre-compile preserved terms for fast lookup
        self._preserved = set(_PRESERVED_LEGAL_TERMS)

    def normalize_spelling(self, query: str) -> str:
        """Basic Arabic spelling normalization (diacritics, hamza variants)."""
        # Remove diacritics
        q = re.sub(r'[\u064B-\u065F\u0670]', '', query)
        # Normalize whitespace
        q = re.sub(r'\s+', ' ', q).strip()
        return q

    def normalize_colloquial_forms(self, query: str) -> str:
        """Replace Gulf colloquial phrases and words with clearer forms."""
        q = query

        # Phase 1: phrase-level replacements (longest first to avoid partial matches)
        for colloquial, standard in _COLLOQUIAL_PHRASES:
            if colloquial in q:
                q = q.replace(colloquial, standard)

        # Phase 2: word-level replacements (only standalone words)
        words = q.split()
        result = []
        for w in words:
            # Check if this word is a preserved legal term
            if any(t in w for t in self._preserved):
                result.append(w)
            elif w in _COLLOQUIAL_WORDS:
                result.append(_COLLOQUIAL_WORDS[w])
            else:
                result.append(w)

        return " ".join(result)

    def preserve_key_legal_tokens(self, query: str) -> list[str]:
        """Extract legal terms that must be preserved in any rewrite."""
        found = []
        for term in _PRESERVED_LEGAL_TERMS:
            if term in query:
                found.append(term)
        return found

    def detect_equivalent_formulations(self, query: str) -> list[tuple[str, str]]:
        """Detect known colloquial → standard equivalences in the query."""
        found = []
        for colloquial, standard in _COLLOQUIAL_PHRASES:
            if colloquial in query:
                found.append((colloquial, standard))
        for word in query.split():
            if word in _COLLOQUIAL_WORDS:
                found.append((word, _COLLOQUIAL_WORDS[word]))
        return found


# ══════════════════════════════════════════════════════════════
# Rewrite Safety Policy
# ══════════════════════════════════════════════════════════════

class RewriteSafetyPolicy:
    """Ensures rewrites don't distort meaning, drop ambiguity, or invent facts."""

    def validate_rewrite(self, original: str, rewritten: str) -> bool:
        """Check that the rewrite is safe — meaning not drastically changed."""
        if not rewritten or not rewritten.strip():
            return False
        # Rewrite should not be drastically shorter (losing info)
        if len(rewritten) < len(original) * 0.3 and len(original) > 10:
            return False
        # Rewrite should not be drastically longer (inventing info)
        if len(rewritten) > len(original) * 4 and len(original) > 5:
            return False
        return True

    def detect_meaning_shift(self, original: str, rewritten: str) -> bool:
        """Detect if a rewrite changed the fundamental meaning."""
        # Colloquial + standard negation markers (treated equivalently)
        _NEG = ["ما ", "مو ", "لا ", "ليس", "بدون", "مش",
                "ماني", "مانت", "لم ", "لست", "لسنا", "لستم"]
        neg_in_orig = any(n in original for n in _NEG)
        neg_in_rew = any(n in rewritten for n in _NEG)
        if neg_in_orig != neg_in_rew:
            return True  # negation was added or removed
        return False

    def ensure_ambiguity_preserved(self, original: str,
                                     result: QueryRewriteResult) -> QueryRewriteResult:
        """If the original is ambiguous, ensure the rewrite doesn't fake specificity."""
        # Short vague queries must stay vague
        if len(original.split()) <= 3 and not result.detected_domain_hint:
            result.ambiguity_flags.append("very_short_query")
            result.notes_internal.append("query too short to determine specific intent")

        # Conditional/hypothetical queries must retain ambiguity
        if any(c in original for c in ["إذا", "لو", "في حالة"]):
            result.ambiguity_flags.append("conditional_query")

        # Multi-domain queries must retain multi-domain flag
        domains_found = set()
        for d, keywords in _DOMAIN_HINTS.items():
            if any(kw in original for kw in keywords):
                domains_found.add(d)
        if len(domains_found) > 1:
            result.ambiguity_flags.append("multi_domain")
            result.notes_internal.append(f"multi-domain: {domains_found}")

        return result


# ══════════════════════════════════════════════════════════════
# Query Rewriter
# ══════════════════════════════════════════════════════════════

class QueryRewriter:
    """
    Main rewriter. Transforms raw user input into cleaner forms.
    Fully deterministic — no LLM calls.
    """

    def __init__(self):
        self._normalizer = ColloquialArabicNormalizer()
        self._safety = RewriteSafetyPolicy()

    def rewrite(self, query: str) -> QueryRewriteResult:
        """Full rewrite pipeline. Returns all internal representations."""
        result = QueryRewriteResult(original_query=query)

        if not query or not query.strip():
            return result

        q = query.strip()

        # Step 1: Detect style
        result.style = self._detect_style(q)

        # Step 2: Detect emotional and urgency signals (before any rewriting)
        result.emotional_signals = self._detect_emotional(q)
        result.urgency_signals = self._detect_urgency(q)

        # Step 3: Preserve legal terms
        result.preserved_legal_terms = self._normalizer.preserve_key_legal_tokens(q)

        # Step 4: Normalize spelling
        normalized = self._normalizer.normalize_spelling(q)
        result.normalized_query = normalized

        # Step 5: Rewrite for understanding (colloquial → clearer)
        rewritten = self.rewrite_for_understanding(normalized)
        # Safety check: no meaning shift
        if self._safety.detect_meaning_shift(normalized, rewritten):
            rewritten = normalized  # Revert if meaning shifted
            result.notes_internal.append("rewrite reverted: meaning shift detected")
        if not self._safety.validate_rewrite(normalized, rewritten):
            rewritten = normalized
            result.notes_internal.append("rewrite reverted: validation failed")
        result.rewritten_query = rewritten

        # Step 6: Generate retrieval query
        result.retrieval_query = self.rewrite_for_retrieval(rewritten, q)

        # Step 7: Detect domain hint
        result.detected_domain_hint = self._detect_domain_hint(q)

        # Step 8: Ambiguity preservation
        result = self._safety.ensure_ambiguity_preserved(q, result)

        log.info("[REWRITE] style=%s domain=%s emotional=%s urgency=%s colloquial_maps=%d",
                 result.style, result.detected_domain_hint,
                 len(result.emotional_signals), len(result.urgency_signals),
                 len(self._normalizer.detect_equivalent_formulations(q)))
        return result

    # ── Core Methods ──

    def normalize_arabic(self, query: str) -> str:
        """Normalize spelling + colloquial forms."""
        q = self._normalizer.normalize_spelling(query)
        return self._normalizer.normalize_colloquial_forms(q)

    def detect_colloquial_signals(self, query: str) -> list[tuple[str, str]]:
        """Detect Gulf colloquial patterns in query."""
        return self._normalizer.detect_equivalent_formulations(query)

    def detect_fragmented_query(self, query: str) -> bool:
        """Detect if query is too fragmented to process reliably."""
        words = query.split()
        if len(words) <= 2:
            return True
        # No verb or question word
        question_words = ["هل", "ما", "كم", "كيف", "متى", "أين", "لماذا", "من",
                          "وش", "ايش", "شو", "شلون"]
        has_question = any(w in query for w in question_words)
        has_verb_indicator = any(v in query for v in [
            "أريد", "أبي", "أبغى", "أقدر", "يحق", "فصلوني", "حكموا",
            "طردوني", "ساعدني", "جاني", "وصلني"])
        if not has_question and not has_verb_indicator and len(words) <= 4:
            return True
        return False

    def rewrite_for_understanding(self, query: str) -> str:
        """Rewrite colloquial query into clearer semantic form."""
        return self._normalizer.normalize_colloquial_forms(query)

    def rewrite_for_retrieval(self, rewritten_query: str, original_query: str) -> str:
        """
        Generate a retrieval-optimized form: legal keywords, domain terms, entities.
        Strips filler words, keeps substance.
        """
        # Combine keywords from both original and rewritten
        all_text = original_query + " " + rewritten_query

        # Extract legal / domain keywords
        retrieval_terms = []

        # Add domain keywords found
        for domain, keywords in _DOMAIN_HINTS.items():
            for kw in keywords:
                if kw in all_text and kw not in retrieval_terms:
                    retrieval_terms.append(kw)

        # Add preserved legal terms
        for term in _PRESERVED_LEGAL_TERMS:
            if term in all_text and term not in retrieval_terms:
                retrieval_terms.append(term)

        # Add urgency-relevant terms
        for signal, _ in _URGENCY_SIGNALS:
            if signal in original_query and signal not in retrieval_terms:
                retrieval_terms.append(signal)

        # If few keywords found, pad with substantive words from rewritten query
        if len(retrieval_terms) < 3:
            _FILLER = {"في", "من", "على", "إلى", "هل", "ما", "كم", "كيف", "متى",
                       "أين", "لماذا", "أنا", "أني", "هذا", "هذه", "ذلك", "تلك",
                       "و", "أو", "لكن", "بس", "بعد", "قبل", "عند", "مع",
                       "شيء", "شي", "يعني", "لم", "لا", "ليس", "لست"}
            for w in rewritten_query.split():
                if (len(w) >= 3
                    and w not in _FILLER
                    and w not in retrieval_terms
                    and not w.startswith("ال") or len(w) > 5):
                    retrieval_terms.append(w)
                    if len(retrieval_terms) >= 5:
                        break

        if not retrieval_terms:
            return rewritten_query  # No keywords found, use rewritten as-is

        return " ".join(retrieval_terms[:12])  # Cap at 12 terms

    def preserve_user_intent(self, original: str, rewritten: str) -> str:
        """Ensure original intent keywords are not lost in rewrite."""
        # Check if any legal terms from original are missing in rewritten
        original_legal = self._normalizer.preserve_key_legal_tokens(original)
        for term in original_legal:
            if term not in rewritten:
                rewritten = rewritten + " " + term
        return rewritten

    # ── Detection Helpers ──

    def _detect_style(self, query: str) -> str:
        """Detect the query style: formal, colloquial, fragmented, emotional."""
        has_colloquial = len(self._normalizer.detect_equivalent_formulations(query)) > 0
        has_emotional = len(self._detect_emotional(query)) > 0
        is_fragmented = self.detect_fragmented_query(query)

        if is_fragmented:
            return "fragmented"
        if has_emotional and has_colloquial:
            return "emotional_colloquial"
        if has_emotional:
            return "emotional"
        if has_colloquial:
            return "colloquial"
        return "formal"

    def _detect_emotional(self, query: str) -> list[str]:
        """Detect emotional signals in query."""
        found = []
        for signal, label in _EMOTIONAL_SIGNALS:
            if signal in query:
                found.append(f"{label}:{signal}")
        return found

    def _detect_urgency(self, query: str) -> list[str]:
        """Detect urgency signals in query."""
        found = []
        for signal, label in _URGENCY_SIGNALS:
            if signal in query:
                found.append(f"{label}:{signal}")
        return found

    def _detect_domain_hint(self, query: str) -> str:
        """Best-guess domain hint from query keywords."""
        scores = {}
        for domain, keywords in _DOMAIN_HINTS.items():
            score = sum(1 for kw in keywords if kw in query)
            if score > 0:
                scores[domain] = score
        if not scores:
            return ""
        return max(scores, key=scores.get)


# ══════════════════════════════════════════════════════════════
# Module-level Singleton
# ══════════════════════════════════════════════════════════════

_rewriter: Optional[QueryRewriter] = None


def get_query_rewriter() -> QueryRewriter:
    global _rewriter
    if _rewriter is None:
        _rewriter = QueryRewriter()
    return _rewriter


def rewrite_query(query: str) -> QueryRewriteResult:
    """Convenience function: rewrite a query and return all representations."""
    return get_query_rewriter().rewrite(query)
