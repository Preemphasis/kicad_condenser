"""S-Expression tokenizer and parser for KiCad file formats.

The KiCad S-expression format uses Lisp-like nested lists:
  (token attr1 attr2 (nested token ...))

Quoted strings use double-quotes with backslash escapes.
Line comments start with a semicolon (;) and run to end-of-line.

Public API
----------
parse(text: str) -> SExpr
    Parse a full S-expression document and return the root node.

find(node: SExpr, key: str) -> SExpr | None
    Return the first child list whose first element equals *key*.

find_all(node: SExpr, key: str) -> list[SExpr]
    Return all child lists whose first element equals *key*.

atom(node: SExpr, index: int) -> str
    Return the positional atom at *index* (0 = the key itself).
"""

from __future__ import annotations

from typing import Union

# A node is either an atom (str) or a list of nodes.
SExpr = Union[str, list]


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

_OPEN = "("
_CLOSE = ")"


def _tokenize(text: str) -> list[str]:
    """Convert raw KiCad S-expression text into a flat token list."""
    tokens: list[str] = []
    i = 0
    n = len(text)

    while i < n:
        c = text[i]

        # Skip whitespace
        if c in " \t\r\n":
            i += 1
            continue

        # Line comment — skip to end of line
        if c == ";":
            while i < n and text[i] != "\n":
                i += 1
            continue

        # Open / close paren
        if c == _OPEN:
            tokens.append(_OPEN)
            i += 1
            continue

        if c == _CLOSE:
            tokens.append(_CLOSE)
            i += 1
            continue

        # Quoted string
        if c == '"':
            i += 1  # skip opening quote
            buf: list[str] = []
            while i < n:
                ch = text[i]
                if ch == "\\":
                    i += 1
                    if i >= n:
                        break
                    escaped = text[i]
                    if escaped == "n":
                        buf.append("\n")
                    elif escaped == "t":
                        buf.append("\t")
                    elif escaped == "r":
                        buf.append("\r")
                    else:
                        buf.append(escaped)
                    i += 1
                elif ch == '"':
                    i += 1  # skip closing quote
                    break
                else:
                    buf.append(ch)
                    i += 1
            # Prefix with a sentinel so we can tell quoted strings from bare atoms
            tokens.append("\x00" + "".join(buf))
            continue

        # Bare atom — everything up to whitespace or paren
        j = i
        while j < n and text[j] not in " \t\r\n();\x00":
            j += 1
        tokens.append(text[i:j])
        i = j

    return tokens


# ---------------------------------------------------------------------------
# Recursive parser
# ---------------------------------------------------------------------------

def _parse_tokens(tokens: list[str], pos: int) -> tuple[SExpr, int]:
    """Recursively build an SExpr tree from *tokens* starting at *pos*."""
    tok = tokens[pos]

    if tok == _OPEN:
        pos += 1  # consume "("
        children: list[SExpr] = []
        while tokens[pos] != _CLOSE:
            child, pos = _parse_tokens(tokens, pos)
            children.append(child)
        pos += 1  # consume ")"
        return children, pos

    if tok == _CLOSE:
        raise SyntaxError("Unexpected ')' in S-expression")

    # Atom — strip sentinel from quoted strings
    if tok.startswith("\x00"):
        return tok[1:], pos + 1

    return tok, pos + 1


def parse(text: str) -> SExpr:
    """Parse a KiCad S-expression string and return the root node."""
    tokens = _tokenize(text)
    if not tokens:
        raise ValueError("Empty S-expression")
    result, consumed = _parse_tokens(tokens, 0)
    return result


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def find(node: SExpr, key: str) -> SExpr | None:
    """Return the first child list of *node* whose first element is *key*."""
    if not isinstance(node, list):
        return None
    for child in node:
        if isinstance(child, list) and child and child[0] == key:
            return child
    return None


def find_all(node: SExpr, key: str) -> list[SExpr]:
    """Return all child lists of *node* whose first element is *key*."""
    if not isinstance(node, list):
        return []
    return [
        child
        for child in node
        if isinstance(child, list) and child and child[0] == key
    ]


def atom(node: SExpr, index: int) -> str:
    """Return the string atom at *index* within *node*.

    Raises IndexError if out of range, TypeError if the element is a list.
    """
    if not isinstance(node, list):
        raise TypeError(f"Expected a list node, got {type(node)}")
    value = node[index]
    if isinstance(value, list):
        raise TypeError(f"Element at index {index} is a list, not an atom")
    return value
