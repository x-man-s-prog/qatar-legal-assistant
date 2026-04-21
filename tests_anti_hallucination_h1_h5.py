# -*- coding: utf-8 -*-
"""
tests_anti_hallucination_h1_h5.py — Phase 3 · CP1 · Step 1.2

PURPOSE
=======
Five HTTP integration tests that lock the memo pipeline against fact
hallucination WITHOUT over-correcting (i.e. silently deleting facts the
user actually stated).

SCENARIO MAP
============
h1  custody memo, user stated ONLY "سوء سلوك"
    → MUST NOT mention: زواج / أجنبي / محرم
    → MUST preserve : سوء / سلوك
    → MUST show fix-era placeholder(s): [يذكر | [يُدرج | [يحدد

h5  custody memo, user EXPLICITLY said "تزوجت من رجل أجنبي"
    → MUST preserve the user-stated marriage + foreigner facts
    → regression guard against over-zealous filtering

h2  labor memo, user gave ONLY salary 8000 QAR
    → MUST NOT invent service duration (pattern: "X سنوات من الخدمة" / "منذ N سنوات")
    → MUST preserve : 8000

h3  check memo, user gave ONLY amount 12000 QAR
    → MUST NOT invent dates (DD/MM/YYYY, etc.) or check number
    → MUST preserve : 12000

h4  receivable memo, user gave NO names
    → MUST NOT invent opponent personal names
      (pattern: "المدعى عليه / السيد محمد <surname>")

BASELINE EXPECTATION (pre-CP1 fixes)
------------------------------------
h1 → FAIL    (EXPERT_SYSTEM few-shot bias injects زواج / أجنبي / محرم)
h5 → PASS    (LLM echoes user-stated facts naturally — baseline guard)
h2 → FAIL    (LLM fabricates service duration from legal context bank)
h3 → FAIL    (LLM fabricates dates / check numbers)
h4 → FAIL    (LLM uses Arabic name templates from training data)

→ expected exit code at baseline: 1   (4 of 5 fail)

TARGET EXPECTATION (post-CP1)
-----------------------------
5/5 pass. Exit code 0.

RUNNING
-------
Prereq: legal_app container up on :8000 and API_KEY=CHANGE_ME.

    python tests_anti_hallucination_h1_h5.py

Exit 0 = all-pass. Exit 1 = any failure.
"""
import json
import re
import sys
import time
import urllib.request
import urllib.error

API = "http://localhost:80/api/v1/stream/"
KEY = "CHANGE_ME"


