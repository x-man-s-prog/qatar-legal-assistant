# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║  النظام 3: طبقة الذكاء — Intelligence Layer                      ║
║  الإصدار: 1.0  |  المساعد القانوني القطري v8.0                   ║
╚══════════════════════════════════════════════════════════════════╝

يضم ثلاثة أنظمة مترابطة:

┌─────────────────────────────────────────────────────────────────┐
│  A. التفكير الداخلي (Internal Monologue)                         │
│     → خطوة مخفية: النموذج يُحلّل قبل أن يُجيب                   │
│     → يكتشف الثغرات والمخاطر القانونية                          │
│     → يخطط هيكل الإجابة قبل كتابتها                             │
│                                                                  │
│  B. منسّق الإجابة (Output Formatter)                             │
│     → إجابة مُهيكَلة بـ Markdown احترافي                         │
│     → جداول للمقارنة، نقاط للحالات، عريض للأحكام                │
│     → إجابة المستخدم العادي ≠ إجابة المحترف                     │
│                                                                  │
│  C. نقطة التحقق (Checkpoint / Chain of Verification)            │
│     → تتحقق أن الإجابة مدعومة فعلاً بنصوص المصادر              │
│     → تكشف الادعاءات غير الموجودة في قاعدة البيانات             │
│     → درجة موثوقية 0-100%                                       │
└─────────────────────────────────────────────────────────────────┘
"""

import re
import json
import time
import asyncio
import logging
from typing import Optional
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════
# Prompts النظام
# ══════════════════════════════════════════════════════════════════

# A. التفكير الداخلي — الخطوة المخفية
INTERNAL_MONOLOGUE_PROMPT = """أنت محلل قانوني خبير. مهمتك تحليل السؤال قبل الإجابة.
هذا التحليل سيبقى مخفياً عن المستخدم — أنت تفكر بصوت عالٍ.

أخرج JSON فقط:
{
  "legal_issue": "ما هي المسألة القانونية الحقيقية؟",
  "legal_category": "جنائي | مدني | تجاري | عمالي | أسرة | إداري",
  "severity": "منخفضة | متوسطة | عالية | بالغة الخطورة",
  "key_gaps": ["ثغرة في المعلومات 1", "ثغرة 2"],
  "applicable_laws": ["قانون مُحتمَل 1", "قانون مُحتمَل 2"],
  "response_structure": ["قسم 1 من الإجابة", "قسم 2", "قسم 3"],
  "user_type_hint": "مواطن عادي | رجل أعمال | محامٍ | موظف | أجنبي",
  "risks_to_mention": ["خطر يجب التنبيه عليه 1", "خطر 2"],
  "needs_lawyer": true,
  "urgency": "فوري | قريب | غير عاجل"
}"""

# B. منسّق الإجابة — Prompt التوليد النهائي
def build_formatter_prompt(monologue: dict, user_type: str = "مواطن") -> str:
    """
    يبني الـ prompt النهائي بناءً على نتيجة التفكير الداخلي.
    الإجابة تتكيف تلقائياً حسب نوع المستخدم وشدة المسألة.
    """
    category   = monologue.get("legal_category", "")
    severity   = monologue.get("severity", "متوسطة")
    user_hint  = monologue.get("user_type_hint", user_type)
    risks      = monologue.get("risks_to_mention", [])
    structure  = monologue.get("response_structure", [])
    need_lawyer= monologue.get("needs_lawyer", False)
    urgency    = monologue.get("urgency", "غير عاجل")

    # بناء تعليمات التنسيق
    format_rules = []

    # حدة الإجابة تختلف بحسب خطورة المسألة
    if severity == "بالغة الخطورة":
        format_rules.append("⚠️ ابدأ بتحذير واضح لخطورة الموضوع")
    elif severity == "عالية":
        format_rules.append("انتبه للمخاطر القانونية وأبرزها")

    # تكيف اللغة مع نوع المستخدم
    if "محامٍ" in user_hint or "محامي" in user_hint:
        format_rules.append("استخدم المصطلحات القانونية الدقيقة بدون تبسيط مفرط")
    elif "أجنبي" in user_hint:
        format_rules.append("بسّط اللغة وأضف تفسيراً للمصطلحات القانونية")
    else:
        format_rules.append("اشرح المصطلحات القانونية بلغة بسيطة مفهومة")

    # هيكل الإجابة المطلوب
    structure_hint = ""
    if structure:
        structure_hint = f"\nرتّب إجابتك على: {' ← '.join(structure[:4])}"

    # المخاطر
    risks_hint = ""
    if risks:
        risks_hint = f"\n⚠️ تنبّه لذكر: {' | '.join(risks[:2])}"

    # طلب المحامي
    lawyer_hint = ""
    if need_lawyer:
        lawyer_hint = "\nأضف توصية بالتواصل مع محامٍ متخصص في النهاية."

    urgency_hint = ""
    if urgency == "فوري":
        urgency_hint = "\nأوضح أن الأمر يستدعي تصرفاً فورياً."

    return f"""أنت مستشار قانوني قطري خبير. أجب بطريقة احترافية ومنظمة.

