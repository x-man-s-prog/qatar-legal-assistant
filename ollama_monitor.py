# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║  نظام مراقبة أداء Ollama — المساعد القانوني القطري              ║
║  الإصدار: 1.0                                                ║
╚══════════════════════════════════════════════════════════════════╝

راقب أداء Ollama في الوقت الفعلي وكتشف المشاكل.

使用方法:
    # تشغيل المراقبة المستمرة (كل 30 ثانية)
    python ollama_monitor.py --watch

    # اختبار أداء واحد
    python ollama_monitor.py --test

    # مراقبة مع تنبيه
    python ollama_monitor.py --watch --alert --threshold 5

متطلبات:
    pip install httpx psutil
"""

import asyncio
import httpx
import time
import os
import sys
import json
from pathlib import Path
from datetime import datetime
from collections import deque
import argparse

# ══════════════════════════════════════════════════════════
# إعدادات
# ══════════════════════════════════════════════════════════
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
API_BASE = os.getenv("API_BASE", "http://localhost:8000")
CHECK_INTERVAL = 30  # ثانية
HISTORY_SIZE = 60  # آخر 60 قياس

# ══════════════════════════════════════════════════════════
# ألوان
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

# ══════════════════════════════════════════════════════════
# تخزين السجل
# ══════════════════════════════════════════════════════════
class MetricsStore:
    def __init__(self, max_size=100):
        self.embed_times = deque(maxlen=max_size)
        self.chat_times = deque(maxlen=max_size)
        self.errors = deque(maxlen=max_size)
        self.uptimes = deque(maxlen=max_size)
        self.timestamps = deque(maxlen=max_size)

    def add(self, embed_time, chat_time, error=None, uptime=0):
        self.embed_times.append(embed_time)
        self.chat_times.append(chat_time)
        self.errors.append(error)
        self.uptimes.append(uptime)
        self.timestamps.append(datetime.now())

    def avg_embed_time(self):
        return sum(self.embed_times) / len(self.embed_times) if self.embed_times else 0

    def avg_chat_time(self):
        return sum(self.chat_times) / len(self.chat_times) if self.chat_times else 0

    def error_rate(self):
        if not self.timestamps:
            return 0
        return sum(1 for e in self.errors if e) / len(self.errors) * 100

    def p95_embed(self):
        if len(self.embed_times) < 5:
            return 0
        sorted_times = sorted(self.embed_times)
        return sorted_times[int(len(sorted_times) * 0.95)]

    def p95_chat(self):
        if len(self.chat_times) < 5:
            return 0
        sorted_times = sorted(self.chat_times)
        return sorted_times[int(len(sorted_times) * 0.95)]

    def is_slow(self, threshold=5):
        """هل الأداء بطيء؟"""
        return self.avg_chat_time() > threshold

    def recent_errors(self):
        return [e for e in self.errors[-10:] if e]

# ══════════════════════════════════════════════════════════
# اختبارات الأداء
# ══════════════════════════════════════════════════════════
async def test_embedding(sentence: str = "اختبار أداء Embedding للنظام القانوني") -> float:
    """اختبار سرعة embedding — يُعيد الوقت بالثواني"""
    async with httpx.AsyncClient(timeout=60) as client:
        t0 = time.time()
        try:
            resp = await client.post(
                f"{OLLAMA_HOST}/api/embeddings",
                json={"model": "nomic-embed-text", "prompt": sentence}
            )
            elapsed = time.time() - t0
            if resp.status_code == 200:
                return elapsed
            return -1
        except Exception as e:
            return -1

async def test_chat(question: str = "ما هي عقوبة السرقة؟") -> tuple[float, str]:
    """اختبار سرعة chat — يُعيد (الوقت، الإجابة)"""
    async with httpx.AsyncClient(timeout=180) as client:
        t0 = time.time()
        try:
            resp = await client.post(
                f"{OLLAMA_HOST}/api/chat",
                json={
                    "model": "qwen2.5:1.5b",
                    "messages": [{"role": "user", "content": question}],
                    "stream": False,
                    "options": {"num_predict": 50, "temperature": 0.1}
                }
            )
            elapsed = time.time() - t0
            if resp.status_code == 200:
                data = resp.json()
                answer = data.get("message", {}).get("content", "")[:50]
                return elapsed, answer
            return -1, ""
        except Exception as e:
            return -1, str(e)

async def get_ollama_stats() -> dict:
    """جلب إحصائيات Ollama"""
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(f"{OLLAMA_HOST}/api/ps")
            if resp.status_code == 200:
                return resp.json()
        except:
            pass
    return {}

# ══════════════════════════════════════════════════════════
# الطباعة
# ══════════════════════════════════════════════════════════
def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_header():
    print(f"\n{Colors.HEADER}{'═'*60}{Colors.ENDC}")
    print(f"{Colors.BOLD}🧠 نظام مراقبة Ollama — المساعد القانوني{Colors.ENDC}")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{Colors.HEADER}{'═'*60}{Colors.ENDC}\n")

def print_status(status: str, icon: str = "●"):
    icons = {
        "ok": f"{Colors.OKGREEN}{icon} OK{Colors.ENDC}",
        "slow": f"{Colors.WARNING}{icon} بطيء{Colors.ENDC}",
        "error": f"{Colors.FAIL}{icon} خطأ{Colors.ENDC}",
    }
    print(f"  الحالة: {icons.get(status, status)}")

def print_metrics(store: MetricsStore):
    print(f"\n{Colors.OKCYAN}📊 الإحصائيات:{Colors.ENDC}")

    # Embedding
    print(f"\n  Embedding (nomic-embed-text):")
    avg_emb = store.avg_embed_time()
    p95_emb = store.p95_embed()
    emb_status = f"{Colors.OKGREEN}✓{Colors.ENDC}" if avg_emb < 2 else f"{Colors.WARNING}⚠{Colors.ENDC}" if avg_emb < 5 else f"{Colors.FAIL}✗{Colors.ENDC}"
    print(f"    {emb_status} المتوسط: {avg_emb:.2f}s | P95: {p95_emb:.2f}s | آخر: {store.embed_times[-1]:.2f}s")

    # Chat
    print(f"\n  Chat (qwen2.5:1.5b):")
    avg_chat = store.avg_chat_time()
    p95_chat = store.p95_chat()
    chat_status = f"{Colors.OKGREEN}✓{Colors.ENDC}" if avg_chat < 10 else f"{Colors.WARNING}⚠{Colors.ENDC}" if avg_chat < 30 else f"{Colors.FAIL}✗{Colors.ENDC}"
    print(f"    {chat_status} المتوسط: {avg_chat:.2f}s | P95: {p95_chat:.2f}s | آخر: {store.chat_times[-1]:.2f}s")

    # الأخطاء
    error_rate = store.error_rate()
    error_icon = f"{Colors.OKGREEN}✓{Colors.ENDC}" if error_rate == 0 else f"{Colors.WARNING}⚠{Colors.ENDC}" if error_rate < 10 else f"{Colors.FAIL}✗{Colors.ENDC}"
    print(f"\n  {error_icon} معدل الأخطاء: {error_rate:.1f}%")

    # التنبيهات الأخيرة
    recent = store.recent_errors()
    if recent:
        print(f"\n{Colors.WARNING}⚠️ التنبيهات:{Colors.ENDC}")
        for err in recent[-3:]:
            print(f"    • {err[:60]}")

def print_model_info():
    """عرض معلومات النموذج"""
    stats = asyncio.run(get_ollama_stats())
    if stats:
        models = stats.get("models", [])
        if models:
            print(f"\n{Colors.OKBLUE}🤖 النماذج المحملة:{Colors.ENDC}")
            for m in models[:3]:
                name = m.get("name", "?")
                size = m.get("size", 0)
                size_mb = size / (1024 * 1024)
                print(f"    • {name} ({size_mb:.0f} MB)")

# ══════════════════════════════════════════════════════════
# المراقبة المستمرة
# ══════════════════════════════════════════════════════════
async def watch_mode(interval: int = 30, threshold: float = 5, alert: bool = False):
    """المراقبة المستمرة"""
    store = MetricsStore(HISTORY_SIZE)
    last_alert_time = 0

    print(f"\n{Colors.OKCYAN}🔍 بدء المراقبة (كل {interval} ثانية){Colors.ENDC}")
    print("    اضغط Ctrl+C للإيقاف\n")

    while True:
        try:
            # اختبار
            print(f"\n⏱️  {datetime.now().strftime('%H:%M:%S')} — جاري الاختبار...")

            emb_time = await test_embedding()
            chat_time, answer = await test_chat()

            # تخزين
            error = None
            if emb_time < 0:
                error = f"Embedding فشل"
            if chat_time < 0:
                error = f"Chat فشل: {answer}"

            store.add(emb_time if emb_time > 0 else 0,
                     chat_time if chat_time > 0 else 0,
                     error)

            # عرض
            clear_screen()
            print_header()

            status = "ok"
            if error:
                status = "error"
            elif store.is_slow(threshold):
                status = "slow"

            print_status(status)

            # تنبيه
            if alert and status in ("slow", "error"):
                now = time.time()
                if now - last_alert_time > 300:  # تنبيه كل 5 دقائق
                    last_alert_time = now
                    print(f"\n{Colors.WARNING}🔔 تنبيه: الأداء {'بطيء' if status == 'slow' else 'به أخطاء'}{Colors.ENDC}")

            print_metrics(store)
            print_model_info()

            await asyncio.sleep(interval)

        except KeyboardInterrupt:
            print(f"\n\n{Colors.OKGREEN}تم إيقاف المراقبة{Colors.ENDC}")
            break
        except Exception as e:
            print(f"\n{Colors.FAIL}خطأ: {e}{Colors.ENDC}")
            await asyncio.sleep(5)

# ══════════════════════════════════════════════════════════
# اختبار أداء واحد
# ══════════════════════════════════════════════════════════
async def test_performance():
    """اختبار أداء واحد مع تقرير مفصل"""
    print(f"\n{Colors.HEADER}{'═'*60}{Colors.ENDC}")
    print(f"{Colors.BOLD}🧪 اختبار أداء Ollama{Colors.ENDC}")
    print(f"{Colors.HEADER}{'═'*60}{Colors.ENDC}\n")

    print("📡 فحص الاتصال...")
    stats = await get_ollama_stats()
    if stats:
        print(f"  {Colors.OKGREEN}✓{Colors.ENDC} Ollama متصل")
        models = stats.get("models", [])
        print(f"  النماذج المحملة: {len(models)}")
    else:
        print(f"  {Colors.FAIL}✗{Colors.ENDC} Ollama غير متصل")
        return

    # اختبار Embedding
    print(f"\n🔤 اختبار Embedding (3 محاولات)...")
    embed_results = []
    for i in range(3):
        t = await test_embedding()
        if t > 0:
            embed_results.append(t)
            print(f"    محاولة {i+1}: {t:.2f}s")
        else:
            print(f"    محاولة {i+1}: {Colors.FAIL}فشل{Colors.ENDC}")
        await asyncio.sleep(0.5)

    if embed_results:
        avg = sum(embed_results) / len(embed_results)
        print(f"  {Colors.OKGREEN}✓{Colors.ENDC} المتوسط: {avg:.2f}s")
    else:
        print(f"  {Colors.FAIL}✗{Colors.ENDC} فشل كامل")

    # اختبار Chat
    print(f"\n💬 اختبار Chat (3 محاولات)...")
    chat_results = []
    for i in range(3):
        t, answer = await test_chat()
        if t > 0:
            chat_results.append(t)
            print(f"    محاولة {i+1}: {t:.2f}s")
        else:
            print(f"    محاولة {i+1}: {Colors.FAIL}فشل{Colors.ENDC}")
        await asyncio.sleep(1)

    if chat_results:
        avg = sum(chat_results) / len(chat_results)
        print(f"  {Colors.OKGREEN}✓{Colors.ENDC} المتوسط: {avg:.2f}s")
    else:
        print(f"  {Colors.FAIL}✗{Colors.FAIL} فشل كامل")

    # التوصيات
    print(f"\n{Colors.HEADER}{'═'*60}{Colors.ENDC}")
    print(f"{Colors.BOLD}📋 التوصيات:{Colors.ENDC}")
    print(f"{Colors.HEADER}{'═'*60}{Colors.ENDC}")

    if embed_results:
        avg_emb = sum(embed_results) / len(embed_results)
        if avg_emb < 1:
            print(f"  {Colors.OKGREEN}✓{Colors.ENDC} سرعة Embedding ممتازة")
        elif avg_emb < 3:
            print(f"  {Colors.WARNING}⚠{Colors.ENDC} سرعة Embedding مقبولة")
        else:
            print(f"  {Colors.FAIL}✗{Colors.ENDC} سرعة Embedding بطيئة — فكر في:")
            print(f"     • استخدام نموذج embedding أخف")
            print(f"     • زيادة موارد النظام")

    if chat_results:
        avg_chat = sum(chat_results) / len(chat_results)
        if avg_chat < 5:
            print(f"  {Colors.OKGREEN}✓{Colors.ENDC} سرعة Chat ممتازة")
        elif avg_chat < 15:
            print(f"  {Colors.WARNING}⚠{Colors.ENDC} سرعة Chat مقبولة")
        else:
            print(f"  {Colors.FAIL}✗{Colors.ENDC} سرعة Chat بطيئة — فكر في:")
            print(f"     • استخدام نموذج أصغر (qwen2.5:0.5b)")
            print(f"     • تقليل num_ctx")
            print(f"     • زيادة RAM")

# ══════════════════════════════════════════════════════════
# تقرير JSON
# ══════════════════════════════════════════════════════════
async def generate_report():
    """توليد تقرير JSON"""
    print("📊 توليد التقرير...")

    embed_times = []
    chat_times = []

    for _ in range(5):
        t = await test_embedding()
        if t > 0:
            embed_times.append(t)
        await asyncio.sleep(0.5)

    for _ in range(5):
        t, _ = await test_chat()
        if t > 0:
            chat_times.append(t)
        await asyncio.sleep(1)

    report = {
        "timestamp": datetime.now().isoformat(),
        "embed": {
            "samples": embed_times,
            "avg": sum(embed_times) / len(embed_times) if embed_times else 0,
            "min": min(embed_times) if embed_times else 0,
            "max": max(embed_times) if embed_times else 0,
        },
        "chat": {
            "samples": chat_times,
            "avg": sum(chat_times) / len(chat_times) if chat_times else 0,
            "min": min(chat_times) if chat_times else 0,
            "max": max(chat_times) if chat_times else 0,
        },
        "status": "healthy" if sum(embed_times) / max(len(embed_times), 1) < 3 else "slow"
    }

    print(json.dumps(report, indent=2))
    return report

# ══════════════════════════════════════════════════════════
# التشغيل
# ══════════════════════════════════════════════════════════
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="مراقبة Ollama")
    parser.add_argument("--watch", "-w", action="store_true", help="المراقبة المستمرة")
    parser.add_argument("--test", "-t", action="store_true", help="اختبار أداء واحد")
    parser.add_argument("--report", "-r", action="store_true", help="تقرير JSON")
    parser.add_argument("--interval", "-i", type=int, default=30, help="فترة المراقبة (ثانية)")
    parser.add_argument("--threshold", type=float, default=5, help="عتبة البطء (ثانية)")
    parser.add_argument("--alert", "-a", action="store_true", help="تنبيهات")

    args = parser.parse_args()

    if args.watch:
        asyncio.run(watch_mode(args.interval, args.threshold, args.alert))
    elif args.report:
        asyncio.run(generate_report())
    elif args.test:
        asyncio.run(test_performance())
    else:
        print("""
╔══════════════════════════════════════════════════════════════════╗
║              نظام مراقبة Ollama — المساعد القانوني                  ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  الاستخدام:                                                       ║
║    python ollama_monitor.py --test      # اختبار أداء واحد         ║
║    python ollama_monitor.py --watch     # مراقبة مستمرة          ║
║    python ollama_monitor.py --report    # تقرير JSON              ║
║                                                                  ║
║  الخيارات:                                                        ║
║    --watch        المراقبة المستمرة                               ║
║    --test         اختبار أداء واحد                                ║
║    --report       تقرير JSON                                      ║
║    --interval 30  فترة المراقبة (ثانية)                           ║
║    --threshold 5  عتبة البطء (ثانية)                              ║
║    --alert        تنبيهات                                        ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
        """)
