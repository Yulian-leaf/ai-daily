from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.config import Config, Models
from src.models import Item, Score
from src.storage import Storage
from src.summarizer import run_summarize


def _item(url: str, title: str = "t", content: str = "c") -> Item:
    return Item(url=url, title=title, content=content,
                published_at=datetime.now(timezone.utc), source="test")


def _cfg(threshold: int = 7, top_n: int = 2) -> Config:
    return Config(
        sources=[],
        keywords=["LLM", "agent"],
        models=Models(scorer="anthropic/claude-haiku-4-5",
                      summarizer="anthropic/claude-sonnet-4-6"),
        score_threshold=threshold,
        top_n=top_n,
    )


@pytest.mark.asyncio
async def test_run_summarize_scores_all_and_summarizes_top_n(tmp_path: Path, monkeypatch):
    """全量打分，只总结过阈值且 top_n 的条目。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    db = tmp_path / "t.db"
    s = Storage(db)
    s.init()
    s.record_items([
        _item("https://a", title="TITLE-A"),
        _item("https://b", title="TITLE-B"),
        _item("https://c", title="TITLE-C"),
        _item("https://d", title="TITLE-D"),
    ])

    call_log: list[str] = []

    async def fake_complete_json(*, model, prompt, max_tokens, temperature=0.2):
        if model == "anthropic/claude-haiku-4-5":
            call_log.append("score")
            if "TITLE-A" in prompt: return ({"score": 9, "tags": ["LLM"]}, 0.001)
            if "TITLE-B" in prompt: return ({"score": 8, "tags": ["agent"]}, 0.001)
            if "TITLE-C" in prompt: return ({"score": 6, "tags": ["misc"]}, 0.001)
            if "TITLE-D" in prompt: return ({"score": 10, "tags": ["LLM", "agent"]}, 0.001)
            raise AssertionError(f"unexpected scorer prompt: {prompt[:100]!r}")
        call_log.append("summary")
        if "TITLE-D" in prompt:
            return ({"innovation": "i-d", "approach": "ap-d", "metrics": "m-d",
                     "links": "l-d", "why_relevant": "w-d"}, 0.01)
        if "TITLE-A" in prompt:
            return ({"innovation": "i-a", "approach": "ap-a", "metrics": "m-a",
                     "links": "l-a", "why_relevant": "w-a"}, 0.01)
        raise AssertionError(f"unexpected summarizer prompt: {prompt[:100]!r}")

    with patch("src.summarizer.complete_json", new=AsyncMock(side_effect=fake_complete_json)):
        result = await run_summarize(s, _cfg())

    assert result["scored"] == 4
    assert result["passed_threshold"] == 3
    assert result["summarized"] == 2
    assert result["scorer_cost_usd"] == pytest.approx(0.004)
    assert result["summarizer_cost_usd"] == pytest.approx(0.02)
    assert call_log.count("score") == 4
    assert call_log[:4] == ["score"] * 4
    assert call_log.count("summary") == 2

    top = s.get_top_summaries(min_score=7, limit=10, within_days=1)
    assert {a.url for a in top} == {"https://a", "https://b", "https://d"}
    with_summary = [a for a in top if a.summary is not None]
    assert {a.url for a in with_summary} == {"https://d", "https://a"}
    s.close()


@pytest.mark.asyncio
async def test_run_summarize_skips_item_on_score_error(tmp_path: Path, monkeypatch):
    """单条打分失败不中断整体。"""
    from src.llm import LLMError
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    s = Storage(tmp_path / "t.db")
    s.init()
    s.record_items([
        _item("https://a", title="TITLE-A"),
        _item("https://b", title="TITLE-B"),
    ])

    async def fake(*, model, prompt, max_tokens, temperature=0.2):
        if "TITLE-A" in prompt:
            raise LLMError("simulated provider error")
        return ({"score": 8, "tags": []}, 0.001)

    with patch("src.summarizer.complete_json", new=AsyncMock(side_effect=fake)):
        result = await run_summarize(s, _cfg(top_n=5))

    assert result["scored"] == 1
    assert result["score_errors"] == 1
    s.close()


@pytest.mark.asyncio
async def test_run_summarize_with_no_items_is_noop(tmp_path: Path, monkeypatch):
    """无条目时零 LLM 调用。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    s = Storage(tmp_path / "t.db")
    s.init()
    with patch("src.summarizer.complete_json", new=AsyncMock()) as m:
        result = await run_summarize(s, _cfg())
    assert result == {
        "scored": 0, "passed_threshold": 0, "summarized": 0,
        "score_errors": 0, "summary_errors": 0,
        "scorer_cost_usd": 0.0, "summarizer_cost_usd": 0.0,
        "backlog": 0, "purged": 0, "already_today": 0,
    }
    assert m.await_count == 0
    s.close()


def _cfg_with_subfields() -> Config:
    return Config(
        sources=[],
        keywords=["AI for Science"],
        models=Models(scorer="anthropic/claude-haiku-4-5",
                      summarizer="anthropic/claude-sonnet-4-6"),
        score_threshold=7,
        top_n=2,
        subfields=[{"key": "protein", "label": "蛋白质/结构"}],
    )


