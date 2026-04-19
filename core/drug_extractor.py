# -*- coding: utf-8 -*-
"""
Drug Name Extractor — clean extraction from OCR schedule text.
4-stage pipeline: OCR clean → item detect → name extract → normalize.
"""
import re, logging
from typing import Optional

log = logging.getLogger("drug_extractor")

# ══════════════════════════════════════════════════════════════
# Stage 1: OCR Normalization (presentation-form Arabic → canonical)
# ══════════════════════════════════════════════════════════════

_OCR_MAP = str.maketrans({
    "ﺍ": "ا", "ﺎ": "ا", "ﺂ": "آ", "ﺄ": "أ", "ﺈ": "إ",
    "ﺐ": "ب", "ﺑ": "ب", "ﺒ": "ب", "ﺏ": "ب",
    "ﺕ": "ت", "ﺖ": "ت", "ﺗ": "ت", "ﺘ": "ت",
    "ﺙ": "ث", "ﺚ": "ث", "ﺛ": "ث", "ﺜ": "ث",
    "ﺝ": "ج", "ﺞ": "ج", "ﺟ": "ج", "ﺠ": "ج",
    "ﺡ": "ح", "ﺢ": "ح", "ﺣ": "ح", "ﺤ": "ح",
    "ﺥ": "خ", "ﺦ": "خ", "ﺧ": "خ", "ﺨ": "خ",
    "ﺩ": "د", "ﺪ": "د", "ﺫ": "ذ", "ﺬ": "ذ",
    "ﺭ": "ر", "ﺮ": "ر", "ﺯ": "ز", "ﺰ": "ز",
    "ﺱ": "س", "ﺲ": "س", "ﺳ": "س", "ﺴ": "س",
    "ﺵ": "ش", "ﺶ": "ش", "ﺷ": "ش", "ﺸ": "ش",
    "ﺹ": "ص", "ﺺ": "ص", "ﺻ": "ص", "ﺼ": "ص",
    "ﺽ": "ض", "ﺾ": "ض", "ﺿ": "ض", "ﻀ": "ض",
    "ﻁ": "ط", "ﻂ": "ط", "ﻃ": "ط", "ﻄ": "ط",
    "ﻅ": "ظ", "ﻆ": "ظ", "ﻇ": "ظ", "ﻈ": "ظ",
    "ﻉ": "ع", "ﻊ": "ع", "ﻋ": "ع", "ﻌ": "ع",
    "ﻍ": "غ", "ﻎ": "غ", "ﻏ": "غ", "ﻐ": "غ",
    "ﻑ": "ف", "ﻒ": "ف", "ﻓ": "ف", "ﻔ": "ف",
    "ﻕ": "ق", "ﻖ": "ق", "ﻗ": "ق", "ﻘ": "ق",
    "ﻙ": "ك", "ﻚ": "ك", "ﻛ": "ك", "ﻜ": "ك",
    "ﻝ": "ل", "ﻞ": "ل", "ﻟ": "ل", "ﻠ": "ل",
    "ﻡ": "م", "ﻢ": "م", "ﻣ": "م", "ﻤ": "م",
    "ﻥ": "ن", "ﻦ": "ن", "ﻧ": "ن", "ﻨ": "ن",
    "ﻩ": "ه", "ﻪ": "ه", "ﻫ": "ه", "ﻬ": "ه",
    "ﻭ": "و", "ﻮ": "و",
    "ﻱ": "ي", "ﻲ": "ي", "ﻳ": "ي", "ﻴ": "ي",
    "ﻯ": "ى", "ﻰ": "ى", "ﺓ": "ة", "ﺔ": "ة", "ﺀ": "ء",
})

