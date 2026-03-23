"""CLI entry point: ingest, list, search."""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="ingest",
        description="Document ingestion pipeline — transforms documents into a queryable knowledge store",
    )
    sub = parser.add_subparsers(dest="command")

    # --- ingest ---
    p_ingest = sub.add_parser(
        "ingest", help="Ingest a document or directory into the knowledge store"
    )
    p_ingest.add_argument("file_path", help="Path to document, directory, or glob pattern")
    p_ingest.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    p_ingest.add_argument(
        "--skip-enrichment",
        action="store_true",
        help="Skip LLM enrichment (saves API cost, still builds search indexes)",
    )
    p_ingest.add_argument(
        "--data-dir", default=None, help="Override data directory (default: data/)"
    )
    p_ingest.add_argument(
        "--chunking",
        choices=["paragraph", "semantic", "recursive", "docling", "code"],
        default=None,
        help="Chunking strategy (default: from config)",
    )
    p_ingest.add_argument(
        "--force",
        action="store_true",
        help="Force re-ingestion even if document is unchanged",
    )
    p_ingest.add_argument(
        "--parallel",
        type=int,
        default=1,
        metavar="N",
        help="Number of parallel workers for batch ingestion (default: 1)",
    )
    p_ingest.add_argument(
        "--no-recursive",
        action="store_true",
        help="Don't recurse into subdirectories",
    )
    p_ingest.add_argument(
        "--no-checkpoint",
        action="store_true",
        help="Disable pipeline checkpoint/resume",
    )
    p_ingest.add_argument(
        "--profile",
        choices=["auto", "paper", "article", "documentation", "general", "code"],
        default=None,
        help="Extraction profile (default: auto-detect from content)",
    )
    p_ingest.add_argument(
        "--access-tags",
        default=None,
        help="Comma-separated access tags for the document (e.g. team-a,confidential)",
    )
    p_ingest.add_argument(
        "--weight",
        type=float,
        default=0.0,
        help="Document weight/authority boost for search scoring (e.g. 0.3 for mandatory, 0.15 for guideline)",
    )
    p_ingest.add_argument(
        "--pinned",
        action="store_true",
        help="Pin document: top chunks always included in corpus search results",
    )
    p_ingest.add_argument(
        "--tags",
        default=None,
        help="Comma-separated category tags for filtering (e.g. compliance,coding,style)",
    )

    # --- parse (parse-only, no storage) ---
    p_parse = sub.add_parser(
        "parse",
        help="Parse and chunk a document without storing. Outputs JSONL to stdout.",
    )
    p_parse.add_argument("file_path", help="Path to document or directory")
    p_parse.add_argument(
        "--format",
        choices=["jsonl", "json"],
        default="jsonl",
        help="Output format (default: jsonl)",
    )
    p_parse.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output file (default: stdout)",
    )
    p_parse.add_argument(
        "--chunking",
        choices=["paragraph", "semantic", "recursive", "docling", "code"],
        default=None,
        help="Chunking strategy (default: from config)",
    )
    p_parse.add_argument(
        "--profile",
        choices=["auto", "paper", "article", "documentation", "general", "code"],
        default=None,
        help="Extraction profile (default: auto-detect)",
    )
    p_parse.add_argument("-v", "--verbose", action="store_true")

    # --- list ---
    sub.add_parser("list", help="List all ingested documents")

    # --- search ---
    p_search = sub.add_parser("search", help="Search within a document")
    p_search.add_argument("doc_id", help="Document ID (from 'ingest list')")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument(
        "-n", "--results", type=int, default=5, help="Number of results (default: 5)"
    )
    p_search.add_argument(
        "--hyde",
        action="store_true",
        help="Use HyDE (Hypothetical Document Embeddings) query expansion",
    )
    p_search.add_argument(
        "--auto-merge", action="store_true", help="Auto-merge L3 results into parent L2/L1 chunks"
    )
    p_search.add_argument(
        "--kg", action="store_true", help="Boost results using knowledge graph relationships"
    )

    # --- corpus-search ---
    p_csearch = sub.add_parser("corpus-search", help="Search across all ingested documents")
    p_csearch.add_argument("query", help="Search query")
    p_csearch.add_argument(
        "-n", "--results", type=int, default=10, help="Number of results (default: 10)"
    )
    p_csearch.add_argument(
        "--doc-ids", nargs="*", default=None, help="Limit to specific document IDs"
    )
    p_csearch.add_argument(
        "--tags",
        default=None,
        help="Comma-separated tags to filter documents (e.g. compliance,style)",
    )
    p_csearch.add_argument("--hyde", action="store_true", help="Use HyDE query expansion")
    p_csearch.add_argument(
        "--auto-merge", action="store_true", help="Auto-merge L3 results into parent L2/L1 chunks"
    )
    p_csearch.add_argument(
        "--kg", action="store_true", help="Boost results using knowledge graph relationships"
    )

    # --- enrich ---
    p_enrich = sub.add_parser("enrich", help="Re-enrich a document without re-parsing")
    p_enrich.add_argument("doc_id", help="Document ID to re-enrich")
    p_enrich.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    # --- versions ---
    p_versions = sub.add_parser("versions", help="List archived versions of a document")
    p_versions.add_argument("doc_id", help="Document ID")

    # --- export ---
    p_exp = sub.add_parser("export", help="Export document to portable format")
    p_exp.add_argument("doc_id", help="Document ID to export")
    p_exp.add_argument(
        "--format",
        choices=["jsonl", "parquet", "llamaindex", "langchain"],
        required=True,
        help="Export format",
    )
    p_exp.add_argument("-o", "--output", required=True, help="Output file path")

    # --- config ---
    sub.add_parser("config", help="Show effective configuration (all sources merged)")

    # --- serve ---
    p_serve = sub.add_parser("serve", help="Start the API server and web UI")
    p_serve.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    p_serve.add_argument("--port", type=int, default=8081, help="Port (default: 8081)")
    p_serve.add_argument(
        "--reload", action="store_true", help="Auto-reload on code changes (dev mode)"
    )

    # --- watch ---
    p_watch = sub.add_parser("watch", help="Watch a directory and auto-ingest on changes")
    p_watch.add_argument("dir", help="Directory to watch")
    p_watch.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    p_watch.add_argument(
        "--skip-enrichment",
        action="store_true",
        help="Skip LLM enrichment for auto-ingested documents",
    )
    p_watch.add_argument(
        "--data-dir", default=None, help="Override data directory (default: data/)"
    )
    p_watch.add_argument(
        "--cv-push",
        action="store_true",
        help="Auto-push to CognitiveVault after each batch",
    )
    p_watch.add_argument(
        "--cv-url", default=None, help="CognitiveVault base URL (or set CV_URL env var)"
    )
    p_watch.add_argument(
        "--cv-api-key", default=None, help="CognitiveVault API key (or set CV_API_KEY env var)"
    )
    p_watch.add_argument(
        "--cv-vault-id", default=None, help="Target vault ID (or set CV_VAULT_ID env var)"
    )

    # --- mcp ---
    sub.add_parser("mcp", help="Start MCP server for AI agent integration")

    # --- eval ---
    eval_parser = sub.add_parser("eval", help="Evaluate retrieval quality")
    eval_parser.add_argument("doc_id", help="Document ID to evaluate")
    eval_parser.add_argument("--queries", help="Path to JSONL file with Q&A pairs (optional)")
    eval_parser.add_argument(
        "-k", type=int, default=5, help="Number of results per query (default: 5)"
    )
    eval_parser.add_argument(
        "--compare", action="store_true", help="Compare hybrid vs vector-only vs BM25-only"
    )
    eval_parser.add_argument("--output", "-o", help="Save detailed results to JSON file")
    eval_parser.add_argument(
        "--judge",
        action="store_true",
        help="Use LLM-as-judge scoring (faithfulness, relevance, completeness)",
    )

    # --- audit ---
    audit_parser = sub.add_parser("audit", help="View search audit trail")
    audit_parser.add_argument("-n", type=int, default=20, help="Number of recent entries")
    audit_parser.add_argument("--query", help="Filter by query substring")

    # --- cleanup ---
    cleanup_parser = sub.add_parser("cleanup", help="Clean stale checkpoints and temp files")
    cleanup_parser.add_argument(
        "--max-age", type=int, default=24, help="Max age in hours (default: 24)"
    )

    # --- export-cv ---
    p_export = sub.add_parser("export-cv", help="Export documents to CognitiveVault")
    p_export.add_argument(
        "doc_ids",
        nargs="*",
        help="Document IDs to export (default: all)",
    )
    p_export.add_argument(
        "--cv-url",
        default=None,
        help="CognitiveVault base URL (or set CV_URL env var)",
    )
    p_export.add_argument(
        "--cv-api-key",
        default=None,
        help="CognitiveVault API key (or set CV_API_KEY env var)",
    )
    p_export.add_argument(
        "--cv-vault-id",
        default=None,
        help="Target vault ID (or set CV_VAULT_ID env var)",
    )
    p_export.add_argument(
        "--delete-removed",
        action="store_true",
        help="Delete CV entries whose sourcePaths are not in this export",
    )

    args = parser.parse_args(argv)

    from ingestible.logging import setup_logging

    setup_logging(json_output=False, level="INFO")  # Console output for CLI

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "ingest":
        _cmd_ingest(args)
    elif args.command == "parse":
        _cmd_parse(args)
    elif args.command == "list":
        _cmd_list()
    elif args.command == "search":
        _cmd_search(args)
    elif args.command == "corpus-search":
        _cmd_corpus_search(args)
    elif args.command == "enrich":
        _cmd_enrich(args)
    elif args.command == "versions":
        _cmd_versions(args)
    elif args.command == "export":
        _cmd_export(args)
    elif args.command == "config":
        _cmd_config()
    elif args.command == "serve":
        import uvicorn

        uvicorn.run(
            "ingestible.api:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
        )
    elif args.command == "watch":
        _cmd_watch(args)
    elif args.command == "eval":
        from pathlib import Path

        from ingestible.config import get_settings
        from ingestible.eval import compare_strategies, evaluate_document, load_eval_queries

        settings = get_settings()

        queries = None
        if args.queries:
            queries = load_eval_queries(Path(args.queries))
            print(f"Loaded {len(queries)} eval queries from {args.queries}")

        if args.judge:
            import asyncio

            from ingestible.eval_llm_judge import evaluate_with_judge

            report = asyncio.run(
                evaluate_with_judge(
                    args.doc_id,
                    settings,
                    queries,
                    k=args.k,
                    concurrency=settings.llm_judge_concurrency,
                )
            )
            print(report.summary())

            if args.output:
                import json

                Path(args.output).write_text(json.dumps(report.to_dict(), indent=2))
                print(f"\nDetailed results saved to {args.output}")
        elif args.compare:
            reports = compare_strategies(args.doc_id, settings, queries, k=args.k)
            for name, report in reports.items():
                print(f"\n--- {name} ---")
                print(report.summary())
        else:
            report = evaluate_document(args.doc_id, settings, queries, k=args.k)
            print(report.summary())

            if args.output:
                import json

                output = report.to_dict()
                output["results"] = [
                    {
                        "query": r.query,
                        "hit": r.hit,
                        "reciprocal_rank": round(r.reciprocal_rank, 4),
                        "precision": round(r.precision_at_k, 4),
                        "recall": round(r.recall_at_k, 4),
                        "retrieved": r.retrieved_chunk_ids,
                        "expected": r.expected_chunk_ids,
                    }
                    for r in report.results
                ]
                Path(args.output).write_text(json.dumps(output, indent=2))
                print(f"\nDetailed results saved to {args.output}")
    elif args.command == "audit":
        import json
        import time

        from ingestible.config import get_settings

        settings = get_settings()
        audit_path = settings.data_dir / "audit.jsonl"
        if not audit_path.exists():
            print("No audit log found. Enable with INGEST_AUDIT_ENABLED=true")
        else:
            lines = audit_path.read_text().strip().split("\n")
            entries = [json.loads(ln) for ln in lines if ln.strip()]
            if args.query:
                entries = [e for e in entries if args.query.lower() in e.get("query", "").lower()]
            for e in entries[-args.n :]:
                ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e["timestamp"]))
                print(
                    f'[{ts}] query="{e["query"]}" doc={e.get("doc_id", "corpus")} results={len(e["retrieved_chunk_ids"])} latency={e.get("latency_ms", 0):.0f}ms'
                )
    elif args.command == "cleanup":
        from ingestible.config import get_settings
        from ingestible.pipeline.cleanup import cleanup_stale

        settings = get_settings()
        counts = cleanup_stale(settings, max_age_hours=args.max_age)
        print(f"Cleaned: {counts['checkpoints']} checkpoints, {counts['temp_files']} temp files")
    elif args.command == "mcp":
        try:
            from ingestible.mcp_server import mcp

            mcp.run()
        except ImportError:
            print("MCP server requires the mcp extra. Install with: pip install ingestible[mcp]")
            sys.exit(1)
    elif args.command == "export-cv":
        _cmd_export_cv(args)


