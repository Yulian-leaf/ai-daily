from pathlib import Path

import pytest

from src.prompts import load_prompt, render


def test_load_prompt_finds_file(tmp_path: Path):
    """按名字加载提示词文件。"""
    (tmp_path / "score.txt").write_text("hi {keywords}", encoding="utf-8")
    out = load_prompt("score", prompts_dir=tmp_path)
    assert out == "hi {keywords}"


def test_load_prompt_missing(tmp_path: Path):
    """文件缺失时抛 FileNotFoundError。"""
    with pytest.raises(FileNotFoundError):
        load_prompt("nope", prompts_dir=tmp_path)


def test_render_fills_placeholders():
    """占位符渲染。"""
    tmpl = "kw={keywords} t={title}"
    out = render(tmpl, {"keywords": "LLM, agent", "title": "Hello"})
    assert out == "kw=LLM, agent t=Hello"


def test_render_preserves_literal_braces_in_json_examples():
    """JSON 示例里的 {{ }} 保留为字面花括号。"""
    # JSON in prompts uses {{ and }} to mean literal { } under str.format
    tmpl = 'Output: {{"score": 7}} for {title}'
    out = render(tmpl, {"title": "x"})
    assert out == 'Output: {"score": 7} for x'


def test_render_missing_key_raises():
    """模板缺 key 时抛 KeyError。"""
    with pytest.raises(KeyError):
        render("hi {missing}", {})
