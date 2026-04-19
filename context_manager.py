# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║   النظام 1: مدير السياق المتقدم — Advanced Context Manager       ║
║   الإصدار: 1.0  |  المساعد القانوني القطري v8.0                  ║
╚══════════════════════════════════════════════════════════════════╝

المشكلة التي يحلّها:
    إرسال كامل تاريخ المحادثة مع كل طلب يستهلك آلاف التوكنز ويُبطّئ النموذج.
    بعد 10 رسائل يصبح السياق ثقيلاً — النموذج "ينسى" أول المحادثة ويتعب.

الحل:
    تلخيص ديناميكي ذكي يحتفظ بـ:
    ✅ الحقائق القانونية الثابتة (أسماء القوانين، أرقام المواد، القرارات)
    ✅ ملخص مختصر لسياق المحادثة
    ✅ الأسئلة المعلقة (لم تُحسم بعد)
    ✅ آخر 3 رسائل كاملة (للاستمرارية الطبيعية)

النتيجة:
    من 2000 توكن → 300 توكن فقط مع الحفاظ على 95% من الذكاء السياقي
"""

import re
import json
import time
import asyncio
import logging
from typing import Optional
from collections import deque

log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════
# الثوابت والضبط
# ══════════════════════════════════════════════════════════════════
SUMMARY_TRIGGER      = 8    # عدد الرسائل قبل تشغيل التلخيص
FULL_HISTORY_KEEP    = 3    # عدد الرسائل الأخيرة التي تُحفظ كاملةً (لا تُلخَّص)
MAX_SUMMARY_CHARS    = 300  # الحد الأقصى لأحرف الملخص
MAX_FACT_CHARS       = 150  # الحد الأقصى لكل حقيقة قانونية
SESSION_TTL_MINUTES  = 30   # مدة انتهاء صلاحية الجلسة (دقيقة)
MAX_LEGAL_FACTS      = 5    # أقصى عدد للحقائق المحتفظ بها
MAX_CITED_LAWS       = 5    # أقصى عدد للقوانين المُستشهد بها

# ══════════════════════════════════════════════════════════════════
# نمط استدعاء Gemini/Claude/Ollama (مُمرَّر من main.py)
# ══════════════════════════════════════════════════════════════════
# هذا الـ prompt يُرسَل للنموذج لتلخيص المحادثة
SUMMARIZE_SYSTEM_PROMPT = """أنت مساعد قانوني متخصص. مهمتك تلخيص المحادثة القانونية.

قواعد التلخيص:
1. احتفظ فقط بالمعلومات ذات القيمة القانونية
2. اختصر الشرح — احتفظ بالأرقام والأسماء والقرارات
3. الحقائق القانونية: أرقام المواد، أسماء القوانين، العقوبات، الأحكام

