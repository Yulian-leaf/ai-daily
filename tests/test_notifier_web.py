from datetime import datetime, timezone
from pathlib import Path

from src.models import Item, Score, Summary
from src.notifier.web import render_site
from src.storage import Storage


def _seed(s: Storage):
    now = datetime.now(timezone.utc)
    s.record_items([
        Item(url="https://example.com/foo", title="Foo Paper", content="...",
             published_at=now, source="arxiv:cs.AI"),
        Item(url="https://example.com/bar", title="Bar Repo", content="...",
             published_at=now, source="github:agent"),
        Item(url="https://example.com/below", title="Below Threshold", content="...",
             published_at=now, source="rss:misc"),
    ])
    s.save_score("https://example.com/foo",
                 Score(score=9, tags=["LLM", "agent"], model="m", cost_usd=0.001))
    s.save_summary("https://example.com/foo",
                   Summary(innovation="核心创新 X",
                           approach="技术方案 Y",
                           metrics="50% 提升",
                           links="https://example.com/code",
                           why_relevant="与关键词强相关",
                           model="m", cost_usd=0.01))
    s.save_score("https://example.com/bar",
                 Score(score=7, tags=["MCP"], model="m", cost_usd=0.001))
    s.save_summary("https://example.com/bar",
                   Summary(innovation="Bar 创新", approach="A2",
                           metrics="未披露", links="无",
                           why_relevant="关注 MCP 用户值得看",
                           model="m", cost_usd=0.01))
    # below: scored but no summary
    s.save_score("https://example.com/below",
                 Score(score=4, tags=[], model="m", cost_usd=0.001))


def test_render_site_first_run_puts_summaries_in_today_band(tmp_path: Path):
    s = Storage(tmp_path / "t.db"); s.init()
    _seed(s)
    out_dir = tmp_path / "site"
    result = render_site(s, min_score=7, within_days=30, top_n=100, output_dir=out_dir)
    s.close()

    index = out_dir / "index.html"
    assert index.exists()
    html = index.read_text(encoding="utf-8")

    # Self-contained — inline style + inline favorites script, no external assets.
    assert "<style>" in html
    assert '<link rel="stylesheet"' not in html
    assert "<script src=" not in html  # no external scripts
    assert 'href="http' in html  # but article links must be present

    # Both summarized items appear
    assert "Foo Paper" in html
    assert "Bar Repo" in html
    # Both bands are present. Use unique section markers so we don't match
    # the header meta line, which mentions both 今日新增 / 归档 as counters.
    today_band = html.index('class="band today"')
    archive_band = html.index('class="band archive"')
    assert today_band < archive_band
    # Both items live in the today band (before the archive band marker)
    assert today_band < html.index("Foo Paper") < archive_band
    assert today_band < html.index("Bar Repo") < archive_band

    assert 'href="https://example.com/foo"' in html
    assert 'href="https://example.com/bar"' in html
    assert "核心创新 X" in html
    assert "Bar 创新" in html
    assert "LLM" in html and "agent" in html and "MCP" in html
    assert "arxiv:cs.AI" in html
    assert "github:agent" in html
    # Foo's links: real URL ≠ item url → render as 补充
    assert "补充：" in html
    assert 'href="https://example.com/code"' in html
    # Bar's links = "无" → suppressed
    assert "补充：无" not in html
    assert "代码/项目：" not in html

    # Below-threshold (no summary) not rendered
    assert "Below Threshold" not in html

    # Score-desc within today
    assert html.index("Foo Paper") < html.index("Bar Repo")

    assert result["today"] == 2
    assert result["archive"] == 0
    assert result["marked_surfaced"] == 2
    assert result["rendered"] == 2  # back-compat key
    assert result["output"] == str(index)


def test_render_site_second_run_same_day_moves_to_archive(tmp_path: Path):
    s = Storage(tmp_path / "t.db"); s.init()
    _seed(s)
    out_dir = tmp_path / "site"
    # First run: items become surfaced.
    r1 = render_site(s, min_score=7, within_days=30, top_n=100, output_dir=out_dir)
    assert r1["today"] == 2 and r1["archive"] == 0

    # Second run (no new items in between).
    r2 = render_site(s, min_score=7, within_days=30, top_n=100, output_dir=out_dir)
    s.close()
    assert r2["today"] == 0
    assert r2["archive"] == 2
    assert r2["marked_surfaced"] == 0  # nothing new to mark

    html = (out_dir / "index.html").read_text(encoding="utf-8")
    # Today band is empty
    assert "本批次无新条目" in html
    # Items now appear in archive band (after the archive band marker)
    archive_band = html.index('class="band archive"')
    assert html.index("Foo Paper") > archive_band
    assert html.index("Bar Repo") > archive_band