def _is_url(file_path: str) -> bool:
    """Detect if input is an HTTP(S) URL."""
    return file_path.startswith("http://") or file_path.startswith("https://")


def _is_batch_input(file_path: str) -> bool:
    """Detect if input is a directory or glob pattern (batch mode)."""
    from pathlib import Path

    if _is_url(file_path):
        return False
    if "*" in file_path or "?" in file_path:
        return True
    p = Path(file_path)
    return p.is_dir()


def _cmd_ingest(args: argparse.Namespace) -> None:
    from ingestible.config import get_settings

    overrides = {}
    if args.data_dir:
        from pathlib import Path

        overrides["data_dir"] = Path(args.data_dir)
    if args.chunking:
        overrides["chunking_strategy"] = args.chunking
    if args.no_checkpoint:
        overrides["checkpoint_enabled"] = False
    if args.profile:
        overrides["extraction_profile"] = args.profile

    settings = get_settings(**overrides)

    parsed_access_tags = None
    if args.access_tags:
        parsed_access_tags = [t.strip() for t in args.access_tags.split(",") if t.strip()]

    parsed_tags = None
    if args.tags:
        parsed_tags = [t.strip() for t in args.tags.split(",") if t.strip()]

    if _is_batch_input(args.file_path):
        from ingestible.pipeline.batch import ingest_batch

        if args.verbose:
            import logging

            logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

        report = ingest_batch(
            args.file_path,
            settings,
            skip_enrichment=args.skip_enrichment,
            force=args.force,
            parallel=args.parallel,
            recursive=not args.no_recursive,
        )
        print(
            f"\nBatch complete: {report.succeeded} succeeded, {report.failed} failed ({report.elapsed_seconds}s)"
        )
        for r in report.results:
            status = "OK" if not r.error else f"FAILED: {r.error}"
            print(f"  {r.path.name:40s}  {status}")
    else:
        from ingestible.pipeline.orchestrator import ingest

        callback = None
        if args.verbose:
            from ingestible.pipeline.progress import CLIProgress

            callback = CLIProgress()

        doc_dir = ingest(
            args.file_path,
            settings,
            skip_enrichment=args.skip_enrichment,
            verbose=args.verbose,
            force=args.force,
            progress_callback=callback,
            access_tags=parsed_access_tags,
            weight=args.weight,
            pinned=args.pinned,
            tags=parsed_tags,
        )
        print(f"Ingested → {doc_dir}")


