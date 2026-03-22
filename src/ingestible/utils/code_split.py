"""Language-aware splitting of source code at top-level declaration boundaries.

Primary backend: **tree-sitter** (AST-based, handles all edge cases).
Fallback: regex heuristics when tree-sitter is not installed.

Install tree-sitter support with: ``pip install ingestible[code]``
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

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
    ".tsx": "tsx",
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
    ".cs": "c_sharp",
    ".rb": "ruby",
    ".swift": "swift",
    ".scala": "scala",
}


def detect_language(extension: str) -> str:
    """Map a file extension (with dot) to a language name."""
    return _EXT_TO_LANGUAGE.get(extension.lower(), "unknown")


# ============================================================================
# Tree-sitter backend (primary)
# ============================================================================

# Mapping from language name -> (module_name, function_name) for loading grammars.
_TS_GRAMMAR_MAP: dict[str, tuple[str, str]] = {
    "python": ("tree_sitter_python", "language"),
    "javascript": ("tree_sitter_javascript", "language"),
    "typescript": ("tree_sitter_typescript", "language_typescript"),
    "tsx": ("tree_sitter_typescript", "language_tsx"),
    "go": ("tree_sitter_go", "language"),
    "rust": ("tree_sitter_rust", "language"),
    "java": ("tree_sitter_java", "language"),
    "c": ("tree_sitter_c", "language"),
    "cpp": ("tree_sitter_cpp", "language"),
    "c_sharp": ("tree_sitter_c_sharp", "language"),
    "ruby": ("tree_sitter_ruby", "language"),
    "kotlin": ("tree_sitter_kotlin", "language"),
    "scala": ("tree_sitter_scala", "language"),
}

# Node types considered "top-level declarations" per language.
# These are the direct children of the root (module) node we extract.
_DECLARATION_TYPES: dict[str, set[str]] = {
    "python": {
        "function_definition",
        "class_definition",
        "decorated_definition",
    },
    "javascript": {
        "function_declaration",
        "class_declaration",
        "lexical_declaration",
        "variable_declaration",
        "export_statement",
    },
    "typescript": {
        "function_declaration",
        "class_declaration",
        "interface_declaration",
        "type_alias_declaration",
        "enum_declaration",
        "lexical_declaration",
        "variable_declaration",
        "export_statement",
    },
    "tsx": {
        "function_declaration",
        "class_declaration",
        "interface_declaration",
        "type_alias_declaration",
        "enum_declaration",
        "lexical_declaration",
        "variable_declaration",
        "export_statement",
    },
    "go": {
        "function_declaration",
        "method_declaration",
        "type_declaration",
        "var_declaration",
        "const_declaration",
    },
    "rust": {
        "function_item",
        "struct_item",
        "enum_item",
        "impl_item",
        "trait_item",
        "mod_item",
        "type_item",
        "const_item",
        "static_item",
        "macro_definition",
    },
    "java": {
        "class_declaration",
        "interface_declaration",
        "enum_declaration",
        "record_declaration",
        "annotation_type_declaration",
    },
    "c": {
        "function_definition",
        "struct_specifier",
        "enum_specifier",
        "type_definition",
        "declaration",
    },
    "cpp": {
        "function_definition",
        "class_specifier",
        "struct_specifier",
        "namespace_definition",
        "template_declaration",
        "enum_specifier",
        "type_definition",
        "declaration",
    },
    "c_sharp": {
        "class_declaration",
        "interface_declaration",
        "struct_declaration",
        "enum_declaration",
        "record_declaration",
        "namespace_declaration",
    },
    "ruby": {
        "method",
        "class",
        "module",
        "singleton_method",
    },
    "kotlin": {
        "function_declaration",
        "class_declaration",
        "object_declaration",
    },
    "scala": {
        "function_definition",
        "class_definition",
        "trait_definition",
        "object_definition",
    },
}

# Map AST node type -> human-readable kind
_NODE_KIND_MAP: dict[str, str] = {
    "function_definition": "function",
    "function_declaration": "function",
    "function_item": "function",
    "method_declaration": "method",
    "method": "function",
    "singleton_method": "function",
    "class_definition": "class",
    "class_declaration": "class",
    "class_specifier": "class",
    "class": "class",
    "interface_declaration": "interface",
    "interface": "interface",
    "type_alias_declaration": "type",
    "type_declaration": "type",
    "type_definition": "type",
    "type_item": "type",
    "struct_item": "struct",
    "struct_specifier": "struct",
    "struct_declaration": "struct",
    "enum_declaration": "enum",
    "enum_specifier": "enum",
    "enum_item": "enum",
    "impl_item": "impl",
    "trait_item": "trait",
    "trait_definition": "trait",
    "mod_item": "module",
    "module": "module",
    "namespace_definition": "namespace",
    "namespace_declaration": "namespace",
    "template_declaration": "template",
    "const_item": "constant",
    "const_declaration": "constant",
    "static_item": "constant",
    "var_declaration": "variable",
    "lexical_declaration": "variable",
    "variable_declaration": "variable",
    "declaration": "declaration",
    "macro_definition": "macro",
    "decorated_definition": "decorated",
    "export_statement": "export",
    "record_declaration": "class",
    "annotation_type_declaration": "interface",
    "object_declaration": "object",
    "object_definition": "object",
    "function_definition_scala": "function",
    "class_definition_scala": "class",
}


def _try_load_ts_parser(language: str):
    """Try to load a tree-sitter parser for the given language. Returns (Parser, Language) or None."""
    try:
        from tree_sitter import Language, Parser
    except ImportError:
        return None

    spec = _TS_GRAMMAR_MAP.get(language)
    if spec is None:
        return None

    module_name, func_name = spec
    try:
        import importlib

        mod = importlib.import_module(module_name)
        capsule = getattr(mod, func_name)()
        lang = Language(capsule)
        parser = Parser(lang)
        return parser
    except (ImportError, AttributeError, Exception) as e:
        logger.debug("tree-sitter grammar for %s not available: %s", language, e)
        return None


def _extract_name(node, source_bytes: bytes) -> str:
    """Extract the declaration name from an AST node."""
    # Try common field names
    for field in ("name", "declarator"):
        child = node.child_by_field_name(field)
        if child:
            text = source_bytes[child.start_byte : child.end_byte].decode("utf-8", errors="replace")
            # For declarators like "int foo()", extract just the identifier
            if "(" in text:
                text = text.split("(")[0].strip()
            if " " in text:
                text = text.split()[-1]
            return text

    # For decorated_definition, recurse into the inner definition
    if node.type == "decorated_definition":
        for child in node.children:
            if child.type in ("function_definition", "class_definition"):
                return _extract_name(child, source_bytes)

    # For export_statement, recurse into the exported declaration
    if node.type == "export_statement":
        for child in node.children:
            if child.is_named and child.type not in ("export", "default"):
                return _extract_name(child, source_bytes)

    # For lexical_declaration (const/let/var), get the first variable declarator
    if node.type in ("lexical_declaration", "variable_declaration"):
        for child in node.named_children:
            if child.type == "variable_declarator":
                return _extract_name(child, source_bytes)

    # For Go type_declaration / var_declaration / const_declaration, recurse into spec children
    if node.type in ("type_declaration", "var_declaration", "const_declaration"):
        for child in node.named_children:
            name = _extract_name(child, source_bytes)
            if name:
                return name

    # For Go type_spec, the name field is on the spec itself
    if node.type == "type_spec":
        name_node = node.child_by_field_name("name")
        if name_node:
            return source_bytes[name_node.start_byte : name_node.end_byte].decode(
                "utf-8", errors="replace"
            )

    return ""


def _ts_split(source: str, language: str, parser) -> list[CodeDeclaration]:
    """Split source code using tree-sitter AST."""
    source_bytes = source.encode("utf-8")
    tree = parser.parse(source_bytes)
    root = tree.root_node

    decl_types = _DECLARATION_TYPES.get(language, set())
    declarations: list[CodeDeclaration] = []
    preamble_parts: list[str] = []
    preamble_start = 0
    preamble_end = -1

    for child in root.children:
        if child.type in decl_types:
            # Flush accumulated preamble
            if preamble_parts:
                text = "\n".join(preamble_parts).strip()
                if text:
                    declarations.append(
                        CodeDeclaration(
                            kind="preamble",
                            name="",
                            signature="",
                            content=text,
                            line_start=preamble_start,
                            line_end=preamble_end,
                        )
                    )
                preamble_parts = []

            content = source_bytes[child.start_byte : child.end_byte].decode(
                "utf-8", errors="replace"
            )
            name = _extract_name(child, source_bytes)
            kind = _NODE_KIND_MAP.get(child.type, child.type)

            # For decorated_definition, resolve the inner kind
            if kind == "decorated" and child.type == "decorated_definition":
                for inner in child.children:
                    if inner.type in ("function_definition", "class_definition"):
                        kind = _NODE_KIND_MAP.get(inner.type, inner.type)
                        break

            # For export_statement, resolve the inner kind
            if kind == "export" and child.type == "export_statement":
                for inner in child.children:
                    if inner.is_named and inner.type in _NODE_KIND_MAP:
                        kind = _NODE_KIND_MAP.get(inner.type, inner.type)
                        break

            first_line = content.split("\n")[0].rstrip()

            declarations.append(
                CodeDeclaration(
                    kind=kind,
                    name=name,
                    signature=first_line,
                    content=content,
                    line_start=child.start_point[0],
                    line_end=child.end_point[0],
                )
            )
        else:
            # Non-declaration node (imports, comments, etc.) -> preamble
            text = source_bytes[child.start_byte : child.end_byte].decode("utf-8", errors="replace")
            if not preamble_parts:
                preamble_start = child.start_point[0]
            preamble_end = child.end_point[0]
            preamble_parts.append(text)

    # Flush trailing preamble
    if preamble_parts:
        text = "\n".join(preamble_parts).strip()
        if text:
            declarations.append(
                CodeDeclaration(
                    kind="preamble",
                    name="",
                    signature="",
                    content=text,
                    line_start=preamble_start,
                    line_end=preamble_end,
                )
            )

    return declarations


# ============================================================================
# Regex fallback backend
# ============================================================================

_PY_DECL = re.compile(r"^(async\s+def|def|class)\s+(\w+)", re.MULTILINE)
_PY_DECORATOR = re.compile(r"^@\w+")


def _count_braces(line: str) -> int:
    """Count net brace depth change, ignoring braces inside strings and // comments."""
    depth = 0
    i = 0
    n = len(line)
    while i < n:
        c = line[i]
        if c == "/" and i + 1 < n and line[i + 1] == "/":
            break
        if c in ('"', "'", "`"):
            quote = c
            i += 1
            while i < n and line[i] != quote:
                if line[i] == "\\" and i + 1 < n:
                    i += 1
                i += 1
            i += 1
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        i += 1
    return depth


