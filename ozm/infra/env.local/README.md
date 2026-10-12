<!-- Записка скилла tnlife-miniapp-engineering к каталогу локального окружения.
     Норма — references/01-corp-standard.md, «Файлы окружения». Подставьте ozm в файлах
     каталога, скопируйте сюда .env.* из ../env.example и поднимите стенд. -->

# Локальный стенд env.local

Когда читать: на S0, перед первым `make -C infra up`, и каждый раз, когда
стенд «не поднимается из заготовок».

Каталог монтируется в контейнеры `docker-compose.yaml` как есть. Здесь лежит
всё, что нужно только локальному стенду и чего на stage и prod быть не должно.

## Что здесь лежит

| Файл | Кто читает | Зачем |
|---|---|---|
| `traefik/tls.yaml` | `ozm-traefik`, том `/etc/traefik/dynamic` | TLS для `*.localhost` на self-signed сертификате; маршруты traefik берёт из labels в compose |
| `traefik/certs/` | тот же том, подкаталог `certs/` | `local.crt` и `local.key` генерирует `make -C infra up` при первом запуске; в репозиторий не попадают (`.gitignore` из набора, `templates/code/gitignore`) |
| `postgres/init-roles.sql` | `ozm-postgres`, `/docker-entrypoint-initdb.d` | вторая роль БД (решение D3): роль-владелец схемы — `POSTGRES_USER` контейнера (`PG_MIGRATE_USER` в `.env.pg`), под ней идут миграции; роль рантайма `PGUSER` с DML без DDL создаёт этот скрипт. Исполняется один раз при создании тома, раньше `init.sql` |
| `postgres/init.sql` | тот же том | расширения из конфигурации managed-кластера, БЕЗ схемы и БЕЗ ролей. Сам контейнер БД — только профиль `local` (на контурах БД managed); порт `5432` — на `127.0.0.1`. Повторный прогон скриптов — `make -C infra reset-data CONFIRM=yes`, обычный `down` тома не трогает |
| `otel/config.yaml` | `ozm-otel`, `/etc/otel` | локальный коллектор: приём OTLP, скрейп `ozm-api:9090` (receiver prometheus, решение D5), экспорт только в `debug` — экспортёра `otlp/external` здесь нет вовсе, иначе коллектор валидировал бы его адрес и падал в крэш-луп на плейсхолдере из `.env.otel`; его читает проверка [11/15] |
| `oidc/config.json` | `ozm-oidc`, `/etc/oidc` | мок Цифрового профиля: тестовые пользователи с claim `portal_code` |
| `.env.app`, `.env.pg`, `.env.smtp`, `.env.oidc`, `.env.otel` | `env_file` сервисов и `--env-file` в `make up` | **сюда не входят** — копируются из `../env.example/`, см. ниже |

## Что подставить и скопировать

| Шаг | Команда или действие | Почему |
|---|---|---|
| 1 | `ozm` во всех файлах каталога | имя роли и БД в `init.sql`, имя сервиса в шапках |
| 2 | `cp ../env.example/.env.* ./` (пять файлов, `.env.ai` — только для AI-слоя) | compose читает `env.local/.env.*`; без `.env.app` цель `up` останавливается с подсказкой |
| 3 | в каждом `.env.*` раскомментировать блок «Локальный стенд» и закомментировать значения контура | локально БД в контейнере без TLS (`PGSSLMODE=disable`, `PGSSLROOTCERT` закомментирован — том с сертификатом в compose тоже), форвард телеметрии выключен, издатель — `https://oidc.localhost/default` |
| 4 | в `.env.pg` задать обе роли: `PG_MIGRATE_USER`/`PG_MIGRATE_PASSWORD` (владелец схемы, он же `POSTGRES_USER` контейнера) и `PGUSER`/`PGPASSWORD` (рантайм), имена разные | `init-roles.sql` останавливается, если роли совпали: рантайм с DDL может снять триггер `deny_mutation` с `audit_log` |
| 5 | в `.env.app` заменить `REPLACE_WITH_COMPOSE_SUBNET` на сеть compose, где живёт traefik: `docker network inspect ozm_ozm-net --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}'` (сеть создаётся первым `up`, поэтому шаг делается после него) | nginx фронта доверяет `X-Forwarded-For` только из этой сети; подсеть Compose выдаёт из пула Docker, поэтому числа в шаблоне нет. Не заполнено — работает дефолт образа `127.0.0.1/32`: realip выключен, клиентским адресом остаётся адрес прокси, локально это безвредно |
| 6 | в `oidc/config.json` заменить `REPLACE_WITH_PORTAL_CODE_*` на коды ролей продукта | роли — из таблицы «маршрут → роли» (`policy.go`), в источниках шаблона их нет |
| 7 | `git check-ignore infra/env.local/traefik/certs/local.key` | ключ обязан быть в `.gitignore` репозитория Infra (`templates/code/gitignore`); хук `detect-private-key` — вторая линия |

## Как поднять и проверить

```bash
make -C infra up                       # сертификат, затем compose up с --env-file на каждый .env.*
curl -k https://api.localhost/healthz  # 200 от ozm-api
curl -k https://api.localhost/readyz   # 200 только после OIDC discovery к моку и БД
open https://app.localhost             # SPA; браузер один раз попросит доверять сертификату
make -C infra down                     # остановить; тома и данные локальной БД остаются
make -C infra reset-data CONFIRM=yes   # остановить и удалить тома — init.sql отработает заново
```

