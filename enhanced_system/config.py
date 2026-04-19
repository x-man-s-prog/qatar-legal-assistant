# -*- coding: utf-8 -*-
"""
إعدادات النظام — المساعد القانوني القطري MAX Edition
System Configuration for Qatari Legal Assistant
"""

import os
from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """إعدادات التطبيق الموحدة"""

    # ═══════════════════════════════════════════════
    # مفاتيح API
    # ═══════════════════════════════════════════════
    anthropic_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None

    # ═══════════════════════════════════════════════
    # إعدادات قاعدة البيانات
    # ═══════════════════════════════════════════════
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "ragdb"
    db_user: str = "raguser"
    db_password: str = "RAGsecret2024!"

    # ═══════════════════════════════════════════════
    # إعدادات Ollama
    # ═══════════════════════════════════════════════
    ollama_host: str = "http://localhost:11434"
    model_embed: str = "nomic-embed-text"
    model_ollama_llm: str = "qwen2.5:1.5b"

    # ═══════════════════════════════════════════════
    # إعدادات النماذج
    # ═══════════════════════════════════════════════
    model_main: str = "claude-3-5-sonnet-20241022"
    model_fast: str = "claude-3-haiku-20240307"
    model_gemini: str = "gemini-2.0-flash"

    # ═══════════════════════════════════════════════
    # إعدادات التطبيق
    # ═══════════════════════════════════════════════
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = False
    log_level: str = "INFO"

    @property
    def db_url(self) -> str:
        """رابط قاعدة البيانات"""
        return f"postgresql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"

    @property
    def db_dsn(self) -> str:
        """DSN قاعدة البيانات لـ asyncpg"""
        return f"postgresql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    """الحصول على إعدادات التطبيق (مخزنة مؤقتًا)"""
    return Settings()
