import re

import pytest
from freezegun import freeze_time

from src.fetchers.hackernews import fetch_hackernews


@pytest.mark.asyncio
@freeze_time("2026-05-15 13:00:00")
async def test_fetch_hn_filters_by_points(httpx_mock, hn_search_json):
    """HN 结果按分数阈值过滤。"""
    httpx_mock.add_response(
        url=re.compile(r"https://hn\.algolia\.com/api/v1/search.*"),
        text=hn_search_json,
        headers={"content-type": "application/json"},
    )
    source = {
        "name": "hackernews-ai",
        "type": "hackernews",
        "query": "AI",
        "min_points": 100,
    }
    items = await fetch_hackernews(source, window_hours=36)
    urls = [i.url for i in items]
    assert "https://anthropic.com/news/claude-4-7" in urls
    assert "https://example.com/low" not in urls
    item = next(i for i in items if "claude-4-7" in i.url)
    assert item.title == "Claude 4.7 release notes"
    assert item.source == "hackernews:hackernews-ai"
