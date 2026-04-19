# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║  سكريبت إصلاح المقاطع بدون Embedding — RAG Legal Assistant    ║
║  الإصدار: 1.0                                                ║
╚══════════════════════════════════════════════════════════════════╝

المشكلة: 41 chunk بدون embedding → لا تظهر في البحث المتجهي
الحل: إعادة توليد الـ embeddings للنصوص المفقودة

使用方法:
    python fix_missing_embeddings.py

متطلبات:
    pip install httpx asyncpg
    Ollama يعمل محلياً (默认: http://localhost:11434)
"""

import asyncio
import httpx
import os
import sys
from pathlib import Path
from datetime import datetime

# ══════════════════════════════════════════════════════════
# إعدادات الاتصال
# ══════════════════════════════════════════════════════════
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
EMBEDDING_MODEL = "nomic-embed-text"

# إعدادات قاعدة البيانات (نفس إعدادات main.py)
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "database": os.getenv("DB_NAME", "ragdb"),
    "user": os.getenv("DB_USER", "raguser"),
    "password": os.getenv("DB_PASSWORD", "RAGsecret2024!"),
}

# ══════════════════════════════════════════════════════════
# تحميل .env إذا وُجد
# ══════════════════════════════════════════════════════════
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8-sig").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            if _v.strip():
                os.environ[_k.strip()] = _v.strip()

# ══════════════════════════════════════════════════════════
# دوال الـ Embedding
# ══════════════════════════════════════════════════════════
async def get_embedding(text: str) -> list[float] | None:
    """يحصل على embedding من Ollama"""
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{OLLAMA_HOST}/api/embeddings",
                json={"model": EMBEDDING_MODEL, "prompt": text[:2000]}
            )
            if response.status_code == 200:
                return response.json()["embedding"]
            else:
                print(f"  ⚠️ خطأ في Ollama: {response.status_code}")
                return None
    except Exception as e:
        print(f"  ⚠️ استثناء: {e}")
        return None

# ══════════════════════════════════════════════════════════
# دوال قاعدة البيانات
# ══════════════════════════════════════════════════════════
async def get_missing_embeddings(conn) -> list[dict]:
    """يجلب المقاطع بدون embedding"""
    rows = await conn.fetch("""
        SELECT id, law_name, article_number, content, source
        FROM chunks
        WHERE embedding IS NULL
           OR embedding = '[]'
           OR LENGTH(CAST(embedding AS TEXT)) < 10
        LIMIT 100
    """)
    return [dict(r) for r in rows]

async def get_missing_embeddings_count(conn) -> int:
    """يحسب عدد المقاطع بدون embedding"""
    count = await conn.fetchval("""
        SELECT COUNT(*)
        FROM chunks
        WHERE embedding IS NULL
           OR embedding = '[]'
           OR LENGTH(CAST(embedding AS TEXT)) < 10
    """)
    return count or 0

async def update_embedding(conn, chunk_id: int, embedding: list[float]):
    """يحدث embedding للمقطع"""
    emb_str = "[" + ",".join(map(str, embedding)) + "]"
    await conn.execute(
        "UPDATE chunks SET embedding = $1::vector WHERE id = $2",
        emb_str, chunk_id
    )

# ══════════════════════════════════════════════════════════
# دالة الإصلاح الرئيسية
# ══════════════════════════════════════════════════════════
async def fix_missing_embeddings(batch_size: int = 10, dry_run: bool = False):
    """
    يُعيد توليد embeddings للمقاطع المفقودة

    المدخلات:
        batch_size: عدد المقاطع في كل دفعة (افتراضي: 10)
        dry_run: True للاختبار فقط بدون حفظ
    """
    print("=" * 60)
    print("🔧 إصلاح المقاطع بدون Embedding")
    print("=" * 60)

    # الاتصال بقاعدة البيانات
    try:
        import asyncpg
        conn = await asyncpg.connect(**DB_CONFIG)
        print(f"✅ اتصال قاعدة البيانات ناجح")
    except Exception as e:
        print(f"❌ فشل الاتصال بقاعدة البيانات: {e}")
        return

    # فحص Ollama
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{OLLAMA_HOST}/api/tags")
            if resp.status_code != 200:
                print(f"❌ Ollama غير متصل")
                return
            print(f"✅ Ollama متصل")
    except Exception as e:
        print(f"❌ Ollama غير متصل: {e}")
        await conn.close()
        return

    # فحص النموذج
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            test_emb = await client.post(
                f"{OLLAMA_HOST}/api/embeddings",
                json={"model": EMBEDDING_MODEL, "prompt": "اختبار"}
            )
            if test_emb.status_code != 200:
                print(f"❌ نموذج {EMBEDDING_MODEL} غير متوفر")
                print(f"   للتثبيت: ollama pull {EMBEDDING_MODEL}")
                await conn.close()
                return
            print(f"✅ نموذج {EMBEDDING_MODEL} متوفر")
    except Exception as e:
        print(f"❌ خطأ في نموذج {EMBEDDING_MODEL}: {e}")
        await conn.close()
        return

    # جلب عدد المقاطع المفقودة
    missing_count = await get_missing_embeddings_count(conn)
    print(f"\n📊 المقاطع بدون embedding: {missing_count}")

    if missing_count == 0:
        print("✅ لا توجد مقاطع تحتاج إصلاح!")
        await conn.close()
        return

    if dry_run:
        print("🧪 وضع الاختبار (dry-run) — لن يتم الحفظ")
        print("-" * 40)

    # جلب المقاطع
    chunks = await get_missing_embeddings(conn)
    print(f"📥 جلب {len(chunks)} مقطع للإصلاح")

    # الإصلاح
    success_count = 0
    fail_count = 0
    start_time = datetime.now()

    for i, chunk in enumerate(chunks, 1):
        chunk_id = chunk["id"]
        content = chunk["content"][:2000]  # قص للـ limit
        law_name = chunk.get("law_name", "")[:30]

        print(f"\n[{i}/{len(chunks)}] معالجة: {law_name}... (ID: {chunk_id})")

        # الحصول على embedding
        embedding = await get_embedding(content)

        if embedding:
            if not dry_run:
                await update_embedding(conn, chunk_id, embedding)
            success_count += 1
            print(f"  ✅ embedding جاهز ({len(embedding)} dimensions)")
        else:
            fail_count += 1
            print(f"  ❌ فشل في توليد embedding")

        # انتظار لتجنب الضغط على Ollama
        await asyncio.sleep(0.5)

        # رسالة كل 10 مقاطع
        if i % 10 == 0:
            elapsed = (datetime.now() - start_time).total_seconds()
            rate = i / elapsed if elapsed > 0 else 0
            remaining = (missing_count - i) / rate if rate > 0 else 0
            print(f"\n📈 التقدم: {i}/{missing_count} | "
                  f"النجاح: {success_count} | الفشل: {fail_count} | "
                  f"الوقت المتبقي: {remaining:.0f} ثانية")

    # النتيجة النهائية
    elapsed_total = (datetime.now() - start_time).total_seconds()
    print("\n" + "=" * 60)
    print("📋 نتيجة الإصلاح:")
    print(f"   ✅ نجح: {success_count}")
    print(f"   ❌ فشل: {fail_count}")
    print(f"   ⏱️  الوقت الكلي: {elapsed_total:.1f} ثانية")
    print("=" * 60)

    # فحص متبقي
    remaining = await get_missing_embeddings_count(conn)
    if remaining > 0:
        print(f"\n⚠️  لا يزال هناك {remaining} مقطع بدون embedding")
        print(f"   شغّل السكريبت مرة أخرى لإصلاح الباقي")
    else:
        print("\n🎉 تم إصلاح جميع المقاطع بنجاح!")

    await conn.close()

# ══════════════════════════════════════════════════════════
# التشغيل
# ══════════════════════════════════════════════════════════
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="إصلاح المقاطع بدون Embedding")
    parser.add_argument("--batch", "-b", type=int, default=10,
                       help="حجم الدفعة (افتراضي: 10)")
    parser.add_argument("--dry-run", "-d", action="store_true",
                       help="اختبار فقط بدون حفظ")
    args = parser.parse_args()

    asyncio.run(fix_missing_embeddings(
        batch_size=args.batch,
        dry_run=args.dry_run
    ))
