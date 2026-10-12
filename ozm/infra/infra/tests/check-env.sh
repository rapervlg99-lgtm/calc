#!/usr/bin/env bash
# Шаблон скилла tnlife-miniapp-engineering. Проверка файлов окружения по всем
# контурам — формат, полнота, заполненность и роли БД, девять проверок — по
# проверке [3/15] run.sh и требованиям readme-deploy.md §1.2 и §2.3. Одна и та
# же во всех формах продукта (мини-апп, веб- и API-сервис). Скопируйте в
# infra/tests/check-env.sh (scaffold.sh кладёт его сам), подставьте ozm,
# список контуров, канонический набор .env.* и обязательные ключи в блоке
# настроек.
#
# Использование:
#   bash infra/tests/check-env.sh            # все контуры
#   bash infra/tests/check-env.sh env.stage  # один контур по имени каталога
#   bash infra/tests/check-env.sh --help     # эта шапка
#
# Печатает по строке на проверку с PASS, FAIL или SKIP (WARN — не валит), в
# конце — сводку. Код возврата: 0 — FAIL нет; 1 — есть FAIL; 2 — ошибка
# аргументов (неизвестное имя контура, лишний аргумент). Опечатка в вызове
# отчётом о репозитории быть не должна: иначе `check-env.sh env.stag`
# напечатал бы «ни один контур не найден» с кодом 1 и выглядел бы как
# реальная проблема дерева.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ─────────────────────────────────────────────────────────────────────────────
# НАСТРОЙКИ ПРОЕКТА — правьте только этот блок
# ─────────────────────────────────────────────────────────────────────────────

# Базовое имя сервиса — используется только в заголовке вывода.
SERVICE="${SERVICE:-ozm}"

# Корень репозитория. По умолчанию — два уровня вверх от скрипта (infra/tests/).
REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"

# Каталог, где лежат контуры.
ENV_ROOT="${REPO_ROOT}/infra"

# Контуры. Порядок важен только для вывода.
ENV_DIRS=(
  "env.local"
  "env.stage"
  "env.prod"
)

# Контуры, где секретов в git не бывает — только плейсхолдеры.
ENV_SECRET_DIRS=(
  "env.stage"
  "env.prod"
)

# Канонический набор файлов. В каждом контуре лежит ровно один и тот же набор.
# Заводите шестую группу — допишите её сюда и создайте файл во всех контурах.
ENV_FILES=(
  ".env.app"
  ".env.pg"
  ".env.smtp"
  ".env.oidc"
  ".env.otel"
)

# Ключи, которые обязаны быть раскомментированы в каждом контуре.
# Имена — только стандартные из readme-deploy.md §1.2.
#
# ГРАНИЦА ПРОВЕРКИ. Сюда НЕ добавляются переменные продукта (класс 2:
# APP_ENV, SESSION_*, CORS_ALLOWED_ORIGINS, MAX_JSON_BODY, AI_*,
# BRIDGE_ENABLED и прочие): их состав задаёт продукт, а не корпоративная
# норма, и гейт на них означал бы, что скрипт знает чужой контракт. Что
# продуктовый флаг реально читается конфигом — проверяет тест приложения,
# а не этот скрипт (references/03-auth-profile.md, раздел 8).
# Единственное исключение — проверка [9/9] ниже: роль миграций
# PG_MIGRATE_USER (класс 2) на stage и prod обязана отличаться от PGUSER.
# Это решение D3 (references/12-forks-and-adr.md, «Решения по сборке
# набора»): без него блок REVOKE/GRANT первой миграции мёртв, а рантайм-роль
# владеет audit_log и может снять триггер append-only.
# OIDC_TRUSTED_ISSUER — класс 1 по §12 корпоративного шаблона (перечислен
# поимённо в 01-corp-standard.md, «Файлы окружения»), и конфиг приложения
# отказывает на старте без него вне local (templates/code/config.go): гейт без
# этого имени был бы зелёным над окружением, на котором бинарь не
# поднимается. Обобщения «все OIDC_* — класс 1» здесь нет: список закрытый и
# поимённый, остальные OIDC_* и PG_MIGRATE_* — класс 2. Список одинаков во
# всех формах продукта; нужен ли класс 1 целиком API-сервису без
# пользовательского входа — открытый вопрос 01-corp-standard.md.
REQUIRED_KEYS=(
  PGHOST PGPORT PGDATABASE PGUSER PGPASSWORD PGSSLMODE
  OIDC_ISSUER OIDC_CLIENT_ID OIDC_CLIENT_SECRET OIDC_REDIRECT_URL
  OIDC_SCOPES OIDC_PORTAL_CODE_CLAIM OIDC_TRUSTED_ISSUER
  OTEL_EXPORTER_OTLP_ENDPOINT OTEL_SERVICE_NAME OTEL_RESOURCE_ATTRIBUTES
)

