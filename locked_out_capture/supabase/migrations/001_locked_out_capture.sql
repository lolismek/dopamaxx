create schema if not exists extensions;
create extension if not exists vector with schema extensions;
create extension if not exists pgcrypto with schema extensions;

create table if not exists public.posts (
  id uuid primary key default extensions.gen_random_uuid(),
  platform text not null check (platform in ('x', 'twitter')),
  platform_post_id text not null,
  canonical_url text,
  author_handle text,
  author_name text,
  text text,
  media jsonb not null default '[]'::jsonb,
  raw_capture jsonb not null default '{}'::jsonb,
  embedding extensions.vector(1536),
  embedding_model text,
  embedding_status text not null default 'pending'
    check (embedding_status in ('pending', 'complete', 'failed')),
  embedding_error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (platform, platform_post_id)
);

create table if not exists public.post_observations (
  id uuid primary key default extensions.gen_random_uuid(),
  user_id text not null,
  session_id text not null,
  post_id uuid not null references public.posts(id) on delete cascade,
  mode text not null default 'locked_out' check (mode = 'locked_out'),
  dwell_ms integer not null check (dwell_ms >= 0),
  viewport_score double precision,
  center_score double precision,
  main_visible_ratio double precision,
  reward_source text not null default 'random_v0',
  reward_model_version text not null default 'random_v0',
  reward_score double precision not null check (reward_score >= -1 and reward_score <= 1),
  reward_label text not null check (reward_label in ('hit', 'miss', 'neutral')),
  eeg_context jsonb not null default '{}'::jsonb,
  raw_observation jsonb not null default '{}'::jsonb,
  observed_at timestamptz not null,
  created_at timestamptz not null default now()
);

create index if not exists posts_platform_post_id_idx
  on public.posts (platform, platform_post_id);

create index if not exists posts_embedding_cosine_idx
  on public.posts
  using ivfflat (embedding extensions.vector_cosine_ops)
  with (lists = 100)
  where embedding is not null;

create index if not exists post_observations_user_label_idx
  on public.post_observations (user_id, reward_label, observed_at desc);

create index if not exists post_observations_post_id_idx
  on public.post_observations (post_id);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists posts_set_updated_at on public.posts;
create trigger posts_set_updated_at
before update on public.posts
for each row execute function public.set_updated_at();

create or replace function public.match_user_hit_posts(
  query_user_id text,
  query_embedding extensions.vector(1536),
  match_count int default 10
)
returns table (
  post_id uuid,
  platform text,
  platform_post_id text,
  canonical_url text,
  author_handle text,
  author_name text,
  text text,
  similarity double precision,
  max_reward_score double precision
)
language sql
stable
as $$
  with hit_posts as (
    select
      p.id,
      p.platform,
      p.platform_post_id,
      p.canonical_url,
      p.author_handle,
      p.author_name,
      p.text,
      p.embedding,
      max(o.reward_score) as max_reward_score
    from public.posts p
    join public.post_observations o on o.post_id = p.id
    where
      o.user_id = query_user_id
      and o.reward_label = 'hit'
      and p.embedding is not null
    group by p.id
  )
  select
    h.id as post_id,
    h.platform,
    h.platform_post_id,
    h.canonical_url,
    h.author_handle,
    h.author_name,
    h.text,
    1 - (h.embedding OPERATOR(extensions.<=>) query_embedding) as similarity,
    h.max_reward_score
  from hit_posts h
  order by h.embedding OPERATOR(extensions.<=>) query_embedding
  limit greatest(match_count, 1);
$$;
