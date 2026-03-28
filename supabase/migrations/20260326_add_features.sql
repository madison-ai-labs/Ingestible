-- Audit log
create table if not exists audit_log (
  id bigint generated always as identity primary key,
  actor_id uuid references profiles(id) on delete set null,
  actor_email text,
  event text not null,  -- 'user.login', 'user.signup', 'key.created', 'key.revoked', 'key.deleted', 'role.changed', 'settings.updated'
  target_type text,     -- 'user', 'api_key', 'settings'
  target_id text,
  metadata jsonb default '{}',
  ip_address text,
  user_agent text,
  created_at timestamptz not null default now()
);
create index idx_audit_created on audit_log (created_at desc);
create index idx_audit_actor on audit_log (actor_id);

-- Tier limits configuration
create table if not exists tier_limits (
  tier text primary key check (tier in ('free', 'premium', 'admin')),
  requests_per_day integer not null default 100,
  requests_per_minute integer not null default 10,
  max_documents integer not null default 5,
  max_keys integer not null default 2,
  max_file_size_mb integer not null default 50,
  enrichment_enabled boolean not null default false
);

insert into tier_limits (tier, requests_per_day, requests_per_minute, max_documents, max_keys, max_file_size_mb, enrichment_enabled) values
  ('free', 100, 10, 5, 2, 50, false),
  ('premium', 10000, 100, 100, 10, 500, true),
  ('admin', 999999, 9999, 999999, 999, 999, true)
on conflict (tier) do nothing;

-- Webhook subscriptions
create table if not exists webhook_subscriptions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references profiles(id) on delete cascade,
  url text not null,
  events text[] not null default '{}',  -- 'ingestion.complete', 'key.revoked', 'quota.warning', 'quota.exceeded'
  secret text,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  last_triggered_at timestamptz,
  failure_count integer not null default 0
);
create index idx_webhook_user on webhook_subscriptions (user_id);

-- Teams
create table if not exists teams (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  owner_id uuid not null references profiles(id) on delete cascade,
  created_at timestamptz not null default now()
);

create table if not exists team_members (
  team_id uuid not null references teams(id) on delete cascade,
  user_id uuid not null references profiles(id) on delete cascade,
  role text not null default 'member' check (role in ('owner', 'admin', 'member')),
  joined_at timestamptz not null default now(),
  primary key (team_id, user_id)
);

-- Notification preferences on profiles
alter table profiles add column if not exists notify_quota_warning boolean not null default true;
alter table profiles add column if not exists notify_quota_exceeded boolean not null default true;
alter table profiles add column if not exists notify_weekly_digest boolean not null default false;

-- RLS for new tables
alter table audit_log enable row level security;
alter table tier_limits enable row level security;
alter table webhook_subscriptions enable row level security;
alter table teams enable row level security;
alter table team_members enable row level security;

-- Anyone can read tier limits
create policy "Anyone can read tier limits" on tier_limits for select using (true);

-- Users can manage their own webhooks
create policy "Users manage own webhooks" on webhook_subscriptions for all using (auth.uid() = user_id);

-- Team policies
create policy "Team members can read team" on teams for select using (
  id in (select team_id from team_members where user_id = auth.uid())
);
create policy "Owners can update team" on teams for update using (owner_id = auth.uid());
create policy "Users can create teams" on teams for insert with check (auth.uid() = owner_id);

create policy "Members can read team members" on team_members for select using (
  team_id in (select team_id from team_members where user_id = auth.uid())
);
