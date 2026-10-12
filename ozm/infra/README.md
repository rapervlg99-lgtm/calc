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

`compliance` проходит целиком (PASS=15, FAIL=0, SKIP=0) в обоих режимах, и стенд
поднимается: контуры, `docker-compose.yaml` и сервисы говорят на одних именах, а
все пять целей `smoke` отвечают. Подключение к БД — `PGHOST`/`PGPORT`/`PGDATABASE`/
`PGUSER`/`PGPASSWORD`/`PGSSLMODE` (+`PGSSLROOTCERT`, `PG_MIGRATE_*` для роли
владельца схемы), рантайм — `HTTP_ADDR`, `LOG_LEVEL`, `CORS_ALLOWED_ORIGINS`;
продуктовые настройки — `CALC_OZM_APP_*`. Сервисы: `ozm-traefik`, `ozm-api`,
`ozm-web`, `ozm-ocr`, `ozm-postgres`, `ozm-migrate`, `ozm-oidc`, `ozm-otel`,
`ozm-mailpit` (последние четыре — стенд нормы в профиле `local`).

Как поднять локально (сертификат `*.localhost` создаётся один раз, дальше compose
с профилем `local` и `--env-file` на каждый файл контура):

```bash
openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
  -keyout infra/env.local/traefik/certs/local.key -out infra/env.local/traefik/certs/local.crt \
  -subj '/CN=localhost/O=ozm local' -addext 'subjectAltName=DNS:localhost,DNS:*.localhost'
cd infra && ENV_DIR=env.local OTEL_CONFIG_DIR=./env.local/otel COMPOSE_PROFILES=local \
  docker compose -p ozm -f docker-compose.yaml \
  --env-file env.local/.env.app --env-file env.local/.env.pg --env-file env.local/.env.oidc \
  --env-file env.local/.env.otel --env-file env.local/.env.smtp up -d
```

Что ещё не закрыто и требует отдельной работы:

- **Отступление по версии traefik.** В контурах стоит `traefik:v3.6.25`, а не
  нормативный `v3.1.7`: docker-провайдер старой версии не разговаривает с демоном
  Docker Desktop (проверено прогоном). Нормативный пин возвращается вместе с
  переходом стенда на linux-демон.
- **Метрики.** Норма держит `/metrics` на отдельном порту `METRICS_ADDR=:9090` и
  скрейпит `ozm-api:9090`; наш бэкенд отдаёт их на порту API, поэтому
  `infra/env.local/otel/config.yaml` нацелен на `ozm-api:8080` (порт тоже не
  публикуется наружу). Появится `METRICS_ADDR` — цель возвращается на `:9090`.
- **Заголовки безопасности.** `security-headers.conf` нормы (`include` в каждом
  location) не подключён: CSP надо сначала проверить на SPA — во `index.html` есть
  инлайновые стили и скрипт префикса.
- **Имена образов и Makefile.** `make -C infra up|build` ждёт образы
  `${DOCKER_REGISTRY}/ozm-<сервис>:${IMAGE_TAG}` и `env.example/` для раскладки
  контура; у нас образы локальные (`ozm-backend:local`, `ozm-frontend:local`,
  `ozm-ocr:local`), а значения локального контура уже заполнены в
  `env.local/.env.*`. Цель `up` Makefile запускается вручную теми же аргументами,
  что в примере выше (кроме `make up` — он требует блока плейсхолдеров).
- **`smoke` из `tests/run.sh`** — POSIX-скрипт: он гоняется в CI (`tests.yaml`,
  ubuntu) и в WSL; на этой машине те же пять целей проверены вручную (`curl -k` +
  `docker inspect ozm-otel`).

## Имена

| Конвенция | Значение |
|-----------|----------|
| Product slug | `ozm` |
| Env: БД и рантайм | канонические имена нормы (`PG*`, `HTTP_ADDR`, `LOG_LEVEL`, `CORS_ALLOWED_ORIGINS`) |
| Env: продукт | `CALC_OZM_APP_*` (распознавание, зрение, выгрузки) |
| Compose services | `ozm-api`, `ozm-web`, `ozm-ocr`, `ozm-postgres`, `ozm-migrate` + стенд `ozm-traefik`, `ozm-oidc`, `ozm-otel`, `ozm-mailpit` |
| Binaries | `ozm-server`, `ozm-migrate` |
| DB | `ozm` |

Не копируйте секреты и GitLab registry paths из отмостки без замены: в stage и prod
в git лежат только плейсхолдеры `REPLACE_WITH_*` (проверки [3/15] и [8/15]); в
`env.local` — значения стенда (низкоэнтропийные, dev-only).
