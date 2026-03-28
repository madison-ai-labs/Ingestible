-- User profiles (extends Supabase auth.users)
create table if not exists profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text,
  name text,
  avatar_url text,
  role text not null default 'free' check (role in ('free', 'premium', 'admin')),
  created_at timestamptz not null default now()
);

-- Auto-create profile on signup
-- SET search_path = public is critical — without it the function can't find
-- the profiles table when invoked by supabase_auth_admin.
create or replace function handle_new_user()
returns trigger as $$
begin
  insert into public.profiles (id, email, name, avatar_url)
  values (
    new.id,
    new.email,
    coalesce(new.raw_user_meta_data->>'name', new.raw_user_meta_data->>'full_name'),
    new.raw_user_meta_data->>'avatar_url'
  );
  return new;
exception when others then
  raise log 'handle_new_user failed: %', sqlerrm;
  return new;
end;
$$ language plpgsql security definer set search_path = public;

create or replace trigger on_auth_user_created
  after insert on auth.users
  for each row execute function handle_new_user();

-- API keys table (owned by users)
create table if not exists api_keys (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references profiles(id) on delete cascade,
  key text not null unique,
  label text not null,
  created_at timestamptz not null default now(),
  last_used_at timestamptz,
  revoked boolean not null default false,
  requests_count bigint not null default 0,
  tokens_used bigint not null default 0,
  documents_ingested integer not null default 0,
  searches_performed bigint not null default 0,
  errors_count bigint not null default 0,
  bytes_uploaded bigint not null default 0
);

create index idx_api_keys_key on api_keys (key) where not revoked;
create index idx_api_keys_user on api_keys (user_id);
create index idx_api_keys_created on api_keys (created_at desc);

-- RLS policies
alter table profiles enable row level security;
alter table api_keys enable row level security;

-- Users can read their own profile
create policy "Users read own profile" on profiles
  for select using (auth.uid() = id);

-- Users can read their own keys
create policy "Users read own keys" on api_keys
  for select using (auth.uid() = user_id);

-- Users can insert their own keys
create policy "Users insert own keys" on api_keys
  for insert with check (auth.uid() = user_id);

-- Users can update their own keys
create policy "Users update own keys" on api_keys
  for update using (auth.uid() = user_id);

-- Users can delete their own keys
create policy "Users delete own keys" on api_keys
  for delete using (auth.uid() = user_id);

-- Per-day usage metrics (time-series)
create table if not exists api_key_usage (
  id bigint generated always as identity primary key,
  api_key_id uuid not null references api_keys(id) on delete cascade,
  date date not null default current_date,
  endpoint text not null,
  method text not null default 'GET',
  requests integer not null default 0,
  errors integer not null default 0,
  latency_avg_ms integer,
  latency_p99_ms integer,
  tokens_used bigint not null default 0,
  bytes_uploaded bigint not null default 0,
  unique (api_key_id, date, endpoint, method)
);

create index idx_usage_key_date on api_key_usage (api_key_id, date desc);
create index idx_usage_date on api_key_usage (date desc);

alter table api_key_usage enable row level security;

create policy "Users read own usage" on api_key_usage
  for select using (
    api_key_id in (select id from api_keys where user_id = auth.uid())
  );

-- Request log
create table if not exists api_request_log (
  id bigint generated always as identity primary key,
  api_key_id uuid not null references api_keys(id) on delete cascade,
  timestamp timestamptz not null default now(),
  method text not null,
  path text not null,
  status_code integer not null,
  latency_ms integer,
  request_bytes bigint,
  response_bytes bigint,
  error_message text,
  ip_address text,
  user_agent text
);

create index idx_log_key_time on api_request_log (api_key_id, timestamp desc);
create index idx_log_time on api_request_log (timestamp desc);

alter table api_request_log enable row level security;

create policy "Users read own logs" on api_request_log
  for select using (
    api_key_id in (select id from api_keys where user_id = auth.uid())
  );
