# Шаблон скилла tnlife-miniapp-engineering: Makefile инфраструктуры продукта.
# Сделан по корпоративному шаблону поставки (01-corp-standard.md): скрипты
# up.sh и build.sh свёрнуты в цели up и build, чтобы стенд S0 поднимался одним
# файлом без вспомогательных скриптов. Подставьте ozm (везде, где он
# встречается) и сверьте пути в блоке «Настройки».
#
# КУДА КЛАСТЬ: infra/Makefile. Пути в целях отсчитываются от infra/, поэтому
# цели зовут из корня рабочего каталога через -C: `make -C infra gen`,
# `make -C infra up`. Голое `make gen` из корня НЕ работает (02 §2).
#
# ЕДИНЫЙ ВХОД СТЕКА — цель up, другого входа набор не поставляет:
#   локальный стенд: make -C infra up                     (ENV_DIR=env.local)
#   контур:          make -C infra up ENV_DIR=env.stage
# Профиль compose цель подставляет сама (переменная COMPOSE_PROFILES ниже),
# поэтому приставка COMPOSE_PROFILES=local в команде не нужна. Тот же
# вызов стоит в cloud-init (cloud-init/vm.yaml.tmpl, скрипт up-app.sh):
# отдельного infra/up.sh набор не поставляет — он свёрнут в эту цель.
#
# Отступы в рецептах — ТАБУЛЯЦИЯ. Редактор, заменивший её пробелами, ломает
# файл: make отвечает «missing separator».
#
# Проверка без Docker: `make -C infra -n up build` печатает команды, ничего
# не запуская; `make -C infra -n up ENV_DIR=env.stage` показывает, что на
# контуре сертификат не генерируется и профиль стенда не включается;
# `make -C infra -n build REGISTRY_PROFILE=corp` — оба FROM пойдут через прокси.
# Список целей — `make -C infra help`.
#
# ДАННЫЕ: `down` тома НЕ трогает — стек останавливается, локальная БД
# переживает down и следующий up. Удаляет тома только `reset-data`, и только
# с явным CONFIRM=yes: `make -C infra reset-data CONFIRM=yes`. `down -v` по
# умолчанию молча уносил бы данные стенда при каждой остановке.

# ─── Настройки: правьте только этот блок ─────────────────────────────────────
SERVICE              := ozm

# Исходный конфиг коллектора (08 §2) и каталог окружения. ENV_DIR задаёт
# контур и переопределяется в командной строке: `make -C infra up
# ENV_DIR=env.stage`. Каталог конфига коллектора выводится из него же — это
# вторая переменная-каталог в compose, и забытая, она оставляет коллектор с
# локальным конфигом на контуре.
OTEL_SRC             := observability/otel-collector.yaml
ENV_DIR              := env.local
OTEL_CONFIG_DIR      := ./$(ENV_DIR)/otel
# Самоподписанный сертификат нужен только прокси локального стенда, поэтому
# каталог сертификатов закреплён за env.local и не следует за ENV_DIR.
CERT_DIR             := env.local/traefik/certs

# Сборка образов: два набора образов — один Dockerfile (решение D8, шапка
# Dockerfile.backend). На рабочей машине корпоративного прокси нет, и путь
# <прокси>/gcr.io/distroless/… не существует, поэтому набор local тянет всё с
# docker.io, а рантайм api — alpine; набор corp идёт через прокси (хост выдаёт
# служба эксплуатации: прямые pull на ВМ закрыты, 01 §«ЗАПРЕЩЕНО») с рантаймом
# distroless. Набор corp передаёт ci/build.yaml — единственный путь образа на
# контур (§2.1); локально он нужен, только чтобы проверить сборку через прокси:
#   make -C infra build                                                     # local
#   make -C infra build REGISTRY_PROFILE=corp DOCKER_PROXY_HOST_1=<прокси>   # corp
# Реестр образов — тот же, что в compose. Образ мока Цифрового профиля compose
# берёт из OIDC_MOCK_IMAGE окружения (дефолт в docker-compose.yaml).
# DOCKER_REGISTRY тоже принадлежит набору, а не общей части: имя реестра
# попадает в ТЕГ образа, и плейсхолдер в теге ломает сборку не сообщением про
# незаполненное значение, а докеровским «repository name must be lowercase» —
# в наборе local плейсхолдера здесь быть не должно. Набор local складывает
# образы под именем localhost/ozm-…: имя валидное, никуда не пушится
# (цель build не пушит вовсе), и compose поднимает те же теги — переменная
# уходит ему через export ниже. Реестр контура задаёт ci/build.yaml
# переменной окружения, и она перебивает оба дефолта (?=).
# Как проверить: `make -C infra build` на свежем каркасе, без единой
# подстановки, доходит до docker build (проверено на каркасе набора).
IMAGE_TAG            ?= local
REGISTRY_PROFILE     ?= local
ifeq ($(REGISTRY_PROFILE),corp)
DOCKER_REGISTRY      ?= REPLACE_WITH_IMAGE_REGISTRY
DOCKER_PROXY_HOST_1  ?= REPLACE_WITH_DOCKER_PROXY_HOST
RUNTIME_IMAGE        ?= gcr.io/distroless/static-debian12:nonroot
else ifeq ($(REGISTRY_PROFILE),local)
DOCKER_REGISTRY      ?= localhost
DOCKER_PROXY_HOST_1  ?= docker.io
RUNTIME_IMAGE        ?= alpine:3.22.1
else
$(error REGISTRY_PROFILE=$(REGISTRY_PROFILE): допустимы local и corp)
endif