تعليمات التنسيق:
{chr(10).join('• ' + r for r in format_rules)}
{structure_hint}
{risks_hint}
{lawyer_hint}
{urgency_hint}

هيكل إجابتك (Markdown):

## 📋 التكييف القانوني
[ما طبيعة هذه المسألة؟ المجال: {category}]

## ⚖️ السند النظامي
[النصوص القانونية ذات الصلة — المادة، اسم القانون، السنة]

## 🔍 التحليل التفصيلي
[الحكم الدقيق | الاستثناءات | الظروف المشددة والمخففة]

## ✅ التوصية العملية
[ماذا يفعل المستخدم؟ الخطوات المُرتَّبة | التحذيرات الجوهرية]"""


# C. نقطة التحقق — بناء الـ prompt
CHECKPOINT_PROMPT = """أنت مدقق قانوني. تحقق من مطابقة الإجابة للمصادر.

السؤال: {question}

المصادر المسترجعة من قاعدة البيانات:
{sources_text}

الإجابة المولَّدة:
{answer_text}

مهمتك:
1. لكل ادعاء في الإجابة: هل هو مدعوم بالمصادر؟
2. هل هناك ادعاءات لا أساس لها في المصادر؟
3. هل الأحكام والعقوبات مذكورة بشكل صحيح؟

