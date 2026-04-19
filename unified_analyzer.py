# -*- coding: utf-8 -*-
"""
Unified Analyzer — Phase 1 Core Intelligence Upgrade
=====================================================
Single LLM call replacing classify_intent + extract_legal_meaning.
Latency savings: 400-800ms per request.

Returns a rich analysis dict containing:
  intent, domain, legal_issue, actors, user_goal,
  emotional_state, ambiguity_score, complexity, user_level,
  possible_claims, relevant_laws, urgency, normalized_query
"""
from __future__ import annotations
import json, re, logging, time
from typing import Optional

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# UNIFIED ANALYSIS PROMPT — Single LLM call does everything
# ─────────────────────────────────────────────────────────────────────────────
UNIFIED_ANALYSIS_PROMPT = (
    "أنت محرك تحليل قانوني ذكي. مهمتك: تحليل مدخل المستخدم بعمق في استدعاء واحد.\n\n"
    "افهم:\n"
    "- النية الحقيقية خلف الكلمات (حتى العامية والعاطفية)\n"
    "- اللهجة (خليجية، مصرية، شامية، فصحى)\n"
    "- البعد القانوني الضمني حتى في الشكاوى العاطفية\n"
    "- مستوى المستخدم من أسلوبه\n\n"
    'أخرج JSON فقط بالهيكل التالي (لا نص خارج JSON):\n'
    '{\n'
    '  "intent": "conversation|legal_question_clear|legal_question_implicit|legal_writing_request|emotional_with_legal_intent|emotional_non_legal",\n'
    '  "domain": "criminal|civil|labor|family|commercial|administrative|real_estate|electronic|unknown",\n'
    '  "legal_issue": "المشكلة القانونية الجوهرية بالعربية الرسمية",\n'
    '  "action": "ما حدث أو ما يجب أن يحدث",\n'
    '  "actors": "الأطراف المعنية (ضحية، جاني، طرف أول، طرف ثانٍ)",\n'
    '  "user_goal": "معلومة|توجيه|إجراء|كتابة وثيقة|تفريغ عاطفي",\n'
    '  "emotional_state": "محايد|غاضب|خائف|محبط|يائس|عاجل",\n'
    '  "ambiguity_score": 0.0,\n'
    '  "complexity": "بسيط|متوسط|معقد",\n'
    '  "user_level": "beginner|intermediate|expert",\n'
    '  "possible_claims": ["مطالبة أو جريمة محتملة 1"],\n'
    '  "relevant_laws": ["قانون محتمل 1"],\n'
    '  "urgency": "immediate|soon|not_urgent",\n'
    '  "normalized_query": "الاستعلام القانوني الرسمي الموسع المناسب للبحث في قاعدة بيانات قانونية"\n'
    '}\n\n'
    "قواعد ambiguity_score:\n"
    "- 0.0-0.3: واضح تماماً\n"
    "- 0.3-0.6: غامض نسبياً لكن يمكن الإجابة\n"
    "- 0.6-1.0: غامض جداً يحتاج توضيح\n\n"
    "قواعد user_level:\n"
    "- beginner: لغة عامية، لا مصطلحات قانونية\n"
    "- intermediate: بعض المصطلحات القانونية، فهم عام\n"
    "- expert: مصطلحات قانونية دقيقة، مواد قانونية، إجراءات\n\n"
    'المدخل: "{user_input}"'
)

