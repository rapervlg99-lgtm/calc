-- +goose Up
create table calculations (
    id          uuid primary key default gen_random_uuid(),
    created_at  timestamptz not null default now(),
    object_name text not null default '',
    total_cents bigint not null default 0,
    request     jsonb not null,
    response    jsonb not null,
    fingerprint text,
    ip          inet,
    user_agent  text
);

create index calculations_created_at_idx on calculations (created_at desc);

-- +goose Down
drop table if exists calculations;
