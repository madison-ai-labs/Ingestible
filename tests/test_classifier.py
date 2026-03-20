"""Tests for VBC content-tier classification."""
from ingestible.pipeline.stage1c_classify import classify_block, _split_into_blocks


class TestClassifyBlock:
    def test_fenced_code_block(self):
        assert classify_block("```python\ndef foo():\n    return 42\n```") == "T0"

    def test_latex_block(self):
        assert classify_block("$$\\sum_{i=1}^{n} x_i$$") == "T0"

    def test_latex_inline(self):
        assert classify_block("\\begin{equation}\nx = \\frac{-b \\pm \\sqrt{b^2}}{2a}\n\\end{equation}") == "T0"

    def test_markdown_table(self):
        table = "| Name | Age |\n| --- | --- |\n| Alice | 30 |\n| Bob | 25 |"
        assert classify_block(table) == "T1"

    def test_dense_json_block_is_verbatim(self):
        # Dense bracket content (bracket_density > 0.05) is classified as T0 (verbatim)
        assert classify_block('{"key": "value",\n "items": [1, 2, 3],\n "nested": {"a": "b"}}') == "T0"

    def test_json_like_block_is_structural(self):
        # JSON-like: starts with {, bracket_density > 0.02, but < 3 lines so not T0
        block = '{"username": "alice_wonderland", "email": "alice@example.com"}'
        assert classify_block(block) == "T1"

    def test_key_value_block(self):
        block = "HOST: localhost\nPORT: 8080\nDEBUG: true\nLOG_LEVEL: info"
        assert classify_block(block) == "T1"

    def test_prose_is_t2_or_t3(self):
        prose = "The quick brown fox jumps over the lazy dog. This is simple narrative text."
        tier = classify_block(prose)
        assert tier in ("T2", "T3")

    def test_empty_text(self):
        assert classify_block("") == "T3"
        assert classify_block("   ") == "T3"


class TestSplitIntoBlocks:
    def test_splits_code_fences(self):
        md = "Some text.\n\n```python\ncode here\n```\n\nMore text."
        blocks = _split_into_blocks(md)
        assert len(blocks) == 3
        assert blocks[0] == "Some text."
        assert "```python" in blocks[1]
        assert blocks[2] == "More text."

    def test_splits_paragraphs(self):
        md = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        blocks = _split_into_blocks(md)
        assert len(blocks) == 3

    def test_preserves_code_block_intact(self):
        md = "```\nline 1\nline 2\nline 3\n```"
        blocks = _split_into_blocks(md)
        assert len(blocks) == 1
        assert "line 1" in blocks[0]
        assert "line 3" in blocks[0]