# ─────────────────────────────────────────────────────────────────────────────
# Rule-based fallback patterns
# ─────────────────────────────────────────────────────────────────────────────
_WRITING_RE  = re.compile(
    r"(اكتب|صغ|صياغة|عريضة|مذكرة|عقد عمل|استئناف|رسالة رسمية|وثيقة|إخطار|إنذار)",
    re.IGNORECASE
)
_EMOTIONAL_RE = re.compile(
    r"(ظلمني|ظالم|فصلوني|طردوني|خانني|حقي ضاع|ما دفعوا|تعبت|خايف|ما أنصفوني)",
    re.IGNORECASE
)
_LEGAL_RE = re.compile(
    r"(قانون|مادة|محكمة|عقوبة|جريمة|حق|شكوى|دعوى|تعويض|عقد|طلاق|حضانة|ميراث|فصل|راتب|إيجار|توقيف|استئناف)",
    re.IGNORECASE
)
_GREETING_RE = re.compile(
    r"^(السلام|مرحبا|هلا|أهلا|صباح|مساء|هاي|hi\b|hello\b|وعليكم)",
    re.IGNORECASE
)
_DOMAIN_RE = {
    "criminal":       re.compile(r"(جريمة|عقوبة|سرقة|اعتداء|قتل|احتيال|اعتقال|جنحة|جناية|حبس|نيابة عامة)", re.I),
    "labor":          re.compile(r"(عمل|راتب|فصل|موظف|صاحب عمل|عقد عمل|إجازة|ساعات عمل|فصل تعسفي)", re.I),
    "family":         re.compile(r"(طلاق|زواج|حضانة|نفقة|مهر|ميراث|أسرة|أحوال شخصية|قاصر)", re.I),
    "civil":          re.compile(r"(تعويض مدني|التزام|ضرر|إيجار|بيع|شراء|مديونية|دين)", re.I),
    "commercial":     re.compile(r"(تجاري|شركة|علامة تجارية|إفلاس|شراكة|استيراد)", re.I),
    "administrative": re.compile(r"(إداري|جواز|إقامة|تأشيرة|حكومة|ترخيص وزارة)", re.I),
    "real_estate":    re.compile(r"(عقار|أرض|شقة|تسجيل ملكية|رهن عقاري)", re.I),
    "electronic":     re.compile(r"(إلكتروني|إنترنت|سوشيال|ابتزاز إلكتروني|جرائم معلوماتية)", re.I),
}

_SEV_MAP = {
    "عاجل":  "critical",
    "يائس":  "high",
    "خائف":  "high",
    "غاضب":  "medium",
    "محبط":  "medium",
    "محايد": "low",
}


def _rule_based_analysis(text: str) -> dict:
    """Fast rule-based fallback used for Ollama mode or when LLM is unavailable."""
    t = text.strip()
    # Intent detection
    if _GREETING_RE.search(t) and len(t.split()) <= 4:
        intent = "conversation"
    elif _WRITING_RE.search(t):
        intent = "legal_writing_request"
    elif _EMOTIONAL_RE.search(t):
        intent = "emotional_with_legal_intent"
    elif _LEGAL_RE.search(t):
        intent = "legal_question_clear"
    else:
        intent = "legal_question_implicit"

    # Domain detection
    domain = "unknown"
    for d, pat in _DOMAIN_RE.items():
        if pat.search(t):
            domain = d
            break

    # Ambiguity score
    words = t.split()
    ambiguity = 0.0
    if len(words) <= 3:
        ambiguity += 0.30
    if not _LEGAL_RE.search(t):
        ambiguity += 0.20
    pronouns = sum(1 for w in words if w in {"هو", "هي", "هم", "هذا", "هذه", "ذلك"})
    if pronouns >= 2:
        ambiguity += 0.15

    return {
        "intent":          intent,
        "domain":          domain,
        "legal_issue":     "",
        "action":          "",
        "actors":          "",
        "user_goal":       "معلومة",
        "emotional_state": "غاضب" if _EMOTIONAL_RE.search(t) else "محايد",
        "ambiguity_score": min(1.0, ambiguity),
        "complexity":      "بسيط" if len(words) <= 5 else "متوسط" if len(words) <= 12 else "معقد",
        "user_level":      "beginner",
        "possible_claims": [],
        "relevant_laws":   [],
        "urgency":         "not_urgent",
        "normalized_query": t,
    }


