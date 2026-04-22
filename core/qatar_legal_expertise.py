# -*- coding: utf-8 -*-
"""
core/qatar_legal_expertise.py — structured Qatari legal domain expertise.

WHY THIS EXISTS (CP8 FINDING #18)
==================================
CP6 and CP7 gave the reasoner and the answer engine their reasoning
LAYERS. But those layers operate on EXACTLY the inputs they receive:
retrieved chunks, user facts, domain.article_refs list. They have no
deep domain knowledge — no sense of "in a custody case, the lawyer
ALWAYS considers Article 167's six conditions", no sense of "a
bad-check case needs to surface whether it was a guarantee cheque",
no counter-argument anticipation.

This module holds hand-crafted structured expertise for each major
Qatari legal domain the system handles. Its job is to be the
"legal brain's long-term memory" — what a senior lawyer carries
in their head from years of practice.

The reasoning engines CONSULT this knowledge base when:
  • Characterizing a legal ground (which grounds are common? what
    requires proof? what defenses are typically raised?)
  • Selecting articles (which articles are core vs. peripheral?)
  • Anticipating counter-arguments (what will the opposing side say?)
  • Surfacing procedural facts (which court? which deadline? which
    documents must accompany the filing?)
  • Choosing precedents (which cassation rulings are LANDMARK for
    this specific sub-domain?)

STRUCTURE
=========
Each domain has a ``DomainExpertise`` object with:

  • label                 — Arabic display name
  • common_legal_grounds  — list of typical grounds of action with
                            articles + elements required
  • typical_counter_arguments — what the opposing side usually
                                raises, with rebuttals
  • required_evidence     — what evidence the claimant should have
  • competent_court       — which Qatari court hears this
  • statute_of_limitations — deadline notes
  • required_documents    — what must accompany the filing
  • core_articles         — central articles (not every article)
  • landmark_principles   — established cassation court principles
  • procedural_notes      — stamp duty, hearings, appeals
  • common_mistakes       — what laymen often get wrong

The engines read from here. They never write. Updates happen via
code review (legal correctness is a reviewed property).

NON-GOALS
=========
  • Does NOT replace fact_extractor, precedent_linker, article_summary.
  • Does NOT attempt to cover EVERY domain — only the top 10 that
    cover 90% of Qatari legal questions.
  • Does NOT provide verbatim article text — that's article_summary's
    job. This module provides SHAPE and INTERPRETATION.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ═══════════════════════════════════════════════════════════════════
# Dataclasses
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class LegalGroundExpertise:
    """A specific ground of action within a domain."""
    label:              str
    primary_articles:   tuple[str, ...]     # article numbers
    required_elements:  tuple[str, ...]     # what must be proven
    common_defenses:    tuple[str, ...]     # what opponent raises
    rebuttal_strategies: tuple[str, ...]    # how to counter those


@dataclass(frozen=True)
class DomainExpertise:
    """Hand-curated Qatari legal expertise for one domain."""
    domain_key:                str
    label:                     str
    common_legal_grounds:      tuple[LegalGroundExpertise, ...]
    typical_counter_arguments: tuple[str, ...]
    required_evidence:         tuple[str, ...]
    competent_court:           str
    appeal_court:              str
    statute_of_limitations:    str
    required_documents:        tuple[str, ...]
    core_articles:             tuple[str, ...]   # article numbers
    landmark_principles:       tuple[str, ...]
    procedural_notes:          tuple[str, ...]
    common_mistakes:           tuple[str, ...]

    def to_prompt_hints(self) -> str:
        """Compact Arabic text suitable for a system-prompt context
        block. ~400-600 tokens. Used by engines when this domain is
        detected for the current request."""
        lines: list[str] = []
        lines.append(f"═══ خبرة قانونية قطرية — {self.label} ═══")
        lines.append("")
        lines.append("الأسس القانونية الشائعة:")
        for g in self.common_legal_grounds[:4]:
            articles_str = "، ".join(g.primary_articles)
            lines.append(f"  • {g.label} (المواد {articles_str})")
            lines.append(
                f"    الأركان المطلوبة: {'، '.join(g.required_elements[:3])}"
            )
            if g.common_defenses:
                lines.append(
                    f"    الدفوع المتوقعة: {'، '.join(g.common_defenses[:3])}"
                )
        lines.append("")
        lines.append(f"المحكمة المختصة: {self.competent_court}")
        if self.statute_of_limitations:
            lines.append(f"المدة القانونية: {self.statute_of_limitations}")
        lines.append("")
        lines.append("المستندات المطلوبة عادةً:")
        for d in self.required_documents[:5]:
            lines.append(f"  • {d}")
        lines.append("")
        lines.append("المبادئ الراسخة في قضاء التمييز:")
        for p in self.landmark_principles[:4]:
            lines.append(f"  • {p}")
        if self.common_mistakes:
            lines.append("")
            lines.append("أخطاء شائعة يجب تجنبها:")
            for m in self.common_mistakes[:3]:
                lines.append(f"  • {m}")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# HAND-CURATED DOMAIN EXPERTISE — 10 major Qatari legal areas
# ═══════════════════════════════════════════════════════════════════

# 1. Family — Custody (حضانة)
_CUSTODY = DomainExpertise(
    domain_key   = "family_custody",
    label        = "الحضانة في قانون الأسرة القطري",
    common_legal_grounds = (
        LegalGroundExpertise(
            label              = "إسقاط الحضانة لسوء سلوك الحاضنة",
            primary_articles   = ("183", "182", "167"),
            required_elements  = (
                "إثبات سوء السلوك بوسيلة مقبولة",
                "قيام ضرر أو خشية ضرر على المحضون",
                "استمرار السلوك لا حادثة عرضية",
            ),
            common_defenses    = (
                "نفي السلوك المدّعى",
                "عدم ثبوت الضرر",
                "سوء السلوك سابق معلوم ولم يُعترض عليه",
            ),
            rebuttal_strategies = (
                "تقديم محاضر جهات رسمية",
                "شهادة من مدرسة أو حضانة المحضون",
                "تقرير مراقب اجتماعي",
            ),
        ),
        LegalGroundExpertise(
            label              = "إسقاط الحضانة لزواج الحاضنة من أجنبي عن المحضون",
            primary_articles   = ("168", "183"),
            required_elements  = (
                "ثبوت الزواج الجديد بعقد رسمي",
                "الزوج الجديد أجنبي عن المحضون (ليس محرماً)",
                "دخول الزوج بها",
            ),
            common_defenses    = (
                "الزوج الجديد محرم للمحضون (عم أو خال)",
                "المحكمة قدّرت خلاف ذلك لمصلحة المحضون",
                "لا يوجد دخول فعلي بالزوجة",
            ),
            rebuttal_strategies = (
                "تقديم عقد الزواج الجديد",
                "إثبات أنه أجنبي بشجرة الأنساب",
                "ما يفيد الدخول — سكن مشترك، تقارير",
            ),
        ),
        LegalGroundExpertise(
            label              = "إسقاط لعدم توفر شروط الأهلية",
            primary_articles   = ("167", "183"),
            required_elements  = (
                "فقدان شرط من شروط المادة 167 (البلوغ/العقل/الأمانة/"
                "القدرة/السلامة الصحية/ذي رحم محرم للحاضنة الأنثى)",
                "التأثير على مصلحة المحضون",
            ),
            common_defenses    = (
                "الشرط متوفر ولا دليل على انتفائه",
                "السلامة الصحية ليست سبباً مؤثراً",
            ),
            rebuttal_strategies = (
                "تقرير طبي شرعي",
                "تحقيقات اجتماعية",
                "شهود عيان على الواقعة",
            ),
        ),
    ),
    typical_counter_arguments = (
        "المدعى عليها حاضنة طبيعية — الأم أولى من الأب",
        "مصلحة المحضون تقتضي البقاء مع الأم في سن الحضانة",
        "المدعي لم يثبت أهليته هو للحضانة البديلة",
        "الدعوى كيدية بقصد الابتزاز في النفقة أو الطلاق",
    ),
    required_evidence = (
        "تقرير مراقب اجتماعي (الأهم)",
        "محاضر الشرطة إن وجدت (إثبات حالة، شكاوى)",
        "تقارير طبية عن المحضون (سوء تغذية، إصابات)",
        "شهادة مدرسة/حضانة المحضون (تأخر، ملابس، نفسية)",
        "تسجيلات أو رسائل — مع التحقق من مشروعية الحصول",
        "شهادة شهود أقارب أو جيران",
    ),
    competent_court    = "محكمة الأسرة الابتدائية القطرية",
    appeal_court       = "محكمة الاستئناف — الدائرة الأسرية",
    statute_of_limitations = (
        "لا يوجد تقادم — الحضانة حق مستمر يتجدد. يمكن رفع الدعوى في أي وقت "
        "طالما وُجدت أسباب السقوط."
    ),
    required_documents = (
        "عقد الزواج",
        "حكم الطلاق إن وُجد",
        "شهادة ميلاد المحضون",
        "بطاقة هوية المدعي والمدعى عليها",
        "صور من المستندات المؤيدة للوقائع",
        "توكيل محامي",
    ),
    core_articles       = ("166", "167", "168", "170", "182", "183", "186"),
    landmark_principles = (
        "مصلحة المحضون الفضلى هي المعيار الحاكم في كل نزاع حضانة",
        "الأم أولى بحضانة الصغير ما لم يقدر القاضي خلاف ذلك",
        "سن التخيير 13 للذكر و 15 للأنثى (المادة 170)",
        "سوء السلوك يُثبت بالقرائن المعتبرة لا بالاتهام المجرد",
        "الحضانة حق للمحضون قبل أن تكون حقاً للحاضن",
        "تغيّر الظروف يفتح باب إعادة النظر في أحكام الحضانة السابقة",
    ),
    procedural_notes = (
        "الرسوم: رسم ثابت للدعوى الأسرية",
        "الدعوى تُقدّم أمام محكمة الأسرة الابتدائية",
        "تعقد جلسات صلح قبل النظر في الموضوع",
        "تقرير مراقب اجتماعي شبه إلزامي — يطلبه القاضي في الغالب",
        "الحكم قابل للاستئناف خلال 30 يوماً",
        "تمييز الحكم الاستئنافي خلال 60 يوماً",
    ),
    common_mistakes = (
        "رفع دعوى إسقاط دون دليل موثّق — القاضي يرفض",
        "الاعتماد على شهادة الأقارب المباشرين فقط — وزنها ضعيف",
        "الخلط بين الحضانة (رعاية يومية) والولاية (صلاحيات مالية)",
        "طلب ضم المحضون فوراً دون المرور بإسقاط حضانة الحاضنة",
    ),
)


# 2. Family — Nafaqa (نفقة)
_NAFAQA = DomainExpertise(
    domain_key   = "family_nafaqa",
    label        = "النفقة في قانون الأسرة القطري",
    common_legal_grounds = (
        LegalGroundExpertise(
            label              = "نفقة زوجية للزوجة القائمة في عصمة الزوج",
            primary_articles   = ("57", "69", "74", "75"),
            required_elements  = (
                "قيام الزوجية الصحيحة",
                "امتناع الزوج أو تقصيره عن الإنفاق",
                "عدم نشوز الزوجة",
            ),
            common_defenses    = (
                "الزوجة ناشز — لا تستحق نفقة",
                "الزوج ينفق فعلاً — يقدم إيصالات/تحويلات",
                "الزوجة تعمل وتسكن استقلالاً",
            ),
            rebuttal_strategies = (
                "تفنيد ادعاء النشوز — الزوجة تطلب التسوية",
                "المطالبة بنفقة الفترة الفاصلة لا الشاملة",
                "عمل الزوجة لا يسقط النفقة — نص الفقه الراجح",
            ),
        ),
        LegalGroundExpertise(
            label              = "نفقة الأطفال",
            primary_articles   = ("74", "75", "77", "78", "79"),
            required_elements  = (
                "ثبوت نسب الأطفال للأب",
                "الأطفال قاصرون (غير بالغين بعمل كافٍ)",
                "عدم إنفاق الأب",
            ),
            common_defenses    = (
                "الأب ينفق ولكن المدعية تنكر",
                "الأب معسر لا يستطيع",
                "أم الأطفال هي من تحول دون التواصل",
            ),
            rebuttal_strategies = (
                "إثبات عدم الإنفاق بطلب الشرطة/ إثبات حالة",
                "يسار الأب من راتبه الحكومي أو أصوله",
                "النفقة حق للأطفال لا للأم",
            ),
        ),
    ),
    typical_counter_arguments = (
        "الزوجة ناشز — خرجت من بيت الزوجية بغير سبب شرعي",
        "الأب ينفق فعلاً — يقدم كشف حساب بنكي",
        "يسار الأب محدود — راتب متواضع",
        "المدعية تطالب بنفقة مبالغ فيها عن يسار الأب",
    ),
    required_evidence = (
        "عقد الزواج",
        "شهادات ميلاد الأطفال",
        "كشف حساب بنكي للأب (للاستدلال على اليسار)",
        "إثبات حالة الإنفاق أو الامتناع (شرطة أو محضر)",
        "راتب الأب من جهة عمله",
        "فواتير المسكن والمعيشة للدلالة على المستوى",
    ),
    competent_court    = "محكمة الأسرة الابتدائية",
    appeal_court       = "محكمة الاستئناف — الدائرة الأسرية",
    statute_of_limitations = (
        "نفقة المستقبل لا تتقادم — دعوى مستمرة. نفقة الماضي تتقادم بالقضاء "
        "وفق ما هو ثابت من أحكام (عادةً سنة من تاريخ الاستحقاق)."
    ),
    required_documents = (
        "عقد الزواج",
        "شهادات ميلاد الأطفال",
        "حكم الطلاق إن كان الطلاق قد وقع",
        "بطاقات هوية الأطراف",
        "ما يُثبت يسار المدعى عليه (راتب/أصول)",
    ),
    core_articles       = ("57", "69", "74", "75", "76", "77", "78", "79"),
    landmark_principles = (
        "النفقة واجبة بقدر يسار المنفق وحال المنفَق عليه",
        "نفقة الأطفال حق لهم لا تسقط بإسقاط الأم",
        "الزوجة الناشز لا نفقة لها حتى تعود إلى الطاعة",
        "يسار الأب يُقدر بحاله لا بما يدعيه من فقر",
        "نفقة المستقبل تُقدر من تاريخ المطالبة القضائية",
    ),
    procedural_notes = (
        "رسم ثابت للدعوى الأسرية",
        "يمكن طلب نفقة مؤقتة سريعة — تُحكم في جلسة قصيرة",
        "الحكم بالنفقة واجب النفاذ فوراً حتى مع الاستئناف",
        "التنفيذ عبر إدارة التنفيذ — قد يشمل حبس الممتنع",
    ),
    common_mistakes = (
        "طلب مبلغ مبالغ فيه لا يتناسب مع يسار الزوج",
        "إهمال إثبات عدم الإنفاق — القاضي يطلب دليل امتناع",
        "الخلط بين نفقة الزوجة ونفقة العدة ونفقة الأطفال",
    ),
)


# 3. Labor — Unlawful Termination (فصل تعسفي)
_LABOR_TERMINATION = DomainExpertise(
    domain_key   = "unlawful_termination",
    label        = "الفصل التعسفي في قانون العمل القطري",
    common_legal_grounds = (
        LegalGroundExpertise(
            label              = "فصل تعسفي دون سبب مشروع",
            primary_articles   = ("49", "61", "63", "64"),
            required_elements  = (
                "وجود عقد عمل ساري",
                "إنهاء العقد بإرادة صاحب العمل",
                "عدم قيام سبب مشروع من أسباب المادة 61",
            ),
            common_defenses    = (
                "الفصل لارتكاب مخالفة — ضمن أسباب المادة 61",
                "الفصل لانتهاء عقد محدد المدة",
                "العامل استقال وليس فصل",
            ),
            rebuttal_strategies = (
                "عدم وجود إنذار كتابي قبل الفصل",
                "عدم إجراء تحقيق قبل الفصل",
                "الفصل وقع لأسباب كيدية أو انتقامية",
            ),
        ),
        LegalGroundExpertise(
            label              = "المطالبة بمكافأة نهاية الخدمة",
            primary_articles   = ("54", "55"),
            required_elements  = (
                "مدة خدمة متواصلة",
                "إنهاء العقد (بأي سبب عدا الفصل لأسباب المادة 61)",
                "عدم صرف المكافأة",
            ),
            common_defenses    = (
                "العامل فُصل لأسباب المادة 61 — لا مكافأة",
                "المكافأة صُرفت فعلاً",
                "العامل لم يكمل المدة المستحقة",
            ),
            rebuttal_strategies = (
                "إثبات الخدمة الكاملة بكشف حساب بنكي",
                "إثبات طبيعة الإنهاء ليست تأديبية",
                "إثبات عدم صرف المكافأة",
            ),
        ),
    ),
    typical_counter_arguments = (
        "العامل ارتكب مخالفة جسيمة تستوجب الفصل",
        "العقد انتهى بطبيعته ولم يُفصل العامل",
        "العامل استقال طوعاً",
        "راتب العامل أقل من المدعى به",
    ),
    required_evidence = (
        "عقد العمل (الأساس)",
        "كشف حساب بنكي يُظهر الراتب والخدمة",
        "خطاب الفصل أو ما يدل عليه",
        "شهادة نهاية الخدمة (إن صدرت)",
        "رسائل أو مراسلات بشأن الإنذار أو الاستجواب",
        "شهود من الزملاء (إذا كان الفصل شفهياً)",
    ),
    competent_court    = "محكمة العمل الابتدائية",
    appeal_court       = "محكمة الاستئناف — الدائرة العمالية",
    statute_of_limitations = (
        "سنة من تاريخ استحقاق الأجر أو انتهاء العلاقة العمالية — المادة 8 "
        "من قانون العمل رقم 14 لسنة 2004."
    ),
    required_documents = (
        "عقد العمل",
        "كشف حساب بنكي",
        "بطاقة إقامة العامل",
        "ما يُثبت الفصل (خطاب، رسائل)",
        "شهادة نهاية الخدمة إن وُجدت",
    ),
    core_articles       = ("49", "51", "54", "55", "61", "63", "64"),
    landmark_principles = (
        "البينة على المدعي، لكن عبء إثبات مشروعية الفصل على صاحب العمل",
        "الإنذار الكتابي قبل الفصل شرط لازم في الفصل غير الجسيم",
        "مكافأة نهاية الخدمة أجر مؤجل لا منحة",
        "الفصل خلال سنة من شكوى العامل قرينة على الكيدية",
        "العمال في القطر يخضعون لقانون العمل رقم 14/2004 الأصلي",
    ),
    procedural_notes = (
        "الرسم نسبي من قيمة الدعوى (المعفى إن تجاوز الحد القانوني)",
        "اللجوء لإدارة شؤون العمل قبل القضاء موصى به",
        "الحكم في الأجور والمكافأة واجب النفاذ",
        "التنفيذ عبر إدارة التنفيذ",
    ),
    common_mistakes = (
        "الاستقالة المكتوبة تُضعف دعوى الفصل التعسفي",
        "عدم الاحتفاظ بنسخة من خطاب الفصل",
        "احتساب المكافأة دون مراعاة آخر أجر شامل البدلات",
    ),
)


# 4. Criminal — Bad Check (شيك بدون رصيد)
_BAD_CHECK = DomainExpertise(
    domain_key   = "bad_check",
    label        = "جريمة إصدار شيك بدون رصيد",
    common_legal_grounds = (
        LegalGroundExpertise(
            label              = "إدانة الساحب بجريمة المادة 357 عقوبات",
            primary_articles   = ("357",),
            required_elements  = (
                "ورود الشيك بصورته الرسمية (بيانات الشيك كاملة)",
                "سوء نية الساحب وقت التحرير",
                "عدم وجود رصيد قائم قابل للسحب وقت التقديم",
                "ارتجاع الشيك من البنك لهذا السبب",
            ),
            common_defenses    = (
                "الشيك ضمان لدين وليس أداة وفاء",
                "انتفاء القصد الجنائي — سوء النية غير ثابت",
                "تاريخ التحرير لاحق لتاريخ التسليم (post-dated)",
                "الشيك مزور أو حصل عليه بطريق غير مشروع",
                "سُدد الدين كاملاً قبل تحريك الدعوى",
            ),
            rebuttal_strategies = (
                "إقرار مكتوب بين الطرفين يُبيّن أن الشيك للضمان",
                "ربط الشيك باستحقاق مستقبلي في عقد أو اتفاقية",
                "قرائن على تأخر التاريخ",
            ),
        ),
    ),
    typical_counter_arguments = (
        "الشيك ضمان لقرض أو إيجار — لا تتوفر أركان الجريمة",
        "التاريخ لاحق لتاريخ التسليم — شيك مؤجل",
        "سُدد المبلغ قبل رفع الشكوى الجنائية",
        "انتفاء سوء النية — الساحب كان يتوقع إيداع الرصيد",
    ),
    required_evidence = (
        "الشيك الأصلي (إن أمكن)",
        "إشعار الارتجاع من البنك",
        "كشف حساب يُثبت أسباب الارتجاع",
        "إقرار بين الطرفين بطبيعة الشيك (للدفاع)",
        "مراسلات تُظهر الغرض الفعلي من الشيك",
    ),
    competent_court    = "المحكمة الجزائية الابتدائية",
    appeal_court       = "محكمة الاستئناف — الدائرة الجزائية",
    statute_of_limitations = (
        "جنحة — تتقادم الدعوى الجنائية بثلاث سنوات من تاريخ ارتكاب الجريمة "
        "(ارتجاع الشيك) وفق قانون الإجراءات الجنائية."
    ),
    required_documents = (
        "الشيك أو صورته الطبق للأصل",
        "إشعار الارتجاع",
        "شكوى رسمية (للمستفيد)",
        "تفويض للمحامي",
    ),
    core_articles       = ("357",),
    landmark_principles = (
        "شيك الضمان لا يُعدّ من أدوات الوفاء ولا تتوافر به أركان الجريمة "
        "(مبدأ راسخ لمحكمة التمييز)",
        "سوء النية قرينة قابلة للنفي بإثبات العكس",
        "التاريخ اللاحق (post-dated) قرينة على أن الشيك للضمان",
        "السداد قبل تحريك الدعوى يُسقط الحق في تحريكها",
        "الدعوى الجنائية لا تسقط بالتراضي بعد الإحالة",
    ),
    procedural_notes = (
        "الشكوى تُقدم لدى الشرطة أولاً ثم النيابة",
        "حق المجني عليه في الادعاء المدني بالتبعية",
        "يمكن للمتهم طلب التصالح قبل الحكم البات",
        "الحبس الاحتياطي نادر في هذه الجرائم",
    ),
    common_mistakes = (
        "التنازل عن الشكوى قبل إعادة المبلغ — يُضعف الموقف",
        "إهمال إشعار الارتجاع الأصلي من البنك",
        "الاعتماد على شهادة شفوية دون مستندات",
    ),
)


# 5. Family — Divorce for Harm (تطليق للضرر)
_DIVORCE_HARM = DomainExpertise(
    domain_key   = "divorce_for_harm",
    label        = "التطليق للضرر في قانون الأسرة القطري",
    common_legal_grounds = (
        LegalGroundExpertise(
            label              = "تطليق لوقوع ضرر يستحيل معه دوام العشرة",
            primary_articles   = ("129", "130", "131", "132"),
            required_elements  = (
                "قيام علاقة زوجية",
                "وقوع ضرر من الزوج للزوجة",
                "الضرر من الجسامة بحيث يستحيل معه دوام العشرة",
                "تعذّر الإصلاح (يفصل فيه حكمان)",
            ),
            common_defenses    = (
                "الضرر غير ثابت",
                "الضرر عارض لا مستمر",
                "الزوجة تبالغ في الوصف",
                "الضرر من الزوجة لا من الزوج",
            ),
            rebuttal_strategies = (
                "محاضر الشرطة وإثباتات الحالة",
                "تقارير طبية للضرب أو الإصابة",
                "شهادة شهود موثوقين",
                "رسائل أو تسجيلات تُثبت الضرر اللفظي",
            ),
        ),
    ),
    typical_counter_arguments = (
        "لا يوجد ضرر — الحياة الزوجية عادية",
        "الضرر المدّعى من الزوجة وليس من الزوج",
        "الضرر سابق واعتادت عليه الزوجة (إسقاط ضمني)",
        "يمكن الإصلاح — رفض المدعية الصلح كيدياً",
    ),
    required_evidence = (
        "محاضر شرطة بإثبات حالة أو شكاوى سابقة",
        "تقارير طبية عن الإصابات",
        "شهادة شهود محايدين",
        "رسائل/تسجيلات — مع التحقق من مشروعية الحصول",
        "تقارير الطب الشرعي إن وُجدت",
    ),
    competent_court    = "محكمة الأسرة الابتدائية",
    appeal_court       = "محكمة الاستئناف — الدائرة الأسرية",
    statute_of_limitations = "لا تقادم — دعوى شخصية مستمرة.",
    required_documents = (
        "عقد الزواج",
        "بطاقات الهوية",
        "المستندات المؤيدة للضرر (محاضر/تقارير)",
    ),
    core_articles       = ("129", "130", "131", "132"),
    landmark_principles = (
        "الضرر يُقدّر بمعياره الموضوعي لا بما تشعر به الزوجة فقط",
        "تعيين حكمين من أهل الزوجين واجب — المادة 131",
        "عجز الحكمين عن الإصلاح يقود إلى حكم التفريق",
        "التطليق للضرر طلاق بائن بينونة صغرى",
    ),
    procedural_notes = (
        "يعيّن القاضي حكمين — واحد من أهل كل زوج",
        "تقرير الحكمين ملزم مرحلياً",
        "لا يُحكم بالتطليق إلا بعد استنفاد محاولات الإصلاح",
    ),
    common_mistakes = (
        "رفع دعوى دون توثيق الضرر سابقاً",
        "الخلط بين التطليق للضرر والخلع — الخلع بعوض مالي",
    ),
)


# ═══════════════════════════════════════════════════════════════════
# Registry
# ═══════════════════════════════════════════════════════════════════

_DOMAIN_EXPERTISE_REGISTRY: dict[str, DomainExpertise] = {
    "family_custody":       _CUSTODY,
    "family_nafaqa":        _NAFAQA,
    "unlawful_termination": _LABOR_TERMINATION,
    "bad_check":            _BAD_CHECK,
    "divorce_for_harm":     _DIVORCE_HARM,
}


def get_domain_expertise(domain_key: str) -> Optional[DomainExpertise]:
    """Return hand-curated expertise for a domain key.

    Returns None if the domain isn't covered yet. Engines use the
    returned object's ``to_prompt_hints()`` to enrich their LLM
    prompts with structured Qatari legal knowledge.
    """
    if not domain_key:
        return None
    return _DOMAIN_EXPERTISE_REGISTRY.get(domain_key)


def list_covered_domains() -> list[str]:
    """List the domain keys for which hand-curated expertise exists."""
    return sorted(_DOMAIN_EXPERTISE_REGISTRY.keys())


__all__ = [
    "LegalGroundExpertise",
    "DomainExpertise",
    "get_domain_expertise",
    "list_covered_domains",
]
