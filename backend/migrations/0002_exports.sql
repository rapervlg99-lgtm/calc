-- +goose Up
create table exports (
    id             uuid primary key default gen_random_uuid(),
    calculation_id uuid not null references calculations(id) on delete cascade,
    format         text not null check (format in ('pdf', 'xlsx', 'docx')),
    generated_at   timestamptz not null default now(),
    bytes_hash     text
);

create index exports_calc_idx on exports (calculation_id);
create index exports_generated_at_idx on exports (generated_at desc);

-- +goose Down
drop table if exists exports;
