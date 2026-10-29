from app.services.retrieval.ask_title import derive_ask_session_title


def test_derive_title_from_question():
    title = derive_ask_session_title("总结我最近收藏的 Agent 相关资料，并分析未来发展趋势")
    assert "Agent" in title
    assert len(title) <= 25


def test_derive_title_strips_fillers():
    assert "OpenKB" in derive_ask_session_title("请问 OpenKB 有哪些技术特点？")
