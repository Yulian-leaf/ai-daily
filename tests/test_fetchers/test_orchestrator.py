from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from src.fetchers import fetch_all
from src.models import Item


def _item(url: str) -> Item:
    return Item(
        url=url,
        title=url,
        content="",
        published_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
        source="rss:test",
    )


@pytest.mark.asyncio
async def test_fetch_all_aggregates_results(monkeypatch):
    """多源并发抓取结果聚合在一起。"""
    rss = AsyncMock(return_value=[_item("https://a"), _item("https://b")])
    arxiv = AsyncMock(return_value=[_item("https://c")])
    github = AsyncMock(return_value=[])
    hackernews = AsyncMock(return_value=[])
    monkeypatch.setattr("src.fetchers.fetch_rss", rss)
    monkeypatch.setattr("src.fetchers.fetch_arxiv", arxiv)
    monkeypatch.setattr("src.fetchers.fetch_github", github)
    monkeypatch.setattr("src.fetchers.fetch_hackernews", hackernews)

    sources = [
        {"name": "s1", "type": "rss", "url": "https://x"},
        {"name": "s2", "type": "arxiv", "categories": ["cs.AI"]},
        {"name": "s3", "type": "github", "topic": "agent"},
        {"name": "s4", "type": "hackernews", "query": "AI"},
    ]
    items = await fetch_all(sources, window_hours=36)
    urls = sorted(i.url for i in items)
    assert urls == ["https://a", "https://b", "https://c"]


@pytest.mark.asyncio
async def test_fetch_all_isolates_failing_fetcher(monkeypatch, caplog):
    """单源失败被吞掉并打日志，不影响其它源。"""
    rss = AsyncMock(side_effect=RuntimeError("boom"))
    arxiv = AsyncMock(return_value=[_item("https://ok")])
    github = AsyncMock(return_value=[])
    hackernews = AsyncMock(return_value=[])
    monkeypatch.setattr("src.fetchers.fetch_rss", rss)
    monkeypatch.setattr("src.fetchers.fetch_arxiv", arxiv)
    monkeypatch.setattr("src.fetchers.fetch_github", github)
    monkeypatch.setattr("src.fetchers.fetch_hackernews", hackernews)

    sources = [
        {"name": "bad", "type": "rss", "url": "https://x"},
        {"name": "good", "type": "arxiv", "categories": ["cs.AI"]},
    ]
    items = await fetch_all(sources, window_hours=36)
    assert [i.url for i in items] == ["https://ok"]
    # Failure was logged.
    assert any("bad" in rec.message and "boom" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_fetch_all_skips_unknown_source_type(monkeypatch, caplog):
    """未知 source type 跳过并打日志。"""
    sources = [{"name": "weird", "type": "smoke-signal"}]
    items = await fetch_all(sources, window_hours=36)
    assert items == []
    assert any("unknown source type" in rec.message for rec in caplog.records)
