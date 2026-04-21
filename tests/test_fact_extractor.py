# -*- coding: utf-8 -*-
"""
tests/test_fact_extractor.py — unit contract for core/fact_extractor.

Scope
=====
Locks the PUBLIC and REGEX-FALLBACK contracts of fact_extractor. The
LLM path itself is not stubbed here (the module is integration-tested
end-to-end via the h1-h5 suite); what this file guards is:

  • ExtractedFacts dataclass semantics (is_empty / as_facts_lines /
    to_dict / from_dict round-trip).
  • _build_context behaviour (history filtering, ordering).
  • _regex_fallback coverage: comma-preserving amounts, Arabic ages,
    dates, Arabic-punctuation sentence splitting.
  • extract_user_facts async contract: empty input → empty struct.
  • extract_user_facts_sync wrapper contract: callable from sync code,
    returns a valid ExtractedFacts on any input.

Determinism
-----------
All calls pass ``use_cache=False`` so Redis state does not leak
between tests. The LLM is a remote dependency — we accept whichever
path (LLM or regex fallback) runs, as long as the return type is
correct. Tests that depend on specific extraction content use
``_regex_fallback`` directly.

Run
---
    pytest tests/test_fact_extractor.py -v
"""
import pytest

from core.fact_extractor import (
    ExtractedFacts,
    extract_user_facts,
    extract_user_facts_sync,
    _build_context,
    _regex_fallback,
)


# ═══════════════════════════════════════════════════════════════════
# Dataclass contract
# ═══════════════════════════════════════════════════════════════════

def test_fe_dataclass_is_empty_default():
    assert ExtractedFacts().is_empty() is True


def test_fe_dataclass_not_empty_with_claim():
    f = ExtractedFacts(claims=["test claim"])
    assert f.is_empty() is False


def test_fe_dataclass_not_empty_with_amount():
    f = ExtractedFacts(amounts=["12,000 ريال"])
    assert f.is_empty() is False


def test_fe_as_facts_lines_deduplicates():
    f = ExtractedFacts(claims=["claim one", "claim one", "claim two"])
    lines = f.as_facts_lines()
    assert len(lines) == 2
    assert "claim one" in lines
    assert "claim two" in lines


def test_fe_as_facts_lines_skips_too_short():
    f = ExtractedFacts(claims=["abc", "this is long enough"])
    lines = f.as_facts_lines()
    assert "abc" not in lines
    assert "this is long enough" in lines


def test_fe_as_facts_lines_caps_at_six():
    f = ExtractedFacts(claims=[f"long enough claim {i}" for i in range(10)])
    assert len(f.as_facts_lines()) == 6


def test_fe_roundtrip_to_dict_from_dict():
    original = ExtractedFacts(
        names=["أحمد"],
        dates=["2024"],
        amounts=["12,000 ريال"],
        ages=["3 سنوات"],
        claims=["claim one"],
        requests=["اكتب مذكرة"],
    )
    rebuilt = ExtractedFacts.from_dict(original.to_dict())
    assert rebuilt.to_dict() == original.to_dict()


def test_fe_from_dict_tolerates_missing_keys():
    # Partial dict — missing keys must not raise
    f = ExtractedFacts.from_dict({"claims": ["one claim"]})
    assert f.claims == ["one claim"]
    assert f.names == []
    assert f.amounts == []


def test_fe_from_dict_caps_list_sizes():
    bloat = {"claims": [f"c{i}" for i in range(50)]}
    f = ExtractedFacts.from_dict(bloat)
    assert len(f.claims) == 6         # claims cap


# ═══════════════════════════════════════════════════════════════════
# _build_context
# ═══════════════════════════════════════════════════════════════════

def test_fe_build_context_plain_query():
    ctx = _build_context("simple query", history=None)
    assert ctx == "simple query"


def test_fe_build_context_combines_history_user_messages_only():
    history = [
        {"role": "user",      "content": "past user 1"},
        {"role": "assistant", "content": "past assistant reply"},
        {"role": "user",      "content": "past user 2"},
    ]
    ctx = _build_context("current", history)
    assert "past user 1" in ctx
    assert "past user 2" in ctx
    assert "current" in ctx
    assert "past assistant reply" not in ctx


def test_fe_build_context_empty_query_ok():
    ctx = _build_context("", history=[])
    # Returns empty string (joined with separator absent since only one part)
    assert ctx == ""


def test_fe_build_context_caps_to_last_four_user_messages():
    history = [
        {"role": "user", "content": f"msg {i}"} for i in range(10)
    ]
    ctx = _build_context("current", history)
    # History slice is last 8 turns → then last 4 user msgs kept
    # So "msg 0"..."msg 5" should be dropped.
    assert "msg 0" not in ctx
    assert "msg 9" in ctx
    assert "current" in ctx


# ═══════════════════════════════════════════════════════════════════
# _regex_fallback coverage
# ═══════════════════════════════════════════════════════════════════

