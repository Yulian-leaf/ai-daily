from datetime import datetime, timezone
from pathlib import Path

from src.models import Item
from src.storage import Storage


def _item(url: str, source: str = "rss:test") -> Item:
    return Item(
        url=url,
        title=f"title for {url}",
        content="content",
        published_at=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc),
        source=source,
    )


def test_init_creates_schema(tmp_path: Path):
    """init 建库建表，重复调用幂等。"""
    db_path = tmp_path / "test.db"
    storage = Storage(db_path)
    storage.init()
    # Calling twice must be idempotent.
    storage.init()
    storage.close()
    assert db_path.exists()


def test_seen_urls_empty_initially(tmp_path: Path):
    """空库 seen_urls 返回空集。"""
    storage = Storage(tmp_path / "test.db")
    storage.init()
    assert storage.seen_urls(["https://a", "https://b"]) == set()
    storage.close()


def test_record_and_check_seen_urls(tmp_path: Path):
    """入库后 seen_urls 能命中已存 URL。"""
    storage = Storage(tmp_path / "test.db")
    storage.init()
    storage.record_items([_item("https://a"), _item("https://b")])
    seen = storage.seen_urls(["https://a", "https://c"])
    assert seen == {"https://a"}
    storage.close()


def test_record_items_is_idempotent_on_duplicate_url(tmp_path: Path):
    """重复 URL 幂等写入，不报错。"""
    storage = Storage(tmp_path / "test.db")
    storage.init()
    storage.record_items([_item("https://a")])
    # Second insert of same URL should not raise.
    storage.record_items([_item("https://a")])
    assert storage.seen_urls(["https://a"]) == {"https://a"}
    storage.close()


def test_record_items_preserves_first_seen_timestamp(tmp_path: Path):
    """重复入库保留首次 first_seen。"""
    storage = Storage(tmp_path / "test.db")
    storage.init()
    storage.record_items([_item("https://a")])
    row = storage.fetch_item_row("https://a")
    first_seen_1 = row["first_seen"]
    storage.record_items([_item("https://a")])
    row2 = storage.fetch_item_row("https://a")
    assert row2["first_seen"] == first_seen_1
    storage.close()
