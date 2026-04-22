# 🚀 Al-Meezan Restoration — Runbook

دليل تشغيل خطوة بخطوة لاستكمال استعادة التشريعات الناقصة.

## ⚡ الحالة عند بدء هذا الـ runbook

- ✅ Enumeration مكتمل (9,293 تشريع مُفَهرس — 98.6%)
- ✅ 705 تشريع مفقود تم تحديدهم
- ✅ Schema v2 مُطبَّق (12 جدول)
- ✅ 167 تشريع مُحمَّل جزئياً (حوالي 35 منها مُدخل كاملاً)
- ⏳ باقي ~540 تشريع للتحميل + parse + ingest

## 📋 Prerequisites

قبل البدء تأكد:

```bash
# 1) Docker services شغّالة
docker ps --filter name=legal_ --format "{{.Names}}: {{.Status}}"
# يجب ترى: legal_db, legal_app, legal_redis, legal_nginx, legal_ollama

# 2) Python 3.10+ مع psycopg2
python -c "import psycopg2; print('OK')"

# 3) انت في مجلد المشروع
cd "C:\Users\sa2005599\Desktop\المساعد القانوني\الكود"
```

## 🎯 التشغيل — 4 أوامر متتالية

### Step 1 — تحميل الأولوية 1 (26 تشريع حديث قيد التطبيق)
**الوقت المتوقع:** 15-20 دقيقة  
**يستهدف:** 2015+ in-force laws

```bash
python -X utf8 scripts/meezan_downloader.py \
    --ids-file data/meezan_enum/priority1_recent_inforce.txt \
    --sleep 0.2
```

**إذا علق على تشريع معيّن (80+ قسم):**
- اضغط `Ctrl+C` وأعد التشغيل — سيتخطّى المُحمَّل ويستمر.

### Step 2 — تحميل الأولوية 2 (189 تشريع قديم قيد التطبيق)
**الوقت المتوقع:** 60-90 دقيقة

```bash
python -X utf8 scripts/meezan_downloader.py \
    --ids-file data/meezan_enum/priority2_old_inforce.txt \
    --sleep 0.2
```

### Step 3 — تحميل الأولوية 3 (490 تشريع ملغى — للكتلوج الكامل)
**الوقت المتوقع:** 2.5-3 ساعات  
**اختياري:** التشريعات الملغاة مفيدة للتتبع التاريخي لكنها ليست حرجة.

```bash
python -X utf8 scripts/meezan_downloader.py \
    --ids-file data/meezan_enum/priority3_canceled.txt \
    --sleep 0.2
```

### Step 4 — Parse + Ingest + Report
**الوقت المتوقع:** 15-30 دقيقة

```bash
# Parse كل ما تم تحميله → parsed.json
python -X utf8 scripts/meezan_parser.py --all-downloaded

# Ingest إلى laws_v2 (upsert — آمن إعادة تشغيله)
python -X utf8 scripts/meezan_ingester.py --all-parsed

# تقرير نهائي بكل التشريعات المستعادة
python -X utf8 scripts/meezan_report.py
# النتيجة: data/meezan_enum/RESTORATION_REPORT.md
```

### Step 5 (اختياري) — تحقق مع الموقع الحي

```bash
# تحقق عيّنة (أول 50 تشريع)
python -X utf8 scripts/meezan_verifier.py --all --limit 50 --sleep 0.3

# تحقق byte-for-byte مع مقارنة الـ content hash (أبطأ لكن أدق)
python -X utf8 scripts/meezan_verifier.py --all --deep --limit 50
```

## 📊 فحص التقدّم أثناء التشغيل

```bash
# عدد التشريعات المُحمَّلة
ls data/meezan_laws/ | wc -l

# عدد التشريعات المُدخلة في laws_v2
docker exec legal_db psql -U raguser -d ragdb -c \
    "SELECT COUNT(*) FROM laws_v2;"

# التشريعات الأخيرة بالـ DB
docker exec legal_db psql -U raguser -d ragdb -c \
    "SELECT almeezan_id, law_type, law_number, law_year, 
     (SELECT COUNT(*) FROM articles_v2 WHERE law_id=laws_v2.id) articles 
     FROM laws_v2 ORDER BY ingested_at DESC LIMIT 10;"

# سجل التحقق
docker exec legal_db psql -U raguser -d ragdb -c \
    "SELECT status, COUNT(*) FROM verification_log_v2 GROUP BY status;"
```

## 🔄 في حالة خطأ

### خطأ "تشريع معيّن يعلق":
```bash
# احذف مجلد التشريع العالق وأعد التشغيل — سيتخطاه
rm -rf data/meezan_laws/<LAW_ID>/
python scripts/meezan_downloader.py --ids-file ...
```

### خطأ "connection refused":
```bash
# أعد تشغيل Docker DB
docker restart legal_db
sleep 15
```

### خطأ "429 rate limit" من الميزان:
زد الـ sleep:
```bash
python scripts/meezan_downloader.py --ids-file ... --sleep 0.5
```

## ✅ التحقق النهائي

بعد اكتمال كل الخطوات:

```bash
# 1) عدد التشريعات في v2
docker exec legal_db psql -U raguser -d ragdb -c \
    "SELECT COUNT(*) AS laws,
     (SELECT COUNT(*) FROM articles_v2) AS articles,
     (SELECT COUNT(*) FROM attachments_v2) AS attachments,
     (SELECT COUNT(*) FROM law_relationships_v2) AS refs 
     FROM laws_v2;"

# النتيجة المتوقعة:
#  laws ≈ 705 + 35 existing = ~740 ingested from Al-Meezan
#  articles ≈ 8,000-15,000 (حسب حجم كل تشريع)
#  attachments ≈ 100-500
#  refs ≈ 2,000-5,000

# 2) افتح التقرير النهائي
# data/meezan_enum/RESTORATION_REPORT.md
```

## 🔮 الخطوة التالية (CP13)

بعد اكتمال هذا الـ runbook:

1. **Vector embeddings** — تفعيل pgvector extension ومعالجة chunks_v2 بـ nomic-embed-text.
2. **Concept ontology** — إضافة مفاهيم قانونية إلى `legal_concepts_v2` وربطها بالمواد.
3. **Relationship graph** — استخراج شامل للمراجع بين التشريعات عبر LLM.
4. **Router migration** — تحويل الـ router من `laws` (v1) إلى `laws_v2` كـ source-of-truth.

كل هذه مستقلة ويمكن تنفيذها بعد اكتمال هذا الـ runbook.

## 📞 في حالة التوقف المطوَّل

إذا أردت إيقاف التنفيذ وإكماله لاحقاً:
- `Ctrl+C` في أي مرحلة آمن — السكريبتات resumable.
- ملف state في `data/meezan_enum/meezan_enum_state*.json` يحفظ آخر نقطة.
- `meta.json` في كل `data/meezan_laws/<ID>/` يعني "تم تحميله بنجاح — سيُتخطّى".