def _cmd_parse(args: argparse.Namespace) -> None:
    """Parse and chunk document(s) without storing. Output JSONL to stdout or file."""
    import json
    import logging
    import tempfile
    from pathlib import Path

    from ingestible.config import get_settings
    from ingestible.pipeline.orchestrator import generate_doc_id
    from ingestible.pipeline.stage1_parsing import parse_document
    from ingestible.pipeline.stage1b_clean import clean_document
    from ingestible.pipeline.stage2_structure import detect_structure
    from ingestible.pipeline.stage3_chunking import chunk_document
    from ingestible.pipeline.stage3b_validation import validate_chunks
    from ingestible.profiles import PROFILES, detect_profile

    if args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(message)s")

    overrides = {}
    if args.chunking:
        overrides["chunking_strategy"] = args.chunking
    if args.profile:
        overrides["extraction_profile"] = args.profile
    # Use a temp data dir — nothing is persisted
    overrides["data_dir"] = Path(tempfile.mkdtemp(prefix="ingest-parse-"))
    settings = get_settings(**overrides)

    file_path = Path(args.file_path).resolve()

    # Collect files
    if file_path.is_dir():
        supported = {
            ".pdf",
            ".docx",
            ".doc",
            ".txt",
            ".md",
            ".rst",
            ".html",
            ".epub",
            ".pptx",
            ".xlsx",
            ".csv",
            ".json",
            ".jsonl",
            ".xml",
        }
        files = sorted(
            f
            for f in file_path.iterdir()
            if f.suffix.lower() in supported and not f.name.startswith(".")
        )
    else:
        files = [file_path]

    # Output target
    out = sys.stdout
    output_path = None
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        out = open(output_path, "w", encoding="utf-8")

    total_chunks = 0

    for fp in files:
        try:
            # Stage 1: Parse
            parsed = parse_document(fp, timeout=settings.parse_timeout)

            # Stage 1b: Clean
            if settings.cleaning_enabled:
                parsed = clean_document(parsed)

            # Profile detection
            if settings.extraction_profile == "auto":
                profile_name = detect_profile(parsed)
            else:
                profile_name = settings.extraction_profile
            profile = PROFILES.get(profile_name, PROFILES["general"])

            # Apply profile overrides
            chunk_settings = settings
            profile_overrides = {}
            if profile.max_chunk_tokens is not None:
                profile_overrides["max_chunk_tokens"] = profile.max_chunk_tokens
            if profile.min_chunk_tokens is not None:
                profile_overrides["min_chunk_tokens"] = profile.min_chunk_tokens
            if profile.chunking_strategy is not None:
                profile_overrides["chunking_strategy"] = profile.chunking_strategy
            if profile_overrides:
                chunk_settings = settings.model_copy(update=profile_overrides)

            # Stage 2: Structure
            doc_id = generate_doc_id(fp)
            structure = detect_structure(parsed, doc_id)

            # Stage 3: Chunk + validate
            chunks = chunk_document(structure, chunk_settings)
            chunks, _ = validate_chunks(chunks)

            # Output JSONL
            for chunk in chunks.l3_chunks:
                record = {
                    "id": chunk.chunk_id,
                    "doc_id": doc_id,
                    "doc_title": chunks.l0.title or fp.stem,
                    "content": chunk.content,
                    "summary": chunk.summary,
                    "chapter": chunk.position.chapter,
                    "section": chunk.position.section,
                    "page_start": chunk.page_start,
                    "page_end": chunk.page_end,
                    "concepts": chunk.concepts,
                    "keywords": chunk.keywords,
                    "profile": profile_name,
                }
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
                total_chunks += 1

            if args.verbose:
                print(
                    f"  {fp.name}: {len(chunks.l3_chunks)} chunks ({profile_name})", file=sys.stderr
                )

        except Exception as e:
            print(f"  {fp.name}: FAILED — {e}", file=sys.stderr)

    if output_path:
        out.close()
        print(f"{total_chunks} chunks → {output_path}", file=sys.stderr)
    elif args.verbose:
        print(f"{total_chunks} chunks", file=sys.stderr)

    # Cleanup temp dir
    import shutil

    shutil.rmtree(str(overrides["data_dir"]), ignore_errors=True)


