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
