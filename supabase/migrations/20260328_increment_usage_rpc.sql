create or replace function increment_api_key_usage(p_key_id uuid)
returns void as $$
  update api_keys
  set requests_count = requests_count + 1,
      last_used_at = now()
  where id = p_key_id and not revoked;
$$ language sql security definer;
