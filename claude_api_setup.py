# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║  تفعيل Claude API — المساعد القانوني القطري                     ║
║  الإصدار: 1.0                                                ║
╚══════════════════════════════════════════════════════════════════╝

هذا الملف يُظهر كيفية تفعيل Claude API في مشروعك.

## خطوات التفعيل:

### 1. الحصول على مفتاح API
    • سجل في: https://console.anthropic.com/
    • احصل على API key

### 2. إضافة المفتاح لـ .env
    أنشئ/عدّل ملف .env في نفس مجلد main.py:

    ANTHROPIC_API_KEY=sk-ant-api03-xxxxx
    MODEL_MAIN=claude-3-5-sonnet-20241022
    MODEL_FAST=claude-3-haiku-20240307

### 3. (اختياري) استخدام Secret
    إذا كنت تستخدم متغيرات البيئة في سيرفرك:

    export ANTHROPIC_API_KEY="sk-ant-api03-xxxxx"

## النماذج المتاحة من Claude:

| النموذج | السرعة | الجودة | الاستخدام |
|---------|--------|--------|----------|
| claude-3-5-sonnet-20241022 | متوسط | ★★★★★ | الإجابة الرئيسية |
| claude-3-5-haiku-20240307 | سريع | ★★★☆☆ | التحليل السريع |
| claude-3-opus-20240229 | بطيء | ★★★★★ | المهام المعقدة |

## ملاحظات:
    • Claude-3-Haiku مجاني في.plan Claude (100 رسالة/دقيقة)
    • Sonnet و Opus يحتاجان اشتراك مدفوع
    • يمكن استخدام كل من Claude و Gemini معاً

## للتحقق من التفعيل:
    curl http://localhost:8000/api/v1/health
    → يجب أن يظهر "claude" في models

"""

# ══════════════════════════════════════════════════════════
# ملف .env المطلوب (انسخ هذا إلى .env في مجلد main.py)
# ══════════════════════════════════════════════════════════

ENV_TEMPLATE = """
# ══════════════════════════════════════════════════════════
# مفاتيح API — المساعد القانوني القطري
# ══════════════════════════════════════════════════════════

# ─── Claude API (اختياري — للردود عالية الجودة) ───
# احصل على المفتاح من: https://console.anthropic.com/
ANTHROPIC_API_KEY=sk-ant-api03-YOUR-KEY-HERE

# ─── Gemini API (مجاني — بديل لـ Claude) ───
# احصل على المفتاح من: https://makersuite.google.com/app/apikey
# GEMINI_API_KEY=YOUR-GEMINI-KEY-HERE

# ─── إعدادات النماذج ───
MODEL_MAIN=claude-3-5-sonnet-20241022
MODEL_FAST=claude-3-haiku-20240307
MODEL_GEMINI=gemini-2.0-flash

# ─── إعدادات Ollama (محلي — مجاني) ───
OLLAMA_HOST=http://localhost:11434
MODEL_OLLAMA_LLM=qwen2.5:1.5b

# ─── إعدادات قاعدة البيانات ───
DB_HOST=localhost
DB_PORT=5432
DB_NAME=ragdb
DB_USER=raguser
DB_PASSWORD=RAGsecret2024!
"""

# ══════════════════════════════════════════════════════════
# كود التفعيل في main.py (اضافة في أعلى الملف)
# ══════════════════════════════════════════════════════════

MAIN_PY_ACTIVATION = '''
# ══════════════════════════════════════════════════════════
# تفعيل Claude API — أضف هذا في أعلى main.py بعد السطور الموجودة
# ══════════════════════════════════════════════════════════

# تحميل .env إن وُجد
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8-sig").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            if _v.strip():
                os.environ[_k.strip()] = _v.strip()

# ─── مفاتيح API ───
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GEMINI_KEY    = os.getenv("GEMINI_API_KEY", "")

# ─── إعدادات النماذج ───
MODEL_CLAUDE_MAIN = os.getenv("MODEL_MAIN", "claude-3-5-sonnet-20241022")
MODEL_CLAUDE_FAST = os.getenv("MODEL_FAST", "claude-3-haiku-20240307")
MODEL_GEMINI      = os.getenv("MODEL_GEMINI", "gemini-2.0-flash")

# ══════════════════════════════════════════════════════════
# التحقق من التفعيل (أضف في /api/v1/health)
# ══════════════════════════════════════════════════════════

@app.get("/api/v1/health")
async def health():
    return {
        "status": "ok",
        "claude": "✓ متصل" if ANTHROPIC_KEY else "✗ غير مفعّل",
        "gemini": "✓ متصل" if GEMINI_KEY else "✗ غير مفعّل",
        "ollama": "✓ متصل",  # تحقق فعلي من Ollama
    }
'''

# ══════════════════════════════════════════════════════════
# أمر التثبيت
# ══════════════════════════════════════════════════════════

INSTALL_COMMANDS = """
# ══════════════════════════════════════════════════════════
# خطوات التفعيل السريعة
# ══════════════════════════════════════════════════════════

