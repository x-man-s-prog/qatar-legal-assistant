# -*- coding: utf-8 -*-
"""Tests for drug-list OCR cleanup."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.answer_builder import (
    build_drug_answer,
    _normalize_ocr,
    _is_garbage_line,
)


def test_normalize_ocr_letters():
    s = "ﺍﺴﻴﺘﻭﺭﻓﻴﻥ"  # presentation forms
    out = _normalize_ocr(s)
    assert "ا" in out
    assert "ﺍ" not in out


def test_normalize_keeps_normal_text():
    s = "اسيتورفين"
    assert _normalize_ocr(s) == s


def test_garbage_line_punctuation():
    assert _is_garbage_line("...---,,,...") is True
    assert _is_garbage_line("12 34 56") is True


def test_garbage_line_short():
    assert _is_garbage_line("ا") is True
    assert _is_garbage_line("") is True


def test_garbage_line_real_substance():
    assert _is_garbage_line("اسيتورفين") is False
    assert _is_garbage_line("MORPHINE") is False


def test_drug_builder_drops_long_paragraphs():
    long_paragraph = "ا" * 200
    chunks = [{"content": f"1- اسيتورفين\n2- مورفين\n{long_paragraph}\n3- كوكايين",
               "law_name": "قانون مكافحة المخدرات"}]
    out = build_drug_answer(chunks)
    assert "اسيتورفين" in out
    assert "مورفين" in out
    assert "كوكايين" in out
    # Long paragraph should not appear
    assert long_paragraph not in out


def test_drug_builder_normalizes_ocr_forms():
    # OCR-form Arabic for "اسيتورفين"
    chunks = [{"content": "1- ﺍﺴﻴﺘﻭﺭﻓﻴﻥ\n2- ﻤﻭﺭﻓﻴﻥ",
               "law_name": "قانون مكافحة المخدرات"}]
    out = build_drug_answer(chunks)
    # Should appear in canonical Arabic (or at least with normalization applied)
    assert "ﺍ" not in out  # presentation forms removed
    assert "ا" in out


def test_drug_builder_extracts_english_names():
    chunks = [{"content": "1- MORPHINE - مورفين\n2- COCAINE - كوكايين",
               "law_name": "قانون مكافحة المخدرات"}]
    out = build_drug_answer(chunks)
    assert "MORPHINE" in out or "مورفين" in out
    assert "COCAINE" in out or "كوكايين" in out


def test_drug_builder_skips_filler_words():
    chunks = [{"content": "1- THE LAW says morphine\n2- MORPHINE pure",
               "law_name": "قانون مكافحة المخدرات"}]
    out = build_drug_answer(chunks)
    # THE / LAW must NOT appear as a substance
    lines = out.split("\n")
    bare_items = [l.split("- ", 1)[-1] for l in lines if "- " in l]
    assert "THE" not in bare_items
    assert "LAW" not in bare_items


def test_drug_builder_no_forbidden_markers():
    chunks = [{"content": "📋 جدول المخدرات\n1- اسيتورفين\n2- مورفين",
               "law_name": "قانون مكافحة المخدرات"}]
    out = build_drug_answer(chunks)
    for marker in ["📋", "⚖️", "🔍", "✅", "📊"]:
        assert marker not in out


def test_drug_builder_caps_to_max():
    items = "\n".join(f"{i}- مادة_{i}" for i in range(300))
    chunks = [{"content": items, "law_name": "قانون مكافحة المخدرات"}]
    out = build_drug_answer(chunks)
    # We cap at MAX_ITEMS (200)
    lines = [l for l in out.split("\n") if l.strip().startswith(tuple(str(i) for i in range(10)))]
    assert len(lines) <= 200
