#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import sys, io
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
"""
scripts/check_env.py — فحص جاهزية البيئة للإنتاج
====================================================
يتحقق أن كل المتغيرات الضرورية موجودة ويختبر الاتصالات الفعلية.

الاستخدام:
  python scripts/check_env.py             # فحص كامل
  python scripts/check_env.py --no-db    # بدون فحص DB
  python scripts/check_env.py --no-redis # بدون فحص Redis

رموز الخروج:
  0 — جاهز للإنتاج
  1 — يوجد خطأ حرج
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

# ── تحميل .env ──────────────────────────────────────────────────
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8-sig").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            if _v.strip():
                os.environ[_k.strip()] = _v.strip()

# ── ألوان Terminal ──────────────────────────────────────────────
_TTY = sys.stdout.isatty()
GREEN  = "\033[92m" if _TTY else ""
RED    = "\033[91m" if _TTY else ""
YELLOW = "\033[93m" if _TTY else ""
BLUE   = "\033[94m" if _TTY else ""
RESET  = "\033[0m"  if _TTY else ""
BOLD   = "\033[1m"  if _TTY else ""

OK   = f"{GREEN}✅{RESET}"
FAIL = f"{RED}❌{RESET}"
WARN = f"{YELLOW}⚠️ {RESET}"
INFO = f"{BLUE}ℹ️ {RESET}"


# ════════════════════════════════════════════════════════════════
# متغيرات البيئة المطلوبة
# ════════════════════════════════════════════════════════════════

REQUIRED = [
    # (key, description, critical)
    ("DB_HOST",     "خادم قاعدة البيانات",          True),
    ("DB_NAME",     "اسم قاعدة البيانات",            True),
    ("DB_USER",     "مستخدم قاعدة البيانات",         True),
    ("DB_PASSWORD", "كلمة مرور قاعدة البيانات",      True),
    ("API_KEY",     "مفتاح API للأمان",              True),
    ("JWT_SECRET",  "سر JWT للمصادقة",               True),
    ("ALLOWED_ORIGINS", "أصول CORS المسموحة",        True),
]

OPTIONAL = [
    ("OPENAI_API_KEY",     "مفتاح OpenAI GPT",      False),
    ("GEMINI_API_KEY",     "مفتاح Google Gemini",    False),
    ("ANTHROPIC_API_KEY",  "مفتاح Anthropic Claude", False),
    ("REDIS_URL",          "رابط Redis",              False),
    ("OLLAMA_HOST",        "خادم Ollama المحلي",      False),
]

# القيم الافتراضية الخطرة التي يجب تغييرها
DANGEROUS_DEFAULTS = {
    "DB_PASSWORD": ["RAGsecret2024!", "password", "123456", "admin"],
    "JWT_SECRET":  ["mizan-dev-secret-change-in-prod", "secret", "change-me"],
    "API_KEY":     ["<generate: openssl rand -hex 32>", "test", "dev"],
}

# الحد الأدنى لطول المفاتيح الأمنية
MIN_SECRET_LENGTH = {
    "API_KEY":    32,
    "JWT_SECRET": 32,
}


# ════════════════════════════════════════════════════════════════
# فحوصات المتغيرات
# ════════════════════════════════════════════════════════════════

def check_env_vars() -> tuple[list[str], list[str], list[str]]:
    """يُعيد (errors, warnings, infos)."""
    errors   = []
    warnings = []
    infos    = []

    print(f"\n{BOLD}── فحص متغيرات البيئة ──────────────────────────{RESET}")

    # متغيرات مطلوبة
    for key, desc, critical in REQUIRED:
        val = os.getenv(key, "")
        if not val:
            msg = f"{desc} ({key}) مفقود"
            errors.append(msg)
            print(f"  {FAIL} {msg}")
        else:
            # فحص القيم الافتراضية الخطرة
            if key in DANGEROUS_DEFAULTS and val in DANGEROUS_DEFAULTS[key]:
                msg = f"{desc} ({key}) يستخدم قيمة افتراضية خطرة!"
                warnings.append(msg)
                print(f"  {WARN} {msg}")
            # فحص الطول الأدنى
            elif key in MIN_SECRET_LENGTH and len(val) < MIN_SECRET_LENGTH[key]:
                msg = f"{key} قصير جداً ({len(val)} حرف — الحد الأدنى: {MIN_SECRET_LENGTH[key]})"
                warnings.append(msg)
                print(f"  {WARN} {msg}")
            else:
                print(f"  {OK} {desc} ({key})")

    # متغيرات اختيارية
    print(f"\n{BOLD}── النماذج المتاحة ──────────────────────────────{RESET}")
    any_llm = False
    for key, desc, _ in OPTIONAL:
        val = os.getenv(key, "")
        if val and val not in ["<generate: openssl rand -hex 32>", ""]:
            print(f"  {OK} {desc} ({key})")
            if "KEY" in key:
                any_llm = True
        else:
            print(f"  {INFO} {desc} ({key}) — غير محدد")

    if not any_llm:
        # تحقق من Ollama
        ollama = os.getenv("OLLAMA_HOST", "")
        if not ollama:
            warnings.append("لا يوجد أي نموذج LLM مُعدّ (OpenAI/Gemini/Claude/Ollama)")
            print(f"\n  {WARN} تحذير: لا يوجد أي نموذج LLM مُعدّ")
        else:
            infos.append(f"Ollama فقط على {ollama} — تأكد من تشغيله")

    return errors, warnings, infos


# ════════════════════════════════════════════════════════════════
# فحص قاعدة البيانات
# ════════════════════════════════════════════════════════════════

async def check_database() -> tuple[bool, str]:
    """يختبر الاتصال بـ DB ويُعيد (success, message)."""
    try:
        import asyncpg
    except ImportError:
        return False, "asyncpg غير مثبت — pip install asyncpg"

    host = os.getenv("DB_HOST", "localhost")
    port = int(os.getenv("DB_PORT", "5432"))
    name = os.getenv("DB_NAME", "ragdb")
    user = os.getenv("DB_USER", "raguser")
    pwd  = os.getenv("DB_PASSWORD", "")

    try:
        conn = await asyncio.wait_for(
            asyncpg.connect(host=host, port=port, database=name, user=user, password=pwd),
            timeout=5.0,
        )
        # تحقق من الجداول الأساسية
        tables = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' "
            "AND tablename IN ('chunks','laws','answer_cache','learning_log')"
        )
        table_names = {r["tablename"] for r in tables}

        chunks_count = await conn.fetchval(
            "SELECT COUNT(*) FROM chunks WHERE is_active IS NULL OR is_active = TRUE"
        ) or 0
        await conn.close()

        missing = {"chunks", "laws"} - table_names
        if missing:
            return False, f"جداول مفقودة: {missing} — شغّل index_almeezan_v3.py"

        if chunks_count == 0:
            return False, "جدول chunks فارغ — شغّل index_almeezan_v3.py"

        return True, f"متصل ✓ | {chunks_count:,} chunk | جداول: {sorted(table_names)}"

    except asyncio.TimeoutError:
        return False, f"انتهت مهلة الاتصال بـ {host}:{port}/{name}"
    except Exception as exc:
        return False, str(exc)[:120]


# ════════════════════════════════════════════════════════════════
# فحص Redis
# ════════════════════════════════════════════════════════════════

async def check_redis() -> tuple[bool, str]:
    """يختبر الاتصال بـ Redis ويُعيد (success, message)."""
    redis_url = os.getenv("REDIS_URL", "")
    if not redis_url:
        return True, "غير مُعدّ — سيُستخدم In-Memory fallback"

    try:
        import redis.asyncio as aioredis
    except ImportError:
        return True, "redis غير مثبت — سيُستخدم In-Memory fallback"

    try:
        client = aioredis.from_url(redis_url, socket_connect_timeout=3)
        await asyncio.wait_for(client.ping(), timeout=3.0)
        info = await client.info("server")
        version = info.get("redis_version", "unknown")
        await client.aclose()
        return True, f"متصل ✓ | Redis {version}"
    except asyncio.TimeoutError:
        return False, f"انتهت مهلة الاتصال بـ Redis: {redis_url}"
    except Exception as exc:
        return False, str(exc)[:80]


# ════════════════════════════════════════════════════════════════
# فحص CORS
# ════════════════════════════════════════════════════════════════

def check_cors() -> list[str]:
    warnings = []
    origins = os.getenv("ALLOWED_ORIGINS", "")
    if not origins:
        return warnings
    for origin in origins.split(","):
        origin = origin.strip()
        if origin in ("*", "http://localhost:8000", "http://127.0.0.1:8000"):
            warnings.append(f"CORS origin خطير في الإنتاج: '{origin}'")
    return warnings


# ════════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════════

async def main(args) -> int:
    print(f"\n{BOLD}{'='*52}{RESET}")
    print(f"{BOLD}  فحص جاهزية البيئة — المساعد القانوني القطري{RESET}")
    print(f"{BOLD}{'='*52}{RESET}")

    all_errors   = []
    all_warnings = []

    # 1. متغيرات البيئة
    errors, warnings, infos = check_env_vars()
    all_errors   += errors
    all_warnings += warnings

    # 2. فحص CORS
    cors_warns = check_cors()
    all_warnings += cors_warns
    if cors_warns:
        for w in cors_warns:
            print(f"  {WARN} {w}")

    # 3. قاعدة البيانات
    if not args.no_db:
        print(f"\n{BOLD}── فحص قاعدة البيانات ───────────────────────────{RESET}")
        ok, msg = await check_database()
        if ok:
            print(f"  {OK} قاعدة البيانات: {msg}")
        else:
            print(f"  {FAIL} قاعدة البيانات: {msg}")
            all_errors.append(f"DB: {msg}")
    else:
        print(f"\n  {INFO} تخطّي فحص DB (--no-db)")

    # 4. Redis
    if not args.no_redis:
        print(f"\n{BOLD}── فحص Redis ─────────────────────────────────────{RESET}")
        ok, msg = await check_redis()
        if ok:
            print(f"  {OK} Redis: {msg}")
        else:
            print(f"  {WARN} Redis: {msg}")
            all_warnings.append(f"Redis: {msg}")
    else:
        print(f"\n  {INFO} تخطّي فحص Redis (--no-redis)")

    # ── التقرير النهائي ──────────────────────────────────────────
    print(f"\n{BOLD}{'='*52}{RESET}")
    if not all_errors and not all_warnings:
        print(f"  {GREEN}{BOLD}🚀 النظام جاهز للإنتاج!{RESET}")
        print(f"{'═'*52}\n")
        return 0

    if all_errors:
        print(f"  {RED}{BOLD}❌ غير جاهز — {len(all_errors)} خطأ حرج:{RESET}")
        for e in all_errors:
            print(f"     • {e}")

    if all_warnings:
        print(f"  {YELLOW}{BOLD}⚠️  {len(all_warnings)} تحذير يحتاج مراجعة:{RESET}")
        for w in all_warnings:
            print(f"     • {w}")

    print(f"{'═'*52}\n")
    return 1 if all_errors else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="فحص جاهزية البيئة للإنتاج")
    parser.add_argument("--no-db",    action="store_true", help="تخطّي فحص قاعدة البيانات")
    parser.add_argument("--no-redis", action="store_true", help="تخطّي فحص Redis")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args)))