# Ключи КЛАССА 2, обязательные по норме на всех контурах, — тоже закрытый
# поимённый список, а не префикс: гейт не знает чужой контракт (см. границу
# проверки выше), но эти имена норма называет сама.
#   - TRUSTED_PROXY_CIDR: доверенные прокси nginx. Не задан — образ web едет с
#     дефолтом 127.0.0.1/32 (ENV в Dockerfile фронта, ${TRUSTED_PROXY_CIDR:-…}
#     в compose), realip выключен, X-Real-IP несёт адрес балансировщика — и
#     весь rate-limit входа сидит на одном ключе: запросы сверх
#     RATE_LIMIT_AUTH_PER_MIN (дефолт заготовки — templates/code/config.go) от
#     одного клиента блокируют вход всем пользователям сразу, а в логе ИБ у
#     всех один и тот же client_ip.
REQUIRED_KEYS_PRODUCT=(
  TRUSTED_PROXY_CIDR
)

# Ключи, значение которых обязано быть ОДНОЙ сетью в CIDR-нотации. Широкая
# сеть — тот самый антипаттерн, от которого избавился realip.conf.template:
# доверие всей приватной сети возвращает клиенту возможность подставить
# X-Forwarded-For и получить чужой адрес в логе и свою корзину rate-limit.
# Плейсхолдер PLACEHOLDER_PREFIX* в stage и prod стоит по норме ([8/9]) и
# формату не проверяется — его подставляет служба эксплуатации.
CIDR_KEYS=(
  TRUSTED_PROXY_CIDR
)
CIDR_FORMAT='^([0-9]{1,3}\.){3}[0-9]{1,3}/[0-9]{1,2}$|^[0-9A-Fa-f:]+/[0-9]{1,3}$'
CIDR_FORBIDDEN='^(0\.0\.0\.0/0|::/0|10\.0\.0\.0/8|172\.16\.0\.0/12|192\.168\.0\.0/16)$'

# Ключи ролей БД для проверки [9/9]: рантайм и владелец схемы (миграции).
PG_RUNTIME_USER_KEY="PGUSER"
PG_MIGRATE_USER_KEY="PG_MIGRATE_USER"

# Имена, от которых отказались: «своё имя = отдельный спринт миграции».
# Формат: «LEGACY=чем заменить». Список — зеркало таблицы синонимов
# 01-corp-standard.md «Файлы окружения»; правятся вместе.
#   - OIDC_EXPECTED_ISSUER — не используется: каноническое имя
#     OIDC_TRUSTED_ISSUER назначено §12 корп. шаблона (01-corp-standard.md,
#     «Файлы окружения»);
#   - OIDC_INSECURE_SKIP_VERIFY — имя читается и как TLS-skip под
#     самоподписанный мок (такой режим в норме не используется), и как отказ
#     от проверки подписи; отказ от проверки ПОДПИСИ токена называется
#     OIDC_TOKEN_SIGNATURE_UNVERIFIED — одно имя не может значить две разные
#     вещи (таблица синонимов 01-corp-standard.md, «Файлы окружения»).
LEGACY_KEYS=(
  "DATABASE_URL=PGHOST + PGUSER + PGPASSWORD + PGDATABASE + PGPORT + PGSSLMODE"
  "STORAGE_DSN=те же PG*"
  "SSO_JWKS_URL=OIDC_JWKS_URL"
  "SSO_AUDIENCE=OIDC_AUDIENCE"
  "SSO_TRUSTED_ISS=OIDC_TRUSTED_ISSUER"
  "OIDC_EXPECTED_ISSUER=OIDC_TRUSTED_ISSUER (каноническое имя по §12 корп. шаблона)"
  "OIDC_INSECURE_SKIP_VERIFY=OIDC_TOKEN_SIGNATURE_UNVERIFIED (отказ от проверки подписи токена; старое имя читается и как TLS-skip, такой режим в норме не используется)"
)

