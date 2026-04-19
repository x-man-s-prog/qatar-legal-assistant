# -*- coding: utf-8 -*-
"""
اختبارات LLMGateway
====================
تختبر: المزودين المتاحين، fallback، streaming، التحقق من المدخلات.
"""
import sys
import os
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# إضافة مجلد الكود لمسار الاستيراد
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from llm_gateway import LLMGateway, get_gateway


# ══════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════

@pytest.fixture
def gateway():
    """يُنشئ instance جديد من LLMGateway لكل اختبار."""
    return LLMGateway()


@pytest.fixture
def system_prompt():
    return "أنت مساعد قانوني متخصص في القانون القطري."


@pytest.fixture
def messages():
    return [{"role": "user", "content": "ما هي عقوبة السرقة في قطر؟"}]


# ══════════════════════════════════════════════════════════
# اختبارات المزودين المتاحين
# ══════════════════════════════════════════════════════════

class TestAvailableProviders:

    def test_returns_list(self, gateway):
        providers = gateway.get_available_providers()
        assert isinstance(providers, list)
        assert len(providers) >= 1

    def test_ollama_always_available(self, gateway):
        """Ollama دائماً متاح — fallback محلي."""
        providers = gateway.get_available_providers()
        assert "ollama" in providers

    def test_provider_values_valid(self, gateway):
        valid = {"openai", "gemini", "claude", "ollama"}
        for p in gateway.get_available_providers():
            assert p in valid, f"مزود غير معروف: {p}"

    def test_get_available_models_returns_dict(self, gateway):
        models = gateway.get_available_models()
        assert isinstance(models, dict)
        assert "ollama" in models

    def test_models_are_strings(self, gateway):
        for provider, model in gateway.get_available_models().items():
            assert isinstance(model, str)
            assert len(model) > 0


# ══════════════════════════════════════════════════════════
# اختبارات الـ Primary Provider
# ══════════════════════════════════════════════════════════

class TestPrimaryProvider:

    def test_primary_provider_is_valid(self, gateway):
        primary = gateway.primary_provider()
        assert primary in ("openai", "gemini", "claude", "ollama")

    def test_primary_prefers_openai_when_key_set(self, gateway):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test123"}):
            gw = LLMGateway()
            # يتحقق من أن OpenAI يُعطى الأولوية عند توفر المفتاح
            providers = gw.get_available_providers()
            if "openai" in providers:
                assert gw.primary_provider() == "openai"

    def test_is_ollama_mode_false_when_api_key_present(self, gateway):
        """إذا كان هناك مفتاح API، لا نكون في وضع Ollama فقط."""
        if gateway.primary_provider() != "ollama":
            assert gateway.is_ollama_mode() is False

    def test_is_ollama_mode_true_when_no_keys(self):
        """بدون أي مفاتيح — يجب أن يكون وضع Ollama."""
        env = {
            "OPENAI_API_KEY": "",
            "GEMINI_API_KEY": "",
            "ANTHROPIC_API_KEY": "",
        }
        with patch.dict(os.environ, env):
            # نُنشئ instance جديد في بيئة بدون مفاتيح
            import importlib
            import llm_gateway as gw_mod
            # نحفظ القيم القديمة
            old_openai    = gw_mod._OPENAI_KEY
            old_gemini    = gw_mod._GEMINI_KEY
            old_anthropic = gw_mod._ANTHROPIC_KEY
            gw_mod._OPENAI_KEY    = ""
            gw_mod._GEMINI_KEY    = ""
            gw_mod._ANTHROPIC_KEY = ""
            try:
                gw = LLMGateway()
                assert gw.is_ollama_mode() is True
            finally:
                gw_mod._OPENAI_KEY    = old_openai
                gw_mod._GEMINI_KEY    = old_gemini
                gw_mod._ANTHROPIC_KEY = old_anthropic


