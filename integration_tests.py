# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║  اختبارات التكامل — المساعد القانوني القطري                   ║
║  الإصدار: 1.0                                                ║
╚══════════════════════════════════════════════════════════════════╝

المساعدة في التحقق من صحة عمل النظام بالكامل.

使用方法:
    # تشغيل جميع الاختبارات
    python integration_tests.py

    # تشغيل اختبار محدد
    python integration_tests.py --test database
    python integration_tests.py --test ollama
    python integration_tests.py --test api

    # وضع تفصيلي
    python integration_tests.py --verbose

متطلبات:
    pip install httpx asyncpg
"""

import asyncio
import httpx
import sys
import time
from pathlib import Path
from datetime import datetime

# ══════════════════════════════════════════════════════════
# إعدادات
# ══════════════════════════════════════════════════════════
API_BASE = os.getenv("API_BASE", "http://localhost:8000")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "database": os.getenv("DB_NAME", "ragdb"),
    "user": os.getenv("DB_USER", "raguser"),
    "password": os.getenv("DB_PASSWORD", "RAGsecret2024!"),
}

import os

# ══════════════════════════════════════════════════════════
# تحميل .env
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
# ألوان console
# ══════════════════════════════════════════════════════════
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def print_header(text):
    print(f"\n{Colors.HEADER}{'='*60}{Colors.ENDC}")
    print(f"{Colors.BOLD}{text}{Colors.ENDC}")
    print(f"{Colors.HEADER}{'='*60}{Colors.ENDC}\n")

def print_test(name, passed, details=""):
    status = f"{Colors.OKGREEN}✓ PASS{Colors.ENDC}" if passed else f"{Colors.FAIL}✗ FAIL{Colors.ENDC}"
    print(f"  [{status}] {name}")
    if details:
        print(f"         {details}")

# ══════════════════════════════════════════════════════════
# اختبارات قاعدة البيانات
# ══════════════════════════════════════════════════════════
async def test_database():
    """اختبار الاتصال بقاعدة البيانات"""
    print_header("🗄️ اختبار قاعدة البيانات")

    try:
        import asyncpg
        conn = await asyncpg.connect(**DB_CONFIG)
        print_test("الاتصال بقاعدة البيانات", True)

        # فحص الجداول
        tables = await conn.fetch("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_name IN ('chunks', 'laws', 'learning_log', 'answer_cache')
        """)
        table_names = [t['table_name'] for t in tables]
        print_test("جدول chunks موجود", 'chunks' in table_names)
        print_test("جدول laws موجود", 'laws' in table_names)
        print_test("جدول learning_log موجود", 'learning_log' in table_names)

        # فحص المقاطع
        total_chunks = await conn.fetchval("SELECT COUNT(*) FROM chunks")
        active_chunks = await conn.fetchval(
            "SELECT COUNT(*) FROM chunks WHERE is_active = TRUE OR is_active IS NULL"
        )
        print_test(f"عدد المقاطع الكلي ({total_chunks})", total_chunks > 0)
        print_test(f"المقاطع النشطة ({active_chunks})", active_chunks > 0)

        # فحص المقاطع بدون embedding
        missing_emb = await conn.fetchval("""
            SELECT COUNT(*) FROM chunks
            WHERE embedding IS NULL OR LENGTH(CAST(embedding AS TEXT)) < 10
        """)
        print_test(f"المقاطع بدون embedding ({missing_emb})", missing_emb == 0,
                  "⚠️ يجب إصلاحها" if missing_emb > 0 else "✓ جميعها لها embedding")

        # فحص القوانين
        total_laws = await conn.fetchval("SELECT COUNT(*) FROM laws")
        print_test(f"عدد القوانين ({total_laws})", total_laws > 0)

        await conn.close()
        return True

    except Exception as e:
        print_test("الاتصال بقاعدة البيانات", False, str(e))
        return False

