# infra — нормативная поставка OZM

Раскладка и приёмка перенесены из корпоративного шаблона ТН
(tnlife-miniapp-engineering). Повседневная работа идёт на локальном стенде
[dev/docker-compose.local.yml](../dev/docker-compose.local.yml) (UI :5173, API :8080,
OCR :8000); здесь — поставка и её проверки.

```
infra/
  docker-compose.yaml   # стенд целиком одним файлом: лимиты, healthcheck, container_name
  Makefile              # make -C infra up|build|gen|…, контур задаётся ENV_DIR=env.stage
  env.local/            # контур local: .env.app/.env.pg/.env.oidc/.env.otel/.env.smtp,
                        # postgres (init.sql, init-roles.sql), otel, oidc, traefik
  env.stage/            # то же для stage
  env.prod/             # то же для prod
  observability/        # alerts.yaml, otel-collector.yaml
  tests/                # приёмка: run.sh (15 проверок + smoke), check-env.sh, openapi-gate.sh
  infra/cloud-init/     # единый cloud-init: vm.yaml.tmpl, render.sh, targets/*.env
  README.md
```

Удвоение `infra/infra` у cloud-init — не опечатка: так раскладывает каркас набора,
и проверка [7/15] грепает именно этот путь.

## Приёмка

```bash
bash infra/tests/run.sh compliance            # 15 статических проверок нормы
bash infra/tests/run.sh compliance --strict   # режим CI: SKIP считается FAIL
bash infra/tests/run.sh smoke                 # curl по поднятому стенду env.local
COMPLIANCE_STRICT=1 bash infra/tests/run.sh   # то же переменной окружения
```

Корень репозитория скрипт определяет сам (два уровня вверх от `infra/tests/run.sh`),
поэтому запускать его нужно из этого места — пути в `.github/workflows/tests.yaml`
рассчитаны на него же.

## Состояние

`compliance` проходит целиком (PASS=15, FAIL=0, SKIP=0) в обоих режимах; контуры,
`docker-compose.yaml` и бэкенд говорят на одних именах: подключение к БД —
`PGHOST`/`PGPORT`/`PGDATABASE`/`PGUSER`/`PGPASSWORD`/`PGSSLMODE` (+`PGSSLROOTCERT`,
`PG_MIGRATE_*` для роли владельца схемы), рантайм — `HTTP_ADDR`, `LOG_LEVEL`,
`CORS_ALLOWED_ORIGINS`; продуктовые настройки — `CALC_OZM_APP_*`. Сервисы называются
так, как их зовут контуры: `ozm-postgres`, `ozm-api`, `ozm-web`, `ozm-ocr`,
`ozm-migrate`.

Что ещё не закрыто и требует отдельной работы:

- сами файлы `.env.*` пока не в git (их отсекает `ozm/.gitignore` строкой `.env.*`),
  поэтому в свежем клоне проверка [3/15] не найдёт ни одного контура: норме нужны
  исключения для `infra/env.<контур>/.env.*` (значения stage и prod — только
  плейсхолдеры `REPLACE_WITH_*`, в local — значения стенда);
- стенд пока не тот, что в бланке нормы: нет прокси (`ozm-traefik`), мока Цифрового
  профиля (`ozm-oidc`), коллектора OTel (`ozm-otel`) и `ozm-mailpit`, а вход один —
  nginx фронта; из-за этого `smoke` (цели `https://api.localhost/healthz`,
  `https://app.localhost/healthz`, `oidc-mock`, `docker-health:ozm-otel`) не проходит;
- `TRUSTED_PROXY_CIDR` из контура пока никто не читает: образ фронта не несёт
  realip-шаблона нормы (`realip.conf.template` + `security-headers.conf`).

## Имена

| Конвенция | Значение |
|-----------|----------|
| Product slug | `ozm` |
| Env: БД и рантайм | канонические имена нормы (`PG*`, `HTTP_ADDR`, `LOG_LEVEL`, `CORS_ALLOWED_ORIGINS`) |
| Env: продукт | `CALC_OZM_APP_*` (распознавание, зрение, выгрузки) |
| Compose services | `ozm-api`, `ozm-web`, `ozm-ocr`, `ozm-postgres`, `ozm-migrate` |
| Binaries | `ozm-server`, `ozm-migrate` |
| DB | `ozm` |

Не копируйте секреты и GitLab registry paths из отмостки без замены: в stage и prod
в git лежат только плейсхолдеры `REPLACE_WITH_*` (проверки [3/15] и [8/15]).