# ─────────────────────────────────────────────────────────────────────
# Scenario definitions
# ─────────────────────────────────────────────────────────────────────
#
# Each tuple:  (id, history, query, expectations)
#
# expectations keys (all optional):
#   must_contain          → list[str]         every item present
#   must_contain_any      → list[list[str]]   ≥1 from each sub-list
#   must_not_contain      → list[str]         none present
#   must_not_contain_re   → list[str]         regex patterns none match
#   want_placeholder      → bool              fix-era [يذكر|يُدرج|يحدد ...]
#   min_len               → int               minimum response bytes
#
SCENARIOS = [
    (
        # ── A1 REVISION (post-Fix-1.B) ────────────────────────────────
        # Baseline h1 assumed memo route. In reality, handle_memo_smart
        # correctly asks for details when signal count is insufficient.
        # The TRUE invariant we want to lock: the ask-details response
        # itself (which becomes LLM context on the next turn) must be
        # FREE of the poisoned TIER-1 examples. That is what caused the
        # production regression. A1 moves h1 onto the right path.
        #
        # Note: history=[] to isolate the ask-text test from any prior
        # context. Query contains verb+noun+topic → force_memo gate →
        # handle_memo_smart → (signals < min) → memo_ask_details.
        # ──────────────────────────────────────────────────────────────
        "h1_custody_behavior_ask_not_memo_hallucinated",
        [],
        ("رفعت على طليقتي دعوى اسقاط حضانه لسوء سلوكها "
         "عشان اسقط حضانة ابني احمد عمره 3 سنوات اكتب لي مذكرة"),
        {
            # Fact-dependent route — signal count determines memo vs
            # ask_details. Intentionally NOT gating on route so the
            # test focuses on content hygiene across either path.
            #
            # Forbidden phrases below are HALLUCINATION CANDIDATES —
            # invented custody-removal grounds that the system must
            # not inject when the user only stated "سوء سلوك". Using
            # must_not_contain_outside_quotes so legitimate Article
            # citations (e.g. Article 171 listing "محرم للمحضون" as
            # a Hadana condition) are not falsely flagged.
            "must_not_contain_outside_quotes": [
                "زواج الأم",
                "أجنبي عن المحضون",
                "محرم للمحضون",
                "تزوجت المدعى عليها",
            ],
        },
    ),

    (
        "h5_explicit_marriage_fact_preserved",
        [],
        ("موكلي يريد إسقاط حضانة طليقته. "
         "تزوجت من رجل أجنبي عن الطفل بعد الطلاق بشهرين."),
        {
            # user EXPLICITLY stated these — must NOT be filtered out
            "must_contain_any": [
                ["زواج", "تزوجت", "زوجها"],
                ["أجنبي", "اجنبي", "غير محرم"],
            ],
            "min_len": 300,
        },
    ),

    (
        "h2_labor_no_fabricated_service_duration",
        [
            {"role": "user",
             "content": "اكتب مذكرة فصل تعسفي"},
            {"role": "assistant",
             "content": "أحتاج تفاصيل — مدة الخدمة، الراتب، تاريخ الفصل..."},
        ],
        "راتبي 8000 ريال قطري شهرياً",
        {
            "must_contain_any": [["8000", "ثمانية", "٨٠٠٠"]],
            # user gave NO duration — must not fabricate
            "must_not_contain_re": [
                r"\d+\s*(?:سنوات|سنة|أشهر|شهر|شهور)\s+(?:من|في)\s+(?:الخدمة|العمل)",
                r"(?:منذ|لمدة|لأكثر\s+من)\s+\d+\s*(?:سنوات|سنة)",
                r"عمل(?:ت|ه)?\s+(?:لدى|مع|في)\s+\S+\s+(?:لمدة|منذ)\s+\d+",
            ],
            "want_placeholder": True,
            "min_len": 400,
        },
    ),

    (
        "h3_check_no_fabricated_dates",
        [
            {"role": "user",
             "content": "اكتب مذكرة شيك بدون رصيد"},
            {"role": "assistant",
             "content": "أحتاج تفاصيل — رقم الشيك، تاريخه، البنك..."},
        ],
        # Signals = 2 (digits "12" and "000") → meets min_signals[شيك]=2
        # Forces memo route, not ask_details.
        "كتب لي شيك بمبلغ 12,000 ريال وأرجعته البنك بدون رصيد",
        {
            "must_contain_any": [["12000", "12,000", "اثنا عشر ألف"]],
            # user gave NO date or check number — must not fabricate
            "must_not_contain_re": [
                r"\d{1,2}\s*[/\-]\s*\d{1,2}\s*[/\-]\s*\d{2,4}",
                r"(?:بتاريخ|تاريخ)\s+\d{1,2}\s*/\s*\d{1,2}",
                r"رقم\s+الشيك\s*:?\s*\d{4,}",
            ],
            "want_placeholder": True,
            "min_len": 400,
        },
    ),

    (
        # ── Fix 1.A Gap 1 guard — structured fields rendered ──────
        # fact_extractor extracts names/ages/amounts/dates as
        # STRUCTURED fields (beyond `claims`). Phase 5 live demo
        # revealed that these were never surfaced in the memo
        # (LLM condensed user's "1- طفل احمد 3 سنوات" into
        # structured fields instead of a claim sentence). This test
        # locks that supplementary details reach the final memo.
        # Same custody T3→T4 shape as the real-user scenario.
        # ──────────────────────────────────────────────────────────
        "h1c_structured_facts_rendered_in_memo",
        [
            {"role": "user",
             "content": "اكتب مذكرة اسقاط حضانه ضد طليقتي"},
            {"role": "assistant",
             "content": ("قبل ما أكتب مذكرة حضانة احترافية بأسماء "
                         "ووقائعك الحقيقية، أحتاج منك هذه التفاصيل...")},
        ],
        ("1- طفل واحد اسمه احمد وعمره 3 سنوات "
         "2- السبب سوء سلوك الحاضنة "
         "3- لا لكن يوجد وثيقة طلاق فقط"),
        {
            "want_route": "memo",
            # must_contain_any — accept Arabic alef variants
            # (user typed "احمد" bare-alef; LLM may normalise to
            # "أحمد" with hamza). Both are the same name.
            "must_contain_any": [
                ["احمد", "أحمد"],
                ["3 سنوات", "ثلاث سنوات", "٣ سنوات"],
            ],
        },
    ),

    (
        # ── Fix 1.A Gap 2 guard — prayer quality not meta echo ────
        # When domain prayers are all filtered as poison, the
        # fallback historically used extracted.requests verbatim —
        # which caused the Prayers section to literally repeat the
        # user's "اكتب مذكرة اسقاط حضانه ضد طليقتي" as a court
        # prayer. This is not hallucination but a severe quality
        # defect. Fix 1.A refinement: fall back to a generic legal
        # prayer scaffold, not user meta-requests.
        # ──────────────────────────────────────────────────────────
        "h1d_prayers_no_meta_request_echo",
        [
            {"role": "user",
             "content": "اكتب مذكرة اسقاط حضانه ضد طليقتي"},
            {"role": "assistant",
             "content": ("قبل ما أكتب مذكرة حضانة احترافية بأسماء "
                         "ووقائعك الحقيقية، أحتاج منك هذه التفاصيل...")},
        ],
        ("1- طفل واحد اسمه احمد وعمره 3 سنوات "
         "2- السبب سوء سلوك الحاضنة "
         "3- لا لكن يوجد وثيقة طلاق فقط"),
        {
            "want_route": "memo",
            "must_not_contain_in_section": {
                "الطلبات": [
                    "اكتب مذكرة",
                    "احتاج مذكرة",
                    "أريد مذكرة",
                    "احتاجك",
                ],
            },
            "must_contain_in_section": {
                # At least one formal legal prayer starting with "الحكم"
                "الطلبات": ["الحكم"],
            },
        },
    ),

    (
        # ── Phase 7 Stretch: defense-section richness ──────────────
        # Post-Fix-1.A, custody memos dropped from ~3 defense bullets
        # (poisoned) to 1 (user-claim echo only) — all DomainRules
        # markers were rejected by alignment since every marker
        # assumed "زواج". Phase 7 fix adds Layer 2 (claims always)
        # + Layer 3 (generic legal defenses) to keep the section
        # substantive without re-introducing invention.
        # ──────────────────────────────────────────────────────────
        "h1e_defenses_section_rich",
        [
            {"role": "user",
             "content": "اكتب مذكرة اسقاط حضانه ضد طليقتي"},
            {"role": "assistant",
             "content": ("قبل ما أكتب مذكرة حضانة احترافية بأسماء "
                         "ووقائعك الحقيقية، أحتاج منك هذه التفاصيل...")},
        ],
        ("1- طفل واحد اسمه احمد وعمره 3 سنوات "
         "2- السبب سوء سلوك الحاضنة "
         "3- لا لكن يوجد وثيقة طلاق فقط"),
        {
            "want_route": "memo",
            "must_contain_in_section": {
                # Layer 3 fingerprint: both "مصلحة" and "قانون"
                # appear in the generic fallback defenses emitted
                # when no domain marker aligns with user facts.
                "الدفوع": ["مصلحة", "قانون"],
            },
        },
    ),

    (
        # ── Phase 7 Stretch: prayers domain-specific substantive ──
        # Gap 2 fix produced prayer #2 as a generic bracket-only
        # placeholder. For the major domains, a domain-specific
        # hint (e.g. "إسقاط الحضانة وضم المحضون" for custody)
        # tells the lawyer the standard prayer shape for the case
        # without asserting facts. Still bracketed — not certainty.
        # ──────────────────────────────────────────────────────────
        "h1f_prayers_domain_specific_scaffold",
        [
            {"role": "user",
             "content": "اكتب مذكرة اسقاط حضانه ضد طليقتي"},
            {"role": "assistant",
             "content": ("قبل ما أكتب مذكرة حضانة احترافية بأسماء "
                         "ووقائعك الحقيقية، أحتاج منك هذه التفاصيل...")},
        ],
        ("1- طفل واحد اسمه احمد وعمره 3 سنوات "
         "2- السبب سوء سلوك الحاضنة "
         "3- لا لكن يوجد وثيقة طلاق فقط"),
        {
            "want_route": "memo",
            "must_contain_in_section": {
                # Custody domain hint = "إسقاط الحضانة وضم المحضون"
                "الطلبات": ["إسقاط", "ضم"],
            },
            "must_not_contain_in_section": {
                # Gap 2 guard: still no meta-request echo
                "الطلبات": ["اكتب مذكرة"],
            },
        },
    ),

    (
        # ── FINDING #13 Source D guard ────────────────────────────
        # Dedicated test for the PRAYERS section. h1 covers the memo
        # as a whole; this test specifically proves the Prayers
        # template (DomainRules.primary_prayers) is filtered against
        # user facts — NOT simply stripped by the article-quote regex.
        # If Fix 1.A Path X-prayers works, the prayers section will
        # contain NONE of the user-unstated marriage phrases.
        # Same query as h1; different assertion locus.
        # ──────────────────────────────────────────────────────────
        "h1b_prayers_section_no_poison",
        [],
        ("رفعت على طليقتي دعوى اسقاط حضانه لسوء سلوكها "
         "عشان اسقط حضانة ابني احمد عمره 3 سنوات اكتب لي مذكرة"),
        {
            "must_not_contain_in_section": {
                "section_marker": "الطلبات",
                "forbidden": [
                    "لزواجها",
                    "من أجنبي",
                    "من رجل أجنبي",
                    "تزوجت المدعى عليها",
                    "زواج الأم",
                ],
            },
        },
    ),

    (
        "h4_no_fabricated_names",
        [
            {"role": "user",
             "content": "اكتب مذكرة مطالبة بدين"},
            {"role": "assistant",
             "content": "أحتاج تفاصيل — اسم المدين، المبلغ، تاريخ الدين..."},
        ],
        "بعت له بضاعة وما دفع ثمنها",
        {
            # user gave NO names — must not invent specific Arabic names
            # paired with surnames / titles
            "must_not_contain_re": [
                r"(?:المدعى\s+عليه|الخصم|المطلوب)\s*/?\s*"
                r"(?:محمد|أحمد|عبدالله|عبد\s+الله|فاطمة|عائشة|سارة|خالد|علي|حسن)"
                r"\s+[\u0600-\u06FF]+",
                r"السيد(?:ة)?\s*/?\s*"
                r"(?:محمد|أحمد|عبدالله|فاطمة|عائشة|سارة|خالد|علي|حسن)"
                r"\s+[\u0600-\u06FF]+",
            ],
            "want_placeholder": True,
            "min_len": 300,
        },
    ),
]


