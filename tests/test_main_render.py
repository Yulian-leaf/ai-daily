from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.models import Item, Score, Summary
from src.storage import Storage


@pytest.mark.asyncio
async def test_run_render_cmd_writes_html(tmp_path: Path):
    """run_render_cmd 渲染并写出 index.html。"""
    src = tmp_path / "sources.yaml"
    src.write_text("sources: []\n", encoding="utf-8")
    prefs = tmp_path / "preferences.yaml"
    prefs.write_text("""
keywords: [LLM]
models:
  scorer: openai/gpt-4o-mini
  summarizer: openai/gpt-4o
score_threshold: 7
top_n: 10
""", encoding="utf-8")
    db = tmp_path / "t.db"
    s = Storage(db); s.init()
    s.record_items([Item(url="https://x/a", title="A", content="c",
                         published_at=datetime.now(timezone.utc), source="t")])
    s.save_score("https://x/a", Score(score=9, tags=["LLM"], model="m", cost_usd=0.001))
    s.save_summary("https://x/a", Summary(innovation="i", approach="ap",
                                          metrics="m", links="l",
                                          why_relevant="w",
                                          model="m", cost_usd=0.01))
    s.close()
    out_dir = tmp_path / "site"

    from src.main import run_render_cmd
    result = await run_render_cmd(
        sources_path=src, preferences_path=prefs, db_path=db,
        output_dir=out_dir,
    )
    assert result["rendered"] == 1
    assert (out_dir / "index.html").exists()