Порты стенда на хосте: вход прокси `:80`/`:443`, прямой вход `web` — `127.0.0.1:8088`
(`WEB_HOST_IP`/`WEB_HOST_PORT` в `.env.app`); всё остальное — `127.0.0.1:5432`
(БД), `127.0.0.1:5556` (мок Цифрового профиля), `127.0.0.1:2525` и
`127.0.0.1:8025` (Mailpit), `127.0.0.1:8090` (панель traefik). Коллектор OTel
на хост не публикуется: телеметрия — `docker compose logs ozm-otel`;
`/metrics` бэкенда (`:9090`) виден только коллектору внутри сети compose.

## Стенд без корпоративного прокси

Стенд поднимается на ноутбуке без прокси-реестра (решение D8): у всех
образов compose дефолт `${DOCKER_PROXY_HOST_1:-docker.io}`, мок Цифрового
профиля берётся из `${OIDC_MOCK_IMAGE:-ghcr.io/…}`, а `make -C infra build`
собирает `api` и `web` набором `local` — оба `FROM` через `docker.io`,
рантайм `api` — `alpine` (с оболочкой; это стенд, не поставка). Набор `corp`
(distroless через прокси) передаёт `ci/build.yaml`; локально —
`make -C infra build REGISTRY_PROFILE=corp DOCKER_PROXY_HOST_1=<прокси>`.
Стенд занимает `:80` и `:443` — второй стенд на той же машине не поднимется.

## Чек-лист

- [ ] `make -C infra up` проходит без ручных шагов после копирования `.env.*`.
- [ ] `traefik`, `oidc` и `mailpit` не упоминаются в `env.stage` и `env.prod`: `grep -rniE
      "traefik|mock-oauth2|mailpit" infra/env.stage infra/env.prod` — пусто.
- [ ] Без профиля compose публикует на хост только вход `web`: `docker compose -f infra/docker-compose.yaml
      config | grep -c published` → `1`; с `COMPOSE_PROFILES=local` у всех портов, кроме `:80`/`:443`, стоит
      `host_ip: 127.0.0.1`.
- [ ] `diff infra/env.local/otel/config.yaml infra/observability/otel-collector.yaml` показывает только шапку,
      блок `exporters.otlp/external` и экспортёры пайплайнов.
- [ ] Локальный конфиг коллектора валиден с окружением стенда: `docker run --rm --env-file
      infra/env.local/.env.otel -v "$PWD/infra/env.local/otel/config.yaml:/etc/otel/local.yaml"
      otel/opentelemetry-collector-contrib:0.111.0 validate --config=/etc/otel/local.yaml` — код 0 и пустой
      вывод (тот же результат и на 0.158.0).
- [ ] В `postgres/init.sql` нет `CREATE EXTENSION`, которого нет в конфигурации managed-кластера контура.
- [ ] `local.crt` и `local.key` не отслеживаются git.
- [ ] Две роли БД: `psql "host=127.0.0.1 user=<PGUSER> dbname=<PGDATABASE>" -c 'DROP TRIGGER audit_log_deny_mutation ON audit_log'` — `permission denied`.
- [ ] `docker compose config` у `ozm-otel` показывает `OTLP_ENDPOINT` в `environment`; `9090` есть в `expose` у `api` и нет в `ports`.
- [ ] `docker exec ozm-web cat /etc/nginx/conf.d/realip.conf` печатает `set_real_ip_from` с сетью из `TRUSTED_PROXY_CIDR`.

## Открытые вопросы

- Допустим ли traefik как локальный dev-прокси с точки зрения аудита ИБ: норма 01 нормирует только nginx (по
  умолчанию) и Envoy (запрещён), а оговорка «только локально» для Envoy отступлением быть не перестаёт.
  Подтвердить у команды платформы; запасной вариант — nginx и в `env.local`.
- Какие расширения включены в конфигурации managed-кластера контуров — список нужен, чтобы локальный
  `init.sql` не включал лишнего. Подтвердить у службы эксплуатации.
- Коды ролей для мока Цифрового профиля берутся из RBAC продукта; эталонный набор тестовых пользователей для приёмки в источниках не описан.
- `REPLACE_WITH_DOCKER_PROXY_HOST`: хост корпоративного прокси-реестра для набора `corp` (`Makefile`,
  `ci/build.yaml`) — выдаёт служба эксплуатации; в источниках только правило «через прокси», без адреса.
- `REPLACE_WITH_LB_CIDR`: сеть балансировщика контура для `TRUSTED_PROXY_CIDR` в `env.<контур>/.env.app` — у
  службы эксплуатации; в наборе значения нет. Локальный `REPLACE_WITH_COMPOSE_SUBNET` открытым вопросом не
  является: значение берётся с машины разработчика шагом 5 выше.
- Образ мока Цифрового профиля под профилем `oidc-mock` на stage: путь через прокси
  (`OIDC_MOCK_IMAGE=<прокси>/ghcr.io/navikt/mock-oauth2-server:2.1.10`) подтвердить у эксплуатации — форма
  пути у прокси-реестра в источниках не зафиксирована.
