# -*- coding: utf-8 -*-
"""
core/case_memory/summary.py — one-shot case summary via GPT.

Called **exactly once** per unique case (first insertion). Subsequent
hits re-use the cached summary from Redis — never re-generate.

Called from the background task ``_store_case_bg`` in
``routers/query_router.handle_general``, **not** in the hot path that
returns the response. Failure is non-fatal: the caller stores a
fallback prefix of the original query when GPT is unavailable.

Cost envelope: ≤ 150 tokens per unique case, near-deterministic
temperature. At the expected volume (≤ 50 cases / session × active
sessions) this is negligible.

Adaptation note
---------------
The original Layer 3 prompt referenced a non-existent
``services.llm_service.call_openai_chat_completion`` helper with
per-call ``model``/``temperature``/``timeout`` kwargs. The codebase
actually exposes ``call_openai(system, messages, max_tokens)`` —
model comes from the ``MODEL_OPENAI`` env var, temperature is fixed
at 0.3, and timeout is handled by httpx at 120s.

Rather than introduce a new helper in ``llm_service`` (out of CP2
scope per session rule "no edits outside core/case_memory/..."), we
wrap the existing ``call_openai`` and:

  • apply our own ``asyncio.wait_for`` timeout (10s — summary must
    not hang the background task);
  • detect the service's error-string return convention (``"خطأ..."``)
    and convert it to ``None`` per the caller contract.

``_SUMMARY_MODEL`` is kept as module documentation of the intended
model (``gpt-4o-mini``) so that a future ``llm_service`` refactor
exposing per-call model selection has a single place to wire in.

Status: CP2 · Part D. Implementation live; cm20/cm20b exercise it.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────

# Documented intent — not currently routable through call_openai.
# See "Adaptation note" in the module docstring.
_SUMMARY_MODEL: str = "gpt-4o-mini"
_SUMMARY_MAX_TOKENS: int = 150
_SUMMARY_TEMPERATURE: float = 0.1          # intent; not enforceable today
_SUMMARY_TIMEOUT_SECONDS: float = 10.0

# Truncation caps on prompt inputs
_QUERY_TRIM_CHARS: int = 500
_ANSWER_TRIM_CHARS: int = 2000

# Defensive upper bound on the returned summary
_MAX_SUMMARY_CHARS: int = 600


# ─────────────────────────────────────────────────────────────────
# Prompt
# ─────────────────────────────────────────────────────────────────

_SUMMARY_SYSTEM_PROMPT: str = """أنت تساعد محامياً قطرياً على تلخيص قضايا عملائه.
مهمتك: تلخيص القضية في 2-3 جمل عربية قصيرة لتُخزَّن كذاكرة للرجوع إليها.

قواعد صارمة:
- جملتان إلى ثلاث جمل فقط. لا أكثر.
- لغة فصحى واضحة، بدون مصطلحات فقهية معقدة.
- ركّز على: (1) من الأطراف، (2) ما الواقعة، (3) الاتجاه القانوني الأساسي.
- لا تذكر أرقام مواد أو أحكام تمييز — فقط السياق الوقائعي.
- لا تقدم رأياً قانونياً.
- ابدأ مباشرة، بدون تمهيد ("هذه قضية..." ممنوعة).

مثال جيد: "موكل صاحب شركة. موظفه سرق 50 ألف واعترف وعنده سابقة. المسار: مطالبة جنائية + تعويض مدني."

مثال سيء (مرفوض): "هذه قضية مهمة في مجال السرقات الوظيفية، حيث يعتبر..."
"""


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────

async def generate_case_summary_once(
    query: str,
    answer: str,
) -> Optional[str]:
    """Produce a 2-3 sentence case summary from the Q/A pair.

    Parameters
    ----------
    query : str
        The user's original query (the one that spawned the case).
    answer : str
        The assistant's full reply to that query.

    Returns
    -------
    Optional[str]
        Summary on success (always non-empty if not None).
        ``None`` on any failure — LLM unavailable, timeout, empty or
        error-string response, transport exception. The caller is
        expected to fall back (typically ``query[:120] + "..."``).

    Design note
    -----------
    Returns ``None`` rather than raising so the background-task caller
    (``_store_case_bg``) cannot be destabilised by a single failing
    summary. The explicit None contract is documented at the callsite
    in store.py prep work for CP3.
    """
    if not query or not answer:
        return None

    query_trimmed = query[:_QUERY_TRIM_CHARS]
    answer_trimmed = answer[:_ANSWER_TRIM_CHARS]

    user_content = (
        f"السؤال الأصلي:\n{query_trimmed}\n\n"
        f"الإجابة المُولَّدة (مقتطف):\n{answer_trimmed}\n\n"
        f"لخّص القضية في 2-3 جمل."
    )

    try:
        # Local import: avoids module-load-time dependency on llm_service
        # and lets tests monkey-patch ``_call_with_timeout`` cleanly.
        from services.llm_service import call_openai

        raw = await _call_with_timeout(
            call_openai,
            timeout=_SUMMARY_TIMEOUT_SECONDS,
            system=_SUMMARY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
            max_tokens=_SUMMARY_MAX_TOKENS,
        )
    except Exception as e:
        # Any failure (timeout, network, JSON, …) becomes None.
        log.warning(
            "case_memory summary generation failed: %s: %s",
            type(e).__name__, e,
        )
        return None

    # Validation: must be non-empty string.
    if not raw or not isinstance(raw, str):
        log.warning("case_memory summary: empty or non-string response")
        return None

    summary = raw.strip()
    if not summary:
        return None

    # llm_service.call_openai returns "خطأ OpenAI (...)" style strings
    # when the upstream call fails — treat those as failures.
    if summary.startswith("خطأ"):
        log.warning("case_memory summary: llm_service returned error sentinel")
        return None

    # Defensive upper bound — the prompt asks for 2-3 sentences but
    # LLMs drift. Trim at the nearest Arabic comma if we exceed.
    if len(summary) > _MAX_SUMMARY_CHARS:
        head = summary[:_MAX_SUMMARY_CHARS]
        pivot = head.rfind("،")
        summary = (head[:pivot] if pivot > 0 else head) + "..."

    return summary


# ─────────────────────────────────────────────────────────────────
# Helpers (module-level so tests can monkey-patch)
# ─────────────────────────────────────────────────────────────────

async def _call_with_timeout(func, timeout: float, **kwargs):
    """Wrap an async call with an ``asyncio.wait_for`` timeout.

    Module-level (not a closure) so ``tests/phase3/test_case_memory_unit``
    can ``monkeypatch.setattr`` this name to inject mock behaviour
    without touching the production code path.
    """
    return await asyncio.wait_for(func(**kwargs), timeout=timeout)


__all__ = ["generate_case_summary_once"]
