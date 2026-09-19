from src.notifier.labels import label_for


def test_known_lab_source():
    """实验室博客源 → DeepMind / lab。"""
    lbl = label_for("rss:deepmind-blog")
    assert lbl.short == "DeepMind"
    assert lbl.category == "lab"


def test_known_journal_source():
    """期刊源 → Nature / paper。"""
    lbl = label_for("rss:nature")
    assert lbl.short == "Nature"
    assert lbl.category == "paper"


def test_known_github_trending():
    """GitHub topic 源 → GitHub · protein / github。"""
    lbl = label_for("github:github-trending-protein")
    assert lbl.short == "GitHub · protein"
    assert lbl.category == "github"


def test_known_arxiv():
    """arXiv 分类源 → arXiv · 生命 / paper。"""
    lbl = label_for("arxiv:arxiv-qbio")
    assert lbl.short == "arXiv · 生命"
    assert lbl.category == "paper"


def test_known_hn():
    """HN 源 → Hacker News / community。"""
    lbl = label_for("hackernews:hackernews-ai")
    assert lbl.short == "Hacker News"
    assert lbl.category == "community"


def test_unknown_rss_falls_back_to_name_and_other():
    """未知 rss 源按名字兜底、分类 other。"""
    lbl = label_for("rss:some-new-blog")
    assert lbl.short == "some-new-blog"
    assert lbl.category == "other"


def test_unknown_github_falls_back_to_github_category():
    """未知 github 源兜底 github 分类。"""
    lbl = label_for("github:github-trending-rust")
    assert lbl.short == "github-trending-rust"
    assert lbl.category == "github"


def test_completely_unstructured_source():
    """无前缀的源兜底为原名 + other。"""
    lbl = label_for("nopfx")
    assert lbl.short == "nopfx"
    assert lbl.category == "other"
