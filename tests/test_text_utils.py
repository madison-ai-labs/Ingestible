from ingestion_tool.utils.text import (
    extract_heading_level,
    is_code_block,
    is_table_block,
    split_paragraphs,
    split_sentences,
)


def test_split_paragraphs():
    text = "First paragraph.\n\nSecond paragraph.\n\nThird."
    result = split_paragraphs(text)
    assert len(result) == 3
    assert result[0] == "First paragraph."


def test_split_paragraphs_empty():
    assert split_paragraphs("") == []
    assert split_paragraphs("   \n\n   ") == []


def test_split_sentences():
    text = "Hello world. This is a test. And another one."
    result = split_sentences(text)
    assert len(result) == 3


def test_is_table_block():
    table = "| A | B |\n|---|---|\n| 1 | 2 |"
    assert is_table_block(table) is True
    assert is_table_block("just some text") is False


def test_is_code_block():
    code = "```python\nprint('hello')\n```"
    assert is_code_block(code) is True
    assert is_code_block("not code") is False


def test_extract_heading_level():
    assert extract_heading_level("# Title") == 1
    assert extract_heading_level("## Section") == 2
    assert extract_heading_level("### Sub") == 3
    assert extract_heading_level("Not a heading") is None
