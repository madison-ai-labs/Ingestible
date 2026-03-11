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
    p_ingest = sub.add_parser("ingest", help="Ingest a document or directory into the knowledge store")
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
        choices=["paragraph", "semantic", "recursive"],
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

    # --- list ---
    sub.add_parser("list", help="List all ingested documents")

    # --- search ---
    p_search = sub.add_parser("search", help="Search within a document")
    p_search.add_argument("doc_id", help="Document ID (from 'ingest list')")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument(
        "-n", "--results", type=int, default=5, help="Number of results (default: 5)"
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

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "ingest":
        _cmd_ingest(args)
    elif args.command == "list":
        _cmd_list()
    elif args.command == "search":
        _cmd_search(args)
    elif args.command == "export-cv":
        _cmd_export_cv(args)


def _is_batch_input(file_path: str) -> bool:
    """Detect if input is a directory or glob pattern (batch mode)."""
    from pathlib import Path

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

    settings = get_settings(**overrides)

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
        print(f"\nBatch complete: {report.succeeded} succeeded, {report.failed} failed ({report.elapsed_seconds}s)")
        for r in report.results:
            status = "OK" if not r.error else f"FAILED: {r.error}"
            print(f"  {r.path.name:40s}  {status}")
    else:
        from ingestible.pipeline.orchestrator import ingest

        doc_dir = ingest(
            args.file_path,
            settings,
            skip_enrichment=args.skip_enrichment,
            verbose=args.verbose,
            force=args.force,
        )
        print(f"Ingested → {doc_dir}")


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
    from pathlib import Path

    from ingestible.config import get_settings
    from ingestible.pipeline.stage5_embedding import Embedder
    from ingestible.pipeline.stage6_storage import load_chunks
    from ingestible.search.hybrid import load_searcher

    settings = get_settings()
    doc_dir = settings.documents_dir / args.doc_id

    if not doc_dir.exists():
        print(f"Document not found: {args.doc_id}")
        print("Run 'ingest list' to see available documents.")
        sys.exit(1)

    chunks = load_chunks(doc_dir)
    embedder = Embedder(settings)
    searcher = load_searcher(doc_dir, chunks, embedder, settings)

    response = searcher.search(args.query, n_results=args.results)

    if not response.results:
        print("No results found.")
        return

    print(f"Search: \"{args.query}\" in {args.doc_id}")
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


def _cmd_export_cv(args: argparse.Namespace) -> None:
    import os
    from ingestible.adapters.cv_export import CVConfig, export_batch_to_cv
    from ingestible.config import get_settings
    from ingestible.pipeline.stage6_storage import list_documents

    import logging

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

    results = export_batch_to_cv(
        doc_ids, settings, config, delete_removed=args.delete_removed
    )

    succeeded = sum(1 for r in results if not r.error)
    failed = sum(1 for r in results if r.error)

    print(f"\nExport complete: {succeeded} succeeded, {failed} failed")
    for r in results:
        if r.error:
            print(f"  {r.doc_id:40s}  FAILED: {r.error}")
        else:
            print(f"  {r.doc_id:40s}  created={r.created} updated={r.updated} unchanged={r.unchanged}")


if __name__ == "__main__":
    main()
