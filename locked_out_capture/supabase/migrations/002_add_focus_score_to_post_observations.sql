alter table public.post_observations
  add column if not exists focus_score double precision
    check (focus_score is null or (focus_score >= 0 and focus_score <= 1));

create index if not exists post_observations_user_focus_idx
  on public.post_observations (user_id, focus_score, observed_at desc)
  where focus_score is not null;
