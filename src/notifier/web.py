from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.notifier.labels import label_for
from src.storage import Storage

# 北京时间（UTC+8，固定偏移；中国无夏令时）。
_BEIJING_TZ = timezone(timedelta(hours=8))


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

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    html = template.render(
        today=today,
        archive_groups=archive_groups,
        archive_total=len(archive),
        within_days=within_days,
        generated_at=datetime.now(_BEIJING_TZ).strftime(
            "%Y-%m-%d %H:%M (北京时间 UTC+8)"
        ),
        subfields=subfields or [],
        field_labels={s["key"]: s["label"] for s in (subfields or [])},
    )

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


_PERIOD_FILE = {"weekly": "weekly.html", "biweekly": "biweekly.html"}
_PERIOD_LABEL = {"weekly": "周报", "biweekly": "双周报告"}
_FIELD_ICONS = {
    "protein": "🧬", "drug": "💊", "molsim": "⚛️", "materials": "🧪",
    "climate": "🌍", "ai4math": "📐", "scifm": "🧠", "bioinfo": "🧫",
}


def render_weekly(
    storage: Storage,
    *,
    period: str = "weekly",
    subfields: list[dict[str, str]] | None = None,
    output_dir: Path = Path("site"),
    templates_dir: Path = Path("templates"),
) -> dict:
    """Render the weekly digest page (latest report + archive).

    weekly -> weekly.html, biweekly -> biweekly.html (two separate pages)."""
    reports = storage.get_weekly_reports(period=period)
    latest = reports[0] if reports else None
    archive = reports[1:] if reports else []

    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["label"] = label_for
    template = env.get_template("weekly.html.j2")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    period_label = _PERIOD_LABEL.get(period, "周报")
    other_period = "biweekly" if period == "weekly" else "weekly"

    html = template.render(
        latest=latest,
        archive=archive,
        period=period,
        period_label=period_label,
        other_label=_PERIOD_LABEL[other_period],
        other_link=_PERIOD_FILE[other_period],
        subfields=subfields or [],
        field_labels={s["key"]: s["label"] for s in (subfields or [])},
        generated_at=datetime.now(_BEIJING_TZ).strftime(
            "%Y-%m-%d %H:%M (北京时间 UTC+8)"
        ),
    )

    output_path = output_dir / _PERIOD_FILE.get(period, "weekly.html")
    output_path.write_text(html, encoding="utf-8")
    return {"output": str(output_path), "reports": len(reports)}


def _clip(text: str | None, limit: int = 80) -> str:
    """Collapse a long summary into a short one-liner for the poster."""
    text = (text or "").strip().replace("\n", " ")
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _select_poster_highlights(
    items: list, subfields_keys: list[str],
) -> list[dict]:
    """Pick poster highlights deterministically: one highest-score item per
    subfield, then top-2 by score from the remaining pool (<=10 total)."""
    by_field: dict[str, list] = defaultdict(list)
    for a in items:
        by_field[a.score.field or ""].append(a)

    picked: list = []
    used: set[str] = set()
    for key in subfields_keys:
        if key in by_field:
            best = max(by_field[key], key=lambda a: a.score.score)
            picked.append(best)
            used.add(best.url)

    rest = [a for a in items if a.url not in used]
    rest.sort(key=lambda a: a.score.score, reverse=True)
    picked.extend(rest[:2])
    picked.sort(key=lambda a: a.score.score, reverse=True)

    return [
        {
            "field": a.score.field or "",
            "title": a.title,
            "url": a.url,
            "summary": _clip(a.summary.innovation) if a.summary else "",
            "score": f"{a.score.score:.1f}",
        }
        for a in picked
    ]


def render_poster(
    storage: Storage,
    *,
    period: str = "weekly",
    min_score: int = 6,
    subfields: list[dict[str, str]] | None = None,
    output_dir: Path = Path("site"),
    templates_dir: Path = Path("templates"),
) -> dict:
    """Render the latest report as a shareable, fixed-size poster (poster.html)."""
    latest = storage.get_latest_weekly(period)
    stats = storage.get_stats()

    poster_highlights: list[dict] = []
    if latest:
        items = storage.get_surfaced_since(latest.week_start, min_score=min_score)
        poster_highlights = _select_poster_highlights(
            items, [s["key"] for s in (subfields or [])],
        )

    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["label"] = label_for
    template = env.get_template("poster.html.j2")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    html = template.render(
        report=latest,
        poster_highlights=poster_highlights,
        period_label=_PERIOD_LABEL.get(period, "周报"),
        stats=stats,
        subfields=subfields or [],
        field_labels={s["key"]: s["label"] for s in (subfields or [])},
        field_icons=_FIELD_ICONS,
        field_max=max(
            (stats["by_field"].get(s["key"], 0) for s in (subfields or [])),
            default=1,
        ),
        generated_at=datetime.now(_BEIJING_TZ).strftime(
            "%Y-%m-%d %H:%M (北京时间 UTC+8)"
        ),
    )

    output_path = output_dir / "poster.html"
    output_path.write_text(html, encoding="utf-8")
    return {
        "output": str(output_path),
        "report": latest.title if latest else None,
    }
