import re

import httpx
import pytest
from freezegun import freeze_time

import src.fetchers.arxiv as arxiv
from src.fetchers.arxiv import fetch_arxiv


@pytest.fixture(autouse=True)
def _disable_arxiv_throttle(monkeypatch):
    # 测试里把请求间隔设为 0，避免真实等待拖慢测试。
    monkeypatch.setattr(arxiv, "_ARXIV_INTERVAL_SECONDS", 0.0)


@pytest.mark.asyncio
@freeze_time("2026-05-15 12:00:00")
async def test_fetch_arxiv_returns_recent_papers(httpx_mock, arxiv_response_xml):
    """抓取 arXiv，保留时间窗口内的论文、过滤过旧的。"""
    httpx_mock.add_response(
        url=re.compile(r"https://export\.arxiv\.org/api/query.*"),
        text=arxiv_response_xml,
    )
    source = {
        "name": "arxiv-cs-ai",
        "type": "arxiv",
        "categories": ["cs.AI"],
        "max_results": 50,
    }
    items = await fetch_arxiv(source, window_hours=36)
    urls = [i.url for i in items]
    assert "http://arxiv.org/abs/2405.00001v1" in urls
    assert "http://arxiv.org/abs/2401.99999v1" not in urls
    new_item = next(i for i in items if i.url == "http://arxiv.org/abs/2405.00001v1")
    assert new_item.title == "A New Agent Framework"
    assert new_item.source == "arxiv:arxiv-cs-ai"
    assert "novel agent framework" in new_item.content


@pytest.mark.asyncio
@freeze_time("2026-05-15 12:00:00")
async def test_fetch_arxiv_retries_once_on_timeout(
    httpx_mock, arxiv_response_xml, monkeypatch
):
    """超时（瞬态错误）重试一次后成功。"""
    # Avoid real sleep in test.
    monkeypatch.setattr("src.fetchers.arxiv._RETRY_DELAY_SECONDS", 0.0)
    # First call: simulated timeout. Second call: success.
    httpx_mock.add_exception(httpx.ReadTimeout("simulated arxiv slow"))
    httpx_mock.add_response(
        url=re.compile(r"https://export\.arxiv\.org/api/query.*"),
        text=arxiv_response_xml,
    )
    source = {
        "name": "arxiv-cs-ai", "type": "arxiv",
        "categories": ["cs.AI"], "max_results": 50,
    }
    items = await fetch_arxiv(source, window_hours=36)
    # Retry succeeded — got the same items as the happy-path test.
    urls = [i.url for i in items]
    assert "http://arxiv.org/abs/2405.00001v1" in urls


@pytest.mark.asyncio
@freeze_time("2026-05-15 12:00:00")
async def test_fetch_arxiv_does_not_retry_on_404(httpx_mock):
    """404 非瞬态，不重试，直接抛错给编排层。"""
    # 404 is not transient — no retry, error propagates to the orchestrator.
    httpx_mock.add_response(
        url=re.compile(r"https://export\.arxiv\.org/api/query.*"),
        status_code=404,
    )
    source = {
        "name": "arxiv-cs-ai", "type": "arxiv",
        "categories": ["cs.AI"], "max_results": 50,
    }
    with pytest.raises(httpx.HTTPStatusError):
        await fetch_arxiv(source, window_hours=36)


@pytest.mark.asyncio
async def test_arxiv_throttle_spaces_consecutive_requests(monkeypatch):
    """连续请求必须被隔开 ≥ _ARXIV_INTERVAL_SECONDS（防 arXiv 429）。"""
    clock = {"t": 1000.0}
    sleeps = []
    monkeypatch.setattr(arxiv, "_ARXIV_INTERVAL_SECONDS", 3.0)
    monkeypatch.setattr(arxiv.time, "monotonic", lambda: clock["t"])

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        clock["t"] += seconds

    monkeypatch.setattr(arxiv.asyncio, "sleep", fake_sleep)
    arxiv._last_arxiv_slot = 0.0

    await arxiv._throttle()   # 第一次：距离上次足够久，无需等待
    await arxiv._throttle()   # 紧接着第二次：必须等 3 秒

    assert sleeps == [3.0]