def _parse_json_safe(raw: str) -> Optional[dict]:
    """Extract and parse the first JSON object from raw LLM output."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE)
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        return None
    fragment = raw[start:end + 1]
    try:
        return json.loads(fragment)
    except json.JSONDecodeError:
        cleaned = re.sub(r",\s*}", "}", fragment)
        cleaned = re.sub(r",\s*]", "]", cleaned)
        try:
            return json.loads(cleaned)
        except Exception:
            return None


async def analyze_user_input(
    text: str,
    llm_caller=None,
    history: Optional[list] = None,
) -> dict:
    """
    PRIMARY ENTRY POINT — Single LLM call unified analysis.

    Replaces: classify_intent() + extract_legal_meaning() + detect_user_level()
    All three are now ONE LLM call with structured JSON output.

    Performance impact: −1 LLM call per request = ~400–800ms saved.
    Graceful degradation: returns rule-based result if LLM unavailable.
    """
    if llm_caller is None:
        return _rule_based_analysis(text)

    # Inject last 3 user messages as context
    ctx_hint = ""
    if history:
        recent = [m["content"][:100] for m in history[-6:] if m.get("role") == "user"][-3:]
        if recent:
            ctx_hint = "\n\nسياق المحادثة السابقة: " + " | ".join(recent)

    prompt = UNIFIED_ANALYSIS_PROMPT.replace("{user_input}", text.strip() + ctx_hint)

    t0 = time.monotonic()
    try:
        raw = await llm_caller("", [{"role": "user", "content": prompt}])
        log.debug("unified_analyzer LLM %.2fs for q='%s'", time.monotonic() - t0, text[:50])
    except Exception as e:
        log.warning("unified_analyzer LLM failed: %s — using rule-based fallback", e)
        return _rule_based_analysis(text)

    result = _parse_json_safe(raw)
    if result is None:
        log.warning("unified_analyzer: JSON parse failed — using rule-based fallback")
        return _rule_based_analysis(text)

    # Validate and normalise
    valid_intents = {
        "conversation", "legal_question_clear", "legal_question_implicit",
        "legal_writing_request", "emotional_with_legal_intent", "emotional_non_legal",
    }
    valid_domains = {
        "criminal", "civil", "labor", "family", "commercial",
        "administrative", "real_estate", "electronic", "unknown",
    }
    if result.get("intent") not in valid_intents:
        result["intent"] = "legal_question_clear"
    if result.get("domain") not in valid_domains:
        result["domain"] = "unknown"

    result.setdefault("legal_issue",     "")
    result.setdefault("action",          "")
    result.setdefault("actors",          "")
    result.setdefault("user_goal",       "معلومة")
    result.setdefault("emotional_state", "محايد")
    result.setdefault("ambiguity_score", 0.0)
    result.setdefault("complexity",      "متوسط")
    result.setdefault("user_level",      "beginner")
    result.setdefault("possible_claims", [])
    result.setdefault("relevant_laws",   [])
    result.setdefault("urgency",         "not_urgent")
    result.setdefault("normalized_query", text)

    try:
        result["ambiguity_score"] = float(result["ambiguity_score"])
    except (ValueError, TypeError):
        result["ambiguity_score"] = 0.0

    if not isinstance(result["possible_claims"], list):
        result["possible_claims"] = []
    if not isinstance(result["relevant_laws"], list):
        result["relevant_laws"] = []

    log.info(
        "unified_analysis: intent=%s domain=%s ambiguity=%.2f complexity=%s level=%s",
        result["intent"], result["domain"],
        result["ambiguity_score"], result["complexity"], result["user_level"],
    )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Adapters — backward compatibility with existing pipeline
# ─────────────────────────────────────────────────────────────────────────────

def analysis_to_intent_mode(analysis: dict) -> tuple:
    """
    Convert unified analysis to (intent_value, mode) pair.
    Backward compatible with route_mode() / classify_intent() callers.
    """
    intent_val = analysis.get("intent", "legal_question_clear")
    mode_map = {
        "conversation":               "conversation",
        "legal_question_clear":       "legal_pipeline",
        "legal_question_implicit":    "legal_pipeline",
        "legal_writing_request":      "legal_writing",
        "emotional_with_legal_intent":"emotional_legal",
        "emotional_non_legal":        "conversation",
    }
    return intent_val, mode_map.get(intent_val, "legal_pipeline")


def analysis_to_semantic_frame(analysis: dict) -> dict:
    """
    Convert unified analysis to semantic_frame dict.
    Backward compatible with legal_decision_engine / legal_argumentation_engine.
    """
    emotional = analysis.get("emotional_state", "محايد")
    return {
        "legal_issue":               analysis.get("legal_issue", ""),
        "action":                    analysis.get("action", ""),
        "actors":                    analysis.get("actors", ""),
        "legal_domain":              analysis.get("domain", "unknown"),
        "severity":                  _SEV_MAP.get(emotional, "medium"),
        "possible_crimes_or_claims": analysis.get("possible_claims", []),
        "relevant_laws":             analysis.get("relevant_laws", []),
        "urgency":                   analysis.get("urgency", "not_urgent"),
        "confidence": (
            "high"   if analysis.get("ambiguity_score", 1.0) < 0.35 else
            "medium" if analysis.get("ambiguity_score", 1.0) < 0.65 else
            "low"
        ),
    }
