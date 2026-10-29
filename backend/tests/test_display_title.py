from types import SimpleNamespace

from app.services.display_title import library_card_title


def test_library_card_title_truncates_long_display():
    source = SimpleNamespace(
        source_type="URL",
        display_name="A" * 140,
        original_url="https://x.com/status/1",
        canonical_url=None,
    )
    title = library_card_title(source, document_title=None, analysis_summary=None, max_len=96)
    assert len(title) <= 96
    assert title.endswith("…")
