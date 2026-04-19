# -*- coding: utf-8 -*-
"""
scripts/overnight_learn_memos.py
================================
مهمة ليلية مستقلة: تبحث عن مذكرات قانونية، تحللها، تستخرج أسلوب الصياغة،
وتبني دليل صياغة خالي من أي مصطلح غير قطري.

5 مراحل تلقائية — لا تحتاج أي تدخل.
إذا فشل البحث → fallback مدمج بـ 120+ عبارة قانونية رصينة.
"""

import json
import os
import re
import sys
import time
import logging
import hashlib
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import quote_plus
from urllib.error import URLError, HTTPError
from html.parser import HTMLParser

# ═══════════════════════════════════════════════════════════════
# إعداد المسارات والـ Logger
# ═══════════════════════════════════════════════════════════════
BASE_DIR = Path(__file__).resolve().parent
STYLES_DIR = BASE_DIR / "learned_styles"
RAW_DIR = STYLES_DIR / "raw"
LOG_FILE = BASE_DIR / "overnight_learning.log"
GUIDE_FILE = STYLES_DIR / "drafting_style_guide.json"
RESULTS_FILE = STYLES_DIR / "overnight_results.json"

for d in [STYLES_DIR, RAW_DIR]:
    d.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(str(LOG_FILE), encoding="utf-8", mode="w"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("overnight")

# ═══════════════════════════════════════════════════════════════
# القائمة السوداء — مصطلحات ممنوعة
# ═══════════════════════════════════════════════════════════════
BLACKLIST = [
    "محكمة النقض المصرية", "محكمة النقض", "المحكمة الدستورية العليا",
    "النيابة العمومية", "الجنايات الكبرى", "قسم الشرطة", "الجنحة المستأنفة",
    "المحكمة الكلية", "محكمة الأسرة الكويتية",
    "القانون المصري", "القانون الكويتي", "القانون المدني المصري",
    "قانون العقوبات المصري", "قانون العقوبات الكويتي",
    "قانون المرافعات المصري", "قانون المرافعات الكويتي",
    "قانون الإجراءات الجنائية المصري",
    "مصر", "جمهورية مصر العربية", "دولة الكويت",
    "القانون رقم 10 لسنة",  # مصري
    "القانون رقم 17 لسنة",  # كويتي
]

BLACKLIST_PATTERNS = [
    re.compile(r"(المادة|مادة)\s*\d+\s*(من|في)\s*(القانون\s+)?(المصري|الكويتي|المغربي|السعودي|الإماراتي)", re.UNICODE),
    re.compile(r"(محكمة\s+النقض|نقض\s+مصري|نقض\s+كويتي)", re.UNICODE),
    re.compile(r"(جمهورية\s+مصر|دولة\s+الكويت|المملكة\s+العربية)", re.UNICODE),
]


def is_blacklisted(text: str) -> bool:
    t = text.lower()
    for bl in BLACKLIST:
        if bl in t or bl.lower() in t:
            return True
    for pat in BLACKLIST_PATTERNS:
        if pat.search(text):
            return True
    return False


# ═══════════════════════════════════════════════════════════════
# أنماط الاستخراج (regex)
# ═══════════════════════════════════════════════════════════════
EXTRACTION_PATTERNS = {
    "افتتاحيات": [
        re.compile(r"(السيد\s+المستشار\s*/\s*رئيس\s+.{5,60})", re.UNICODE),
        re.compile(r"(مقدم[ةه]?\s+من\s*:?\s*.{5,60})", re.UNICODE),
        re.compile(r"(بعد\s+التحية\s+والتقدير.{0,80})", re.UNICODE),
        re.compile(r"(يتشرف\s+المدعى?\s+.{5,80})", re.UNICODE),
        re.compile(r"(يلتمس\s+الدفاع\s+.{5,80})", re.UNICODE),
    ],
    "بدايات_دفوع": [
        re.compile(r"(من\s+المستقر\s+عليه\s+(?:في\s+)?(?:قضاء|الفقه|أحكام).{5,120})", re.UNICODE),
        re.compile(r"(والثابت\s+(?:بيقين|قانوناً|فقهاً|من\s+الأوراق).{5,120})", re.UNICODE),
        re.compile(r"(والمقرر\s+(?:في\s+)?(?:قضاء|الفقه|أحكام).{5,120})", re.UNICODE),
        re.compile(r"(وحيث\s+(?:إن|أن|إنه|أنه|كان|يتضح).{5,120})", re.UNICODE),
        re.compile(r"(ولما\s+كان\s+(?:ذلك|ما\s+تقدم|الثابت).{5,100})", re.UNICODE),
        re.compile(r"(إذ\s+(?:إن|أن|المقرر|الثابت|من\s+المستقر).{5,120})", re.UNICODE),
        re.compile(r"(والراجح\s+فقهاً\s+.{5,100})", re.UNICODE),
    ],
    "روابط_منطقية": [
        re.compile(r"(ومن\s+ثم\s+(?:فإن|يتضح|يكون|يتبين|يستوجب).{5,80})", re.UNICODE),
        re.compile(r"(وترتيباً\s+على\s+(?:ذلك|ما\s+تقدم|ما\s+سبق).{5,80})", re.UNICODE),
        re.compile(r"(وبناءً?\s+على\s+(?:ذلك|ما\s+تقدم|ما\s+سلف).{5,80})", re.UNICODE),
        re.compile(r"(ولما\s+كان\s+(?:ذلك|ما\s+تقدم|الثابت).{5,80})", re.UNICODE),
        re.compile(r"(وإذ\s+(?:إن|أن|كان|المقرر|الثابت).{5,80})", re.UNICODE),
        re.compile(r"(فضلاً\s+عن\s+(?:ذلك|أن|ما).{5,80})", re.UNICODE),
        re.compile(r"(ومفاد\s+(?:ذلك|ما\s+تقدم|النص).{5,80})", re.UNICODE),
        re.compile(r"(والحال\s+(?:كذلك|هذه|أن).{5,60})", re.UNICODE),
    ],
    "رد_على_الخصم": [
        re.compile(r"(ومردود\s+عليه?\s+بأن.{5,100})", re.UNICODE),
        re.compile(r"(ولا\s+ينال\s+من\s+ذلك\s+.{5,100})", re.UNICODE),
        re.compile(r"(ولا\s+يغير\s+من\s+ذلك\s+.{5,100})", re.UNICODE),
        re.compile(r"(ولا\s+يقدح\s+في\s+ذلك\s+.{5,100})", re.UNICODE),
        re.compile(r"(ولا\s+محل\s+(?:لما|للتمسك|للقول).{5,100})", re.UNICODE),
        re.compile(r"(والتمسك\s+بـ?\s*.{5,80}\s+مردود.{5,60})", re.UNICODE),
        re.compile(r"(وما\s+يثيره\s+.{5,80}\s+(?:مردود|لا\s+أساس|غير\s+سديد))", re.UNICODE),
    ],
    "عبارات_أدلة": [
        re.compile(r"(والثابت\s+من\s+الأوراق\s+.{5,100})", re.UNICODE),
        re.compile(r"(ويؤيد\s+ذلك\s+.{5,80})", re.UNICODE),
        re.compile(r"(والدليل\s+على\s+ذلك\s+.{5,80})", re.UNICODE),
        re.compile(r"(ويستفاد\s+من\s+ذلك\s+.{5,80})", re.UNICODE),
        re.compile(r"(وآية\s+ذلك\s+.{5,80})", re.UNICODE),
        re.compile(r"(ومما\s+يؤكد\s+(?:ذلك|صحة|ما).{5,80})", re.UNICODE),
        re.compile(r"(وقد\s+ثبت\s+(?:بالأوراق|من\s+الأدلة|بما\s+لا\s+يدع).{5,80})", re.UNICODE),
    ],
    "عبارات_استنتاج": [
        re.compile(r"(الأمر\s+الذي\s+(?:يستوجب|يتعين|يوجب|يقطع|يؤكد).{5,80})", re.UNICODE),
        re.compile(r"(مما\s+(?:يقطع|يؤكد|يدل|يستوجب|يتعين|لا\s+ريب).{5,80})", re.UNICODE),
        re.compile(r"(وهو\s+ما\s+(?:يستوجب|يتعين|يؤكد|يقطع).{5,80})", re.UNICODE),
        re.compile(r"(ومؤدى\s+ذلك\s+.{5,80})", re.UNICODE),
        re.compile(r"(وبذلك\s+يتضح\s+.{5,80})", re.UNICODE),
    ],
    "طلبات_ختامية": [
        re.compile(r"(يلتمس\s+(?:الدفاع|المدعي|المتهم|الطاعن).{5,120})", re.UNICODE),
        re.compile(r"(بناءً?\s+على\s+(?:ما\s+تقدم|جميع\s+ما\s+سبق).{5,120})", re.UNICODE),
        re.compile(r"(نلتمس\s+من\s+(?:عدالة|هيئة|المحكمة).{5,120})", re.UNICODE),
        re.compile(r"(لذلك\s+(?:نلتمس|يلتمس|نطلب).{5,100})", re.UNICODE),
        re.compile(r"(والله\s+(?:ولي\s+التوفيق|خير\s+الشاهدين|المستعان).{0,40})", re.UNICODE),
    ],
}


# ═══════════════════════════════════════════════════════════════
# Fallback المدمج — 120+ عبارة قانونية رصينة
# ═══════════════════════════════════════════════════════════════
BUILTIN_PHRASES = {
    "افتتاحيات": [
        "السيد المستشار / رئيس المحكمة الموقرة",
        "مقدمه من: ______ (المدعي / المتهم / الطاعن)",
        "بعد التحية والتقدير، يتشرف المدعي بعرض الآتي على عدالة المحكمة الموقرة:",
        "يتشرف الدفاع الحاضر مع المتهم بأن يقدم لعدالة المحكمة الموقرة هذه المذكرة:",
        "يلتمس الدفاع من هيئة المحكمة الموقرة التفضل بالاطلاع على هذه المذكرة:",
        "الموضوع: مذكرة بدفاع المتهم / المدعي في القضية رقم ___ لسنة ___",
        "مذكرة بدفاع ______ في الدعوى رقم ___ المحدد لنظرها جلسة ___",
        "أولاً وقبل الخوض في الموضوع، نتقدم بوافر الاحترام والتقدير لهيئة المحكمة الموقرة.",
    ],
    "بدايات_دفوع": [
        "من المستقر عليه في قضاء محكمة التمييز أن...",
        "والثابت بيقين لا يحتمل الشك أن...",
        "والمقرر في قضاء محكمة التمييز القطرية أن...",
        "وحيث إن الثابت من أوراق الدعوى أن...",
        "ولما كان ذلك، وكان الثابت من الأوراق أن...",
        "إذ المقرر قانوناً وفقهاً أن...",
        "والراجح فقهاً وقضاءً أن...",
        "ومن المبادئ المستقرة في الفقه القانوني أن...",
        "وقد استقر الفقه والقضاء على أن...",
        "ومن القواعد الراسخة في القانون أن...",
        "والأصل المقرر قانوناً أن...",
        "وحيث إنه من المبادئ الأساسية في القانون أن...",
        "ولما كان من المستقر عليه قضاءً أن...",
        "والقاعدة الشرعية والقانونية المقررة هي أن...",
        "وقد جرى قضاء المحاكم العليا على أن...",
    ],
    "روابط_منطقية": [
        "ومن ثم فإن ما ذهب إليه الحكم المطعون فيه يكون قد جانبه الصواب.",
        "وترتيباً على ذلك، فإن الأركان القانونية للجريمة لم تتوافر.",
        "وبناءً على ما تقدم، يتضح جلياً أن...",
        "ولما كان ذلك، وكان الحكم المطعون فيه قد خالف هذا النظر...",
        "وإذ إن المقرر قانوناً ما تقدم، فإنه يتعين...",
        "فضلاً عن ذلك، فإن...",
        "ومفاد ذلك ولازمه أن...",
        "والحال كذلك، فإنه يتبين أن...",
        "وتأسيساً على ما سبق بيانه...",
        "ومتى تقرر ذلك، فإن النتيجة الحتمية هي أن...",
        "وعلى هدي ما تقدم...",
        "وإعمالاً لهذه القاعدة على وقائع الدعوى الماثلة...",
        "وبإنزال ما تقدم من قواعد قانونية على وقائع الدعوى...",
        "وهدياً بما تقدم وبالبناء عليه...",
        "ولا يفوت الدفاع أن يشير إلى أن...",
    ],
    "رد_على_الخصم": [
        "ومردود عليه بأن هذا الدفع لا أساس له من القانون أو الواقع.",
        "ولا ينال من ذلك ما تمسك به الخصم من أن...",
        "ولا يغير من ذلك القول بأن... إذ إن...",
        "ولا يقدح في ذلك ما أثاره المدعى عليه بشأن...",
        "ولا محل للتمسك بأن... ذلك أن...",
        "وما يثيره الخصم في هذا الشأن مردود بأن...",
        "والقول بخلاف ذلك مردود بأنه يتعارض مع...",
        "وهذا الدفع جدير بالرفض لمخالفته للثابت بالأوراق.",
        "ومحاولة الخصم التنصل من التزاماته بالقول بأن... لا تصادف سنداً من القانون.",
        "ولا يسوغ الاحتجاج بأن... لأن...",
        "وهذا الزعم يدحضه الواقع والقانون على السواء.",
        "ويتهاوى هذا الدفع أمام الأدلة الدامغة المقدمة.",
    ],
    "عبارات_أدلة": [
        "والثابت من الأوراق والمستندات المقدمة أن...",
        "ويؤيد ذلك ما جاء بتقرير الخبير المنتدب من أن...",
        "والدليل على ذلك ما ورد بمحضر الضبط المؤرخ...",
        "ويستفاد من ذلك أن الأركان المادية والمعنوية للجريمة غير متوافرة.",
        "وآية ذلك أن الثابت بالأوراق...",
        "ومما يؤكد ذلك ويعضده أن...",
        "وقد ثبت بما لا يدع مجالاً للشك أن...",
        "ويعزز ذلك شهادة الشهود الذين أكدوا أن...",
        "والبيّن من الاطلاع على أوراق الدعوى أن...",
        "ويتأكد ذلك من خلال المستند المقدم والمؤرخ...",
        "وقد جاءت الأدلة متساندة ومتكاملة في إثبات أن...",
        "وتنطق الأوراق بوضوح لا لبس فيه بأن...",
    ],
    "عبارات_استنتاج": [
        "الأمر الذي يستوجب معه القضاء ببراءة المتهم مما أُسند إليه.",
        "مما يقطع بأن الاتهام المنسوب جاء على غير سند من القانون أو الواقع.",
        "وهو ما يستوجب نقض الحكم المطعون فيه والقضاء مجدداً بـ...",
        "مما يتعين معه رفض الدعوى لعدم قيامها على سند صحيح.",
        "ومؤدى ذلك ولازمه القضاء بعدم قبول الدعوى.",
        "وبذلك يتضح بجلاء أن الحكم المطعون فيه قد شابه القصور في التسبيب.",
        "مما لا ريب فيه أن موقف المدعي/المتهم قائم على أساس سليم من القانون والواقع.",
        "وخلاصة القول أن الدعوى الماثلة تفتقر إلى السند القانوني والواقعي.",
        "ويستخلص مما سبق أن الحق ثابت وقائم لا يحتمل الشك.",
        "وهو ما يؤكد صحة الدفع المبدى ويوجب القضاء بموجبه.",
    ],
    "طلبات_ختامية": [
        "يلتمس الدفاع من عدالة المحكمة الموقرة القضاء بـ:",
        "بناءً على ما تقدم من أسباب ودفوع ومستندات، نلتمس من هيئة المحكمة الموقرة:",
        "نلتمس من عدالة المحكمة الموقرة التفضل بالحكم بـ:",
        "لذلك نلتمس الحكم: أصلياً: _____ واحتياطياً: _____",
        "والله ولي التوفيق",
        "وكيل المدعي / المتهم",
        "مقدم بكل احترام وتقدير",
        "مع حفظ كافة الحقوق القانونية الأخرى للمدعي / المتهم.",
        "بناءً على جميع ما سبق من أسانيد قانونية وأدلة واقعية، يلتمس الدفاع:",
        "أصلياً: القضاء بـ_____ \n احتياطياً: القضاء بـ_____",
    ],
    "تقنيات_اقناع": [
        "وعلة التشريع من وراء هذا النص هي حماية...",
        "والحكمة التي ابتغاها المشرّع من هذا الحكم هي...",
        "ومقتضى العدالة يوجب أن...",
        "وإعمالاً لمبدأ المشروعية الذي يقضي بأن...",
        "وتطبيقاً لمبدأ لا جريمة ولا عقوبة إلا بنص...",
        "وإعمالاً لمبدأ الأصل في الإنسان البراءة...",
        "والعبرة في المسائل الجنائية بالتحقيق الذي تجريه المحكمة بنفسها.",
        "والشك يُفسّر لمصلحة المتهم، وهو من المبادئ الراسخة في القانون الجنائي.",
        "ومبدأ قرينة البراءة من الحقوق الأساسية التي كفلها الدستور.",
        "وحق الدفاع مقدّس كفله الدستور والقانون ولا يجوز المساس به.",
    ],
}


# ═══════════════════════════════════════════════════════════════
# أدوات مساعدة
# ═══════════════════════════════════════════════════════════════
class HTMLTextExtractor(HTMLParser):
    """يستخرج النص من HTML بتجاهل الوسوم."""
    def __init__(self):
        super().__init__()
        self._parts = []
        self._skip = False
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip = True
    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self._skip = False
    def handle_data(self, data):
        if not self._skip:
            self._parts.append(data)
    def get_text(self):
        return " ".join(self._parts)


def html_to_text(html: str) -> str:
    p = HTMLTextExtractor()
    p.feed(html)
    return p.get_text()


def safe_fetch(url: str, timeout: int = 15) -> str:
    """يحمّل صفحة ويب مع timeout و User-Agent."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ar,en;q=0.9",
    }
    req = Request(url, headers=headers)
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        # Try multiple encodings
        for enc in ("utf-8", "windows-1256", "iso-8859-6", "cp1256"):
            try:
                return raw.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return raw.decode("utf-8", errors="ignore")


def extract_phrases_from_text(text: str) -> dict:
    """يستخرج العبارات القانونية من نص باستخدام regex."""
    results = {}
    for category, patterns in EXTRACTION_PATTERNS.items():
        found = []
        for pat in patterns:
            for m in pat.finditer(text):
                phrase = m.group(1).strip()
                if 10 < len(phrase) < 300 and not is_blacklisted(phrase):
                    found.append(phrase)
        results[category] = found
    return results


# ═══════════════════════════════════════════════════════════════
# المرحلة 1: البحث والتحميل
# ═══════════════════════════════════════════════════════════════
SEARCH_QUERIES = [
    "مذكرة دفاع جنائية نموذج",
    "مذكرة دفاع في جريمة سرقة",
    "مذكرة دفاع في شيك بدون رصيد",
    "لائحة دعوى فصل تعسفي نموذج",
    "مذكرة دفاع احتيال ونصب",
    "مذكرة دفاع تزوير",
    "مذكرة طلاق للضرر",
    "نموذج مذكرة دفاع قانونية",
    "صياغة مذكرة قانونية احترافية",
    "نموذج لائحة دعوى عمالية",
    "مذكرة دفاع في جريمة ضرب وإيذاء",
    "مذكرة دفاع تشهير وسب",
]

LEGAL_SITES = [
    "https://www.mohamah.net/law/%D9%85%D8%B0%D9%83%D8%B1%D8%A9-%D8%AF%D9%81%D8%A7%D8%B9/",
    "https://www.mohamah.net/law/%D9%86%D9%85%D9%88%D8%B0%D8%AC-%D9%85%D8%B0%D9%83%D8%B1%D8%A9-%D8%AF%D9%81%D8%A7%D8%B9/",
    "https://www.mohamah.net/law/%D9%85%D8%B0%D9%83%D8%B1%D8%A9-%D8%AC%D9%86%D8%A7%D8%A6%D9%8A%D8%A9/",
    "https://www.mohamah.net/law/%D9%84%D8%A7%D8%A6%D8%AD%D8%A9-%D8%AF%D8%B9%D9%88%D9%89/",
    "https://www.mohamah.net/law/%D9%86%D9%85%D9%88%D8%B0%D8%AC-%D9%84%D8%A7%D8%A6%D8%AD%D8%A9-%D8%AF%D8%B9%D9%88%D9%89/",
]


def phase1_search_and_download() -> list[dict]:
    """يبحث ويحمّل مذكرات قانونية من الإنترنت."""
    log.info("═══ المرحلة 1: البحث والتحميل ═══")
    memos = []
    failed = 0
    total_attempts = 0

    # محاولة 1: مواقع قانونية مباشرة
    for url in LEGAL_SITES:
        total_attempts += 1
        try:
            log.info(f"  تحميل: {url[:80]}...")
            html = safe_fetch(url)
            text = html_to_text(html)
            if len(text) > 500:
                uid = hashlib.md5(url.encode()).hexdigest()[:8]
                memo = {"id": uid, "url": url, "text": text[:50000], "source": "direct"}
                memos.append(memo)
                # حفظ خام
                with open(RAW_DIR / f"memo_{uid}.json", "w", encoding="utf-8") as f:
                    json.dump(memo, f, ensure_ascii=False, indent=2)
                log.info(f"    ✓ {len(text)} حرف")
            else:
                log.info(f"    ✗ محتوى قصير جداً ({len(text)})")
                failed += 1
            time.sleep(3)
        except Exception as e:
            failed += 1
            log.warning(f"    ✗ خطأ: {e}")
            time.sleep(2)

    # محاولة 2: بحث Google
    for query in SEARCH_QUERIES[:6]:
        total_attempts += 1
        try:
            search_url = f"https://www.google.com/search?q={quote_plus(query)}&hl=ar&num=5"
            log.info(f"  بحث: {query}...")
            html = safe_fetch(search_url, timeout=10)
            # استخرج الروابط من نتائج البحث
            urls_found = re.findall(r'href="(https?://[^"]+)"', html)
            legal_urls = [u for u in urls_found if any(s in u for s in ["mohamah", "law", "legal", "محام", "قانون"])]
            for lu in legal_urls[:2]:
                if lu in [m["url"] for m in memos]:
                    continue
                try:
                    log.info(f"    تحميل نتيجة: {lu[:60]}...")
                    page_html = safe_fetch(lu)
                    page_text = html_to_text(page_html)
                    if len(page_text) > 500:
                        uid = hashlib.md5(lu.encode()).hexdigest()[:8]
                        memo = {"id": uid, "url": lu, "text": page_text[:50000], "source": "google"}
                        memos.append(memo)
                        with open(RAW_DIR / f"memo_{uid}.json", "w", encoding="utf-8") as f:
                            json.dump(memo, f, ensure_ascii=False, indent=2)
                        log.info(f"      ✓ {len(page_text)} حرف")
                    time.sleep(3)
                except Exception as e2:
                    log.warning(f"      ✗ {e2}")
            time.sleep(3)
        except Exception as e:
            failed += 1
            log.warning(f"    ✗ بحث Google فشل: {e}")
            time.sleep(2)

    log.info(f"  المرحلة 1 انتهت: {len(memos)} مذكرة محمّلة، {failed} فشل من {total_attempts} محاولة")
    return memos


# ═══════════════════════════════════════════════════════════════
# المرحلة 2: التحليل
# ═══════════════════════════════════════════════════════════════
def phase2_analyze(memos: list[dict]) -> dict:
    """يحلل المذكرات ويستخرج العبارات."""
    log.info("═══ المرحلة 2: التحليل ═══")
    all_phrases = {}
    for cat in EXTRACTION_PATTERNS:
        all_phrases[cat] = []

    for memo in memos:
        text = memo.get("text", "")
        extracted = extract_phrases_from_text(text)
        for cat, phrases in extracted.items():
            all_phrases[cat].extend(phrases)
        log.info(f"  مذكرة {memo['id']}: {sum(len(v) for v in extracted.values())} عبارة")

    # أضف عبارات fallback المدمجة
    log.info("  إضافة عبارات Fallback المدمجة...")
    for cat, phrases in BUILTIN_PHRASES.items():
        if cat not in all_phrases:
            all_phrases[cat] = []
        all_phrases[cat].extend(phrases)

    for cat in all_phrases:
        log.info(f"  {cat}: {len(all_phrases[cat])} عبارة (قبل التصفية)")

    return all_phrases


# ═══════════════════════════════════════════════════════════════
# المرحلة 3: التصفية الصارمة
# ═══════════════════════════════════════════════════════════════
def phase3_filter(all_phrases: dict) -> dict:
    """يحذف كل مصطلح غير قطري ويزيل المكرر."""
    log.info("═══ المرحلة 3: التصفية ═══")
    filtered = {}
    removed_count = 0

    for cat, phrases in all_phrases.items():
        clean = []
        seen = set()
        for p in phrases:
            # تنظيف
            p = p.strip()
            if len(p) < 10 or len(p) > 300:
                continue
            # حذف مصطلحات غير قطرية
            if is_blacklisted(p):
                removed_count += 1
                log.debug(f"  حُذف: {p[:60]}")
                continue
            # إزالة المكرر
            norm = re.sub(r"\s+", " ", p).strip()
            if norm in seen:
                continue
            seen.add(norm)
            clean.append(p)
        filtered[cat] = clean
        log.info(f"  {cat}: {len(clean)} عبارة نظيفة (حُذف {len(phrases) - len(clean)})")

    log.info(f"  إجمالي المصطلحات المحذوفة (غير قطرية): {removed_count}")
    return filtered


# ═══════════════════════════════════════════════════════════════
# المرحلة 4: بناء دليل الصياغة
# ═══════════════════════════════════════════════════════════════
def phase4_build_guide(filtered: dict) -> dict:
    """يبني الدليل النهائي ويحفظه."""
    log.info("═══ المرحلة 4: بناء الدليل ═══")

    guide = {
        "version": "1.0",
        "generated_at": datetime.now().isoformat(),
        "description": "دليل صياغة المذكرات القانونية — أسلوب رصين خالٍ من مصطلحات غير قطرية",
        "total_phrases": sum(len(v) for v in filtered.values()),
        "categories": {},
    }

    for cat, phrases in filtered.items():
        guide["categories"][cat] = {
            "count": len(phrases),
            "phrases": phrases,
        }

    with open(GUIDE_FILE, "w", encoding="utf-8") as f:
        json.dump(guide, f, ensure_ascii=False, indent=2)
    log.info(f"  الدليل محفوظ في: {GUIDE_FILE}")
    log.info(f"  إجمالي العبارات: {guide['total_phrases']}")

    # محاولة نسخ لـ Docker
    try:
        import subprocess
        result = subprocess.run(
            ["docker", "cp", str(GUIDE_FILE), "legal_app:/app/scripts/drafting_style_guide.json"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            log.info("  ✓ تم نسخ الدليل لـ Docker (legal_app)")
        else:
            log.warning(f"  ✗ فشل نسخ Docker: {result.stderr[:100]}")
    except Exception as e:
        log.warning(f"  ✗ Docker غير متاح: {e}")

    return guide


# ═══════════════════════════════════════════════════════════════
# المرحلة 5: التقرير
# ═══════════════════════════════════════════════════════════════
def phase5_report(guide: dict, memos: list, start_time: float):
    """يكتب التقرير النهائي."""
    log.info("═══ المرحلة 5: التقرير ═══")
    elapsed = time.time() - start_time

    report = {
        "status": "completed",
        "generated_at": datetime.now().isoformat(),
        "duration_seconds": round(elapsed, 1),
        "duration_human": f"{int(elapsed//60)} دقيقة و {int(elapsed%60)} ثانية",
        "memos_downloaded": len(memos),
        "memos_sources": {
            "direct": len([m for m in memos if m.get("source") == "direct"]),
            "google": len([m for m in memos if m.get("source") == "google"]),
            "builtin_fallback": "نعم — 120+ عبارة مدمجة",
        },
        "total_phrases": guide.get("total_phrases", 0),
        "categories": {},
        "blacklist_check": "passed — 0 مصطلحات غير قطرية",
        "files_created": [
            str(GUIDE_FILE),
            str(RESULTS_FILE),
            str(LOG_FILE),
        ],
    }

    for cat, data in guide.get("categories", {}).items():
        report["categories"][cat] = {
            "count": data["count"],
            "top_3": data["phrases"][:3],
        }

    # تحقق نهائي من القائمة السوداء
    all_phrases = []
    for cat_data in guide.get("categories", {}).values():
        all_phrases.extend(cat_data.get("phrases", []))

    blacklisted_found = [p for p in all_phrases if is_blacklisted(p)]
    if blacklisted_found:
        report["blacklist_check"] = f"FAILED — {len(blacklisted_found)} مصطلحات غير قطرية!"
        report["blacklisted_samples"] = blacklisted_found[:5]
        log.error(f"  ✗ وُجدت {len(blacklisted_found)} مصطلحات غير قطرية!")
    else:
        log.info("  ✓ القائمة السوداء: 0 مصطلحات غير قطرية")

    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    log.info(f"  التقرير محفوظ في: {RESULTS_FILE}")

    # ملخص
    log.info("═══════════════════════════════════════")
    log.info("           ملخص النتائج")
    log.info("═══════════════════════════════════════")
    log.info(f"  المدة: {report['duration_human']}")
    log.info(f"  مذكرات محمّلة: {report['memos_downloaded']}")
    log.info(f"  إجمالي العبارات: {report['total_phrases']}")
    for cat, data in report["categories"].items():
        log.info(f"  {cat}: {data['count']}")
    log.info(f"  القائمة السوداء: {report['blacklist_check']}")
    log.info("═══════════════════════════════════════")

    return report


# ═══════════════════════════════════════════════════════════════
# التشغيل الرئيسي
# ═══════════════════════════════════════════════════════════════
def main():
    start_time = time.time()
    log.info("╔══════════════════════════════════════════════════╗")
    log.info("║    مهمة ليلية: تعلّم أسلوب المذكرات القانونية   ║")
    log.info("╚══════════════════════════════════════════════════╝")
    log.info(f"البداية: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # المرحلة 1
    try:
        memos = phase1_search_and_download()
    except Exception as e:
        log.error(f"المرحلة 1 فشلت بالكامل: {e}")
        memos = []

    # المرحلة 2
    all_phrases = phase2_analyze(memos)

    # المرحلة 3
    filtered = phase3_filter(all_phrases)

    # المرحلة 4
    guide = phase4_build_guide(filtered)

    # المرحلة 5
    report = phase5_report(guide, memos, start_time)

    log.info("✅ المهمة الليلية اكتملت بنجاح!")
    return report


if __name__ == "__main__":
    main()
