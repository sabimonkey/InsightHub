from app.services.synthesis.learning_note import project_learning_note


def test_project_learning_note_maps_user_language():
    payload = {
        "title": "学习摘要",
        "executive_summary": "本期重点摘要",
        "themes": [{"title": "Agent", "summary": "主题概述", "points": [{"text": "点一", "statement_type": "FACT", "citations": []}]}],
        "key_facts": [{"text": "事实一", "statement_type": "FACT", "citations": []}],
        "disagreements": [{"text": "观点分歧", "statement_type": "SOURCE_VIEW", "citations": []}],
        "open_questions": [{"text": "待确认问题", "statement_type": "UNCERTAINTY", "citations": []}],
    }
    note = project_learning_note(payload)
    assert note is not None
    assert "本期重点摘要" in note["highlights"]
    assert "关键事实" in note["sections"]
    assert note["sections"]["关键事实"][0]["label"] == "关键事实"
    assert "不同观点" in note["sections"]
    assert note["follow_ups"] == ["待确认问题"]
