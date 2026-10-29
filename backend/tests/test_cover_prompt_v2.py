from app.services.cover.prompt import PROMPT_VERSION, build_cover_prompt
from app.services.image.minimax_contract import MAX_PROMPT_CHARS


def test_cover_v2_includes_dominant_subject_constraint():
    prompt, usable = build_cover_prompt(
        title="OpenKB Agent 工作流",
        categories=["project_discovery"],
        source_type="GITHUB",
        summary="开源知识库 Agent 编排与插件市场。",
        points=["模板市场"],
    )
    assert usable
    assert "large, unmistakable" in prompt
    assert "random UI glyphs" in prompt
    assert len(prompt) <= MAX_PROMPT_CHARS


def test_cover_v2_prompt_version():
    assert PROMPT_VERSION == "cover-v6"


def test_cover_v5_prompt_strengthens_subject_contrast_without_locking_palette():
    prompt, _ = build_cover_prompt(
        title="Robotics research",
        categories=["knowledge"],
        source_type="PDF",
        summary="A robotic arm assists a surgeon during precision imaging.",
        points=[],
        color_scheme="cool",
    )
    assert "strong contrast readable at card size" in prompt
    assert "Avoid washed-out" in prompt
    assert "Palette direction (cool):" in prompt
    assert "cool cobalt" in prompt
    assert "muted amber, clay" not in prompt


def test_cover_v2_themes():
    for title, slug in [
        ("AI Bot 模板", ["business"]),
        ("半导体算力", ["knowledge"]),
        ("商业趋势", ["business"]),
    ]:
        prompt, _ = build_cover_prompt(title=title, categories=slug, source_type="URL", summary="行业洞察与趋势。" * 2, points=[])
        assert len(prompt) <= MAX_PROMPT_CHARS
        assert "large, unmistakable" in prompt
