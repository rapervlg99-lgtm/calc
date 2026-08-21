-- +goose Up
create table dicts (
    name       text primary key,
    payload    jsonb not null,
    updated_at timestamptz not null default now(),
    updated_by text not null default 'system'
);

create index dicts_updated_at_idx on dicts (updated_at desc);

-- +goose Down
drop table if exists dicts;