def test_render_site_empty_db_writes_empty_states(tmp_path: Path):
    s = Storage(tmp_path / "t.db"); s.init()
    out_dir = tmp_path / "site"
    result = render_site(s, min_score=7, within_days=30, top_n=100, output_dir=out_dir)
    s.close()
    assert result["today"] == 0
    assert result["archive"] == 0
    html = (out_dir / "index.html").read_text(encoding="utf-8")
    assert "本批次无新条目" in html
    assert "归档暂时为空" in html


def test_render_site_source_badge_uses_friendly_label_and_category(tmp_path: Path):
    """The rendered HTML must show the friendly label (not the raw source id)
    and tag the badge with a `cat-<category>` class for color-coding."""
    from datetime import datetime, timezone
    from src.models import Item, Score, Summary
    s = Storage(tmp_path / "t.db"); s.init()
    s.record_items([Item(url="https://example/x", title="X", content="...",
                         published_at=datetime.now(timezone.utc),
                         source="rss:deepmind-blog")])
    s.save_score("https://example/x", Score(score=9, tags=["LLM"], model="m", cost_usd=0.001))
    s.save_summary("https://example/x", Summary(innovation="i", approach="a",
                                                metrics="m", links="l",
                                                why_relevant="w", model="m",
                                                cost_usd=0.01))
    out_dir = tmp_path / "site"
    render_site(s, min_score=7, within_days=30, top_n=100, output_dir=out_dir)
    s.close()
    html = (out_dir / "index.html").read_text(encoding="utf-8")
    assert "cat-lab" in html         # DeepMind -> lab category
    assert ">DeepMind<" in html       # friendly label rendered
    # raw id not in visible badge (only in the title= attribute for hover/debug)
    assert ">rss:deepmind-blog<" not in html


def test_render_site_archive_groups_by_surfaced_date(tmp_path: Path):
    """Archive items get grouped by their surfaced_at date, most recent first,
    each inside its own <details> block with the date as summary."""
    from datetime import datetime, timezone, timedelta
    from src.models import Item, Score, Summary
    s = Storage(tmp_path / "t.db"); s.init()
    now = datetime.now(timezone.utc)
    s.record_items([
        Item(url="https://x/a", title="ALPHA", content="c",
             published_at=now, source="rss:openai-blog"),
        Item(url="https://x/b", title="BETA", content="c",
             published_at=now, source="rss:openai-blog"),
    ])
    for u in ("https://x/a", "https://x/b"):
        s.save_score(u, Score(score=9, tags=[], model="m", cost_usd=0.001))
        s.save_summary(u, Summary(innovation="i", approach="a", metrics="m",
                                  links="l", why_relevant="w",
                                  model="m", cost_usd=0.01))
    # Backdate surfaced_at to two different dates.
    conn = s._conn_or_die()
    conn.execute("UPDATE summaries SET surfaced_at=? WHERE url=?",
                 ((now - timedelta(days=1)).isoformat(), "https://x/a"))
    conn.execute("UPDATE summaries SET surfaced_at=? WHERE url=?",
                 ((now - timedelta(days=2)).isoformat(), "https://x/b"))
    conn.commit()

    out_dir = tmp_path / "site"
    result = render_site(s, min_score=7, within_days=30, top_n=100, output_dir=out_dir)
    s.close()

    assert result["archive_dates"] == 2
    html = (out_dir / "index.html").read_text(encoding="utf-8")

    # Two <details> blocks, one per date.
    yesterday = (now - timedelta(days=1)).date().isoformat()
    day_before = (now - timedelta(days=2)).date().isoformat()
    assert f'id="archive-{yesterday}"' in html
    assert f'id="archive-{day_before}"' in html
    # The more recent date comes first.
    assert html.index(f'archive-{yesterday}') < html.index(f'archive-{day_before}')


def test_render_site_includes_favorites_machinery(tmp_path: Path):
    """Favorites section + toggleStar JS + STAR_PREFIX localStorage key are
    all present in the rendered HTML (no test of the JS itself, just markers)."""
    s = Storage(tmp_path / "t.db"); s.init()
    out_dir = tmp_path / "site"
    render_site(s, min_score=7, within_days=30, top_n=100, output_dir=out_dir)
    s.close()
    html = (out_dir / "index.html").read_text(encoding="utf-8")
    assert 'id="favorites"' in html
    assert "toggleStar" in html
    assert "STAR_PREFIX" in html
    assert "ai-daily:star:" in html