# Токен корпоративного npm-реестра для установки кита. По норме кит ставится из
# реестра (01 «Стек», 05 «Подключение кита и моста»), и токен живёт только в
# переменной окружения — в образ он уходит секретом сборки, не аргументом.
# Переменная не задана — секрет не передаётся: так собирается проект, где кит
# вендорен каталогом uikit/ по ADR.
ifdef GITLAB_NPM_TOKEN
NPM_SECRET_ARG := --secret id=npm_token,env=GITLAB_NPM_TOKEN
else
NPM_SECRET_ARG :=
endif

# Имя compose-проекта фиксируем явно: по умолчанию Compose берёт его из имени
# каталога, а не-ASCII имя схлопывается в пустое, и Compose падает.
COMPOSE_PROJECT_NAME ?= $(SERVICE)
# ─────────────────────────────────────────────────────────────────────────────

# Профиль compose. Сервисы стенда — прокси, мок Цифрового профиля, мок SMTP —
# закрыты `profiles: ["local"]` и без профиля не создаются. Профиль зашит в
# цель up, чтобы локальный стенд поднимался одной командой; на контуре он
# пустой, и сервисы стенда туда не уезжают, даже если compose-файл уехал
# целиком. Перекрывается из окружения — например `COMPOSE_PROFILES=oidc-mock`
# для мока Цифрового профиля на stage до ответа ЦП (03 §8).
ifeq ($(ENV_DIR),env.local)
COMPOSE_PROFILES ?= local
else
# Вне локального стенда из окружения принимается только oidc-mock (мок
# Цифрового профиля на stage до ответа ЦП, 03 §8). Любой другой профиль —
# прежде всего local с прокси, базой и моком почты — сбрасывается: иначе
# `COMPOSE_PROFILES=local make up ENV_DIR=env.prod` поднял бы на боевой ВМ
# traefik с docker.sock, postgres и mailpit.
ifneq ($(filter-out oidc-mock,$(COMPOSE_PROFILES)),)
$(warning COMPOSE_PROFILES=$(COMPOSE_PROFILES) на контуре $(ENV_DIR) сброшен: вне env.local допустим только oidc-mock)
override COMPOSE_PROFILES :=
endif
endif

# Compose читает эти переменные из окружения процесса, а не из env_file
# сервисов, — экспортируем, чтобы `make up` видел тот же тег, что `make build`.
# ENV_DIR и OTEL_CONFIG_DIR обязаны быть здесь: их compose подставляет в
# env_file и в монтирование конфига коллектора, и без экспорта стек на любом
# контуре поднимется с окружением env.local (см. шапку docker-compose.yaml).
export IMAGE_TAG DOCKER_REGISTRY DOCKER_PROXY_HOST_1 ENV_DIR OTEL_CONFIG_DIR COMPOSE_PROFILES

# Все .env.* окружения передаются как --env-file: только так Compose раскрывает
# ${PGUSER} и прочие подстановки в самом compose-файле (см. комментарий у
# сервиса postgres в docker-compose.yaml), а не только внутри контейнеров.
ENV_FILES     := $(wildcard $(ENV_DIR)/.env.*)
ENV_FILE_ARGS := $(foreach f,$(ENV_FILES),--env-file $(f))
COMPOSE_ARGS  := -p $(COMPOSE_PROJECT_NAME) -f docker-compose.yaml
# RUNTIME_IMAGE нужен только образу api: у web оба базовых образа с docker.io,
# а неиспользованный build-arg BuildKit печатает предупреждением.
BUILD_ARGS_API := --build-arg DOCKER_PROXY_HOST_1=$(DOCKER_PROXY_HOST_1) --build-arg RUNTIME_IMAGE=$(RUNTIME_IMAGE)
BUILD_ARGS_WEB := --build-arg DOCKER_PROXY_HOST_1=$(DOCKER_PROXY_HOST_1)