def _split_python_regex(lines: list[str]) -> list[CodeDeclaration]:
    """Split Python source at top-level def/class boundaries with decorator support."""
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
        if line and not line[0].isspace():
            m = _PY_DECL.match(line)
            if m:
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


_TS_DECL_RE = re.compile(
    r"^(?:export\s+)?(?:default\s+)?(?:abstract\s+)?"
    r"(function\*?|class|interface|type|const|let|var|enum)\s+(\w+)",
    re.MULTILINE,
)
_GO_DECL_RE = re.compile(
    r"^(func)\s+(?:\([^)]*\)\s+)?(\w+)" r"|^(type)\s+(\w+)" r"|^(var|const)\s+(\w+)",
    re.MULTILINE,
)
_RUST_DECL_RE = re.compile(
    r"^(?:pub(?:\([^)]*\))?\s+)?(?:unsafe\s+)?(?:async\s+)?"
    r"(fn|struct|enum|trait|impl|mod|type|const|static|macro_rules!)\s*(\w+)",
    re.MULTILINE,
)
_JAVA_DECL_RE = re.compile(
    r"^(?:(?:public|private|protected|static|final|abstract|synchronized|sealed|default)\s+)*"
    r"(class|interface|enum|record|@interface)\s+(\w+)",
    re.MULTILINE,
)

