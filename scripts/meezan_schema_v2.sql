-- ============================================================
-- Al-Meezan Legal Corpus — Professional Indexing Schema v2
-- ============================================================
-- DESIGN GOALS
-- ------------
-- 1. FIDELITY    — every field Al-Meezan exposes is captured verbatim.
-- 2. TRACEABILITY — every article/attachment traces back to its source URL.
-- 3. LINKABILITY  — laws reference laws, articles reference articles,
--                   rulings reference articles, and we can traverse any graph.
-- 4. SEMANTIC     — enriched with LLM-derived tags, topics, legal concepts
--                   for retrieval beyond lexical match.
-- 5. EVOLUTION    — versioning so amendments are first-class citizens:
--                   one law can have N amendments, each preserved.
-- 6. ATTACHMENTS  — schedules/annexes/tables are captured as first-class
--                   child objects (not inlined text).
-- 7. EMBEDDINGS   — dense vectors at article, law, and concept levels.
-- ============================================================

-- ── 1. LAWS (top-level legislation) ──────────────────────────
CREATE TABLE IF NOT EXISTS laws_v2 (
    id                  SERIAL PRIMARY KEY,
    almeezan_id         INTEGER UNIQUE,          -- Al-Meezan canonical ID
    law_type            TEXT,                    -- قانون / مرسوم / قرار / ...
    law_number          TEXT,                    -- e.g. "22"
    law_year            INTEGER,                 -- e.g. 2004
    law_name            TEXT NOT NULL,           -- full title (raw)
    law_name_normalized TEXT,                    -- for fuzzy search
    issue_date          DATE,                    -- رسمي تاريخ الإصدار
    publish_date        DATE,                    -- تاريخ النشر
    effective_date      DATE,                    -- تاريخ السريان
    status              TEXT NOT NULL            -- in_force / canceled / amended
                            CHECK (status IN ('in_force', 'canceled', 'amended', 'unknown')),
    source              TEXT NOT NULL DEFAULT 'almeezan'
                            CHECK (source IN ('almeezan', 'gazette', 'manual')),
    language            TEXT DEFAULT 'ar',
    -- URLs
    source_url          TEXT,                    -- /LawPage.aspx?id=X
    fulltext_url        TEXT,                    -- /LawView.aspx?LawID=X
    pdf_url             TEXT,                    -- /LocalPdfLaw.aspx?Target=X
    owner_url           TEXT,                    -- /LawOwner.aspx?id=X
    -- Metadata
    issuer              TEXT,                    -- الجهة المُصدِرة
    authorizing_body    TEXT,                    -- السلطة المانحة (was "authorization" — reserved)
    gazette_issue       TEXT,                    -- رقم الجريدة الرسمية
    gazette_page        TEXT,                    -- الصفحة
    summary             TEXT,                    -- موجز (LLM-derived)
    legal_domain        TEXT,                    -- مجال قانوني (criminal/civil/family/labor/commercial/...)
    subjects            TEXT[],                  -- (array) المواضيع من الشجرة
    keywords            TEXT[],                  -- (array) الكلمات المفتاحية
    target_parties      TEXT[],                  -- (array) الأطراف المستهدفة
    geographical_scope  TEXT,                    -- نطاق تطبيق: قطر / إقليمي / دولي
    content_hash        CHAR(64),                -- sha256 of fulltext (for change detection)
    parse_version       INTEGER DEFAULT 1,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_verified_at    TIMESTAMPTZ,
    UNIQUE (law_type, law_number, law_year, source)
);

