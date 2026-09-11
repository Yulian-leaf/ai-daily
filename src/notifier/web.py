from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.notifier.labels import label_for
from src.storage import Storage


def _group_archive_by_date(archive: list) -> list[tuple[str, list]]:
    """Group archive Analysis items by date(surfaced_at), most recent first.

    Returns a list of (date_str "YYYY-MM-DD", [analyses]) tuples. Items
    inside each group keep their score-desc order.
    """
    by_date: dict[str, list] = defaultdict(list)
    for a in archive:
        if a.surfaced_at is None:
            # Shouldn't happen — archive is defined as surfaced_at NOT NULL.
            continue
        by_date[a.surfaced_at.date().isoformat()].append(a)
    # Sort each bucket by score desc (storage already does, but be defensive).
    for items in by_date.values():
        items.sort(key=lambda x: (-x.score.score, x.url))
    # Sort dates descending.
    return sorted(by_date.items(), key=lambda kv: kv[0], reverse=True)


def render_site(
    storage: Storage,
    *,
    min_score: int,
    within_days: int,
    top_n: int,
    output_dir: Path = Path("site"),
    templates_dir: Path = Path("templates"),
    subfields: list[dict[str, str]] | None = None,
) -> dict:
    """Render the daily digest page (today + archive grouped by date) to a
    single self-contained HTML file. After write, mark today's batch surfaced."""
    today = storage.get_today_summaries(min_score=min_score)
    archive = storage.get_archive_summaries(
        min_score=min_score, within_days=within_days,
    )
    archive_groups = _group_archive_by_date(archive)

    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["label"] = label_for
    template = env.get_template("index.html.j2")
    html = template.render(
        today=today,
        archive_groups=archive_groups,
        archive_total=len(archive),
        within_days=within_days,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        subfields=subfields or [],
        field_labels={s["key"]: s["label"] for s in (subfields or [])},
    )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "index.html"
    output_path.write_text(html, encoding="utf-8")

    marked = storage.mark_surfaced([a.url for a in today])

    return {
        "today": len(today),
        "archive": len(archive),
        "archive_dates": len(archive_groups),
        "marked_surfaced": marked,
        "output": str(output_path),
        # Back-compat key kept for older tests / callers.
        "rendered": len(today) + len(archive),
    }
