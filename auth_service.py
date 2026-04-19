# -*- coding: utf-8 -*-
"""
auth_service.py — نظام المصادقة (JWT + bcrypt)
================================================
المسؤوليات:
  - تجزئة كلمة المرور (bcrypt)
  - إنشاء والتحقق من JWT access + refresh tokens
  - عمليات DB: تسجيل / تسجيل دخول / إحضار المستخدم
  - CREATE TABLE users إذا لم تكن موجودة

الجداول المُنشأة:
  users (id SERIAL PK, email TEXT UNIQUE, password_hash TEXT,
         role TEXT DEFAULT 'user', created_at TIMESTAMPTZ, last_login TIMESTAMPTZ)
"""
import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import bcrypt as _bcrypt_lib
import jwt

log = logging.getLogger(__name__)

# ── JWT configuration ──
_JWT_SECRET      = os.getenv("JWT_SECRET", "mizan-dev-secret-change-in-prod")
_JWT_ALGORITHM   = "HS256"
_ACCESS_MINUTES  = 15
_REFRESH_DAYS    = 7

# ── DB SQL ──
_CREATE_USERS_TABLE = """
CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    email         TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'user',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS users_email_idx ON users (email);
"""

_SINGLETON: Optional["AuthService"] = None


def init_auth_service(pool) -> "AuthService":
    global _SINGLETON
    _SINGLETON = AuthService(pool)
    return _SINGLETON


def get_auth_service() -> Optional["AuthService"]:
    return _SINGLETON


# ══════════════════════════════════════════════════════════════
# Password helpers
# ══════════════════════════════════════════════════════════════

