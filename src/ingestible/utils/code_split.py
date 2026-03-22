"""Language-aware splitting of source code at top-level declaration boundaries.

Uses regex-based heuristics (not a full AST) for portability across languages.
Supports Python, TypeScript/JavaScript, Go, Rust, and Java/Kotlin.

Known limitation: regex cannot distinguish keywords inside string literals or
comments from real declarations. For production use on complex codebases,
consider tree-sitter (used by LlamaIndex CodeSplitter, Aider, Continue.dev).
The regex approach here is a zero-dependency baseline that handles the majority
of real-world source files correctly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class CodeDeclaration:
    """A top-level declaration extracted from a source file."""

    kind: str  # "function", "class", "interface", "struct", "enum", "preamble", etc.
    name: str  # declaration name (empty for preamble)
    signature: str  # first line / signature
    content: str  # full declaration body including signature
    line_start: int = 0
    line_end: int = 0


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

_EXT_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".pyw": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".c": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".swift": "swift",
    ".scala": "scala",
}


def detect_language(extension: str) -> str:
    """Map a file extension (with dot) to a language name."""
    return _EXT_TO_LANGUAGE.get(extension.lower(), "unknown")


# ---------------------------------------------------------------------------
# Brace counting with string/comment awareness
# ---------------------------------------------------------------------------


def _count_braces(line: str) -> int:
    """Count net brace depth change, ignoring braces inside strings and comments.

    Handles single-quoted, double-quoted, backtick (template) strings,
    and // line comments. Does NOT handle multi-line /* */ block comments
    across lines (would need stateful tracking).
    """
    depth = 0
    i = 0
    n = len(line)
    while i < n:
        c = line[i]
        if c == "/" and i + 1 < n and line[i + 1] == "/":
            break  # rest of line is a comment
        if c in ('"', "'", "`"):
            # Skip string literal
            quote = c
            i += 1
            while i < n and line[i] != quote:
                if line[i] == "\\" and i + 1 < n:
                    i += 1  # skip escaped char
                i += 1
            i += 1  # skip closing quote
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        i += 1
    return depth


# ---------------------------------------------------------------------------
# Python splitter
# ---------------------------------------------------------------------------

_PY_DECL = re.compile(r"^(async\s+def|def|class)\s+(\w+)", re.MULTILINE)
_PY_DECORATOR = re.compile(r"^@\w+")


def _split_python(lines: list[str]) -> list[CodeDeclaration]:
    """Split Python source at top-level (indent=0) def/class boundaries.

    Handles decorators: @-prefixed lines immediately preceding a def/class
    are included with the declaration they decorate.
    """
    declarations: list[CodeDeclaration] = []
    current_lines: list[str] = []
    current_kind = "preamble"
    current_name = ""
    current_sig = ""
    current_start = 0

    def _flush(end_line: int):
        text = "\n".join(current_lines).strip()
        if text:
            declarations.append(
                CodeDeclaration(
                    kind=current_kind,
                    name=current_name,
                    signature=current_sig,
                    content=text,
                    line_start=current_start,
                    line_end=end_line,
                )
            )

    for i, line in enumerate(lines):
        # Check for top-level declaration (no leading whitespace)
        if line and not line[0].isspace():
            m = _PY_DECL.match(line)
            if m:
                # Walk backwards to collect decorators from current_lines
                decorator_lines: list[str] = []
                while current_lines:
                    prev = current_lines[-1]
                    if prev and not prev[0].isspace() and _PY_DECORATOR.match(prev):
                        decorator_lines.insert(0, current_lines.pop())
                    else:
                        break

                _flush(i - 1 - len(decorator_lines))
                current_lines = decorator_lines + [line]
                kw = m.group(1)
                current_kind = "class" if kw == "class" else "function"
                current_name = m.group(2)
                current_sig = line.rstrip()
                current_start = i - len(decorator_lines)
                continue

        current_lines.append(line)

    _flush(len(lines) - 1)
    return declarations


# ---------------------------------------------------------------------------
# Curly-brace language splitter (TS/JS, Go, Rust, Java, C#, etc.)
# ---------------------------------------------------------------------------

_TS_DECL = re.compile(
    r"^(?:export\s+)?(?:default\s+)?(?:abstract\s+)?"
    r"(function\*?|class|interface|type|const|let|var|enum)\s+(\w+)",
    re.MULTILINE,
)

# Go: handle method receivers — func (s *Server) Name(...)
_GO_DECL = re.compile(
    r"^(func)\s+(?:\([^)]*\)\s+)?(\w+)" r"|^(type)\s+(\w+)" r"|^(var|const)\s+(\w+)",
    re.MULTILINE,
)

_RUST_DECL = re.compile(
    r"^(?:pub(?:\([^)]*\))?\s+)?(?:unsafe\s+)?(?:async\s+)?"
    r"(fn|struct|enum|trait|impl|mod|type|const|static|macro_rules!)\s*(\w+)",
    re.MULTILINE,
)

_JAVA_DECL = re.compile(
    r"^(?:(?:public|private|protected|static|final|abstract|synchronized|sealed|default)\s+)*"
    r"(class|interface|enum|record|@interface)\s+(\w+)",
    re.MULTILINE,
)

_LANG_PATTERNS: dict[str, re.Pattern] = {
    "typescript": _TS_DECL,
    "javascript": _TS_DECL,
    "go": _GO_DECL,
    "rust": _RUST_DECL,
    "java": _JAVA_DECL,
    "kotlin": _JAVA_DECL,
    "csharp": _JAVA_DECL,
    "c": _GO_DECL,
    "cpp": _GO_DECL,
    "scala": _JAVA_DECL,
    "swift": _TS_DECL,
    "ruby": re.compile(r"^(def|class|module)\s+(\w+)", re.MULTILINE),
}

# Map keyword to kind
_KIND_MAP = {
    "function": "function",
    "function*": "function",
    "def": "function",
    "class": "class",
    "interface": "interface",
    "type": "type",
    "const": "constant",
    "let": "variable",
    "var": "variable",
    "enum": "enum",
    "struct": "struct",
    "trait": "trait",
    "impl": "impl",
    "mod": "module",
    "static": "constant",
    "record": "class",
    "@interface": "interface",
    "func": "function",
    "fn": "function",
    "module": "module",
    "macro_rules!": "macro",
}


def _extract_match_groups(m: re.Match) -> tuple[str, str]:
    """Extract (keyword, name) from a regex match with alternation groups.

    Handles patterns like Go's where multiple alternatives each capture
    into different group pairs (1,2) or (3,4) or (5,6).
    """
    groups = m.groups()
    for j in range(0, len(groups), 2):
        if groups[j] is not None:
            kw = groups[j].strip()
            name = groups[j + 1] if j + 1 < len(groups) and groups[j + 1] else ""
            return kw, name
    return "", ""


def _split_braces(lines: list[str], pattern: re.Pattern) -> list[CodeDeclaration]:
    """Split a curly-brace language using brace counting for body boundaries.

    Uses string/comment-aware brace counting to avoid false boundaries
    from braces inside string literals or line comments.
    """
    declarations: list[CodeDeclaration] = []
    current_lines: list[str] = []
    current_kind = "preamble"
    current_name = ""
    current_sig = ""
    current_start = 0
    brace_depth = 0
    in_body = False

    def _flush(end_line: int):
        text = "\n".join(current_lines).strip()
        if text:
            declarations.append(
                CodeDeclaration(
                    kind=current_kind,
                    name=current_name,
                    signature=current_sig,
                    content=text,
                    line_start=current_start,
                    line_end=end_line,
                )
            )

    for i, line in enumerate(lines):
        # Only match declarations at the start of a line (top-level)
        if not in_body and line and not line[0].isspace():
            m = pattern.match(line)
            if m:
                # If we have accumulated preamble/previous decl, flush it
                if current_lines:
                    _flush(i - 1)

                current_lines = [line]
                kw, name = _extract_match_groups(m)
                current_kind = _KIND_MAP.get(kw, kw)
                current_name = name
                current_sig = line.rstrip()
                current_start = i

                # Start tracking braces
                brace_depth = _count_braces(line)
                in_body = brace_depth > 0
                continue

        current_lines.append(line)

        if in_body:
            brace_depth += _count_braces(line)
            if brace_depth <= 0:
                in_body = False
                _flush(i)
                current_lines = []
                current_kind = "preamble"
                current_name = ""
                current_sig = ""
                current_start = i + 1
                brace_depth = 0

    # Flush remainder
    _flush(len(lines) - 1)
    return declarations


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def split_code_declarations(source: str, language: str) -> list[CodeDeclaration]:
    """Split source code into top-level declarations.

    Args:
        source: The source code text.
        language: Language name (e.g. "python", "typescript", "go").

    Returns:
        List of CodeDeclaration objects. If no declarations are found,
        the entire source is returned as a single "module" declaration.
    """
    if not source.strip():
        return []

    lines = source.split("\n")

    if language == "python":
        decls = _split_python(lines)
    elif language in _LANG_PATTERNS:
        decls = _split_braces(lines, _LANG_PATTERNS[language])
    else:
        # Unknown language — return entire file as one block
        decls = [
            CodeDeclaration(
                kind="module",
                name="",
                signature="",
                content=source.strip(),
                line_start=0,
                line_end=len(lines) - 1,
            )
        ]

    # If we only got a single preamble, treat as module
    if len(decls) == 1 and decls[0].kind == "preamble":
        decls[0].kind = "module"

    # Filter empty declarations
    return [d for d in decls if d.content.strip()]