.PHONY: gen otel-sync up down reset-data build compliance lint test help

## gen: разложить оба зеркала OpenAPI из источника (пути — в tests/openapi-gate.sh)
gen:
	@bash tests/openapi-gate.sh gen
	@echo "[gen] Шлюз CI — make -C infra gen && git diff --exit-code"

## otel-sync: разложить исходный конфиг коллектора в env.stage и env.prod
otel-sync:
	@mkdir -p env.stage/otel env.prod/otel
	@echo "[otel-sync] $(OTEL_SRC) → env.stage/otel/config.yaml, env.prod/otel/config.yaml"
	@cp $(OTEL_SRC) env.stage/otel/config.yaml
	@cp $(OTEL_SRC) env.prod/otel/config.yaml
	@echo "[otel-sync] env.local/otel/config.yaml не трогаем — он отличается экспортёрами (08 §2). Дрейф ловит git diff --exit-code"

# Предусловие цели up. Самоподписанный сертификат генерируется только для
# локального стенда: на контуре TLS терминирует nginx контура, и генерация
# ключа на боевой ВМ — лишнее действие с приватным ключом.
ifeq ($(ENV_DIR),env.local)
UP_PREREQ := $(CERT_DIR)/local.crt
else
UP_PREREQ :=
endif

## up: поднять стек контура — по умолчанию локальный стенд, контур задаётся ENV_DIR=env.stage
up: $(UP_PREREQ)
	@test -f $(ENV_DIR)/.env.app || { \
	  echo "[up] Нет $(ENV_DIR)/.env.app. Скопируйте env.example/.env.* в $(ENV_DIR)/; для env.local раскомментируйте в них блоки «Локальный стенд»"; \
	  exit 1; }
# Незаполненный REPLACE_WITH_* в АКТИВНОЙ строке (закомментированные —
# документация, их не смотрим) роняет стек не здесь, а внутри контейнеров и
# по-разному: TRUSTED_PROXY_CIDR — `nginx: [emerg] host not found in
# set_real_ip_from` и крэш-луп web, SESSION_SECRET и ENCRYPTION_KEY — отказ
# конфигурации api на старте. Разбирать это по `docker compose logs` дороже,
# чем прочитать одну строку здесь. Полную проверку файлов окружения по всем
# контурам делает tests/check-env.sh; тут — только предохранитель цели up.
# Как проверить: `make -C infra up` на свежем каркасе печатает список
# незаполненных ключей и выходит с кодом 1, не создавая контейнеров.
	@left=$$(grep -hE '^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*=.*REPLACE_WITH_' $(ENV_DIR)/.env.* 2>/dev/null | sed 's/=.*//;s/^[[:space:]]*//' | sort -u); \
	  if [ -n "$$left" ]; then \
	    echo "[up] В $(ENV_DIR) остались незаполненные значения — подставьте их до подъёма стека:"; \
	    echo "$$left" | sed 's/^/  - /'; \
	    echo "[up] Что куда подставлять: env.local/README.md для стенда, tests/check-env.sh — обязательность по контурам"; \
	    exit 1; \
	  fi
ifneq ($(ENV_DIR),env.local)
# Контур: PGSSLMODE=verify-full требует корневой сертификат managed PG на
# диске и в томе (docker-compose.yaml, сервис api). Без файла pgx падает в
# ParseConfig, без тома — то же самое уже внутри контейнера; ловим до compose.
	@if grep -qE '^PGSSLROOTCERT=' $(ENV_DIR)/.env.pg 2>/dev/null; then \
	  test -f $(ENV_DIR)/certs/pg-root.crt || { \
	    echo "[up] $(ENV_DIR)/.env.pg задаёт PGSSLROOTCERT, а файла $(ENV_DIR)/certs/pg-root.crt нет: положите корневой сертификат managed PG (он публичный, лежит в репозитории)"; \
	    exit 1; }; \
	  grep -qE '^[[:space:]]*- \$$\{ENV_DIR:-env\.local\}/certs/pg-root\.crt:' docker-compose.yaml || { \
	    echo "[up] том с корневым сертификатом у $(SERVICE)-api в docker-compose.yaml закомментирован: раскомментируйте строки volumes и certs/pg-root.crt"; \
	    exit 1; }; \
	fi
endif
	@echo "[up] ENV_DIR=$(ENV_DIR) OTEL_CONFIG_DIR=$(OTEL_CONFIG_DIR) COMPOSE_PROFILES=$(COMPOSE_PROFILES)"
	@echo "[up] docker compose $(COMPOSE_ARGS) up -d"
	@docker compose $(COMPOSE_ARGS) $(ENV_FILE_ARGS) up -d
	@echo "[up] Стек контура $(ENV_DIR) поднят."
