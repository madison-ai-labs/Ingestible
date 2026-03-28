# CognitiveVault Integration

Ingestible integrates with [CognitiveVault](https://github.com/SimplyLiz/CognitiveVault) for bi-directional knowledge synchronization. Documents ingested by Ingestible can be pushed to CognitiveVault as structured entries, and edits made in CognitiveVault are synced back to update the local chunks.

## Export to CognitiveVault

Push ingested documents to a CognitiveVault instance:

```bash
# Export a specific document
ingest export-cv my-document \
  --cv-url https://cv.example.com \
  --cv-api-key cvk_... \
  --cv-vault-id vault-abc

# Export all documents
ingest export-cv \
  --cv-url https://cv.example.com \
  --cv-api-key cvk_... \
  --cv-vault-id vault-abc

# Clean up removed entries
ingest export-cv --delete-removed \
  --cv-url https://cv.example.com \
  --cv-api-key cvk_... \
  --cv-vault-id vault-abc
```

Each chunk becomes a CognitiveVault entry with a `sourcePath` of `ingest:{doc_id}/{chunk_id}`. The export is idempotent — unchanged entries are skipped, modified entries are updated, and new entries are created.

### Environment variables

Instead of CLI flags, you can set:

```
CV_URL=https://cv.example.com
CV_API_KEY=cvk_...
CV_VAULT_ID=vault-abc
```

## Watch + Auto-Push

Combine the file watcher with CognitiveVault auto-push for a fully automated pipeline:

```bash
ingest watch ./docs/ -v --cv-push \
  --cv-url https://cv.example.com \
  --cv-api-key cvk_... \
  --cv-vault-id vault-abc
```

When a file changes:
1. Ingestible detects the change and re-ingests the document
2. After ingestion completes, chunks are automatically pushed to CognitiveVault
3. Unchanged chunks are skipped (content-hash comparison)

## Webhook: CognitiveVault → Ingestible

When a user edits a chunk in CognitiveVault, the webhook syncs the change back:

### Setup

1. Set the webhook secret:
   ```
   INGEST_WEBHOOK_SECRET=your-shared-secret
   ```

2. Configure CognitiveVault to send `entry.updated` webhooks to:
   ```
   POST https://your-ingestible-host/webhooks/cv
   ```

3. CognitiveVault signs each request with HMAC-SHA256 using the shared secret in the `X-Webhook-Signature` header.

### How it works

When CognitiveVault sends an `entry.updated` event for an entry with an `ingest:` sourcePath:

1. Ingestible verifies the HMAC-SHA256 signature
2. Parses the `sourcePath` to extract `doc_id` and `chunk_id`
3. Updates the chunk content on disk (under document lock)
4. Triggers selective re-enrichment for just that chunk
5. Returns confirmation

### Webhook payload

```json
{
  "event": "entry.updated",
  "payload": {
    "entryId": "cv-entry-id",
    "sourcePath": "ingest:my-document/chunk-abc123",
    "content": "Updated chunk content...",
    "checksum": "sha256hex..."
  }
}
```

### Response

```json
{
  "status": "ok",
  "doc_id": "my-document",
  "chunk_id": "chunk-abc123",
  "re_enriched": true
}
```

Events with non-`ingest:` sourcePaths or non-`entry.updated` event types are silently ignored.

## Architecture

```
File system ──→ Ingestible ──→ CognitiveVault
                    ↑               │
                    └── webhook ────┘
```

- **Forward flow:** `ingest export-cv` or `--cv-push` pushes chunks to CognitiveVault
- **Reverse flow:** CognitiveVault webhook updates local chunks when edited
- **Dedup:** Content hashes prevent unnecessary updates in both directions
- **Locking:** Document-level file locks (`portalocker`) prevent concurrent modifications
