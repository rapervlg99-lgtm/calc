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

`compliance` проходит целиком (PASS=15, FAIL=0, SKIP=0) в обоих режимах. Два
направления ещё не закрыты и требуют отдельной работы:

- контуры `env.<контур>/.env.*` пока несут общие имена шаблона (`HTTP_ADDR`,
  `SESSION_SECRET`, …), а бэкенд читает переменные с префиксом `CALC_OZM_`, и файлы
  `.env.*` пока не в git (`ozm/.gitignore`); без этого `docker-compose.yaml` не
  настроит сервисы, а в CI проверка [3/15] получит пустой контур;
- `smoke` ждёт поднятого стенда с прокси, моком Цифрового профиля и коллектором OTel
  и имён сервисов вида `ozm-api`/`ozm-web` — в `docker-compose.yaml` их пока нет.

## Имена

| Конвенция | Значение |
|-----------|----------|
| Product slug | `ozm` |
| Env prefix | `CALC_OZM_*` |
| Compose service (dev) | `ozm-backend` |
| Binaries | `ozm-server`, `ozm-migrate` |
| DB | `ozm` |

Не копируйте секреты и GitLab registry paths из отмостки без замены: в stage и prod
в git лежат только плейсхолдеры `REPLACE_WITH_*` (проверки [3/15] и [8/15]).