def hash_password(plain: str) -> str:
    """Hash a plaintext password with bcrypt (rounds=12)."""
    salt = _bcrypt_lib.gensalt(rounds=12)
    return _bcrypt_lib.hashpw(plain.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify plaintext against bcrypt hash."""
    try:
        return _bcrypt_lib.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════
# Token helpers
# ══════════════════════════════════════════════════════════════

def create_access_token(user_id: int, email: str, role: str) -> str:
    """Issue a short-lived access JWT (15 min)."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub":   str(user_id),
        "email": email,
        "role":  role,
        "type":  "access",
        "iat":   now,
        "exp":   now + timedelta(minutes=_ACCESS_MINUTES),
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


def create_refresh_token(user_id: int) -> str:
    """Issue a long-lived refresh JWT (7 days)."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub":  str(user_id),
        "type": "refresh",
        "iat":  now,
        "exp":  now + timedelta(days=_REFRESH_DAYS),
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """
    Decode and validate a JWT.
    Raises jwt.ExpiredSignatureError or jwt.InvalidTokenError on failure.
    """
    return jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])


def extract_user_id(token: str) -> Optional[int]:
    """Return user_id from a valid access token, or None."""
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            return None
        return int(payload["sub"])
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════
# AuthService — DB operations
# ══════════════════════════════════════════════════════════════

class AuthService:
    def __init__(self, pool):
        self._pool = pool

    # ── Setup ──────────────────────────────────────────────────

    async def ensure_table(self) -> bool:
        if not self._pool:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(_CREATE_USERS_TABLE)
            log.info("✓ users table ready")
            return True
        except Exception as e:
            log.warning("ensure_table (users): %s", e)
            return False

    # ── Register ───────────────────────────────────────────────

    async def register(self, email: str, password: str, role: str = "user") -> dict:
        """
        Create a new user.
        Returns {"ok": True, "user_id": int} or {"ok": False, "error": str}.
        """
        if not email or not password:
            return {"ok": False, "error": "email وpassword مطلوبان"}
        if len(password) < 8:
            return {"ok": False, "error": "كلمة المرور يجب أن تكون 8 أحرف على الأقل"}
        if "@" not in email or "." not in email.split("@")[-1]:
            return {"ok": False, "error": "صيغة البريد الإلكتروني غير صحيحة"}

        pw_hash = hash_password(password)
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "INSERT INTO users (email, password_hash, role) VALUES ($1, $2, $3) "
                    "RETURNING id, email, role, created_at",
                    email.lower().strip(), pw_hash, role,
                )
                return {
                    "ok": True,
                    "user_id":    row["id"],
                    "email":      row["email"],
                    "role":       row["role"],
                    "created_at": row["created_at"].isoformat(),
                }
        except Exception as e:
            err = str(e)
            if "unique" in err.lower() or "duplicate" in err.lower():
                return {"ok": False, "error": "هذا البريد الإلكتروني مسجّل مسبقاً"}
            log.warning("register error: %s", e)
            return {"ok": False, "error": "خطأ في قاعدة البيانات"}

    # ── Login ──────────────────────────────────────────────────

    async def login(self, email: str, password: str) -> dict:
        """
        Authenticate a user.
        Returns {"ok": True, "access_token": ..., "refresh_token": ...}
        or {"ok": False, "error": str}.
        """
        if not email or not password:
            return {"ok": False, "error": "email وpassword مطلوبان"}
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, email, password_hash, role FROM users WHERE email = $1",
                    email.lower().strip(),
                )
            if not row:
                return {"ok": False, "error": "بيانات الدخول غير صحيحة"}
            if not verify_password(password, row["password_hash"]):
                return {"ok": False, "error": "بيانات الدخول غير صحيحة"}

            # Update last_login
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "UPDATE users SET last_login = NOW() WHERE id = $1", row["id"]
                )

            access  = create_access_token(row["id"], row["email"], row["role"])
            refresh = create_refresh_token(row["id"])
            return {
                "ok":            True,
                "access_token":  access,
                "refresh_token": refresh,
                "token_type":    "bearer",
                "user_id":       row["id"],
                "email":         row["email"],
                "role":          row["role"],
            }
        except Exception as e:
            log.warning("login error: %s", e)
            return {"ok": False, "error": "خطأ في قاعدة البيانات"}

    # ── Refresh ────────────────────────────────────────────────

    async def refresh(self, refresh_token: str) -> dict:
        """Exchange a refresh token for a new access token."""
        try:
            payload = decode_token(refresh_token)
            if payload.get("type") != "refresh":
                return {"ok": False, "error": "نوع التوكن غير صحيح"}
            user_id = int(payload["sub"])
        except jwt.ExpiredSignatureError:
            return {"ok": False, "error": "انتهت صلاحية التوكن"}
        except Exception:
            return {"ok": False, "error": "توكن غير صالح"}

        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, email, role FROM users WHERE id = $1", user_id
                )
            if not row:
                return {"ok": False, "error": "المستخدم غير موجود"}
            access = create_access_token(row["id"], row["email"], row["role"])
            return {"ok": True, "access_token": access, "token_type": "bearer"}
        except Exception as e:
            log.warning("refresh error: %s", e)
            return {"ok": False, "error": "خطأ في قاعدة البيانات"}

    # ── Get user ───────────────────────────────────────────────

    async def get_user(self, user_id: int) -> Optional[dict]:
        """Return public user info by id."""
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, email, role, created_at, last_login "
                    "FROM users WHERE id = $1",
                    user_id,
                )
            if not row:
                return None
            return {
                "id":         row["id"],
                "email":      row["email"],
                "role":       row["role"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "last_login": row["last_login"].isoformat()  if row["last_login"]  else None,
            }
        except Exception as e:
            log.warning("get_user error: %s", e)
            return None

    async def get_user_by_email(self, email: str) -> Optional[dict]:
        """Return public user info by email."""
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, email, role, created_at, last_login "
                    "FROM users WHERE email = $1",
                    email.lower().strip(),
                )
            if not row:
                return None
            return {
                "id":         row["id"],
                "email":      row["email"],
                "role":       row["role"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "last_login": row["last_login"].isoformat()  if row["last_login"]  else None,
            }
        except Exception as e:
            log.warning("get_user_by_email error: %s", e)
            return None
