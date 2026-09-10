# 双重过滤、单次批查、保持抓取时序
from src.models import Item
from src.storage import Storage


def dedup_by_url(items: list[Item], storage: Storage) -> list[Item]:
    """Remove items whose URL was seen before OR appears earlier in this batch.

    Returns a new list preserving original order (first occurrence wins).
    """
    if not items:
        return []
    urls = [i.url for i in items]
    already_seen = storage.seen_urls(urls)
    out: list[Item] = []
    batch_seen: set[str] = set()
    for item in items:
        if item.url in already_seen or item.url in batch_seen:
            continue
        batch_seen.add(item.url)
        out.append(item)
    return out