# ══════════════════════════════════════════════════════════
# اختبارات Ollama
# ══════════════════════════════════════════════════════════
async def test_ollama():
    """اختبار Ollama"""
    print_header("🤖 اختبار Ollama")

    async with httpx.AsyncClient(timeout=30) as client:
        # فحص حالة Ollama
        try:
            resp = await client.get(f"{OLLAMA_HOST}/api/tags")
            ollama_ok = resp.status_code == 200
            print_test("Ollama متصل", ollama_ok)
            if not ollama_ok:
                return False
        except Exception as e:
            print_test("Ollama متصل", False, str(e))
            return False

        # فحص النماذج
        try:
            models = resp.json().get("models", [])
            model_names = [m.get("name", "") for m in models]
            print_test("نموذج qwen متوفر", any("qwen" in m.lower() for m in model_names),
                      str(model_names[:3]))
            print_test("نموذج nomic-embed-text متوفر", any("nomic" in m.lower() for m in model_names),
                      str(model_names[:3]))
        except Exception as e:
            print_test("فحص النماذج", False, str(e))

        # اختبار embedding
        try:
            t0 = time.time()
            resp = await client.post(
                f"{OLLAMA_HOST}/api/embeddings",
                json={"model": "nomic-embed-text", "prompt": "اختبار Embedding"}
            )
            emb_time = time.time() - t0
            emb_ok = resp.status_code == 200 and "embedding" in resp.json()
            print_test(f"Embedding يعمل ({emb_time:.2f}s)", emb_ok)
        except Exception as e:
            print_test("Embedding يعمل", False, str(e))

        # اختبار chat
        try:
            t0 = time.time()
            resp = await client.post(
                f"{OLLAMA_HOST}/api/chat",
                json={
                    "model": "qwen2.5:1.5b",
                    "messages": [{"role": "user", "content": "قل: مرحبا"}],
                    "stream": False,
                    "options": {"num_predict": 10}
                }
            )
            chat_time = time.time() - t0
            chat_ok = resp.status_code == 200 and resp.json().get("message")
            print_test(f"Chat يعمل ({chat_time:.2f}s)", chat_ok)
        except Exception as e:
            print_test("Chat يعمل", False, str(e))

    return True

# ══════════════════════════════════════════════════════════
# اختبارات API
# ══════════════════════════════════════════════════════════
async def test_api():
    """اختبار واجهات API"""
    print_header("🌐 اختبار واجهات API")

    async with httpx.AsyncClient(timeout=60) as client:
        base_url = API_BASE

        # اختبار health
        try:
            resp = await client.get(f"{base_url}/api/v1/health")
            health_ok = resp.status_code == 200
            print_test("Health endpoint", health_ok)
            if health_ok:
                data = resp.json()
                print(f"         الإصدار: {data.get('version', '?')}")
                print(f"         الميزات: {len(data.get('features', []))}")
        except Exception as e:
            print_test("Health endpoint", False, str(e))

        # اختبار API query
        try:
            resp = await client.post(
                f"{base_url}/api/v1/query/",
                json={"query": "ما عقوبة السرقة في قطر؟", "model": "ollama"}
            )
            query_ok = resp.status_code == 200
            print_test("API Query (ollama)", query_ok)
            if query_ok:
                data = resp.json()
                has_answer = bool(data.get("answer", ""))
                print_test("الإجابة موجودة", has_answer)
                print(f"         الثقة: {data.get('confidence', 0)}%")
        except Exception as e:
            print_test("API Query (ollama)", False, str(e))

        # اختبار debug_search
        try:
            resp = await client.get(
                f"{base_url}/api/v1/debug_search",
                params={"q": "طلاق وحضانة"}
            )
            debug_ok = resp.status_code == 200
            print_test("Debug Search", debug_ok)
            if debug_ok:
                data = resp.json()
                print(f"         المقاطع: {data.get('chunks_raw', 0)}")
                print(f"         ذات الصلة: {data.get('relevant_after_score_filter', 0)}")
        except Exception as e:
            print_test("Debug Search", False, str(e))

        # اختبار المحادثة
        try:
            resp = await client.post(
                f"{base_url}/api/v1/query/",
                json={"query": "هلا", "session_id": "test_session"}
            )
            chat_ok = resp.status_code == 200
            print_test("Chat (greeting)", chat_ok)
        except Exception as e:
            print_test("Chat (greeting)", False, str(e))

    return True

