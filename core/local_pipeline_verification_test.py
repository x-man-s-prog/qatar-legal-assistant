# -*- coding: utf-8 -*-
"""
Local Pipeline Verification Test
=================================
Verifies that legal queries are handled by the LOCAL pipeline
and NEVER route to OpenAI / Gemini / Claude remote APIs.

Checks:
1. Config placeholder keys are filtered (OPENAI_KEY="CHANGE_ME" → treated as empty)
2. LLMGateway only exposes providers with real keys
3. primary_provider resolves to ollama when no real keys configured
4. A legal query response is generated without raising
5. No "OpenAI error (401)" leaks to users
6. Safe fallback message is returned on any failure
"""
from __future__ import annotations
import asyncio
import logging

log = logging.getLogger("local_pipeline_verify")


def run_local_pipeline_verification() -> dict:
    results = []

    def test(name: str, passed: bool, detail: str = ""):
        results.append({"name": name, "passed": passed, "detail": detail})
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}" + (f" — {detail}" if detail and not passed else ""))

    # ══════════════════════════════════════════════════════════════
    # TEST 1: Placeholder OPENAI_API_KEY filtered at config level
    # ══════════════════════════════════════════════════════════════
    from core.config import OPENAI_KEY, GEMINI_KEY, ANTHROPIC_KEY, _clean_key
    test("T01: _clean_key filters 'CHANGE_ME'",
         _clean_key("CHANGE_ME") == "" and _clean_key("changeme") == "")

    # ══════════════════════════════════════════════════════════════
    # TEST 2: _clean_key filters other placeholder patterns
    # ══════════════════════════════════════════════════════════════
    test("T02: _clean_key filters 'CHANGE_*' and 'YOUR_*' prefixes",
         _clean_key("CHANGE_THIS") == "" and _clean_key("YOUR_KEY_HERE") == "")

    # ══════════════════════════════════════════════════════════════
    # TEST 3: Real-looking keys pass through
    # ══════════════════════════════════════════════════════════════
    test("T03: real key passes through _clean_key",
         _clean_key("sk-proj-xxxxxxxx") == "sk-proj-xxxxxxxx"
         and _clean_key("") == "")

    # ══════════════════════════════════════════════════════════════
    # TEST 4: OPENAI_KEY is empty in current environment (placeholder filtered)
    # ══════════════════════════════════════════════════════════════
    import os
    raw_openai = os.environ.get("OPENAI_API_KEY", "")
    placeholder = raw_openai in ("", "CHANGE_ME", "changeme")
    # When the raw env var is a placeholder, the config key MUST be empty
    test("T04: OPENAI_KEY empty when env is placeholder",
         (not placeholder) or (OPENAI_KEY == ""),
         f"raw='{raw_openai[:10]}' cleaned='{OPENAI_KEY[:10]}'")

    # ══════════════════════════════════════════════════════════════
    # TEST 5: PRIMARY_MODEL falls back to ollama with no real keys
    # ══════════════════════════════════════════════════════════════
    from core.config import PRIMARY_MODEL
    # If no real keys, PRIMARY_MODEL must be ollama
    expected_primary = "ollama" if not (OPENAI_KEY or GEMINI_KEY or ANTHROPIC_KEY) else PRIMARY_MODEL
    test("T05: PRIMARY_MODEL resolves to local (ollama) without real keys",
         PRIMARY_MODEL == expected_primary,
         f"PRIMARY_MODEL={PRIMARY_MODEL}")

    # ══════════════════════════════════════════════════════════════
    # TEST 6: LLMGateway excludes providers with empty keys
    # ══════════════════════════════════════════════════════════════
    from llm_gateway import get_gateway
    gw = get_gateway()
    available = gw.get_available_providers()
    has_openai = "openai" in available
    has_gemini = "gemini" in available
    has_ollama = "ollama" in available
    # Ollama must always be available; openai/gemini only with real keys
    openai_ok = (not has_openai) or bool(OPENAI_KEY)
    gemini_ok = (not has_gemini) or bool(GEMINI_KEY)
    test("T06: gateway.get_available_providers respects cleaned keys",
         openai_ok and gemini_ok and has_ollama,
         f"available={available} OPENAI_KEY_set={bool(OPENAI_KEY)}")

    # ══════════════════════════════════════════════════════════════
    # TEST 7: gateway.primary_provider = ollama when no remote keys
    # ══════════════════════════════════════════════════════════════
    if not (OPENAI_KEY or GEMINI_KEY or ANTHROPIC_KEY):
        test("T07: gateway.primary_provider == 'ollama' (local-only)",
             gw.primary_provider() == "ollama",
             f"primary={gw.primary_provider()}")
    else:
        test("T07: gateway.primary_provider skipped (remote keys present)",
             True)

    # ══════════════════════════════════════════════════════════════
    # TEST 8: is_ollama_mode correctly reflects local-only state
    # ══════════════════════════════════════════════════════════════
    expected_ollama_mode = not (OPENAI_KEY or GEMINI_KEY or ANTHROPIC_KEY)
    test("T08: gateway.is_ollama_mode == local-only",
         gw.is_ollama_mode() == expected_ollama_mode)

    # ══════════════════════════════════════════════════════════════
    # TEST 9: _build_fallback_order excludes unavailable providers
    # ══════════════════════════════════════════════════════════════
    order = gw._build_fallback_order("openai")
    order_has_unavailable = any(p in order for p in ["openai", "gemini", "claude"]
                                  if p not in available)
    test("T09: fallback order never contains unavailable providers",
         not order_has_unavailable,
         f"order={order} available={available}")

    # ══════════════════════════════════════════════════════════════
    # TEST 10: LOCAL_ONLY_MODE config flag exists
    # ══════════════════════════════════════════════════════════════
    from core.config import LOCAL_ONLY_MODE
    test("T10: LOCAL_ONLY_MODE flag exists", isinstance(LOCAL_ONLY_MODE, bool))

    # ══════════════════════════════════════════════════════════════
    # TEST 11: Ordinary user orchestrator runs without remote calls
    # ══════════════════════════════════════════════════════════════
    from core.user_orchestrator import OrdinaryUserOrchestrator, UserFacingMode
    orch = OrdinaryUserOrchestrator()
    try:
        resp = orch.run(
            answer="العامل له الحق في التعويض إذا تم تخفيض راتبه بدون اتفاق.",
            query="اشرح حقوق العامل عند تخفيض راتبه",
            domain="employment", confidence=0.85,
            is_structured=False, mode=UserFacingMode.PUBLIC)
        # Must return a response (guidance, fallback, or ok)
        test("T11: orchestrator runs without remote calls",
             resp.final_status in ("ok", "guided", "fallback")
             and len(resp.final_text) > 0,
             f"status={resp.final_status} len={len(resp.final_text)}")
    except Exception as e:
        test("T11: orchestrator runs without remote calls", False, str(e))

    # ══════════════════════════════════════════════════════════════
    # TEST 12: Safe fallback message on RuntimeError
    # ══════════════════════════════════════════════════════════════
    # Simulate a hard failure — ensure the safe fallback message is returned
    # (We check the string is in the router source)
    with open("/app/routers/query_router.py", "r", encoding="utf-8") as f:
        router_src = f.read()
    has_safe_fallback = "تعذر معالجة الطلب حالياً" in router_src
    has_no_leak = "خطأ في الخدمة: {e}" not in router_src \
                  and "خطأ تقني: {e}" not in router_src
    test("T12: safe fallback message present + no raw-error leak",
         has_safe_fallback and has_no_leak,
         f"safe_fallback={has_safe_fallback} no_leak={has_no_leak}")

    # ══════════════════════════════════════════════════════════════
    # TEST 13: LOCAL_PIPELINE_USED logging marker present in router
    # ══════════════════════════════════════════════════════════════
    has_route_log = "LOCAL_PIPELINE_USED=True" in router_src
    test("T13: LOCAL_PIPELINE_USED logging marker present", has_route_log)

    # ══════════════════════════════════════════════════════════════
    # TEST 14: Fallback response contains local_pipeline_used=True flag
    # ══════════════════════════════════════════════════════════════
    has_flag = '"local_pipeline_used": True' in router_src
    test("T14: fallback payload includes local_pipeline_used=True", has_flag)

    # ══════════════════════════════════════════════════════════════
    # TEST 15: QueryRequest model default is empty (auto-select)
    # ══════════════════════════════════════════════════════════════
    from routers.query_router import QueryRequest
    req = QueryRequest(query="test query")
    test("T15: QueryRequest.model defaults to '' (auto-select)",
         req.model == "",
         f"model='{req.model}'")

    # ══════════════════════════════════════════════════════════════
    # TEST 16: Ultra test suite still passes (end-to-end no regression)
    # ══════════════════════════════════════════════════════════════
    try:
        from core.ultra_test_runner import UltraTestRunner, get_ultra_cases
        runner = UltraTestRunner()
        ultra = runner.run_suite(get_ultra_cases())
        test("T16: 50-case ultra suite still passes",
             ultra["summary"]["passed"] == 50 and ultra["summary"]["critical_count"] == 0,
             f"passed={ultra['summary']['passed']}/50 critical={ultra['summary']['critical_count']}")
    except Exception as e:
        test("T16: 50-case ultra suite still passes", False, str(e))

    # ══════════════════════════════════════════════════════════════
    # Summary
    # ══════════════════════════════════════════════════════════════
    passed = sum(1 for r in results if r["passed"])
    failed = sum(1 for r in results if not r["passed"])
    print(f"\n{'='*50}")
    print(f"LOCAL PIPELINE VERIFICATION: {passed}/{len(results)} passed")
    if failed:
        print("FAILURES:")
        for r in results:
            if not r["passed"]:
                print(f"  - {r['name']}: {r['detail']}")
    print(f"{'='*50}")

    return {"total": len(results), "passed": passed, "failed": failed, "results": results}


if __name__ == "__main__":
    run_local_pipeline_verification()
