import asyncio
import logging
from datetime import datetime, timezone

from src.config import Config
from src.llm import LLMError, check_api_keys, complete_json
from src.models import Item, Score, Summary
from src.prompts import load_prompt, render
from src.storage import Storage


logger = logging.getLogger(__name__)

_SCORE_CONTENT_CHARS = 800
_SUMMARY_CONTENT_CHARS = 4000


def _render_score_prompt(item: Item, cfg: Config) -> str:
    fields = ", ".join(s["key"] for s in cfg.subfields) or "(none)"
    return render(load_prompt("score"), {
        "keywords": ", ".join(cfg.keywords) or "(none)",
        "fields": fields,
        "source": item.source,
        "date": item.published_at.date().isoformat(),
        "title": item.title,
        "content": (item.content or "")[:_SCORE_CONTENT_CHARS],
    })


def _render_summary_prompt(item: Item, cfg: Config) -> str:
    return render(load_prompt("summarize"), {
        "keywords": ", ".join(cfg.keywords) or "(none)",
        "source": item.source,
        "date": item.published_at.date().isoformat(),
        "title": item.title,
        "content": (item.content or "")[:_SUMMARY_CONTENT_CHARS],
    })


async def _score_one(item: Item, cfg: Config) -> tuple[Item, Score | None, Exception | None]:
    try:
        data, cost = await complete_json(
            model=cfg.models.scorer,
            prompt=_render_score_prompt(item, cfg),
            max_tokens=200,
        )
        score = int(data.get("score", -1))
        if not 0 <= score <= 10:
            raise LLMError(f"score out of range: {score}")
        tags = data.get("tags", [])
        if not isinstance(tags, list):
            raise LLMError(f"tags must be a list, got {type(tags).__name__}")
        # field 必须是配置好的子领域 key；越界就回退为 ""（未归类）。
        valid_fields = {s["key"] for s in cfg.subfields}
        field = data.get("field", "")
        if not isinstance(field, str) or field not in valid_fields:
            logger.warning("score field %r not in subfields; falling back to ''", field)
            field = ""
        return item, Score(
            score=score, tags=[str(t) for t in tags], field=field,
            model=cfg.models.scorer, cost_usd=cost,
        ), None
    except Exception as e:
        logger.warning("score failed for %s: %s", item.url, e)
        return item, None, e


async def _summarize_one(item: Item, cfg: Config) -> tuple[Item, Summary | None, Exception | None]:
    try:
        data, cost = await complete_json(
            model=cfg.models.summarizer,
            prompt=_render_summary_prompt(item, cfg),
            max_tokens=1500,
        )
        required = ("innovation", "approach", "metrics", "links", "why_relevant")
        missing = [k for k in required if k not in data]
        if missing:
            raise LLMError(f"summary missing fields: {missing}")
        return item, Summary(
            innovation=str(data["innovation"]),
            approach=str(data["approach"]),
            metrics=str(data["metrics"]),
            links=str(data["links"]),
            why_relevant=str(data["why_relevant"]),
            model=cfg.models.summarizer, cost_usd=cost,
        ), None
    except Exception as e:
        logger.warning("summary failed for %s: %s", item.url, e)
        return item, None, e


async def run_summarize(storage: Storage, cfg: Config) -> dict:
    """Score unscored items, then summarize the top_n that passed threshold.

    After scoring, every item with score >= threshold and no summary yet —
    whether scored in this run or a previous one — competes for top_n in a
    single pool. Stale score-only rows older than the window are purged first
    so old candidates don't surface long after being scored.

    A per-day quota caps the number of NEW summaries to top_n, so running
    this more than once in a single day never produces more than top_n items."""
    if cfg.models is None:
        raise RuntimeError(
            "preferences.yaml must define `models.scorer` and `models.summarizer`"
            " to run summarize"
        )
    check_api_keys(cfg.models)

    metrics = {
        "scored": 0, "passed_threshold": 0, "summarized": 0,
        "score_errors": 0, "summary_errors": 0,
        "scorer_cost_usd": 0.0, "summarizer_cost_usd": 0.0,
        "backlog": 0, "purged": 0, "already_today": 0,
    }

    # 清理陈旧的无摘要分数行（避免旧候选久留后突然被总结上墙）
    metrics["purged"] = storage.purge_stale_unsummarized(older_than_days=7)

    items = storage.get_unscored_items(within_days=7)
    logger.info("found %d unscored items in the last 7 days", len(items))

    score_results = await asyncio.gather(*(_score_one(it, cfg) for it in items))
    for item, score, err in score_results:
        if err is not None or score is None:
            metrics["score_errors"] += 1
            continue
        metrics["scored"] += 1
        metrics["scorer_cost_usd"] += score.cost_usd
        storage.save_score(item.url, score)
        if score.score >= cfg.score_threshold:
            metrics["passed_threshold"] += 1

    # 打分之后一条 SQL 拿走全部候选：本轮的 + 上一轮遗留的（都有分、没摘要）。
    # DB 里每个 url 只有一行，天然去重，无需区分新旧。
    candidates = storage.get_scored_unsummarized(
        min_score=cfg.score_threshold, within_days=7,
    )
    metrics["backlog"] = len(candidates) - metrics["passed_threshold"]

    candidates.sort(key=lambda p: p[1].score, reverse=True)

    # 每日额度：无论一天跑几次 summarize，当天最多只新写 top_n 条摘要。
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).isoformat()
    metrics["already_today"] = storage.count_summarized_since(today_start)
    budget = max(0, cfg.top_n - metrics["already_today"])
    top = candidates[:budget]
    logger.info(
        "threshold>=%d: %d passed (+%d backlog); already %d today, budget %d -> summarizing %d",
        cfg.score_threshold, metrics["passed_threshold"], metrics["backlog"],
        metrics["already_today"], budget, len(top),
    )

    sum_results = await asyncio.gather(*(_summarize_one(it, cfg) for it, _ in top))
    for item, summary, err in sum_results:
        if err is not None or summary is None:
            metrics["summary_errors"] += 1
            continue
        metrics["summarized"] += 1
        metrics["summarizer_cost_usd"] += summary.cost_usd
        storage.save_summary(item.url, summary)

    logger.info(
        "summarize done: scored=%d passed=%d backlog=%d purged=%d already=%d summarized=%d"
        " cost=$%.4f (scorer=$%.4f + summarizer=$%.4f)",
        metrics["scored"], metrics["passed_threshold"], metrics["backlog"],
        metrics["purged"], metrics["already_today"], metrics["summarized"],
        metrics["scorer_cost_usd"] + metrics["summarizer_cost_usd"],
        metrics["scorer_cost_usd"], metrics["summarizer_cost_usd"],
    )
    return metrics
