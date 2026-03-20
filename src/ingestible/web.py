"""Web UI router — server-rendered HTML with htmx for interactivity."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ingestible.config import get_settings
from ingestible.models.chunks import ChunkSet
from ingestible.pipeline.orchestrator import ingest
from ingestible.pipeline.stage5_embedding import Embedder
from ingestible.pipeline.stage6_storage import (
    list_documents,
    load_chunks,
    load_document_meta,
    load_structure,
)
from ingestible.search.hybrid import load_searcher
from ingestible.utils.tokens import count_tokens

router = APIRouter(default_response_class=HTMLResponse)

_templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))

# Reuse the lazy singletons from api.py
_settings = None
_embedder = None


def _get_settings():
    global _settings
    if _settings is None:
        _settings = get_settings()
    return _settings


def _get_embedder():
    global _embedder
    if _embedder is None:
        _embedder = Embedder(_get_settings())
    return _embedder


def _check_upload_size(content: bytes, settings) -> None:
    """Raise 413 if *content* exceeds the configured upload limit."""
    if len(content) > settings.max_upload_bytes:
        max_mb = settings.max_upload_bytes / 1_000_000
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size: {max_mb:.0f}MB",
        )


def _l0_overview_text(l0) -> str:
    """Compose readable overview text from L0's structured fields."""
    parts = [l0.title]
    if l0.author:
        parts.append(f"Author: {l0.author}")
    if l0.domain:
        parts.append(f"Domain: {l0.domain}")
    if l0.document_type:
        parts.append(f"Type: {l0.document_type}")
    parts.append(
        f"Pages: {l0.total_pages} | Chapters: {l0.total_chapters} | "
        f"Sections: {l0.total_sections} | Passages: {l0.total_passages}"
    )
    if l0.executive_summary:
        parts.append(f"Summary: {l0.executive_summary}")
    if l0.toc_summary:
        parts.append(f"TOC: {l0.toc_summary}")
    if l0.key_concepts:
        parts.append(f"Key concepts: {', '.join(l0.key_concepts)}")
    return "\n".join(parts)


def _build_hierarchy(chunks: ChunkSet) -> list[dict]:
    """Build a nested hierarchy: L1 -> L2 -> L3 for the chunk tree template."""
    # Map L2 chunks by parent chapter
    l2_by_chapter: dict[str, list] = {}
    for l2 in chunks.l2_chunks:
        l2_by_chapter.setdefault(l2.parent_chapter_id, []).append(l2)

    # Map L3 chunks by parent section
    l3_by_section: dict[str, list] = {}
    for l3 in chunks.l3_chunks:
        l3_by_section.setdefault(l3.parent_section_id, []).append(l3)

    tree = []
    for l1 in chunks.l1_chunks:
        sections = []
        for l2 in l2_by_chapter.get(l1.chunk_id, []):
            passages = l3_by_section.get(l2.chunk_id, [])
            sections.append({"chunk": l2, "passages": passages})
        tree.append({"chunk": l1, "sections": sections})
    return tree


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/", name="dashboard")
async def dashboard(request: Request):
    settings = _get_settings()
    docs = list_documents(settings)
    return templates.TemplateResponse(
        "index.html", {"request": request, "documents": docs}
    )


@router.get("/doc/{doc_id}", name="document_detail")
async def document_detail(request: Request, doc_id: str):
    settings = _get_settings()
    doc_dir = settings.documents_dir / doc_id

    if not doc_dir.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    meta = load_document_meta(doc_dir)
    chunks = load_chunks(doc_dir)
    l0 = chunks.l0

    return templates.TemplateResponse(
        "document.html",
        {
            "request": request,
            "meta": meta,
            "l0": l0,
            "l0_text": _l0_overview_text(l0),
            "doc_id": doc_id,
            "total_chunks": len(chunks.l3_chunks),
            "chapters": [c.title for c in chunks.l1_chunks],
            "citations": chunks.citations,
        },
    )


