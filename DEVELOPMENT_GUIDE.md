# 📘 دليل التطوير الشامل - المساعد القانوني القطري MAX Edition

## 🎯 نظرة عامة

هذا الدليل يوثّق نظام **المساعد القانوني القطري - MAX Edition** بشكل شامل، بما في ذلك:
- البنية المعمارية
- جميع الوحدات والمكونات
- واجهات API
- دليل التثبيت والتشغيل
- دليل المساهمة

---

## 📁 هيكل الملفات

```
enhanced_system/
├── enhanced_main.py                  # التطبيق الرئيسي (FastAPI)
├── config.py                         # الإعدادات
├── query_engine.py                   # محرك توسيع الاستعلام
├── context_manager.py                # إدارة السياق
├── intelligence_layer.py             # طبقة الذكاء
├── domain_relevance_engine.py        # محرك relevance القانوني
└── ultra_linguistic_engine.py         # محرك الفهم اللغوي المتقدم

scripts/
├── fix_missing_embeddings.py         # إصلاح embeddings المفقودة
├── integration_tests.py              # اختبارات التكامل
├── ollama_monitor.py                 # مراقبة Ollama
└── claude_api_setup.py              # إعداد Claude API
```

---

## 🏗️ البنية المعمارية

### المخطط العام

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           المساعد القانوني القطري                            │
│                              MAX Edition                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐    ┌──────────────┐    ┌──────────────────┐              │
│  │   FastAPI   │───▶│ UltraEngine  │───▶│  Query Expansion  │              │
│  │  Endpoint   │    │ (Linguistic) │    │     Engine        │              │
│  └─────────────┘    └──────────────┘    └────────┬─────────┘              │
│                                                  │                         │
│  ┌─────────────┐    ┌──────────────┐             ▼                         │
│  │  Context    │◀───│ Intelligence │◀────────────────────────┐           │
│  │  Manager    │    │   Layer      │◀──────────────────────────┤           │
│  └──────┬──────┘    └──────────────┘                           │           │
│         │                                                          │           │
│         ▼                                                          ▼           │
│  ┌─────────────┐    ┌──────────────┐    ┌──────────────────┐              │
│  │   Session   │    │   Domain     │    │   Ollama/GPT     │              │
│  │   Storage   │    │  Relevance   │    │   (LLM Backend)  │              │
│  └─────────────┘    └──────────────┘    └────────┬─────────┘              │
│                                                    │                         │
│                                                    ▼                         │
│                                            ┌──────────────────┐              │
│                                            │    PostgreSQL    │              │
│                                            │    + pgvector   │              │
│                                            └──────────────────┘              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 📦 الوحدات التفصيلية

### 1. ultra_linguistic_engine.py - محرك الفهم اللغوي المتقدم

#### الفئة الرئيسية: `UltraLinguisticEngine`

```python
from ultra_linguistic_engine import UltraLinguisticEngine

engine = UltraLinguisticEngine()

# تحليل سؤال قانوني
result = engine.analyze_legal_query("شنو عقوبة السرقة في قطر؟")
```

#### الميزات الرئيسية:

| الميزة | الوصف |
|--------|-------|
| كشف اللهجة | تحديد اللهجة (خليجية، مصرية، شامية، عراقية، فصحى) |
| استخراج القصد | فهم قصد المستخدم (استفسار، استشارة، إلخ) |
| كشف الغموض | تحديد الأسئلة الغامضة |
| التوسع الدلالي | تحويل العامية إلى مصطلحات قانونية |
| كشف الكيانات | استخراج القوانين، المواد، الأسماء، المبالغ |

#### القيم المرجعة:

```python
@dataclass
class LegalQueryAnalysis:
    dialect: str                    # اللهجة المكتشفة
    dialect_confidence: float       # ثقة كشف اللهجة
    intent: str                     # القصد (طلب_معلومات، استشارة_قانونية، إلخ)
    legal_terms: List[str]          # المصطلحات القانونية
    colloquial_terms: List[str]     # مصطلحات عامية
    entities: Dict[str, List[str]]  # الكيانات المستخرجة
    has_ambiguity: bool             # هل السؤال غامض
    ambiguity_details: List[str]     # تفاصيل الغموض
    search_queries: List[str]        # استعلامات البحث الموسعة
    domain: str                     # المجال القانوني
```

---

### 2. query_engine.py - محرك توسيع الاستعلام

#### الفئة الرئيسية: `EnhancedQueryExpansionEngine`

```python
from query_engine import EnhancedQueryExpansionEngine

engine = EnhancedQueryExpansionEngine()

# توسيع استعلام
result = await engine.expand("شنو عقوبة السرقة؟")
```

#### الميزات:

| الميزة | الوصف |
|--------|-------|
| توسيع الاستعلام | إضافة مصطلحات قانونية متعلقة |
| تحويل العامية | من لهجات مختلفة إلى فصحى قانونية |
| كشف القصد | تحديد نوع السؤال القانوني |
| استخراج الكيانات | استخراج القوانين والأرقام والمبالغ |

#### مصطلحات العامية إلى القانونية:

```python
# أمثلة على التحويل
"شنو عقوبة" → "ما هي عقوبة"
"بنسبة لـ" → "بخصوص"
"تبي" → "تريد"
"محتاج أفهم" → "أريد توضيح"
"إجازة" → "vacation"
```

---

### 3. context_manager.py - إدارة السياق

#### الفئة الرئيسية: `EnhancedContextManager`

```python
from context_manager import EnhancedContextManager

manager = EnhancedContextManager()

# إضافة رسالة
manager.add_message(
    session_id="user_123",
    role="user",
    content="ما عقوبة السرقة؟",
    query_analysis={"intent": "طلب_معلومات"},
    sources=[{"law": "قانون العقوبات", "article": "234"}]
)

# بناء السياق
context = manager.build_context_prefix("user_123", include_linguistic=True)
```

#### طبقات السياق:

| الطبقة | الوصف |
|--------|-------|
| `session_summary` | ملخص المحادثة |
| `legal_facts` | الحقائق القانونية المستخرجة |
| `linguistic_context` | سياق اللهجة والقصد |
| `recent_messages` | آخر 5 رسائل |
| `extracted_entities` | الكيانات المستخرجة |

---

### 4. intelligence_layer.py - طبقة الذكاء

#### الفئة الرئيسية: `EnhancedIntelligenceLayer`

```python
from intelligence_layer import (
    EnhancedIntelligenceLayer,
    FormattingContext,
    IntentCategory,
    DialectType,
    ResponseStyle
)

layer = EnhancedIntelligenceLayer()

# تنسيق إجابة
context = FormattingContext(
    dialect=DialectType.GULF,
    intent=IntentCategory.INFORMATION_REQUEST,
    response_style=ResponseStyle.FORMAL_LEGAL
)

answer = layer.format_response(
    answer="الإجابة القانونية...",
    sources=[...],
    formatting_context=context
)
```

#### أنماط الإجابة:

| الأسلوب | الوصف | الاستخدام |
|---------|-------|-----------|
| `FORMAL_LEGAL` | قانوني رسمي | الإجابات الرسمية |
| `SIMPLIFIED` | مبسّط | شرح مبسط للمستخدمين |
| `DETAILED` | مفصّل | التحليلات القانونية |
| `QUICK_ANSWER` | سريع | إجابات قصيرة |

---

### 5. domain_relevance_engine.py - محرك relevance القانوني

#### الفئة الرئيسية: `EnhancedDomainRelevanceEngine`

```python
from domain_relevance_engine import (
    EnhancedDomainRelevanceEngine,
    LegalDomain
)

engine = EnhancedDomainRelevanceEngine()

# تصنيف المجال
analysis = engine.classify_domain(
    query="ما حقوق الموظف عند الفصل؟",
    sources=[...]
)

print(f"المجال: {analysis.primary_domain.value}")
```

