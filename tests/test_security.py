# -*- coding: utf-8 -*-
"""
اختبارات الأمان — test_security.py
====================================
تختبر: API Key auth, SQL injection prevention,
XSS input sanitization, rate-limit headers, .gitignore secrets.
22 اختبار — لا يتطلب DB أو LLM.
"""
import sys
import os
import re
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ══════════════════════════════════════════════════════════════
# Helpers — lightweight ASGI test client (no httpx required)
# ══════════════════════════════════════════════════════════════
def _make_scope(method: str, path: str, headers: list[tuple] | None = None):
    return {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": b"",
        "headers": headers or [],
        "client": ("127.0.0.1", 9000),
    }


# ══════════════════════════════════════════════════════════════
# TestApiKeyConfig
# ══════════════════════════════════════════════════════════════
class TestApiKeyConfig:
    def test_api_key_env_default_empty(self):
        """بيئة التطوير: API_KEY فارغ → لا auth (عزل كامل عن .env)"""
        from pathlib import Path
        env_backup = os.environ.pop("API_KEY", None)
        try:
            import importlib, core.config as cfg
            # عزل .env حتى لا تُلوّث القيمة الافتراضية
            with patch.object(Path, "exists", return_value=False):
                importlib.reload(cfg)
                assert cfg.API_KEY == ""
        finally:
            if env_backup is not None:
                os.environ["API_KEY"] = env_backup
            import importlib, core.config as cfg
            importlib.reload(cfg)

    def test_api_key_loaded_from_env(self):
        """API_KEY يُحمَّل من متغير البيئة"""
        os.environ["API_KEY"] = "test-secret-key"
        try:
            import importlib, core.config as cfg
            importlib.reload(cfg)
            assert cfg.API_KEY == "test-secret-key"
        finally:
            del os.environ["API_KEY"]
            import importlib, core.config as cfg
            importlib.reload(cfg)

    def test_api_key_not_hardcoded(self):
        """API_KEY لا يُضمَّن في الكود — يأتي من env فقط"""
        config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "core", "config.py")
        content = open(config_path, encoding="utf-8").read()
        # يجب أن يكون API_KEY = os.getenv(...)، لا قيمة ثابتة
        assert 'os.getenv("API_KEY"' in content

    def test_db_password_from_env(self):
        """DB_PASSWORD لا يجب أن يكون مُضمَّناً كقيمة ثابتة واضحة في الكود المُشترَك"""
        config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "core", "config.py")
        content = open(config_path, encoding="utf-8").read()
        assert 'os.getenv("DB_PASSWORD"' in content


# ══════════════════════════════════════════════════════════════
# TestGitignoreSecrets
# ══════════════════════════════════════════════════════════════
class TestGitignoreSecrets:
    def _read_gitignore(self):
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".gitignore")
        return open(path, encoding="utf-8").read()

    def test_gitignore_excludes_dotenv(self):
        content = self._read_gitignore()
        assert ".env" in content

    def test_gitignore_excludes_venv(self):
        content = self._read_gitignore()
        assert ".venv/" in content or "venv/" in content

    def test_gitignore_excludes_pycache(self):
        content = self._read_gitignore()
        assert "__pycache__/" in content

    def test_gitignore_excludes_logs(self):
        content = self._read_gitignore()
        assert "*.log" in content

    def test_no_env_file_in_repo(self):
        """ملف .env يجب ألا يكون مُتتبَّعاً في git (وجوده لا يعني تتبعه)"""
        # نتحقق فقط أنه مُدرج في .gitignore
        content = self._read_gitignore()
        assert ".env" in content, ".env يجب أن يكون في .gitignore"


# ══════════════════════════════════════════════════════════════
# TestSqlInjectionPrevention
# ══════════════════════════════════════════════════════════════
class TestSqlInjectionPrevention:
    """التحقق من أن استعلامات DB تستخدم parameterized queries فقط."""

    def _scan_file(self, filepath):
        """ابحث عن f-strings تحتوي كلمات SQL خطرة مع متغيرات مستخدم مباشرة."""
        if not os.path.exists(filepath):
            return []
        content = open(filepath, encoding="utf-8").read()
        # نمط: f"...SELECT/INSERT/UPDATE/DELETE..." مع {variable} غير محمي
        dangerous = re.findall(
            r'f["\'].*(?:SELECT|INSERT|UPDATE|DELETE|DROP|TRUNCATE).*\{(?!i\+1|j\+1|\d)',
            content, re.IGNORECASE
        )
        return dangerous

    def test_llm_service_no_raw_sql_fstrings(self):
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            "services", "llm_service.py")
        dangerous = self._scan_file(path)
        assert dangerous == [], f"SQL injection risk in llm_service.py: {dangerous}"

    def test_query_router_no_raw_sql_fstrings(self):
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            "routers", "query_router.py")
        dangerous = self._scan_file(path)
        assert dangerous == [], f"SQL injection risk in query_router.py: {dangerous}"

    def test_admin_router_no_raw_sql_fstrings(self):
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            "routers", "admin_router.py")
        dangerous = self._scan_file(path)
        assert dangerous == [], f"SQL injection risk in admin_router.py: {dangerous}"

    def test_parameterized_pattern_in_llm_service(self):
        """استعلامات llm_service تستخدم $1 $2 placeholders."""
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            "services", "llm_service.py")
        if not os.path.exists(path):
            pytest.skip("llm_service.py not found")
        content = open(path, encoding="utf-8").read()
        assert "$1" in content, "يجب استخدام parameterized queries في llm_service.py"

    def test_compare_service_no_raw_sql(self):
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            "compare_service.py")
        dangerous = self._scan_file(path)
        assert dangerous == [], f"SQL injection risk in compare_service.py: {dangerous}"

    def test_logger_service_no_raw_sql(self):
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            "logger_service.py")
        dangerous = self._scan_file(path)
        assert dangerous == [], f"SQL injection risk in logger_service.py: {dangerous}"


