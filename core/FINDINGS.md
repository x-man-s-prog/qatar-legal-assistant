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