def _cmd_list() -> None:
    from ingestible.config import get_settings
    from ingestible.pipeline.stage6_storage import list_documents

    settings = get_settings()
    docs = list_documents(settings)

    if not docs:
        print("No documents ingested yet.")
        return

    for doc in docs:
        print(
            f"  {doc.get('doc_id', '?'):40s}  "
            f"{doc.get('title', ''):50s}  "
            f"{doc.get('total_pages', '?')} pages  "
            f"{doc.get('ingestion_date', '')}"
        )


def _cmd_search(args: argparse.Namespace) -> None:
    from ingestible.config import get_settings
    from ingestible.pipeline.stage5_embedding import Embedder
    from ingestible.pipeline.stage6_storage import load_chunks
    from ingestible.search.hybrid import load_searcher

    overrides = {}
    if getattr(args, "hyde", False):
        overrides["hyde_enabled"] = True
    if getattr(args, "auto_merge", False):
        overrides["auto_merge_enabled"] = True
    if getattr(args, "kg", False):
        overrides["kg_retrieval_enabled"] = True

    settings = get_settings(**overrides)
    doc_dir = settings.documents_dir / args.doc_id

    if not doc_dir.exists():
        print(f"Document not found: {args.doc_id}")
        print("Run 'ingest list' to see available documents.")
        sys.exit(1)

    chunks = load_chunks(doc_dir)
    embedder = Embedder(settings)
    searcher = load_searcher(doc_dir, chunks, embedder, settings)

    # HyDE query expansion — only affects vector embedding, not BM25/concept/exact
    query = args.query
    hyde_query = None
    if settings.hyde_enabled:
        import asyncio

        from ingestible.search.query_expansion import QueryExpansionConfig, expand_query

        config = QueryExpansionConfig(hyde_enabled=True)
        expanded = asyncio.run(expand_query(query, config, settings))
        if expanded and expanded[0] != query:
            hyde_query = expanded[0]
            print(f"HyDE expanded query: {hyde_query[:100]}...")

    # Sub-question decomposition — search each independently, merge results
    if settings.sub_questions_enabled:
        import asyncio as _asyncio

        from ingestible.models.search import SearchResponse, SearchResult
        from ingestible.search.query_expansion import QueryExpansionConfig as _SQConfig
        from ingestible.search.query_expansion import expand_query as _sq_expand

        sq_config = _SQConfig(
            sub_questions_enabled=True, max_sub_questions=settings.max_sub_questions
        )
        sub_queries = _asyncio.run(_sq_expand(query, sq_config, settings))
        if len(sub_queries) > 1:
            merged: dict[str, SearchResult] = {}
            for sq in sub_queries:
                resp = searcher.search(sq, n_results=args.results, hyde_query=hyde_query)
                for r in resp.results:
                    if r.chunk_id not in merged or r.score > merged[r.chunk_id].score:
                        merged[r.chunk_id] = r
            results = sorted(merged.values(), key=lambda r: r.score, reverse=True)[: args.results]
            response = SearchResponse(
                doc_id=resp.doc_id,
                query=query,
                results=results,
                total_candidates=len(merged),
            )
        else:
            response = searcher.search(query, n_results=args.results, hyde_query=hyde_query)
    else:
        response = searcher.search(query, n_results=args.results, hyde_query=hyde_query)

    if not response.results:
        print("No results found.")
        return

    print(f'Search: "{args.query}" in {args.doc_id}')
    print(f"Found {response.total_candidates} candidates, showing top {len(response.results)}:\n")

    for i, r in enumerate(response.results, 1):
        sources = ", ".join(r.match_sources) if r.match_sources else "?"
        pages = ""
        if r.page_start:
            pages = f"p.{r.page_start}"
            if r.page_end and r.page_end != r.page_start:
                pages += f"-{r.page_end}"

        print(f"  [{i}] score={r.score:.4f}  ({sources})  {pages}")
        if r.summary:
            print(f"      {r.summary[:200]}")
        else:
            print(f"      {r.content[:200]}")
        print()


