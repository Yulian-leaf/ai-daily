from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.models import Item
from src.storage import Storage


@pytest.mark.asyncio
async def test_run_summarize_cmd_loads_config_and_calls_pipeline(
    tmp_path: Path, monkeypatch
):
    """run_summarize_cmd 加载配置并调用流水线，产出摘要。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    src = tmp_path / "sources.yaml"
    src.write_text("sources: []\n", encoding="utf-8")
    prefs = tmp_path / "preferences.yaml"
    prefs.write_text("""
keywords: [LLM]
models:
  scorer: anthropic/claude-haiku-4-5
  summarizer: anthropic/claude-sonnet-4-6
score_threshold: 7
top_n: 1
""", encoding="utf-8")
    db = tmp_path / "t.db"
    s = Storage(db)
    s.init()
    s.record_items([Item(
        url="https://a", title="t", content="c",
        published_at=datetime.now(timezone.utc), source="x",
    )])
    s.close()

    async def fake(*, model, prompt, max_tokens, temperature=0.2):
        if "claude-haiku" in model:
            return ({"score": 9, "tags": ["LLM"]}, 0.001)
        return ({"innovation": "i", "approach": "a", "metrics": "m",
                 "links": "l", "why_relevant": "w"}, 0.01)

    from src.main import run_summarize_cmd
    with patch("src.summarizer.complete_json", new=AsyncMock(side_effect=fake)):
        result = await run_summarize_cmd(
            sources_path=src, preferences_path=prefs, db_path=db,
        )
    assert result["summarized"] == 1
    assert result["scorer_cost_usd"] > 0
