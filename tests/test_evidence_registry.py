# -*- coding: utf-8 -*-
"""Tests for the Evidence Registry."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.evidence_registry import EvidenceEntry, EvidenceRegistry, SupportLevel


def _make_registry():
    r = EvidenceRegistry()
    r.register(EvidenceEntry(
        entry_id="t1", statement_ar="المربوط هو الراتب الأساسي",
        domain="salary", topic="basic_salary",
        support_level=SupportLevel.DIRECT_EVIDENCE.value,
        tags=["مربوط", "تعريف"],
    ))
    r.register(EvidenceEntry(
        entry_id="t2", statement_ar="الإجمالي يختلف بحسب البدلات",
        domain="salary", topic="total_compensation",
        support_level=SupportLevel.CONTROLLED_INFERENCE.value,
        tags=["إجمالي"],
    ))
    r.register(EvidenceEntry(
        entry_id="t3", statement_ar="قد يصل الإجمالي إلى ضعف المربوط",
        domain="salary", topic="total_compensation",
        support_level=SupportLevel.UNSUPPORTED_BLOCKED.value,
        tags=["محظور"],
    ))
    r.register(EvidenceEntry(
        entry_id="t4", statement_ar="المواد المخدرة مدرجة في الجدول الأول",
        domain="drug", topic="schedule_1",
        support_level=SupportLevel.DIRECT_EVIDENCE.value,
        tags=["مخدرات"],
    ))
    return r


# ── Registration and Lookup ───────────────────────────────

def test_register_and_get():
    r = _make_registry()
    assert r.get("t1") is not None
    assert r.get("t1").statement_ar == "المربوط هو الراتب الأساسي"
    assert r.get("nonexistent") is None


def test_get_by_domain():
    r = _make_registry()
    salary = r.get_by_domain("salary")
    assert len(salary) == 3
    drug = r.get_by_domain("drug")
    assert len(drug) == 1


def test_get_by_topic():
    r = _make_registry()
    tc = r.get_by_topic("total_compensation")
    assert len(tc) == 2


def test_get_direct_evidence():
    r = _make_registry()
    direct = r.get_direct_evidence(domain="salary")
    assert len(direct) == 1
    assert direct[0].entry_id == "t1"


def test_get_inferences():
    r = _make_registry()
    infer = r.get_inferences(domain="salary")
    assert len(infer) == 1
    assert infer[0].entry_id == "t2"


def test_get_blocked():
    r = _make_registry()
    blocked = r.get_blocked(domain="salary")
    assert len(blocked) == 1
    assert blocked[0].entry_id == "t3"


def test_search():
    r = _make_registry()
    results = r.search("مربوط")
    assert any(e.entry_id == "t1" for e in results)


# ── Claim Verification ───────────────────────────────────

def test_is_claim_supported_direct():
    r = _make_registry()
    supported, entry = r.is_claim_supported("المربوط هو الراتب الأساسي", domain="salary")
    assert supported is True
    assert entry.entry_id == "t1"


def test_is_claim_blocked():
    r = _make_registry()
    blocked, entry = r.is_claim_blocked("قد يصل الإجمالي إلى ضعف المربوط", domain="salary")
    assert blocked is True
    assert entry.entry_id == "t3"


def test_unsupported_claim():
    r = _make_registry()
    supported, _ = r.is_claim_supported("القانون سيتغير غداً", domain="salary")
    assert supported is False


# ── Pack Loading ──────────────────────────────────────────

def test_load_pack():
    r = EvidenceRegistry()
    entries = [
        EvidenceEntry(entry_id="p1", statement_ar="بيان 1", domain="test"),
        EvidenceEntry(entry_id="p2", statement_ar="بيان 2", domain="test"),
    ]
    count = r.load_pack("test_pack", entries)
    assert count == 2
    assert "test_pack" in r.loaded_packs()


def test_load_pack_no_duplicate():
    r = EvidenceRegistry()
    entries = [EvidenceEntry(entry_id="p1", statement_ar="بيان", domain="test")]
    r.load_pack("pack_a", entries)
    count2 = r.load_pack("pack_a", entries)  # reload same pack
    assert count2 == 0  # should skip


# ── Stats ─────────────────────────────────────────────────

def test_stats():
    r = _make_registry()
    s = r.stats()
    assert s["total_entries"] == 4
    assert "salary" in s["by_domain"]
    assert "drug" in s["by_domain"]


# ── Entry Methods ─────────────────────────────────────────

def test_entry_is_direct():
    e = EvidenceEntry(entry_id="x", statement_ar="test",
                      support_level=SupportLevel.DIRECT_EVIDENCE.value)
    assert e.is_direct() is True
    assert e.is_inference() is False
    assert e.is_blocked() is False


def test_entry_is_blocked():
    e = EvidenceEntry(entry_id="x", statement_ar="test",
                      support_level=SupportLevel.UNSUPPORTED_BLOCKED.value)
    assert e.is_blocked() is True
    assert e.is_direct() is False
