from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Item:
    url: str
    title: str
    content: str
    published_at: datetime
    source: str
    raw: dict = field(default_factory=dict)


@dataclass
class Score:
    score: int          # 0-10
    tags: list[str]
    model: str
    cost_usd: float
    field: str = ""     # AI4S 子领域 key（scorer 输出，来自 preferences.subfields）


@dataclass
class Summary:
    innovation: str
    approach: str
    metrics: str
    links: str
    why_relevant: str
    model: str
    cost_usd: float


@dataclass
class Analysis:
    """Joined view: an item with its score (always) and summary (if score >= threshold)."""

    url: str
    title: str
    source: str
    content: str
    published_at: datetime
    score: Score
    summary: Summary | None
    surfaced_at: datetime | None = None  # When item was first part of any digest

    @property
    def total_cost_usd(self) -> float:
        return self.score.cost_usd + (self.summary.cost_usd if self.summary else 0.0)
