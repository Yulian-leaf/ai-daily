from pathlib import Path

import pytest

from src.config import load_config, ConfigError


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_loads_models_and_thresholds(tmp_path: Path):
    """解析 models（scorer+summarizer）、score_threshold、top_n。"""
    src = _write(tmp_path / "sources.yaml", "sources: []\n")
    prefs = _write(tmp_path / "preferences.yaml", """
keywords: [LLM]
fetch_window_hours: 36
models:
  scorer: anthropic/claude-haiku-4-5
  summarizer: anthropic/claude-sonnet-4-6
score_threshold: 7
top_n: 10
""")
    cfg = load_config(sources_path=src, preferences_path=prefs)
    assert cfg.models.scorer == "anthropic/claude-haiku-4-5"
    assert cfg.models.summarizer == "anthropic/claude-sonnet-4-6"
    assert cfg.score_threshold == 7
    assert cfg.top_n == 10


def test_models_required_when_summarize_section_present(tmp_path: Path):
    """配了 models 但缺 summarizer 时报 ConfigError。"""
    src = _write(tmp_path / "sources.yaml", "sources: []\n")
    prefs = _write(tmp_path / "preferences.yaml", """
keywords: [LLM]
models:
  scorer: anthropic/claude-haiku-4-5
  # summarizer missing
""")
    with pytest.raises(ConfigError, match="models.summarizer"):
        load_config(sources_path=src, preferences_path=prefs)


def test_defaults_when_models_absent(tmp_path: Path):
    """不配 models 时 models=None，阈值/top_n 用默认值。"""
    src = _write(tmp_path / "sources.yaml", "sources: []\n")
    prefs = _write(tmp_path / "preferences.yaml", "keywords: []\n")
    cfg = load_config(sources_path=src, preferences_path=prefs)
    assert cfg.models is None
    assert cfg.score_threshold == 7
    assert cfg.top_n == 10


def test_invalid_thresholds(tmp_path: Path):
    """score_threshold 越界（>10）报 ConfigError。"""
    src = _write(tmp_path / "sources.yaml", "sources: []\n")
    prefs = _write(tmp_path / "preferences.yaml", """
keywords: []
score_threshold: 11
""")
    with pytest.raises(ConfigError, match="score_threshold"):
        load_config(sources_path=src, preferences_path=prefs)


def test_parses_subfields(tmp_path: Path):
    """subfields 列表正确解析成 [{key,label}, ...]。"""
    src = _write(tmp_path / "sources.yaml", "sources: []\n")
    prefs = _write(tmp_path / "preferences.yaml", """
keywords: []
subfields:
  - key: protein
    label: 蛋白质/结构
  - key: drug
    label: 药物发现
""")
    cfg = load_config(sources_path=src, preferences_path=prefs)
    assert cfg.subfields == [
        {"key": "protein", "label": "蛋白质/结构"},
        {"key": "drug", "label": "药物发现"},
    ]


def test_subfields_absent_defaults_to_empty(tmp_path: Path):
    """不配 subfields 时默认空列表。"""
    src = _write(tmp_path / "sources.yaml", "sources: []\n")
    prefs = _write(tmp_path / "preferences.yaml", "keywords: []\n")
    cfg = load_config(sources_path=src, preferences_path=prefs)
    assert cfg.subfields == []


def test_subfields_reject_bad_entry(tmp_path: Path):
    """subfield 缺 label 等非法项报 ConfigError。"""
    src = _write(tmp_path / "sources.yaml", "sources: []\n")
    prefs = _write(tmp_path / "preferences.yaml", """
keywords: []
subfields:
  - key: protein
""")
    with pytest.raises(ConfigError, match="subfield"):
        load_config(sources_path=src, preferences_path=prefs)
