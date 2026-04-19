# -*- coding: utf-8 -*-
"""
LLM Gateway — بوابة النماذج الموحّدة
======================================
يُوحِّد جميع استدعاءات نماذج الذكاء الاصطناعي في مكان واحد.

المزودون المدعومون (بالترتيب الافتراضي للـ fallback):
  1. OpenAI   (GPT-4o)          — الرئيسي
  2. Gemini   (2.0 Flash)       — احتياطي أول
  3. Claude   (3.5 Sonnet)      — احتياطي ثانٍ
  4. Ollama   (qwen2.5:1.5b)   — احتياطي محلي مجاني

الميزات:
  • Streaming  — بث الإجابة حرفاً بحرف عبر SSE
  • Fallback   — ينتقل تلقائياً للمزود التالي عند الفشل
  • Retry      — إعادة المحاولة مرتين قبل الانتقال
  • Validation — يرفض الإجابات الفارغة ويُجرّب البديل
  • Backward   — دوال وظيفية قديمة محفوظة للتوافق مع main.py

الأداء:
  - فحص المزود المتاح: ~0ms (فحص المفاتيح فقط)
  - call() overhead: ~1ms (بدون حساب زمن الـ API)
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import AsyncIterator, Optional

import httpx

log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════
# تحميل متغيرات البيئة من .env إن وُجد
# ══════════════════════════════════════════════════════════
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8-sig").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            if _v.strip():
                os.environ.setdefault(_k.strip(), _v.strip())

# ══════════════════════════════════════════════════════════
# ثوابت الإعداد
# ══════════════════════════════════════════════════════════
# Filter placeholder values so the gateway doesn't try remote providers with fake keys.
_PLACEHOLDER_KEY_VALUES = {"", "CHANGE_ME", "changeme", "TODO", "your-key-here", "xxx", "none"}

def _clean_gw_key(val: str) -> str:
    v = (val or "").strip()
    if v in _PLACEHOLDER_KEY_VALUES:
        return ""
    if v.startswith("CHANGE") or v.startswith("YOUR_"):
        return ""
    return v

_LOCAL_ONLY = os.getenv("LOCAL_ONLY_MODE", "").lower() in ("1", "true", "yes", "on")

_OPENAI_KEY   = "" if _LOCAL_ONLY else _clean_gw_key(os.getenv("OPENAI_API_KEY", ""))
_GEMINI_KEY   = "" if _LOCAL_ONLY else _clean_gw_key(os.getenv("GEMINI_API_KEY", ""))
_ANTHROPIC_KEY = "" if _LOCAL_ONLY else _clean_gw_key(os.getenv("ANTHROPIC_API_KEY", ""))
_OLLAMA_HOST  = os.getenv("OLLAMA_HOST", "http://localhost:11434")

_MODEL_OPENAI  = os.getenv("MODEL_OPENAI", "gpt-4o")
_MODEL_GEMINI  = os.getenv("MODEL_GEMINI", "gemini-2.0-flash")
_MODEL_CLAUDE  = os.getenv("MODEL_MAIN",   "claude-3-5-sonnet-20241022")
_MODEL_CLAUDE_FAST = os.getenv("MODEL_FAST", "claude-3-haiku-20240307")
_MODEL_OLLAMA  = os.getenv("MODEL_OLLAMA_LLM", "qwen2.5:1.5b")

# عدد مرات إعادة المحاولة قبل الانتقال للمزود التالي
_MAX_RETRIES = 2


# ══════════════════════════════════════════════════════════
# LLMGateway — الفئة الرئيسية
# ══════════════════════════════════════════════════════════
class LLMGateway:
    """
    بوابة موحّدة لجميع مزودي نماذج الذكاء الاصطناعي.

    الاستخدام الأساسي:
        gateway = LLMGateway()

        # استدعاء عادي (بدون streaming):
        answer = await gateway.call(
            system="أنت مساعد قانوني",
            messages=[{"role":"user","content":"ما هو قانون العمل؟"}],
            provider="openai"
        )

        # استدعاء مع streaming:
        async for chunk in gateway.stream(system, messages):
            print(chunk, end="", flush=True)
    """

    # ترتيب الـ fallback الافتراضي
    PROVIDER_ORDER = ["openai", "gemini", "claude", "ollama"]

    def __init__(self):
        # لا نُنشئ httpx clients دائمة — نُنشئها per-request لتجنب timeout issues
        log.info(
            "LLMGateway جاهز — المزود الأساسي: %s | المتاحون: %s",
            self.primary_provider(),
            ", ".join(self.get_available_providers()),
        )

    # ────────────────────────────────────────────────────
    # فحص المزودين المتاحين
    # ────────────────────────────────────────────────────

    def get_available_providers(self) -> list[str]:
        """يُعيد قائمة المزودين الذين لديهم مفاتيح مُعيَّنة."""
        available = []
        if _OPENAI_KEY:
            available.append("openai")
        if _GEMINI_KEY:
            available.append("gemini")
        if _ANTHROPIC_KEY:
            available.append("claude")
        available.append("ollama")   # دائماً متاح (محلي)
        return available

    def get_available_models(self) -> dict[str, str]:
        """يُعيد dict بالمزودين المتاحين ومودياتهم."""
        models: dict[str, str] = {}
        if _OPENAI_KEY:
            models["openai"] = _MODEL_OPENAI
        if _GEMINI_KEY:
            models["gemini"] = _MODEL_GEMINI
        if _ANTHROPIC_KEY:
            models["claude"] = _MODEL_CLAUDE
        models["ollama"] = _MODEL_OLLAMA
        return models

    def primary_provider(self) -> str:
        """يُحدد المزود الأمثل بحسب الأولوية وتوافر المفاتيح."""
        if _OPENAI_KEY:
            return "openai"
        if _GEMINI_KEY:
            return "gemini"
        if _ANTHROPIC_KEY:
            return "claude"
        return "ollama"

    def is_ollama_mode(self) -> bool:
        """صحيح إذا كان الوضع المحلي فقط (Ollama)."""
        return self.primary_provider() == "ollama"

    # ────────────────────────────────────────────────────
    # call() — استدعاء عادي مع fallback
    # ────────────────────────────────────────────────────

    async def call(
        self,
        system: str,
        messages: list[dict],
        provider: Optional[str] = None,
        max_tokens: int = 3000,
        model: Optional[str] = None,
        temperature: float = 0.3,
    ) -> str:
        """
        استدعاء LLM مع fallback تلقائي.

        Args:
            system:      System prompt
            messages:    قائمة رسائل [{role, content}]
            provider:    المزود المفضّل (openai/gemini/claude/ollama)
                         None = يختار الأفضل المتاح تلقائياً
            max_tokens:  الحد الأقصى للرموز في الإجابة
            model:       اسم النموذج المحدد (يتجاوز الإعداد الافتراضي)
            temperature: درجة الإبداع (0=محافظ، 1=مبدع)

        Returns:
            الإجابة كـ string
        """
        effective_provider = provider or self.primary_provider()
        # بناء ترتيب المحاولة: المفضّل أولاً ثم البقية
        order = self._build_fallback_order(effective_provider)

        last_error: Exception | None = None
        for prov in order:
            for attempt in range(_MAX_RETRIES):
                try:
                    result = await self._call_single(
                        prov, system, messages, max_tokens, model, temperature
                    )
                    if result and result.strip():
                        if prov != effective_provider:
                            log.info("LLMGateway: %s أجاب (fallback من %s)", prov, effective_provider)
                        return result
                    # إجابة فارغة — نُجرّب مرة أخرى
                    log.warning("LLMGateway: %s أعاد إجابة فارغة (محاولة %d)", prov, attempt + 1)
                except Exception as e:
                    last_error = e
                    if attempt < _MAX_RETRIES - 1:
                        log.warning("LLMGateway: %s فشل (محاولة %d): %s", prov, attempt + 1, e)
                        await _async_sleep(0.5 * (attempt + 1))
                    else:
                        log.warning("LLMGateway: %s فشل نهائياً، ننتقل للتالي: %s", prov, e)
                    break

        raise RuntimeError(
            f"جميع مزودي LLM فشلوا. آخر خطأ: {last_error}"
        )

    # ────────────────────────────────────────────────────
    # stream() — بث الإجابة مع fallback
    # ────────────────────────────────────────────────────

    async def stream(
        self,
        system: str,
        messages: list[dict],
        provider: Optional[str] = None,
        max_tokens: int = 3000,
        model: Optional[str] = None,
        temperature: float = 0.3,
    ) -> AsyncIterator[str]:
        """
        بث الإجابة حرفاً بحرف مع fallback تلقائي.

        مثال:
            async for chunk in gateway.stream(system, messages):
                yield f"data: {chunk}\n\n"
        """
        effective_provider = provider or self.primary_provider()
        order = self._build_fallback_order(effective_provider)

        for prov in order:
            buffer: list[str] = []
            success = False
            try:
                async for chunk in self._stream_single(
                    prov, system, messages, max_tokens, model, temperature
                ):
                    buffer.append(chunk)
                    yield chunk
                if "".join(buffer).strip():
                    success = True
                else:
                    log.warning("LLMGateway stream: %s أعاد محتوى فارغاً", prov)
            except Exception as e:
                log.warning("LLMGateway stream: %s فشل: %s — ننتقل للتالي", prov, e)

            if success:
                return

        # إذا وصلنا هنا كل المزودين فشلوا
        yield "⚠️ تعذّر الحصول على إجابة — يرجى المحاولة مرة أخرى."

    # ────────────────────────────────────────────────────
    # OpenAI — GPT-4o
    # ────────────────────────────────────────────────────

    async def call_openai(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 3000,
        model: Optional[str] = None,
        temperature: float = 0.3,
    ) -> str:
        """استدعاء OpenAI (GPT-4o) بدون streaming."""
        parts: list[str] = []
        async for chunk in self.stream_openai(system, messages, max_tokens, model, temperature):
            parts.append(chunk)
        result = "".join(parts)
        if result.startswith("خطأ"):
            raise RuntimeError(result)
        return result

    async def stream_openai(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 3000,
        model: Optional[str] = None,
        temperature: float = 0.3,
    ) -> AsyncIterator[str]:
        """بث الإجابة عبر OpenAI API."""
        if not _OPENAI_KEY:
            yield "خطأ: OPENAI_API_KEY غير مُعيَّن"
            return

        msgs = [{"role": "system", "content": system}] + messages
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {_OPENAI_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model or _MODEL_OPENAI,
                    "messages": msgs,
                    "max_tokens": max_tokens,
                    "stream": True,
                    "temperature": temperature,
                },
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    log.error("OpenAI HTTP %d: %s", resp.status_code, body[:200])
                    yield f"خطأ OpenAI ({resp.status_code})"
                    return
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        delta = chunk["choices"][0]["delta"].get("content", "")
                        if delta:
                            yield delta
                    except Exception:
                        continue

    # ────────────────────────────────────────────────────
    # Gemini — Google 2.0 Flash
    # ────────────────────────────────────────────────────

    async def call_gemini(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 3000,
        model: Optional[str] = None,
        temperature: float = 0.3,
    ) -> str:
        """استدعاء Gemini بدون streaming."""
        parts: list[str] = []
        async for chunk in self.stream_gemini(system, messages, max_tokens, model, temperature):
            parts.append(chunk)
        result = "".join(parts)
        if result.startswith("خطأ"):
            raise RuntimeError(result)
        return result

    async def stream_gemini(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 3000,
        model: Optional[str] = None,
        temperature: float = 0.3,
    ) -> AsyncIterator[str]:
        """بث الإجابة عبر Gemini API (مجاني)."""
        if not _GEMINI_KEY:
            yield "خطأ: GEMINI_API_KEY غير مُعيَّن"
            return

        # تحويل رسائل OpenAI format → Gemini format
        contents = []
        for m in messages:
            role = "user" if m["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": m["content"]}]})

        request_body = {
            "contents": contents,
            "systemInstruction": {"parts": [{"text": system}]},
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature":     temperature,
                "topP":            0.85,
                "topK":            40,
            },
        }
        gemini_model = model or _MODEL_GEMINI
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{gemini_model}:streamGenerateContent?alt=sse&key={_GEMINI_KEY}"
        )
        async with httpx.AsyncClient(timeout=180) as c:
            async with c.stream("POST", url, json=request_body) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    log.error("Gemini HTTP %d: %s", resp.status_code, body[:200])
                    yield f"خطأ Gemini ({resp.status_code})"
                    return
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        try:
                            d = json.loads(line[6:])
                            text = d["candidates"][0]["content"]["parts"][0]["text"]
                            if text:
                                yield text
                        except Exception:
                            pass

    # ────────────────────────────────────────────────────
    # Claude — Anthropic
    # ────────────────────────────────────────────────────

    async def call_claude(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 3000,
        model: Optional[str] = None,
        temperature: float = 0.3,
    ) -> str:
        """استدعاء Claude بدون streaming."""
        if not _ANTHROPIC_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY غير مُعيَّن")
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key":         _ANTHROPIC_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type":      "application/json",
                },
                json={
                    "model":      model or _MODEL_CLAUDE,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "system":     system,
                    "messages":   messages,
                },
            )
            r.raise_for_status()
            return r.json()["content"][0]["text"]

    async def stream_claude(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 3000,
        model: Optional[str] = None,
        temperature: float = 0.3,
    ) -> AsyncIterator[str]:
        """بث الإجابة عبر Claude API."""
        if not _ANTHROPIC_KEY:
            yield "خطأ: ANTHROPIC_API_KEY غير مُعيَّن"
            return
        async with httpx.AsyncClient(timeout=180) as c:
            async with c.stream(
                "POST",
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key":         _ANTHROPIC_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type":      "application/json",
                },
                json={
                    "model":      model or _MODEL_CLAUDE,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "system":     system,
                    "messages":   messages,
                    "stream":     True,
                },
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    log.error("Claude HTTP %d: %s", resp.status_code, body[:200])
                    yield f"خطأ Claude ({resp.status_code})"
                    return
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        try:
                            d = json.loads(line[6:])
                            if d.get("type") == "content_block_delta":
                                text = d["delta"].get("text", "")
                                if text:
                                    yield text
                        except Exception:
                            pass

    # ────────────────────────────────────────────────────
    # Ollama — النموذج المحلي المجاني
    # ────────────────────────────────────────────────────

    async def call_ollama(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 2000,
        model: Optional[str] = None,
        temperature: float = 0.05,
    ) -> str:
        """استدعاء Ollama المحلي بدون streaming."""
        parts: list[str] = []
        async for chunk in self.stream_ollama(system, messages, max_tokens, model, temperature):
            parts.append(chunk)
        return "".join(parts)

    async def stream_ollama(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 2000,
        model: Optional[str] = None,
        temperature: float = 0.05,
    ) -> AsyncIterator[str]:
        """بث الإجابة عبر Ollama المحلي."""
        msgs = [{"role": "system", "content": system}] + messages
        async with httpx.AsyncClient(timeout=300) as c:
            async with c.stream(
                "POST",
                f"{_OLLAMA_HOST}/api/chat",
                json={
                    "model":      model or _MODEL_OLLAMA,
                    "messages":   msgs,
                    "stream":     True,
                    "keep_alive": "15m",
                    "options": {
                        "num_predict":  max_tokens,
                        "num_ctx":      3072,
                        "temperature":  temperature,
                        "top_k":        20,
                        "top_p":        0.85,
                        "repeat_penalty": 1.15,
                    },
                },
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    log.error("Ollama HTTP %d: %s", resp.status_code, body[:200])
                    yield f"خطأ Ollama ({resp.status_code})"
                    return
                async for line in resp.aiter_lines():
                    if line:
                        try:
                            d = json.loads(line)
                            text = d.get("message", {}).get("content", "")
                            if text:
                                yield text
                            if d.get("done"):
                                break
                        except Exception:
                            pass

    # ────────────────────────────────────────────────────
    # الدوال الداخلية المساعدة
    # ────────────────────────────────────────────────────

    def _build_fallback_order(self, preferred: str) -> list[str]:
        """يبني ترتيب المحاولة: المفضّل أولاً ثم المتاحون بالترتيب."""
        available = self.get_available_providers()
        order = [preferred] if preferred in available else []
        for prov in self.PROVIDER_ORDER:
            if prov not in order and prov in available:
                order.append(prov)
        # Ollama دائماً في النهاية كـ last resort
        if "ollama" not in order:
            order.append("ollama")
        return order

    async def _call_single(
        self,
        provider: str,
        system: str,
        messages: list[dict],
        max_tokens: int,
        model: Optional[str],
        temperature: float,
    ) -> str:
        """استدعاء مزود واحد بدون fallback."""
        _dispatch = {
            "openai": self.call_openai,
            "gemini": self.call_gemini,
            "claude": self.call_claude,
            "ollama": self.call_ollama,
        }
        fn = _dispatch.get(provider)
        if fn is None:
            raise ValueError(f"مزود غير معروف: {provider}")
        return await fn(system, messages, max_tokens, model, temperature)

    async def _stream_single(
        self,
        provider: str,
        system: str,
        messages: list[dict],
        max_tokens: int,
        model: Optional[str],
        temperature: float,
    ) -> AsyncIterator[str]:
        """بث من مزود واحد بدون fallback."""
        _dispatch = {
            "openai": self.stream_openai,
            "gemini": self.stream_gemini,
            "claude": self.stream_claude,
            "ollama": self.stream_ollama,
        }
        fn = _dispatch.get(provider)
        if fn is None:
            raise ValueError(f"مزود غير معروف: {provider}")
        async for chunk in fn(system, messages, max_tokens, model, temperature):
            yield chunk

    # ────────────────────────────────────────────────────
    # Utility
    # ────────────────────────────────────────────────────

    async def health_check(self) -> dict[str, str]:
        """
        يختبر الاتصال بكل مزود متاح.
        يُستخدم في /api/v1/health endpoint.

        Returns:
            {provider: "ok" | "no_key" | "error: <msg>"}
        """
        results: dict[str, str] = {}

        # OpenAI
        if _OPENAI_KEY:
            try:
                async with httpx.AsyncClient(timeout=10) as c:
                    r = await c.get(
                        "https://api.openai.com/v1/models",
                        headers={"Authorization": f"Bearer {_OPENAI_KEY}"},
                    )
                results["openai"] = "ok" if r.status_code == 200 else f"HTTP {r.status_code}"
            except Exception as e:
                results["openai"] = f"error: {e}"
        else:
            results["openai"] = "no_key"

        # Gemini
        if _GEMINI_KEY:
            try:
                async with httpx.AsyncClient(timeout=10) as c:
                    r = await c.get(
                        f"https://generativelanguage.googleapis.com/v1beta/models?key={_GEMINI_KEY}"
                    )
                results["gemini"] = "ok" if r.status_code == 200 else f"HTTP {r.status_code}"
            except Exception as e:
                results["gemini"] = f"error: {e}"
        else:
            results["gemini"] = "no_key"

        # Claude
        if _ANTHROPIC_KEY:
            try:
                async with httpx.AsyncClient(timeout=10) as c:
                    r = await c.get(
                        "https://api.anthropic.com/v1/models",
                        headers={
                            "x-api-key": _ANTHROPIC_KEY,
                            "anthropic-version": "2023-06-01",
                        },
                    )
                results["claude"] = "ok" if r.status_code == 200 else f"HTTP {r.status_code}"
            except Exception as e:
                results["claude"] = f"error: {e}"
        else:
            results["claude"] = "no_key"

        # Ollama
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.get(f"{_OLLAMA_HOST}/api/tags")
            results["ollama"] = "ok" if r.status_code == 200 else f"HTTP {r.status_code}"
        except Exception as e:
            results["ollama"] = f"error: {e}"

        return results

    def get_stats(self) -> dict:
        """معلومات حالة البوابة."""
        return {
            "primary_provider":    self.primary_provider(),
            "available_providers": self.get_available_providers(),
            "models":              self.get_available_models(),
            "is_ollama_mode":      self.is_ollama_mode(),
        }


# ══════════════════════════════════════════════════════════
# الـ Instance العالمي (singleton)
# ══════════════════════════════════════════════════════════
_gateway: Optional[LLMGateway] = None


def get_gateway() -> LLMGateway:
    """يُعيد instance مشتركاً من LLMGateway (singleton)."""
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway


# ══════════════════════════════════════════════════════════
# دوال التوافق مع main.py القديم — Backward Compatibility
# ══════════════════════════════════════════════════════════
# هذه الدوال تُحاكي الدوال القديمة في main.py حرفياً
# يمكن استيرادها مباشرةً بدلاً من النسخة القديمة

async def call_openai(system: str, messages: list[dict], max_tokens: int = 1000) -> str:
    """توافق مع main.py القديم."""
    return await get_gateway().call_openai(system, messages, max_tokens)


async def stream_openai(system: str, messages: list[dict], max_tokens: int = 3000):
    """توافق مع main.py القديم."""
    async for chunk in get_gateway().stream_openai(system, messages, max_tokens):
        yield chunk


async def call_gemini_compat(system: str, messages: list[dict], max_tokens: int = 1000) -> str:
    """توافق مع main.py القديم."""
    return await get_gateway().call_gemini(system, messages, max_tokens)


async def stream_gemini(system: str, messages: list[dict], max_tokens: int = 3000):
    """توافق مع main.py القديم."""
    async for chunk in get_gateway().stream_gemini(system, messages, max_tokens):
        yield chunk


async def call_claude(
    system: str,
    messages: list[dict],
    model: Optional[str] = None,
    max_tokens: int = 3000,
) -> str:
    """توافق مع main.py القديم."""
    return await get_gateway().call_claude(system, messages, max_tokens, model)


async def stream_claude(
    system: str,
    messages: list[dict],
    model: Optional[str] = None,
    max_tokens: int = 3000,
):
    """توافق مع main.py القديم."""
    async for chunk in get_gateway().stream_claude(system, messages, max_tokens, model):
        yield chunk


async def call_ollama(system: str, messages: list[dict], max_tokens: int = 1000) -> str:
    """توافق مع main.py القديم."""
    return await get_gateway().call_ollama(system, messages, max_tokens)


async def stream_ollama(system: str, messages: list[dict], max_tokens: int = 3000):
    """توافق مع main.py القديم."""
    async for chunk in get_gateway().stream_ollama(system, messages, max_tokens):
        yield chunk


async def _generate_answer(
    model: str,
    system: str,
    messages: list[dict],
    max_tokens: int = 3000,
) -> str:
    """
    توافق مع main.py القديم — مولّد الإجابة الموحّد.
    يستخدم الآن LLMGateway بدلاً من الكود المتكرر.
    """
    return await get_gateway().call(
        system=system,
        messages=messages,
        provider=model or get_gateway().primary_provider(),
        max_tokens=max_tokens,
    )


# ══════════════════════════════════════════════════════════
# دالة مساعدة
# ══════════════════════════════════════════════════════════
async def _async_sleep(seconds: float) -> None:
    """انتظار غير متزامن."""
    import asyncio
    await asyncio.sleep(seconds)