# Ключи, значение которых в stage и prod — только плейсхолдер.
#
# ГРАНИЦА ПРОВЕРКИ. Контур env.local сознательно НЕ проверяется на
# плейсхолдеры: там стоят настоящие dev-значения, и это норма — стенд
# обязан подниматься одной командой без подстановки. Настоящий секрет,
# по ошибке попавший в env.local, ловит не этот скрипт, а gitleaks в
# pre-commit и в security-workflow (templates/code/lint/gitleaks.toml,
# templates/code/security.yaml). Не переносите проверку на env.local:
# она начнёт падать на рабочем стенде и её отключат целиком.
SECRET_KEY_PATTERN='(PASSWORD|SECRET|TOKEN|KEY|AUTHORIZATION)'

# Префикс плейсхолдера. Подчёркивания обязательны: эвристика секретов ловит
# сплошную строку из 16 символов и более, а REPLACE_WITH_... её не проходит.
PLACEHOLDER_PREFIX="REPLACE_WITH_"

# ─────────────────────────────────────────────────────────────────────────────
# СЛУЖЕБНОЕ — ниже правки не требуются
# ─────────────────────────────────────────────────────────────────────────────

PASS=0
FAIL=0
SKIP=0

_pass() { echo "  [PASS] $1"; PASS=$((PASS + 1)); }
_fail() { echo "  [FAIL] $1"; FAIL=$((FAIL + 1)); }
_skip() { echo "  [SKIP] $1"; SKIP=$((SKIP + 1)); }
_warn() { echo "  [WARN] $1"; }

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "${WORK_DIR}"' EXIT