# ══════════════════════════════════════════════════════════
# اختبارات Fallback Order
# ══════════════════════════════════════════════════════════

class TestFallbackOrder:

    def test_ollama_always_last_resort(self, gateway):
        """Ollama دائماً في قائمة الـ fallback."""
        for preferred in gateway.get_available_providers():
            order = gateway._build_fallback_order(preferred)
            assert "ollama" in order

    def test_preferred_is_first(self, gateway):
        """المزود المفضّل يكون أول في القائمة إذا كان متاحاً."""
        available = gateway.get_available_providers()
        for prov in available:
            order = gateway._build_fallback_order(prov)
            assert order[0] == prov, f"{prov} يجب أن يكون أول"

    def test_no_duplicates_in_order(self, gateway):
        """لا تكرار في قائمة الـ fallback."""
        for prov in gateway.get_available_providers():
            order = gateway._build_fallback_order(prov)
            assert len(order) == len(set(order)), f"تكرار في fallback لـ {prov}"

    def test_unknown_provider_defaults_to_available(self, gateway):
        """مزود غير معروف → يرجع للمتاحين."""
        order = gateway._build_fallback_order("unknown_provider_xyz")
        assert len(order) >= 1
        assert "ollama" in order


# ══════════════════════════════════════════════════════════
# اختبارات Singleton
# ══════════════════════════════════════════════════════════

class TestSingleton:

    def test_get_gateway_returns_same_instance(self):
        gw1 = get_gateway()
        gw2 = get_gateway()
        assert gw1 is gw2

    def test_get_gateway_returns_llm_gateway(self):
        assert isinstance(get_gateway(), LLMGateway)


# ══════════════════════════════════════════════════════════
# اختبارات call() مع Mock
# ══════════════════════════════════════════════════════════