@router.get("/doc/{doc_id}/chunk-tree", name="chunk_tree")
async def chunk_tree(request: Request, doc_id: str):
    settings = _get_settings()
    doc_dir = settings.documents_dir / doc_id

    if not doc_dir.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    chunks = load_chunks(doc_dir)
    tree = _build_hierarchy(chunks)

    return templates.TemplateResponse(
        "partials/chunk_tree.html",
        {"request": request, "tree": tree, "doc_id": doc_id},
    )


@router.get("/doc/{doc_id}/economics-panel", name="economics_panel")
async def economics_panel(request: Request, doc_id: str):
    settings = _get_settings()
    doc_dir = settings.documents_dir / doc_id

    if not doc_dir.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    chunks = load_chunks(doc_dir)

    full_tokens = sum(count_tokens(c.content) for c in chunks.l3_chunks)
    l0_tokens = count_tokens(_l0_overview_text(chunks.l0))
    avg_passage_tokens = 400
    avg_query_tokens = l0_tokens + (3 * avg_passage_tokens)
    savings = ((full_tokens - avg_query_tokens) / full_tokens * 100) if full_tokens > 0 else 0

    return templates.TemplateResponse(
        "partials/economics.html",
        {
            "request": request,
            "full_tokens": full_tokens,
            "l0_tokens": l0_tokens,
            "avg_query_tokens": avg_query_tokens,
            "savings": round(savings, 1),
        },
    )


@router.post("/doc/{doc_id}/search-results", name="search_results")
async def search_results(request: Request, doc_id: str):
    settings = _get_settings()
    doc_dir = settings.documents_dir / doc_id

    if not doc_dir.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    form = await request.form()
    query = form.get("query", "")
    if not query:
        return HTMLResponse("<p class='text-gray-500 text-sm'>Enter a query to search.</p>")

    chunks = load_chunks(doc_dir)
    embedder = _get_embedder()
    searcher = load_searcher(doc_dir, chunks, embedder, settings)
    response = searcher.search(str(query), n_results=5)

    return templates.TemplateResponse(
        "partials/search_results.html",
        {"request": request, "results": response.results, "query": query},
    )


@router.get("/search", name="corpus_search")
async def corpus_search_page(request: Request):
    return templates.TemplateResponse("search.html", {"request": request})


@router.post("/search-results", name="corpus_search_results")
async def corpus_search_results(request: Request):
    form = await request.form()
    query = form.get("query", "")
    if not query:
        return HTMLResponse("<p class='text-gray-500 text-sm'>Enter a query to search.</p>")

    from ingestible.search.corpus import CorpusSearcher

    settings = _get_settings()
    embedder = _get_embedder()
    searcher = CorpusSearcher(settings, embedder=embedder)
    response = searcher.search(str(query), n_results=10)

    return templates.TemplateResponse(
        "partials/corpus_search_results.html",
        {"request": request, "results": response.results, "query": query},
    )


@router.get("/upload", name="upload_form")
async def upload_form(request: Request):
    return templates.TemplateResponse("ingest.html", {"request": request})


@router.post("/upload", name="upload_submit")
async def upload_submit(
    request: Request,
    file: UploadFile = File(...),
    skip_enrichment: bool = Form(False),
):
    settings = _get_settings()

    suffix = Path(file.filename or "upload.pdf").suffix
    content = await file.read()
    _check_upload_size(content, settings)
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        doc_dir = ingest(
            tmp_path,
            settings,
            skip_enrichment=skip_enrichment,
            verbose=False,
        )
        meta = load_document_meta(doc_dir)
        doc_id = meta.get("doc_id", doc_dir.name)
        return RedirectResponse(url=f"/doc/{doc_id}", status_code=303)
    except Exception as e:
        return templates.TemplateResponse(
            "ingest.html",
            {"request": request, "error": str(e)},
            status_code=500,
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)
