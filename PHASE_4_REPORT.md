# PHASE 4 — Legal Reasoning Engine Architecture Report
## المساعد القانوني القطري (ميزان) v9.0 → v9.2

**Date:** 2026-04-13
**Scope:** Full Legal Reasoning Engine + Deep Reasoning Intelligence + Knowledge Packs + Evidence Registry

---

## 1. Reasoning Engine Architecture

### Overview

The Legal Reasoning Engine sits between query understanding (intent classification) and answer generation (structured lookup / LLM). It produces an internal `ReasoningResult` object that governs how every answer is constructed and qualified.

### Pipeline Flow

```
User Query
    │
    ▼
┌─────────────────────┐
│ detect_reasoning_mode│  ← 9 question-type modes
│ (reasoning_policy.py)│
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ _detect_domain      │  ← salary / drug / scope / reasoning
│ _detect_topic       │  ← basic_salary / classification / etc.
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ _gather_evidence    │  ← searches Evidence Registry by domain,
│                     │    topic, and keyword signals
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ ReasoningPolicy     │  ← evaluates each evidence item's trust level
│ .evaluate_evidence  │    DIRECT → fact, INFERENCE → qualify,
│                     │    BLOCKED → suppress
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ _build_answer_plan  │  ← ordered steps based on mode guidance
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ ReasoningResult     │  ← structured internal object
│  .direct_evidence   │
│  .controlled_infer  │
│  .blocked_claims    │
│  .answer_plan       │
│  .limitations       │
│  .final_answer_mode │
└──────────┬──────────┘
           │
    ┌──────┴──────┐
    │             │
    ▼             ▼
Structured    LLM Path
   Path       (build_llm_context)
    │             │
    ▼             ▼
enrich_answer  inject reasoning
(enrichment)   into LLM prompt
```

### Core Classes

**`LegalReasoningEngine`** (`core/reasoning_engine.py`, ~400 lines):
- `reason(query, session_id, history, structured_result)` → `ReasoningResult`
- `enrich_answer(base_answer, reasoning, is_structured)` → enriched answer string
- `build_llm_context(reasoning)` → Arabic context block for LLM prompt injection
- `get_context(session_id)` → `ConversationContext` for multi-turn memory

**`ReasoningResult`** (dataclass):
- `reasoning_mode`, `domain`, `topic`, `applicable_law`
- `direct_evidence`, `controlled_inferences`, `blocked_unsupported_claims`
- `answer_plan` (ordered steps), `final_answer_mode`, `limitations`, `warnings`
- `policy_guidance` (mode-specific strategy from ReasoningPolicy)
- Methods: `has_direct_evidence()`, `has_blocked()`, `to_dict()`

**`ConversationContext`** (dataclass):
- Tracks: `current_topic`, `current_law`, `current_grade`, `current_scope`, `current_schedule`, `turn_count`
- Updated automatically per turn; enables follow-up queries like "طيب كم يكون الإجمالي"

### 9 Question-Type Reasoning Modes

| Mode | Example Query | Strategy |
|------|---------------|----------|
| STRUCTURED_FACTUAL | كم مربوط الدرجة السابعة | direct_data_lookup, no inference |
| YES_NO_CLARIFICATION | هل هذا يشمل البدلات | evidence_then_clarify |
| COMPARISON | قارن بين الدرجة السادسة والسابعة | side_by_side data |
| SCOPE_APPLICABILITY | هل يشمل جميع الجهات الحكومية | scope_check + limitations |
| FOLLOWUP_CONTEXTUAL | طيب كم يكون الإجمالي | context_continuation |
| CLASSIFICATION | كيف يتم تصنيف هذه الأدوية | classify_and_explain |
| LEGAL_DISTINCTION | ما الفرق بين الاستخدام الطبي وغير المشروع | distinguish_concepts |
| ANALYTICAL_LEGAL | لماذا يختلف الراتب | structured_analysis |
| GENERAL_LEGAL | ما حكم السرقة | evidence_based_response |

