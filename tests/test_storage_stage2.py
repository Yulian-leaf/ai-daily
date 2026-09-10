import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from src.models import Item, Score, Summary
from src.storage import Storage


def _item(url: str, content: str = "body", title: str = "t", days_ago: int = 0) -> Item:
    return Item(
        url=url,
        title=title,
        content=content,
        published_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        source="test",
        raw={"k": "v"},
    )


def test_items_table_persists_full_content(tmp_path: Path):
    s = Storage(tmp_path / "t.db")
    s.init()
    s.record_items([_item("https://a", content="long body about LLMs")])
    rows = s.get_items_by_urls(["https://a"])
    assert len(rows) == 1
    assert rows[0].content == "long body about LLMs"
    assert rows[0].raw == {"k": "v"}
    s.close()


def test_seen_urls_still_filters_known(tmp_path: Path):
    s = Storage(tmp_path / "t.db")
    s.init()
    s.record_items([_item("https://a")])
    assert s.seen_urls(["https://a", "https://b"]) == {"https://a"}
    s.close()


def test_save_score_and_summary_roundtrip(tmp_path: Path):
    s = Storage(tmp_path / "t.db")
    s.init()
    s.record_items([_item("https://a")])
    s.save_score("https://a", Score(score=8, tags=["LLM", "agent"], model="m1", cost_usd=0.001))
    s.save_summary(
        "https://a",
        Summary(
            innovation="x",
            approach="y",
            metrics="z",
            links="https://a",
            why_relevant="r",
            model="m2",
            cost_usd=0.01,
        ),
    )
    analyses = s.get_top_summaries(min_score=7, limit=10, within_days=1)
    assert len(analyses) == 1
    a = analyses[0]
    assert a.url == "https://a"
    assert a.score.score == 8
    assert a.score.tags == ["LLM", "agent"]
    assert a.summary is not None
    assert a.summary.innovation == "x"
    assert a.total_cost_usd == pytest.approx(0.011)
    s.close()


def test_save_score_persists_field(tmp_path: Path):
    s = Storage(tmp_path / "t.db")
    s.init()
    s.record_items([_item("https://a")])
    s.save_score("https://a", Score(score=8, tags=["protein"], model="m1",
                                    cost_usd=0.001, field="protein"))
    analyses = s.get_top_summaries(min_score=7, limit=10, within_days=1)
    assert analyses[0].score.field == "protein"
    s.close()


def test_init_migrates_adds_field_column(tmp_path: Path):
    """A DB built before the field column existed must be migrated and
    read back with an empty field (not crash)."""
    import sqlite3
    db = tmp_path / "t.db"
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
            scorer_model TEXT NOT NULL, scorer_cost_usd REAL NOT NULL DEFAULT 0,
            innovation TEXT, approach TEXT, metrics TEXT, links TEXT,
            why_relevant TEXT, summarizer_model TEXT, summarizer_cost_usd REAL,
            created_at TEXT NOT NULL, surfaced_at TEXT
        );
        INSERT INTO items VALUES ('https://a','t','c','s','2026-05-10T00:00:00+00:00','{}','2026-05-10T00:00:00+00:00');
        INSERT INTO summaries (url, score, tags_json, scorer_model, scorer_cost_usd, created_at)
          VALUES ('https://a', 9, '["x"]', 'm', 0.001, '2026-05-10T00:00:00+00:00');
    """)
    conn.commit()
    conn.close()
    s = Storage(db); s.init()
    top = s.get_top_summaries(min_score=7, limit=10, within_days=365)
    assert top[0].score.field == ""
    s.close()


def test_get_unscored_items_filters_by_first_seen_not_published_at(tmp_path: Path):
    """An item with old published_at but fresh first_seen MUST appear;
    an item with old first_seen MUST NOT appear, even if published_at is fresh.
    """
    s = Storage(tmp_path / "t.db")
    s.init()

    # Recently recorded item with old published_at - should appear
    s.record_items([_item("https://recent-discovery", days_ago=30)])

    # Insert directly to simulate old first_seen with fresh published_at
    conn = s._conn_or_die()
    old_first_seen = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    fresh_pub = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO items (url, title, content, source, published_at, raw_json, first_seen)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("https://stale-but-recently-published", "t", "c", "test",
         fresh_pub, "{}", old_first_seen),
    )
    conn.commit()

    unscored = s.get_unscored_items(within_days=7)
    urls = {it.url for it in unscored}
    assert urls == {"https://recent-discovery"}
    s.close()


def test_get_unscored_items_excludes_already_scored(tmp_path: Path):
    s = Storage(tmp_path / "t.db")
    s.init()
    s.record_items([_item("https://a"), _item("https://b")])
    s.save_score("https://a", Score(score=5, tags=[], model="m", cost_usd=0.0))
    unscored = s.get_unscored_items(within_days=7)
    assert {it.url for it in unscored} == {"https://b"}
    s.close()


def test_save_score_for_unknown_url_raises_fk_violation(tmp_path: Path):
    import sqlite3
    s = Storage(tmp_path / "t.db")
    s.init()
    with pytest.raises(sqlite3.IntegrityError):
        s.save_score("https://ghost", Score(score=5, tags=[], model="m", cost_usd=0.0))
    s.close()


def test_init_drops_old_seen_urls_table(tmp_path: Path):
    db = tmp_path / "t.db"
    import sqlite3
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE seen_urls (url TEXT PRIMARY KEY, title TEXT, source TEXT,"
        " published_at TEXT, first_seen TEXT);"
        " INSERT INTO seen_urls VALUES ('https://legacy','t','s','2026-01-01','2026-01-01');"
    )
    conn.commit()
    conn.close()

    s = Storage(db)
    s.init()
    assert s.seen_urls(["https://legacy"]) == set()
    s.close()