def _cmd_corpus_search(args: argparse.Namespace) -> None:
    from ingestible.config import get_settings
    from ingestible.search.corpus import CorpusSearcher

    overrides = {}
    if getattr(args, "auto_merge", False):
        overrides["auto_merge_enabled"] = True
    if getattr(args, "kg", False):
        overrides["kg_retrieval_enabled"] = True

    settings = get_settings(**overrides)

    # HyDE: expand once at corpus level, pass to all per-doc searchers
    hyde_query = None
    if getattr(args, "hyde", False):
        import asyncio

        from ingestible.search.query_expansion import HyDEExpander

        try:
            expander = HyDEExpander(settings)
            hyde_query = asyncio.run(expander.expand(args.query))
            if hyde_query:
                print(f"HyDE expanded query: {hyde_query[:100]}...")
        except Exception:
            pass

    filter_tags = None
    if args.tags:
        filter_tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    searcher = CorpusSearcher(settings)
    response = searcher.search(
        args.query,
        n_results=args.results,
        doc_ids=args.doc_ids,
        tags=filter_tags,
        hyde_query=hyde_query,
    )

    if not response.results:
        print("No results found.")
        return

    print(f'Search: "{args.query}" across {response.documents_searched} documents')
    print(f"Found {response.total_candidates} candidates, showing top {len(response.results)}:\n")

    for i, r in enumerate(response.results, 1):
        sources = ", ".join(r.match_sources) if r.match_sources else "?"
        pages = ""
        if r.page_start:
            pages = f"p.{r.page_start}"
            if r.page_end and r.page_end != r.page_start:
                pages += f"-{r.page_end}"

        doc_label = r.doc_title or r.doc_id or "?"
        print(f"  [{i}] score={r.score:.4f}  [{doc_label}]  ({sources})  {pages}")
        if r.summary:
            print(f"      {r.summary[:200]}")
        else:
            print(f"      {r.content[:200]}")
        print()


