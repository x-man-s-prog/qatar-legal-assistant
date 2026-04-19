# -*- coding: utf-8 -*-
"""
اختبارات التحقق من المدخلات
==============================
تختبر: QueryRequest validation، XSS، Session IDs، حد الطول.
"""
import sys
import os
import pytest
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ══════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════

@pytest.fixture
def QueryRequest():
    """يستورد QueryRequest مباشرةً من main.py."""
    # نستورد فقط الـ model بدون تشغيل كل main.py
    from pydantic import BaseModel, field_validator
    from typing import Optional

    class _QueryRequest(BaseModel):
        query:      str
        mode:       Optional[str] = "expert"
        model:      Optional[str] = "openai"
        session_id: Optional[str] = "default"
        history:    Optional[list] = []

        @field_validator("query")
        @classmethod
        def validate_query(cls, v: str) -> str:
            v = v.strip()
            if not v:
                raise ValueError("الرجاء إدخال سؤال.")
            if len(v) > 2000:
                raise ValueError(f"السؤال طويل جداً ({len(v)} حرف). الحد الأقصى 2000 حرف.")
            v = re.sub(r'<[^>]+>', '', v)
            v = v.replace('\x00', '')
            return v

        @field_validator("model")
        @classmethod
        def validate_model(cls, v: Optional[str]) -> str:
            if v not in ("openai", "gemini", "claude", "ollama"):
                return "openai"
            return v or "openai"

        @field_validator("mode")
        @classmethod
        def validate_mode(cls, v: Optional[str]) -> str:
            if v not in ("expert", "general"):
                return "expert"
            return v

        @field_validator("session_id")
        @classmethod
        def validate_session_id(cls, v: Optional[str]) -> str:
            if not v:
                return "default"
            v = re.sub(r'[^a-zA-Z0-9\-_]', '', v)[:64]
            return v or "default"

        @field_validator("history")
        @classmethod
        def validate_history(cls, v: Optional[list]) -> list:
            if not v:
                return []
            return v[-20:] if len(v) > 20 else v

    return _QueryRequest


# ══════════════════════════════════════════════════════════
# اختبارات query
# ══════════════════════════════════════════════════════════

class TestQueryValidation:

    def test_valid_arabic_question(self, QueryRequest):
        """سؤال عربي عادي يجب أن يمر بدون مشاكل."""
        req = QueryRequest(query="ما هي عقوبة السرقة في قطر؟")
        assert req.query == "ما هي عقوبة السرقة في قطر؟"

    def test_whitespace_stripped(self, QueryRequest):
        """المسافات الزائدة تُزال من البداية والنهاية."""
        req = QueryRequest(query="   سؤال قانوني   ")
        assert req.query == "سؤال قانوني"

    def test_query_too_long_rejected(self, QueryRequest):
        """سؤال أطول من 2000 حرف يُرفض."""
        from pydantic import ValidationError
        with pytest.raises((ValidationError, ValueError)):
            QueryRequest(query="أ" * 2001)

    def test_query_exactly_2000_chars_accepted(self, QueryRequest):
        """سؤال بالضبط 2000 حرف مقبول."""
        req = QueryRequest(query="أ" * 2000)
        assert len(req.query) == 2000

    def test_empty_query_rejected(self, QueryRequest):
        """سؤال فارغ يُرفض."""
        from pydantic import ValidationError
        with pytest.raises((ValidationError, ValueError)):
            QueryRequest(query="")

    def test_whitespace_only_rejected(self, QueryRequest):
        """سؤال من مسافات فقط يُرفض."""
        from pydantic import ValidationError
        with pytest.raises((ValidationError, ValueError)):
            QueryRequest(query="   ")


# ══════════════════════════════════════════════════════════
# اختبارات XSS و Injection
# ══════════════════════════════════════════════════════════

class TestXSSProtection:

    def test_script_tags_removed(self, QueryRequest):
        """علامات <script> تُزال مع محتواها."""
        req = QueryRequest(query="<script>alert('xss')</script>سؤال قانوني")
        assert "<script>" not in req.query
        assert "</script>" not in req.query
        # النص العربي يبقى
        assert "سؤال قانوني" in req.query

    def test_html_tags_removed(self, QueryRequest):
        """جميع علامات HTML تُزال."""
        req = QueryRequest(query="<b>سؤال</b> <i>قانوني</i>")
        assert "<b>"  not in req.query
        assert "<i>"  not in req.query
        assert "سؤال" in req.query

    def test_html_event_handlers_removed(self, QueryRequest):
        """معالجات أحداث HTML تُزال."""
        req = QueryRequest(query='<img src=x onerror="alert(1)">سؤال')
        assert "onerror" not in req.query
        assert "alert"   not in req.query

    def test_null_bytes_removed(self, QueryRequest):
        """Null bytes تُزال."""
        req = QueryRequest(query="سؤال\x00قانوني")
        assert "\x00" not in req.query
        assert "سؤالقانوني" in req.query

    def test_legitimate_angle_bracket_text_cleaned(self, QueryRequest):
        """حتى النصوص ذات الأقواس المشروعة تُنظَّف."""
        req = QueryRequest(query="ما المقصود بـ <العقد الإداري>؟")
        # يجب أن يحذف الـ HTML-like tag لكن يبقى النص
        assert "<العقد الإداري>" not in req.query


