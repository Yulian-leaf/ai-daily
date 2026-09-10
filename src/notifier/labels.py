"""Friendly display label + category mapping for raw `Item.source` strings.

Storage stores source like "rss:openai-blog" or "github:github-trending-agent".
The web template wants both:
- a short human label ("OpenAI", "GitHub: agent")
- a category for color-coding ("lab", "expert", ...)
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceLabel:
    short: str
    category: str  # one of: lab / framework / expert / media / github / paper / community / other


_REGISTRY: dict[str, SourceLabel] = {
    # 实验室 / 厂商
    "rss:deepmind-blog":      SourceLabel("DeepMind",        "lab"),
    "rss:google-research":    SourceLabel("Google Research", "lab"),
    "rss:microsoft-research": SourceLabel("MS Research",     "lab"),
    "rss:nvidia-dev-blog":    SourceLabel("NVIDIA",          "lab"),
    # 期刊
    "rss:nature":             SourceLabel("Nature",          "paper"),
    "rss:science":            SourceLabel("Science",         "paper"),
    # 中文媒体
    "rss:qbitai":             SourceLabel("量子位",           "media"),
    # GitHub trending（AI4S）
    "github:github-trending-protein":         SourceLabel("GitHub · protein", "github"),
    "github:github-trending-moleculardynamics": SourceLabel("GitHub · MD",    "github"),
    "github:github-trending-drugdiscovery":   SourceLabel("GitHub · drug",    "github"),
    "github:github-trending-scientific-ml":   SourceLabel("GitHub · SciML",   "github"),
    # arXiv
    "arxiv:arxiv-qbio":       SourceLabel("arXiv · 生命",   "paper"),
    "arxiv:arxiv-physchem":   SourceLabel("arXiv · 物化",   "paper"),
    "arxiv:arxiv-climate":    SourceLabel("arXiv · 地球",   "paper"),
    "arxiv:arxiv-ml":         SourceLabel("arXiv · ML",     "paper"),
    # HN
    "hackernews:hackernews-ai": SourceLabel("Hacker News",  "community"),
}

# Fallback category by prefix when source isn't in _REGISTRY.
_PREFIX_FALLBACK: dict[str, str] = {
    "rss": "other",
    "github": "github",
    "arxiv": "paper",
    "hackernews": "community",
}


def label_for(source: str) -> SourceLabel:
    """Return the friendly label for a raw source string. Unknown sources get
    a best-effort label derived from the prefix and a category guess."""
    hit = _REGISTRY.get(source)
    if hit is not None:
        return hit
    # Unknown: parse "prefix:name"
    if ":" in source:
        prefix, name = source.split(":", 1)
        category = _PREFIX_FALLBACK.get(prefix, "other")
        return SourceLabel(short=name, category=category)
    return SourceLabel(short=source, category="other")
