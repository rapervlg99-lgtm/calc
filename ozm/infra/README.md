# infra — deploy stub (MVP)

Рабочий вариант развёртывания на одной машине: `dev/docker-compose.yml` +
`dev/scripts/deploy.sh`, описание в [docs/deploy.md](../docs/deploy.md).

Stage/prod деплой по образцу blind-area-calc `infra/`. В MVP достаточно локального
`dev/docker-compose.local.yml`. Здесь — каркас имён под slug **ozm**.

## Целевая раскладка (Phase 5)

```
infra/
  env.stage/
    .env.ozm          # CALC_OZM_APP_*
    .env.pg           # CALC_OZM_PG_*
    .docker-compose.yaml
    .build.tags
  env.prod/
    … то же
  volume/frontend/nginx.conf
  README.md
```

## Имена

| Конвенция | Значение |
|-----------|----------|
| Product slug | `ozm` |
| Env prefix | `CALC_OZM_*` |
| Compose service (dev) | `ozm-backend` |
| Binaries | `ozm-server`, `ozm-migrate` |
| DB | `ozm` |

Не копируйте секреты и GitLab registry paths из отмостки без замены.