#### المجالات القانونية المدعومة:

| المجال | القيمة | قوانين مرتبطة |
|--------|--------|--------------|
| جنائي | CRIMINAL | قانون العقوبات |
| مدني | CIVIL | قانون المعاملات المدنية |
| تجاري | COMMERCIAL | قانون التجارة |
| أسري | FAMILY | قانون الأسرة |
| عمالي | LABOR | قانون العمل |
| عقاري | PROPERTY | قانون الشهر العقاري |
| إداري | ADMINISTRATIVE | قانون الخدمة المدنية |
| إلكتروني | CYBER | قانون الجرائم المعلوماتية |

#### معادلة حساب Relevance:

```python
score_final = (
    base_score       × 0.35
    + domain_match   × 0.25
    + law_priority   × 0.20
    + concept_cov    × 0.15
    + year_factor    × 0.05
)
```

---

## 🌐 واجهات API

### نقطة النهاية الرئيسية: `/api/v1/query/`

#### الطلب:

```json
POST /api/v1/query/
{
    "query": "شنو عقوبة السرقة في قطر؟",
    "session_id": "user_123",
    "model": "ollama",
    "max_sources": 5,
    "include_reasoning": false
}
```

#### الاستجابة:

```json
{
    "answer": "📜 الإجابة القانونية\n\n**عقوبة السرقة:**\n\nوفقاً لقانون العقوبات القطري...",
    "sources": [
        {
            "title": "كتاب العقوبات",
            "content": "يعاقب بالحبس كل من ارتكب جريمة السرقة...",
            "law": "قانون العقوبات",
            "article": "234",
            "similarity": 0.89
        }
    ],
    "confidence": 87.5,
    "session_id": "user_123",
    "dialect": "خليجية",
    "dialect_confidence": 0.85,
    "intent": "طلب_معلومات",
    "domain": "جنائي",
    "response_time": 2.45
}
```

### نقطة النهاية الصحية: `/health`

```json
GET /health
{
    "status": "ok",
    "version": "3.0-MAX",
    "database": "✓",
    "ollama": "✓",
    "claude": "✓ غير مفعّل",
    "features": [
        "enhanced_query_engine",
        "enhanced_context_manager",
        "enhanced_intelligence_layer",
        "enhanced_domain_relevance",
        "ultra_linguistic_engine"
    ]
}
```

### نقطة النهاية للتصحيح: `/api/v1/debug_search`

```json
GET /api/v1/debug_search?q=طلاق وحضانة
{
    "query": "طلاق وحضانة",
    "expanded_queries": [
        "طلاق وحضانة",
        "انفصال وزوجية",
        "حضانة أطفال"
    ],
    "dialect": "خليجية",
    "dialect_confidence": 0.72,
    "intent": "طلب_معلومات",
    "domain": "أسري",
    "chunks_total": 45,
    "chunks_raw": 45,
    "relevant_after_score_filter": 12,
    "final_chunks": 10
}
```

---

## 🔧 التثبيت والتشغيل

### المتطلبات:

- Python 3.9+
- PostgreSQL 14+ with pgvector extension
- Ollama (for local LLM)
- 8GB+ RAM

### خطوات التثبيت:

```bash
# 1. استنساخ المشروع
git clone <repo-url>
cd legal-assistant

# 2. إنشاء بيئة افتراضية
python -m venv venv
source venv/bin/activate  # Linux/Mac
# أو
.\venv\Scripts\activate  # Windows

# 3. تثبيت المتطلبات
pip install -r requirements.txt

# 4. إعداد قاعدة البيانات
psql -U postgres -c "CREATE DATABASE ragdb;"
psql -U postgres -d ragdb -c "CREATE EXTENSION vector;"

# 5. نسخ ملف البيئة
cp .env.example .env
# ثم قم بتعديل .env حسب إعداداتك

# 6. تشغيل Ollama
ollama serve
ollama pull qwen2.5:1.5b
ollama pull nomic-embed-text

# 7. تشغيل التطبيق
python enhanced_main.py
```

