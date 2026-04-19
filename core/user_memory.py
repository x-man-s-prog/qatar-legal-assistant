#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
user_memory.py — ذاكرة تراكمية للمستخدم
==========================================
يحفظ معلومات القضايا + أسلوب الصياغة المفضّل لكل مستخدم.
"""
import json, os, re, logging
from typing import Optional

log = logging.getLogger("user_memory")
MEMORY_DIR = "/app/user_memories"


def _ensure_dir():
    os.makedirs(MEMORY_DIR, exist_ok=True)


def save_case_info(session_id: str, case_info: dict):
    _ensure_dir()
    mem = load_user_memory(session_id)
    mem["cases"].append(case_info)
    # أبقِ آخر 10 قضايا فقط
    mem["cases"] = mem["cases"][-10:]
    _path = os.path.join(MEMORY_DIR, f"{session_id}.json")
    try:
        with open(_path, 'w', encoding='utf-8') as f:
            json.dump(mem, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.warning("save_case_info failed: %s", e)


def load_user_memory(session_id: str) -> dict:
    _path = os.path.join(MEMORY_DIR, f"{session_id}.json")
    if os.path.exists(_path):
        try:
            with open(_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {"cases": [], "style": {}, "preferences": {}}


def save_user_style(session_id: str, style: dict):
    _ensure_dir()
    mem = load_user_memory(session_id)
    mem["style"] = style
    _path = os.path.join(MEMORY_DIR, f"{session_id}.json")
    try:
        with open(_path, 'w', encoding='utf-8') as f:
            json.dump(mem, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.warning("save_user_style failed: %s", e)


def learn_from_user_memo(memo_text: str) -> dict:
    """يحلل مذكرة كتبها المستخدم ويستخرج أسلوبه."""
    style = {
        "opening": "بسم الله",
        "citation_style": "مختصر",
        "has_ruling_numbers": False,
        "unique_phrases": [],
        "tone": "رسمي",
    }

    if not memo_text or len(memo_text) < 100:
        return style

    # الافتتاح
    if "أَحْمَدُهُ" in memo_text or "الحمد لله" in memo_text[:200]:
        style["opening"] = "خطبة بليغة"
    elif "بسم الله" in memo_text[:100]:
        style["opening"] = "بسم الله"

    # أسلوب الاستشهاد
    if "نص المادة" in memo_text or "تنص المادة" in memo_text:
        style["citation_style"] = "ينقل نص المادة كاملاً"
    elif "وفقاً للمادة" in memo_text:
        style["citation_style"] = "يشير بدون نقل"

    # أرقام طعون
    ruling_re = re.compile(r'الطعن\s*رقم\s*\d+\s*/\s*\d{4}', re.UNICODE)
    if ruling_re.search(memo_text):
        style["has_ruling_numbers"] = True

    # عبارات مميزة
    _PHRASES = [
        "دون اختصار مخل او اسهاب ممل",
        "يقطع بصحة ما نذهب إليه",
        "فجور في الخصومة",
        "ما ينشده مصلحة",
        "على سبيل الجزم واليقين",
        "والثابت بيقين لا يدع مجالاً للشك",
    ]
    for p in _PHRASES:
        if p in memo_text:
            style["unique_phrases"].append(p)

    return style


def build_memory_context(session_id: str) -> str:
    """يبني سياق من ذاكرة المستخدم لحقنه في prompt."""
    mem = load_user_memory(session_id)
    parts = []

    if mem.get("cases"):
        parts.append("═══ قضايا سابقة للمستخدم ═══")
        for case in mem["cases"][-3:]:
            topic = case.get("topic", "")
            summary = case.get("summary", "")
            if topic or summary:
                parts.append(f"  • {topic}: {summary}")

    if mem.get("style"):
        s = mem["style"]
        if s.get("opening") and s["opening"] != "بسم الله":
            parts.append(f"أسلوب المستخدم: يحب {s['opening']}")
        if s.get("has_ruling_numbers"):
            parts.append("المستخدم يفضّل الاستشهاد بأرقام طعون")
        if s.get("unique_phrases"):
            parts.append(f"عبارات مفضّلة: {' | '.join(s['unique_phrases'][:3])}")

    if not parts:
        return ""
    return "\n" + "\n".join(parts) + "\n"
