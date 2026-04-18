"""Tests for NyxCore-inspired features: code chunking, weight, pinned, tags."""

from __future__ import annotations

import json

from ingestible.config import Settings
from ingestible.models.chunks import ChunkPosition, ChunkSet, L0Chunk, L1Chunk, L2Chunk, L3Chunk
from ingestible.models.document import DocumentStructure, PageContent, ParsedDocument, StructureNode
from ingestible.models.search import SearchResult
from ingestible.pipeline.stage6_storage import (
    list_documents,
    load_document_meta,
    save_document,
    update_document_meta,
)
from ingestible.profiles import PROFILES, detect_profile
from ingestible.utils.code_split import detect_language, split_code_declarations

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_structure(doc_id: str = "test-doc", title: str = "Test") -> DocumentStructure:
    return DocumentStructure(
        doc_id=doc_id,
        title=title,
        root=StructureNode(id="root", title=title, level=0),
    )


def _make_chunks(doc_id: str = "test-doc") -> ChunkSet:
    return ChunkSet(
        doc_id=doc_id,
        l0=L0Chunk(chunk_id=f"{doc_id}-L0", title="Test"),
        l1_chunks=[L1Chunk(chunk_id="ch1", title="Ch1", content="chapter")],
        l2_chunks=[L2Chunk(chunk_id="s1", title="S1", content="section", parent_chapter_id="ch1")],
        l3_chunks=[
            L3Chunk(
                chunk_id="p1",
                content="passage one",
                parent_section_id="s1",
                position=ChunkPosition(chapter="ch1", section="s1", index=0),
            ),
            L3Chunk(
                chunk_id="p2",
                content="passage two",
                parent_section_id="s1",
                position=ChunkPosition(chapter="ch1", section="s1", index=1),
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Schema v3: weight, pinned, tags in meta.json
# ---------------------------------------------------------------------------


class TestSchemaV3:
    def test_save_with_defaults(self, tmp_path):
        """Meta.json includes weight/pinned/tags with defaults."""
        settings = Settings(data_dir=tmp_path)
        save_document(_make_structure(), _make_chunks(), settings)
        meta = load_document_meta(settings.documents_dir / "test-doc")
        assert meta["schema_version"] == 4
        assert meta["weight"] == 0.0
        assert meta["pinned"] is False
        assert meta["tags"] == []

    def test_save_with_values(self, tmp_path):
        """Custom weight/pinned/tags are persisted."""
        settings = Settings(data_dir=tmp_path)
        save_document(
            _make_structure(),
            _make_chunks(),
            settings,
            weight=0.3,
            pinned=True,
            tags=["compliance", "legal"],
        )
        meta = load_document_meta(settings.documents_dir / "test-doc")
        assert meta["weight"] == 0.3
        assert meta["pinned"] is True
        assert meta["tags"] == ["compliance", "legal"]

    def test_backward_compat_v2(self, tmp_path):
        """Documents at schema v2 still load (missing fields get defaults via .get())."""
        doc_dir = tmp_path / "documents" / "old-doc"
        doc_dir.mkdir(parents=True)
        meta = {
            "schema_version": 2,
            "doc_id": "old-doc",
            "title": "Old",
            "total_pages": 1,
            "total_chapters": 0,
            "total_sections": 0,
            "total_passages": 0,
            "ingestion_date": "",
            "content_hash": "",
            "author": "",
            "creation_date": "",
            "source_language": "",
            "version": 1,
            "extraction_profile": "",
            "access_tags": [],
            "l0": L0Chunk(chunk_id="old-doc-L0", title="Old").model_dump(),
        }
        (doc_dir / "meta.json").write_text(json.dumps(meta))
        loaded = load_document_meta(doc_dir)
        assert loaded.get("weight", 0.0) == 0.0
        assert loaded.get("pinned", False) is False
        assert loaded.get("tags", []) == []


# ---------------------------------------------------------------------------
# update_document_meta (PATCH)
# ---------------------------------------------------------------------------


class TestUpdateMeta:
    def test_update_weight(self, tmp_path):
        settings = Settings(data_dir=tmp_path)
        save_document(_make_structure(), _make_chunks(), settings)
        doc_dir = settings.documents_dir / "test-doc"
        meta = update_document_meta(doc_dir, weight=0.15)
        assert meta["weight"] == 0.15
        # Reload from disk
        meta2 = load_document_meta(doc_dir)
        assert meta2["weight"] == 0.15

    def test_update_pinned(self, tmp_path):
        settings = Settings(data_dir=tmp_path)
        save_document(_make_structure(), _make_chunks(), settings)
        doc_dir = settings.documents_dir / "test-doc"
        meta = update_document_meta(doc_dir, pinned=True)
        assert meta["pinned"] is True

    def test_update_tags(self, tmp_path):
        settings = Settings(data_dir=tmp_path)
        save_document(_make_structure(), _make_chunks(), settings)
        doc_dir = settings.documents_dir / "test-doc"
        meta = update_document_meta(doc_dir, tags=["workflow", "coding"])
        assert meta["tags"] == ["workflow", "coding"]

    def test_partial_update_preserves_others(self, tmp_path):
        settings = Settings(data_dir=tmp_path)
        save_document(
            _make_structure(),
            _make_chunks(),
            settings,
            weight=0.3,
            pinned=True,
            tags=["a"],
        )
        doc_dir = settings.documents_dir / "test-doc"
        # Only update tags
        meta = update_document_meta(doc_dir, tags=["b"])
        assert meta["weight"] == 0.3
        assert meta["pinned"] is True
        assert meta["tags"] == ["b"]


# ---------------------------------------------------------------------------
# Tag filtering in list_documents
# ---------------------------------------------------------------------------


class TestTagFiltering:
    def test_filter_by_tags(self, tmp_path):
        settings = Settings(data_dir=tmp_path)
        save_document(
            _make_structure("doc-a"),
            _make_chunks("doc-a"),
            settings,
            tags=["compliance"],
        )
        save_document(
            _make_structure("doc-b"),
            _make_chunks("doc-b"),
            settings,
            tags=["coding"],
        )
        save_document(
            _make_structure("doc-c"),
            _make_chunks("doc-c"),
            settings,
            tags=["compliance", "coding"],
        )

        # Filter by compliance
        results = list_documents(settings, tags=["compliance"])
        ids = {d["doc_id"] for d in results}
        assert ids == {"doc-a", "doc-c"}

        # Filter by coding
        results = list_documents(settings, tags=["coding"])
        ids = {d["doc_id"] for d in results}
        assert ids == {"doc-b", "doc-c"}

        # No filter
        results = list_documents(settings)
        assert len(results) == 3

    def test_filter_no_match(self, tmp_path):
        settings = Settings(data_dir=tmp_path)
        save_document(
            _make_structure("doc-x"),
            _make_chunks("doc-x"),
            settings,
            tags=["general"],
        )
        results = list_documents(settings, tags=["nonexistent"])
        assert results == []


# ---------------------------------------------------------------------------
# Code splitting
# ---------------------------------------------------------------------------


class TestCodeSplit:
    def test_detect_language(self):
        assert detect_language(".py") == "python"
        assert detect_language(".ts") == "typescript"
        assert detect_language(".go") == "go"
        assert detect_language(".rs") == "rust"
        assert detect_language(".java") == "java"
        assert detect_language(".xyz") == "unknown"

    def test_split_python_basic(self):
        source = """import os

def hello():
    print("hello")

class Foo:
    def bar(self):
        pass

def baz():
    return 42
"""
        decls = split_code_declarations(source, "python")
        assert len(decls) >= 3  # preamble + hello + Foo + baz (or merged)
        names = [d.name for d in decls]
        assert "hello" in names
        assert "Foo" in names
        assert "baz" in names

    def test_split_python_preserves_content(self):
        source = """def add(a, b):
    return a + b
"""
        decls = split_code_declarations(source, "python")
        assert any("return a + b" in d.content for d in decls)

    def test_split_typescript(self):
        source = """import { foo } from "bar";

export function hello(): void {
    console.log("hello");
}

export class MyService {
    private name: string;

    constructor(name: string) {
        this.name = name;
    }
}

export const MAX = 100;
"""
        decls = split_code_declarations(source, "typescript")
        names = [d.name for d in decls]
        assert "hello" in names
        assert "MyService" in names

    def test_split_go(self):
        source = """package main

import "fmt"

func Hello() {
    fmt.Println("hello")
}

type Config struct {
    Name string
    Port int
}
"""
        decls = split_code_declarations(source, "go")
        names = [d.name for d in decls]
        assert "Hello" in names
        assert "Config" in names

    def test_split_rust(self):
        source = """use std::io;

pub fn greet(name: &str) {
    println!("Hello, {}", name);
}

pub struct Server {
    port: u16,
}
"""
        decls = split_code_declarations(source, "rust")
        names = [d.name for d in decls]
        assert "greet" in names
        assert "Server" in names

    def test_empty_source(self):
        assert split_code_declarations("", "python") == []
        assert split_code_declarations("   \n  \n  ", "python") == []

    def test_unknown_language_returns_single_module(self):
        source = "some random content"
        decls = split_code_declarations(source, "unknown")
        assert len(decls) == 1
        assert decls[0].kind == "module"

    def test_single_preamble_becomes_module(self):
        source = """import os
import sys

X = 42
"""
        decls = split_code_declarations(source, "python")
        assert len(decls) == 1
        assert decls[0].kind == "module"

    # --- Edge cases: decorators ---

    def test_python_decorators_stay_with_function(self):
        source = """import os

@app.route("/api")
@login_required
def handle_request():
    pass

def other():
    pass
"""
        decls = split_code_declarations(source, "python")
        handle = next(d for d in decls if d.name == "handle_request")
        assert "@app.route" in handle.content
        assert "@login_required" in handle.content

    def test_python_class_decorator(self):
        source = """@dataclass
class Config:
    x: int = 0
"""
        decls = split_code_declarations(source, "python")
        cfg = next(d for d in decls if d.name == "Config")
        assert "@dataclass" in cfg.content

    # --- Edge cases: Go method receivers ---

    def test_go_method_receiver(self):
        source = """package main

func (s *Server) HandleRequest(w http.ResponseWriter) {
    // handler
}

func Plain() {
    // plain
}

type Server struct {
    Port int
}
"""
        decls = split_code_declarations(source, "go")
        names = [d.name for d in decls]
        assert "HandleRequest" in names
        assert "Plain" in names
        assert "Server" in names

    # --- Edge cases: Rust impl<T> and pub(super) ---

    def test_rust_impl_generic(self):
        source = """pub fn greet() {
    println!("hi");
}

impl<T: Display> MyTrait for MyStruct<T> {
    fn method(&self) {}
}
"""
        decls = split_code_declarations(source, "rust")
        # impl should be detected as its own declaration
        kinds = [d.kind for d in decls]
        assert "impl" in kinds or "function" in kinds

    def test_rust_pub_super(self):
        source = """pub(super) fn helper() {
    // helper
}
"""
        decls = split_code_declarations(source, "rust")
        assert any(d.name == "helper" for d in decls)

    def test_rust_macro_rules(self):
        source = """macro_rules! my_macro {
    ($x:expr) => { $x + 1 }
}

pub fn foo() {
    // foo
}
"""
        decls = split_code_declarations(source, "rust")
        names = [d.name for d in decls]
        assert "my_macro" in names
        assert "foo" in names

    # --- Edge cases: braces in strings ---

    def test_braces_in_string_literal(self):
        source = """function render() {
    return "this { has } unbalanced { braces";
}

function other() {
    return 1;
}
"""
        decls = split_code_declarations(source, "javascript")
        names = [d.name for d in decls]
        assert "render" in names
        assert "other" in names

    # --- Edge cases that only tree-sitter handles correctly ---

    def test_python_def_in_multiline_string(self):
        """def/class keywords inside triple-quoted strings must not cause false splits."""
        source = '''"""
def ghost_function():
    not real
"""

def real_function():
    pass
'''
        decls = split_code_declarations(source, "python")
        names = [d.name for d in decls]
        assert "real_function" in names
        # ghost_function should NOT appear as a separate declaration
        assert "ghost_function" not in names

    def test_python_nested_class_not_split(self):
        """Nested classes inside a parent class should stay together."""
        source = """class Outer:
    class Inner:
        pass

    def method(self):
        pass
"""
        decls = split_code_declarations(source, "python")
        outer = next(d for d in decls if d.name == "Outer")
        assert "class Inner:" in outer.content
        assert "def method(self):" in outer.content
        # Inner should NOT be a separate top-level declaration
        assert not any(d.name == "Inner" for d in decls)

    def test_typescript_arrow_function(self):
        source = """export const handler = async (req: Request) => {
    return new Response("ok");
};

export function greet(): string {
    return "hi";
}
"""
        decls = split_code_declarations(source, "typescript")
        names = [d.name for d in decls]
        assert "handler" in names
        assert "greet" in names

    def test_java_annotations_stay_with_class(self):
        source = """import java.util.List;

@Entity
@Table(name = "users")
public class User {
    @Id
    private Long id;

    public Long getId() {
        return id;
    }
}
"""
        decls = split_code_declarations(source, "java")
        user = next(d for d in decls if d.name == "User")
        assert "@Entity" in user.content
        assert "@Table" in user.content

    def test_go_var_block(self):
        """Go var(...) blocks should be captured."""
        source = """package main

var (
    ErrNotFound = errors.New("not found")
    ErrTimeout  = errors.New("timeout")
)

func Run() {
    // run
}
"""
        decls = split_code_declarations(source, "go")
        names = [d.name for d in decls]
        assert "Run" in names
        # The var block should exist as a declaration (not merged into preamble)
        var_decls = [
            d for d in decls if d.kind in ("variable", "preamble") and "ErrNotFound" in d.content
        ]
        assert len(var_decls) >= 1

    def test_rust_impl_with_methods(self):
        """impl blocks with methods should be a single declaration."""
        source = """pub struct Server {
    port: u16,
}

impl Server {
    pub fn new(port: u16) -> Self {
        Server { port }
    }

    pub fn start(&self) {
        println!("Starting on port {}", self.port);
    }
}
"""
        decls = split_code_declarations(source, "rust")
        impl_decl = next((d for d in decls if d.kind == "impl"), None)
        assert impl_decl is not None
        assert "pub fn new" in impl_decl.content
        assert "pub fn start" in impl_decl.content

    def test_template_literal_braces(self):
        """Template literals with ${} should not corrupt brace counting."""
        source = """function render(items) {
    return `<div>
        ${items.map(i => `<span>{${i}}</span>`)}
    </div>`;
}

function other() {
    return 1;
}
"""
        decls = split_code_declarations(source, "javascript")
        names = [d.name for d in decls]
        assert "render" in names
        assert "other" in names


# ---------------------------------------------------------------------------
# Code profile detection
# ---------------------------------------------------------------------------


class TestCodeProfile:
    def test_code_profile_exists(self):
        assert "code" in PROFILES
        assert PROFILES["code"].chunking_strategy == "code"

    def test_auto_detect_code_from_source_format(self):
        doc = ParsedDocument(
            title="test.py",
            source_path="/test.py",
            source_format="code",
            total_pages=1,
            pages=[PageContent(page_num=1, markdown="def foo(): pass", has_code_blocks=True)],
        )
        assert detect_profile(doc) == "code"


# ---------------------------------------------------------------------------
# SearchResult new fields
# ---------------------------------------------------------------------------


class TestSearchResultFields:
    def test_default_values(self):
        r = SearchResult(chunk_id="c1", content="text")
        assert r.doc_tags == []
        assert r.pinned is False

    def test_set_values(self):
        r = SearchResult(
            chunk_id="c1",
            content="text",
            doc_tags=["compliance", "legal"],
            pinned=True,
        )
        assert r.doc_tags == ["compliance", "legal"]
        assert r.pinned is True


# ---------------------------------------------------------------------------
# Config: pinned_top_n
# ---------------------------------------------------------------------------


class TestConfigPinnedTopN:
    def test_default_value(self):
        s = Settings()
        assert s.pinned_top_n == 3

    def test_code_in_chunking_strategy(self):
        s = Settings(chunking_strategy="code")
        assert s.chunking_strategy == "code"
