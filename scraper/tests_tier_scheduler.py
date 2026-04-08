"""Tests for tier_scheduler module."""

import pytest
from datetime import datetime, timezone, timedelta

from tier_scheduler import assign_tier, is_eligible, get_eligible_sources


@pytest.fixture
def now():
    return datetime(2026, 4, 8, 12, 0, 0, tzinfo=timezone.utc)


class TestAssignTier:
    def test_new_source_no_posts(self, now):
        assert assign_tier("src_1", {}, now) == "NEW"

    def test_hot_source_posted_today(self, now):
        dates = {"src_1": "2026-04-08T10:00:00.000Z"}
        assert assign_tier("src_1", dates, now) == "HOT"

    def test_hot_source_posted_6_days_ago(self, now):
        dates = {"src_1": "2026-04-02T12:00:00.000Z"}
        assert assign_tier("src_1", dates, now) == "HOT"

    def test_warm_source_posted_15_days_ago(self, now):
        dates = {"src_1": "2026-03-24T12:00:00.000Z"}
        assert assign_tier("src_1", dates, now) == "WARM"

    def test_cold_source_posted_60_days_ago(self, now):
        dates = {"src_1": "2026-02-07T12:00:00.000Z"}
        assert assign_tier("src_1", dates, now) == "COLD"

    def test_cold_source_posted_years_ago(self, now):
        dates = {"src_1": "2020-01-01T00:00:00.000Z"}
        assert assign_tier("src_1", dates, now) == "COLD"

    def test_boundary_exactly_7_days(self, now):
        dates = {"src_1": (now - timedelta(days=7)).isoformat()}
        assert assign_tier("src_1", dates, now) == "HOT"

    def test_boundary_just_over_7_days(self, now):
        dates = {"src_1": (now - timedelta(days=7, seconds=1)).isoformat()}
        assert assign_tier("src_1", dates, now) == "WARM"

    def test_boundary_exactly_30_days(self, now):
        dates = {"src_1": (now - timedelta(days=30)).isoformat()}
        assert assign_tier("src_1", dates, now) == "WARM"

    def test_invalid_date_returns_new(self, now):
        dates = {"src_1": "not-a-date"}
        assert assign_tier("src_1", dates, now) == "NEW"


class TestIsEligible:
    def test_new_tier_always_eligible(self, now):
        source = {"Last checked": now.isoformat()}
        assert is_eligible(source, "NEW", now) is True

    def test_hot_eligible_after_4h(self, now):
        source = {"Last checked": (now - timedelta(hours=5)).isoformat()}
        assert is_eligible(source, "HOT", now) is True

    def test_hot_not_eligible_within_4h(self, now):
        source = {"Last checked": (now - timedelta(hours=2)).isoformat()}
        assert is_eligible(source, "HOT", now) is False

    def test_warm_eligible_after_24h(self, now):
        source = {"Last checked": (now - timedelta(hours=25)).isoformat()}
        assert is_eligible(source, "WARM", now) is True

    def test_warm_not_eligible_within_24h(self, now):
        source = {"Last checked": (now - timedelta(hours=12)).isoformat()}
        assert is_eligible(source, "WARM", now) is False

    def test_cold_eligible_after_7_days(self, now):
        source = {"Last checked": (now - timedelta(days=8)).isoformat()}
        assert is_eligible(source, "COLD", now) is True

    def test_cold_not_eligible_within_7_days(self, now):
        source = {"Last checked": (now - timedelta(days=3)).isoformat()}
        assert is_eligible(source, "COLD", now) is False

    def test_never_checked_always_eligible(self, now):
        source = {}
        assert is_eligible(source, "HOT", now) is True

    def test_empty_last_checked_eligible(self, now):
        source = {"Last checked": ""}
        assert is_eligible(source, "WARM", now) is True


class TestGetEligibleSources:
    def test_selects_up_to_limit(self, now):
        dates = {
            "s1": "2026-04-08T10:00:00Z",
            "s2": "2026-04-07T10:00:00Z",
            "s3": "2026-04-06T10:00:00Z",
            "s4": "2026-04-05T10:00:00Z",
        }
        sources = [
            {"id": "s1", "Last checked": "2026-04-08T01:00:00Z"},
            {"id": "s2", "Last checked": "2026-04-08T01:00:00Z"},
            {"id": "s3", "Last checked": "2026-04-08T01:00:00Z"},
            {"id": "s4", "Last checked": "2026-04-08T01:00:00Z"},
        ]
        selected, stats = get_eligible_sources(sources, dates, limit=3)
        assert len(selected) == 3
        assert stats["eligible_count"] == 4
        assert stats["selected_count"] == 3

    def test_new_sources_prioritized(self, now):
        dates = {"s1": "2026-04-08T10:00:00Z"}
        sources = [
            {"id": "s1", "Last checked": "2026-04-08T01:00:00Z"},
            {"id": "s2"},
        ]
        selected, stats = get_eligible_sources(sources, dates, limit=3)
        assert selected[0]["id"] == "s2"

    def test_no_eligible_returns_empty(self, now):
        dates = {"s1": "2026-04-08T10:00:00Z"}
        sources = [
            {"id": "s1", "Last checked": "2026-04-08T11:00:00Z"},
        ]
        selected, stats = get_eligible_sources(sources, dates, limit=3)
        assert len(selected) == 0

    def test_mixed_tiers(self, now):
        dates = {
            "s1": "2026-04-08T10:00:00Z",
            "s2": "2026-03-20T10:00:00Z",
            "s3": "2025-01-01T10:00:00Z",
        }
        sources = [
            {"id": "s1", "Last checked": "2026-04-08T01:00:00Z"},
            {"id": "s2", "Last checked": "2026-04-06T01:00:00Z"},
            {"id": "s3", "Last checked": "2026-03-30T01:00:00Z"},
        ]
        selected, stats = get_eligible_sources(sources, dates, limit=3)
        assert len(selected) == 3
        assert stats["tier_counts"] == {"HOT": 1, "WARM": 1, "COLD": 1, "NEW": 0}