CREATE INDEX IF NOT EXISTS idx_laws_v2_status       ON laws_v2 (status);
CREATE INDEX IF NOT EXISTS idx_laws_v2_type_year    ON laws_v2 (law_type, law_year);
CREATE INDEX IF NOT EXISTS idx_laws_v2_year_month   ON laws_v2 (law_year);
CREATE INDEX IF NOT EXISTS idx_laws_v2_domain       ON laws_v2 (legal_domain);
CREATE INDEX IF NOT EXISTS idx_laws_v2_subjects     ON laws_v2 USING GIN (subjects);
CREATE INDEX IF NOT EXISTS idx_laws_v2_keywords     ON laws_v2 USING GIN (keywords);
CREATE INDEX IF NOT EXISTS idx_laws_v2_name_trgm    ON laws_v2 USING GIN (law_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_laws_v2_norm_trgm    ON laws_v2 USING GIN (law_name_normalized gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_laws_v2_hash         ON laws_v2 (content_hash);


-- ── 2. ARTICLES (individual مادة / bnd) ──────────────────────
CREATE TABLE IF NOT EXISTS articles_v2 (
    id                  SERIAL PRIMARY KEY,
    law_id              INTEGER NOT NULL REFERENCES laws_v2(id) ON DELETE CASCADE,
    almeezan_tree_id    INTEGER,                 -- LawTreeSectionID
    article_number      TEXT,                    -- "المادة 5" or "5 مكرر"
    article_number_int  INTEGER,                 -- extracted numeric portion for sorting
    article_type        TEXT,                    -- article / chapter / book / section
    parent_article_id   INTEGER REFERENCES articles_v2(id) ON DELETE SET NULL,
    parent_hierarchy    TEXT,                    -- e.g. "الباب الأول / الفصل الثاني"
    title               TEXT,                    -- if article has a title
    text                TEXT NOT NULL,           -- RAW text verbatim
    text_normalized     TEXT,                    -- normalized for search
    -- Rich metadata (LLM-enriched)
    legal_concepts      TEXT[],                  -- ["قصد جنائي", "ركن مادي", ...]
    referenced_laws     JSONB,                   -- [{law_number, law_year, article}]
    referenced_articles INTEGER[],               -- fk to other articles_v2.id
    defined_terms       JSONB,                   -- [{term, definition}]
    penalties           JSONB,                   -- [{type, amount/duration}]
    procedural_steps    JSONB,                   -- [{step, actor}]
    effective_section   TEXT,                    -- "أحكام عامة" / "عقوبات" / ...
    source_url          TEXT,                    -- /LawArticles.aspx?LawTreeSectionID=Y&lawId=X
    position            INTEGER,                 -- ordering within the law
    content_hash        CHAR(64),
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_articles_v2_tree_unique
    ON articles_v2 (law_id, almeezan_tree_id)
    WHERE almeezan_tree_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_articles_v2_law_pos   ON articles_v2 (law_id, position);
CREATE INDEX IF NOT EXISTS idx_articles_v2_num       ON articles_v2 (law_id, article_number_int);
CREATE INDEX IF NOT EXISTS idx_articles_v2_concepts  ON articles_v2 USING GIN (legal_concepts);
CREATE INDEX IF NOT EXISTS idx_articles_v2_refs      ON articles_v2 USING GIN (referenced_articles);
CREATE INDEX IF NOT EXISTS idx_articles_v2_text_trgm ON articles_v2 USING GIN (text gin_trgm_ops);


-- ── 3. ATTACHMENTS (schedules / annexes / tables / PDFs) ─────
CREATE TABLE IF NOT EXISTS attachments_v2 (
    id                  SERIAL PRIMARY KEY,
    law_id              INTEGER NOT NULL REFERENCES laws_v2(id) ON DELETE CASCADE,
    article_id          INTEGER REFERENCES articles_v2(id) ON DELETE SET NULL,
    attachment_type     TEXT NOT NULL,           -- schedule / annex / form / table / figure / pdf
    sequence_num        INTEGER,                 -- ترتيب الملحق
    title               TEXT,                    -- "جدول المخدرات رقم 1"
    subtitle            TEXT,                    -- extra context
    description         TEXT,                    -- textual description or caption
    text_content        TEXT,                    -- extracted text if table/schedule
    rows_jsonb          JSONB,                   -- structured table rows
    columns_jsonb       JSONB,                   -- column definitions
    file_path           TEXT,                    -- local cached path
    file_url            TEXT,                    -- remote URL
    mime_type           TEXT,
    file_size           INTEGER,
    content_hash        CHAR(64),
    source_url          TEXT,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_attach_v2_law   ON attachments_v2 (law_id);
CREATE INDEX IF NOT EXISTS idx_attach_v2_type  ON attachments_v2 (attachment_type);
CREATE INDEX IF NOT EXISTS idx_attach_v2_title_trgm ON attachments_v2 USING GIN (title gin_trgm_ops);


-- ── 4. RELATIONSHIPS (law ↔ law, article ↔ article) ──────────
CREATE TABLE IF NOT EXISTS law_relationships_v2 (
    id                  SERIAL PRIMARY KEY,
    source_law_id       INTEGER NOT NULL REFERENCES laws_v2(id) ON DELETE CASCADE,
    target_law_id       INTEGER REFERENCES laws_v2(id) ON DELETE CASCADE,
    target_law_ref      JSONB,                   -- for unresolved: {law_type, number, year}
    relationship_type   TEXT NOT NULL            -- amends / amended_by / cancels / canceled_by /
                            CHECK (relationship_type IN (   -- references / referenced_by / derives / implementing
                                'amends','amended_by',
                                'cancels','canceled_by',
                                'references','referenced_by',
                                'implements','implemented_by',
                                'supplements','supplemented_by',
                                'supersedes','superseded_by'
                            )),
    detected_by         TEXT,                    -- regex / llm / manual
    confidence          REAL,                    -- 0.0..1.0
    note                TEXT,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_law_id, target_law_id, relationship_type)
);

CREATE INDEX IF NOT EXISTS idx_law_rel_v2_src  ON law_relationships_v2 (source_law_id);
CREATE INDEX IF NOT EXISTS idx_law_rel_v2_tgt  ON law_relationships_v2 (target_law_id);
CREATE INDEX IF NOT EXISTS idx_law_rel_v2_type ON law_relationships_v2 (relationship_type);


CREATE TABLE IF NOT EXISTS article_citations_v2 (
    id                  SERIAL PRIMARY KEY,
    source_article_id   INTEGER NOT NULL REFERENCES articles_v2(id) ON DELETE CASCADE,
    target_article_id   INTEGER REFERENCES articles_v2(id) ON DELETE CASCADE,
    target_ref          JSONB,                   -- unresolved: {law_ref, article_number}
    citation_type       TEXT,                    -- direct / implicit / see_also
    span_start          INTEGER,                 -- char offset in source text
    span_end            INTEGER,
    detected_by         TEXT,
    confidence          REAL,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_article_id, target_article_id)
);

CREATE INDEX IF NOT EXISTS idx_artcit_v2_src ON article_citations_v2 (source_article_id);
CREATE INDEX IF NOT EXISTS idx_artcit_v2_tgt ON article_citations_v2 (target_article_id);


-- ── 5. LEGAL CONCEPTS (ontology) ─────────────────────────────
CREATE TABLE IF NOT EXISTS legal_concepts_v2 (
    id                  SERIAL PRIMARY KEY,
    concept_id          TEXT UNIQUE NOT NULL,    -- canonical id (e.g. "criminal.drug.possession")
    name_ar             TEXT NOT NULL,
    name_en             TEXT,
    description         TEXT,
    parent_id           INTEGER REFERENCES legal_concepts_v2(id) ON DELETE SET NULL,
    aliases             TEXT[],                  -- ["حيازة مخدرات", "احتياز مخدر", ...]
    domain              TEXT,                    -- criminal / civil / family / ...
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_concepts_v2_aliases ON legal_concepts_v2 USING GIN (aliases);
CREATE INDEX IF NOT EXISTS idx_concepts_v2_parent  ON legal_concepts_v2 (parent_id);


CREATE TABLE IF NOT EXISTS article_concepts_v2 (
    article_id          INTEGER NOT NULL REFERENCES articles_v2(id) ON DELETE CASCADE,
    concept_id          INTEGER NOT NULL REFERENCES legal_concepts_v2(id) ON DELETE CASCADE,
    relevance           REAL DEFAULT 0.5,
    PRIMARY KEY (article_id, concept_id)
);

CREATE INDEX IF NOT EXISTS idx_artcon_v2_concept ON article_concepts_v2 (concept_id);


-- ── 6. CHUNKS for vector retrieval ───────────────────────────
CREATE TABLE IF NOT EXISTS chunks_v2 (
    id                  SERIAL PRIMARY KEY,
    chunk_id            TEXT UNIQUE NOT NULL,    -- "lawX_artY_chunkZ"
    law_id              INTEGER REFERENCES laws_v2(id) ON DELETE CASCADE,
    article_id          INTEGER REFERENCES articles_v2(id) ON DELETE CASCADE,
    attachment_id       INTEGER REFERENCES attachments_v2(id) ON DELETE CASCADE,
    content             TEXT NOT NULL,
    content_normalized  TEXT,
    chunk_type          TEXT,                    -- article / chapter_summary / attachment / preamble
    token_count         INTEGER,
    position            INTEGER,
    -- richer retrieval metadata
    law_type            TEXT,
    law_year            INTEGER,
    article_number      TEXT,
    legal_domain        TEXT,
    legal_concepts      TEXT[],
    keywords            TEXT[],
    -- embedding columns (pgvector if available; fallback JSONB)
    embedding           JSONB,                   -- {"model":"...","dim":N,"vec":[...]}
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chunks_v2_law        ON chunks_v2 (law_id);
CREATE INDEX IF NOT EXISTS idx_chunks_v2_article    ON chunks_v2 (article_id);
CREATE INDEX IF NOT EXISTS idx_chunks_v2_type       ON chunks_v2 (chunk_type);
CREATE INDEX IF NOT EXISTS idx_chunks_v2_domain     ON chunks_v2 (legal_domain);
CREATE INDEX IF NOT EXISTS idx_chunks_v2_concepts   ON chunks_v2 USING GIN (legal_concepts);
CREATE INDEX IF NOT EXISTS idx_chunks_v2_keywords   ON chunks_v2 USING GIN (keywords);
CREATE INDEX IF NOT EXISTS idx_chunks_v2_content_tr ON chunks_v2 USING GIN (content gin_trgm_ops);


-- ── 7. VERSIONS (amendment history per law) ──────────────────
CREATE TABLE IF NOT EXISTS law_versions_v2 (
    id                  SERIAL PRIMARY KEY,
    law_id              INTEGER NOT NULL REFERENCES laws_v2(id) ON DELETE CASCADE,
    version_number      INTEGER NOT NULL,
    effective_date      DATE,
    amending_law_id     INTEGER REFERENCES laws_v2(id) ON DELETE SET NULL,
    changes_summary     TEXT,
    full_text           TEXT,                    -- snapshot of that version
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (law_id, version_number)
);


-- ── 8. SUBJECTS (from Al-Meezan LawsBySubject tree) ──────────
CREATE TABLE IF NOT EXISTS subjects_v2 (
    id                  SERIAL PRIMARY KEY,
    almeezan_entry_id   INTEGER UNIQUE NOT NULL, -- e.g. 2542
    name                TEXT NOT NULL,           -- "التشريعات الجزائية"
    parent_id           INTEGER REFERENCES subjects_v2(id) ON DELETE SET NULL,
    path                TEXT,                    -- "التشريعات / الجزائية / ..."
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS law_subjects_v2 (
    law_id              INTEGER NOT NULL REFERENCES laws_v2(id) ON DELETE CASCADE,
    subject_id          INTEGER NOT NULL REFERENCES subjects_v2(id) ON DELETE CASCADE,
    PRIMARY KEY (law_id, subject_id)
);


-- ── 9. VERIFICATION LOG ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS verification_log_v2 (
    id                  SERIAL PRIMARY KEY,
    law_id              INTEGER NOT NULL REFERENCES laws_v2(id) ON DELETE CASCADE,
    verified_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status              TEXT NOT NULL            -- ok / diff / missing / error
                            CHECK (status IN ('ok','diff','missing','error')),
    diff_summary        TEXT,
    live_hash           CHAR(64),
    db_hash             CHAR(64),
    note                TEXT
);

CREATE INDEX IF NOT EXISTS idx_verif_v2_law ON verification_log_v2 (law_id);


-- ── Extensions ───────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS pg_trgm;
-- pgvector will be enabled later when we have model-specific embeddings.
-- CREATE EXTENSION IF NOT EXISTS vector;