def _cmd_enrich(args: argparse.Namespace) -> None:
    import logging

    from ingestible.config import get_settings
    from ingestible.pipeline.re_enrich import re_enrich

    if args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING)

    settings = get_settings()

    doc_dir = settings.documents_dir / args.doc_id
    if not doc_dir.exists():
        print(f"Document not found: {args.doc_id}")
        print("Run 'ingest list' to see available documents.")
        sys.exit(1)

    doc_dir = re_enrich(args.doc_id, settings)
    print(f"Re-enriched → {doc_dir}")


def _cmd_versions(args: argparse.Namespace) -> None:
    from ingestible.config import get_settings
    from ingestible.pipeline.stage6_storage import list_versions

    settings = get_settings()
    doc_dir = settings.documents_dir / args.doc_id

    if not doc_dir.exists():
        print(f"Document not found: {args.doc_id}")
        print("Run 'ingest list' to see available documents.")
        sys.exit(1)

    versions = list_versions(doc_dir)
    if not versions:
        print(f"No archived versions for {args.doc_id}.")
        return

    print(f"Versions for {args.doc_id}:")
    for v in versions:
        print(
            f"  v{v['version']:3d}  "
            f"archived={v.get('archived_at', '?')}  "
            f"hash={v.get('content_hash', '?')[:12]}..."
        )


