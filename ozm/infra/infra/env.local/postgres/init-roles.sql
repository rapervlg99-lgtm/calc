-- Шаблон скилла tnlife-miniapp-engineering: две роли БД на локальном стенде.
-- Подставлять нечего: имена и пароли приходят из env.local/.env.pg через
-- окружение контейнера (\getenv, psql 15+; образ postgres:16 в compose).
--
-- КУДА КЛАСТЬ: infra/env.local/postgres/init-roles.sql. Каталог смонтирован в
-- /docker-entrypoint-initdb.d контейнера ozm-postgres; entrypoint образа
-- postgres скармливает *.sql psql при ПЕРВОМ создании тома, в алфавитном
-- порядке — этот файл идёт раньше init.sql. Изменили — `make -C infra
-- reset-data CONFIRM=yes`, затем снова `make -C infra up`.
--
-- ПОЧЕМУ SQL, А НЕ init-roles.sh: shell-скрипт из bind-mount на Docker
-- Desktop (macOS) entrypoint пытается ИСПОЛНИТЬ, а том смонтирован noexec —
-- «bad interpreter: Permission denied», роль не создаётся (проверено
-- прогоном на каркасе набора). Файл .sql идёт через psql -f и от прав на
-- исполнение не зависит; значения окружения читает \getenv.
--
-- ЗАЧЕМ ДВЕ РОЛИ (решение D3). Иммутабельность audit_log держит триггер
-- deny_mutation (0001_init.up.sql), а триггер снимает владелец таблицы. Если
-- миграции и рантайм идут под одной ролью PGUSER, рантайм — владелец и может
-- DROP TRIGGER: «иммутабельность» держится на дисциплине. Поэтому:
--   - PG_MIGRATE_USER / PG_MIGRATE_PASSWORD — роль-владелец схемы: под ней
--     migrations.Apply создаёт таблицы и триггеры. На локальном стенде это
--     POSTGRES_USER контейнера (docker-compose.yaml), на контурах — вторая
--     роль managed-кластера (заявка в эксплуатацию, s0-requests.md);
--   - PGUSER / PGPASSWORD — роль рантайма: CONNECT, USAGE на схему и DML на
--     таблицы, которые создаёт владелец. DDL у неё нет по построению: CREATE
--     на схему public отозван, владельцем таблиц она не бывает.
-- Ограничения на audit_log (REVOKE UPDATE, DELETE) ставит сама миграция 0001
-- для роли из app.runtime_role — раннер выставляет её перед прогоном.
-- check-env.sh на stage и prod требует PG_MIGRATE_USER ≠ PGUSER; здесь то же
-- правило держит блок DO ниже: совпали — исключение, ON_ERROR_STOP роняет
-- инициализацию. ГРАБЛИ: после отказа контейнер перезапускается (restart:
-- unless-stopped) с уже созданным PGDATA и init-файлы больше не исполняет —
-- БД healthy, а роли рантайма нет, api не подключается («role does not
-- exist»). Ошибка видна в `docker compose logs ozm-postgres`; лечится
-- `make -C infra reset-data CONFIRM=yes` после правки .env.pg (проверено
-- прогоном на каркасе набора).
--
-- Как проверить (после `make -C infra up`):
--   psql "host=127.0.0.1 user=<PGUSER> dbname=<PGDATABASE>" \
--     -c 'DROP TRIGGER audit_log_deny_mutation ON audit_log'   -- permission denied
--   psql … -c 'CREATE TABLE t(id int)'                          -- permission denied
--   psql … -c '\dp entities'   -- у роли рантайма arwd, владелец — роль миграций

-- Переменная окружения не задана — \getenv оставляет psql-переменную пустой,
-- и первый же :'…' даёт синтаксическую ошибку: инициализация падает громко.
\getenv runtime_role PGUSER
\getenv runtime_password PGPASSWORD
\getenv owner_role POSTGRES_USER
\getenv dbname POSTGRES_DB

-- Роли обязаны различаться. Внутри $$ psql переменные не подставляет,
-- поэтому значения передаются через set_config.
SELECT set_config('init.runtime_role', :'runtime_role', false),
       set_config('init.owner_role', :'owner_role', false);
DO $$
BEGIN
  IF current_setting('init.runtime_role') = current_setting('init.owner_role') THEN
    RAISE EXCEPTION 'init-roles: PGUSER (%) совпадает с ролью-владельцем POSTGRES_USER — рантайм получил бы DDL. Разведите PGUSER и PG_MIGRATE_USER в env.local/.env.pg',
      current_setting('init.runtime_role');
  END IF;
END
$$;

-- Роль рантайма: LOGIN без CREATEDB, CREATEROLE и SUPERUSER. %I и %L
-- экранируют идентификатор и пароль, \gexec исполняет собранную команду.
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'runtime_role', :'runtime_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'runtime_role') \gexec

-- Вход в базу — только явным грантом, не через PUBLIC.
REVOKE ALL ON DATABASE :"dbname" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"dbname" TO :"runtime_role";

-- Схема: пользоваться можно, создавать в ней — нет (DDL только у владельца).
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO :"runtime_role";

-- Таблицы и последовательности, которые владелец создаст миграциями, роль
-- рантайма получает по умолчанию: DML без DDL. UPDATE и DELETE на audit_log
-- отзывает миграция 0001 (append-only), триггер deny_mutation — вторая линия.
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner_role" IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"runtime_role";
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner_role" IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO :"runtime_role";

\echo init-roles: роль рантайма :runtime_role создана, владелец схемы — :owner_role