class TestCallWithMock:

    @pytest.mark.asyncio
    async def test_call_returns_string(self, gateway, system_prompt, messages):
        """تحقق أن call() يُعيد string."""
        with patch.object(gateway, "_call_single", new_callable=AsyncMock) as mock:
            mock.return_value = "هذه إجابة اختبارية"
            result = await gateway.call(system_prompt, messages)
            assert isinstance(result, str)
            assert len(result) > 0

    @pytest.mark.asyncio
    async def test_call_uses_preferred_provider_first(self, gateway, system_prompt, messages):
        """تحقق أن call() يجرب المزود المفضّل أولاً."""
        calls = []
        async def mock_call_single(provider, *args, **kwargs):
            calls.append(provider)
            return "إجابة"
        with patch.object(gateway, "_call_single", side_effect=mock_call_single):
            await gateway.call(system_prompt, messages, provider="gemini")
            assert calls[0] == "gemini", f"يجب أن يكون gemini أولاً، لكن كان {calls[0]}"

    @pytest.mark.asyncio
    async def test_fallback_on_empty_response(self, gateway, system_prompt, messages):
        """إذا أعاد المزود الأول فراغاً — ينتقل للتالي."""
        call_count = [0]
        async def mock_call_single(provider, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return ""   # فراغ — يُحفّز الـ fallback
            return "إجابة من المزود الثاني"
        with patch.object(gateway, "_call_single", side_effect=mock_call_single):
            result = await gateway.call(system_prompt, messages)
            assert call_count[0] >= 2, "يجب أن يجرب مزوداً ثانياً عند الفراغ"

    @pytest.mark.asyncio
    async def test_fallback_on_exception(self, gateway, system_prompt, messages):
        """إذا رمى المزود الأول exception — ينتقل للتالي."""
        call_order = []
        available = gateway.get_available_providers()

        async def mock_call_single(provider, *args, **kwargs):
            call_order.append(provider)
            if len(call_order) == 1:
                raise RuntimeError("API فشل")
            return "إجابة احتياطية"

        with patch.object(gateway, "_call_single", side_effect=mock_call_single):
            result = await gateway.call(system_prompt, messages)
            assert len(call_order) >= 2, "يجب الانتقال للمزود الثاني بعد الفشل"
            assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_raises_when_all_providers_fail(self, gateway, system_prompt, messages):
        """إذا فشل جميع المزودين — يرفع RuntimeError."""
        async def always_fail(provider, *args, **kwargs):
            raise RuntimeError(f"{provider} فشل دائماً")

        with patch.object(gateway, "_call_single", side_effect=always_fail):
            with pytest.raises(RuntimeError, match="جميع مزودي LLM فشلوا"):
                await gateway.call(system_prompt, messages)


# ══════════════════════════════════════════════════════════
# اختبارات stream() مع Mock
# ══════════════════════════════════════════════════════════

class TestStreamWithMock:

    @pytest.mark.asyncio
    async def test_stream_yields_strings(self, gateway, system_prompt, messages):
        """تحقق أن stream() يُنتج chunks من النوع str."""
        chunks = ["إجابة ", "اختبارية ", "للبث"]

        async def mock_stream_single(provider, *args, **kwargs):
            for c in chunks:
                yield c

        with patch.object(gateway, "_stream_single", side_effect=mock_stream_single):
            result = []
            async for chunk in gateway.stream(system_prompt, messages):
                result.append(chunk)
                assert isinstance(chunk, str)
            assert "".join(result) == "إجابة اختبارية للبث"

    @pytest.mark.asyncio
    async def test_stream_fallback_on_exception(self, gateway, system_prompt, messages):
        """fallback في الـ stream عند الخطأ."""
        call_count = [0]

        async def mock_stream_single(provider, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("بث فشل")
            yield "إجابة بديلة"

        with patch.object(gateway, "_stream_single", side_effect=mock_stream_single):
            result = []
            async for chunk in gateway.stream(system_prompt, messages):
                result.append(chunk)
            assert call_count[0] >= 2


# ══════════════════════════════════════════════════════════
# اختبارات OpenAI Response Parsing
# ══════════════════════════════════════════════════════════

class TestOpenAIResponseParsing:

    @pytest.mark.asyncio
    async def test_stream_openai_parses_chunks_correctly(self, gateway, system_prompt, messages):
        """تحقق من parsing صحيح لـ SSE chunks من OpenAI."""
        import json as _json

        fake_lines = [
            'data: ' + _json.dumps({"choices": [{"delta": {"content": "الجواب "}}]}),
            'data: ' + _json.dumps({"choices": [{"delta": {"content": "القانوني"}}]}),
            'data: [DONE]',
        ]

        class FakeStream:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                pass
            @property
            def status_code(self):
                return 200
            async def aiter_lines(self):
                for line in fake_lines:
                    yield line

        class FakeClient:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                pass
            def stream(self, *a, **kw):
                return FakeStream()

        with patch("httpx.AsyncClient", return_value=FakeClient()):
            import llm_gateway as gw_mod
            original_key = gw_mod._OPENAI_KEY
            gw_mod._OPENAI_KEY = "sk-test"
            try:
                result = []
                async for chunk in gateway.stream_openai(system_prompt, messages):
                    result.append(chunk)
                assert "".join(result) == "الجواب القانوني"
            finally:
                gw_mod._OPENAI_KEY = original_key


# ══════════════════════════════════════════════════════════
# اختبارات get_stats()
# ══════════════════════════════════════════════════════════

class TestStats:

    def test_get_stats_structure(self, gateway):
        stats = gateway.get_stats()
        assert "primary_provider"    in stats
        assert "available_providers" in stats
        assert "models"              in stats
        assert "is_ollama_mode"      in stats

    def test_get_stats_types(self, gateway):
        stats = gateway.get_stats()
        assert isinstance(stats["primary_provider"],    str)
        assert isinstance(stats["available_providers"], list)
        assert isinstance(stats["models"],              dict)
        assert isinstance(stats["is_ollama_mode"],      bool)