def _cmd_export(args: argparse.Namespace) -> None:
    from pathlib import Path

    from ingestible.config import get_settings
    from ingestible.export import export_document
    from ingestible.pipeline.stage6_storage import load_chunks, load_document_meta

    settings = get_settings()
    doc_dir = settings.documents_dir / args.doc_id

    if not doc_dir.exists():
        print(f"Document not found: {args.doc_id}")
        print("Run 'ingest list' to see available documents.")
        sys.exit(1)

    chunks = load_chunks(doc_dir)
    meta = load_document_meta(doc_dir)
    output_path = Path(args.output)

    export_document(chunks, args.format, output_path, doc_title=meta.get("title", ""))
    print(f"Exported {args.doc_id} to {output_path} ({args.format})")


def _cmd_config() -> None:
    from ingestible.config import get_settings

    settings = get_settings()
    for key, value in settings.model_dump().items():
        print(f"{key}={value}")


def _cmd_watch(args: argparse.Namespace) -> None:
    import logging
    import os
    from pathlib import Path

    from ingestible.config import get_settings

    if args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING)

    overrides = {}
    if args.data_dir:
        overrides["data_dir"] = Path(args.data_dir)
    settings = get_settings(**overrides)

    watch_dir = Path(args.dir).resolve()
    if not watch_dir.is_dir():
        print(f"Error: {args.dir} is not a directory")
        sys.exit(1)

    cv_config = None
    if args.cv_push:
        from ingestible.adapters.cv_export import CVConfig

        cv_url = args.cv_url or os.environ.get("CV_URL")
        cv_api_key = args.cv_api_key or os.environ.get("CV_API_KEY")
        cv_vault_id = args.cv_vault_id or os.environ.get("CV_VAULT_ID")

        if not cv_url or not cv_api_key or not cv_vault_id:
            print("Error: --cv-push requires --cv-url, --cv-api-key, --cv-vault-id")
            print("       (or set CV_URL, CV_API_KEY, CV_VAULT_ID environment variables)")
            sys.exit(1)

        cv_config = CVConfig(base_url=cv_url, api_key=cv_api_key, vault_id=cv_vault_id)

    from ingestible.pipeline.watcher import FileWatcher

    watcher = FileWatcher(
        watch_dir=watch_dir,
        settings=settings,
        skip_enrichment=args.skip_enrichment,
        cv_push=args.cv_push,
        cv_config=cv_config,
    )
    watcher.start()