# ══════════════════════════════════════════════════════════
# اختبارات الجودة
# ══════════════════════════════════════════════════════════
async def test_quality():
    """اختبار جودة الإجابات"""
    print_header("📊 اختبار جودة الإجابات")

    test_questions = [
        ("ما عقوبة السرقة في قطر؟", "criminal"),
        ("شروط الطلاق وحضانة الأطفال", "family"),
        ("فصل تعسفي من العمل", "labor"),
        ("مكافأة نهاية الخدمة", "labor"),
    ]

    async with httpx.AsyncClient(timeout=120) as client:
        results = []

        for question, expected_domain in test_questions:
            print(f"\n  اختبار: {question[:30]}...")

            try:
                t0 = time.time()
                resp = await client.post(
                    f"{API_BASE}/api/v1/query/",
                    json={"query": question, "model": "ollama"}
                )
                elapsed = time.time() - t0

                if resp.status_code == 200:
                    data = resp.json()
                    answer = data.get("answer", "")
                    confidence = data.get("confidence", 0)
                    sources_count = len(data.get("sources", []))

                    results.append({
                        "question": question,
                        "success": True,
                        "elapsed": elapsed,
                        "confidence": confidence,
                        "sources": sources_count,
                        "has_answer": len(answer) > 50,
                    })

                    print_test(
                        f"إجابة ناجحة (ثقة: {confidence}%, مصادر: {sources_count})",
                        confidence > 0
                    )
                else:
                    results.append({"question": question, "success": False})
                    print_test(f"فشل الطلب", False)

            except Exception as e:
                results.append({"question": question, "success": False, "error": str(e)})
                print_test(f"استثناء", False, str(e))

        # ملخص
        success_count = sum(1 for r in results if r.get("success"))
        avg_confidence = sum(r.get("confidence", 0) for r in results if r.get("success")) / max(success_count, 1)
        avg_sources = sum(r.get("sources", 0) for r in results if r.get("success")) / max(success_count, 1)

        print(f"\n  📈 ملخص:")
        print(f"     • نسبة النجاح: {success_count}/{len(results)} ({success_count/len(results)*100:.0f}%)")
        print(f"     • متوسط الثقة: {avg_confidence:.1f}%")
        print(f"     • متوسط المصادر: {avg_sources:.1f}")

        return success_count >= len(results) * 0.75

# ══════════════════════════════════════════════════════════
# تشغيل جميع الاختبارات
# ══════════════════════════════════════════════════════════
async def run_all_tests(verbose=False):
    """تشغيل جميع الاختبارات"""
    print_header("🚀 اختبارات التكامل الشاملة")
    print(f"⏰ الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🌐 API: {API_BASE}")
    print(f"🤖 Ollama: {OLLAMA_HOST}")

    results = {}

    # 1. قاعدة البيانات
    results['database'] = await test_database()

    # 2. Ollama
    results['ollama'] = await test_ollama()

    # 3. API
    results['api'] = await test_api()

    # 4. الجودة
    results['quality'] = await test_quality()

    # النتيجة النهائية
    print_header("📋 النتيجة النهائية")
    total = len(results)
    passed = sum(1 for v in results.values() if v)

    for name, passed_test in results.items():
        status = f"{Colors.OKGREEN}✓{Colors.ENDC}" if passed_test else f"{Colors.FAIL}✗{Colors.ENDC}"
        print(f"  {status} {name}")

    print(f"\n{Colors.BOLD}النتيجة: {passed}/{total} اختبارات ناجحة{Colors.ENDC}")

    if passed == total:
        print(f"\n{Colors.OKGREEN}🎉 جميع الاختبارات ناجحة!{Colors.ENDC}")
        return 0
    elif passed >= total * 0.5:
        print(f"\n{Colors.WARNING}⚠️ بعض الاختبارات فشلت، راجع التفاصيل{Colors.ENDC}")
        return 1
    else:
        print(f"\n{Colors.FAIL}❌ فشل كبير — تحقق من النظام{Colors.ENDC}")
        return 2

# ══════════════════════════════════════════════════════════
# التشغيل
# ══════════════════════════════════════════════════════════
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="اختبارات التكامل")
    parser.add_argument("--test", "-t", choices=["database", "ollama", "api", "quality"],
                       help="تشغيل اختبار محدد")
    parser.add_argument("--verbose", "-v", action="store_true", help="وضع تفصيلي")
    args = parser.parse_args()

    if args.test == "database":
        asyncio.run(test_database())
    elif args.test == "ollama":
        asyncio.run(test_ollama())
    elif args.test == "api":
        asyncio.run(test_api())
    elif args.test == "quality":
        asyncio.run(test_quality())
    else:
        exit_code = asyncio.run(run_all_tests(verbose=args.verbose))
        sys.exit(exit_code)
