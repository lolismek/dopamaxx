create table if not exists post_reactions (
    reaction_id text primary key,
    user_id text not null,
    session_id text not null,
    post_id text not null,
    text text not null default '',
    author text,
    url text,
    media_urls text[] not null default '{}',
    embedding double precision[] not null default '{}',
    reward_score double precision not null,
    focus_score double precision,
    label text not null check (label in ('hit', 'miss', 'neutral')),
    dwell_ms integer not null check (dwell_ms >= 0),
    eeg_features jsonb not null default '{}',
    metadata jsonb not null default '{}',
    created_at timestamptz not null default now()
);

create index if not exists post_reactions_user_label_created_idx
    on post_reactions (user_id, label, created_at desc);

create index if not exists post_reactions_session_post_idx
    on post_reactions (session_id, post_id);

create table if not exists preference_embeddings (
    embedding_id text primary key,
    user_id text not null,
    label text not null check (label in ('hit', 'miss')),
    embedding double precision[] not null,
    source_reaction_id text references post_reactions (reaction_id) on delete cascade,
    weight double precision not null default 1,
    metadata jsonb not null default '{}',
    created_at timestamptz not null default now()
);

create index if not exists preference_embeddings_user_label_idx
    on preference_embeddings (user_id, label, created_at desc);

create table if not exists agent_runs (
    run_id text primary key,
    user_id text not null,
    session_id text not null,
    status text not null check (status in ('running', 'completed', 'cancelled', 'failed')),
    target_count integer not null default 20 check (target_count > 0),
    queued_count integer not null default 0,
    fetched_count integer not null default 0,
    accepted_count integer not null default 0,
    error text,
    started_at timestamptz not null default now(),
    finished_at timestamptz
);

create index if not exists agent_runs_session_started_idx
    on agent_runs (user_id, session_id, started_at desc);

create table if not exists microdose_queue (
    queue_id text primary key,
    run_id text not null references agent_runs (run_id) on delete cascade,
    user_id text not null,
    session_id text not null,
    post_id text not null,
    text text not null default '',
    author text,
    url text,
    media_urls text[] not null default '{}',
    predicted_reward double precision not null,
    rank integer not null check (rank > 0),
    status text not null default 'ready' check (status in ('ready', 'shown', 'dismissed', 'consumed')),
    rationale text,
    metadata jsonb not null default '{}',
    created_at timestamptz not null default now()
);

create index if not exists microdose_queue_ready_idx
    on microdose_queue (user_id, session_id, status, rank);

create unique index if not exists microdose_queue_run_post_idx
    on microdose_queue (run_id, post_id);