def _cmd_export_cv(args: argparse.Namespace) -> None:
    import logging
    import os

    from ingestible.adapters.cv_export import CVConfig, export_batch_to_cv
    from ingestible.config import get_settings
    from ingestible.pipeline.stage6_storage import list_documents

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    settings = get_settings()

    cv_url = args.cv_url or os.environ.get("CV_URL")
    cv_api_key = args.cv_api_key or os.environ.get("CV_API_KEY")
    cv_vault_id = args.cv_vault_id or os.environ.get("CV_VAULT_ID")

    if not cv_url or not cv_api_key or not cv_vault_id:
        print("Error: CognitiveVault connection requires --cv-url, --cv-api-key, --cv-vault-id")
        print("       (or set CV_URL, CV_API_KEY, CV_VAULT_ID environment variables)")
        sys.exit(1)

    config = CVConfig(base_url=cv_url, api_key=cv_api_key, vault_id=cv_vault_id)

    # Resolve doc_ids
    if args.doc_ids:
        doc_ids = args.doc_ids
    else:
        docs = list_documents(settings)
        doc_ids = [d.get("doc_id", "") for d in docs if d.get("doc_id")]
        if not doc_ids:
            print("No documents ingested yet. Run 'ingest ingest <file>' first.")
            sys.exit(1)
        print(f"Exporting all {len(doc_ids)} documents...")

    results = export_batch_to_cv(doc_ids, settings, config, delete_removed=args.delete_removed)

    succeeded = sum(1 for r in results if not r.error)
    failed = sum(1 for r in results if r.error)

    print(f"\nExport complete: {succeeded} succeeded, {failed} failed")
    for r in results:
        if r.error:
            print(f"  {r.doc_id:40s}  FAILED: {r.error}")
        else:
            print(
                f"  {r.doc_id:40s}  created={r.created} updated={r.updated} unchanged={r.unchanged}"
            )


if __name__ == "__main__":
    main()