def test_fe_regex_preserves_comma_amount():
    """The h3 regression — comma-separated thousands must survive."""
    ctx = "كتب لي شيك بمبلغ 12,000 ريال"
    result = _regex_fallback(ctx)
    assert len(result.amounts) >= 1
    assert "12,000" in result.amounts[0]
    assert "ريال" in result.amounts[0]


def test_fe_regex_multiple_amounts():
    ctx = "دفع 5,000 ريال أولاً ثم 8000 ريال لاحقاً"
    result = _regex_fallback(ctx)
    assert len(result.amounts) == 2
    assert any("5,000" in a for a in result.amounts)
    assert any("8000" in a for a in result.amounts)


def test_fe_regex_extracts_age():
    ctx = "موكلي له طفل اسمه احمد عمره 3 سنوات"
    result = _regex_fallback(ctx)
    assert any("3" in a for a in result.ages)


def test_fe_regex_extracts_date():
    ctx = "حُرر الشيك بتاريخ 15/03/2024"
    result = _regex_fallback(ctx)
    assert any("15/03/2024" in d for d in result.dates)


def test_fe_regex_extracts_claims_from_sentences():
    ctx = "رفعت دعوى حضانة. السبب سوء السلوك. الأم تزوجت."
    result = _regex_fallback(ctx)
    # 3 sentences, all ≥ 8 chars
    assert len(result.claims) >= 2


def test_fe_regex_fallback_on_empty_text():
    result = _regex_fallback("")
    assert result.is_empty()


def test_fe_regex_ignores_plain_numbers_without_currency():
    # "12" alone (no ريال/دينار/درهم) must NOT be classed as amount
    ctx = "عنده 12 ولد وبنت"
    result = _regex_fallback(ctx)
    assert result.amounts == []


# ═══════════════════════════════════════════════════════════════════
# Public API contracts — async + sync
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_fe_async_empty_query_returns_empty():
    result = await extract_user_facts("", use_cache=False)
    assert isinstance(result, ExtractedFacts)
    assert result.is_empty()


@pytest.mark.asyncio
async def test_fe_async_whitespace_query_returns_empty():
    result = await extract_user_facts("   \n  ", use_cache=False)
    assert isinstance(result, ExtractedFacts)
    assert result.is_empty()


@pytest.mark.asyncio
async def test_fe_async_returns_extracted_facts_instance():
    # Do NOT assert specific content — LLM may or may not be reachable.
    # The invariant: return type is ExtractedFacts, never raises.
    result = await extract_user_facts(
        "موكلي موظف سرق 50 ألف واعترف",
        history=[],
        use_cache=False,
    )
    assert isinstance(result, ExtractedFacts)


def test_fe_sync_wrapper_callable_with_simple_input():
    result = extract_user_facts_sync(
        "test query",
        history=[],
        use_cache=False,
    )
    assert isinstance(result, ExtractedFacts)


def test_fe_sync_wrapper_handles_empty():
    result = extract_user_facts_sync("", history=[], use_cache=False)
    assert isinstance(result, ExtractedFacts)
    assert result.is_empty()


def test_fe_sync_wrapper_handles_none_history():
    result = extract_user_facts_sync("some query", history=None, use_cache=False)
    assert isinstance(result, ExtractedFacts)


# ═══════════════════════════════════════════════════════════════════
# composer._split_combined_query — rehydrates handle_memo_smart's
# " | "-joined combined query. Lives in composer.py but tested here
# because it's conceptually part of the fact_extractor integration.
# ═══════════════════════════════════════════════════════════════════

def test_split_combined_no_pipe():
    from core.runtime_v2.composer import _split_combined_query
    actual, pseudo = _split_combined_query("simple query")
    assert actual == "simple query"
    assert pseudo == []


def test_split_combined_with_pipe():
    from core.runtime_v2.composer import _split_combined_query
    actual, pseudo = _split_combined_query("msg1 | msg2 | current query here")
    assert actual == "current query here"
    assert len(pseudo) == 2
    assert pseudo[0] == {"role": "user", "content": "msg1"}
    assert pseudo[1] == {"role": "user", "content": "msg2"}


def test_split_combined_short_current_fallback():
    from core.runtime_v2.composer import _split_combined_query
    # Final part < 3 chars → regarded as malformed, return whole as query
    actual, pseudo = _split_combined_query("normal message content | a")
    assert actual == "normal message content | a"
    assert pseudo == []


def test_split_combined_empty():
    from core.runtime_v2.composer import _split_combined_query
    actual, pseudo = _split_combined_query("")
    assert actual == ""
    assert pseudo == []


def test_split_combined_real_world_custody():
    """The T3→T4 handle_memo_smart combined query shape."""
    from core.runtime_v2.composer import _split_combined_query
    q = (
        "اكتب مذكرة اسقاط حضانه ضد طليقتي | "
        "1- طفل واحد اسمه احمد وعمره 3 سنوات 2- السبب سوء سلوك"
    )
    actual, pseudo = _split_combined_query(q)
    assert "1-" in actual and "احمد" in actual
    assert len(pseudo) == 1
    assert "اكتب مذكرة" in pseudo[0]["content"]
