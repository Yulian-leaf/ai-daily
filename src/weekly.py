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
_PROMPT_NAMES = {"weekly": "weekly", "biweekly": "biweekly"}
# 周报按北京时间自然周对齐（周一到周日）。
_BEIJING_TZ = timezone(timedelta(hours=8))


def _one_line(text: str | None, limit: int = 80) -> str:
    """Collapse a long summary into a short one-liner to keep the prompt compact."""
    text = (text or "").strip().replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _render_weekly_prompt(
    items: list[Analysis], week_start: str, week_end: str, period: str = "weekly",
) -> str:
    lines = []
    for a in items:
        field = a.score.field or "(未归类)"
        summary = _one_line(a.summary.innovation) if a.summary else ""
        lines.append(f"- [{field}] {a.title} —— {summary}（{a.url}）")
    body = "\n".join(lines) if lines else "（本期无条目）"
    range_label = f"{week_start[5:]} ~ {week_end[5:]}"  # MM-DD ~ MM-DD
    prompt_name = _PROMPT_NAMES.get(period, "weekly")
    return render(load_prompt(prompt_name), {"items": body, "range": range_label})


async def _generate_weekly(
    items: list[Analysis], cfg: Config, week_start: str, week_end: str,
    period: str = "weekly",
) -> WeeklyReport:
    data, _cost = await complete_json(
        model=cfg.models.summarizer,
        prompt=_render_weekly_prompt(items, week_start, week_end, period),
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
        slogan=str(data.get("slogan", "")),
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

    # 按北京时间自然周对齐：week_start = 本周一，week_end = 本周日；
    # 双周报告再往前推一周（覆盖两个自然周）。
    bj_now = datetime.now(_BEIJING_TZ)
    bj_monday = bj_now.replace(
        hour=0, minute=0, second=0, microsecond=0,
    ) - timedelta(days=bj_now.weekday())
    weeks = 1 if period == "weekly" else 2
    start_dt = bj_monday - timedelta(days=7 * (weeks - 1))
    end_dt = bj_monday + timedelta(days=6)

    now = datetime.now(timezone.utc)
    week_start = start_dt.date().isoformat()
    week_end = end_dt.date().isoformat()

    items = storage.get_surfaced_since(
        start_dt.astimezone(timezone.utc).isoformat(),
        min_score=cfg.score_threshold,
    )
    if len(items) < _MIN_ITEMS:
        logger.info(
            "weekly: only %d surfaced items in %s window, skipping",
            len(items), period,
        )
        return {"skipped": True, "items": len(items)}

    report = await _generate_weekly(items, cfg, week_start, week_end, period)
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