### ملف .env:

```env
# Database
DB_HOST=localhost
DB_PORT=5432
DB_NAME=ragdb
DB_USER=raguser
DB_PASSWORD=RAGsecret2024!

# Ollama
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen2.5:1.5b
OLLAMA_EMBED_MODEL=nomic-embed-text

# Optional: Claude API
ANTHROPIC_API_KEY=sk-ant-api03-xxxxx

# Optional: Gemini
GEMINI_API_KEY=your-key-here
```

---

## 🧪 الاختبارات

### تشغيل جميع الاختبارات:

```bash
python scripts/integration_tests.py
```

### تشغيل اختبار محدد:

```bash
# اختبار قاعدة البيانات
python scripts/integration_tests.py --test database

# اختبار Ollama
python scripts/integration_tests.py --test ollama

# اختبار API
python scripts/integration_tests.py --test api

# اختبار الجودة
python scripts/integration_tests.py --test quality
```

### مراقبة Ollama:

```bash
# اختبار أداء واحد
python scripts/ollama_monitor.py --test

# مراقبة مستمرة
python scripts/ollama_monitor.py --watch

# مراقبة مع تنبيهات
python scripts/ollama_monitor.py --watch --alert
```

---

## 📊 الميزات المتقدمة

### 1. كشف اللهجات

```python
#Supported dialects:
# - خليجية (Gulf)
# - مصرية (Egyptian)
# - شامية (Levantine)
# - عراقية (Iraqi)
# - فصحى (Modern Standard)

dialect = detect_dialect("شنو عقوبة السرقة؟")
# Returns: {"dialect": "خليجية", "confidence": 0.85}
```

### 2. تحليل القصد

```python
from intelligence_layer import IntentCategory

#Categories:
# - INFORMATION_REQUEST: طلب معلومات
# - LEGAL_ADVICE: استشارة قانونية
# - PROCEDURAL_GUIDANCE: إرشاد إجرائي
# - RIGHTS_INQUIRY: استفسار حقوق
# - OBLIGATIONS_INQUIRY: استفسار التزامات
# - CASE_ANALYSIS: تحليل حالة
```

### 3. كشف الغموض

```python
# الأسئلة الغامضة يتم كشفها تلقائياً
ambiguity_warnings = layer.detect_ambiguities(
    query="ما الحكم؟",
    answer="...",
    sources=[...]
)
# Warnings:
# - استخدام غير محدد لـ 'شيء'
# - لا توجد مصادر قانونية موثوقة
```

---

## 🔒 الأمان

### التوصيات:

1. **لا تخزن بيانات حساسة**: النظام يُعالج استفسارات قانونية عامة
2. **تحقق من المدخلات**: استخدم Pydantic للتحقق من صحة البيانات
3. **إدارة الجلسات**: نظّف جلسات المستخدمين بانتظام
4. **النسخ الاحتياطي**: احتفظ بنسخ احتياطية من قاعدة البيانات

---

## 🤝 المساهمة

### خطوات المساهمة:

1. Fork المشروع
2. أنشئ فرع جديد (`git checkout -b feature/amazing-feature`)
3. Commit التغييرات (`git commit -m 'Add amazing feature'`)
4. Push إلى الفرع (`git push origin feature/amazing-feature`)
5. افتح Pull Request

### معايير الكود:

- اتبع PEP 8
- استخدم type hints
- اكتب docstrings لكل الدوال
- أضف اختبارات للميزات الجديدة

---

## 📞 الدعم

للأسئلة والمشاكل:
- افتح issue على GitHub
- تواصل مع فريق التطوير

---

## 📄 الرخصة

MIT License

---

**نتمنى لك تجربة ممتازة مع المساعد القانوني القطري - MAX Edition!** ⚖️
