-- Add suspended flag to profiles
alter table profiles add column if not exists suspended boolean not null default false;

-- Add per-user quota overrides (nullable = use tier defaults)
alter table profiles add column if not exists quota_overrides jsonb;

-- Index for quick suspended lookups
create index if not exists idx_profiles_suspended on profiles (suspended) where suspended = true;

-- Allow service role to update profiles (for admin API)
create policy "Service role manages all profiles" on profiles
  for all using (auth.role() = 'service_role');
