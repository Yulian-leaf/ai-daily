import re

import pytest
from freezegun import freeze_time

from src.fetchers.github import fetch_github


@pytest.mark.asyncio
@freeze_time("2026-05-15 12:00:00")
async def test_fetch_github_filters_by_pushed_recency_and_stars(
    httpx_mock, github_search_json
):
    """按 push 时间和 star 数过滤 GitHub 仓库。"""
    httpx_mock.add_response(
        url=re.compile(r"https://api\.github\.com/search/repositories.*"),
        text=github_search_json,
        headers={"content-type": "application/json"},
    )
    source = {
        "name": "github-trending-agent",
        "type": "github",
        "topic": "agent",
        "min_stars": 10,
    }
    items = await fetch_github(source, window_hours=72)
    urls = [i.url for i in items]
    assert "https://github.com/alice/cool-agent" in urls
    # bob/old-agent has min_stars=10 below 5? It's 5, so below threshold AND old
    assert "https://github.com/bob/old-agent" not in urls
    cool = next(i for i in items if i.url == "https://github.com/alice/cool-agent")
    assert cool.title == "alice/cool-agent"
    assert "LLM agent framework" in cool.content
    assert cool.source == "github:github-trending-agent"
