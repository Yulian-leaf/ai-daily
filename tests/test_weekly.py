from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.config import Config, Models
from src.models import Item, Score, Summary, WeeklyReport
from src.notifier.web import render_poster, render_weekly
from src.storage import Storage
from src.weekly import run_weekly


def _cfg() -> Config:
    return Config(
        sources=[],
        keywords=["AI for Science"],
        models=Models(scorer="deepseek/deepseek-chat",
                      summarizer="deepseek/deepseek-chat"),
        score_threshold=7,
        top_n=10,
        subfields=[{"key": "protein", "label": "蛋白质/结构"}],
    )


def _seed_surfaced(s: Storage, n: int = 5) -> None:
    """Seed n items that are scored, summarized, and surfaced today."""
    now = datetime.now(timezone.utc)
    for i in range(n):
        url = f"https://x/{i}"
        s.record_items([Item(url=url, title=f"T{i}", content="c",
                             published_at=now, source="arxiv:arxiv-qbio")])
        s.save_score(url, Score(score=9, tags=["protein"], model="m",
                                cost_usd=0.001, field="protein"))
        s.save_summary(url, Summary(innovation="i", approach="a", metrics="m",
                                    links="l", why_relevant="w",
                                    model="m", cost_usd=0.01))
        s.mark_surfaced([url])


def test_save_and_get_weekly_report_roundtrip(tmp_path: Path):
    s = Storage(tmp_path / "t.db"); s.init()
    report = WeeklyReport(
        period="weekly", week_start="2026-09-13", week_end="2026-09-19",
        title="T", slogan="金句", overview="o",
        highlights=[{"field": "protein", "title": "t", "url": "u", "summary": "s"}],
        trend="tr", outlook="out", generated_at="2026-09-19T00:00:00+00:00",
    )
    s.save_weekly_report(report)
    got = s.get_weekly_reports("weekly")
    assert len(got) == 1
    assert got[0].title == "T"
    assert got[0].slogan == "金句"
    assert got[0].highlights[0]["field"] == "protein"

    # idempotent upsert: same (period, week_start) overwrites, no duplicate.
    report.title = "T2"
    s.save_weekly_report(report)
    got = s.get_weekly_reports("weekly")
    assert len(got) == 1
    assert got[0].title == "T2"
    s.close()


def test_get_surfaced_since_filters(tmp_path: Path):
    s = Storage(tmp_path / "t.db"); s.init()
    _seed_surfaced(s, n=3)
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=1)).isoformat()
    assert len(s.get_surfaced_since(cutoff, min_score=7)) == 3
    future = (now + timedelta(days=1)).isoformat()
    assert s.get_surfaced_since(future, min_score=7) == []
    s.close()


@pytest.mark.asyncio
async def test_run_weekly_generates_report(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    s = Storage(tmp_path / "t.db"); s.init()
    _seed_surfaced(s, n=5)

    async def fake(*, model, prompt, max_tokens, temperature=0.2):
        return ({"title": "AI4S 周报", "overview": "本周概述",
                 "highlights": [{"field": "protein", "title": "T0",
                                 "url": "https://x/0", "summary": "亮点"}],
                 "trend": "趋势", "outlook": "展望"}, 0.01)

    with patch("src.weekly.complete_json", new=AsyncMock(side_effect=fake)):
        result = await run_weekly(s, _cfg())

    assert result["skipped"] is False
    assert result["highlights"] == 1
    assert s.get_latest_weekly("weekly").title == "AI4S 周报"
    s.close()


@pytest.mark.asyncio
async def test_run_weekly_skips_when_few_items(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    s = Storage(tmp_path / "t.db"); s.init()
    _seed_surfaced(s, n=1)  # below the min-items threshold

    with patch("src.weekly.complete_json", new=AsyncMock()) as m:
        result = await run_weekly(s, _cfg())

    assert result["skipped"] is True
    assert m.await_count == 0  # no LLM call when skipping
    assert s.get_latest_weekly("weekly") is None
    s.close()


def test_render_weekly_writes_html(tmp_path: Path):
    s = Storage(tmp_path / "t.db"); s.init()
    s.save_weekly_report(WeeklyReport(
        period="weekly", week_start="2026-09-13", week_end="2026-09-19",
        title="T", overview="o",
        highlights=[{"field": "protein", "title": "t", "url": "u", "summary": "s"}],
        trend="tr", outlook="out", generated_at="2026-09-19T00:00:00+00:00",
    ))
    out_dir = tmp_path / "site"
    result = render_weekly(
        s, period="weekly",
        subfields=[{"key": "protein", "label": "蛋白质/结构"}],
        output_dir=out_dir,
    )
    s.close()
    html = (out_dir / "weekly.html").read_text(encoding="utf-8")
    assert "T" in html
    assert "蛋白质/结构" in html
    assert 'href="index.html"' in html
    assert result["reports"] == 1


@pytest.mark.asyncio
async def test_run_biweekly_uses_biweekly_prompt(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    s = Storage(tmp_path / "t.db"); s.init()
    _seed_surfaced(s, n=5)

    captured = {}

    async def fake(*, model, prompt, max_tokens, temperature=0.2):
        captured["prompt"] = prompt
        return ({"title": "AI4S 双周报告", "overview": "o",
                 "highlights": [], "trend": "t", "outlook": "out"}, 0.01)

    with patch("src.weekly.complete_json", new=AsyncMock(side_effect=fake)):
        await run_weekly(s, _cfg(), period="biweekly")

    assert "双周" in captured["prompt"]  # biweekly.txt is used, not weekly.txt
    assert s.get_latest_weekly("biweekly").title == "AI4S 双周报告"
    assert s.get_latest_weekly("weekly") is None
    s.close()


def test_get_stats(tmp_path: Path):
    s = Storage(tmp_path / "t.db"); s.init()
    _seed_surfaced(s, n=3)
    stats = s.get_stats()
    assert stats["items"] == 3
    assert stats["summarized"] == 3
    assert stats["surfaced"] == 3
    assert stats["by_field"].get("protein") == 3
    s.close()


def test_render_poster_writes_html(tmp_path: Path):
    s = Storage(tmp_path / "t.db"); s.init()
    s.save_weekly_report(WeeklyReport(
        period="weekly", week_start="2026-09-13", week_end="2026-09-19",
        title="T", overview="o",
        highlights=[{"field": "protein", "title": "t", "url": "u", "summary": "s"}],
        trend="tr", outlook="out", generated_at="2026-09-19T00:00:00+00:00",
    ))
    _seed_surfaced(s, n=3)
    out_dir = tmp_path / "site"
    result = render_poster(
        s, period="weekly",
        subfields=[{"key": "protein", "label": "蛋白质/结构"}],
        output_dir=out_dir,
    )
    s.close()
    html = (out_dir / "poster.html").read_text(encoding="utf-8")
    assert "T" in html
    assert "蛋白质/结构" in html
    assert "抓取条目" in html
    # stats["items"] must render the int, not the dict.items() method repr.
    assert 'class="num">3</span><small>抓取条目' in html
    assert "9.0" in html  # poster highlight shows score with one decimal
    assert result["report"] == "T"
