import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterable

from src.models import Item, Score, Summary, Analysis


_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    url TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT NOT NULL,
    published_at TEXT NOT NULL,
    raw_json TEXT NOT NULL DEFAULT '{}',
    first_seen TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items_first_seen ON items(first_seen);
CREATE INDEX IF NOT EXISTS idx_items_source ON items(source);

CREATE TABLE IF NOT EXISTS summaries (
    url TEXT PRIMARY KEY REFERENCES items(url),
    score INTEGER NOT NULL,
    tags_json TEXT NOT NULL,
    field TEXT NOT NULL DEFAULT '',
    scorer_model TEXT NOT NULL,
    scorer_cost_usd REAL NOT NULL DEFAULT 0,
    innovation TEXT,
    approach TEXT,
    metrics TEXT,
    links TEXT,
    why_relevant TEXT,
    summarizer_model TEXT,
    summarizer_cost_usd REAL,
    created_at TEXT NOT NULL,
    surfaced_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_summaries_score ON summaries(score);
-- idx_summaries_surfaced_at is created by _migrate_add_surfaced_at after the
-- column is guaranteed to exist on both fresh and pre-feature DBs.
"""


class Storage:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None

    def init(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.row_factory = sqlite3.Row
        # If legacy Stage-1-only table is present and new `items` is not, drop it.
        # We don't migrate; data will be re-fetched. Documented in plan.
        legacy = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='seen_urls'"
        ).fetchone()
        has_items = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='items'"
        ).fetchone()
        if legacy and not has_items:
            self._conn.executescript("DROP TABLE seen_urls;")
        self._conn.executescript(_SCHEMA)
        # Stage 3-dedup migration: if summaries.surfaced_at is missing on a
        # pre-existing table, add it and backfill from created_at so existing
        # rows are treated as already archived (not "new today").
        self._migrate_add_surfaced_at()
        # AI4S migration: add summaries.field if missing (older DBs).
        self._migrate_add_field()
        self._conn.commit()

    def _migrate_add_surfaced_at(self) -> None:
        assert self._conn is not None
        cols = self._conn.execute("PRAGMA table_info(summaries)").fetchall()
        col_names = {c[1] for c in cols}
        if "surfaced_at" not in col_names:
            self._conn.executescript(
                "ALTER TABLE summaries ADD COLUMN surfaced_at TEXT;"
                "UPDATE summaries SET surfaced_at = created_at;"
            )
        # Always ensure the index exists (handles both fresh and migrated DBs).
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_summaries_surfaced_at"
            " ON summaries(surfaced_at)"
        )

    def _migrate_add_field(self) -> None:
        assert self._conn is not None
        cols = self._conn.execute("PRAGMA table_info(summaries)").fetchall()
        col_names = {c[1] for c in cols}
        if "field" not in col_names:
            self._conn.execute(
                "ALTER TABLE summaries ADD COLUMN field TEXT NOT NULL DEFAULT ''"
            )

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _conn_or_die(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Storage.init() not called")
        return self._conn

    # --- items (Stage 1 + 2) ---

    def seen_urls(self, urls: Iterable[str]) -> set[str]:
        urls = list(urls)
        if not urls:
            return set()
        conn = self._conn_or_die()
        placeholders = ",".join("?" * len(urls))
        rows = conn.execute(
            f"SELECT url FROM items WHERE url IN ({placeholders})", urls
        ).fetchall()
        return {r["url"] for r in rows}

    def record_items(self, items: Iterable[Item]) -> None:
        conn = self._conn_or_die()
        now = datetime.now(timezone.utc).isoformat()
        rows = [
            (
                it.url, it.title, it.content, it.source,
                it.published_at.isoformat(),
                json.dumps(it.raw, default=str),
                now,
            )
            for it in items
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO items"
            " (url, title, content, source, published_at, raw_json, first_seen)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()

    def fetch_item_row(self, url: str) -> dict:
        conn = self._conn_or_die()
        row = conn.execute(
            "SELECT * FROM items WHERE url = ?", (url,)
        ).fetchone()
        return dict(row) if row else {}

    def get_items_by_urls(self, urls: list[str]) -> list[Item]:
        if not urls:
            return []
        conn = self._conn_or_die()
        placeholders = ",".join("?" * len(urls))
        rows = conn.execute(
            f"SELECT * FROM items WHERE url IN ({placeholders})", urls
        ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def get_unscored_items(self, within_days: int) -> list[Item]:
        conn = self._conn_or_die()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=within_days)).isoformat()
        rows = conn.execute(
            "SELECT i.* FROM items i LEFT JOIN summaries s ON s.url = i.url"
            " WHERE s.url IS NULL AND i.first_seen >= ?"
            " ORDER BY i.first_seen DESC",
            (cutoff,),
        ).fetchall()
        return [self._row_to_item(r) for r in rows]

    # --- summaries (Stage 2) ---

    def save_score(self, url: str, score: Score) -> None:
        conn = self._conn_or_die()
        conn.execute(
            "INSERT INTO summaries"
            " (url, score, tags_json, field, scorer_model, scorer_cost_usd, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(url) DO UPDATE SET"
            "   score=excluded.score, tags_json=excluded.tags_json,"
            "   field=excluded.field,"
            "   scorer_model=excluded.scorer_model,"
            "   scorer_cost_usd=excluded.scorer_cost_usd",
            (
                url, score.score, json.dumps(score.tags), score.field,
                score.model, score.cost_usd,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()

    def save_summary(self, url: str, summary: Summary) -> None:
        conn = self._conn_or_die()
        cur = conn.execute(
            "UPDATE summaries SET"
            "  innovation=?, approach=?, metrics=?, links=?, why_relevant=?,"
            "  summarizer_model=?, summarizer_cost_usd=?"
            " WHERE url=?",
            (
                summary.innovation, summary.approach, summary.metrics,
                summary.links, summary.why_relevant,
                summary.model, summary.cost_usd, url,
            ),
        )
        if cur.rowcount == 0:
            raise ValueError(f"save_summary: no score row exists for {url}; call save_score first")
        conn.commit()

    def get_top_summaries(
        self, min_score: int, limit: int, within_days: int
    ) -> list[Analysis]:
        conn = self._conn_or_die()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=within_days)).isoformat()
        rows = conn.execute(
            "SELECT i.url, i.title, i.source, i.content, i.published_at,"
            "       s.score, s.tags_json, s.field, s.scorer_model, s.scorer_cost_usd,"
            "       s.innovation, s.approach, s.metrics, s.links, s.why_relevant,"
            "       s.summarizer_model, s.summarizer_cost_usd, s.surfaced_at"
            " FROM items i JOIN summaries s ON s.url = i.url"
            " WHERE s.score >= ? AND i.first_seen >= ?"
            " ORDER BY s.score DESC, i.published_at DESC"
            " LIMIT ?",
            (min_score, cutoff, limit),
        ).fetchall()
        return [self._row_to_analysis(r) for r in rows]

    def get_today_summaries(self, min_score: int) -> list[Analysis]:
        """Items with summary + score >= threshold that have NOT been surfaced yet."""
        conn = self._conn_or_die()
        rows = conn.execute(
            "SELECT i.url, i.title, i.source, i.content, i.published_at,"
            "       s.score, s.tags_json, s.field, s.scorer_model, s.scorer_cost_usd,"
            "       s.innovation, s.approach, s.metrics, s.links, s.why_relevant,"
            "       s.summarizer_model, s.summarizer_cost_usd, s.surfaced_at"
            " FROM items i JOIN summaries s ON s.url = i.url"
            " WHERE s.score >= ? AND s.innovation IS NOT NULL"
            "   AND s.surfaced_at IS NULL"
            " ORDER BY s.score DESC, i.published_at DESC",
            (min_score,),
        ).fetchall()
        return [self._row_to_analysis(r) for r in rows]

    def get_archive_summaries(
        self, min_score: int, within_days: int
    ) -> list[Analysis]:
        """Items with summary + score >= threshold that have been surfaced
        already and are still within the archive window (filtered by surfaced_at)."""
        conn = self._conn_or_die()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=within_days)).isoformat()
        rows = conn.execute(
            "SELECT i.url, i.title, i.source, i.content, i.published_at,"
            "       s.score, s.tags_json, s.field, s.scorer_model, s.scorer_cost_usd,"
            "       s.innovation, s.approach, s.metrics, s.links, s.why_relevant,"
            "       s.summarizer_model, s.summarizer_cost_usd, s.surfaced_at"
            " FROM items i JOIN summaries s ON s.url = i.url"
            " WHERE s.score >= ? AND s.innovation IS NOT NULL"
            "   AND s.surfaced_at IS NOT NULL AND s.surfaced_at >= ?"
            " ORDER BY s.surfaced_at DESC, s.score DESC",
            (min_score, cutoff),
        ).fetchall()
        return [self._row_to_analysis(r) for r in rows]

    def mark_surfaced(self, urls: list[str]) -> int:
        """Mark a batch of summaries as surfaced (NULL -> now). No-op for
        already-surfaced rows. Returns the number of rows actually updated."""
        if not urls:
            return 0
        conn = self._conn_or_die()
        now = datetime.now(timezone.utc).isoformat()
        placeholders = ",".join("?" * len(urls))
        cur = conn.execute(
            f"UPDATE summaries SET surfaced_at = ?"
            f" WHERE url IN ({placeholders}) AND surfaced_at IS NULL",
            [now, *urls],
        )
        conn.commit()
        return cur.rowcount

    # --- helpers ---

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> Item:
        return Item(
            url=row["url"],
            title=row["title"],
            content=row["content"],
            source=row["source"],
            published_at=datetime.fromisoformat(row["published_at"]),
            raw=json.loads(row["raw_json"]) if row["raw_json"] else {},
        )

    @staticmethod
    def _row_to_analysis(row: sqlite3.Row) -> Analysis:
        field = row["field"] if "field" in row.keys() and row["field"] else ""
        score = Score(
            score=row["score"],
            tags=json.loads(row["tags_json"]),
            model=row["scorer_model"],
            cost_usd=row["scorer_cost_usd"],
            field=field,
        )
        summary = None
        if row["innovation"] is not None:
            summary = Summary(
                innovation=row["innovation"],
                approach=row["approach"],
                metrics=row["metrics"],
                links=row["links"],
                why_relevant=row["why_relevant"],
                model=row["summarizer_model"] or "",
                cost_usd=row["summarizer_cost_usd"] or 0.0,
            )
        # surfaced_at is present in all three SELECTs that hit this helper.
        # Use sqlite3.Row.keys() to stay safe if a future SELECT drops it.
        surfaced_at = None
        if "surfaced_at" in row.keys() and row["surfaced_at"]:
            surfaced_at = datetime.fromisoformat(row["surfaced_at"])
        return Analysis(
            url=row["url"],
            title=row["title"],
            source=row["source"],
            content=row["content"],
            published_at=datetime.fromisoformat(row["published_at"]),
            score=score,
            summary=summary,
            surfaced_at=surfaced_at,
        )
