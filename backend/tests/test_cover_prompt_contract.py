import pytest

from app.services.cover.prompt import (
    DEFAULT_GLOBAL_PROMPT,
    GLOBAL_PROMPT_MAX_CHARS,
    PROMPT_VERSION,
    build_default_cover_prompt,
    build_cover_prompt,
    choose_palette,
    resolve_cover_topic,
    resolve_effective_cover_prompt,
)
from app.services.cover.service import CoverGenerationService
from app.services.image.minimax_contract import MAX_PROMPT_CHARS, prompt_char_count


TARGET_URL = "https://x.com/argona0x/status/2110045296902164532?s=46"


def test_default_prompt_under_target_for_chinese_title():
    prompt, usable = build_default_cover_prompt(
        title="OpenKB Agent 工作流",
        source_type="URL",
        summary="开源知识库 Agent 编排与插件市场。",
    )
    assert usable
    assert prompt_char_count(prompt) <= MAX_PROMPT_CHARS
    assert DEFAULT_GLOBAL_PROMPT in prompt
    assert "Article topic and visual subject:" in prompt
    assert TARGET_URL not in prompt


def test_long_english_title_stays_within_default_budget():
    title = "A" * 400 + " benchmark report on multi-agent memory systems"
    prompt, _ = build_default_cover_prompt(title=title, source_type="URL", summary="Industry trends.")
    assert prompt_char_count(prompt) <= MAX_PROMPT_CHARS


def test_url_only_title_uses_fallback_topic_not_duplicated_url():
    topic, usable = resolve_cover_topic(
        title=TARGET_URL,
        summary=None,
        plain_excerpt=None,
        source_type="URL",
    )
    assert TARGET_URL not in topic
    prompt, _ = build_default_cover_prompt(title=TARGET_URL, source_type="URL", summary=None)
    assert prompt.count("https://") == 0
    assert prompt_char_count(prompt) <= MAX_PROMPT_CHARS
    assert usable is False


def test_summary_used_when_title_is_url():
    prompt, usable = build_default_cover_prompt(
        title=TARGET_URL,
        source_type="URL",
        summary="讨论 Agent 记忆架构与检索增强。",
    )
    assert usable
    assert "Agent" in prompt or "记忆" in prompt
    assert TARGET_URL not in prompt


def test_emoji_title():
    prompt, _ = build_default_cover_prompt(title="🚀 发射计划", source_type="URL", summary="")
    assert "🚀" in prompt
    assert prompt_char_count(prompt) <= MAX_PROMPT_CHARS


def test_effective_prompt_accepts_exactly_1500_chars():
    body = "A" * 1500
    assert prompt_char_count(resolve_effective_cover_prompt(default_prompt="short default", edited_prompt=body)) == 1500


def test_effective_prompt_rejects_over_1500():
    body = "B" * 1501
    with pytest.raises(ValueError, match="COVER_PROMPT_TOO_LONG"):
        resolve_effective_cover_prompt(default_prompt="short default", edited_prompt=body)


def test_submit_matches_preview_no_double_wrap(db_session, monkeypatch):
    from datetime import datetime, timezone

    from app.models.source_item import SourceItem

    monkeypatch.setenv("MINIMAX_API_KEY", "fake")
    from app.core.config import get_settings
    from app.services.llm.deployments import sync_deployments

    settings = get_settings().model_copy(update={"minimax_enable_fake": True, "cover_inline": True})
    sync_deployments(db_session, settings)
    now = datetime.now(timezone.utc)
    unique = f"https://example.test/cover-prompt/{__import__('uuid').uuid4()}"
    source = SourceItem(
        id=__import__("uuid").uuid4(),
        source_type="URL",
        display_name=unique,
        original_url=unique,
        canonical_url=unique,
        status="STORED",
        privacy_level="PRIVATE",
        system_scope="AUTOMATION_TEST",
        created_at=now,
        updated_at=now,
    )
    db_session.add(source)
    db_session.commit()
    service = CoverGenerationService(db_session, settings=settings)
    preview, _, _ = service.build_prompt_for_source(source.id)
    run = service.enqueue(source.id, prompt=preview, confirm_send=True)
    assert run.prompt == preview
    assert prompt_char_count(run.prompt) <= MAX_PROMPT_CHARS


def test_prompt_version_v6_and_topic_color_choices_are_not_global_warm():
    assert PROMPT_VERSION == "cover-v6"
    prompt, _ = build_default_cover_prompt(
        title="Robotics and medical imaging",
        source_type="PDF",
        summary="A robot-assisted diagnostic imaging system.",
        color_scheme="cool",
    )
    assert "Palette direction (cool):" in prompt
    assert "cool cobalt" in prompt
    assert "Warm Editorial" not in prompt
    assert "muted amber, clay" not in prompt


def test_automatic_palette_avoids_recently_repeated_options():
    palette = choose_palette("Robotics and medical imaging", recent_palettes=["cool"] * 8)
    assert palette != "cool"
    assert palette in {"high_contrast", "vivid", "neutral"}


def test_legacy_build_cover_prompt_wrapper():
    prompt, _ = build_cover_prompt(
        title="Test",
        categories=["knowledge"],
        source_type="URL",
        summary="Summary",
        points=[],
    )
    assert prompt_char_count(prompt) <= MAX_PROMPT_CHARS


def test_global_prompt_configuration_has_safe_context_budget():
    assert len(DEFAULT_GLOBAL_PROMPT) <= GLOBAL_PROMPT_MAX_CHARS
