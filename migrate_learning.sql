-- ═══════════════════════════════════════════════════════
-- نظام التعلم التراكمي — جداول قاعدة البيانات
-- ═══════════════════════════════════════════════════════

-- امتداد البحث بالتشابه الثلاثي (يُسرّع ILIKE بـ 10-100x ويدعم الفازي)
CREATE EXTENSION IF NOT EXISTS pg_trgm;
-- فهرس GIN على محتوى المقاطع (يُفعّل البحث السريع + similarity())
CREATE INDEX IF NOT EXISTS chunks_content_trgm ON chunks USING GIN(content gin_trgm_ops);

-- 1. سجل كل المحادثات (نجاح + فشل)
CREATE TABLE IF NOT EXISTS learning_log (
    id            SERIAL PRIMARY KEY,
    session_id    TEXT NOT NULL,
    query         TEXT NOT NULL,
    query_type    TEXT NOT NULL DEFAULT 'legal',   -- legal | greeting | followup | off_topic
    result_type   TEXT NOT NULL DEFAULT 'unknown', -- found | not_found | low_relevance | cached
    answer        TEXT,                            -- الإجابة المُعطاة (أول 1000 حرف)
    top_score     FLOAT DEFAULT 0,                 -- أعلى نسبة صلة من الاسترجاع
    sources_count INT DEFAULT 0,                   -- عدد المصادر المُستخدمة
    model_used    TEXT,                            -- gemini | claude | ollama
    feedback      SMALLINT DEFAULT NULL,           -- +1 إعجاب | -1 عدم إعجاب | NULL لم يُقيَّم
    feedback_note TEXT,                            -- ملاحظة اختيارية من المستخدم
    latency_ms    INT DEFAULT 0,                   -- وقت الاستجابة بالملّي ثانية
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_learning_log_created    ON learning_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_learning_log_result     ON learning_log (result_type);
CREATE INDEX IF NOT EXISTS idx_learning_log_feedback   ON learning_log (feedback);
CREATE INDEX IF NOT EXISTS idx_learning_log_session    ON learning_log (session_id);

-- 2. ذاكرة التخزين المؤقت للأجوبة الناجحة
CREATE TABLE IF NOT EXISTS answer_cache (
    id            SERIAL PRIMARY KEY,
    query_norm    TEXT NOT NULL UNIQUE,  -- السؤال بعد التطبيع (للمطابقة)
    query_orig    TEXT NOT NULL,         -- السؤال الأصلي (للعرض)
    answer        TEXT NOT NULL,         -- الإجابة الكاملة
    sources_json  JSONB,                 -- المصادر المستخدمة
    hit_count     INT DEFAULT 1,         -- كم مرة خُدِم من الكاش
    quality_score FLOAT DEFAULT 0,       -- متوسط التقييمات (+1 / -1)
    model_used    TEXT,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    last_hit_at   TIMESTAMPTZ DEFAULT NOW(),
    expires_at    TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '30 days')
);

CREATE INDEX IF NOT EXISTS idx_cache_expires ON answer_cache (expires_at);

-- 3. اقتراحات التحسين (يولّدها Gemini أسبوعياً)
CREATE TABLE IF NOT EXISTS improvement_suggestions (
    id              SERIAL PRIMARY KEY,
    period_start    TIMESTAMPTZ NOT NULL,
    period_end      TIMESTAMPTZ NOT NULL,
    total_queries   INT DEFAULT 0,
    failed_queries  INT DEFAULT 0,
    failure_rate    FLOAT DEFAULT 0,
    root_causes     JSONB,              -- أسباب الفشل الرئيسية
    missing_keywords JSONB,             -- كلمات مفتاحية ناقصة مقترحة
    prompt_suggestion TEXT,             -- اقتراح تعديل الـ prompt
    examples_added  INT DEFAULT 0,      -- عدد الأمثلة المضافة للـ few-shot
    applied         BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 4. أمثلة few-shot (الأجوبة النموذجية المُجمَّعة)
CREATE TABLE IF NOT EXISTS fewshot_examples (
    id            SERIAL PRIMARY KEY,
    query         TEXT NOT NULL,
    answer        TEXT NOT NULL,
    category      TEXT,                 -- عمل | أسرة | جنائي | تجاري | ...
    quality_score FLOAT DEFAULT 1.0,   -- 0-1 (تُحسَّن بالتقييمات)
    use_count     INT DEFAULT 0,        -- كم مرة حُقنت في الـ prompt
    active        BOOLEAN DEFAULT TRUE,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fewshot_active ON fewshot_examples (active, quality_score DESC);