**Priority ordering** (critical for correct classification):
1. Follow-up contextual (requires conversation history)
2. Yes/No — escalates to SCOPE only when scope-context signals present (جهات, حكومية, نطاق)
3. Legal distinction — before comparison, when comparing abstract concepts (not grades)
4. Comparison — grade-level / data-level comparisons
5. Classification
6. Scope/applicability
7. Structured factual (via classify_query)
8. Analytical legal
9. General legal (fallback)

---

## 2. Knowledge Packs Created

Four curated knowledge packs, each a Python module returning `list[EvidenceEntry]`:

### Salary Pack (`core/knowledge_packs/salary_pack.py`)
- 15+ entries covering: basic salary definition (مربوط), start/end of bound, periodic increment, grade structure (14 grades), allowances (social, housing, transport), total compensation, special entity regimes
- Key blocked claim: "قد يصل إجمالي الراتب إلى ضعف المربوط أو أكثر" (UNSUPPORTED_BLOCKED)
- Key direct evidence: salary table shows basic salary only, not total with allowances

### Drug Pack (`core/knowledge_packs/drug_pack.py`)
- 13+ entries covering: three schedules, narcotics vs psychotropics vs pharma, severity link, medical use, illicit use, medical vs illicit distinction
- Blocked: danger claims ("هذه المواد قاتلة"), medical advice ("يمكن استخدام هذه المادة بأمان")

### Scope Pack (`core/knowledge_packs/scope_pack.py`)
- 7+ entries covering: civil service scope, government entity definition, military exclusion, special entities, salary table applicability, drug law scope
- Blocked: complete exclusion list claim

### Reasoning Pack (`core/knowledge_packs/reasoning_pack.py`)
- 10+ entries: meta-knowledge about evidence quality, reasoning boundaries, answer strategy
- Blocked: speculation about future legislation, personal opinions about law fairness

---

## 3. Evidence Registry Design

**`core/evidence_registry.py`** (~300 lines)

### Three-Tier Trust Model

| Level | Action | Usage |
|-------|--------|-------|
| `DIRECT_EVIDENCE` | State as fact | Verified from law text, official tables |
| `CONTROLLED_INFERENCE` | State with qualifier | Reasonable deduction, qualified with "وفقاً للمعلومات المتاحة" |
| `UNSUPPORTED_BLOCKED` | Block entirely | Claims that cannot be verified, speculation |

### EvidenceEntry Structure

```python
@dataclass
class EvidenceEntry:
    entry_id: str                    # "sal_001_marbout_definition"
    statement_ar: str                # Arabic knowledge statement
    domain: str = ""                 # "salary", "drug", "scope", "reasoning"
    topic: str = ""                  # "basic_salary", "classification"
    support_level: str = "direct"    # Trust tier
    source_type: str = ""            # "law_text", "official_table"
    source_law: str = ""             # "قانون الخدمة المدنية"
    source_article: str = ""         # "المادة 22"
    conditions: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    confidence_rationale: str = ""
    version: str = "1.0"
```

### Registry Capabilities

- **Indexed lookup**: by domain, topic, tag, entry_id
- **Trust-level filtering**: `get_direct_evidence()`, `get_inferences()`, `get_blocked()`
- **Claim verification**: `is_claim_supported(text, domain)` → (bool, entry)
- **Claim blocking**: `is_claim_blocked(text, domain)` → (bool, entry)
- **Keyword search**: `search(keyword)` scans statements and tags
- **Pack loading**: `load_pack(name, entries)` with deduplication
- **Stats**: total entries, by_domain breakdown, loaded packs list

### Bootstrap

`get_registry()` singleton loads all 4 knowledge packs at first access. Currently holds 45+ curated entries across 4 domains.

---

## 4. Self-Improvement Structures

**`core/improvement_memory.py`** (~300 lines)

### Failure Pattern Detection

Analyzes `failure_logger` data to detect:
- **Repeated refusals** — same query intent refused 3+ times (signals a knowledge gap)
- **Ambiguous intents** — queries that oscillate between classifications
- **Grade misses** — specific grades that fail to resolve

### Knowledge Gap Tracking

