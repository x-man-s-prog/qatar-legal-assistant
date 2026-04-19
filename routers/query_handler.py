# -*- coding: utf-8 -*-
"""
routers/query_handler.py — Query Models & Shared Helpers
=========================================================
Request validation, enhanced templates, fast LLM helper,
and common constants shared between JSON and streaming paths.
"""
import re
import json
import os
import logging
from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel, field_validator

from core import app_state
from core.config import (
    ANTHROPIC_KEY, GEMINI_KEY, OPENAI_KEY,
    MODEL_CLAUDE_FAST, PRIMARY_MODEL,
)
from services.llm_service import call_claude, stream_gemini, stream_openai

log = logging.getLogger(__name__)


# ══ Pydantic Models ══

class QueryRequest(BaseModel):
    query:      str
    mode:       Optional[str] = "expert"
    model:      Optional[str] = "openai"
    session_id: Optional[str] = "default"
    history:    Optional[list] = []

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise HTTPException(status_code=400, detail="الرجاء إدخال سؤال.")
        if len(v) > 15000:
            raise HTTPException(
                status_code=400,
                detail=f"النص طويل جداً ({len(v)} حرف). الحد الأقصى 15000 حرف."
            )
        v = re.sub(r'<[^>]+>', '', v)
        v = v.replace('\x00', '')
        return v

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: Optional[str]) -> str:
        allowed = {"openai", "gemini", "claude", "ollama"}
        if v and v not in allowed:
            return "openai"
        return v or "openai"

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: Optional[str]) -> str:
        if v not in ("expert", "general"):
            return "expert"
        return v

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: Optional[str]) -> str:
        if not v:
            return "default"
        v = re.sub(r'[^a-zA-Z0-9\-_]', '', v)[:64]
        return v or "default"

    @field_validator("history")
    @classmethod
    def validate_history(cls, v: Optional[list]) -> list:
        if not v:
            return []
        return v[-20:] if len(v) > 20 else v


class FeedbackRequest(BaseModel):
    log_id:  int
    value:   int
    note:    Optional[str] = ""
    query:   Optional[str] = ""
    answer:  Optional[str] = ""
    sources: Optional[list] = []
    model:   Optional[str] = ""


# ══ Enhanced Memo Templates ══

_ENHANCED_TEMPLATES = {}
_TEMPLATE_KEYWORDS = {
    "مذكرة_دفاع_سرقة": ["سرقة", "سرق"],
    "مذكرة_دفاع_ضرب": ["ضرب", "إيذاء", "اعتداء", "دفاع شرعي"],
    "مذكرة_دفاع_شيك": ["شيك", "بدون رصيد"],
    "مذكرة_دفاع_تشهير": ["تشهير", "سب", "قذف", "إلكتروني"],
    "مذكرة_دفاع_احتيال": ["احتيال", "نصب", "ناصبني"],
    "لائحة_فصل_تعسفي": ["فصل", "تعسفي", "طفشني", "طردني", "شالني"],
    "مذكرة_طلاق_للضرر": ["طلاق", "خلع"],
    "مذكرة_حضانة": ["حضانة", "عيال", "أطفال"],
    "لائحة_تعويض": ["تعويض", "ضرر", "حادث"],
    "مذكرة_طعن_تمييز": ["طعن", "تمييز"],
    "مذكرة_إخلاء": ["إخلاء", "إيجار", "مستأجر"],
    "مذكرة_شركات": ["شركة", "شريك", "مساهم"],
}

try:
    _tpl_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "overnight_results", "enhanced_memo_templates.json")
    if os.path.exists(_tpl_path):
        with open(_tpl_path, "r", encoding="utf-8") as f:
            _ENHANCED_TEMPLATES = json.load(f)
        log.info("enhanced_memo_templates loaded: %d templates", len(_ENHANCED_TEMPLATES))
except Exception as e:
    log.debug("enhanced_memo_templates not loaded: %s", e)


def get_enhanced_template(query: str) -> str:
    """Find a matching enhanced memo template and build context from it."""
    if not _ENHANCED_TEMPLATES:
        return ""
    q_lower = query.lower()
    for tpl_name, keywords in _TEMPLATE_KEYWORDS.items():
        for kw in keywords:
            if kw in q_lower:
                tpl = _ENHANCED_TEMPLATES.get(tpl_name)
                if not tpl:
                    continue
                ctx = "\n═══ قالب مذكرة محسّن ═══\n"
                ctx += f"البنية: {' → '.join(tpl.get('structure', []))}\n"
                arts = tpl.get("articles", [])
                if arts:
                    ctx += "\n📜 المواد القانونية المطلوبة:\n"
                    for a in arts[:5]:
                        ctx += f"  م.{a.get('article','')} {a.get('law','')}: {a.get('text','')[:300]}\n"
                ruls = tpl.get("rulings", [])
                if ruls:
                    ctx += "\n⚖️ أحكام تمييز مرتبطة:\n"
                    for r in ruls[:3]:
                        ctx += f"  {r[:250]}\n"
                defs = tpl.get("defenses", [])
                if defs:
                    ctx += f"\n🛡️ الدفوع المقترحة: {' | '.join(defs)}\n"
                sp = tpl.get("style_phrases", {})
                starters = sp.get("بدايات_دفوع", [])[:3]
                if starters:
                    ctx += "\n✍️ عبارات افتتاح الدفوع:\n"
                    for s in starters:
                        ctx += f"  • {s}\n"
                return ctx
    return ""


