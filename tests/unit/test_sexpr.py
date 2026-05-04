"""Unit tests for the S-expression parser."""

import pytest

from kicad_condenser.parser.sexpr import atom, find, find_all, parse


class TestTokenizerAndParser:
    def test_simple_atom(self):
        assert parse("hello") == "hello"

    def test_empty_list(self):
        assert parse("()") == []

    def test_single_element_list(self):
        assert parse("(foo)") == ["foo"]

    def test_nested(self):
        result = parse("(kicad_sch (version 20231120))")
        assert result == ["kicad_sch", ["version", "20231120"]]

    def test_quoted_string(self):
        result = parse('(property "Reference" "R1")')
        assert result == ["property", "Reference", "R1"]

    def test_quoted_string_with_spaces(self):
        result = parse('(text "Hello World")')
        assert result == ["text", "Hello World"]

    def test_escaped_quote_in_string(self):
        result = parse('(text "say \\"hi\\"")')
        assert result == ["text", 'say "hi"']

    def test_escaped_newline(self):
        result = parse('(text "line1\\nline2")')
        assert result == ["text", "line1\nline2"]

    def test_comment_skipped(self):
        result = parse("(foo ; this is a comment\n  bar)")
        assert result == ["foo", "bar"]

    def test_multiline(self):
        text = """
(kicad_sch
  (version 20231120)
  (generator kicad_condenser)
)
"""
        result = parse(text)
        assert result[0] == "kicad_sch"
        assert find(result, "version") == ["version", "20231120"]

    def test_negative_numbers(self):
        result = parse("(at -10.5 20.0)")
        assert result == ["at", "-10.5", "20.0"]

    def test_deeply_nested(self):
        result = parse("(a (b (c (d e))))")
        assert result == ["a", ["b", ["c", ["d", "e"]]]]

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            parse("")

    def test_multiple_root_atoms(self):
        # Only the first top-level expression is returned
        result = parse("(a 1)(b 2)")
        assert result == ["a", "1"]


class TestFindHelpers:
    def setup_method(self):
        self.node = parse("""
(symbol "Device:R"
  (in_bom yes)
  (on_board yes)
  (property "Reference" "R")
  (property "Value" "R")
)
""")

    def test_find_existing(self):
        result = find(self.node, "in_bom")
        assert result == ["in_bom", "yes"]

    def test_find_missing_returns_none(self):
        assert find(self.node, "nonexistent") is None

    def test_find_on_atom_returns_none(self):
        assert find("not_a_list", "key") is None

    def test_find_all(self):
        results = find_all(self.node, "property")
        assert len(results) == 2
        assert results[0][1] == "Reference"
        assert results[1][1] == "Value"

    def test_find_all_missing(self):
        assert find_all(self.node, "nothing") == []


class TestAtomHelper:
    def test_atom_index_0(self):
        node = ["symbol", "Device:R"]
        assert atom(node, 0) == "symbol"

    def test_atom_index_1(self):
        node = ["version", "20231120"]
        assert atom(node, 1) == "20231120"

    def test_atom_on_non_list_raises(self):
        with pytest.raises(TypeError):
            atom("not_a_list", 0)

    def test_atom_on_list_element_raises(self):
        node = ["parent", ["child"]]
        with pytest.raises(TypeError):
            atom(node, 1)

    def test_atom_out_of_range_raises(self):
        node = ["foo"]
        with pytest.raises(IndexError):
            atom(node, 5)