ifeq ($(ENV_DIR),env.local)
	@echo "[up] Локальные адреса:"
	@echo "  https://app.localhost    $(SERVICE)-web (SPA)"
	@echo "  https://api.localhost    $(SERVICE)-api (/api/v1, /healthz, /readyz, /metrics)"
	@echo "  https://oidc.localhost   мок Цифрового профиля"
	@echo "  http://localhost:8090    панель traefik"
	@echo "  http://localhost:8025    Mailpit"
	@echo "  Порты БД, мока Цифрового профиля и Mailpit привязаны к 127.0.0.1; коллектор OTel портов на хост не публикует — телеметрия в docker compose logs $(SERVICE)-otel"
endif

# Приватных ключей в репозитории нет: сертификат генерируется при первом
# запуске, браузер один раз попросит подтвердить доверие. local.crt и local.key
# ОБЯЗАНЫ быть в .gitignore репозитория Infra (проверка — `git check-ignore`
# в README), хук detect-private-key из pre-commit-config.yaml — страховка.
$(CERT_DIR)/local.crt:
	@echo "[up] Генерирую self-signed сертификат для *.localhost → $(CERT_DIR)"
	@mkdir -p $(CERT_DIR)
	@openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
	  -keyout $(CERT_DIR)/local.key -out $(CERT_DIR)/local.crt \
	  -subj "/CN=localhost/O=$(SERVICE) local" \
	  -addext "subjectAltName=DNS:localhost,DNS:*.localhost" >/dev/null 2>&1
	@chmod 600 $(CERT_DIR)/local.key

## down: остановить стек compose-проекта; тома остаются — данные локальной БД переживают down и следующий up
down:
	@docker compose $(COMPOSE_ARGS) down

# Удаление томов вынесено из down осознанно: `down -v` без предупреждения
# уносил данные стенда при каждой остановке. Здесь два предохранителя:
# цель работает только на env.local (на контуре БД managed, томов с данными у
# compose нет — 01 «Стек») и только с явным CONFIRM=yes в командной строке.
## reset-data: down плюс удаление томов (init.sql отработает заново); только env.local и только с CONFIRM=yes
reset-data:
ifneq ($(ENV_DIR),env.local)
	@echo "[reset-data] Только локальный стенд: на контуре $(ENV_DIR) БД managed, томов с данными у compose нет"; exit 1
endif
	@test "$(CONFIRM)" = "yes" || { \
	  echo "[reset-data] Удалит тома compose-проекта $(COMPOSE_PROJECT_NAME): данные локальной БД пропадут, вернуть их будет нечем."; \
	  echo "[reset-data] Подтвердите явно: make -C infra reset-data CONFIRM=yes"; \
	  exit 1; }
	@docker compose $(COMPOSE_ARGS) down -v

## build: собрать образы api и web набором REGISTRY_PROFILE (local по умолчанию, corp — через прокси); контекст web — КОРЕНЬ рабочего каталога
build:
	@echo "[build] набор образов $(REGISTRY_PROFILE): DOCKER_PROXY_HOST_1=$(DOCKER_PROXY_HOST_1) RUNTIME_IMAGE=$(RUNTIME_IMAGE)"
	@echo "[build] $(SERVICE)-api $(IMAGE_TAG)"
	@docker build $(BUILD_ARGS_API) -t $(DOCKER_REGISTRY)/$(SERVICE)-api:$(IMAGE_TAG) -f ../backend/Dockerfile ../backend
	@echo "[build] $(SERVICE)-web $(IMAGE_TAG)"
	@docker build $(BUILD_ARGS_WEB) $(NPM_SECRET_ARG) -t $(DOCKER_REGISTRY)/$(SERVICE)-web:$(IMAGE_TAG) -f ../frontend/Dockerfile ..
	@docker images --filter "reference=$(DOCKER_REGISTRY)/$(SERVICE)-*"

## compliance: 15 статических проверок корп. шаблона
compliance:
	@bash tests/run.sh compliance

## lint: compliance плюс golangci-lint по бэкенду — полный набор 02 §12, ноль замечаний
lint: compliance
	@cd ../backend && golangci-lint run ./...

## test: compliance, smoke по поднятому стенду и файлы окружения по контурам
test:
	@bash tests/run.sh compliance
	@bash tests/run.sh smoke
	@bash tests/check-env.sh

## help: список целей
help:
	@grep -E '^## ' Makefile | sed 's/^## /  /' | column -t -s ':'
