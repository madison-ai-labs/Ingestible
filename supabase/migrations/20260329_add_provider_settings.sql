-- LLM provider keys and vector backend configuration on profiles
-- Keys are stored encrypted at rest by Supabase (vault recommended for production)

alter table profiles add column if not exists llm_provider text not null default 'none'
  check (llm_provider in ('none', 'anthropic', 'openai', 'custom'));
alter table profiles add column if not exists llm_api_key text;  -- encrypted at rest
alter table profiles add column if not exists llm_model text;  -- e.g. 'claude-sonnet-4-20250514', 'gpt-4o'
alter table profiles add column if not exists llm_custom_endpoint text;  -- for custom provider
alter table profiles add column if not exists llm_custom_model text;  -- model name for custom endpoint

alter table profiles add column if not exists vector_backend text not null default 'chromadb'
  check (vector_backend in ('chromadb', 'pgvector', 'qdrant'));
alter table profiles add column if not exists vector_connection_string text;  -- pgvector/qdrant connection

alter table profiles add column if not exists embedding_model text not null default 'e5-large-v2';

-- Pipeline preferences
alter table profiles add column if not exists enrichment_enabled boolean not null default true;
alter table profiles add column if not exists auto_merge_enabled boolean not null default false;
alter table profiles add column if not exists hyde_enabled boolean not null default false;
alter table profiles add column if not exists kg_retrieval_enabled boolean not null default false;
alter table profiles add column if not exists content_classification boolean not null default false;