4 known gaps pre-loaded + dynamic gap detection from failure patterns:
- `gap_salary_allowances` — specific allowance amounts not in DB
- `gap_special_entities` — salary regimes for Qatar Petroleum, QIA, etc.
- `gap_ocr_degraded_segments` — damaged OCR chunks with <50% readability
- `gap_penalty_tables` — drug law penalty amounts not extracted

### Improvement Candidate Generation

Produces actionable `ImprovementCandidate` items:
- Candidates from known gaps (e.g., "add allowance table scraping")
- Candidates from detected patterns (e.g., "add salary table for grade X")
- Each has: `candidate_id`, `description_ar`, `priority`, `source_gap`, `estimated_effort`

### Evidence Debt Tracking

4 known evidence debts — areas where the system knows it should have better evidence:
- `debt_total_salary` — cannot compute total salary (needs allowance data)
- `debt_entity_salary` — special entities have different tables
- `debt_drug_danger` — cannot state medical danger levels
- `debt_penalty_amounts` — penalty specifics not extracted from law

### Improvement Report

`generate_improvement_report()` aggregates all subsystems into a single JSON report exposed at `/debug/improvement-report`.

---

## 5. Exact Files Modified / Created

### New Files (Phase 4)

| File | Lines | Purpose |
|------|-------|---------|
| `core/evidence_registry.py` | ~300 | Central trust layer |
| `core/reasoning_engine.py` | ~400 | Legal reasoning engine |
| `core/reasoning_policy.py` | ~278 | Policy rules + mode detection |
| `core/improvement_memory.py` | ~300 | Self-improvement infrastructure |
| `core/knowledge_packs/__init__.py` | 1 | Package init |
| `core/knowledge_packs/salary_pack.py` | ~150 | Salary domain knowledge |
| `core/knowledge_packs/drug_pack.py` | ~130 | Drug domain knowledge |
| `core/knowledge_packs/scope_pack.py` | ~80 | Scope domain knowledge |
| `core/knowledge_packs/reasoning_pack.py` | ~100 | Meta-reasoning knowledge |
| `tests/test_evidence_registry.py` | 156 | 16 tests |
| `tests/test_reasoning_engine.py` | 348 | 43 tests |
| `tests/test_improvement_memory.py` | 79 | 7 tests |

### Modified Files

| File | Changes |
|------|---------|
| `main.py` | Added 3 debug endpoints: `/debug/evidence-registry`, `/debug/improvement-report`, `/debug/reasoning` |
| `routers/query_router.py` | Wired reasoning engine at 3 injection points (structured hit enrichment, LLM context building, prompt assembly) |

---

## 6. Tests Added / Updated

### Phase 4 Test Suites

| Suite | Tests | Status |
|-------|-------|--------|
| `test_evidence_registry.py` | 16 | 16 passed |
| `test_reasoning_engine.py` | 43 | 43 passed |
| `test_improvement_memory.py` | 7 | 7 passed |
| **Phase 4 Total** | **66** | **66 passed** |

### Combined with Mandate D Tests

| Suite | Tests | Status |
|-------|-------|--------|
| `test_salary_comparison.py` | 17 | 17 passed |
| `test_failure_logger.py` | 6 | 6 passed |
| `test_salary_scope.py` | 11 | 11 passed |
| `test_drug_cleanup.py` | 11 | 11 passed |
| **All Custom Tests** | **110** | **110 passed** |

### Key Test Coverage

- Mode detection for all 9 reasoning modes including edge cases (priority ordering)
- Domain detection (salary, drug, scope) with context fallback
- Topic detection (basic_salary, total_compensation, classification, medical_vs_illicit)
- Reasoning policy (all 3 trust tiers + mode guidance)
- Engine integration (reason → enrich → LLM context)
- Multi-turn context preservation
- Evidence registry (CRUD, pack loading, claim verification, stats)
- Knowledge packs (entry counts, key entry existence)
- Improvement memory (patterns, gaps, candidates, debts, report structure)
- No internal tag leakage to user-facing text

---

## 7. Examples: Before vs After

### Query: "هل هذا يشمل البدلات؟"

**Before (v9.0):** LLM guesses based on prompt. May claim total salary amounts. No evidence tracking.

