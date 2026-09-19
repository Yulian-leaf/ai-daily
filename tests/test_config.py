from pathlib import Path

import pytest

from src.config import load_config, ConfigError


def test_load_default_config(tmp_path: Path):
    """加载最小合法配置，验证 sources/keywords/fetch_window 解析正确。"""
    sources = tmp_path / "sources.yaml"
    prefs = tmp_path / "preferences.yaml"
    sources.write_text(
        "sources:\n"
        "  - name: s1\n"
        "    type: rss\n"
        "    url: https://example.com/feed\n",
        encoding="utf-8",
    )
    prefs.write_text(
        "keywords: [foo, bar]\n"
        "fetch_window_hours: 24\n",
        encoding="utf-8",
    )
    config = load_config(sources_path=sources, preferences_path=prefs)
    assert len(config.sources) == 1
    assert config.sources[0]["name"] == "s1"
    assert config.sources[0]["type"] == "rss"
    assert config.keywords == ["foo", "bar"]
    assert config.fetch_window_hours == 24


def test_load_config_defaults_fetch_window(tmp_path: Path):
    """不写 fetch_window_hours 时回退到默认 168 小时（7 天）。"""
    sources = tmp_path / "sources.yaml"
    prefs = tmp_path / "preferences.yaml"
    sources.write_text("sources: []\n", encoding="utf-8")
    prefs.write_text("keywords: []\n", encoding="utf-8")
    config = load_config(sources_path=sources, preferences_path=prefs)
    assert config.fetch_window_hours == 168  # default (7d)


def test_load_config_missing_source_field_raises(tmp_path: Path):
    """source 缺必填字段（type）时报 ConfigError。"""
    sources = tmp_path / "sources.yaml"
    prefs = tmp_path / "preferences.yaml"
    sources.write_text(
        "sources:\n"
        "  - name: bad\n",  # missing 'type'
        encoding="utf-8",
    )
    prefs.write_text("keywords: []\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="missing required field 'type'"):
        load_config(sources_path=sources, preferences_path=prefs)


def test_load_config_rejects_bool_fetch_window(tmp_path: Path):
    """fetch_window_hours 传布尔值要报错，防止类型写错。"""
    sources = tmp_path / "sources.yaml"
    prefs = tmp_path / "preferences.yaml"
    sources.write_text("sources: []\n", encoding="utf-8")
    prefs.write_text("keywords: []\nfetch_window_hours: true\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="must be an integer in"):
        load_config(sources_path=sources, preferences_path=prefs)


def test_real_default_config_loads():
    """仓库里真实的 config/*.yaml 能正常加载（冒烟测试）。"""
    # The committed config/*.yaml should load without errors.
    config = load_config(
        sources_path=Path("config/sources.yaml"),
        preferences_path=Path("config/preferences.yaml"),
    )
    assert len(config.sources) > 0
    assert len(config.keywords) > 0
