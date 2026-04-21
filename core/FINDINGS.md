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

