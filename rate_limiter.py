# -*- coding: utf-8 -*-
"""
Rate Limiter — مُقيِّد معدل الطلبات
=====================================
Sliding-window rate limiter بطبقتين:
  الطبقة 1: Redis (إذا توفر) — مشترك بين جميع Workers
  الطبقة 2: In-Memory       — fallback عند غياب Redis

المزايا:
  • Redis: يعمل مع multi-worker Gunicorn / Uvicorn clusters
  • In-Memory: zero-dependency، يعمل دائماً
  • انتقال تلقائي بين الطبقتين بدون أي تغيير في الكود

الأداء:
  - Redis check:     ~1ms (single ZADD + ZCOUNT)
  - In-Memory check: ~0.1ms (deque lookup)
  - Fallback:        تلقائي عند أول خطأ Redis
"""
from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# ── تحميل .env ──────────────────────────────────────────
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8-sig").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            if _v.strip():
                os.environ.setdefault(_k.strip(), _v.strip())

_REDIS_URL      = os.getenv("REDIS_URL", "")
_MAX_REQUESTS   = int(os.getenv("RATE_LIMIT_MAX_REQUESTS",  "30"))
_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))


# ══════════════════════════════════════════════════════════
# RateLimiter — الفئة الرئيسية
# ══════════════════════════════════════════════════════════
class RateLimiter:
    """
    Sliding-window rate limiter مع Redis fallback.

    الاستخدام:
        limiter = RateLimiter(redis_url="redis://localhost:6379/0")
        await limiter.connect()

        allowed, remaining = await limiter.is_allowed("127.0.0.1")
        if not allowed:
            raise HTTPException(429, "Too Many Requests")
    """

    def __init__(
        self,
        redis_url:      Optional[str] = None,
        max_requests:   int           = _MAX_REQUESTS,
        window_seconds: int           = _WINDOW_SECONDS,
    ):
        self.max_requests   = max_requests
        self.window_seconds = window_seconds
        self._redis_url     = redis_url or _REDIS_URL
        self._redis         = None
        self._use_redis     = False
        # In-memory fallback: {identifier: deque([timestamp, ...])}
        self._windows: dict[str, deque] = defaultdict(deque)
        log.info(
            "RateLimiter: max=%d req/%ds | Redis: %s",
            max_requests,
            window_seconds,
            "مُعيَّن" if self._redis_url else "غير مُعيَّن (in-memory)",
        )

    async def connect(self) -> bool:
        """
        يتصل بـ Redis إن كان URL متاحاً.
        يُشغَّل مرة واحدة عند بدء التطبيق.
        Returns True إذا نجح الاتصال.
        """
        if not self._redis_url:
            log.info("RateLimiter: وضع in-memory (لا Redis URL)")
            return False
        try:
            import redis.asyncio as aioredis
            self._redis     = aioredis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=3,
            )
            # اختبار الاتصال
            await self._redis.ping()
            self._use_redis = True
            log.info("✓ RateLimiter: Redis متصل — %s", self._redis_url.split("@")[-1])
            return True
        except ImportError:
            log.info("RateLimiter: redis package غير مثبّت — سيستخدم in-memory")
        except Exception as e:
            log.warning("RateLimiter: Redis فشل (%s) — سيستخدم in-memory", e)
        self._use_redis = False
        return False

    async def disconnect(self):
        """يُغلق الاتصال بـ Redis."""
        if self._redis:
            try:
                await self._redis.close()
            except Exception:
                pass

    # ────────────────────────────────────────────────────
    # الدالة الرئيسية
    # ────────────────────────────────────────────────────

    async def is_allowed(
        self,
        identifier: str,
        max_requests:   Optional[int] = None,
        window_seconds: Optional[int] = None,
    ) -> tuple[bool, int]:
        """
        يتحقق إذا كان الطلب مسموحاً به.

        Args:
            identifier:     IP أو session_id
            max_requests:   تجاوز الافتراضي (اختياري)
            window_seconds: تجاوز الافتراضي (اختياري)

        Returns:
            (allowed: bool, remaining: int)
            remaining = عدد الطلبات المتبقية في النافذة الحالية
        """
        limit  = max_requests   or self.max_requests
        window = window_seconds or self.window_seconds

        if self._use_redis and self._redis:
            try:
                return await self._check_redis(identifier, limit, window)
            except Exception as e:
                log.warning("RateLimiter Redis خطأ، fallback لـ in-memory: %s", e)
                self._use_redis = False   # تعطيل Redis مؤقتاً حتى إعادة التشغيل

        return self._check_memory(identifier, limit, window)

    async def _check_redis(
        self, identifier: str, limit: int, window: int
    ) -> tuple[bool, int]:
        """
        Sliding window بـ Redis Sorted Set.
        Key:   rl:{identifier}
        Score: timestamp بالثوانٍ (float)
        """
        now     = time.time()
        key     = f"rl:{identifier}"
        cutoff  = now - window

        pipe = self._redis.pipeline()
        pipe.zremrangebyscore(key, "-inf", cutoff)   # أزل الطلبات خارج النافذة
        pipe.zadd(key, {str(now): now})               # أضف الطلب الحالي
        pipe.zcard(key)                               # عدد الطلبات في النافذة
        pipe.expire(key, window + 10)                 # TTL تلقائي للتنظيف
        results = await pipe.execute()

        count     = results[2]
        remaining = max(0, limit - count)
        allowed   = count <= limit

        if not allowed:
            log.warning(
                "rate_limit [redis]: %s محظور — %d/%d طلباً في %ds",
                identifier[:20], count, limit, window
            )
        return allowed, remaining

    def _check_memory(
        self, identifier: str, limit: int, window: int
    ) -> tuple[bool, int]:
        """
        Sliding window بـ deque في الذاكرة.
        O(1) amortized — يزيل الطلبات القديمة عند كل فحص.
        """
        now    = time.monotonic()
        dq     = self._windows[identifier]
        cutoff = now - window

        # أزل الطلبات خارج النافذة
        while dq and dq[0] < cutoff:
            dq.popleft()

        count     = len(dq)
        remaining = max(0, limit - count)

        if count >= limit:
            log.warning(
                "rate_limit [memory]: %s محظور — %d/%d طلباً في %ds",
                identifier[:20], count, limit, window
            )
            return False, 0

        dq.append(now)
        return True, remaining - 1

    # ────────────────────────────────────────────────────
    # إدارة وإحصاءات
    # ────────────────────────────────────────────────────

    async def reset(self, identifier: str) -> bool:
        """يُعيد تعيين حد الطلبات لمعرّف معين (للاستخدام الإداري)."""
        self._windows.pop(identifier, None)
        if self._use_redis and self._redis:
            try:
                await self._redis.delete(f"rl:{identifier}")
                return True
            except Exception:
                pass
        return True

    def get_stats(self) -> dict:
        """يُعيد إحصاءات الحالة الحالية."""
        now    = time.monotonic()
        window = self.window_seconds
        active = {
            ip: len([t for t in dq if t > now - window])
            for ip, dq in self._windows.items()
            if dq
        }
        return {
            "backend":        "redis" if self._use_redis else "in_memory",
            "redis_url":      self._redis_url.split("@")[-1] if self._redis_url else None,
            "max_requests":   self.max_requests,
            "window_seconds": self.window_seconds,
            "active_clients": len(active),
            "top_clients":    sorted(active.items(), key=lambda x: -x[1])[:5],
        }


# ══════════════════════════════════════════════════════════
# Global instance — singleton
# ══════════════════════════════════════════════════════════
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """يُعيد أو يُنشئ الـ instance العالمي."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter(
            redis_url=_REDIS_URL or None,
            max_requests=_MAX_REQUESTS,
            window_seconds=_WINDOW_SECONDS,
        )
    return _rate_limiter


async def check_rate_limit(identifier: str) -> tuple[bool, int]:
    """
    دالة مختصرة للاستخدام في main.py.
    تُعيد (allowed, remaining).
    """
    return await get_rate_limiter().is_allowed(identifier)
