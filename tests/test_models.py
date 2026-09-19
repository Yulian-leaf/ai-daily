from datetime import datetime, timezone

from src.models import Item


def test_item_construction_minimal():
    """最小构造 Item，raw 默认空字典。"""
    item = Item(
        url="https://arxiv.org/abs/2401.00001",
        title="Sample Paper",
        content="Abstract content",
        published_at=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc),
        source="arxiv:cs.AI",
    )
    assert item.url == "https://arxiv.org/abs/2401.00001"
    assert item.title == "Sample Paper"
    assert item.source == "arxiv:cs.AI"
    assert item.raw == {}  # default


def test_item_with_raw_payload():
    """带 raw 原始数据的 Item 能保留原样。"""
    raw = {"id": "2401.00001", "categories": ["cs.AI"]}
    item = Item(
        url="https://arxiv.org/abs/2401.00001",
        title="Sample Paper",
        content="Abstract",
        published_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
        source="arxiv:cs.AI",
        raw=raw,
    )
    assert item.raw == raw


def test_item_equality_by_value():
    """同字段的 Item 相等（dataclass 值相等）。"""
    a = Item(
        url="https://example.com/x",
        title="x",
        content="",
        published_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
        source="rss:example",
    )
    b = Item(
        url="https://example.com/x",
        title="x",
        content="",
        published_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
        source="rss:example",
    )
    assert a == b
