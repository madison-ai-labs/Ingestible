# MCP Server

Ingestible exposes a [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server so AI agents (Claude, GPT, etc.) can ingest documents, search, and retrieve content directly — no HTTP API needed.

## Setup

```bash
pip install ingestible[mcp]
ingest mcp
```

### Claude Desktop

Add to your Claude Desktop configuration (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "ingestible": {
      "command": "python",
      "args": ["-m", "ingestible.mcp_server"]
    }
  }
}
```

If using a virtual environment:

```json
{
  "mcpServers": {
    "ingestible": {
      "command": "/path/to/venv/bin/python",
      "args": ["-m", "ingestible.mcp_server"]
    }
  }
}
```

### Claude Code

Add to your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "ingestible": {
      "command": "python",
      "args": ["-m", "ingestible.mcp_server"]
    }
  }
}
```

## Tools

The MCP server exposes 8 tools:

### ingest_document

Ingest a document into the knowledge store. Runs the full 6-stage pipeline.

```
ingest_document(
  file_path: str,           # Local path, HTTP(S) URL, or cloud URL (s3://, gs://, az://)
  skip_enrichment: bool,    # Skip LLM enrichment (default: false)
  profile: str              # Extraction profile (default: "auto")
)
```

**Returns:** JSON with `doc_id`, `title`, `total_pages`, `total_chunks`, `enriched`

### search

Search across ingested documents. If `doc_id` is provided, searches within that document only. Otherwise, searches the entire corpus.

```
search(
  query: str,               # Natural language search query
  doc_id: str | None,       # Optional — restrict to one document
  n_results: int,           # Number of results (default: 5)
  tags: list[str] | None,   # Filter by metadata tags (corpus search only)
  hyde: bool,               # HyDE query expansion (default: false)
  auto_merge: bool,         # Auto-merge child chunks (default: false)
  kg_boost: bool            # Knowledge graph boost (default: false)
)
```

**Returns:** JSON with ranked results including content, scores, match sources, and metadata

### list_documents

List all ingested documents.

```
list_documents()
```

**Returns:** JSON array of `{ doc_id, title, total_pages, ingestion_date }`

### get_document_overview

Get the L0 document overview — a structured map of the entire document. This is the "map" that lets the AI understand the document's structure before searching.

```
get_document_overview(doc_id: str)
```

**Returns:** JSON with `title`, `executive_summary`, `key_findings`, `key_concepts`, `chapters`, `methodology`, `limitations`, `toc_summary`, `total_pages`, `total_chapters`, `total_sections`, `total_passages`

### get_chunk

Drill into a specific chunk by ID. Use this to read the full content of a passage found via search.

```
get_chunk(
  chunk_id: str,            # Chunk ID (from search results or overview)
  doc_id: str               # Document containing the chunk
)
```

**Returns:** JSON with chunk content, summary, concepts, and metadata

### get_knowledge_graph

Get entity-relationship triples extracted from a document. Only available when KG extraction was enabled during ingestion.

```
get_knowledge_graph(doc_id: str)
```

**Returns:** JSON with `triples`, `entities`, and entity counts

### delete_document

Delete a document and all its indexes.

```
delete_document(doc_id: str)
```

**Returns:** JSON confirmation

### eval_judge

Evaluate retrieval quality using LLM-as-judge scoring.

```
eval_judge(
  doc_id: str,              # Document to evaluate
  k: int                    # Results per query (default: 5)
)
```

**Returns:** Faithfulness, relevance, and completeness scores (0-1 scale)

## Typical Agent Workflow

A well-behaved AI agent interacts with Ingestible in three steps:

1. **Get the map** — call `get_document_overview` to understand the document structure (~500-800 tokens)
2. **Search** — call `search` with a natural language query to find relevant passages
3. **Drill down** — call `get_chunk` on promising results to read full content

This keeps context usage to ~1,000-2,000 tokens per query instead of loading the entire document.

## Configuration

The MCP server uses the same configuration as the CLI and API. Set environment variables or use a `.env` file:

```bash
INGEST_DATA_DIR=data
INGEST_LLM_PROVIDER=anthropic
INGEST_ANTHROPIC_API_KEY=sk-ant-...
```

See the [Usage Guide](Usage) for the full configuration reference.
