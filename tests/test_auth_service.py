# -*- coding: utf-8 -*-
"""
اختبارات auth_service
=======================
تختبر: bcrypt, JWT tokens, register, login, refresh, get_user.
28 اختبار — بدون DB حقيقي (AsyncMock).
"""
import sys
import os
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import jwt as _jwt

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from auth_service import (
    AuthService,
    init_auth_service,
    get_auth_service,
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    extract_user_id,
    _JWT_SECRET,
    _JWT_ALGORITHM,
)


# ══════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════

def _make_pool(fetchrow_return=None, execute_return=None):
    """Create a mock asyncpg pool."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow_return)
    conn.execute  = AsyncMock(return_value=execute_return)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_AsyncCtx(conn))
    return pool, conn


class _AsyncCtx:
    def __init__(self, obj): self._obj = obj
    async def __aenter__(self): return self._obj
    async def __aexit__(self, *_): pass


def _make_user_row(uid=1, email="user@test.com", role="user", pw_hash=None):
    pw_hash = pw_hash or hash_password("password123")
    row = MagicMock()
    row.__getitem__ = lambda self, k: {
        "id": uid, "email": email, "password_hash": pw_hash, "role": role,
        "created_at": MagicMock(isoformat=lambda: "2026-01-01T00:00:00+00:00"),
        "last_login":  MagicMock(isoformat=lambda: "2026-04-05T10:00:00+00:00"),
    }[k]
    return row


# ══════════════════════════════════════════════════════════════
# TestPasswordHelpers
# ══════════════════════════════════════════════════════════════
class TestPasswordHelpers:
    def test_hash_returns_string(self):
        h = hash_password("secret123")
        assert isinstance(h, str) and len(h) > 20

    def test_hash_different_each_time(self):
        h1 = hash_password("secret123")
        h2 = hash_password("secret123")
        assert h1 != h2   # bcrypt salt

    def test_verify_correct_password(self):
        h = hash_password("correct")
        assert verify_password("correct", h) is True

    def test_verify_wrong_password(self):
        h = hash_password("correct")
        assert verify_password("wrong", h) is False

    def test_verify_invalid_hash(self):
        assert verify_password("any", "not-a-hash") is False


# ══════════════════════════════════════════════════════════════
# TestTokenHelpers
# ══════════════════════════════════════════════════════════════
class TestTokenHelpers:
    def test_access_token_is_string(self):
        t = create_access_token(1, "u@t.com", "user")
        assert isinstance(t, str) and len(t) > 10

    def test_refresh_token_is_string(self):
        t = create_refresh_token(1)
        assert isinstance(t, str) and len(t) > 10

    def test_access_token_decode_ok(self):
        t = create_access_token(5, "a@b.com", "admin")
        p = decode_token(t)
        assert p["sub"] == "5"
        assert p["email"] == "a@b.com"
        assert p["role"] == "admin"
        assert p["type"] == "access"

    def test_refresh_token_decode_ok(self):
        t = create_refresh_token(7)
        p = decode_token(t)
        assert p["sub"] == "7"
        assert p["type"] == "refresh"

    def test_decode_expired_raises(self):
        from datetime import datetime, timezone, timedelta
        payload = {"sub": "1", "type": "access",
                   "exp": datetime.now(timezone.utc) - timedelta(seconds=1)}
        bad = _jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)
        with pytest.raises(_jwt.ExpiredSignatureError):
            decode_token(bad)

    def test_decode_wrong_secret_raises(self):
        t = _jwt.encode({"sub": "1"}, "wrong-secret", algorithm="HS256")
        with pytest.raises(_jwt.InvalidTokenError):
            decode_token(t)

    def test_extract_user_id_valid(self):
        t = create_access_token(42, "x@y.com", "user")
        assert extract_user_id(t) == 42

    def test_extract_user_id_refresh_returns_none(self):
        t = create_refresh_token(42)
        assert extract_user_id(t) is None   # wrong type

    def test_extract_user_id_invalid_returns_none(self):
        assert extract_user_id("not.a.token") is None


# ══════════════════════════════════════════════════════════════
# TestRegister
# ══════════════════════════════════════════════════════════════
class TestRegister:
    @pytest.mark.asyncio
    async def test_register_success(self):
        row = MagicMock()
        row.__getitem__ = lambda self, k: {
            "id": 1, "email": "new@test.com", "role": "user",
            "created_at": MagicMock(isoformat=lambda: "2026-01-01T00:00:00+00:00"),
        }[k]
        pool, _ = _make_pool(fetchrow_return=row)
        svc = AuthService(pool)
        result = await svc.register("new@test.com", "password123")
        assert result["ok"] is True
        assert result["user_id"] == 1

    @pytest.mark.asyncio
    async def test_register_short_password_fails(self):
        pool, _ = _make_pool()
        svc = AuthService(pool)
        result = await svc.register("u@t.com", "short")
        assert result["ok"] is False
        assert "8" in result["error"]

    @pytest.mark.asyncio
    async def test_register_invalid_email_fails(self):
        pool, _ = _make_pool()
        svc = AuthService(pool)
        result = await svc.register("not-an-email", "password123")
        assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_register_empty_email_fails(self):
        pool, _ = _make_pool()
        svc = AuthService(pool)
        result = await svc.register("", "password123")
        assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_register_duplicate_email(self):
        pool, conn = _make_pool()
        conn.fetchrow.side_effect = Exception("duplicate key violates unique constraint")
        svc = AuthService(pool)
        result = await svc.register("dup@test.com", "password123")
        assert result["ok"] is False
        assert "مسبقاً" in result["error"]


# ══════════════════════════════════════════════════════════════
# TestLogin
# ══════════════════════════════════════════════════════════════
class TestLogin:
    @pytest.mark.asyncio
    async def test_login_success(self):
        pw_hash = hash_password("pass1234")
        row = _make_user_row(uid=3, email="u@q.com", pw_hash=pw_hash)
        pool, conn = _make_pool(fetchrow_return=row)
        conn.execute = AsyncMock(return_value=None)
        svc = AuthService(pool)
        result = await svc.login("u@q.com", "pass1234")
        assert result["ok"] is True
        assert "access_token" in result
        assert "refresh_token" in result

    @pytest.mark.asyncio
    async def test_login_wrong_password(self):
        pw_hash = hash_password("correct")
        row = _make_user_row(pw_hash=pw_hash)
        pool, conn = _make_pool(fetchrow_return=row)
        conn.execute = AsyncMock(return_value=None)
        svc = AuthService(pool)
        result = await svc.login("u@q.com", "wrong")
        assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_login_user_not_found(self):
        pool, _ = _make_pool(fetchrow_return=None)
        svc = AuthService(pool)
        result = await svc.login("ghost@q.com", "pass1234")
        assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_login_tokens_are_valid_jwt(self):
        pw_hash = hash_password("testpass1")
        row = _make_user_row(pw_hash=pw_hash)
        pool, conn = _make_pool(fetchrow_return=row)
        conn.execute = AsyncMock(return_value=None)
        svc = AuthService(pool)
        result = await svc.login("u@q.com", "testpass1")
        payload = decode_token(result["access_token"])
        assert payload["type"] == "access"


# ══════════════════════════════════════════════════════════════
# TestRefresh
# ══════════════════════════════════════════════════════════════
class TestRefresh:
    @pytest.mark.asyncio
    async def test_refresh_success(self):
        refresh = create_refresh_token(5)
        row = MagicMock()
        row.__getitem__ = lambda self, k: {"id": 5, "email": "r@q.com", "role": "user"}[k]
        pool, _ = _make_pool(fetchrow_return=row)
        svc = AuthService(pool)
        result = await svc.refresh(refresh)
        assert result["ok"] is True
        assert "access_token" in result

    @pytest.mark.asyncio
    async def test_refresh_with_access_token_fails(self):
        access = create_access_token(5, "r@q.com", "user")
        pool, _ = _make_pool()
        svc = AuthService(pool)
        result = await svc.refresh(access)
        assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_refresh_invalid_token_fails(self):
        pool, _ = _make_pool()
        svc = AuthService(pool)
        result = await svc.refresh("garbage.token.here")
        assert result["ok"] is False


# ══════════════════════════════════════════════════════════════
# TestGetUser
# ══════════════════════════════════════════════════════════════
class TestGetUser:
    @pytest.mark.asyncio
    async def test_get_user_found(self):
        row = _make_user_row(uid=10, email="found@q.com")
        pool, _ = _make_pool(fetchrow_return=row)
        svc = AuthService(pool)
        user = await svc.get_user(10)
        assert user is not None
        assert user["id"] == 10
        assert user["email"] == "found@q.com"

    @pytest.mark.asyncio
    async def test_get_user_not_found(self):
        pool, _ = _make_pool(fetchrow_return=None)
        svc = AuthService(pool)
        user = await svc.get_user(999)
        assert user is None

    @pytest.mark.asyncio
    async def test_get_user_by_email(self):
        row = _make_user_row(uid=2, email="by@email.com")
        pool, _ = _make_pool(fetchrow_return=row)
        svc = AuthService(pool)
        user = await svc.get_user_by_email("by@email.com")
        assert user is not None
        assert user["email"] == "by@email.com"


# ══════════════════════════════════════════════════════════════
# TestSingleton
# ══════════════════════════════════════════════════════════════
class TestSingleton:
    def test_init_returns_instance(self):
        pool, _ = _make_pool()
        svc = init_auth_service(pool)
        assert isinstance(svc, AuthService)

    def test_get_returns_same_instance(self):
        pool, _ = _make_pool()
        svc = init_auth_service(pool)
        assert get_auth_service() is svc
