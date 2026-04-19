# -*- coding: utf-8 -*-
"""
routers/auth_router.py — Authentication endpoints
==================================================
POST /api/v1/auth/register
POST /api/v1/auth/login
POST /api/v1/auth/refresh
GET  /api/v1/auth/me
"""
import re
import logging
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, field_validator
from typing import Optional
from core import app_state
from auth_service import decode_token, extract_user_id

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


# ── Request models ──────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email:    str
    password: str
    role:     Optional[str] = "user"

    @field_validator("email")
    @classmethod
    def clean_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not v or "@" not in v:
            raise ValueError("صيغة البريد الإلكتروني غير صحيحة")
        return v

    @field_validator("password")
    @classmethod
    def check_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("كلمة المرور يجب أن تكون 8 أحرف على الأقل")
        return v

    @field_validator("role")
    @classmethod
    def sanitize_role(cls, v: Optional[str]) -> str:
        allowed = {"user", "admin"}
        return v if v in allowed else "user"


class LoginRequest(BaseModel):
    email:    str
    password: str

    @field_validator("email")
    @classmethod
    def clean_email(cls, v: str) -> str:
        return v.strip().lower()


class RefreshRequest(BaseModel):
    refresh_token: str


# ── Helper: extract Bearer token ────────────────────────────────

def _get_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


# ── Endpoints ───────────────────────────────────────────────────

@router.post("/register")
async def register(req: RegisterRequest):
    svc = app_state.get_auth_service() if hasattr(app_state, "get_auth_service") else None
    if not svc:
        raise HTTPException(503, "auth_service غير متاح")
    result = await svc.register(req.email, req.password, req.role)
    if not result["ok"]:
        raise HTTPException(400, result["error"])
    return {
        "message":    "تم التسجيل بنجاح",
        "user_id":    result["user_id"],
        "email":      result["email"],
        "role":       result["role"],
        "created_at": result["created_at"],
    }


@router.post("/login")
async def login(req: LoginRequest):
    svc = app_state.get_auth_service() if hasattr(app_state, "get_auth_service") else None
    if not svc:
        raise HTTPException(503, "auth_service غير متاح")
    result = await svc.login(req.email, req.password)
    if not result["ok"]:
        raise HTTPException(401, result["error"])
    return {
        "access_token":  result["access_token"],
        "refresh_token": result["refresh_token"],
        "token_type":    "bearer",
        "user_id":       result["user_id"],
        "email":         result["email"],
        "role":          result["role"],
    }


@router.post("/refresh")
async def refresh_token(req: RefreshRequest):
    svc = app_state.get_auth_service() if hasattr(app_state, "get_auth_service") else None
    if not svc:
        raise HTTPException(503, "auth_service غير متاح")
    result = await svc.refresh(req.refresh_token)
    if not result["ok"]:
        raise HTTPException(401, result["error"])
    return {
        "access_token": result["access_token"],
        "token_type":   "bearer",
    }


@router.get("/me")
async def get_me(authorization: Optional[str] = Header(None)):
    token = _get_bearer(authorization)
    if not token:
        raise HTTPException(401, "Authorization header مطلوب (Bearer token)")
    user_id = extract_user_id(token)
    if not user_id:
        raise HTTPException(401, "توكن غير صالح أو منتهي الصلاحية")
    svc = app_state.get_auth_service() if hasattr(app_state, "get_auth_service") else None
    if not svc:
        raise HTTPException(503, "auth_service غير متاح")
    user = await svc.get_user(user_id)
    if not user:
        raise HTTPException(404, "المستخدم غير موجود")
    return user