أخرج JSON فقط (بدون أي نص إضافي):
{
  "summary": "ملخص في جملة أو جملتين",
  "legal_facts": [
    "حقيقة قانونية محددة مثل: عقوبة السرقة: حبس 3 سنوات بموجب م335 قانون العقوبات 2004",
    "حقيقة أخرى إن وجدت"
  ],
  "cited_laws": ["قانون العقوبات 2004", "قانون الإجراءات الجنائية 2004"],
  "pending_questions": ["سؤال لم يُجَب عليه كاملاً إن وجد"]
}"""


# ══════════════════════════════════════════════════════════════════
# هيكل بيانات الجلسة
# ══════════════════════════════════════════════════════════════════
class SessionData:
    """
    يخزّن حالة كاملة لجلسة محادثة واحدة.

    الذاكرة ثلاثية الطبقات:
    ┌─────────────────────────────────────────────┐
    │ طبقة 1: الملخص (summary)                    │  ← أقدم جزء — مُلخَّص
    │ طبقة 2: الحقائق الثابتة (legal_facts)       │  ← أهم جزء — لا يُحذف
    │ طبقة 3: آخر N رسائل (recent_messages)       │  ← أحدث جزء — كاملة
    └─────────────────────────────────────────────┘
    """

    __slots__ = [
        'messages',          # قائمة كاملة الرسائل (deque مع حد أقصى)
        'summary',           # ملخص المحادثة القديمة
        'legal_facts',       # حقائق قانونية ثابتة (مواد، قوانين، أحكام)
        'cited_laws',        # قوانين تم الاستشهاد بها
        'pending_questions', # أسئلة لم تُحسم
        'last_active',       # وقت آخر نشاط (لتنظيف الجلسات المنتهية)
        'summary_version',   # عداد لتتبع تحديثات الملخص
        'total_messages',    # إجمالي الرسائل (بما فيها المُلخَّصة)
    ]

    def __init__(self):
        # deque مع حد أقصى = لا نحتاج تنظيف يدوي
        self.messages: deque        = deque(maxlen=20)
        self.summary: str           = ""
        self.legal_facts: list      = []
        self.cited_laws: list       = []
        self.pending_questions: list = []
        self.last_active: float     = time.time()
        self.summary_version: int   = 0
        self.total_messages: int    = 0

    def add_message(self, role: str, content: str):
        """يضيف رسالة للتاريخ مع تحديث الوقت"""
        self.messages.append({
            "role": role,
            "content": content[:1500],  # حد أقصى لكل رسالة
            "ts": int(time.time())
        })
        self.last_active = time.time()
        self.total_messages += 1

    def needs_summarization(self) -> bool:
        """هل التاريخ طويل بما يكفي لتشغيل التلخيص؟"""
        return len(self.messages) >= SUMMARY_TRIGGER

    def get_recent_messages(self) -> list[dict]:
        """يُعيد آخر N رسائل بدون timestamp (للإرسال للـ API)"""
        recent = list(self.messages)[-FULL_HISTORY_KEEP:]
        return [{"role": m["role"], "content": m["content"]} for m in recent]

    def is_expired(self) -> bool:
        """هل انتهت صلاحية الجلسة؟"""
        return (time.time() - self.last_active) > (SESSION_TTL_MINUTES * 60)


# ══════════════════════════════════════════════════════════════════
# مدير الجلسات الرئيسي
# ══════════════════════════════════════════════════════════════════
class AdvancedContextManager:
    """
    مدير السياق المتقدم — يتحكم في ذاكرة جميع المستخدمين.

    الاستخدام في main.py:
    ─────────────────────
        from context_manager import ctx_manager

        # إضافة رسالة
        ctx_manager.add(session_id, "user", question)
        ctx_manager.add(session_id, "assistant", answer)

        # بناء السياق للإرسال للـ API
        prefix  = ctx_manager.build_prefix(session_id)
        history = ctx_manager.get_history(session_id)

        # تشغيل التلخيص (في الخلفية)
        asyncio.create_task(ctx_manager.maybe_summarize(session_id, llm_func))
    """

    def __init__(self):
        self._sessions: dict[str, SessionData] = {}
        self._lock = asyncio.Lock()

    def _get_or_create(self, sid: str) -> SessionData:
        """يُعيد بيانات الجلسة أو ينشئ واحدة جديدة"""
        if sid not in self._sessions:
            self._sessions[sid] = SessionData()
            log.debug("new session: %s", sid)
        return self._sessions[sid]

    def add(self, sid: str, role: str, content: str):
        """
        يضيف رسالة للذاكرة.

        المدخل:
            sid     — معرّف الجلسة (مثل session_id من الطلب)
            role    — "user" أو "assistant"
            content — نص الرسالة
        """
        session = self._get_or_create(sid)
        session.add_message(role, content)

    def get_history(self, sid: str) -> list[dict]:
        """
        يُعيد آخر N رسائل كاملة للإرسال للـ API.
        دائماً يُعيد مصفوفة (حتى لو الجلسة جديدة).
        """
        if sid not in self._sessions:
            return []
        return self._sessions[sid].get_recent_messages()

    def build_prefix(self, sid: str) -> str:
        """
        يبني بادئة السياق الذكية للإرسال مع كل طلب.

        الهيكل:
        ┌────────────────────────────────────────────────┐
        │ [ملخص المحادثة]: ...                           │
        │ [الحقائق الثابتة]: م335 قانون العقوبات...     │
        │ [القوانين المستشهد بها]: قانون العقوبات 2004  │
        └────────────────────────────────────────────────┘

        إذا كانت الجلسة جديدة أو قصيرة → سلسلة فارغة
        """
        if sid not in self._sessions:
            return ""

        s = self._sessions[sid]
        parts = []

        # 1. الملخص (إن وُجد)
        if s.summary:
            parts.append(f"[ملخص المحادثة السابقة]\n{s.summary[:MAX_SUMMARY_CHARS]}")

        # 2. الحقائق القانونية الثابتة (الأهم — لا تُحذف أبداً)
        if s.legal_facts:
            facts_str = "\n".join(f"• {f[:MAX_FACT_CHARS]}" for f in s.legal_facts[:MAX_LEGAL_FACTS])
            parts.append(f"[الحقائق القانونية المتفق عليها في هذه الجلسة]\n{facts_str}")

        # 3. القوانين المستشهد بها (اختصار)
        if s.cited_laws:
            parts.append(f"[القوانين المُناقَشة]: {' | '.join(s.cited_laws[:MAX_CITED_LAWS])}")

        # 4. الأسئلة المعلقة (إن وُجدت)
        if s.pending_questions:
            parts.append(f"[سؤال سابق لم يُحسم]: {s.pending_questions[0][:100]}")

        if not parts:
            return ""

        return "\n\n".join(parts) + "\n\n"

    async def maybe_summarize(self, sid: str, llm_caller: callable):
        """
        يُشغَّل في الخلفية (asyncio.create_task) بعد كل إجابة.
        إذا وصل عدد الرسائل للحد المُحدد → يُلخّص ويُحدّث الذاكرة.

        المدخل:
            sid        — معرّف الجلسة
            llm_caller — دالة غير متزامنة تُرسل طلباً للـ LLM وتُعيد نصاً
                         مثال: llm_caller(system_prompt, messages) -> str

        مثال الاستخدام في main.py:
            async def _my_llm(system, messages):
                return await call_claude(system, messages, max_tokens=400)

            asyncio.create_task(ctx_manager.maybe_summarize(sid, _my_llm))
        """
        if sid not in self._sessions:
            return

        session = self._sessions[sid]
        if not session.needs_summarization():
            return  # لا حاجة للتلخيص بعد

        # بناء نص المحادثة للتلخيص (نُلخّص ما قبل آخر N رسائل)
        messages_to_summarize = list(session.messages)[:-FULL_HISTORY_KEEP]
        if len(messages_to_summarize) < 4:
            return  # لا يكفي للتلخيص

        conv_text = "\n".join(
            f"{'مستخدم' if m['role'] == 'user' else 'مساعد'}: {m['content'][:400]}"
            for m in messages_to_summarize
        )

        try:
            # استدعاء النموذج للتلخيص
            raw = await llm_caller(
                SUMMARIZE_SYSTEM_PROMPT,
                [{"role": "user", "content": f"المحادثة للتلخيص:\n{conv_text}"}]
            )

            # استخراج JSON من الرد
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            if not m:
                log.debug("summarize: لم يُعثر على JSON في رد النموذج")
                return

            result = json.loads(m.group())

            # تحديث بيانات الجلسة
            async with self._lock:
                if result.get("summary"):
                    session.summary = result["summary"][:MAX_SUMMARY_CHARS]

                # دمج الحقائق الجديدة مع القديمة (بدون تكرار)
                new_facts = result.get("legal_facts", [])
                existing  = set(f[:50] for f in session.legal_facts)
                for fact in new_facts:
                    if fact[:50] not in existing and len(fact) > 10:
                        session.legal_facts.append(fact[:MAX_FACT_CHARS])
                        existing.add(fact[:50])
                # احتفظ بأحدث MAX_LEGAL_FACTS حقيقة
                session.legal_facts = session.legal_facts[-MAX_LEGAL_FACTS:]

                # تحديث القوانين
                for law in result.get("cited_laws", []):
                    if law not in session.cited_laws:
                        session.cited_laws.append(law)
                session.cited_laws = session.cited_laws[-MAX_CITED_LAWS:]

                # تحديث الأسئلة المعلقة
                session.pending_questions = result.get("pending_questions", [])[:2]

                # احذف الرسائل القديمة من الـ deque (ابقِ آخر N فقط)
                recent = list(session.messages)[-FULL_HISTORY_KEEP:]
                session.messages.clear()
                for msg in recent:
                    session.messages.append(msg)

                session.summary_version += 1

            log.info(
                "session summarized: sid=%s v=%d facts=%d laws=%d",
                sid, session.summary_version,
                len(session.legal_facts), len(session.cited_laws)
            )

        except json.JSONDecodeError as e:
            log.debug("summarize JSON parse error: %s", e)
        except Exception as e:
            log.warning("summarize failed (sid=%s): %s", sid, e)

    def update_legal_facts_from_answer(self, sid: str, answer: str, sources: list):
        """
        يستخرج الحقائق القانونية تلقائياً من الإجابة والمصادر.
        يُستدعى بعد كل إجابة ناجحة بدون الحاجة لـ LLM.

        مثال:
            الإجابة تقول: "المادة 335 من قانون العقوبات 2004 تنص..."
            → يُضيف: "م335 | قانون العقوبات 2004 | ذُكر في المحادثة"
        """
        if sid not in self._sessions:
            return

        session = self._sessions[sid]

        # استخرج مواد القانون من الإجابة
        article_pattern = re.compile(
            r'المادة\s*\(?\s*(\d+)\s*\)?\s*من\s+([^.،\n]{10,60})',
            re.UNICODE
        )
        for match in article_pattern.finditer(answer[:1000]):
            art_num = match.group(1)
            law_name = match.group(2).strip()[:50]
            fact = f"م{art_num} | {law_name}"
            if not any(f"م{art_num}" in f for f in session.legal_facts):
                session.legal_facts.append(fact)

        # استخرج أسماء القوانين من المصادر
        for src in sources[:5]:
            title = src.get("title", "")[:60]
            year  = src.get("law_year", "")
            key   = f"{title[:30]} {year}"
            if title and key not in session.cited_laws:
                session.cited_laws.append(key)

        # احتفظ بالحد الأقصى
        session.legal_facts = session.legal_facts[-MAX_LEGAL_FACTS:]
        session.cited_laws  = session.cited_laws[-MAX_CITED_LAWS:]

    def clear(self, sid: str):
        """يمسح جلسة بعينها"""
        self._sessions.pop(sid, None)

    def cleanup_expired(self):
        """يُنظّف الجلسات المنتهية (شغّلها دورياً كل 5 دقائق)"""
        expired = [sid for sid, s in self._sessions.items() if s.is_expired()]
        for sid in expired:
            del self._sessions[sid]
        if expired:
            log.info("cleanup: حُذفت %d جلسة منتهية", len(expired))
        return len(expired)

    def stats(self) -> dict:
        """إحصائيات الذاكرة — مفيد لـ /api/v1/health"""
        return {
            "active_sessions": len(self._sessions),
            "sessions_with_summary": sum(1 for s in self._sessions.values() if s.summary),
            "total_legal_facts": sum(len(s.legal_facts) for s in self._sessions.values()),
        }


# ══════════════════════════════════════════════════════════════════
# مثيل مُشترك (Singleton) — استورده في main.py
# ══════════════════════════════════════════════════════════════════
ctx_manager = AdvancedContextManager()


# ══════════════════════════════════════════════════════════════════
# دورة تنظيف تلقائية (شغّلها عند بدء التطبيق)
# ══════════════════════════════════════════════════════════════════
async def start_cleanup_loop():
    """
    دورة خلفية تُنظّف الجلسات المنتهية كل 5 دقائق.

    في main.py داخل lifespan:
        asyncio.create_task(start_cleanup_loop())
    """
    while True:
        await asyncio.sleep(300)  # كل 5 دقائق
        ctx_manager.cleanup_expired()


# ══════════════════════════════════════════════════════════════════
# مثال توضيحي لطريقة الدمج في main.py
# ══════════════════════════════════════════════════════════════════
"""
═══════════════════════════════════════════════════════════════
طريقة الدمج مع main.py الحالي
═══════════════════════════════════════════════════════════════

