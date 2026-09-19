"""Tests for the Stage 3-dedup surfaced_at state: today/archive split, mark,
and the pre-existing-table migration."""
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.models import Item, Score, Summary
from src.storage import Storage


def _item(url: str, days_ago: int = 0) -> Item:
    return Item(
        url=url, title="t", content="c",
        published_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        source="test",
    )


def _seed_two(s: Storage):
    s.record_items([_item("https://a"), _item("https://b")])
    s.save_score("https://a", Score(score=9, tags=["LLM"], model="m", cost_usd=0.001))
    s.save_summary("https://a", Summary(innovation="ia", approach="ap", metrics="m",
                                        links="l", why_relevant="w", model="m",
                                        cost_usd=0.01))
    s.save_score("https://b", Score(score=8, tags=["agent"], model="m", cost_usd=0.001))
    s.save_summary("https://b", Summary(innovation="ib", approach="ap", metrics="m",
                                        links="l", why_relevant="w", model="m",
                                        cost_usd=0.01))


def test_get_today_returns_only_unsurfaced(tmp_path: Path):
    """未上墙的摘要属于今日，按分数倒序。"""
    s = Storage(tmp_path / "t.db"); s.init()
    _seed_two(s)
    today = s.get_today_summaries(min_score=7)
    assert {a.url for a in today} == {"https://a", "https://b"}
    # Score desc, so a (9) comes before b (8)
    assert today[0].url == "https://a"
    s.close()


def test_get_today_skips_score_only_rows(tmp_path: Path):
    """只有分数没摘要的行不进今日。"""
    s = Storage(tmp_path / "t.db"); s.init()
    s.record_items([_item("https://scored-only")])
    s.save_score("https://scored-only",
                 Score(score=9, tags=[], model="m", cost_usd=0.001))
    # No save_summary call → innovation IS NULL
    today = s.get_today_summaries(min_score=7)
    assert today == []
    s.close()


def test_mark_surfaced_keeps_items_in_today_until_next_day(tmp_path: Path):
    """上墙后当天仍在今日，不提前进归档。"""
    s = Storage(tmp_path / "t.db"); s.init()
    _seed_two(s)
    n = s.mark_surfaced(["https://a", "https://b"])
    assert n == 2

    # Surfaced today → still in "today" (date-based split).
    assert {a.url for a in s.get_today_summaries(min_score=7)} == {"https://a", "https://b"}
    # Not in archive yet: surfaced_at is today, not a previous day.
    assert s.get_archive_summaries(min_score=7, within_days=30) == []
    s.close()


def test_mark_surfaced_is_idempotent(tmp_path: Path):
    """mark_surfaced 幂等：已上墙的不再更新。"""
    s = Storage(tmp_path / "t.db"); s.init()
    _seed_two(s)
    assert s.mark_surfaced(["https://a"]) == 1
    # Second call on the same url: NULL guard means no update.
    assert s.mark_surfaced(["https://a"]) == 0
    s.close()


def test_mark_surfaced_empty_list(tmp_path: Path):
    """空列表返回 0。"""
    s = Storage(tmp_path / "t.db"); s.init()
    assert s.mark_surfaced([]) == 0
    s.close()


def test_archive_filters_by_within_days(tmp_path: Path):
    """归档按 within_days 窗口过滤。"""
    s = Storage(tmp_path / "t.db"); s.init()
    _seed_two(s)
    # Surface a yesterday (in window), b 30 days ago (outside window).
    conn = s._conn_or_die()
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    conn.execute("UPDATE summaries SET surfaced_at=? WHERE url=?",
                 (yesterday, "https://a"))
    conn.execute("UPDATE summaries SET surfaced_at=? WHERE url=?", (old, "https://b"))
    conn.commit()

    archive = s.get_archive_summaries(min_score=7, within_days=7)
    assert {a.url for a in archive} == {"https://a"}  # b is outside window
    s.close()


def test_init_migrates_old_summaries_table_backfills_surfaced_at(tmp_path: Path):
    """Simulate a DB created before the surfaced_at column existed; init() must
    add the column and backfill from created_at so existing rows are archived
    (not surfaced as 'today new')."""
    db = tmp_path / "t.db"
    # Build a pre-feature DB by hand: items + summaries WITHOUT surfaced_at.
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE items (
            url TEXT PRIMARY KEY, title TEXT NOT NULL, content TEXT NOT NULL,
            source TEXT NOT NULL, published_at TEXT NOT NULL,
            raw_json TEXT NOT NULL DEFAULT '{}', first_seen TEXT NOT NULL
        );
        CREATE TABLE summaries (
            url TEXT PRIMARY KEY REFERENCES items(url),
            score INTEGER NOT NULL, tags_json TEXT NOT NULL,
            scorer_model TEXT NOT NULL,
            scorer_cost_usd REAL NOT NULL DEFAULT 0,
            innovation TEXT, approach TEXT, metrics TEXT, links TEXT,
            why_relevant TEXT, summarizer_model TEXT, summarizer_cost_usd REAL,
            created_at TEXT NOT NULL
        );
        INSERT INTO items VALUES ('https://old','t','c','src','2026-05-10T00:00:00+00:00','{}','2026-05-10T00:00:00+00:00');
        INSERT INTO summaries
          (url, score, tags_json, scorer_model, scorer_cost_usd,
           innovation, approach, metrics, links, why_relevant,
           summarizer_model, summarizer_cost_usd, created_at)
          VALUES
          ('https://old', 9, '["LLM"]', 'm', 0.001,
           'i','a','m','l','w','m', 0.01, '2026-05-10T00:00:00+00:00');
    """)
    conn.commit()
    conn.close()

    s = Storage(db); s.init()
    # After migration, the existing summary should be in archive (not today).
    assert s.get_today_summaries(min_score=7) == []
    archive = s.get_archive_summaries(min_score=7, within_days=365)
    assert len(archive) == 1
    assert archive[0].url == "https://old"
    s.close()