# Known drug name mappings: English → Arabic
_DRUG_NAMES = {
    "ACETORPHINE": "اسيتورفين",
    "CANNABIS": "حشيش (قنب)",
    "COCA LEAF": "ورق الكوكا",
    "COCAINE": "كوكايين",
    "CODEINE": "كودايين",
    "DESOMORPHINE": "ديزومورفين",
    "DIHYDROMORPHINE": "ثنائي هيدرومورفين",
    "ECGONINE": "ايكجونين",
    "ETHYLMORPHINE": "ايثيل مورفين",
    "ETORPHINE": "ايتورفين",
    "HEROIN": "هيروين",
    "HYDROCODONE": "هيدروكودون",
    "HYDROMORPHONE": "هيدرومورفون",
    "METHADONE": "ميثادون",
    "MORPHINE": "مورفين",
    "OPIUM": "أفيون",
    "OXYCODONE": "اوكسيكودون",
    "OXYMORPHONE": "اوكسيمورفون",
    "PETHIDINE": "بيثيدين",
    "THEBAINE": "ثيبايين",
    "FENTANYL": "فنتانيل",
    "SUFENTANIL": "سوفنتانيل",
    "ALFENTANIL": "الفنتانيل",
    "REMIFENTANIL": "ريميفنتانيل",
    "TRAMADOL": "ترامادول",
    "KETAMINE": "كيتامين",
    "AMPHETAMINE": "أمفيتامين",
    "METHAMPHETAMINE": "ميثامفيتامين",
    "METHYLPHENIDATE": "ميثيلفينيدات",
    "PHENCYCLIDINE": "فينسيكليدين",
    "MESCALINE": "ميسكالين",
    "PSILOCYBIN": "سيلوسيبين",
    "LSD": "ال اس دي",
    "MDMA": "ام دي ام ايه",
    "GHB": "جي اتش بي",
    "BARBITAL": "باربيتال",
    "DIAZEPAM": "ديازيبام",
    "ALPRAZOLAM": "البرازولام",
    "CLONAZEPAM": "كلونازيبام",
    "LORAZEPAM": "لورازيبام",
    "MIDAZOLAM": "ميدازولام",
    "CAPTAGON": "كبتاجون",
}

# Lines to skip entirely
_SKIP_PATTERNS = [
    re.compile(r"^\s*$"),
    re.compile(r"^[\d\s\.\-,;:]+$"),  # Pure numbers/punctuation
    re.compile(r"preparations?\s+of", re.I),  # "preparations of..."
    re.compile(r"per\s+dosage", re.I),
    re.compile(r"not\s+more\s+than", re.I),
    re.compile(r"not\s+exceeding", re.I),
    re.compile(r"containing", re.I),
    re.compile(r"^\s*\d+\s*%"),  # Percentage lines
    re.compile(r"mg\s*per", re.I),
    re.compile(r"milligrams?", re.I),
    re.compile(r"الجدول\s*رقم"),  # Schedule headers
    re.compile(r"المواد المخدرة"),  # Section headers
    re.compile(r"المؤثرات العقلية"),
    re.compile(r"جداول ملحقة"),
    re.compile(r"وزير الصحة"),
    re.compile(r"قرار.*رقم"),
    re.compile(r"بتعديل"),
    re.compile(r"القانون رقم"),
    re.compile(r"الملحق"),
    re.compile(r"صدر.*بتاريخ"),
    re.compile(r"الموافق"),
    re.compile(r"مجلس الوزراء"),
]