# ══ Fast LLM Helpers ══

async def fast_llm_call(sys_p: str, msgs: list) -> str:
    """Quick LLM call for intent/normalization — uses gateway or fastest available model."""
    try:
        if app_state.GW_AVAILABLE:
            return await app_state.llm_gw.call(system=sys_p or " ", messages=msgs, max_tokens=150)
        if ANTHROPIC_KEY:
            return await call_claude(sys_p or " ", msgs, MODEL_CLAUDE_FAST, 150)
        elif GEMINI_KEY:
            parts = []
            async for t in stream_gemini(sys_p or " ", msgs, max_tokens=150):
                parts.append(t)
            return "".join(parts)
        elif OPENAI_KEY:
            parts = []
            async for t in stream_openai(sys_p or " ", msgs, max_tokens=150):
                parts.append(t)
            return "".join(parts)
    except Exception:
        pass
    return ""


async def fast_llm_call_no_gw(sys_p: str, msgs: list) -> str:
    """Quick LLM call without gateway (for streaming path)."""
    try:
        if ANTHROPIC_KEY:
            return await call_claude(sys_p or " ", msgs, MODEL_CLAUDE_FAST, 150)
        elif GEMINI_KEY:
            parts = []
            async for t in stream_gemini(sys_p or " ", msgs, max_tokens=150):
                parts.append(t)
            return "".join(parts)
        elif OPENAI_KEY:
            parts = []
            async for t in stream_openai(sys_p or " ", msgs, max_tokens=150):
                parts.append(t)
            return "".join(parts)
    except Exception:
        pass
    return ""


# ══ Drafting Detection Constants ══

DRAFTING_DETECT = (
    'صيغ لي', 'صيغ ', 'صياغة', 'اكتب لي', 'اكتب مذكرة', 'نموذج عقد', 'نموذج مذكرة',
    'عقد إيجار', 'عقد عمل', 'عقد شراكة', 'عقد بيع', 'عقد خدمات',
    'مذكرة دفاع', 'مذكرة', 'لائحة دعوى', 'لائحة', 'شكوى رسمية',
    'أبي عقد', 'أبغى عقد', 'أريد عقد', 'حرر لي', 'جهز لي',
    'نموذج شكوى', 'أبي نموذج', 'ابي مذكرة', 'أبي مذكرة', 'ابغي مذكرة',
    'عطني نموذج', 'عطني مذكرة', 'صياغة مخصصة',
)

LEGAL_CITATION_RULE = (
    "\n\n⚠️⚠️ هذه وثيقة قانونية رسمية تُقدّم للمحكمة. التعليمات التالية إلزامية وليست اختيارية:\n\n"
    "【ممنوع مطلقاً】 لا تكتب فراغات مثل [رقم المادة] أو [اسم القانون] أو [___].\n"
    "إذا عندك رقم المادة من السياق → استخدمه. إذا ما عندك → اكتب اسم القانون فقط بدون رقم مادة.\n\n"
    "【أسلوب المحكمة إلزامي】 استخدم عبارات: 'لما كان ذلك وكان الثابت...' و'ومن ثم فإن...' و'وبإنزال ما تقدم...'\n\n"
    "⛔⛔ لا تذكر رقم مادة إلا إذا ظهر في السياق أعلاه — لا تختلق أرقاماً أبداً.\n"
    "⛔ لا تستخدم m40 أو m326 — اكتب 'المادة 40' بالعربي.\n"
    "⛔ م.357 عقوبات = شيكات فقط! مواد الحضانة = م.166, 173, 174, 178 أسرة.\n"
    "⛔ إذا شككت في رقم المادة → لا تذكره.\n\n"
    "【إلزامي في كل دفع】\n"
    "1. اذكر رقم المادة + اسم القانون + رقمه + سنته. مثال: 'وفقاً للمادة 61 من قانون العمل رقم 14 لسنة 2004'\n"
    "2. إذا وجدت مبادئ تمييز في النصوص أعلاه → استخدمها: 'وقد قضت محكمة التمييز في الطعن رقم X لسنة Y بأن...'\n"
    "3. كل دفع يتبع منهج IRAC: المسألة → القاعدة (النص + تفسير التمييز) → التطبيق → النتيجة\n"
    "4. القاضي لن يقبل دفعاً بدون سند قانوني — هذا ليس موضوع إنشاء بل وثيقة قضائية\n\n"
    "【لا تفعل】\n"
    "- ⛔ لا تذكر رقم مادة لم يظهر في السياق أعلاه — إذا ما عرفت الرقم اذكر اسم القانون فقط\n"
    "- ⛔ لا تخلط بين القوانين — مادة الشيك (357) لا تُذكر في مذكرة حضانة!\n"
    "- لا تستخدم تنسيق m85 أو m815 — استخدم 'المادة 85' بالعربي\n"
    "- لا تترك أي دفع بدون سند قانوني\n"
)

# Sources visibility keywords
SOURCES_KEYWORDS = ["مراجع","مصادر","سند قانوني","أساس قانوني","المادة اللي","وين مكتوب","أعطني السند","أبي المراجع","المرجع"]


def should_show_sources(q: str) -> bool:
    """Check if user explicitly requested sources."""
    q_lower = q.lower()
    return any(w in q_lower for w in SOURCES_KEYWORDS)
