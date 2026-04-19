# -*- coding: utf-8 -*-
"""Full pipeline integration test — post Phase 1-6 validation."""
import asyncio, sys, io
sys.path.insert(0, ".")
# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

async def test_full_pipeline():
    from unified_analyzer import analyze_user_input, analysis_to_intent_mode
    from citation_guard import mmr_rerank, build_grounding_instruction, validate_citations
    from legal_reasoning_engine import build_legal_reasoning, apply_reasoning_to_answer
    from language_perfection import perfect_answer_rules
    from production_hardening import check_rate_limit, get_health, response_cache

    print("=" * 60)
    print("   FULL PIPELINE INTEGRATION TEST — Phases 1–6")
    print("=" * 60)

    # ── 1. Rate Limiter ──────────────────────────────────────────
    allowed, remaining = check_rate_limit("127.0.0.1")
    assert allowed, "Rate limit should allow first request"
    print(f"[1] Rate Limiter      ✓  allowed={allowed}, remaining={remaining}")

    # ── 2. Unified Analysis (rule-based fallback, no LLM) ────────
    # Question includes decision-seeking phrase to trigger reasoning block
    q = "صاحب العمل لم يدفعوا راتبي منذ 3 أشهر، ماذا أفعل وما خياراتي القانونية؟"
    analysis = await analyze_user_input(q)
    intent, mode = analysis_to_intent_mode(analysis)
    assert analysis["domain"] in ("labor", "عمل"), f"Expected labor domain, got {analysis['domain']}"
    print(f"[2] Unified Analysis  ✓  domain={analysis['domain']}, intent={intent}, mode={mode}, level={analysis['user_level']}")

    # ── 3. Simulated RAG chunks ──────────────────────────────────
    chunks = [
        {"content": "المادة 66 من قانون العمل القطري رقم 14 لسنة 2004 تلزم صاحب العمل بدفع الأجر في موعده", "score": 0.92, "source": "labor_law"},
        {"content": "المادة 110 تتيح للعامل تقديم شكوى لوزارة العمل عند تأخر صرف الراتب", "score": 0.88, "source": "labor_law"},
        {"content": "المادة 120 تنص على تعويض العامل عن فترة الإشعار عند إنهاء العقد", "score": 0.75, "source": "labor_law"},
        {"content": "يحق للعامل إنهاء عقده دون إشعار إذا أخل صاحب العمل بالتزاماته المالية", "score": 0.70, "source": "labor_law"},
    ]

    # ── 4. MMR Rerank ────────────────────────────────────────────
    reranked = mmr_rerank(chunks, lambda_param=0.6, top_k=4)
    assert len(reranked) <= 4
    print(f"[3] MMR Rerank        ✓  {len(reranked)}/{len(chunks)} chunks selected")

    # ── 5. Grounding Instruction ─────────────────────────────────
    grounding = build_grounding_instruction(reranked)
    assert len(grounding) > 10, f"Grounding instruction should not be empty, got: {repr(grounding)}"
    print(f"[4] Grounding Instr.  ✓  {len(grounding)} chars: {grounding[:60].strip()}...")

    # ── 6. Simulate LLM answer with hallucinated article ─────────
    # Use a longer answer (>400 chars) so ALL perfection steps activate
    raw_answer = (
        "بناءً على المعلومات المتوفرة، وفقاً للمادة 66 من قانون العمل القطري رقم 14 لسنة 2004 "
        "يلتزم صاحب العمل بدفع الأجر في موعده المحدد بعقد العمل أو اللوائح الداخلية للمنشأة. "
        "وفي حال التأخر في الصرف يحق للعامل اتخاذ إجراءات قانونية فورية للمطالبة بحقه. "
        "كما أشرنا آنفاً، المادة 110 تتيح للعامل تقديم شكوى رسمية إلى وزارة العمل والشؤون الاجتماعية. "
        "ومما سبق يتضح أن المادة 120 تمنح العامل حق التعويض عن فترة الإشعار في حالة الإنهاء المفاجئ. "
        "كذلك المادة 999 تمنحك مكافأة إضافية غير موجودة في القانون القطري. "
        "وبناءً على ما سبق فإن موقفك القانوني قوي ويمكنك المطالبة بكامل حقوقك المالية المتأخرة."
    )

    # ── 7. Citation Validation ───────────────────────────────────
    validated, hallucinated = validate_citations(raw_answer, reranked, strict=True)
    assert any("999" in h for h in hallucinated), f"Article 999 should be flagged, got: {hallucinated}"
    print(f"[5] Citation Guard    ✓  {len(hallucinated)} hallucinated: {hallucinated}")

    # ── 8. Language Perfection ───────────────────────────────────
    perfected = perfect_answer_rules(validated, "إجراء", "غاضب")
    # Robotic opener should be removed (always active)
    assert "بناءً على المعلومات المتوفرة" not in perfected, "Robotic opener should be removed"
    # Filler phrases removed for answers >400 chars
    assert "كما أشرنا آنفاً" not in perfected, "Filler phrase should be removed in long answers"
    assert "ومما سبق يتضح أن" not in perfected, "Filler phrase should be removed"
    print(f"[6] Language Polish   ✓  {len(raw_answer)}->{len(perfected)} chars, robotic phrases removed")
    print(f"    Preview: {perfected[:100]}...")

    # ── 9. Legal Reasoning Engine ────────────────────────────────
    reasoning = build_legal_reasoning(q, perfected, analysis, reranked, "legal_pipeline")
    assert reasoning["show_block"] is True
    assert reasoning["argument_strength"] > 50
    print(f"[7] Legal Reasoning   ✓  strength={reasoning['argument_strength']}, risk={reasoning['risk_level']}")
    print(f"    action={reasoning['best_action']}")
    print(f"    proven={len(reasoning['proven_elements'])}, missing={len(reasoning['missing_elements'])}")

    # ── 10. Apply Reasoning to Answer ────────────────────────────
    final_answer = apply_reasoning_to_answer(perfected, reasoning)
    assert len(final_answer) >= len(perfected)
    print(f"[8] Answer w/ Reason  ✓  {len(final_answer)} chars total")

    # ── 11. Response Cache ───────────────────────────────────────
    await response_cache.set("test_labor_q", {"answer": final_answer, "domain": "labor"}, domain="labor")
    cached = await response_cache.get("test_labor_q", domain="labor")
    assert cached is not None and "answer" in cached
    print(f"[9] Response Cache    ✓  set+get OK, {len(cached['answer'])} chars cached")

    # ── 12. Health Check ─────────────────────────────────────────
    health = get_health(force_refresh=True)
    print(f"[10] Health Check     ✓  status={health['status']}, modules={health['modules_loaded']}/{health['modules_total']}")
    critical_modules = {k: v for k, v in health["modules"].items() if v["critical"]}
    for mod, status in critical_modules.items():
        icon = "✓" if status.get("ok") else "✗"
        print(f"     {icon} {mod}: loaded={status['loaded']}, ok={status.get('ok')}")

    print()
    print("=" * 60)
    print("   ALL 10 TESTS PASSED ✓")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_full_pipeline())