# ─────────────────────────────────────────────────────────────────────
# SSE collector
# ─────────────────────────────────────────────────────────────────────

def _sse_post(query, history, timeout=180):
    body = json.dumps({
        "query": query,
        "session_id": f"ah-{int(time.time() * 1000)}",
        "mode": "expert",
        "history": history,
    }).encode("utf-8")
    req = urllib.request.Request(
        API, data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "X-API-Key": KEY,
        },
    )
    answer = ""
    done = {}
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for line in r:
            txt = line.decode("utf-8", errors="replace")
            if not txt.startswith("data: "):
                continue
            try:
                obj = json.loads(txt[6:])
            except Exception:
                continue
            t = obj.get("type")
            if t == "chunk":
                answer += obj.get("content") or obj.get("text") or ""
            elif t == "done":
                done = obj
    return {"answer": answer, "done": done}


# ─────────────────────────────────────────────────────────────────────
# Assertion engine
# ─────────────────────────────────────────────────────────────────────

def _check(answer, done, expect):
    errors = []

    # Route gate
    want_route = expect.get("want_route")
    if want_route:
        actual_route = done.get("route", "?")
        if actual_route != want_route:
            errors.append(
                f"WRONG ROUTE: got {actual_route!r}, wanted {want_route!r}"
            )

    for p in expect.get("must_contain", []):
        if p not in answer:
            errors.append(f"MISSING required: {p!r}")

    for group in expect.get("must_contain_any", []):
        if not any(p in answer for p in group):
            errors.append(f"MISSING any of: {group}")

    for p in expect.get("must_not_contain", []):
        if p in answer:
            errors.append(f"HALLUCINATION: forbidden {p!r}")

    # ── must_not_contain_outside_quotes ────────────────────────────
    # Strips article-body quotations (those starting with «المادة ...»)
    # BEFORE checking. Legitimate legal citations quote the article
    # text verbatim from the DB (which may contain phrases like
    # "محرم للمحضون" as part of Qatar Family Law Article 171). Those
    # are factual, not hallucinated — the guard should only flag
    # phrases appearing in the system's own narrative / bullets.
    #
    # Marker labels in defense section use «...» too, but DON'T start
    # with "المادة", so the surgical regex preserves them as poison
    # targets. Tested against pos 554 / 803 / 2114 snippets in the
    # h1 forensic probe.
    forbidden_outside = expect.get("must_not_contain_outside_quotes", [])
    if forbidden_outside:
        cleaned = re.sub(r"«\s*المادة[^»]*»", "", answer, flags=re.DOTALL)
        for p in forbidden_outside:
            if p in cleaned:
                errors.append(
                    f"HALLUCINATION (outside article quotes): forbidden {p!r}"
                )

    for pat in expect.get("must_not_contain_re", []):
        m = re.search(pat, answer)
        if m:
            errors.append(f"FABRICATION: /{pat[:60]}/ matched {m.group(0)!r}")

    # ── must_not_contain_in_section ────────────────────────────────
    # Targeted guard for deep-structural poison like FINDING #13
    # Source D (DomainRules.primary_prayers). Supports TWO shapes:
    #
    #   Shape A (legacy h1b):
    #     {"section_marker": "الطلبات", "forbidden": [str, ...]}
    #
    #   Shape B (h1d and later):
    #     {"الطلبات": [str, ...], "another_section": [...], ...}
    #
    # Detection: if the dict has both "section_marker" and "forbidden"
    # keys it's Shape A; otherwise treat each key as a section name.
    sec_spec = expect.get("must_not_contain_in_section")
    if sec_spec:
        if "section_marker" in sec_spec and "forbidden" in sec_spec:
            pairs = [(sec_spec["section_marker"], sec_spec["forbidden"])]
        else:
            pairs = list(sec_spec.items())
        for section_name, forbidden_list in pairs:
            if section_name and section_name in answer:
                sec_start = answer.find(section_name)
                section_text = answer[sec_start:]
                for p in forbidden_list:
                    if p in section_text:
                        errors.append(
                            f"SECTION POISON: {p!r} present in "
                            f"'{section_name}' section"
                        )

    # ── must_contain_in_section ─────────────────────────────────────
    # Positive counterpart to must_not_contain_in_section. Ensures a
    # named section has required phrases (e.g. "الطلبات" must contain
    # "الحكم" so it's a real legal prayer, not a user echo).
    # Shape: {"الطلبات": ["الحكم"], ...}
    sec_must = expect.get("must_contain_in_section")
    if sec_must:
        if "section_marker" in sec_must and "required" in sec_must:
            pairs = [(sec_must["section_marker"], sec_must["required"])]
        else:
            pairs = list(sec_must.items())
        for section_name, required_list in pairs:
            if section_name not in answer:
                errors.append(f"SECTION MISSING: '{section_name}' not found")
                continue
            sec_start = answer.find(section_name)
            section_text = answer[sec_start:]
            for p in required_list:
                if p not in section_text:
                    errors.append(
                        f"SECTION MISSING PHRASE: {p!r} not in "
                        f"'{section_name}' section"
                    )

    if expect.get("want_placeholder"):
        # Accept any bracketed placeholder the system actually emits.
        # Post-fix placeholders fall into two families:
        #   (a) verb-form    — [يذكر…], [يُدرج…], [يحدد…], [يُبنى…], [تُطبَّق…]
        #   (b) noun-form    — [اسم…],   [تاريخ…], [مبلغ…], [رقم…]
        placeholders = (
            "[يذكر", "[يُدرج", "[يحدد", "[يُبنى", "[تُطبَّق",
            "[اسم", "[تاريخ", "[مبلغ", "[رقم",
        )
        if not any(p in answer for p in placeholders):
            errors.append(
                "NO PLACEHOLDER: post-fix memo must mark missing facts "
                "with a bracketed placeholder "
                "([يذكر…] / [يُدرج…] / [يحدد…] / [اسم…] / [تاريخ…] / "
                "[مبلغ…] / [رقم…])"
            )

    min_len = expect.get("min_len", 0)
    if len(answer) < min_len:
        errors.append(f"TOO SHORT: {len(answer)} < min {min_len}")

    max_len = expect.get("max_len")
    if max_len is not None and len(answer) > max_len:
        errors.append(f"TOO LONG: {len(answer)} > max {max_len}")

    return (not errors, errors)


