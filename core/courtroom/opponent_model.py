# -*- coding: utf-8 -*-
"""
Opponent Modeling — predicts what the OTHER side will argue.

Rule-based: domain → typical opposing positions, procedural defenses,
and weak-spot exploitation. Used by Tier 2/3 only.

NOT outcome prediction. Output is conditional ("الخصم سيغلب أن يدّعي…").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.legal_gates import LegalDomain
from core.knowledge.domain_binder import BindingResult


# Per-domain opponent move catalog (deterministic)
_OPPONENT_PLAYBOOK: dict[str, dict] = {
    "employment": {
        "likely_arguments": [
            "ترك العامل العمل بإرادته (استقالة ضمنية).",
            "تم تنبيه العامل إنذاراً مكتوباً قبل الفصل.",
            "العامل ارتكب مخالفة جسيمة تبرر الفصل دون إشعار.",
        ],
        "procedural_defenses": [
            "سقوط الدعوى بمضي المدة (ميعاد تقادم العمالية).",
            "اختصاص جهة عمل بديلة (لجنة فض المنازعات قبل المحكمة).",
        ],
        "weak_spots_to_attack": [
            "غياب إشعار خطّي رسمي من العامل.",
            "نقص توثيق ساعات العمل أو الراتب الفعلي.",
            "عدم وجود شهود على الفصل.",
        ],
    },
    "family": {
        "likely_arguments": [
            "الأم/الأب ليس أهلاً للحضانة (سلوك / استقرار).",
            "تنازل الطرف الآخر عن الحضانة / النفقة سابقاً.",
            "الزوجة ناشز وأسقطت حقها.",
        ],
        "procedural_defenses": [
            "سبق الفصل في النزاع (حجية الأمر المقضي).",
            "اختصاص محكمة أخرى (موطن الزوج).",
        ],
        "weak_spots_to_attack": [
            "عدم توثيق المهر أو النفقة الفعلية.",
            "غياب شهود من خارج العائلة.",
            "تأخر رفع الدعوى لفترة طويلة.",
        ],
    },
    "criminal": {
        "likely_arguments": [
            "انتفاء القصد الجنائي.",
            "الفعل لا يندرج تحت النص المتبع.",
            "الاعتراف منتزع تحت إكراه.",
        ],
        "procedural_defenses": [
            "بطلان إجراءات القبض/التفتيش.",
            "سقوط الدعوى بمضي المدة.",
            "عدم اختصاص المحكمة.",
        ],
        "weak_spots_to_attack": [
            "ضعف الأدلة المادية.",
            "تناقض شهادات الشهود.",
            "ثغرات في محضر الضبط.",
        ],
    },
    "civil": {
        "likely_arguments": [
            "العقد لاغٍ لتخلف ركن أساسي.",
            "تنفيذ الالتزام مستحيل لقوة قاهرة.",
            "إخلال الطرف الآخر سابق وأبرز.",
            # Construction-specific opposing arguments
            "العيوب طفيفة ولا تبرر رفض الاستلام.",
            "تسلَّم رب العمل المنشأ فعلاً واستعمله — قبول ضمني.",
            "تأخر رب العمل في الاحتجاج بالعيوب أكثر من المعقول.",
            "العمل مطابق للمواصفات والاستشاري وافق على المراحل السابقة.",
            "العيوب المدّعاة ناشئة عن سوء استعمال رب العمل لا عن تنفيذ المقاول.",
        ],
        "procedural_defenses": [
            "سقوط الحق بالتقادم.",
            "عدم قبول الدعوى لانتفاء المصلحة.",
            "اختصاص التحكيم إن نص العقد على شرط تحكيمي.",
        ],
        "weak_spots_to_attack": [
            "غياب توثيق العقد كتابة.",
            "نقص في إثبات قيمة الضرر.",
            "تأخر المطالبة.",
            # Construction-specific weak spots
            "عدم وجود محضر استلام بتحفظات مكتوبة.",
            "غياب تقرير استشاري مستقل قبل رفع الدعوى.",
            "عدم توجيه إنذار رسمي للمقاول قبل الرفض.",
            "استعمال المنشأ فعلياً بعد الادعاء بوجود عيوب.",
        ],
    },
    "commercial": {
        "likely_arguments": [
            "العقد التجاري انتهى بمدته الطبيعية.",
            "الإخلال من الجهة المدعية وليس المدعى عليها.",
            "الشراكة فُسخت باتفاق مسبق.",
        ],
        "procedural_defenses": [
            "اختصاص التحكيم التجاري.",
            "سقوط الدعوى بالتقادم التجاري.",
        ],
        "weak_spots_to_attack": [
            "غياب سجل تجاري واضح.",
            "اختلاط الذمة المالية.",
            "نقص توثيق محاضر الاجتماعات.",
        ],
    },
    "rental": {
        "likely_arguments": [
            "المستأجر ارتكب تعديات تستوجب الإخلاء.",
            "العقد منتهٍ تلقائياً ولم يُجدَّد.",
            "المؤجر له الحق في التجديد بقيمة سوقية.",
        ],
        "procedural_defenses": [
            "اختصاص لجنة فض المنازعات الإيجارية أولاً.",
            "بطلان الإنذار الموجه.",
        ],
        "weak_spots_to_attack": [
            "غياب عقد إيجار مسجل رسمياً.",
            "تأخر الإنذار أو عدم تبليغه قانونياً.",
        ],
    },
    "banking": {
        "likely_arguments": [
            "العميل وقّع موافقة على شروط البنك.",
            "التأخير في السداد يبرر الفوائد الإضافية.",
            "البنك مارس حقه في الضمانات.",
        ],
        "procedural_defenses": [
            "اختصاص الدائرة المصرفية المتخصصة.",
            "تقادم الدين.",
        ],
        "weak_spots_to_attack": [
            "غياب نسخة موقعة من عقد القرض.",
            "تجاوز سقف الفائدة المقرر قانوناً.",
        ],
    },
}


@dataclass
class OpponentModel:
    domain:                 str
    likely_arguments:       list[str] = field(default_factory=list)
    procedural_defenses:    list[str] = field(default_factory=list)
    weak_spots_to_attack:   list[str] = field(default_factory=list)
    posture_estimate:       str = "balanced"   # weak | balanced | strong

    def to_public(self) -> dict:
        return {
            "domain":               self.domain,
            "likely_arguments":     self.likely_arguments[:3],
            "procedural_defenses":  self.procedural_defenses[:2],
            "weak_spots_to_attack": self.weak_spots_to_attack[:3],
            "posture_estimate":     self.posture_estimate,
        }

    def render_arabic(self) -> str:
        parts = []
        if self.likely_arguments:
            parts.append("**ما يُتوقَّع أن يدفع به الخصم:**")
            for a in self.likely_arguments[:3]:
                parts.append(f"• {a}")
        if self.procedural_defenses:
            parts.append("\n**دفوع شكلية محتملة:**")
            for d in self.procedural_defenses[:2]:
                parts.append(f"• {d}")
        if self.weak_spots_to_attack:
            parts.append("\n**نقاط ضعف يستهدفها الخصم:**")
            for w in self.weak_spots_to_attack[:3]:
                parts.append(f"• {w}")
        return "\n".join(parts)


def build_opponent_model(domain_value: str,
                          binding: Optional[BindingResult] = None,
                          ) -> Optional[OpponentModel]:
    play = _OPPONENT_PLAYBOOK.get(domain_value)
    if not play:
        return None
    return OpponentModel(
        domain=domain_value,
        likely_arguments=list(play.get("likely_arguments", [])),
        procedural_defenses=list(play.get("procedural_defenses", [])),
        weak_spots_to_attack=list(play.get("weak_spots_to_attack", [])),
    )