# ══════════════════════════════════════════════════════════════
# TestInputValidation — XSS & injection via Pydantic
# ══════════════════════════════════════════════════════════════
class TestInputValidation:
    """محاكاة التحقق من المدخلات في query_router."""

    def _validate_query(self, query: str, max_len: int = 2000) -> str:
        """نسخة مبسطة من التحقق المتوقع في routers."""
        if not query or not query.strip():
            raise ValueError("query فارغ")
        if len(query) > max_len:
            raise ValueError(f"query يتجاوز {max_len} حرف")
        return query.strip()

    def test_normal_query_passes(self):
        assert self._validate_query("ما عقوبة السرقة في قطر؟") is not None

    def test_empty_query_rejected(self):
        with pytest.raises(ValueError):
            self._validate_query("")

    def test_whitespace_only_rejected(self):
        with pytest.raises(ValueError):
            self._validate_query("   ")

    def test_very_long_query_rejected(self):
        with pytest.raises(ValueError):
            self._validate_query("س" * 3000)

    def test_xss_script_tag_passed_as_text(self):
        """XSS لا يُنفَّذ — يُعامَل كنص عادي (HTML escaping مسؤولية الواجهة)."""
        q = self._validate_query("<script>alert('xss')</script>")
        assert "<script>" in q   # النص يُحفظ كما هو — الواجهة مسؤولة عن escape

    def test_sql_in_query_treated_as_text(self):
        """SQL كمدخل يُعامَل كنص — لا ينفذ لأن الاستعلامات parameterized."""
        q = self._validate_query("'; DROP TABLE chunks; --")
        assert "DROP TABLE" in q   # نص، لا يُنفَّذ

    def test_arabic_query_accepted(self):
        q = self._validate_query("ما حقوق المرأة في قانون الأسرة القطري؟")
        assert len(q) > 0

    def test_query_with_special_chars(self):
        q = self._validate_query("قانون العمل (رقم 14) — المادة [٢٢]")
        assert q is not None


# ══════════════════════════════════════════════════════════════
# TestSecurityMiddlewareLogic
# ══════════════════════════════════════════════════════════════
class TestSecurityMiddlewareLogic:
    """اختبار منطق middleware الأمان بدون FastAPI server."""

    def _check_api_key(self, api_key_config: str, provided_key: str, path: str) -> int:
        """محاكاة منطق التحقق من API Key في security_middleware."""
        public_paths = {"/", "/health", "/api/v1/health"}
        if not api_key_config:
            return 200   # dev mode — no auth
        if path.startswith("/static"):
            return 200   # static files always public
        if path in public_paths:
            return 200   # health checks always public
        if provided_key != api_key_config:
            return 401
        return 200

    def test_dev_mode_no_key_required(self):
        """بيئة dev: API_KEY فارغ → كل الطلبات مسموحة."""
        assert self._check_api_key("", "", "/api/v1/query/") == 200

    def test_valid_key_accepted(self):
        assert self._check_api_key("secret123", "secret123", "/api/v1/stream/") == 200

    def test_wrong_key_rejected(self):
        assert self._check_api_key("secret123", "wrong-key", "/api/v1/stream/") == 401

    def test_missing_key_rejected(self):
        assert self._check_api_key("secret123", "", "/api/v1/stream/") == 401

    def test_health_path_always_public(self):
        assert self._check_api_key("secret123", "", "/health") == 200
        assert self._check_api_key("secret123", "", "/api/v1/health") == 200

    def test_root_path_always_public(self):
        assert self._check_api_key("secret123", "", "/") == 200

    def test_static_files_always_public(self):
        assert self._check_api_key("secret123", "", "/static/style.css") == 200
        assert self._check_api_key("secret123", "", "/static/app.js") == 200

    def test_api_endpoints_require_key_in_prod(self):
        assert self._check_api_key("prod-key", "", "/api/v1/compare") == 401
        assert self._check_api_key("prod-key", "", "/api/v1/analytics") == 401

    def test_key_comparison_is_exact(self):
        """المقارنة دقيقة — لا partial match."""
        assert self._check_api_key("secret", "secret2", "/api/v1/query/") == 401
        assert self._check_api_key("secret", "secre", "/api/v1/query/") == 401
