from datetime import datetime, timezone

import pytest
from freezegun import freeze_time

from src.fetchers.rss import fetch_rss


@pytest.mark.asyncio
@freeze_time("2026-05-15 12:00:00")
async def test_fetch_rss_returns_items_within_window(httpx_mock, rss_feed_xml):
    """解析 RSS 并保留时间窗口内的条目。"""
    httpx_mock.add_response(
        url="https://example.com/feed",
        text=rss_feed_xml,
        headers={"content-type": "application/rss+xml"},
    )
    source = {
        "name": "example",
        "type": "rss",
        "url": "https://example.com/feed",
    }
    items = await fetch_rss(source, window_hours=36)
    assert len(items) == 1
    assert items[0].url == "https://example.com/blog/agents"
    assert items[0].title == "Recent Post About Agents"
    assert items[0].source == "rss:example"
    assert items[0].published_at == datetime(2026, 5, 14, 10, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
@freeze_time("2026-05-15 12:00:00")
async def test_fetch_rss_filters_old_items(httpx_mock, rss_feed_xml):
    """过滤窗口外的旧条目。"""
    httpx_mock.add_response(
        url="https://example.com/feed",
        text=rss_feed_xml,
    )
    source = {
        "name": "example",
        "type": "rss",
        "url": "https://example.com/feed",
    }
    items = await fetch_rss(source, window_hours=36)
    # "Old Post" is from 2024, must be filtered.
    urls = [i.url for i in items]
    assert "https://example.com/blog/old" not in urls


@pytest.mark.asyncio
async def test_fetch_rss_http_error_raises(httpx_mock):
    """HTTP 错误向上抛异常。"""
    httpx_mock.add_response(
        url="https://example.com/feed",
        status_code=500,
    )
    source = {
        "name": "example",
        "type": "rss",
        "url": "https://example.com/feed",
    }
    with pytest.raises(Exception):
        await fetch_rss(source, window_hours=36)
