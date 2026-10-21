from app.core.llm import build_messages, extract_citation_ids, sanitize_citations


def test_extract_and_sanitize_citations() -> None:
    answer = "甲 [S1]，乙 [S2]，丙 [S9]。"
    assert extract_citation_ids(answer) == {"S1", "S2", "S9"}

    cleaned, used = sanitize_citations(answer, {"S1", "S2"})
    assert "[S9]" not in cleaned
    assert "[S1]" in cleaned and "[S2]" in cleaned
    assert used == {"S1", "S2"}


def test_build_messages_contains_context() -> None:
    chunks = [
        {
            "id": "S1",
            "text": "市内交通费每日上限 80 元。",
            "source": "差旅管理制度.pdf",
            "page": "12-14",
            "version": "v2.1",
        }
    ]
    messages = build_messages("差旅报销标准是多少", chunks)
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "[S1]" in messages[1]["content"]
    assert "差旅报销标准是多少" in messages[1]["content"]
