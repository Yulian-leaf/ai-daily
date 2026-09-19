import logging
from datetime import datetime, timezone, timedelta

from src.config import Config
from src.llm import LLMError, check_api_keys, complete_json
from src.models import Analysis, WeeklyReport
from src.prompts import load_prompt, render
from src.storage import Storage


logger = logging.getLogger(__name__)

# 窗口内条目不足该数量时跳过生成（避免产出空周报）。
_MIN_ITEMS = 3
_WINDOW_DAYS = {"weekly": 7, "biweekly": 14}


def _one_line(text: str | None, limit: int = 80) -> str:
    """Collapse a long summary into a short one-liner to keep the prompt compact."""
    text = (text or "").strip().replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _render_weekly_prompt(
    items: list[Analysis], week_start: str, week_end: str,
) -> str:
    lines = []
    for a in items:
        field = a.score.field or "(未归类)"
        summary = _one_line(a.summary.innovation) if a.summary else ""
        lines.append(f"- [{field}] {a.title} —— {summary}（{a.url}）")
    body = "\n".join(lines) if lines else "（本期无条目）"
    range_label = f"{week_start[5:]} ~ {week_end[5:]}"  # MM-DD ~ MM-DD
    return render(load_prompt("weekly"), {"items": body, "range": range_label})


async def _generate_weekly(
    items: list[Analysis], cfg: Config, week_start: str, week_end: str,
) -> WeeklyReport:
    data, _cost = await complete_json(
        model=cfg.models.summarizer,
        prompt=_render_weekly_prompt(items, week_start, week_end),
        max_tokens=4000,
    )
    required = ("title", "overview", "highlights")
    missing = [k for k in required if k not in data]
    if missing:
        raise LLMError(f"weekly missing fields: {missing}")
    highlights = data.get("highlights") or []
    if not isinstance(highlights, list):
        raise LLMError("weekly highlights must be a list")
    return WeeklyReport(
        title=str(data["title"]),
        overview=str(data.get("overview", "")),
        highlights=[dict(h) if isinstance(h, dict) else {} for h in highlights],
        trend=str(data.get("trend", "")),
        outlook=str(data.get("outlook", "")),
    )


async def run_weekly(
    storage: Storage,
    cfg: Config,
    *,
    period: str = "weekly",
) -> dict:
    """Generate a weekly / biweekly report from surfaced summaries.

    Input = already-surfaced daily items (title + field + one-liner + url),
    no re-fetch / re-score. If the window has too few items, skip generation.
    """
    if cfg.models is None:
        raise RuntimeError(
            "preferences.yaml must define `models.scorer` and `models.summarizer`"
            " to run weekly"
        )
    check_api_keys(cfg.models)

    window_days = _WINDOW_DAYS.get(period, 7)
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=window_days)
    week_start = start.date().isoformat()
    week_end = now.date().isoformat()

    items = storage.get_surfaced_since(
        start.isoformat(), min_score=cfg.score_threshold,
    )
    if len(items) < _MIN_ITEMS:
        logger.info(
            "weekly: only %d surfaced items in %s window, skipping",
            len(items), period,
        )
        return {"skipped": True, "items": len(items)}

    report = await _generate_weekly(items, cfg, week_start, week_end)
    report.period = period
    report.week_start = week_start
    report.week_end = week_end
    report.generated_at = now.isoformat()
    storage.save_weekly_report(report)

    logger.info(
        "weekly done: period=%s window=%s..%s items=%d highlights=%d",
        period, week_start, week_end, len(items), len(report.highlights),
    )
    return {
        "skipped": False,
        "items": len(items),
        "highlights": len(report.highlights),
        "week_start": week_start,
        "week_end": week_end,
    }