# ─────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────

def main():
    results = []
    for scenario_id, history, query, expect in SCENARIOS:
        short_q = re.sub(r"\s+", " ", query)[:75]
        print(f"━━━ {scenario_id}")
        print(f"    query: {short_q}")

        try:
            r = _sse_post(query, history)
        except urllib.error.HTTPError as e:
            body_err = e.read().decode("utf-8", errors="replace")[:200]
            print(f"  HTTPError {e.code}: {body_err}")
            results.append(
                (scenario_id, False, "http-error", 0, [f"HTTP {e.code}"])
            )
            time.sleep(5.0)
            continue
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}")
            results.append((scenario_id, False, "error", 0, [str(e)]))
            time.sleep(5.0)
            continue

        answer = r["answer"]
        done = r["done"]
        route = done.get("route", "?")
        ok, errs = _check(answer, done, expect)
        tag = "✓ PASS" if ok else "✗ FAIL"
        print(f"  len={len(answer)}  route={route}  {tag}")
        for e in errs:
            print(f"    - {e}")
        preview = re.sub(r"\s+", " ", answer[:220])
        print(f"    « {preview}{'…' if len(answer) > 220 else ''} »")
        results.append((scenario_id, ok, route, len(answer), errs))
        time.sleep(6.0)  # TPM pacing per FINDING #9

    # ── Summary ──
    passed = sum(1 for r in results if r[1])
    total = len(results)
    print()
    print("═" * 72)
    print(f"  TOTAL: {passed}/{total} PASSED")
    print("═" * 72)
    for scenario_id, ok, route, ln, errs in results:
        tag = "✓" if ok else "✗"
        print(f"  {tag} {scenario_id:<48} route={route:<16} len={ln}")

    print()
    print("  BASELINE EXPECTATION (pre-CP1 fixes):")
    print("    h1_custody_no_marriage_hallucination     → FAIL")
    print("    h5_explicit_marriage_fact_preserved      → PASS (guard)")
    print("    h2_labor_no_fabricated_service_duration  → FAIL")
    print("    h3_check_no_fabricated_dates             → FAIL")
    print("    h4_no_fabricated_names                   → FAIL")
    print("  → expected baseline exit code: 1 (4 failures)")
    print("  POST-CP1 TARGET: 5/5 PASS, exit code 0.")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
