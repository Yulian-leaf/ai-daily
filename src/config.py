from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    pass


@dataclass
class Models:
    scorer: str
    summarizer: str


@dataclass
class Config:
    sources: list[dict[str, Any]]
    keywords: list[str]
    fetch_window_hours: int = 168
    models: Models | None = None
    score_threshold: int = 7
    top_n: int = 10
    subfields: list[dict[str, str]] = field(default_factory=list)
    raw_preferences: dict[str, Any] = field(default_factory=dict)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must be a YAML mapping at top level")
    return data


def _validate_source(src: dict[str, Any]) -> None:
    for required in ("name", "type"):
        if required not in src:
            raise ConfigError(
                f"source {src!r} missing required field {required!r}"
            )


def _parse_models(prefs: dict[str, Any]) -> Models | None:
    models_doc = prefs.get("models")
    if models_doc is None:
        return None
    if not isinstance(models_doc, dict):
        raise ConfigError("`models` must be a mapping with `scorer` and `summarizer`")
    scorer = models_doc.get("scorer")
    summarizer = models_doc.get("summarizer")
    if not isinstance(scorer, str) or not scorer:
        raise ConfigError("`models.scorer` must be a non-empty string like 'anthropic/claude-haiku-4-5'")
    if not isinstance(summarizer, str) or not summarizer:
        raise ConfigError("`models.summarizer` must be a non-empty string like 'anthropic/claude-sonnet-4-6'")
    return Models(scorer=scorer, summarizer=summarizer)


def _parse_bounded_int(prefs: dict[str, Any], key: str, default: int, *, min_v: int, max_v: int) -> int:
    val = prefs.get(key, default)
    if isinstance(val, bool) or not isinstance(val, int) or val < min_v or val > max_v:
        raise ConfigError(f"`{key}` must be an integer in [{min_v}, {max_v}]")
    return val


def _parse_subfields(prefs: dict[str, Any]) -> list[dict[str, str]]:
    """Parse optional `subfields: [{key, label}, ...]` into normalized dicts."""
    subfields_doc = prefs.get("subfields")
    if subfields_doc is None:
        return []
    if not isinstance(subfields_doc, list):
        raise ConfigError("`subfields` must be a list of {key, label}")
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in subfields_doc:
        if not isinstance(entry, dict):
            raise ConfigError(f"subfield entry must be a mapping: {entry!r}")
        key = entry.get("key")
        label = entry.get("label")
        if not isinstance(key, str) or not key or not isinstance(label, str) or not label:
            raise ConfigError(f"subfield entry needs non-empty 'key' and 'label': {entry!r}")
        if key in seen:
            raise ConfigError(f"duplicate subfield key: {key!r}")
        seen.add(key)
        out.append({"key": key, "label": label})
    return out


def load_config(
    sources_path: Path = Path("config/sources.yaml"),
    preferences_path: Path = Path("config/preferences.yaml"),
) -> Config:
    sources_doc = _load_yaml(sources_path)
    prefs_doc = _load_yaml(preferences_path)

    sources = sources_doc.get("sources", [])
    if not isinstance(sources, list):
        raise ConfigError("`sources` must be a list")
    for src in sources:
        _validate_source(src)

    keywords = prefs_doc.get("keywords", [])
    if not isinstance(keywords, list):
        raise ConfigError("`keywords` must be a list")

    fetch_window = _parse_bounded_int(prefs_doc, "fetch_window_hours", 168, min_v=1, max_v=24 * 30)
    score_threshold = _parse_bounded_int(prefs_doc, "score_threshold", 7, min_v=0, max_v=10)
    top_n = _parse_bounded_int(prefs_doc, "top_n", 10, min_v=1, max_v=100)

    return Config(
        sources=sources,
        keywords=keywords,
        fetch_window_hours=fetch_window,
        models=_parse_models(prefs_doc),
        score_threshold=score_threshold,
        top_n=top_n,
        subfields=_parse_subfields(prefs_doc),
        raw_preferences=prefs_doc,
    )