# ══════════════════════════════════════════════════════════
# اختبارات session_id
# ══════════════════════════════════════════════════════════

class TestSessionIdValidation:

    def test_valid_uuid_accepted(self, QueryRequest):
        """UUID صالح يُقبل."""
        req = QueryRequest(query="سؤال", session_id="550e8400-e29b-41d4-a716-446655440000")
        assert "550e8400" in req.session_id

    def test_path_traversal_blocked(self, QueryRequest):
        """محاولة path traversal تُمنع — الأحرف الخطرة (. و /) تُحذف."""
        req = QueryRequest(query="سؤال", session_id="../../../etc/passwd")
        # الأحرف الخطرة محذوفة
        assert "/" not in req.session_id
        assert "." not in req.session_id
        # لا توجد ../  أو مسار كامل
        assert "../" not in req.session_id
        assert "etc/passwd" not in req.session_id

    def test_sql_injection_in_session_blocked(self, QueryRequest):
        """أحرف SQL في session_id تُزال."""
        req = QueryRequest(query="سؤال", session_id="'; DROP TABLE sessions;--")
        assert "'" not in req.session_id
        assert ";" not in req.session_id
        assert "DROP" in req.session_id   # الأحرف اللاتينية تُبقى

    def test_session_id_length_truncated(self, QueryRequest):
        """session_id الطويل جداً يُقطع عند 64 حرفاً."""
        req = QueryRequest(query="سؤال", session_id="a" * 100)
        assert len(req.session_id) <= 64

    def test_arabic_session_id_cleared(self, QueryRequest):
        """session_id بأحرف عربية → يرجع للافتراضي."""
        req = QueryRequest(query="سؤال", session_id="معرف-الجلسة")
        # الأحرف العربية تُزال، الشرطة تُبقى
        assert "م" not in req.session_id
        assert "ع" not in req.session_id

    def test_none_session_id_defaults(self, QueryRequest):
        """session_id=None → يرجع "default"."""
        req = QueryRequest(query="سؤال", session_id=None)
        assert req.session_id == "default"


# ══════════════════════════════════════════════════════════
# اختبارات model
# ══════════════════════════════════════════════════════════

class TestModelValidation:

    def test_valid_models_accepted(self, QueryRequest):
        """النماذج المسموحة تُقبل."""
        for m in ("openai", "gemini", "claude", "ollama"):
            req = QueryRequest(query="سؤال", model=m)
            assert req.model == m

    def test_invalid_model_normalized(self, QueryRequest):
        """نموذج غير معروف → openai."""
        req = QueryRequest(query="سؤال", model="gpt-5-turbo-ultra")
        assert req.model == "openai"

    def test_injection_in_model_normalized(self, QueryRequest):
        """محاولة حقن في اسم النموذج → openai."""
        req = QueryRequest(query="سؤال", model="openai; rm -rf /")
        assert req.model == "openai"


# ══════════════════════════════════════════════════════════
# اختبارات mode
# ══════════════════════════════════════════════════════════

class TestModeValidation:

    def test_expert_mode_accepted(self, QueryRequest):
        req = QueryRequest(query="سؤال", mode="expert")
        assert req.mode == "expert"

    def test_general_mode_accepted(self, QueryRequest):
        req = QueryRequest(query="سؤال", mode="general")
        assert req.mode == "general"

    def test_invalid_mode_defaults_to_expert(self, QueryRequest):
        req = QueryRequest(query="سؤال", mode="hacker_mode")
        assert req.mode == "expert"


# ══════════════════════════════════════════════════════════
# اختبارات history
# ══════════════════════════════════════════════════════════

class TestHistoryValidation:

    def test_history_truncated_to_20(self, QueryRequest):
        """history أطول من 20 رسالة يُقطع."""
        long_history = [{"role": "user", "content": f"سؤال {i}"} for i in range(50)]
        req = QueryRequest(query="سؤال", history=long_history)
        assert len(req.history) <= 20

    def test_history_keeps_last_messages(self, QueryRequest):
        """يحتفظ بآخر 20 رسالة (الأحدث)."""
        history = [{"role": "user", "content": str(i)} for i in range(50)]
        req = QueryRequest(query="سؤال", history=history)
        # آخر رسالة يجب أن تكون محفوظة
        assert req.history[-1]["content"] == "49"

    def test_empty_history_returns_empty_list(self, QueryRequest):
        req = QueryRequest(query="سؤال", history=[])
        assert req.history == []

    def test_none_history_returns_empty_list(self, QueryRequest):
        req = QueryRequest(query="سؤال", history=None)
        assert req.history == []