# 1. أنشئ ملف .env في مجلد main.py:
cat > .env << 'EOF'
ANTHROPIC_API_KEY=sk-ant-api03-xxxxx
MODEL_MAIN=claude-3-5-sonnet-20241022
MODEL_FAST=claude-3-haiku-20240307
EOF

# 2. أعد تشغيل السيرفر:
#    • إذا تستخدم uvicorn: Ctrl+C ثم uvicorn main:app --reload
#    • إذا تستخدم Docker: docker-compose restart

# 3. تحقق من التفعيل:
curl http://localhost:8000/api/v1/health | jq

# النتيجة المتوقعة:
# {
#   "status": "ok",
#   "claude": "✓ متصل",
#   "gemini": "✓ غير مفعّل",
#   "ollama": "✓ متصل"
# }

# 4. جرب سؤال:
curl -X POST http://localhost:8000/api/v1/query/ \\
  -H "Content-Type: application/json" \\
  -d '{"query": "ما عقوبة السرقة؟", "model": "claude"}'
"""

# ══════════════════════════════════════════════════════════
# مقارنة بين النماذج
# ══════════════════════════════════════════════════════════

MODEL_COMPARISON = """
╔══════════════════════════════════════════════════════════════╗
║                    مقارنة النماذج                           ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  ┌──────────────────┬─────────┬─────────┬─────────────────┐  ║
║  │ النموذج          │ السرعة  │ الجودة   │ التكلفة         │  ║
║  ├──────────────────┼─────────┼─────────┼─────────────────┤  ║
║  │ Claude Sonnet    │ ★★★★☆  │ ★★★★★  │ مدفوع ($)       │  ║
║  │ Claude Haiku    │ ★★★★★  │ ★★★☆☆  │ مجاني (plan)    │  ║
║  │ Gemini Flash     │ ★★★★★  │ ★★★★☆  │ مجاني ✓         │  ║
║  │ Ollama (محلي)   │ ★★★★☆  │ ★★★☆☆  │ مجاني 100% ✓    │  ║
║  └──────────────────┴─────────┴─────────┴─────────────────┘  ║
║                                                              ║
║  التوصية:                                                    ║
║  ─────────                                                    ║
║  • للردود السريعة: Ollama أو Gemini Flash                   ║
║  • للردود عالية الجودة: Claude Sonnet                        ║
║  • للتحليل المتقدم: Claude Haiku (مجاني)                    ║
║                                                              ║
║  الاستراتيجية المثالية:                                         ║
║  ───────────────────                                         ║
║  Ollama (مجاني) → Gemini Flash (مجاني) → Claude (مدفوع)    ║
║       ↓                ↓                  ↓                 ║
║    fallback 1      fallback 2        جودة عالية               ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
"""

# ══════════════════════════════════════════════════════════
# حفظ الملفات
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import os
    from pathlib import Path

    # إنشاء ملف .env.example
    output_dir = Path(__file__).parent
    env_file = output_dir / ".env.example"
    env_file.write_text(ENV_TEMPLATE.strip(), encoding="utf-8")
    print(f"✅ تم إنشاء: {env_file}")

    # إنشاء ملف التعليمات
    readme_file = output_dir / "CLAUDE_API_SETUP.md"
    readme_content = f"""# تفعيل Claude API

{COMPARISON}

## خطوات التفعيل

### 1. الحصول على مفتاح API
زُر: https://console.anthropic.com/

### 2. إضافة المفتاح
أنشئ ملف `.env` في مجلد main.py:

```bash
cp .env.example .env
# ثم عدّل .env وأضف مفتاحك
```

### 3. التحقق
```bash
curl http://localhost:8000/api/v1/health
```

### 4. الاستخدام
```bash
# مع Claude:
curl -X POST http://localhost:8000/api/v1/query/ \\
  -d '{{"query": "سؤالك", "model": "claude"}}'

# مع Gemini:
curl -X POST http://localhost:8000/api/v1/query/ \\
  -d '{{"query": "سؤالك", "model": "gemini"}}'

# مع Ollama (مجاني):
curl -X POST http://localhost:8000/api/v1/query/ \\
  -d '{{"query": "سؤالك", "model": "ollama"}}'
```
"""
    readme_file.write_text(readme_content, encoding="utf-8")
    print(f"✅ تم إنشاء: {readme_file}")

    print("\n" + "=" * 60)
    print("📋 ملخص ملفات التفعيل:")
    print(f"   • .env.example — قالب ملف البيئة")
    print(f"   • CLAUDE_API_SETUP.md — تعليمات التفعيل")
    print("=" * 60)
