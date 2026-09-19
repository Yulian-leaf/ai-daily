from datetime import datetime, timezone
from pathlib import Path

from src.dedup import dedup_by_url
from src.models import Item
from src.storage import Storage


def _item(url: str) -> Item:
    return Item(
        url=url,
        title=url,
        content="",
        published_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
        source="rss:test",
    )


def test_dedup_by_url_removes_already_seen(tmp_path: Path):
    """去掉库里已存在的 URL，只保留新条目。"""
    storage = Storage(tmp_path / "t.db")
    storage.init()
    storage.record_items([_item("https://a"), _item("https://b")])
    fresh = [_item("https://a"), _item("https://c")]
    result = dedup_by_url(fresh, storage)
    assert [i.url for i in result] == ["https://c"]
    storage.close()


def test_dedup_by_url_dedups_within_batch(tmp_path: Path):
    """同一批里重复 URL 只保留第一个。"""
    storage = Storage(tmp_path / "t.db")
    storage.init()
    fresh = [_item("https://a"), _item("https://a"), _item("https://b")]
    result = dedup_by_url(fresh, storage)
    urls = [i.url for i in result]
    assert urls == ["https://a", "https://b"]
    storage.close()


def test_dedup_by_url_empty_input(tmp_path: Path):
    """空输入返回空列表，不崩。"""
    storage = Storage(tmp_path / "t.db")
    storage.init()
    assert dedup_by_url([], storage) == []
    storage.close()