_REGEX_LANG_PATTERNS: dict[str, re.Pattern] = {
    "typescript": _TS_DECL_RE,
    "javascript": _TS_DECL_RE,
    "tsx": _TS_DECL_RE,
    "go": _GO_DECL_RE,
    "rust": _RUST_DECL_RE,
    "java": _JAVA_DECL_RE,
    "kotlin": _JAVA_DECL_RE,
    "c_sharp": _JAVA_DECL_RE,
    "c": _GO_DECL_RE,
    "cpp": _GO_DECL_RE,
    "scala": _JAVA_DECL_RE,
    "swift": _TS_DECL_RE,
    "ruby": re.compile(r"^(def|class|module)\s+(\w+)", re.MULTILINE),
}

_REGEX_KIND_MAP = {
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


def _extract_regex_groups(m: re.Match) -> tuple[str, str]:
    """Extract (keyword, name) from a regex match with alternation groups."""
    groups = m.groups()
    for j in range(0, len(groups), 2):
        if groups[j] is not None:
            kw = groups[j].strip()
            name = groups[j + 1] if j + 1 < len(groups) and groups[j + 1] else ""
            return kw, name
    return "", ""


def _split_braces_regex(lines: list[str], pattern: re.Pattern) -> list[CodeDeclaration]:
    """Split a curly-brace language using string-aware brace counting."""
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
        if not in_body and line and not line[0].isspace():
            m = pattern.match(line)
            if m:
                if current_lines:
                    _flush(i - 1)
                current_lines = [line]
                kw, name = _extract_regex_groups(m)
                current_kind = _REGEX_KIND_MAP.get(kw, kw)
                current_name = name
                current_sig = line.rstrip()
                current_start = i
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

    _flush(len(lines) - 1)
    return declarations


def _split_regex(source: str, language: str) -> list[CodeDeclaration]:
    """Regex-based fallback splitter."""
    lines = source.split("\n")

    if language == "python":
        return _split_python_regex(lines)
    elif language in _REGEX_LANG_PATTERNS:
        return _split_braces_regex(lines, _REGEX_LANG_PATTERNS[language])
    else:
        return [
            CodeDeclaration(
                kind="module",
                name="",
                signature="",
                content=source.strip(),
                line_start=0,
                line_end=len(lines) - 1,
            )
        ]


# ============================================================================
# Public API
# ============================================================================

# Cache parsers to avoid re-loading grammars on every call
_parser_cache: dict[str, object] = {}


def split_code_declarations(source: str, language: str) -> list[CodeDeclaration]:
    """Split source code into top-level declarations.

    Uses tree-sitter (AST-based) when available, falls back to regex heuristics.
    Install tree-sitter support with: ``pip install ingestible[code]``

    Args:
        source: The source code text.
        language: Language name (e.g. "python", "typescript", "go").

    Returns:
        List of CodeDeclaration objects. If no declarations are found,
        the entire source is returned as a single "module" declaration.
    """
    if not source.strip():
        return []

    # Try tree-sitter first
    parser = _parser_cache.get(language)
    if parser is None and language not in _parser_cache:
        parser = _try_load_ts_parser(language)
        _parser_cache[language] = parser  # cache None too to avoid retrying

    if parser is not None:
        decls = _ts_split(source, language, parser)
    else:
        if language in _TS_GRAMMAR_MAP and language not in _parser_cache:
            logger.info(
                "tree-sitter not available for %s, using regex fallback. "
                "Install with: pip install ingestible[code]",
                language,
            )
        decls = _split_regex(source, language)

    # If we only got a single preamble, treat as module
    if len(decls) == 1 and decls[0].kind == "preamble":
        decls[0].kind = "module"

    # Filter empty declarations
    return [d for d in decls if d.content.strip()]
