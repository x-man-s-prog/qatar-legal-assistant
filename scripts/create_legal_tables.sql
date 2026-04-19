-- Structured legal tables schema
CREATE TABLE IF NOT EXISTS legal_tables (
    id SERIAL PRIMARY KEY,
    parent_law_name TEXT NOT NULL,
    parent_law_number TEXT,
    parent_law_year TEXT,
    law_url TEXT,
    source TEXT DEFAULT 'almeezan',
    source_type TEXT DEFAULT 'statute_table',  -- statute_table, appendix, schedule, salary_table
    table_number TEXT,
    appendix_number TEXT,
    schedule_number TEXT,
    band_number TEXT,
    item_number TEXT,
    row_order INTEGER DEFAULT 0,
    item_title TEXT,
    item_text TEXT,
    raw_text TEXT,
    normalized_text TEXT,
    content_hash TEXT,
    fetch_status TEXT DEFAULT 'pending',  -- pending, fetched, failed, partial
    completeness_status TEXT DEFAULT 'unknown',  -- complete, partial, reference_only, missing
    is_amendment BOOLEAN DEFAULT FALSE,
    amending_law_name TEXT,
    amending_law_number TEXT,
    amending_law_year TEXT,
    fetched_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(content_hash)
);

CREATE INDEX IF NOT EXISTS idx_legal_tables_law ON legal_tables(parent_law_number, parent_law_year);
CREATE INDEX IF NOT EXISTS idx_legal_tables_type ON legal_tables(source_type);
CREATE INDEX IF NOT EXISTS idx_legal_tables_table_num ON legal_tables(table_number);
CREATE INDEX IF NOT EXISTS idx_legal_tables_status ON legal_tables(fetch_status);
CREATE INDEX IF NOT EXISTS idx_legal_tables_hash ON legal_tables(content_hash);

-- Also add source_type column to chunks if not exists
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='chunks' AND column_name='source_type') THEN
        ALTER TABLE chunks ADD COLUMN source_type TEXT DEFAULT 'statute_text';
    END IF;
END $$;
