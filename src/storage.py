import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterable

from src.models import Item, Score, Summary, Analysis, WeeklyReport


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
    surfaced_at TEXT,
    summarized_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_summaries_score ON summaries(score);
-- idx_summaries_surfaced_at is created by _migrate_add_surfaced_at after the
-- column is guaranteed to exist on both fresh and pre-feature DBs.

CREATE TABLE IF NOT EXISTS weekly_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period TEXT NOT NULL DEFAULT 'weekly',
    week_start TEXT NOT NULL,
    week_end TEXT NOT NULL,
    title TEXT NOT NULL,
    overview TEXT,
    highlights_json TEXT NOT NULL DEFAULT '[]',
    trend TEXT,
    outlook TEXT,
    generated_at TEXT NOT NULL,
    UNIQUE(period, week_start)
);
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
        # Daily-quota migration: add summaries.summarized_at if missing.
        self._migrate_add_summarized_at()
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

    def _migrate_add_summarized_at(self) -> None:
        assert self._conn is not None
        cols = self._conn.execute("PRAGMA table_info(summaries)").fetchall()
        col_names = {c[1] for c in cols}
        if "summarized_at" not in col_names:
            # 已有摘要的行回填一个过去的时刻（用上墙时间/打分时间近似），
            # 使其不计入今天的每日额度。
            self._conn.executescript(
                "ALTER TABLE summaries ADD COLUMN summarized_at TEXT;"
                "UPDATE summaries SET summarized_at = COALESCE(surfaced_at, created_at)"
                " WHERE innovation IS NOT NULL;"
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
            "  summarizer_model=?, summarizer_cost_usd=?, summarized_at=?"
            " WHERE url=?",
            (
                summary.innovation, summary.approach, summary.metrics,
                summary.links, summary.why_relevant,
                summary.model, summary.cost_usd,
                datetime.now(timezone.utc).isoformat(),
                url,
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
        """Items with summary + score >= threshold that were surfaced today
        (or not yet surfaced). Same-day re-render keeps them in 'today'; they
        move to archive only when the date rolls over."""
        conn = self._conn_or_die()
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).isoformat()
        rows = conn.execute(
            "SELECT i.url, i.title, i.source, i.content, i.published_at,"
            "       s.score, s.tags_json, s.field, s.scorer_model, s.scorer_cost_usd,"
            "       s.innovation, s.approach, s.metrics, s.links, s.why_relevant,"
            "       s.summarizer_model, s.summarizer_cost_usd, s.surfaced_at"
            " FROM items i JOIN summaries s ON s.url = i.url"
            " WHERE s.score >= ? AND s.innovation IS NOT NULL"
            "   AND (s.surfaced_at IS NULL OR s.surfaced_at >= ?)"
            " ORDER BY s.score DESC, i.published_at DESC",
            (min_score, today_start),
        ).fetchall()
        return [self._row_to_analysis(r) for r in rows]

    def get_archive_summaries(
        self, min_score: int, within_days: int
    ) -> list[Analysis]:
        """Items with summary + score >= threshold that were surfaced on a
        previous day and are still within the archive window."""
        conn = self._conn_or_die()
        now = datetime.now(timezone.utc)
        today_start = now.replace(
            hour=0, minute=0, second=0, microsecond=0
        ).isoformat()
        cutoff = (now - timedelta(days=within_days)).isoformat()
        rows = conn.execute(
            "SELECT i.url, i.title, i.source, i.content, i.published_at,"
            "       s.score, s.tags_json, s.field, s.scorer_model, s.scorer_cost_usd,"
            "       s.innovation, s.approach, s.metrics, s.links, s.why_relevant,"
            "       s.summarizer_model, s.summarizer_cost_usd, s.surfaced_at"
            " FROM items i JOIN summaries s ON s.url = i.url"
            " WHERE s.score >= ? AND s.innovation IS NOT NULL"
            "   AND s.surfaced_at IS NOT NULL AND s.surfaced_at < ?"
            "   AND s.surfaced_at >= ?"
            " ORDER BY s.surfaced_at DESC, s.score DESC",
            (min_score, today_start, cutoff),
        ).fetchall()
        return [self._row_to_analysis(r) for r in rows]

    def get_scored_unsummarized(
        self, min_score: int, within_days: int
    ) -> list[tuple[Item, Score]]:
        """Items already scored >= threshold but never summarized, still
        recent. Returns (Item, Score) pairs ready for summarization."""
        conn = self._conn_or_die()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=within_days)).isoformat()
        rows = conn.execute(
            "SELECT i.*, s.score, s.tags_json, s.field,"
            "       s.scorer_model, s.scorer_cost_usd"
            " FROM items i JOIN summaries s ON s.url = i.url"
            " WHERE s.score >= ? AND s.innovation IS NULL AND s.created_at >= ?"
            " ORDER BY s.score DESC, i.published_at DESC",
            (min_score, cutoff),
        ).fetchall()
        result: list[tuple[Item, Score]] = []
        for r in rows:
            item = self._row_to_item(r)
            field = r["field"] if "field" in r.keys() and r["field"] else ""
            score = Score(
                score=r["score"],
                tags=json.loads(r["tags_json"]),
                model=r["scorer_model"],
                cost_usd=r["scorer_cost_usd"],
                field=field,
            )
            result.append((item, score))
        return result

    def purge_stale_unsummarized(self, older_than_days: int) -> int:
        """Delete score-only rows (never summarized) older than the window,
        so stale candidates never surface long after being scored."""
        conn = self._conn_or_die()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat()
        cur = conn.execute(
            "DELETE FROM summaries WHERE innovation IS NULL AND created_at < ?",
            (cutoff,),
        )
        conn.commit()
        return cur.rowcount

    def count_summarized_since(self, cutoff: str) -> int:
        """Number of summaries written since cutoff (ISO timestamp). Used to
        enforce the per-day top_n quota regardless of how many times
        `summarize` runs in a single day."""
        conn = self._conn_or_die()
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM summaries WHERE summarized_at >= ?",
            (cutoff,),
        ).fetchone()
        return int(row["n"])

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

    # --- weekly reports (Phase 3) ---

    def save_weekly_report(self, report: WeeklyReport) -> None:
        """Upsert a weekly report keyed by (period, week_start). Re-running
        in the same period overwrites instead of duplicating."""
        conn = self._conn_or_die()
        conn.execute(
            "INSERT INTO weekly_reports"
            " (period, week_start, week_end, title, overview, highlights_json,"
            "  trend, outlook, generated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(period, week_start) DO UPDATE SET"
            "   week_end=excluded.week_end, title=excluded.title,"
            "   overview=excluded.overview, highlights_json=excluded.highlights_json,"
            "   trend=excluded.trend, outlook=excluded.outlook,"
            "   generated_at=excluded.generated_at",
            (
                report.period, report.week_start, report.week_end, report.title,
                report.overview, json.dumps(report.highlights, ensure_ascii=False),
                report.trend, report.outlook, report.generated_at,
            ),
        )
        conn.commit()

    def get_weekly_reports(self, period: str = "weekly") -> list[WeeklyReport]:
        conn = self._conn_or_die()
        rows = conn.execute(
            "SELECT * FROM weekly_reports WHERE period = ? ORDER BY week_start DESC",
            (period,),
        ).fetchall()
        return [self._row_to_weekly_report(r) for r in rows]

    def get_latest_weekly(self, period: str = "weekly") -> WeeklyReport | None:
        reports = self.get_weekly_reports(period)
        return reports[0] if reports else None

    def get_surfaced_since(self, cutoff: str, min_score: int) -> list[Analysis]:
        """Surfaced summaries since cutoff, used as weekly-report input."""
        conn = self._conn_or_die()
        rows = conn.execute(
            "SELECT i.url, i.title, i.source, i.content, i.published_at,"
            "       s.score, s.tags_json, s.field, s.scorer_model, s.scorer_cost_usd,"
            "       s.innovation, s.approach, s.metrics, s.links, s.why_relevant,"
            "       s.summarizer_model, s.summarizer_cost_usd, s.surfaced_at"
            " FROM items i JOIN summaries s ON s.url = i.url"
            " WHERE s.innovation IS NOT NULL AND s.surfaced_at IS NOT NULL"
            "   AND s.surfaced_at >= ? AND s.score >= ?"
            " ORDER BY s.score DESC, i.published_at DESC",
            (cutoff, min_score),
        ).fetchall()
        return [self._row_to_analysis(r) for r in rows]

    def get_stats(self) -> dict:
        """Site-wide counts for the poster footer: items / summarized /
        surfaced totals plus per-field distribution."""
        conn = self._conn_or_die()
        items = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        summarized = conn.execute(
            "SELECT COUNT(*) FROM summaries"
            " WHERE innovation IS NOT NULL AND innovation != ''"
        ).fetchone()[0]
        surfaced = conn.execute(
            "SELECT COUNT(*) FROM summaries WHERE surfaced_at IS NOT NULL"
        ).fetchone()[0]
        by_field: dict[str, int] = {}
        for r in conn.execute(
            "SELECT field, COUNT(*) AS n FROM summaries"
            " WHERE field IS NOT NULL AND field != '' GROUP BY field"
        ).fetchall():
            by_field[r["field"]] = r["n"]
        return {
            "items": items,
            "summarized": summarized,
            "surfaced": surfaced,
            "by_field": by_field,
        }

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

    @staticmethod
    def _row_to_weekly_report(row: sqlite3.Row) -> WeeklyReport:
        return WeeklyReport(
            period=row["period"],
            week_start=row["week_start"],
            week_end=row["week_end"],
            title=row["title"],
            overview=row["overview"] or "",
            highlights=json.loads(row["highlights_json"] or "[]"),
            trend=row["trend"] or "",
            outlook=row["outlook"] or "",
            generated_at=row["generated_at"],
        )
