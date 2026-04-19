# -*- coding: utf-8 -*-
"""اختبارات RateLimiter."""
import sys, os, asyncio, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from rate_limiter import RateLimiter


@pytest.fixture
def limiter():
    return RateLimiter(redis_url=None, max_requests=5, window_seconds=60)


class TestInMemoryRateLimiter:

    @pytest.mark.asyncio
    async def test_first_request_allowed(self, limiter):
        allowed, remaining = await limiter.is_allowed("user_1")
        assert allowed is True
        assert remaining == 4  # 5 - 1

    @pytest.mark.asyncio
    async def test_requests_up_to_limit_allowed(self, limiter):
        for i in range(5):
            allowed, _ = await limiter.is_allowed("user_2")
            assert allowed is True

    @pytest.mark.asyncio
    async def test_exceeding_limit_blocked(self, limiter):
        for _ in range(5):
            await limiter.is_allowed("user_3")
        allowed, remaining = await limiter.is_allowed("user_3")
        assert allowed is False
        assert remaining == 0

    @pytest.mark.asyncio
    async def test_reset_clears_limit(self, limiter):
        for _ in range(5):
            await limiter.is_allowed("user_4")
        await limiter.reset("user_4")
        allowed, _ = await limiter.is_allowed("user_4")
        assert allowed is True

    @pytest.mark.asyncio
    async def test_different_users_independent(self, limiter):
        """مستخدمون مختلفون لديهم حدودهم المستقلة."""
        for _ in range(5):
            await limiter.is_allowed("user_a")
        allowed, _ = await limiter.is_allowed("user_b")
        assert allowed is True

    def test_get_stats_structure(self, limiter):
        stats = limiter.get_stats()
        assert "backend"        in stats
        assert "max_requests"   in stats
        assert "window_seconds" in stats
        assert "active_clients" in stats

    def test_get_stats_backend_is_in_memory(self, limiter):
        assert limiter.get_stats()["backend"] == "in_memory"
