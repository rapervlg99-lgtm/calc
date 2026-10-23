-- +goose Up
-- Ссылки для обмена расчётами: «черновик» калькулятора (объект, адрес,
-- конструкции, бетон) по короткому токену. Ссылка вида /ozm/?n1792668187385
-- создаётся при входе в калькулятор и обновляется по мере правок.
create table calc_shares (
    token      text primary key,
    payload    jsonb not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index calc_shares_updated_at_idx on calc_shares (updated_at desc);

-- +goose Down
drop table if exists calc_shares;