def extract_drug_names(chunks: list[dict]) -> list[str]:
    """
    Extract clean drug names from raw DB chunks.
    Returns list of unique drug names (Arabic preferred, English fallback).
    """
    seen = set()
    names = []

    for chunk in chunks[:8]:
        content = chunk.get("content", "") if isinstance(chunk, dict) else str(chunk)
        content = content.translate(_OCR_MAP)  # Stage 1: OCR normalize

        # Stage 2: Extract numbered items
        # Pattern: "N-ENGLISH_NAME(formula...) N ـ اسم_عربي"
        items = re.findall(
            r"(\d+)\s*[\-ـ\.]\s*([A-Z][A-Za-z\s\-]+?)(?:\s*\([^)]*\))?\s+\d+\s*ـ\s*([\u0600-\u06FF][^\n]{2,40})",
            content
        )
        for num, eng, ara in items:
            # Stage 3: Clean the Arabic name
            ara_clean = _clean_arabic_name(ara)
            if ara_clean and ara_clean not in seen:
                seen.add(ara_clean)
                names.append(ara_clean)

        # Also extract standalone English names — STRICT: must be known or look like a real drug name
        eng_items = re.findall(r"(\d+)\s*[\-ـ\.]\s*([A-Z][A-Za-z\s\-]{3,30})", content)
        for num, eng in eng_items:
            eng_clean = eng.strip().split("(")[0].strip()
            # Skip fragments: too short, ends with hyphen, starts with common prefix
            if eng_clean.endswith("-") or len(eng_clean) < 4:
                continue
            if eng_clean.upper().startswith(("METHYL", "PHENYL", "ETHYL", "ALPHA", "BETA", "PARA", "MONO", "POLY")):
                if eng_clean.upper() not in _DRUG_NAMES:
                    continue
            # Skip English sentences/descriptions
            if any(w in eng_clean.lower() for w in ["the ", "this ", "and ", "not ", "its ", "of ", "unless", "which", "listed", "except"]):
                continue
            # Map to Arabic if known
            mapped = _DRUG_NAMES.get(eng_clean.upper())
            if mapped and mapped not in seen:
                seen.add(mapped)
                names.append(mapped)
            elif not mapped and eng_clean.upper() not in seen:
                # Only keep if it looks like a single drug name (one or two words, no common English)
                words = eng_clean.split()
                if len(words) <= 2 and all(len(w) >= 3 for w in words):
                    seen.add(eng_clean.upper())
                    names.append(eng_clean)

        # Extract standalone Arabic numbered items
        ara_items = re.findall(r"(\d+)\s*ـ\s*([\u0600-\u06FF][^\n]{2,50})", content)
        for num, ara in ara_items:
            ara_clean = _clean_arabic_name(ara)
            if ara_clean and ara_clean not in seen:
                seen.add(ara_clean)
                names.append(ara_clean)

    # Stage 4: Final validation — remove noise that slipped through
    validated = []
    for name in names:
        n = name.strip()
        upper = n.upper()

        # Skip fragments with X-/N- prefix (OCR noise)
        if n.startswith("X-") or n.startswith("N-"):
            continue
        # Skip very short English tokens (< 5 chars) — likely OCR fragments
        is_eng = not any("\u0600" <= c <= "\u06FF" for c in n)
        if is_eng and len(n) < 5:
            continue
        # Skip truncated OCR remnants (< 7 chars ending in consonant cluster)
        if is_eng and len(n) < 7 and not upper.endswith(("INE", "ONE", "OLE", "ATE", "IDE", "DOL", "NOL", "PAM")):
            continue
        # Skip names that contain digits mixed with text
        if re.search(r"\d.*[A-Z].*\d|[A-Z].*\d.*[A-Z]", n) and len(n) > 10:
            continue
        # Skip "INTERMEDIATE" type entries
        if "INTERMEDIAT" in upper:
            continue
        # Arabic name mixed with English/numbers = noise
        if re.search(r"[\u0600-\u06FF]", n) and re.search(r"\d+\-[A-Z]", n):
            continue
        # Skip known OCR fragments
        if upper in ("IPERIDIL", "TENOCY", "DNHP"):
            continue

        validated.append(n)

    # Sort: Arabic names first, then English
    arabic = [n for n in validated if any("\u0600" <= c <= "\u06FF" for c in n)]
    english = [n for n in validated if not any("\u0600" <= c <= "\u06FF" for c in n)]
    sorted_names = arabic + english

    log.info("[DRUG_EXTRACT] extracted %d → validated %d (ara=%d eng=%d) from %d chunks",
             len(names), len(sorted_names), len(arabic), len(english), len(chunks))
    return sorted_names


def _clean_arabic_name(name: str) -> Optional[str]:
    """Clean an Arabic drug name — keep ONLY the name part."""
    # Remove everything after common stop phrases
    for stop in ["بجميع", "الناتج", "المحضر", "المستخرج", "ومسمياته", "وأنواعه",
                  "مثل", "بما فيها", "بما في ذلك", "والمعروف", "ويشمل"]:
        idx = name.find(stop)
        if idx > 2:
            name = name[:idx]

    name = name.strip().rstrip("،,.؛;: ")

    # Skip if too long (description, not a name)
    if len(name) > 30:
        return None
    # Skip if too short
    if len(name) < 3:
        return None
    # Skip if it's a skip pattern
    for pat in _SKIP_PATTERNS:
        if pat.search(name):
            return None

    return name


def build_clean_drug_list(chunks: list[dict], law_name: str = "") -> str:
    """
    Main entry: build a clean numbered drug list.
    Returns formatted string or fallback message.
    """
    names = extract_drug_names(chunks)

    if not names:
        log.warning("[DRUG_EXTRACT] no names extracted — fallback")
        return "تعذر استخراج قائمة واضحة من الجدول الحالي. أنصحك بمراجعة الجداول الملحقة بقانون المخدرات على بوابة الميزان."

    lines = ["%d- %s" % (i, n) for i, n in enumerate(names, 1)]
    # No source line in user-facing output — keep clean list only
    result = "\n".join(lines)
    log.info("[DRUG_EXTRACT] built list: %d items", len(names))
    return result
