create or replace function update_api_key_ingestion_stats(
  p_key_id uuid,
  p_tokens_used bigint default 0,
  p_bytes_uploaded bigint default 0,
  p_documents_ingested integer default 0
)
returns void as $$
  update api_keys
  set tokens_used = tokens_used + p_tokens_used,
      bytes_uploaded = bytes_uploaded + p_bytes_uploaded,
      documents_ingested = documents_ingested + p_documents_ingested,
      last_used_at = now()
  where id = p_key_id and not revoked;
$$ language sql security definer;