@pytest.mark.asyncio
async def test_run_summarize_parses_field(tmp_path: Path, monkeypatch):
    """scorer 返回合法 field 时正确写入。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    s = Storage(tmp_path / "t.db")
    s.init()
    s.record_items([_item("https://a", title="TITLE-A")])

    async def fake(*, model, prompt, max_tokens, temperature=0.2):
        if model == "anthropic/claude-haiku-4-5":
            return ({"score": 9, "tags": ["protein"], "field": "protein"}, 0.001)
        return ({"innovation": "i", "approach": "a", "metrics": "m",
                 "links": "l", "why_relevant": "w"}, 0.01)

    with patch("src.summarizer.complete_json", new=AsyncMock(side_effect=fake)):
        await run_summarize(s, _cfg_with_subfields())

    top = s.get_top_summaries(min_score=7, limit=10, within_days=1)
    assert top[0].score.field == "protein"
    s.close()


@pytest.mark.asyncio
async def test_run_summarize_field_out_of_range_falls_back(tmp_path: Path, monkeypatch):
    """越界 field 回退为空字符串。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    s = Storage(tmp_path / "t.db")
    s.init()
    s.record_items([_item("https://a", title="TITLE-A")])

    async def fake(*, model, prompt, max_tokens, temperature=0.2):
        if model == "anthropic/claude-haiku-4-5":
            return ({"score": 9, "tags": [], "field": "bogus"}, 0.001)
        return ({"innovation": "i", "approach": "a", "metrics": "m",
                 "links": "l", "why_relevant": "w"}, 0.01)

    with patch("src.summarizer.complete_json", new=AsyncMock(side_effect=fake)):
        await run_summarize(s, _cfg_with_subfields())

    top = s.get_top_summaries(min_score=7, limit=10, within_days=1)
    assert top[0].score.field == ""
    s.close()


@pytest.mark.asyncio
async def test_run_summarize_backfills_scored_unsummarized(tmp_path: Path, monkeypatch):
    """已打分(过阈值)但没摘要的近期条目，应被补总结。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    s = Storage(tmp_path / "t.db")
    s.init()
    s.record_items([_item("https://a", title="TITLE-A")])
    s.save_score("https://a", Score(score=9, tags=["x"], model="m", cost_usd=0.001))

    async def fake(*, model, prompt, max_tokens, temperature=0.2):
        # 没有未打分条目，只会被 summarizer 调用
        return ({"innovation": "i", "approach": "a", "metrics": "m",
                 "links": "l", "why_relevant": "w"}, 0.01)

    with patch("src.summarizer.complete_json", new=AsyncMock(side_effect=fake)):
        result = await run_summarize(s, _cfg(top_n=5))

    assert result["backlog"] == 1
    assert result["summarized"] == 1
    top = s.get_top_summaries(min_score=7, limit=10, within_days=1)
    assert len(top) == 1 and top[0].summary is not None
    s.close()


@pytest.mark.asyncio
async def test_run_summarize_purges_stale_unsummarized(tmp_path: Path, monkeypatch):
    """太久没写摘要的分数行应被清理，不再补总结。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    s = Storage(tmp_path / "t.db")
    s.init()
    s.record_items([_item("https://a", title="TITLE-A")])
    s.save_score("https://a", Score(score=9, tags=["x"], model="m", cost_usd=0.001))
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    conn = s._conn_or_die()
    conn.execute("UPDATE summaries SET created_at=? WHERE url=?", (old, "https://a"))
    conn.execute("UPDATE items SET first_seen=? WHERE url=?", (old, "https://a"))
    conn.commit()

    with patch("src.summarizer.complete_json", new=AsyncMock()) as m:
        result = await run_summarize(s, _cfg(top_n=5))

    assert result["purged"] == 1
    assert result["backlog"] == 0
    assert result["summarized"] == 0
    assert m.await_count == 0
    assert s.get_top_summaries(min_score=7, limit=10, within_days=1) == []
    s.close()


@pytest.mark.asyncio
async def test_run_summarize_caps_daily_quota(tmp_path: Path, monkeypatch):
    """同一天内多次 summarize，新写摘要总数最多只有 top_n 条。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    s = Storage(tmp_path / "t.db")
    s.init()
    s.record_items([
        _item("https://a"), _item("https://b"),
        _item("https://c"), _item("https://d"),
    ])
    for url in ["https://a", "https://b", "https://c", "https://d"]:
        s.save_score(url, Score(score=9, tags=["x"], model="m", cost_usd=0.001))

    async def fake(*, model, prompt, max_tokens, temperature=0.2):
        return ({"innovation": "i", "approach": "a", "metrics": "m",
                 "links": "l", "why_relevant": "w"}, 0.01)

    with patch("src.summarizer.complete_json", new=AsyncMock(side_effect=fake)):
        first = await run_summarize(s, _cfg(top_n=2))
    assert first["summarized"] == 2
    assert first["already_today"] == 0

    with patch("src.summarizer.complete_json", new=AsyncMock(side_effect=fake)) as m:
        second = await run_summarize(s, _cfg(top_n=2))

    # 第二轮：当天已写 2 条，额度用尽，不再总结
    assert second["already_today"] == 2
    assert second["summarized"] == 0
    assert m.await_count == 0
    assert len(s.get_today_summaries(min_score=7)) == 2
    s.close()