**After (v9.2):**
```
Mode:     YES_NO_CLARIFICATION
Domain:   scope (→ salary context from conversation)
Direct:   5 evidence entries loaded
Blocked:  1 claim suppressed ("total = 2x basic")
Plan:     [lookup_evidence, apply_policy, answer_yes_no, add_limitation]
Enrichment: "جدول الرواتب يعرض المربوط الأساسي فقط..."
```

### Query: "ما الفرق بين الاستخدام الطبي وغير المشروع؟"

**Before:** Classified as COMPARISON. Engine tries side-by-side data lookup (fails — no grades).

**After:**
```
Mode:     LEGAL_DISTINCTION (not COMPARISON)
Domain:   drug
Topic:    medical_vs_illicit
Direct:   9 entries (medical use, illicit definition, distinction rules)
Strategy: distinguish_concepts
Plan:     [gather_evidence, identify_distinction_axes, present_contrast, add_evidence_refs]
```

### Query: "كم مربوط الدرجة السابعة؟"

**Before:** Deterministic lookup works, but no evidence audit trail. Answer is raw data.

**After:**
```
Mode:     STRUCTURED_FACTUAL
Domain:   salary, Topic: basic_salary
Direct:   9 entries confirm مربوط = basic salary
Enrichment: NONE (pure data answer — no decoration needed)
LLM context: 1499 chars of evidence-grounded instructions
```

---

## 8. Remaining Weak Areas

1. **Streaming path integration** — The reasoning engine is wired into the JSON response path of `query_router.py` but the SSE streaming path (~line 1300+) needs the same 3-point injection (enrichment after structured hit, LLM context building, prompt assembly).

2. **Evidence count scaling** — Currently ~45 curated entries. As entries grow to 200+, keyword-based search in `_gather_evidence()` may need TF-IDF or embedding-based retrieval.

3. **Topic detection depth** — `_detect_topic()` uses keyword signals. Queries like "كم العلاوة الاجتماعية للدرجة الخامسة" may resolve topic as "basic_salary" instead of "social_allowance" (sub-topic not yet modeled).

4. **Cross-domain reasoning** — Queries that span salary + scope simultaneously ("كم راتب الدرجة السابعة في قطر للبترول") require cross-domain evidence gathering not yet implemented.

5. **Conversation context persistence** — `ConversationContext` lives in memory. Server restart clears all session contexts. Redis-backed persistence would survive restarts.

6. **Improvement memory automation** — Currently generates candidates but doesn't auto-execute improvements. A scheduled job could process high-priority candidates and create PRs.

7. **Knowledge pack versioning** — Packs have a `version` field but no migration or diff system yet. When laws change, old entries need deprecation/replacement workflow.

---

## 9. Recommended Next Expansion Areas

1. **Wire streaming path** — Apply the same 3-point reasoning injection to the SSE streaming handler in query_router.py for full coverage.

2. **Penalty knowledge pack** — Create `penalty_pack.py` covering drug law penalties (Articles 34-50). Currently the highest evidence debt.

3. **Allowance data pack** — Scrape or manually enter allowance tables (social, housing, transport) to close `gap_salary_allowances`. Would enable total salary computation.

4. **Embedding-based evidence search** — Replace keyword matching in `_gather_evidence()` with pgvector similarity search against evidence statements, for more robust retrieval.

5. **Automated improvement loop** — Schedule a daily job that reads `generate_improvement_report()`, prioritizes the top 3 candidates, and creates structured issues or draft knowledge entries.

6. **Answer validation layer** — Use `ReasoningPolicy.validate_answer_text()` as a post-generation gate on every LLM response, catching blocked claims before they reach the user.

7. **Reasoning trace UI** — Expose reasoning traces (mode, evidence, plan) in a collapsible debug panel in the dashboard for transparency and debugging.

8. **Multi-law support** — Extend domain detection to cover additional Qatari laws (labor law, commercial law, criminal procedure). Each gets its own knowledge pack.

9. **Evidence provenance chain** — Track which evidence entries contributed to each answer, creating an audit trail for legal compliance verification.

10. **Internet-assisted improvement research** — When `detect_new_gaps()` finds a gap, trigger a web search for relevant legal resources and flag them for human review before incorporation.