usage() {
  # Шапка файла до первой непустой строки кода — без привязки к номерам строк.
  awk 'NR > 1 && !/^#/ { exit } NR > 1' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

# Один контур из аргумента либо все контуры из настроек. Имя сверяется со
# списком ENV_DIRS: неизвестное имя — код 2, а не FAIL «контуров нет».
if [[ $# -gt 1 ]]; then
  echo "check-env: ошибка: принимается не больше одного аргумента — имя каталога контура (${ENV_DIRS[*]}) или --help" >&2
  exit 2
fi
if [[ $# -gt 0 ]]; then
  case "$1" in
    -h|--help) usage; exit 0 ;;
  esac
  ARG_KNOWN=0
  for d in ${ENV_DIRS[@]+"${ENV_DIRS[@]}"}; do
    [[ "${d}" == "$1" ]] && ARG_KNOWN=1
  done
  if [[ ${ARG_KNOWN} -eq 0 ]]; then
    echo "check-env: ошибка: неизвестный контур '$1'; допустимы: ${ENV_DIRS[*]} (см. --help)" >&2
    exit 2
  fi
  ENV_DIRS=("$1")
  FILTERED_SECRET_DIRS=()
  for d in ${ENV_SECRET_DIRS[@]+"${ENV_SECRET_DIRS[@]}"}; do
    [[ "${d}" == "$1" ]] && FILTERED_SECRET_DIRS+=("${d}")
  done
  ENV_SECRET_DIRS=(${FILTERED_SECRET_DIRS[@]+"${FILTERED_SECRET_DIRS[@]}"})
fi

# Раскомментированные ключи файла, по одному на строку.
_keys_of_file() {
  grep -E '^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*=' "$1" 2>/dev/null \
    | sed -e 's/^[[:space:]]*//' -e 's/=.*//' \
    || true
}

_value_of_key() {
  # Значение раскомментированного ключа по всем .env.* контура (последнее).
  grep -hE "^[[:space:]]*$2=" "${ENV_ROOT}/$1"/.env.* 2>/dev/null | tail -1 | sed -e 's/^[[:space:]]*//' -e 's/^[^=]*=//' || true
}

# Закомментированные ключи файла: строки вида «# KEY=».
_commented_keys_of_file() {
  grep -E '^[[:space:]]*#[[:space:]]*[A-Za-z_][A-Za-z0-9_]*=' "$1" 2>/dev/null \
    | sed -e 's/^[[:space:]]*#[[:space:]]*//' -e 's/=.*//' \
    || true
}

echo "=== check-env: файлы окружения по контурам (${SERVICE}) ==="
echo ""

# ─── Проверка 1: каталоги контуров на месте ──────────────────────────────────
echo "[1/9] Каталоги контуров существуют"
MISSING_DIRS=""
PRESENT_DIRS=()
for d in ${ENV_DIRS[@]+"${ENV_DIRS[@]}"}; do
  if [[ -d "${ENV_ROOT}/${d}" ]]; then
    PRESENT_DIRS+=("${d}")
  else
    MISSING_DIRS+="${ENV_ROOT}/${d}: каталог не найден"$'\n'
  fi
done
if [[ ${#PRESENT_DIRS[@]} -eq 0 ]]; then
  _fail "Ни один контур не найден в ${ENV_ROOT}"
elif [[ -z "${MISSING_DIRS}" ]]; then
  _pass "Контуры на месте: ${ENV_DIRS[*]}"
else
  _fail "Не хватает контуров:"
  echo "${MISSING_DIRS}" | sed '/^$/d' | sed 's/^/    - /'
fi

# ─── Проверка 2: набор файлов одинаков во всех контурах ──────────────────────
# Базовые группы обязательны везде. Сверх них норма (01-corp-standard.md, раздел «Файлы окружения»)
# разрешает СВОИ группы продукта тем же форматом — AI-слой держит переменные в
# .env.ai, и для сервисного продукта отсутствие этой группы не пробел. Поэтому
# лишний файл сам по себе не ошибка; ошибка — группа, заведённая в одном
# контуре и забытая в другом: тогда окружение расходится между stage и prod.
echo "[2/9] В каждом контуре лежит один и тот же набор .env.*"
SET_ERRORS=""
EXTRA_GROUPS=""
for d in ${PRESENT_DIRS[@]+"${PRESENT_DIRS[@]}"}; do
  for f in ${ENV_FILES[@]+"${ENV_FILES[@]}"}; do
    [[ -f "${ENV_ROOT}/${d}/${f}" ]] || SET_ERRORS+="${d}/${f}: файл не найден"$'\n'
  done
  while IFS= read -r found; do
    [[ -n "${found}" ]] || continue
    base="$(basename "${found}")"
    known=0
    for f in ${ENV_FILES[@]+"${ENV_FILES[@]}"}; do
      [[ "${base}" == "${f}" ]] && known=1
    done
    [[ ${known} -eq 1 ]] && continue
    case " ${EXTRA_GROUPS} " in
      *" ${base} "*) ;;
      *) EXTRA_GROUPS+="${base} " ;;
    esac
  done < <(find "${ENV_ROOT}/${d}" -maxdepth 1 -name ".env.*" 2>/dev/null)
done
for g in ${EXTRA_GROUPS}; do
  for d in ${PRESENT_DIRS[@]+"${PRESENT_DIRS[@]}"}; do
    [[ -f "${ENV_ROOT}/${d}/${g}" ]] ||
      SET_ERRORS+="${d}/${g}: группа продукта есть в другом контуре, здесь её нет"$'\n'
  done
done
if [[ ${#PRESENT_DIRS[@]} -eq 0 ]]; then
  _skip "Контуров нет — сверять нечего"
elif [[ -z "${SET_ERRORS}" ]]; then
  if [[ -n "${EXTRA_GROUPS}" ]]; then
    _pass "Набор файлов совпадает во всех контурах: ${ENV_FILES[*]} (+ группы продукта: ${EXTRA_GROUPS% })"
  else
    _pass "Набор файлов совпадает во всех контурах: ${ENV_FILES[*]}"
  fi
else
  _fail "Расхождения в наборе файлов:"
  echo "${SET_ERRORS}" | sed '/^$/d' | sed 's/^/    - /'
fi

# ─── Проверка 3: формат файла (§2.3) ─────────────────────────────────────────
echo "[3/9] Формат: первая строка '#', файл оканчивается пустой строкой, после '.env.' нет точек (§2.3)"
FORMAT_ERRORS=""
FILES_SEEN=0
for d in ${PRESENT_DIRS[@]+"${PRESENT_DIRS[@]}"}; do
  while IFS= read -r -d '' f; do
    FILES_SEEN=$((FILES_SEEN + 1))
    rel="${d}/$(basename "${f}")"
    first_line="$(head -1 "${f}")"
    if [[ "${first_line}" != \#* ]]; then
      FORMAT_ERRORS+="${rel}: первая строка не '#' (найдено: '${first_line}')"$'\n'
    fi
    if [[ "$(tail -c1 "${f}" | wc -c)" -eq 0 ]]; then
      FORMAT_ERRORS+="${rel}: файл не оканчивается пустой строкой (пустой файл)"$'\n'
    else
      last_line="$(tail -1 "${f}")"
      if [[ -n "${last_line}" ]]; then
        FORMAT_ERRORS+="${rel}: файл не оканчивается пустой строкой (последняя строка: '${last_line}')"$'\n'
      fi
    fi
    case "$(basename "${f}")" in
      .env.*.*) FORMAT_ERRORS+="${rel}: после '.env.' точек больше быть не должно"$'\n' ;;
    esac
  done < <(find "${ENV_ROOT}/${d}" -maxdepth 1 -name ".env.*" -print0 2>/dev/null)
done
if [[ ${FILES_SEEN} -eq 0 ]]; then
  _skip "Файлы .env.* не найдены — проверять нечего"
elif [[ -z "${FORMAT_ERRORS}" ]]; then
  _pass "Формат соблюдён (проверено файлов: ${FILES_SEEN})"
else
  _fail "Нарушения формата:"
  echo "${FORMAT_ERRORS}" | sed '/^$/d' | sed 's/^/    - /'
fi

# ─── Проверка 4: строки вида KEY=VALUE без угловых плейсхолдеров ─────────────
# Угловые плейсхолдеры <домен контура>, <срок сессии>, <число дней> — это
# незаполненные значения шаблона, а не значения: с ними конфиг приложения
# падает на разборе, а стенд «поднимается» до первого запроса. Они ловятся
# во ВСЕХ контурах, включая env.local, — в отличие от REPLACE_WITH_*, которые
# в stage и prod стоят по норме ([8/9]). Без этой проверки любое VALUE
# проходило бы, и гейт был бы зелёным над неподнимаемым стендом.
echo "[4/9] Строки: KEY=VALUE, ключ латиницей в верхнем регистре, значение без угловых плейсхолдеров <…>"
SYNTAX_ERRORS=""
for d in ${PRESENT_DIRS[@]+"${PRESENT_DIRS[@]}"}; do
  while IFS= read -r -d '' f; do
    rel="${d}/$(basename "${f}")"
    line_no=0
    while IFS= read -r line || [[ -n "${line}" ]]; do
      line_no=$((line_no + 1))
      [[ -z "${line}" ]] && continue
      [[ "${line}" =~ ^[[:space:]]*# ]] && continue
      if [[ ! "${line}" =~ ^[A-Z_][A-Z0-9_]*= ]]; then
        SYNTAX_ERRORS+="${rel}:${line_no}: ожидается KEY=VALUE с ключом [A-Z_][A-Z0-9_]* — '${line}'"$'\n'
        continue
      fi
      value="${line#*=}"
      if [[ "${value}" =~ \<[^\<\>]+\> ]]; then
        SYNTAX_ERRORS+="${rel}:${line_no}: ${line%%=*} — угловой плейсхолдер в активной строке, подставьте значение: '${value}'"$'\n'
      fi
    done <"${f}"
  done < <(find "${ENV_ROOT}/${d}" -maxdepth 1 -name ".env.*" -print0 2>/dev/null)
done
if [[ ${FILES_SEEN} -eq 0 ]]; then
  _skip "Файлы .env.* не найдены — проверять нечего"
elif [[ -z "${SYNTAX_ERRORS}" ]]; then
  _pass "Все строки — комментарий, пустая строка или KEY=VALUE без угловых плейсхолдеров"
else
  _fail "Строки не по формату или с незаполненным значением:"
  echo "${SYNTAX_ERRORS}" | sed '/^$/d' | head -20 | sed 's/^/    - /'
fi

# ─── Проверка 5: полнота контракта окружения ─────────────────────────────────
# Правило §2.3: обязательные раскомментированы, необязательные закомментированы,
# и оператор в каждом контуре видит полный контракт. Значит ключ, раскомментированный
# хоть в одном контуре, есть во всех — либо раскомментированным, либо закомментированным.
echo "[5/9] Ключ, раскомментированный в одном контуре, присутствует во всех (§2.3)"
: >"${WORK_DIR}/keys.union"
for d in ${PRESENT_DIRS[@]+"${PRESENT_DIRS[@]}"}; do
  : >"${WORK_DIR}/keys.${d}"
  : >"${WORK_DIR}/allkeys.${d}"
  while IFS= read -r -d '' f; do
    _keys_of_file "${f}" >>"${WORK_DIR}/keys.${d}"
    _keys_of_file "${f}" >>"${WORK_DIR}/allkeys.${d}"
    _commented_keys_of_file "${f}" >>"${WORK_DIR}/allkeys.${d}"
  done < <(find "${ENV_ROOT}/${d}" -maxdepth 1 -name ".env.*" -print0 2>/dev/null)
  sort -u "${WORK_DIR}/keys.${d}" -o "${WORK_DIR}/keys.${d}"
  sort -u "${WORK_DIR}/allkeys.${d}" -o "${WORK_DIR}/allkeys.${d}"
  cat "${WORK_DIR}/keys.${d}" >>"${WORK_DIR}/keys.union"
done
sort -u "${WORK_DIR}/keys.union" -o "${WORK_DIR}/keys.union"
if [[ ${#PRESENT_DIRS[@]} -lt 2 ]]; then
  _skip "Контуров меньше двух — сравнивать нечего"
else
  KEYSET_ERRORS=""
  for d in ${PRESENT_DIRS[@]+"${PRESENT_DIRS[@]}"}; do
    missing="$(comm -23 "${WORK_DIR}/keys.union" "${WORK_DIR}/allkeys.${d}" | tr '\n' ' ')"
    if [[ -n "${missing// /}" ]]; then
      KEYSET_ERRORS+="${d}: ключей нет ни раскомментированными, ни закомментированными: ${missing}"$'\n'
    fi
  done
  if [[ -z "${KEYSET_ERRORS}" ]]; then
    _pass "Контракт окружения полон во всех контурах"
  else
    _fail "Контур видит не весь контракт:"
    echo "${KEYSET_ERRORS}" | sed '/^$/d' | sed 's/^/    - /'
  fi
fi

# ─── Проверка 6: обязательные ключи раскомментированы и заполнены ────────────
# Два списка: класс 1 (имена корпоративного шаблона) и закрытый поимённый
# список ключей класса 2, обязательных по норме. Плюс формат значений из
# CIDR_KEYS: ключ на месте, но с широкой сетью в значении — это выключенная
# защита, а не заполненный контур.
echo "[6/9] Обязательные ключи присутствуют, раскомментированы и заполнены (CIDR — одной сетью)"
REQUIRED_ERRORS=""
for d in ${PRESENT_DIRS[@]+"${PRESENT_DIRS[@]}"}; do
  for k in ${REQUIRED_KEYS[@]+"${REQUIRED_KEYS[@]}"} \
           ${REQUIRED_KEYS_PRODUCT[@]+"${REQUIRED_KEYS_PRODUCT[@]}"}; do
    if ! grep -qx "${k}" "${WORK_DIR}/keys.${d}" 2>/dev/null; then
      REQUIRED_ERRORS+="${d}: нет обязательного ключа ${k}"$'\n'
    fi
  done
  for k in ${CIDR_KEYS[@]+"${CIDR_KEYS[@]}"}; do
    grep -qx "${k}" "${WORK_DIR}/keys.${d}" 2>/dev/null || continue
    cidr_value="$(_value_of_key "${d}" "${k}")"
    # Плейсхолдер контура — норма ([8/9]), формат не проверяется.
    case "${cidr_value}" in
      *"${PLACEHOLDER_PREFIX}"*) continue ;;
    esac
    if [[ ! "${cidr_value}" =~ ${CIDR_FORMAT} ]]; then
      REQUIRED_ERRORS+="${d}: ${k}='${cidr_value}' — ожидается ОДНА сеть в CIDR-нотации (например 192.0.2.0/24) или плейсхолдер ${PLACEHOLDER_PREFIX}*"$'\n'
    elif [[ "${cidr_value}" =~ ${CIDR_FORBIDDEN} ]]; then
      REQUIRED_ERRORS+="${d}: ${k}='${cidr_value}' — широкий диапазон ЗАПРЕЩЁН: доверие всей приватной сети возвращает подмену X-Forwarded-For (frontend/realip.conf.template)"$'\n'
    fi
  done
done
if [[ ${#PRESENT_DIRS[@]} -eq 0 ]]; then
  _skip "Контуров нет — проверять нечего"
elif [[ -z "${REQUIRED_ERRORS}" ]]; then
  _pass "Все обязательные ключи на месте во всех контурах, значения CIDR — одной сетью"
else
  _fail "Не хватает обязательных ключей или значение не по формату:"
  echo "${REQUIRED_ERRORS}" | sed '/^$/d' | sed 's/^/    - /'
fi

# ─── Проверка 7: имена только стандартные ────────────────────────────────────
echo "[7/9] Имена переменных стандартные, без своих аналогов (§1.2)"
LEGACY_ERRORS=""
for d in ${PRESENT_DIRS[@]+"${PRESENT_DIRS[@]}"}; do
  for pair in ${LEGACY_KEYS[@]+"${LEGACY_KEYS[@]}"}; do
    legacy="${pair%%=*}"
    replacement="${pair#*=}"
    if grep -qx "${legacy}" "${WORK_DIR}/keys.${d}" 2>/dev/null; then
      LEGACY_ERRORS+="${d}: ${legacy} — замените на ${replacement}"$'\n'
    fi
  done
done
if [[ ${#PRESENT_DIRS[@]} -eq 0 ]]; then
  _skip "Контуров нет — проверять нечего"
elif [[ -z "${LEGACY_ERRORS}" ]]; then
  _pass "Имён из списка отказа нет"
else
  _fail "Найдены имена, от которых отказались:"
  echo "${LEGACY_ERRORS}" | sed '/^$/d' | sed 's/^/    - /'
fi

# ─── Проверка 8: в stage и prod — только плейсхолдеры ────────────────────────
echo "[8/9] В stage и prod секретные значения — только плейсхолдеры ${PLACEHOLDER_PREFIX}*"
SECRET_ERRORS=""
SECRET_FILES_SEEN=0
for d in ${ENV_SECRET_DIRS[@]+"${ENV_SECRET_DIRS[@]}"}; do
  [[ -d "${ENV_ROOT}/${d}" ]] || continue
  while IFS= read -r -d '' f; do
    SECRET_FILES_SEEN=$((SECRET_FILES_SEEN + 1))
    rel="${d}/$(basename "${f}")"
    line_no=0
    while IFS= read -r line || [[ -n "${line}" ]]; do
      line_no=$((line_no + 1))
      [[ "${line}" =~ ^[[:space:]]*# ]] && continue
      [[ "${line}" =~ ^[A-Z_][A-Z0-9_]*= ]] || continue
      key="${line%%=*}"
      value="${line#*=}"
      [[ -z "${value}" ]] && continue
      # Булев флаг секретом быть не может: OIDC_TOKEN_SIGNATURE_UNVERIFIED=false
      # попадает под слово TOKEN в имени, но это признак, а не значение для
      # подстановки при деплое.
      [[ "${value}" =~ ^(true|false)$ ]] && continue
      if echo "${key}" | grep -qE "${SECRET_KEY_PATTERN}"; then
        if [[ "${value}" != *"${PLACEHOLDER_PREFIX}"* ]]; then
          SECRET_ERRORS+="${rel}:${line_no}: ${key} — ожидается плейсхолдер ${PLACEHOLDER_PREFIX}<ЧТО_ЭТО>"$'\n'
        fi
      fi
      # Эвристика проверки [8/15]: сплошная строка от 16 символов у секретного ключа.
      if echo "${line}" | grep -qiE '(password|secret|key|token)[[:space:]]*=[[:space:]]*[A-Za-z0-9+/]{16,}'; then
        SECRET_ERRORS+="${rel}:${line_no}: ${key} — похоже на настоящий секрет в git"$'\n'
      fi
    done <"${f}"
  done < <(find "${ENV_ROOT}/${d}" -maxdepth 1 -name ".env.*" -print0 2>/dev/null)
done
if [[ ${SECRET_FILES_SEEN} -eq 0 ]]; then
  _skip "Файлы контуров stage и prod не найдены — проверять нечего"
elif [[ -z "${SECRET_ERRORS}" ]]; then
  _pass "Секретных значений в git не найдено (проверено файлов: ${SECRET_FILES_SEEN})"
else
  _fail "Значения, которых не должно быть в git:"
  echo "${SECRET_ERRORS}" | sed '/^$/d' | sed 's/^/    - /'
fi

# ─── Проверка 9: роль миграций отделена от роли рантайма (D3) ────────────────
# Миграции идут под владельцем схемы PG_MIGRATE_USER, рантайм — под PGUSER
# без DDL: иначе рантайм владеет audit_log и может снять триггер append-only
# (06-data-privacy.md §5, 0001_init.up.sql). На stage и prod роли ОБЯЗАНЫ
# различаться — конфиг приложения отказывает при совпадении, этот скрипт
# ловит то же до деплоя. На env.local роль допустимо одна (контейнер БД, TLS
# нет) — печатается предупреждение, гейт не валит.
echo "[9/9] Роль миграций ${PG_MIGRATE_USER_KEY} задана и на stage/prod отличается от ${PG_RUNTIME_USER_KEY}"
ROLE_ERRORS=""
for d in ${PRESENT_DIRS[@]+"${PRESENT_DIRS[@]}"}; do
  runtime_user="$(_value_of_key "${d}" "${PG_RUNTIME_USER_KEY}")"
  migrate_user="$(_value_of_key "${d}" "${PG_MIGRATE_USER_KEY}")"
  is_secret_dir=0
  for s in ${ENV_SECRET_DIRS[@]+"${ENV_SECRET_DIRS[@]}"}; do
    [[ "${s}" == "${d}" ]] && is_secret_dir=1
  done
  if [[ -z "${migrate_user}" ]]; then
    if [[ ${is_secret_dir} -eq 1 ]]; then
      ROLE_ERRORS+="${d}: ${PG_MIGRATE_USER_KEY} не задан — миграции пойдут под ${PG_RUNTIME_USER_KEY}, рантайм останется владельцем схемы"$'\n'
    else
      _warn "${d}: ${PG_MIGRATE_USER_KEY} не задан — на локальном стенде миграции идут под ${PG_RUNTIME_USER_KEY} (допустимо только здесь)"
    fi
  elif [[ -n "${runtime_user}" && "${migrate_user}" == "${runtime_user}" ]]; then
    if [[ ${is_secret_dir} -eq 1 ]]; then
      ROLE_ERRORS+="${d}: ${PG_MIGRATE_USER_KEY} совпадает с ${PG_RUNTIME_USER_KEY} ('${runtime_user}') — вне local роли обязаны различаться"$'\n'
    else
      _warn "${d}: ${PG_MIGRATE_USER_KEY} совпадает с ${PG_RUNTIME_USER_KEY} ('${runtime_user}') — допустимо только на локальном стенде"
    fi
  fi
done
if [[ ${#PRESENT_DIRS[@]} -eq 0 ]]; then
  _skip "Контуров нет — проверять нечего"
elif [[ -z "${ROLE_ERRORS}" ]]; then
  _pass "Роль миграций задана; на stage и prod отличается от роли рантайма"
else
  _fail "Роли БД не разведены:"
  echo "${ROLE_ERRORS}" | sed '/^$/d' | sed 's/^/    - /'
fi

echo ""
echo "=== Итог check-env: PASS=${PASS} FAIL=${FAIL} SKIP=${SKIP} ==="
if [[ "${FAIL}" -gt 0 ]]; then
  exit 1
fi
exit 0