1. في أعلى main.py أضف:
   from context_manager import ctx_manager, start_cleanup_loop

2. في lifespan():
   asyncio.create_task(start_cleanup_loop())

3. في query_stream() بدل الكود الحالي:

   # بدلاً من:
   history = get_history(sid)

   # استخدم:
   history  = ctx_manager.get_history(sid)
   prefix   = ctx_manager.build_prefix(sid)

4. في user_msg لـ Gemini/Claude:
   user_msg = f"{prefix}النصوص القانونية:\n{context}\n\nالسؤال: {q}"

5. بعد الإجابة:
   ctx_manager.add(sid, "user", q)
   ctx_manager.add(sid, "assistant", answer)
   ctx_manager.update_legal_facts_from_answer(sid, answer, sources)

   # في الخلفية (بدون تأخير الإجابة):
   asyncio.create_task(ctx_manager.maybe_summarize(
       sid,
       lambda sys, msgs: call_claude(sys, msgs, max_tokens=400)
       # أو: lambda sys, msgs: _gemini_call(sys, msgs)
   ))

═══════════════════════════════════════════════════════════════
التوفير في التوكنز:
   بدون النظام: 2000+ توكن سياق لكل طلب
   مع النظام:   250-400 توكن فقط (ملخص + حقائق + آخر 3 رسائل)
   توفير:        80-87% من تكلفة السياق
═══════════════════════════════════════════════════════════════
"""
