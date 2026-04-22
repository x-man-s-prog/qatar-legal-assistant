# FINDINGS — Qatar Legal Assistant "Mizan" — Phase 2 Layer 2

## 1. Egyptian vs Qatari Legal Terminology

Qatari legal corpus uses distinct terminology from Egyptian fiqh literature.
Queries using Egyptian phrasing return zero matches despite content existing under Qatari phrasing.

**Confirmed mappings (validated via DB hit counts):**

| Egyptian | Qatari | Impact |
|----------|--------|--------|
| الطعن بالنقض | الطعن بالتمييز | 0 → 532 hits |
| المسؤولية التقصيرية | الفعل الضار | 0 → 10 hits (Art. 199+) |
| الضرر المعنوي / تعويض أدبي | الضرر الأدبي + تقدير التعويض | 0 → 138 hits |
| رد الاعتبار | NOT APPLICABLE in cassation | 0 hits (rehabilitation doesn't reach Tameez) |

**Rule of thumb:** Every new query/concept must be validated against DB hit counts before inclusion in prompts, tests, or documentation.

## 2. Tameez 'عام' Domain Structure

Contrary to fiqh taxonomy, 'عام' in Qatari Tameez DB ≠ administrative/constitutional.

**Actual distribution (72 chunks, 0.6% of corpus):**
- ~60% personal status (nafaqa, hadana, family)
- ~15% court organization (chamber assignment)
- ~15% procedural (public order rules of evidence)
- ~10% royal decrees (appointments)

Administrative/constitutional matters land in `مدني`, not `عام`.

**Implication for domain routing:** G2 defensive rule in precedent_linker handles this correctly (when corpus_domain=None AND civil concepts ≥2 → force مدني).

## 3. Embedding Model Limitation (nomic-embed-text-v1)

**Measured on sample_20 (CP3.4 sweep):**
- precision@3 = 0.53 (Category A, strong gold)
- silence_C = 0.00 at threshold ≤ 0.76 (false positives for unanswerable queries)
- 4 flat-embedding cases: same chunk matches ≥3 unrelated topics (similarity > 0.84)

**Root cause:** Arabic legal prose is under-represented in nomic training. Model cannot distinguish between "تقادم جنائي" and "تقادم مدني" in embedding space.

**Decided resolution path (NOT a patch):**
1. Full embedding replacement to BAAI/bge-m3 + hybrid retrieval (BM25 + Vector + RRF).
2. Blocked by hardware: requires ≥2GB free RAM (laptop has 8GB total, 0.5GB free after Windows).
3. Scheduled for: dedicated session post-hardware upgrade or cloud migration.

**Current behavior is ACCEPTABLE because:**
- System returns real precedents (11.4K rulings available).
- Hallucination guard prevents fake case number citations.
- Users are legal professionals who read and judge rulings themselves.
- Baseline measured (0.53) for future comparison.

## 4. Redundant Retrieval Bug (Fixed in CP3)

q6 latency investigation revealed: `_log_augmentation` was re-embedding + re-querying to populate `n_before` field purely for logging.

**Fix:** Pass `n_before=None` when not genuinely measured. Log shows `before=skipped Δ=?`.

**Impact:** -50% linker work for augmented queries. p90 latency: 3782ms → 2359ms.

**Invariant locked:** test_p14_no_redundant_embedding_for_logging.

## 5. Skip Logic for Definitional Queries

Short definitional queries ("ما عقوبة السرقة؟") don't benefit from precedents — they need article text.

**Rule (pure function `_should_skip_linker`):**
- Has digits OR case keywords → never skip
- Starts with definitional prefix ("ما هو/ما هي/عقوبة") → skip (any length)
- Has concepts (non-empty) → don't skip
- Word count > 6 → don't skip
- All 4 skip conditions hold → skip

**Impact:** Simple query latency: 700ms → 0ms. Token cost: 142 → 0.

## 6. Sample_20 Evaluation Sample

20 curated queries with ground truth case_numbers extracted manually from Tameez chunks.

**Distribution:** 12 مدني + 8 جنائي + 0 عام (عام excluded — insufficient sub-sampling support per Finding #2).

**Categories:**
- A (5): strong gold — s1, s2, s4, s12_new, s16
- B (8): medium gold — s3, s5, s7, s11, s13_new, s14_new, s19_civil, s22
- C (7): zero-hit negative tests — s6, s8, s9, s10, s15, s20_civil, s21_new

**File:** /app/tests/phase2/sample_20.json

**Use:** Future regression evaluation when embedding upgrade is applied.

## 7. Async Pool Binding in Test Harness

**Discovery (pre-Layer 3 verification):**
Commit ff7b4f3 claimed 15/15 phase-2 tests passing. Re-verification
showed 12/15 under pytest-asyncio — 3 tests failed due to event
loop cross-binding in asyncpg pool.

**Not a patch — fixed at source:**
- tests/phase2/conftest.py manages event loop lifecycle per test
- _reset_pool_state() helper cleans pool state between tests
- Production runtime unaffected (verified by 50 HTTP integration tests)

**Lesson captured:** Claims in commit messages must be verified
under the claimed conditions, not assumed from partial runs.
Session protocol updated: before any commit claiming N/N tests,
run full suite in clean environment and capture output.

## 8. Async Redis Client Introduction

**Context:** Phase 2 Layer 3 (Case Memory) required async Redis access.
Pre-flight check (CP1.1) revealed no canonical async client existed.

**Decision:** Create `core/redis_client.py` as canonical async getter.

**Scope (intentionally narrow):**
- Used exclusively by `case_memory/store.py` in this session.
- Existing sync path in `query_router._get_redis()` untouched.
- Different key namespaces prevent interference:
  - Sync: `answer_memory:*` (Layer 1, legacy)
  - Async: `case:*`, `case_index:*` (Layer 3, new)

**Pattern mirrors asyncpg handling in Layer 2:**
- Singleton per (db, event_loop) pair.
- Test-only `_reset_redis_pool_for_loop()` for pytest isolation.
- Lazy creation with PING verification.

**Future migration (separate session):** sync usage in query_router
can eventually migrate to this module. Not done now — out of scope.

**Not a patch:** architectural addition, not workaround.

## 9. TPM Saturation in Integration Test Batches

**Observed during CP2 Parts B, C, and D:**
- Single-test isolation: all passing consistently.
- Back-to-back 38-test regression batch: rotating failures.
- Pattern: different tests fail each run (h5/h6/h7/h8/h9/f5/f6 rotate).
- Isolation probes confirm: each "failed" test returns 17-22KB valid response
  when run alone.

**Root cause:** OpenAI API TPM (tokens per minute) quota saturation
during rapid-fire batch execution.

**Not a code regression. Not a test flakiness bug.**

**Protocol (documented for future sessions):**
- After 3 retry attempts showing rotation pattern → declare TPM artifact.
- Isolation probe the "worst offender" test → confirm 17KB+ response.
- Proceed. Do NOT modify tests or code to mask TPM artifacts.

**Long-term resolution path:**
- Implement per-session TPM-aware test scheduling (cooldowns between suites).
- Or: migrate integration tests to record-replay mode (cached LLM responses).
- Scheduled for: dedicated test-infrastructure session, not inline.

**Evidence:**
- h9 isolation probe: 22,864 bytes response, "مكافأة نهاية الخدمة" present in first sentence.
- h7 isolation probe: 19,399 bytes response, concept "حجية الأمر المقضي" injected.
- h8 isolation probe: 17,160 bytes response, complete answer.
- f5 isolation probe: 17,575 bytes response, contains "10"/"14"/"سنوات".

## 10. Cached Redis Client PING Verification

**Design choice in `core/redis_client.py`:** Every `get_redis_client()` call
PINGs the cached client before returning.

**Rationale:**
- Cached clients can become stale after inactivity (connection timeout,
  network hiccup, Redis restart).
- PING cost: <1ms locally.
- Alternative (skip PING) risks "Connection reset by peer" in hot path,
  which is MUCH more expensive to recover from than the PING cost.

**Not a workaround — defensive reliability feature.**

**Validated:**
- 30/30 phase3 tests pass in 1.27s total — PING overhead negligible.
- Zero "Event loop is closed" errors in production path during CP2 runs.

## 11. Memo Test Coverage Gap — Long Conversations

**Discovery (user-reported production regression):**
A real user submitted 10 turns across a custody-memo session. Starting
at turn 4 the system returned "شرح عام عن الحضانة" instead of a memo,
and by turn 10 had lost context entirely. Memo tests `c1-c8` all
continued to pass during this incident, so the bug was invisible to
CI.

**Two compounding root causes:**

1. **Sliding window `history[-8:]` in `handle_memo_smart`.**
   Signal-sufficiency was computed only over the last 8 messages. In
   a 10-turn conversation the rich-signal turn (T4: names, numbers,
   dates) fell out of that window by T9, so the handler re-asked for
   details mid-memo — identical to the user's "اكتب بالمعلومات
   المتوفرة" final turn returning ``memo_ask_details``.

2. **`phase0_router._MEMO_TRIGGERS` anchored on imperative "اكتب".**
   The list has entries like `"اكتب مذكرة"` and `"احتاج مذكرة"`, but
   misses `"تكتب"` (present tense) and `"احتاج منك تكتب"` variants.
   The query "احتاجك تكتب لي مذكرة حضانة" routes to ``general`` under
   the old matcher, which then produces a full LLM answer and drops
   all memo context.

**Why c1-c8 passed while production failed:**
All c1-c8 histories are ≤ 4 messages — the 8-msg window always contains
the signal-bearing turn. None of them exercise the verb-variant phrasing
either. The tests were correct for their scope but their scope was too
narrow. **The test suite proved the happy path, not the failure surface.**

**Not a patch — root-cause fixes in two places:**

- New ``_compute_memo_signals(history, current_query, topic)`` sweeps
  the ENTIRE history (capped by the session LRU, ~50 turns) and sums
  signals per source. ``_count_signals`` is retained unchanged for
  backward compatibility with tests that exercise the single-blob
  path.
- New three-factor gate ``_is_force_memo_request(query)`` fires when
  the query contains a memo VERB **and** a memo NOUN **and** a topic
  keyword from ``DOMAIN_KEYWORDS``. No parallel topic list — keywords
  are sourced from ``core.metadata_filter.DOMAIN_KEYWORDS`` so adding
  a new topic there flows to memo detection automatically.

**Test coverage closed (must remain green):**
- ``tests_memo_continuity_c9_long.py`` — the exact 10-turn scenario
  the user hit. 10/10 assertions.
- ``tests_memo_force_intent.py`` — verb-variant + regression guard.
  2/2 assertions.
- ``tests/test_memo_signal_computation.py`` — unit contract on the new
  full-history sweep. 2/2 assertions.

**Lesson captured — protocol update:**
Memo-path test fixtures must include at least one scenario with
≥ 10 turns where the rich-signal turn is in the first half of the
history, followed by short follow-up nags. Any future memo refactor
that reintroduces a sliding window will break these tests.

## 12. Server-Side Memo Resilience to UI History Bug

Discovered during live production testing (user session, Turn 3-10).
Three compounding root causes surfaced despite FINDING #11's fix
already being deployed.

### Symptoms
- User typed "اكتب مذكرة إسقاط حضانة" five-plus times explicitly.
- System variously: asked for details (correct once), explained
  custody law without writing (wrong), produced a generic procedural
  checklist ("الأطراف، الوقائع، المستندات…") without a topic ask (wrong).
- Context appeared lost between turns even though the client-side
  conversation UI displayed the full history.

### Three compounding root causes

**Cause A — ال-prefix gap in ``is_memo_request``:**
``_MEMO_TRIGGERS`` used naive ``t in q`` substring checks. The literal
substring "اكتب مذكرة" does not appear inside "اكتب المذكرة" because
the definite article ``ال`` interrupts the match. Phase0 therefore
routed the request to ``general`` instead of ``memo``.

**Fix A (this commit):** ``_matches_memo_trigger`` with a cached
``(?:ال)?word`` regex per trigger word. Same root-cause pattern as
``core/case_memory/entity_extractor._match_word`` shipped in CP2
Part B. ``_MEMO_TRIGGERS`` tuple itself is unchanged.

**Cause B — UI-side history truncation:**
Production logs confirmed UI sends an empty or truncated ``history``
array on ``POST /api/v1/stream/``. ``memo_continuation`` gates A/B/C
all require ``len(history) >= 2`` and silently skip otherwise. The
server routed memo-worthy queries to ``general`` with zero context.

Server-side mitigation (this commit): Fix A makes phase0 robust
to the ``ال``-prefix issue, so even without history the request
reaches ``handle_memo_smart``. UI-side fix is scheduled for a
dedicated FE/UI session.

**Cause C — Silent generic fallback in ``_build_generic_skeleton``:**
When ``handle_memo_smart`` received a memo request with ``topic=="عام"``
and no history context, it fell through to ``runtime_v2``'s
``_build_generic_skeleton``, which produced a hardcoded procedural
ask ("الأطراف، الوقائع، المستندات، الطلب…") without ever asking
which kind of memo. Users parsed this as "the system didn't
understand I wanted a memo about my case."

**Fix B (this commit):** ``handle_memo_smart`` now intercepts BEFORE
``runtime_v2`` is reached when all three conditions hold:
  1. ``topic == "عام"`` — memo-topic map found nothing
  2. ``len(history or []) < 2`` — no session context to stand on
  3. ``not _has_memo_topic(query)`` — query has no ``DOMAIN_KEYWORDS`` hint

When all three hold, we emit a new ``memo_ask_topic`` route with a
compact Arabic prompt that lists the top family options (حضانة /
نفقة / خلع / فصل تعسفي / إيجار / شيك / سرقة / أخرى). ``runtime_v2``'s
generic skeleton path is otherwise untouched — it still serves the
cases where drafting is genuinely appropriate without clear topic.

### Dual topic-detection systems — scheduled

Reconnaissance during Fix B design revealed two independent topic-
detection paths:
  - ``_MEMO_TOPIC_MAP`` in ``routers/query_router.py`` — 12 topics,
    default ``"عام"``.
  - ``_GENERIC_CUES`` in ``core/runtime_v2/pipeline.py`` — 6
    families, default ``None``.

These should eventually unify into a single authoritative topic
registry. Out of scope for this fix — the two systems correctly
serve different call paths today.

### Test coverage closed

Added ``tests/test_phase0_memo_al_prefix.py`` (23 pytest assertions)
and ``tests_memo_no_history_al.py`` (2 HTTP scenarios). Both were
test-first: written to FAIL against the current code, then the fix
landed, then they PASS. They are the permanent guard against both
the ``ال``-prefix regression and the silent-generic-memo regression.

### Protocol update

Memo-path test fixtures MUST include:
  - ``ال``-prefix variants alongside bare-prefix tests.
  - Empty-history scenarios alongside full-history tests.
  - Post-fix live HTTP verification (logs + response inspection),
    not just pytest green.

## 13. Hallucination Template Layers — FIVE origin points (CP1)

### Discovery
CP1 investigation into a user-reported regression ("system invented
'زواج الأم من أجنبي' when user only said 'سوء سلوك'") revealed that
hallucinated facts in generated memos do not come from a single
source — they originate from **five distinct template layers**, each
invisible until the layer above was fixed. Every layer that surfaces
text into LLM context OR the deterministic composer output is a
potential hallucination vector.

### The Five Layers

1. **EXPERT_SYSTEM few-shot examples** (``core/prompts.py``)
   - Fix 1.B: three examples under "مثال صحيح" and "الجانب الإنساني"
     all featured "زواج الأم من أجنبي" as the canonical custody-
     removal ground. LLM pattern-completed this into every custody
     memo regardless of user facts. Plus a fourth poison in the
     "اسأل قبل ما تصيغ" block listing "متى تزوجت الأم?" as the
     default custody question.
   - Replacement: three neutral placeholder-first examples
     (custody / labour / check) + one open-ended custody ask-template.

2. **``_MEMO_GAPS`` ask-text** (``routers/query_router.py``)
   - Fix 1.B: six ask-details questions contained parenthetical
     enumerated examples like ``"(زواج الأم بأجنبي، إهمال، سوء سلوك)?"``.
     Because the ask-text goes into session history verbatim, the LLM
     sees all three options on subsequent turns and can pattern-match
     any of them into the eventual memo.
   - Replacement: open-ended phrasing, no enumerated reasons, each
     question self-contained (≥ 8 words).

3. **``DomainRules.facts_template``** (``core/runtime_v2/domains.py``)
   - Fix 1.A: composer.``_facts_block`` merged user claims with a
     ``facts_template`` tuple verbatim — domain templates like
     ``"تزوّجت المُدَّعى عليها من رجل أجنبي عن المحضون بتاريخ [يُدرج]..."``
     injected as if they were user-stated facts.
   - Replacement: ``extract_user_facts_sync`` gates. When extractor
     produces claims, facts_template is SKIPPED entirely. When
     extractor is empty, template items render as bracketed
     ``[placeholder]`` only — never as assertions.

4. **``DomainRules.paths.markers``** (same module)
   - Fix 1.A Path X: composer.``_defenses_block`` emitted every
     marker's label as a defense element, producing
     ``"يُتمسّك بتحقق عنصر «زواج الأم الحاضنة بعد الطلاق»"`` in
     custody memos whose user said only "سوء سلوك".
   - Replacement: ``_marker_aligned_with_user`` filters markers by
     keyword + label-word overlap with extracted user text
     (``_STOP_WORDS`` filter prevents trivial matches). Only aligned
     markers render; misaligned markers do not enter the memo.

5. **``DomainRules.primary_prayers``** (same module) — **DISCOVERED
   LATE; would have been MASKED by a broader regex patch had the
   "probe before A3" rule not been enforced**
   - Fix 1.A Path X-prayers: composer.``_prayers_block`` emitted
     every domain prayer verbatim, including
     ``"الحكم بإسقاط حضانة ... لزواجها من رجل أجنبي عن المحضون"``.
   - Replacement: ``_prayer_aligned_with_user`` + tight
     ``_PRAYER_POISON_SIGNALS`` blacklist auto-rejects prayers that
     ASSERT unstated facts. Prayers with no significant words
     (pure procedural) still pass.

### CP1 Refinements (same commit — quality gates beyond the 5 layers)

Beyond closing the 5 poison layers, Phase 6+7 closed three memo-
quality gaps surfaced by the live user demo:

**Gap 1 (Phase 6) — ``_facts_block`` rendered only ``claims``.**
The fact extractor's structured fields (``names``, ``ages``,
``amounts``, ``dates``) never reached the memo text. Fix: emit
labelled enrichment bullets ("الأطراف المذكورون: …",
"الأعمار المذكورة: …") after the claims loop.

**Gap 2 (Phase 6) — ``_prayers_block`` fallback echoed user's
meta-request.** When all domain prayers were filtered as poison,
the fallback used ``extracted.requests`` verbatim — producing
prayers like ``"1. اكتب مذكرة اسقاط حضانه ضد طليقتي"``. Fix:
deterministic three-part legal scaffold (accept-plea + placeholder
substantive + costs). Never uses ``extracted.requests``.

**Phase 7 defenses enrichment.** Single-layer output dropped from
3 (poisoned) bullets to 1 (claim echo) after Fix 1.A Path X. Fix:
three-layer output — (1) aligned markers when any, (2) user claims
always alongside, (3) generic legal defenses as fallback
("يُتمسّك بما تقرّره نصوص قانون …", "يُتمسّك بأن مصلحة …").

**Phase 7 prayer domain hints.** Added ``_PRAYER_DOMAIN_HINTS``
dict mapping ``DomainKey.value`` → standard substantive prayer
shape (e.g. "إسقاط الحضانة وضم المحضون" for custody). Used in the
generic fallback's prayer #2 slot, wrapped in brackets with
"وفق ما يراه المحامي" qualifier so it reads as shape suggestion,
not asserted request.

### Root-Cause Rule — Probe Before Patch

When a filter fails to catch poison, ALWAYS probe the actual output
before broadening the filter. A broader filter silently masks
deeper layers. During CP1:

  - Fix 1.B closed Layers 1 + 2 → probe revealed Layer 3.
  - Fix 1.A (facts_block) closed Layer 3 → regression revealed
    Layer 4 was also contributing.
  - Fix 1.A Path X closed Layer 4 → FORENSIC PROBE (not a broader
    regex) revealed Layer 5 in prayers.

If we had applied the proposed "broader ``«...»`` regex" (Fix A3),
Layer 5 would have been masked indefinitely — every custody memo
would silently ship "لزواجها من رجل أجنبي عن المحضون" in the
Prayers section.

### Protocol Update — Domain Template Audit

Before deploying new ``DomainRules`` entries for any topic:

- [ ] ``facts_template``: no specific reasons / amounts / dates /
      names. Only legal-language neutral frame.
- [ ] ``paths.markers``: each marker has both a ``label`` and
      ``keywords`` tuple that actually overlaps with likely user
      wording (not just the label's stop-words).
- [ ] ``primary_prayers``: gate-compatible or marked as
      default-generic (procedural only).
- [ ] ``_PRAYER_POISON_SIGNALS`` updated if the domain introduces
      a new concrete factual assertion that would need to be
      auto-rejected.
- [ ] Test scenario where user facts CONTRADICT the template
      (not just confirm it) is green.

### Scheduled Follow-up

- Fix 1.D (CP1 commit #2): metadata strip
  ("تاريخ بدء العمل : DD/MM/YYYY") from article citations in
  ``_legal_basis_block``.
- CP2: Article sub-clause filtering against user facts (full Fix 1.D).
- CP3: LLM pre-generation guard (Fix 1.C) as defense-in-depth.
- Future: Domain Template Audit tool scanning ``DomainRules`` for
  common poison patterns automatically.

## 14. Context Propagation Across Memo Turns (CP4)

### Discovery
CP1 closed hallucination on its five template layers. CP4 surfaced
three ORTHOGONAL failures when the user ran a realistic multi-turn
session after the CP1 deploy:

  T1: "ما هي عقوبات المرور"                      → general
  T2: "اكتب لي مذكرة اسقاط حضانه ضد طليقتي"     → memo_ask_details  ✓
  T3: "1- احمد 3 سنوات  2- سوء سلوكها ...
       3- لا لكن يوجد وثيقة طلاق بتاريخ ..."      → general  ✗ (should be memo)
  T4: "طيب اكتب المذكرة"                          → memo_ask_topic ✗ (lost topic)
  T5: "ذكرت الموضوع في الرسالة السابقة"         → "لا أملك تفاصيل" ✗
  T6: "ما هي عقوبة تركيب اصوات مزعجة"            → flag-insult penalties ✗
  T7: "ما هي العقوبة بالضبط"                     → flag-insult penalties ✗

Three distinct systemic failures:

### Cause A — Numbered-list details missed by Gates A/B/C

Existing memo-continuation gates in ``query_stream``:
- Gate A: matches memo-ask indicators in the FULL history blob.
- Gate B: matches memo keyword in prior user + short command now.
- Gate C: matches memo keyword in CURRENT query.

T3 is a structured response to T2's ask_details, but:
- It contains NO memo keyword (Gate C miss).
- T2 was a user memo request, but T3 is neither short nor a
  short-command match (Gate B miss).
- Gate A should have fired but the UI-truncation issue
  (FINDING #12 Cause B) means the server does NOT always see
  T2's assistant text in ``req.history``.

**Fix 1 (Gate D) — ``_is_memo_details_response`` in
``routers/query_router.py``.** Pure predicate:
  1. Most recent assistant message contains a memo-ask indicator.
  2. Current query is either a numbered list (``1-``, ``1.``),
     multi-detail (``≥ 2`` newlines or Arabic commas), or a
     direct-answer starter (نعم / اسمه / الراتب / ...).
  3. Fresh-question prefixes (``ما هي عقوبة`` / ``كيف`` / ...)
     auto-disqualify the query — critical defence against T6-type
     over-trigger after a session already held a memo exchange.

Wired directly after Gates A-C, before phase0 routing.

### Cause B — Session topic lost after the ask-details turn

``handle_memo_smart`` detects the memo topic on every call from the
current query alone. When the user types ``"اكتب المذكرة"`` as a
standalone follow-up:
- ``_detect_memo_topic`` returns ``"عام"`` (no topic keyword).
- The history-walk recovery looks at prior USER messages, but the
  earliest user message that MENTIONED a topic is T2; the
  ``memo_continuation`` gate already fired on its own, so T4
  enters ``handle_memo_smart`` fresh. The recovery walk then
  looks at short nags in user history and misses the concrete
  topic established in T2.
- The ``ask_topic_gen`` branch fires → topic is asked again.

**Fix 2 (session topic memory) — new
``core/session_topic_memory.py`` module.** Redis-backed store
(db=2, TTL 1h) with:

- ``set_session_topic(sid, topic)`` / ``get_session_topic(sid)``
  async primaries.
- ``set_session_topic_sync(sid, topic)`` /
  ``get_session_topic_sync(sid)`` sync wrappers via the proven
  ``_corpus_bg`` background loop.
- Refuses to store ``"عام"``: the sentinel "no topic".
- All Redis failures → warning log + ``None``/``False``. Never
  raises. Pre-CP4 behaviour is the safe degraded path.

Integration in ``handle_memo_smart``:
1. On entry: try ``get_session_topic_sync(sid)``. If non-empty,
   prefer it over the "عام" fallback of ``_detect_memo_topic``.
2. After topic is decided: if concrete, call
   ``set_session_topic_sync(sid, topic)``.
3. The ``ask_topic_gen`` branch now carries a fourth guard: skip
   the topic-ask if the session already holds a stored topic
   (defence in depth — the merge in step 1 already handles it).

### Cause C — Irrelevant criminal chunks for sub-domain queries

``_filter_chunks_by_domain`` operates on coarse buckets:
criminal / labor / family / commercial. A traffic-noise query like
``"ما هي عقوبة تركيب اصوات مزعجة على السيارة"`` contains ``"عقوبة"``
→ classified as criminal → all criminal chunks pass, including
flag-insult, cyber-crimes, and hiding-criminals.

**Fix 3 (sub-domain relevance filter) — adds a second narrower
pass in ``handle_general``.** New ``_detect_query_subdomain`` and
``_filter_retrieved_chunks_by_subdomain`` in
``routers/query_router.py``. Signals:

- ``_TRAFFIC_SIGNALS`` (traffic law specific)
- ``_SUBDOMAIN_LAW_PATTERNS``: {"traffic": ("المرور","مرور"), ...}

When a sub-domain is detected, ``law_name`` on each retrieved
chunk must match the sub-domain pattern to survive. If the
filter produces an EMPTY set after sub-domain narrowing, the
handler flips into Fix 4's degradation path (not an unfiltered
fallback).

### Cause D — Hallucinated answers from weak retrieval matches

Before CP4, when the retrieval returned nothing relevant, the LLM
was handed whatever it got and invented answers from weak matches.

**Fix 4 (degradation path) — explicit honest response.** When Fix
3's sub-domain filter empties ``sources``, ``handle_general``
short-circuits into a polite degradation message:

> "لا تتوفر لديّ نصوص قانونية محددة تجيب على سؤالك بدقة في
>  الوقت الحالي. موضوع استفسارك يتعلق بـ... وهو مجال لم تُسترجع
>  له نصوص مباشرة. أنصحك بالرجوع إلى ..."

Route tag: ``general_degraded``. No LLM call. Clients can surface
a subtle UI hint. No hallucination path.

### The Fresh-Question Override

CP4 also surfaces a subtle FEEDBACK between Gates A/B and
long-session state: after a memo cycle, the history blob keeps
matching memo-ask indicators forever, so Gates A/B would route
every subsequent turn to the memo handler — including pivots
to unrelated factual questions.

Placed BEFORE the Gate A/B/C/D cluster:

    _FRESH_Q_PREFIXES = (
        "ما هي عقوبة", "ما عقوبة", "ما هي العقوبة",
        "ما الفرق", "كيف ", "أين ", "متى ", "هل ", ...
    )
    if query starts with any prefix → ALL memo gates are skipped.

Safe because the same prefixes are also excluded inside Gate D
itself (``_GATE_D_FRESH_QUESTION_PREFIXES``).

### Test Coverage

- ``tests/test_session_topic_memory.py`` — 5 unit tests covering
  the async/sync API, "عام" rejection, missing-session, overwrite.
- ``tests/test_gate_d_memo_details.py`` — 6 unit tests covering
  numbered list, multi-comma, direct-answer starter, no-prior-ask,
  empty history, unrelated-query (negative).
- ``tests_context_propagation.py`` — 14-assertion integration
  suite replaying the exact production 7-turn scenario.

### Protocol Update

Multi-turn session tests must include at least one **topic pivot**
— e.g. a traffic/general question AFTER a memo turn — so that
memo-continuation gates cannot silently swallow future standalone
questions. Gate D + the fresh-question override must both pass on
this pivot scenario.

Session-scoped state (like the topic) must never ONLY live in
handler scope. Redis db=2 is the existing bucket for such state;
a new store goes there with a clear key prefix
(``session_topic:``) and a TTL matching the session duration.

### Scheduled Follow-up

- CP5: unify ``_MEMO_TOPIC_MAP`` (query_router) and ``_GENERIC_CUES``
  (pipeline) into a single topic registry (FINDING #12 already
  scheduled this).
- CP5: extend ``_SUBDOMAIN_LAW_PATTERNS`` to cover the remaining
  Qatari legal families once traffic is battle-tested.
- CP5: ``general_degraded`` route should be surfaced in the UI with
  a visible indicator — currently clients treat it identically
  to a normal general answer.

## 15. Server-Side Session State Machine (CP5)

### The Meta-Discovery
CP1 closed hallucination on five template layers. CP4 closed context
propagation with four pattern-match gates + session-topic persistence.
A fresh production reproduction showed ALL CP4 fixes evaporated the
moment the client UI sent ``history=[]`` on a memo-bearing turn:

  T2: "اكتب لي مذكرة اسقاط حضانه" (UI sends history=[])  → ask_details ✓
  T3: "1- احمد 3 سنوات 2- سوء سلوكها..."  (UI history=[]) → GENERAL ✗
  T4: "لماذا لم تكتب المذكرة ؟"            (UI history=[])
      → "لم أكتب المذكرة لأن سؤالك لم يتضمن طلباً صريحاً" ✗
  T5: "اكتب مذكرة اسقاط حضانه"             (UI history=[]) → ask_details (loop) ✗
  T6: "اكتب بالمعلومات المتوفرة"           (UI history=[])
      → "يرجى توضيح السؤال أو الموضوع"     ✗ (catastrophic context loss)

Every CP4 gate — Gate A (assistant-blob match), Gate B (prior user
+ short command), Gate C (current-query keyword), Gate D
(structured-details detector) — requires ``req.history`` to be
non-empty. Gate D's unit tests passed because they sent history
in the test harness. Production doesn't.

### Meta-Root-Cause
**The server keeps NO authoritative state between turns.** Every
handler treats every request as isolated. All memory is either:

  - in-memory per-turn (lost between requests), OR
  - in the client's ``req.history`` field (which the UI truncates).

session_topic_memory (CP4 Fix 2) persisted ONE field. Pattern
matching with CP4 gates saw only what the client sent. Neither
was enough because neither treated the server's memory as
authoritative.

### Root Fix — Server-Side State Machine
``core/session_state.py`` — Redis-backed authoritative state keyed
by ``session_id``. The server now knows:

  • **phase** ∈ {IDLE, AWAITING_MEMO_DETAILS, AWAITING_MEMO_TOPIC,
    MEMO_DRAFTING} — the conversational state.
  • **history** — full turn log (user + assistant) capped at 50
    entries. Server truth. Replaces client ``req.history`` when
    the client sends less.
  • **topic** — memo topic once detected, sticky across turns.
  • **memo_facts** — accumulated user facts for draft-in-progress.
  • **last_updated** — epoch seconds for TTL / debug.

**TTL**: 2 hours (matches realistic memo session length).
**Redis DB**: 2 (existing case_memory bucket).
**Failure mode**: any Redis error → empty state returned, logs at
debug. Pre-CP5 behaviour is the safe degraded path.

### Routing Contract (CP5)

In ``routers/query_router.py::query_stream``, BEFORE any gate or
pattern-match logic:

    session_state = await load_state(sid)

    if len(session_state.history) > len(req.history):
        # Server has more than client → use server as truth
        req.history = session_state.history

    session_state.append_turn("user", q)

    if session_state.phase in {AWAITING_MEMO_DETAILS,
                               AWAITING_MEMO_TOPIC}:
        # Fresh-question pivot exception:
        if q starts with "ما هي عقوبة" / "كيف" / "هل " / ... :
            session_state.reset_memo_state()   # release phase
            # fall through to normal routing
        else:
            # FORCE memo route, ignore gates, ignore query content
            return _wrap_with_state_save(
                handle_memo_smart(q, sid, req.history),
                session_state,
            )

    # Otherwise: normal phase0 + Gates A-D logic continues.
    ...
    # EVERY return site wraps its StreamingResponse so that after the
    # stream completes, the assistant turn is appended to state.history,
    # phase transitions via transition_by_route(), and state is persisted.

### Fresh-Question Pivot — preserved from CP4
The "ما هي عقوبة / كيف / هل" prefix list is reused inside the
CP5 state check. Without it, every post-memo pivot (T7 in the
failing transcript) would be dragged back into the memo handler.

### StreamingResponse Wrapper
CP5's ``_wrap_with_state_save`` intercepts the SSE stream:

  1. For each ``data: {"type": "chunk", ...}`` frame, accumulates
     the content into the assistant-turn buffer.
  2. For the terminal ``data: {"type": "done", "route": "..."}``
     frame, captures the final route label.
  3. After the stream drains, persists state:
       state.append_turn("assistant", accumulated)
       state.transition_by_route(final_route)
       save_state(state)

All existing handlers (handle_general / handle_memo_smart /
handle_article_text / handle_table / handle_calculator /
handle_continuation) are UNCHANGED. The wrapper sits entirely
in query_stream.

### The 4 Phases

| Phase | Entry condition | Exit |
|-------|------------------|------|
| IDLE | Fresh session or memo complete | User asks for memo |
| AWAITING_MEMO_DETAILS | handle_memo_smart emitted memo_ask_details | User responds → MEMO_DRAFTING |
| AWAITING_MEMO_TOPIC | memo request without topic | User gives topic → MEMO_DRAFTING |
| MEMO_DRAFTING | Memo route fired | User pivots to fresh question → IDLE |

### Test Coverage

  - ``tests/test_session_state.py`` — 17 unit tests (dataclass
    invariants, phase transitions, JSON round-trip, Redis
    load/save/delete, sync wrappers).
  - ``tests_cp5_production_scenario.py`` — 17 assertions on the
    exact 8-turn production transcript. **Every request sends
    ``history=[]``** to prove the fix stands without ANY client
    history cooperation.

### The Critical Proof
``tests_cp5_production_scenario.py`` POST-requests with
``history=[]`` on every turn. Pre-CP5: T3 → general (wrong),
T4 → "سؤالك لم يتضمن طلباً صريحاً" (catastrophic), T6 → "يرجى
توضيح السؤال" (context destroyed). Post-CP5: T3 → memo
(route=memo, len=4747, contains احمد + سلوك), T4 →
acknowledgement (not context loss), T6 → memo reuse,
T7 → fresh pivot accepted, state machine releases memo phase.
**17/17 PASS** without any client-supplied history.

### Protocol Update — Server-Truth Principle

Every memo-routing gate, every continuation detector, every topic
recoverer MUST operate on server-stored state, not on
``req.history``. Client history is a hint, not truth. Any new
multi-turn feature follows the same contract:

  1. Load session_state at entry.
  2. Read from state (history / topic / facts / phase).
  3. Decide route based on state.
  4. Append user turn to state.
  5. Save state.
  6. Handler runs.
  7. Wrapper captures assistant turn + transitions phase.
  8. State saved on stream completion.

### Deprecated in CP5 Contract
Gates A/B/C/D (CP4 Fix 1) are retained for backward compatibility
in the fall-through path when state is IDLE. They are NO LONGER
load-bearing for the AWAITING_MEMO_DETAILS path — the state
machine owns it. Subsequent CPs may remove them once soak-testing
confirms state-machine-only routing is stable across edge cases.

### Scheduled Follow-up

- CP6: move ``session_topic_memory`` fields into ``SessionState``
  (currently two parallel Redis keys for the same session).
- CP6: ``memo_facts`` integration — feed accumulated facts to
  ``handle_memo_smart`` so T6 "اكتب بالمعلومات المتوفرة" actually
  uses T3's details (today T6 relies on handle_memo_smart's
  own combined-query logic from ``req.history``).
- CP6: migrate ``fact_extractor``'s Redis cache namespace to be
  session-scoped (currently sig-based; would benefit from a
  session bucket).
- CP6: surface ``state.phase`` in the ``done`` frame so clients
  can display "awaiting memo details" chips.

## 16. Legal Reasoning Engine — Memo Quality Paradigm Shift (CP6)

### The Meta-Root-Cause (Round 2)
CP1-5 closed HALLUCINATION on 5 template layers and restored CONTEXT
via a server-side state machine. Every test was green. Yet the user
re-reported poor memo quality on T3 of a fresh live session:

  • Child's name ``"احمد"`` never appeared in the memo
    (fact_extractor captured it as ``names=["احمد"]`` but the
    composer only rendered ``claims`` as bullets).
  • SEVEN articles dumped (168, 183, 166, 167, 171, 186, 182).
    A lawyer would cite 2-3. Article 168 (non-foreigner spouse
    condition) was injected into a سوء سلوك case — user never
    mentioned marriage.
  • Precedents were three civil cassation rulings about property
    ownership and traffic accident liability — in a family-law
    custody memo. Jaccard similarity was 0.89-0.91 (high on TEXT,
    zero on LEGAL PRINCIPLE).
  • Facts rendered as flat labelled bullets
    (``"الأعمار المذكورة: 3 سنين"``) rather than woven into
    coherent legal prose.
  • Prayer #2 was a ``[placeholder]`` scaffold, not a
    domain-specific substantive prayer.

### Root-Cause Diagnosis
The symptoms are cosmetic, but the architecture behind them is
deep. Every pre-CP6 component was deterministic and safe:

  fact_extractor     — LLM, bounded, structured.
  precedent_linker   — Jaccard + embeddings, bounded.
  article_summary    — DB verbatim, bounded.
  compose_memo       — template concatenation, bounded.

Each piece does its one job without hallucinating. BUT:

  **NO component holds the WHOLE context + makes whole-memo
  decisions**. The composer sees all pieces yet merely concatenates
  them. It is a DUMB ASSEMBLER, not a LAWYER.

A real lawyer writing a memo REASONS:
  1. Characterize the legal ground from facts.
  2. Select 2-3 articles that actually support THAT ground.
  3. Retrieve precedents by legal principle, not text similarity.
  4. Weave facts + law + precedent into coherent prose.
  5. Craft prayers aligned with the argument.

Pre-CP6 there was no layer performing any of those. The "safety
via determinism" design choice had ELIMINATED INTELLIGENCE from
the composition step. CP1's hallucination guard prevented
invention; CP4's state machine restored context; but neither
added legal reasoning.

### The Paradigm Shift
``core/legal_reasoning_engine.py`` (~500 LOC, new module) —
replaces the concatenator with a 5-stage reasoning pipeline:

  Stage 1 — **CHARACTERIZE**
    Given (facts, domain) → ``LegalGround`` {label, primary_article,
    primary_clause, required_elements, confidence}.
    Example: "سوء سلوك الحاضنة" + family_custody →
      label = "إسقاط الحضانة لسوء سلوك الحاضنة"
      primary_article = "183", primary_clause = "3"

  Stage 2 — **SELECT**
    Given (ground, candidate_articles) → 2-4 ``SelectedArticle`` only.
    Explicit ``rejected`` reasons for transparency.
    Example for above: {183, 182, 167}. Reject 168 ("لا تنطبق —
    لم يُذكر زواج"), 171 ("لا علاقة بالسبب"), 186 ("زيارة لا
    تخص الإسقاط").

  Stage 3 — **RERANK PRECEDENTS**
    Given (ground, candidate_precedents) → ``SelectedPrecedent``
    list filtered by LLM score (>= 0.5). Cross-domain rulings
    are auto-rejected. Custody memo never pulls civil-property
    precedents.

  Stage 4 — **COMPOSE PROSE**
    Given (ground, facts, selected articles, selected precedents)
    → lawyer-quality prose memo text. Strict system prompt:
      - Never invent facts.
      - Never cite articles outside the selected list.
      - Never cite precedents outside the selected list.
      - Use bracketed placeholders for missing info
        (``[يُدرج اسم المدعى عليها]``).
      - Prose, not bullets.
      - Qatari court memo style.

  Stage 5 — **VERIFY** (programmatic, cheap)
    Regex-extract article numbers + precedent refs from the
    composed text. Flag any that are outside the selected sets.
    Cheap, deterministic, auditable. No LLM.

### Integration
``core/runtime_v2/composer.py::compose_memo`` is now an
**orchestrator**:

  1. Gather candidate_articles (from domain.article_refs, expanded
     via article_summary + metadata stripping from Fix 1.D).
  2. Gather candidate_precedents (from precedent_linker — CP3).
  3. Get extracted facts (from fact_extractor — CP1 Fix 1.A).
  4. Call ``compose_reasoned_memo_sync`` (the engine).
  5. **If engine succeeds** → return its memo.
  6. **If engine fails** → fall through to existing deterministic
     template assembly. This is the reliable safety net.

### Execution Model
The engine makes 3-4 LLM calls per memo:
  - Stage 1 (characterize) ~1 call
  - Stages 2 + 3 in PARALLEL (asyncio.gather) ~1 call each
  - Stage 4 (compose) ~1 call
  - Stage 5 (verify) no LLM

Total latency: ~10-15s. Pre-CP6 was ~3s. The user accepted this
trade-off: "quality over speed".

**Critical fix**: ``_corpus_bg.run`` has a short hardcoded timeout
(`_TIMEOUT + 1.0` ≈ 6s) designed for sub-second asyncpg work. The
engine exceeds this, causing silent timeout → fallback → symptom
that "engine never ran" despite logs showing success. CP6 runs
the engine in a DEDICATED ``ThreadPoolExecutor`` with its own
event loop + 90s timeout. Pattern is safe because
``compose_memo`` is called from a sync context (runtime_v2.answer),
NOT from within an async context.

### Caching
Characterize + select_articles results are cached in Redis db=2
keyed by ``sha1(json(inputs))``. TTL 1h. Same facts → same ground
→ same articles, which is the correct cache semantics.

Compose output is NEVER cached — style may vary per turn and the
memo is the user-visible artifact.

### Prompts
Each stage has a dedicated Arabic system prompt that enforces:
  - Strict JSON output schema (stages 1, 2, 3).
  - Absolute-no-invention constraints.
  - Mandatory bracketed placeholders for missing fields
    (stage 4 — so downstream test contracts still find markers).
  - Mandatory section headers (``الوقائع`` / ``الدفوع والأسانيد
    الموضوعية`` / ``الأسانيد القانونية`` / ``السوابق القضائية`` /
    ``الطلبات``).

### The Critical Proof
Live user T3 scenario (``1- احمد 3 سنين 2- سوء سلوكها 3- تاريخ
الطلاق 01/01/2023``):

**Pre-CP6 memo** (template dump, 4747 chars):
  - 7 articles dumped (168, 183, 166, 167, 171, 186, 182)
  - 3 civil-property precedents (wrong domain)
  - Flat bullets ("الأعمار المذكورة: 3 سنين")
  - Generic ``[placeholder]`` prayer #2

**Post-CP6 memo** (lawyer prose, 1087 chars):
  - 2 articles on-point (183 primary, 182 procedural)
  - Honest "لا توجد أحكام تمييز ذات صلة مباشرة"
    (engine rejected civil precedents)
  - Prose: "يتقدم المدعي، وهو الأب، بطلب إسقاط حضانة ابنه أحمد،
    البالغ من العمر ثلاث سنوات، من طليقته..."
  - Specific prayer: "الحكم بإسقاط حضانة المدعى عليها لابنه
    أحمد وضم المحضون..."

Denser (1087 vs 4747 chars) but QUALITATIVELY HIGHER — a real
lawyer's memo, not a template dump.

### Test Coverage
Existing suites (11/11 anti-hallucination, 14/14 context-prop,
17/17 production scenario, 132/132 pytest) all stayed green after
adjusting the memo-length threshold from 2500 (old template dump
floor) to 800 (real-prose floor). Prose memos are denser by design.

### Fallback Protocol
The engine has THREE failure modes, all handled:

  1. LLM call timeout → stage returns empty → engine result has
     ``used_engine=False`` → compose_memo falls to template path.
  2. JSON parse failure on any stage → same path.
  3. Compose returned empty/short output → same path.

The template assembler (pre-CP6 path) is preserved and remains the
safe fallback. Zero regression risk on engine failure.

### The Architectural Lesson
"Safety via determinism" is NOT free. It eliminates hallucination
AND eliminates intelligence. Legal drafting needs intelligence.
The solution is not to restore determinism — it is to wrap an
LLM in STRONG INPUT/OUTPUT CONSTRAINTS so its intelligence is
directed and verifiable. The constraints are:

  - Input: grounded facts + candidate articles + candidate precedents
  - Output: prose guided by a strict system prompt
  - Verify: programmatic regex on the output

This is the pattern that scales. Every future "quality" layer
(handle_general answer composition, precedent summarization,
argument strengthening) should follow this pattern — not another
deterministic filter.

### Protocol Update — The Reasoning Layer Principle

When a symptom's root cause is "output quality is poor but no
component is hallucinating", the fix is NOT another filter. It
is an LLM-driven reasoning layer with:

  1. Explicitly grounded input (facts / candidate articles / etc.)
  2. A strict system prompt with output constraints
  3. Programmatic output verification
  4. A deterministic fallback path

This pattern is what makes CP6 different from CP1-5 (which were
constraints ABOUT determinism) and from CP2 (which was filters ON
retrieval). CP6 is the first addition of GENERATIVE REASONING
with guardrails.

### Scheduled Follow-up

- CP7: extend the reasoning pattern to ``handle_general`` — answer
  composition LLM layer with citation-grounded constraints. The
  T1 "ما هي عقوبات المرور" vague answer is the remaining symptom
  this would address.
- CP7: add ``legal_answer_engine.py`` — same 5-stage pattern but
  for Q&A not drafting (characterize question → select relevant
  articles → compose prose answer → verify citations).
- CP8: extend reasoning to precedent summarization — current
  ``rerank_by_ground`` filters, but a summarization layer could
  explain WHY each kept precedent applies.
- CP8: add ``legal_style_guide`` module codifying Qatari memo
  conventions (currently baked into ``_COMPOSE_MEMO_SYSTEM``
  prompt — should be externalized for maintainability).
- Future: domain-specific reasoning overrides (e.g., custody
  cases always check Article 167 elements explicitly) — today
  the engine is domain-agnostic, which may produce generic
  reasoning for specialized domains.

## 17. Session State Race + Answer Reasoning Layer (CP7)

### The Silent Failure
CP5 built the state machine. CP6 added the reasoning engine. Yet a
live production transcript still showed T3 misrouted to general and
T4 falling into the generic_skeleton template. Logs showed state
was being saved — just not in time.

### Root-Cause Diagnosis — Race Condition on State Save
Diagnostic probe with consistent session_id revealed:
  • T1 saved state correctly.
  • T2 (force_memo → memo_ask_details) — the wrapper FINALLY block
    fired AFTER the next request arrived.
  • T3 loaded state BEFORE T2's save landed → phase still IDLE
    → state-based routing didn't fire → fell through to phase0.

The stream wrapper's ``finally`` block is guaranteed to run but
only when the async generator is fully consumed. FastAPI/Uvicorn
consumes the stream as it sends bytes to the client. If the
client is fast (desktop UI on localhost) and the next request
arrives within ~100ms of the previous response's last chunk,
the next request can load state before the wrapper finalizes.

Root fix: **eager save**. Persist state to Redis IMMEDIATELY
after appending the user turn + making route decisions, not
only in the wrapper's finally. The wrapper still saves at the
end (capturing accumulated assistant text + actual route), but
the next request already sees the user turn + predicted phase.

Integration in query_router.py:
  1. After ``_session_state.append_turn("user", q)`` — eager
     ``await _save_state(_session_state)``.
  2. Inside ``force_memo`` block — set phase to
     ``AWAITING_MEMO_DETAILS`` + save again (best-guess).

The wrapper still fires and corrects phase based on actual emitted
route. Worst case: phase is "stale for ~100ms" between eager save
and wrapper finalize. No longer wrong for seconds.

### The Answer Path Had No Reasoning
T1 "ما هي عقوبات المرور" + T6 "اذكر أسانيد أكثر" — both got vague
deflections ("يُفضل الاطلاع على القانون" / "استشر محامي"). CP6 added
reasoning to the MEMO path but ``handle_general`` (every Q&A turn)
still streamed raw LLM output over RAG chunks with no intelligent
selection or citation enforcement.

### Root Fix — Answer Engine
``core/legal_answer_engine.py`` (~450 LOC, NEW) — symmetric to the
memo reasoning engine, adapted for Q&A:

Stage 1 — CLASSIFY QUESTION  
  definitional / procedure / penalty / analysis / general.

Stage 2 — SELECT SOURCES  
  From retrieved RAG chunks, keep 2-5 that ACTUALLY answer the
  question. Skipped when retrieval is already narrow (≤4 chunks)
  to avoid over-filtering.

Stage 3 — COMPOSE ANSWER  
  LLM writes CITED structured answer with mandatory sections:
    • **الإجابة المباشرة** (direct answer — 1-2 lines)
    • **السند القانوني** (legal basis with article citations)
    • **تفصيل عملي** (practical elaboration)
    • **توصية ختامية** (optional advisory)
  Strict prompt forbids: vague deflection, "just go read the
  law yourself", citing articles not in the selected set.

Stage 4 — VERIFY  
  Programmatic regex — every article number cited must be in
  the selected source set.

Integration in ``handle_general``: before streaming raw LLM output
from ``_llm.stream_openai``, call ``compose_reasoned_answer``. On
success, stream its output in chunks. On failure, fall through to
the legacy raw stream path. Backward compatible.

### Observable Impact

T1 "ما هي عقوبات المرور" — Before CP7:
  "العقوبات تشمل الغرامات المالية... يُفضل الاطلاع على قانون
  المرور." (no articles, no numbers, pure deflection)

T1 — After CP7 (engine-served):
  "**الإجابة المباشرة:** عقوبات المرور في قطر تشمل الغرامات
  المالية، السجن، وسحب رخصة القيادة...
  **السند القانوني:** [...]
  **تفصيل عملي:** [...]
  **توصية ختامية:** [...]"
  (structured, with sections, citations when DB has material)

T3 "1- احمد 4 سنوات 2- سوء سلوكها 3- تاريخ الطلاق" — Before CP7:
  route=general, LLM misreads Article 183(2) text about "الحاضنة
  الجديدة" and applies it incorrectly.

T3 — After CP7:
  route=memo, 1415 chars prose narrative: "يتقدم مقدم المذكرة
  [يُدرج اسم المدعي] بدعوى إسقاط الحضانة وضم المحضون ضد طليقته
  [يُدرج اسم المدعى عليها]، وذلك بناءً على سوء سلوكها الذي يهدد
  مصلحة المحضون. حيث إن المدعي هو والد المحضون أحمد، الذي يبلغ
  من العمر أربع سنوات، وقد تم الطلاق بين المدعي والمدعى عليها
  بتاريخ 01/01/2023..."

### Tests + Engine Assertion Semantics
``must_contain_in_section`` updated to ANY-semantics (prose
memos use varying lawyer-phrasing — الحكم / نلتمس / يلتمس /
إسقاط — any one in the Prayers section is valid). Pre-CP7 was
ALL-semantics, which made prose tests brittle.

### Regression State After CP7
  11/11  anti-hallucination
  14/14  context-prop
  17/17  cp5 production scenario
   8/8   c1-c8 memo continuity
 132/132 pytest unit + case_memory E2E
  --------
 182/182 total passing

### Protocol Update — Two Principles

1. **Eager save principle.** Any state that affects routing MUST
   be saved to Redis before the handler runs, not after the
   stream completes. Stream completion is an asynchronous event
   whose timing depends on client consumption speed. Routing
   decisions must not depend on it.

2. **Reasoning parity principle.** Every answer path (memo,
   question, followup, advisory) MUST go through a reasoning
   engine with the same 5-stage pattern: classify → select →
   compose → verify → fallback. Raw LLM streaming over RAG
   chunks is a LEGACY PATH — kept as fallback, never the
   primary.

### Scheduled Follow-up

- CP8: unify ``legal_reasoning_engine`` (memo) and
  ``legal_answer_engine`` (Q&A) under a common base class —
  both share classify/select/compose/verify/fallback patterns.
- CP8: extend reasoning to ``handle_continuation`` — follow-up
  questions currently use raw LLM stream over history.
- CP8: expand retrieval quality — CP7 showed the engine is
  only as good as the chunks it reasons over. T1 (traffic)
  still degraded-looking because the DB chunks for traffic
  law are sparse. A domain-aware retrieval expander (query
  rewrite + synonym expansion) would help.
- Future: move all reasoning cache TTLs to a single config so
  memo (1h), answer (30m), and topic (1h) can be tuned
  together without code changes.