أخرج JSON فقط:
{
  "supported_claims": ["ادعاء موثّق 1", "ادعاء موثّق 2"],
  "unsupported_claims": ["ادعاء غير موثّق 1"],
  "accuracy_score": 0.95,
  "missing_context": ["معلومة مهمة ناقصة من الإجابة"],
  "verdict": "موثوق | يحتاج مراجعة | تحذير: معلومات غير مدعومة"
}"""


# ══════════════════════════════════════════════════════════════════
# هيكل نتيجة التحقق
# ══════════════════════════════════════════════════════════════════
@dataclass
class VerificationResult:
    """نتيجة التحقق من الإجابة"""
    accuracy_score: float       = 1.0    # درجة الدقة 0-1
    verdict: str                = "موثوق"
    supported_claims: list      = field(default_factory=list)
    unsupported_claims: list    = field(default_factory=list)
    missing_context: list       = field(default_factory=list)
    warnings_added: list        = field(default_factory=list)
    processing_time_ms: int     = 0

    def is_reliable(self) -> bool:
        """هل الإجابة موثوقة للعرض المباشر؟"""
        return self.accuracy_score >= 0.75 and len(self.unsupported_claims) == 0


# ══════════════════════════════════════════════════════════════════
# النظام الرئيسي
# ══════════════════════════════════════════════════════════════════
class IntelligenceLayer:
    """
    طبقة الذكاء — تدير دورة الحياة الكاملة للإجابة القانونية:

    السؤال → تفكير داخلي → توليد مُنسَّق → تحقق → إجابة نهائية

    الاستخدام:
        layer = IntelligenceLayer()

        # الطريقة الشاملة (Gemini/Claude):
        answer, verification = await layer.process(
            question=q,
            context=context_text,
            chunks=relevant_chunks,
            llm_caller=lambda sys, msgs: call_claude(sys, msgs, max_tokens=3000),
            fast_llm=lambda sys, msgs: call_claude(sys, msgs, MODEL_CLAUDE_FAST, 400),
        )

        # الطريقة المبسّطة (Ollama — بدون تفكير داخلي):
        answer = layer.format_answer_basic(raw_answer)
    """

    # ─────────────────────────────────────────────────────────────
    # أ. التفكير الداخلي
    # ─────────────────────────────────────────────────────────────
    async def think(
        self,
        question: str,
        fast_llm: callable
    ) -> dict:
        """
        الخطوة المخفية — النموذج يُحلّل السؤال قبل الإجابة.

        المدخل:
            question — سؤال المستخدم
            fast_llm — نموذج سريع (Claude Haiku أو Gemini Flash)

        المخرج:
            dict يحتوي التحليل الداخلي (لا يُعرض للمستخدم)
        """
        try:
            t0 = time.time()
            raw = await asyncio.wait_for(
                fast_llm(
                    INTERNAL_MONOLOGUE_PROMPT,
                    [{"role": "user", "content": f"السؤال: {question}"}]
                ),
                timeout=5.0   # حد أقصى 5 ثوان
            )
            elapsed_ms = int((time.time() - t0) * 1000)

            m = re.search(r'\{.*\}', raw, re.DOTALL)
            if m:
                result = json.loads(m.group())
                result["_processing_ms"] = elapsed_ms
                log.info(
                    "internal_monologue: category=%s severity=%s urgency=%s (%dms)",
                    result.get("legal_category", "?"),
                    result.get("severity", "?"),
                    result.get("urgency", "?"),
                    elapsed_ms
                )
                return result
        except asyncio.TimeoutError:
            log.debug("internal_monologue timeout — skipping")
        except Exception as e:
            log.debug("internal_monologue error: %s", e)

        # fallback بسيط
        return {
            "legal_category": "غير محدد",
            "severity": "متوسطة",
            "needs_lawyer": False,
            "urgency": "غير عاجل",
            "response_structure": ["التكييف القانوني", "السند النظامي", "التحليل", "التوصية"],
            "risks_to_mention": [],
            "_processing_ms": 0,
            "_fallback": True,
        }

    # ─────────────────────────────────────────────────────────────
    # ب. توليد الإجابة المُنسَّقة
    # ─────────────────────────────────────────────────────────────
    async def generate_formatted(
        self,
        question: str,
        context: str,
        monologue: dict,
        history: list,
        main_llm: callable,
        context_prefix: str = "",
    ) -> str:
        """
        يُولّد الإجابة المُنسَّقة بـ Markdown احترافي.

        المدخل:
            question       — سؤال المستخدم
            context        — النصوص القانونية المسترجعة
            monologue      — نتيجة التفكير الداخلي
            history        — تاريخ المحادثة (آخر N رسائل)
            main_llm       — نموذج LLM الرئيسي
            context_prefix — بادئة السياق من ContextManager

        المخرج:
            str — الإجابة المُنسَّقة بـ Markdown
        """
        # بناء system prompt المُخصَّص
        system = build_formatter_prompt(monologue)

        # بناء رسالة المستخدم
        user_msg = (
            f"{context_prefix}"
            f"[النصوص القانونية المسترجعة]\n\n{context}\n\n"
            f"{'═' * 50}\n\n"
            f"السؤال: {question}\n\n"
            f"[التحليل الداخلي المُعدّ]: المسألة {monologue.get('legal_category', '')} | "
            f"الخطورة: {monologue.get('severity', '')} | "
            f"الاستعجال: {monologue.get('urgency', '')}"
        )

        messages = history + [{"role": "user", "content": user_msg}]

        try:
            answer = await main_llm(system, messages)
            return answer
        except Exception as e:
            log.error("generate_formatted error: %s", e)
            return ""

    # ─────────────────────────────────────────────────────────────
    # ج. نقطة التحقق
    # ─────────────────────────────────────────────────────────────
    async def verify(
        self,
        question: str,
        answer: str,
        chunks: list[dict],
        fast_llm: Optional[callable] = None
    ) -> VerificationResult:
        """
        يتحقق من مطابقة الإجابة للمصادر.

        الطريقتان:
        1. التحقق المحلي (سريع — بدون LLM): يفحص الأرقام والأسماء
        2. التحقق بـ LLM (أعمق — مع Gemini/Claude)

        المدخل:
            question  — السؤال الأصلي
            answer    — الإجابة المولَّدة
            chunks    — المقاطع المسترجعة من DB
            fast_llm  — نموذج سريع (اختياري)

        المخرج:
            VerificationResult مع درجة دقة ورسائل تحذيرية
        """
        t0 = time.time()
        result = VerificationResult()

        # ── التحقق المحلي (يعمل دائماً) ──────────────────────────

        # استخرج المواد المذكورة في الإجابة
        cited_articles = re.findall(
            r'المادة\s*\(?\s*(\d+)\s*\)?', answer
        )
        cited_laws = re.findall(
            r'قانون\s+(?:رقم\s*)?\(?\s*(\d+)\s*\)?\s*لسنة\s*\(?\s*(\d+)', answer
        )

        # بناء مجموعات المراجع الصحيحة من المصادر
        valid_articles = {
            str(ch.get("article_number", "")).strip()
            for ch in chunks
        }
        valid_law_refs = {
            (str(ch.get("law_number", "")).strip(), str(ch.get("law_year", "")).strip())
            for ch in chunks
        }
        # نص المصادر للبحث
        all_content = " ".join(ch.get("content", "")[:500] for ch in chunks[:8])

        warnings = []

        # فحص كل مادة مذكورة
        for art_num in cited_articles:
            if art_num in valid_articles:
                result.supported_claims.append(f"م({art_num}) — موثّقة في المصادر ✓")
            elif f"المادة ({art_num})" in all_content or f"المادة {art_num}" in all_content:
                result.supported_claims.append(f"م({art_num}) — موجودة في محتوى المصادر ✓")
            else:
                result.unsupported_claims.append(f"م({art_num}) — لم تُعثَر في المصادر")
                warnings.append(f"المادة ({art_num})")

        # فحص القوانين المذكورة
        for law_num, law_year in cited_laws:
            if (law_num, law_year) in valid_law_refs:
                result.supported_claims.append(f"ق({law_num})/{law_year} — موثّق ✓")
            else:
                in_content = (
                    f"رقم ({law_num})" in all_content or f"رقم {law_num}" in all_content
                ) and (law_year in all_content)
                if in_content:
                    result.supported_claims.append(f"ق({law_num})/{law_year} — في المحتوى ✓")
                else:
                    result.unsupported_claims.append(f"ق({law_num})/{law_year} — لم يُتحقق")

        # ── حساب درجة الدقة ──────────────────────────────────────
        total_claims = len(result.supported_claims) + len(result.unsupported_claims)
        if total_claims > 0:
            result.accuracy_score = len(result.supported_claims) / total_claims
        else:
            # لا توجد استشهادات قابلة للتحقق → درجة محايدة
            result.accuracy_score = 0.80

        # ── التحقق المتقدم بـ LLM (اختياري) ──────────────────────
        if fast_llm and total_claims > 0 and result.accuracy_score < 1.0:
            try:
                sources_text = "\n".join(
                    f"[{i+1}] {ch.get('law_name','')[:40]} م{ch.get('article_number','')} "
                    f"({ch.get('law_year','')}): {ch.get('content','')[:200]}"
                    for i, ch in enumerate(chunks[:5])
                )
                prompt = CHECKPOINT_PROMPT.format(
                    question=question[:200],
                    sources_text=sources_text[:2000],
                    answer_text=answer[:1500]
                )
                raw = await asyncio.wait_for(
                    fast_llm("أنت مدقق قانوني دقيق.", [{"role": "user", "content": prompt}]),
                    timeout=6.0
                )
                m = re.search(r'\{.*\}', raw, re.DOTALL)
                if m:
                    llm_check = json.loads(m.group())
                    # تحديث الدرجة بنتيجة LLM (مُرجَّحة)
                    llm_score = float(llm_check.get("accuracy_score", result.accuracy_score))
                    result.accuracy_score = (result.accuracy_score * 0.4 + llm_score * 0.6)
                    result.verdict = llm_check.get("verdict", result.verdict)
                    result.missing_context = llm_check.get("missing_context", [])[:3]
                    log.info("checkpoint LLM: score=%.2f verdict=%s", result.accuracy_score, result.verdict)
            except Exception as e:
                log.debug("checkpoint LLM error (non-critical): %s", e)

        # ── تحديد الحكم النهائي ───────────────────────────────────
        if result.accuracy_score >= 0.90:
            result.verdict = "موثوق ✓"
        elif result.accuracy_score >= 0.75:
            result.verdict = "مقبول — راجع المصادر"
        elif result.accuracy_score >= 0.50:
            result.verdict = "⚠️ يحتاج مراجعة"
        else:
            result.verdict = "🚨 تحذير: معلومات قد لا تكون مدعومة"

        result.processing_time_ms = int((time.time() - t0) * 1000)
        result.warnings_added = warnings

        log.info(
            "verification: score=%.0f%% verdict=%s claims=%d/%d (%dms)",
            result.accuracy_score * 100, result.verdict,
            len(result.supported_claims), total_claims,
            result.processing_time_ms
        )
        return result

    # ─────────────────────────────────────────────────────────────
    # د. إضافة تحذيرات للإجابة
    # ─────────────────────────────────────────────────────────────
    def apply_verification_to_answer(
        self, answer: str, verification: VerificationResult
    ) -> str:
        """
        يُضيف تحذيرات التحقق للإجابة إذا لزم.
        لا يُعدّل الإجابة إذا كانت موثوقة تماماً.
        """
        if verification.is_reliable():
            return answer   # لا تعديل — الإجابة موثوقة

        notes = []

        if verification.unsupported_claims:
            notes.append(
                "⚠️ **ملاحظة التحقق التلقائي:** "
                "بعض المراجع قد تحتاج تأكيداً من "
                "[بوابة الميزان القانوني](https://almeezan.qa)"
            )

        if verification.missing_context:
            ctx = " | ".join(verification.missing_context[:2])
            notes.append(f"📌 **معلومة إضافية مقترحة:** {ctx}")

        if notes and "\n\n---\n" not in answer:
            answer += "\n\n---\n" + "\n\n".join(notes)

        return answer

    # ─────────────────────────────────────────────────────────────
    # ه. الطريقة الشاملة — Pipeline الكامل
    # ─────────────────────────────────────────────────────────────
    async def process(
        self,
        question: str,
        context: str,
        chunks: list[dict],
        main_llm: callable,
        fast_llm: Optional[callable] = None,
        history: list = None,
        context_prefix: str = "",
        skip_monologue: bool = False,
    ) -> tuple[str, VerificationResult]:
        """
        Pipeline الكامل: تفكير → توليد → تحقق → إجابة نهائية.

        المدخل:
            question       — سؤال المستخدم
            context        — النصوص القانونية (من build_context)
            chunks         — قائمة المقاطع الخام (للتحقق)
            main_llm       — النموذج الرئيسي (Claude/Gemini)
            fast_llm       — نموذج سريع (Claude Haiku / بدونه يُستخدم main)
            history        — تاريخ المحادثة
            context_prefix — بادئة السياق (من ContextManager)
            skip_monologue — تخطّ التفكير الداخلي (مع Ollama مثلاً)

        المخرج:
            (answer_str, VerificationResult)
        """
        if history is None:
            history = []

        _fast = fast_llm or main_llm  # استخدم الرئيسي إذا لم يُعطَ سريع

        # الخطوة 1: التفكير الداخلي (مخفي)
        monologue = {}
        if not skip_monologue:
            monologue = await self.think(question, _fast)

        # الخطوة 2: توليد الإجابة المُنسَّقة
        answer = await self.generate_formatted(
            question=question,
            context=context,
            monologue=monologue,
            history=history,
            main_llm=main_llm,
            context_prefix=context_prefix,
        )

        if not answer:
            return "", VerificationResult(accuracy_score=0, verdict="فشل التوليد")

        # الخطوة 3: التحقق (نقطة الـ Checkpoint)
        verification = await self.verify(question, answer, chunks, _fast)

        # الخطوة 4: تطبيق التحذيرات إذا لزم
        answer = self.apply_verification_to_answer(answer, verification)

        return answer, verification

    # ─────────────────────────────────────────────────────────────
    # و. تنسيق الإجابة البسيط (بدون LLM — للتحسين اللحظي)
    # ─────────────────────────────────────────────────────────────
    @staticmethod
    def format_answer_basic(raw_answer: str, sources: list = None) -> str:
        """
        يُحسّن تنسيق الإجابة الخام بدون LLM إضافي.
        مفيد لتحسين مخرجات Ollama.

        ما يفعله:
        ✅ يُضيف رؤوس إذا لم تكن موجودة
        ✅ يُنسّق أرقام المواد بعريض
        ✅ يُضيف مسافات منطقية
        ✅ يُزيل التكرار الواضح
        """
        if not raw_answer:
            return raw_answer

        text = raw_answer.strip()

        # تنسيق ذكر المادة → **المادة (X)**
        text = re.sub(
            r'(المادة)\s*\(?\s*(\d+)\s*\)?',
            r'**المادة (\2)**',
            text
        )

        # تنسيق ذكر القانون → **قانون رقم (X) لسنة (Y)**
        text = re.sub(
            r'(قانون\s+رقم)\s*\(?\s*(\d+)\s*\)?\s*(لسنة)\s*\(?\s*(\d+)\s*\)?',
            r'**\1 (\2) \3 \4**',
            text
        )

        # إزالة الأسطر الفارغة المتكررة (أكثر من 2)
        text = re.sub(r'\n{3,}', '\n\n', text)

        # إضافة هيكل بسيط إذا كانت الإجابة بدون ترقيم
        if sources and '**' not in text[:100] and len(text) > 200:
            header = "**الإجابة القانونية:**\n\n"
            if not text.startswith('**') and not text.startswith('#'):
                text = header + text
            # إضافة تذييل المصادر
            if sources:
                src_list = "\n".join(
                    f"- {s.get('title','')[:50]} (م{s.get('article','')}, {s.get('law_year','')})"
                    for s in sources[:3]
                )
                text += f"\n\n**المصادر القانونية:**\n{src_list}"

        return text


# ══════════════════════════════════════════════════════════════════
# مثيل مُشترك
# ══════════════════════════════════════════════════════════════════
intelligence = IntelligenceLayer()


# ══════════════════════════════════════════════════════════════════
# طريقة الدمج في main.py
# ══════════════════════════════════════════════════════════════════
"""
═══════════════════════════════════════════════════════════════
طريقة الدمج مع main.py الحالي
═══════════════════════════════════════════════════════════════

