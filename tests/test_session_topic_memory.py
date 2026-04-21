# -*- coding: utf-8 -*-
"""Unit tests for core/session_topic_memory."""
import pytest

from core.session_topic_memory import (
    set_session_topic,
    get_session_topic,
    set_session_topic_sync,
    get_session_topic_sync,
)


@pytest.mark.asyncio
async def test_stm_set_and_get():
    sid = "test-stm-1"
    assert await set_session_topic(sid, "حضانة") is True
    assert await get_session_topic(sid) == "حضانة"


@pytest.mark.asyncio
async def test_stm_ignores_general():
    sid = "test-stm-2"
    # "عام" is the sentinel "no topic" → must NOT be stored
    assert await set_session_topic(sid, "عام") is False
    assert await get_session_topic(sid) is None


@pytest.mark.asyncio
async def test_stm_missing_session():
    assert await get_session_topic("nonexistent-" + "x" * 32) is None


def test_stm_sync_wrappers():
    sid = "test-stm-sync"
    assert set_session_topic_sync(sid, "نفقة") is True
    assert get_session_topic_sync(sid) == "نفقة"


@pytest.mark.asyncio
async def test_stm_overwrite():
    sid = "test-stm-overwrite"
    await set_session_topic(sid, "حضانة")
    await set_session_topic(sid, "طلاق")
    assert await get_session_topic(sid) == "طلاق"