1. في أعلى main.py:
   from intelligence_layer import intelligence, IntelligenceLayer

2. في query_json() (الإجابة الكاملة):

   # بدل:
   answer = await _generate_answer(req.model, system, messages, max_tokens=max_ans)

   # استخدم:
   async def _main_llm(sys, msgs):
       return await _generate_answer(req.model, sys, msgs, max_tokens=max_ans)

   async def _fast_llm(sys, msgs):
       if ANTHROPIC_KEY:
           return await call_claude(sys, msgs, MODEL_CLAUDE_FAST, 400)
       elif GEMINI_KEY:
           parts = []
           async for t in stream_gemini(sys, msgs, 400): parts.append(t)
           return "".join(parts)
       return ""

   answer, verification = await intelligence.process(
       question=q,
       context=context,
       chunks=relevant[:top_n],
       main_llm=_main_llm,
       fast_llm=_fast_llm if not is_ollama else None,
       history=history,
       context_prefix=ctx_prefix,
       skip_monologue=is_ollama,   # تخطَّ التفكير مع Ollama
   )
   # في الـ response:
   return {
       ...,
       "verification_score": round(verification.accuracy_score * 100),
       "verification_verdict": verification.verdict,
   }

3. مع Ollama (تنسيق بسيط بدون LLM):
   answer = intelligence.format_answer_basic(raw_answer, sources)

═══════════════════════════════════════════════════════════════
الفائدة:
   • كل إجابة مبنية على تحليل مسبق مخفي → دقة أعلى
   • تنسيق Markdown احترافي تلقائياً
   • درجة موثوقية لكل إجابة (0-100%)
   • تحذيرات تلقائية للادعاءات غير المدعومة
═══════════════════════════════════════════════════════════════
"""
