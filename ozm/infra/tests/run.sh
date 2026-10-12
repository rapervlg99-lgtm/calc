#!/usr/bin/env bash
# Шаблон скилла tnlife-miniapp-engineering. 15 проверок соответствия
# корпоративного шаблона поставки (readme-deploy.md §5) и дымовой прогон
# стенда — одни и те же во всех формах продукта: мини-апп TN Life, веб- или
# API-сервис без суперапа. Скопируйте в infra/tests/run.sh (scaffold.sh кладёт
# его сам), подставьте значения в блоке «Настройки проекта»: ozm, список
# Dockerfile, пути зеркала контракта и адреса для smoke. Остальное не трогайте.
#
# Использование:
#   bash infra/tests/run.sh compliance            # 15 статических проверок
#   bash infra/tests/run.sh smoke                 # smoke по поднятому стенду env.local
#   bash infra/tests/run.sh                       # оба режима
#   bash infra/tests/run.sh compliance --strict   # SKIP считается FAIL (режим CI)
#   COMPLIANCE_STRICT=1 bash infra/tests/run.sh   # то же переменной окружения
#
# Скрипт считает PASS/FAIL/SKIP, печатает по строке на проверку и падает при
# FAIL>0. Два режима:
#   - обычный: SKIP гейт не валит — это режим рабочей машины на S0, когда
#     части дерева ещё нет (нет миграций, нет зеркала контракта);
#   - strict (--strict или COMPLIANCE_STRICT=1): каждый SKIP засчитывается как
#     FAIL и Dockerfile вне явного списка тоже FAIL. Это режим CI и релизного
#     коммита: порог PASS=15 FAIL=0 SKIP=0 держится кодом возврата, а не
#     чтением сводки глазами.
# Проверки, которым нужен python3 с модулем yaml, при их отсутствии дают FAIL
# в обоих режимах: пропущенный разбор compose — это не «нечего проверять», а
# «проверка не выполнена», и зелёный итог тут был бы ложным. По той же причине
# сбой РАЗБОРА (битый YAML compose или pre-commit, зеркало контракта без
# строки «openapi:») — это FAIL своей проверки, а не обрыв прогона: пятнадцать
# строк и сводка печатаются всегда, иначе вердикт строился бы на обрезанном
# списке.
#
# Код возврата: 0 — FAIL нет; 1 — есть FAIL; 2 — ошибка аргументов.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ─────────────────────────────────────────────────────────────────────────────
# НАСТРОЙКИ ПРОЕКТА — правьте только этот блок
# ─────────────────────────────────────────────────────────────────────────────

# Базовое имя сервиса. Оно же имя сервиса в compose, container_name и имя образа.
SERVICE="${SERVICE:-ozm}"

# Корень репозитория. По умолчанию — два уровня вверх от скрипта (infra/tests/run.sh).
REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"

# Стенд целиком одним файлом.
COMPOSE_FILE="${REPO_ROOT}/infra/docker-compose.yaml"

# Контуры окружения. В каждом лежит ровно один и тот же набор .env.*.
ENV_DIRS=(
  "${REPO_ROOT}/infra/env.local"
  "${REPO_ROOT}/infra/env.stage"
  "${REPO_ROOT}/infra/env.prod"
)

# Контуры, где секретов в git не бывает — только плейсхолдеры REPLACE_WITH_*.
ENV_SECRET_DIRS=(
  "${REPO_ROOT}/infra/env.stage"
  "${REPO_ROOT}/infra/env.prod"
)

# Явный список Dockerfile — образы продукта, которые собирает `make -C infra
# build` и сканирует job dockerfile в security.yaml. Список ОБЪЕДИНЯЕТСЯ с
# автообнаружением: проверки [6/15] и [15/15] дополнительно обходят дерево
# (find по именам Dockerfile, Dockerfile.* и *.Dockerfile, минуя
# DOCKERFILE_SCAN_EXCLUDES) и каждый найденный файл вне списка проверяют тоже,
# печатая WARN с именем; в strict такой файл — FAIL. Завели третий образ —
# допишите его сюда, чтобы список совпадал с security.yaml.
DOCKERFILES=(
  "${REPO_ROOT}/backend/Dockerfile"
  "${REPO_ROOT}/frontend/Dockerfile"
  "${REPO_ROOT}/ocr/Dockerfile"
)

# Что автообнаружение Dockerfile не смотрит. К каталогам из NAME_SCAN_EXCLUDES
# (.git, node_modules, vendor, .claude) добавлены два вендоренных каталога
# нормы: мост tn-bridge/ (вендорится в форме miniapp; в остальных формах
# каталога нет, и исключение безвредно) и кит uikit/ (вендорится только по
# ADR). Их Dockerfile — сборка сторибука кита и подобное, образами продукта
# они не являются и `make -C infra build` их не собирает. Свой Dockerfile,
# который образ продукта, сюда НЕ добавляйте — допишите его в DOCKERFILES.
DOCKERFILE_SCAN_EXCLUDES=(
  "*/tn-bridge/*"
  "*/uikit/*"
)

# Каталог единого cloud-init. infra внутри infra — так раскладывает каркас
# набора (01-corp-standard.md, «Почему пути удваиваются»), проверка [7/15]
# грепает именно этот путь. Менять нельзя.
CLOUDINIT_DIR="${REPO_ROOT}/infra/infra/cloud-init"

# Конфиг локального OTel Collector. Путь тоже нестандартный и тоже зафиксирован.
OTEL_CONFIG="${REPO_ROOT}/infra/env.local/otel/config.yaml"

# Контракт: источник правды и зеркало, которое читают проверки [9/15] и [14/15].
OPENAPI_SRC="${REPO_ROOT}/backend/openapi/openapi.yaml"
OPENAPI_MIRROR="${REPO_ROOT}/docs/api/openapi.yaml"

# Команда, которой чинится рассинхрон зеркала.
GEN_CMD="make -C infra gen"

# Миграции. Расширения managed PG подключаются конфигурацией, не миграцией.
MIGRATIONS_DIR="${REPO_ROOT}/backend/migrations"

# Линтеры, обязательные по §1.9.
PRECOMMIT_FILE="${REPO_ROOT}/.pre-commit-config.yaml"
REQUIRED_LINTERS=(
  yamllint actionlint shellcheck shfmt hadolint
  markdownlint codespell gitleaks ruff go-fmt go-vet
)

# Каталоги, которые не участвуют в проверке имён [1/15] и [2/15].
NAME_SCAN_EXCLUDES=(
  "*/.git/*"
  "*/node_modules/*"
  "*/.claude/*"
  "*/vendor/*"
)

# Кириллица здесь не валит гейт, а печатается как WARN: это зона других треков
# (исходные постановки бизнеса, файлы дизайна).
NAME_SCAN_WARN_PATHS=(
  "${REPO_ROOT}/docs/source/*"
)
NAME_SCAN_WARN_NAMES=(
  "*.fig"
)

# Цели smoke: «подпись|цель|дополнительные аргументы curl». Цель — одного из
# двух видов:
#   - http(s)://… — curl, ожидается ответ 2xx/3xx; -k нужен там, где локальный
#     reverse-proxy отдаёт самоподписанный сертификат;
#   - docker-health:<container_name> — `docker inspect`, ожидается состояние
#     healthy. Так проверяются сервисы, которые по норме не публикуют порты на
#     хост: коллектор OTel наружу не смотрит ни на одном контуре (01
#     «docker-compose и Dockerfile»), поэтому цель вида http://localhost:13133/
#     не отвечает, и smoke не дал бы 5/5.
# Цель ${SERVICE}-web /healthz верна во всех формах: nginx-вход есть и в
# форме api (без SPA).
SMOKE_TARGETS=(
  "${SERVICE}-api /healthz|https://api.localhost/healthz|-k"
  "${SERVICE}-api /readyz|https://api.localhost/readyz|-k"
  "${SERVICE}-web /healthz|https://app.localhost/healthz|-k"
  "oidc-mock .well-known|http://localhost:5556/default/.well-known/openid-configuration|"
  "otel-collector health|docker-health:${SERVICE}-otel|"
)
SMOKE_TIMEOUT="${SMOKE_TIMEOUT:-5}"

# Интерпретатор для разбора YAML и обхода имён файлов.
PY="${PYTHON_BIN:-python3}"

# ─────────────────────────────────────────────────────────────────────────────
# СЛУЖЕБНОЕ — ниже правки не требуются
# ─────────────────────────────────────────────────────────────────────────────

PASS=0
FAIL=0
SKIP=0
TOTAL_FAIL=0

# Strict-режим: переменная окружения COMPLIANCE_STRICT=1 либо флаг --strict
# (флаг разбирается в блоке MAIN и перекрывает переменную).
STRICT="${COMPLIANCE_STRICT:-0}"

_pass() { echo "  [PASS] $1"; PASS=$((PASS + 1)); }
_fail() { echo "  [FAIL] $1"; FAIL=$((FAIL + 1)); }
# SKIP в strict печатается как FAIL с пометкой, чтобы в логе CI было видно и
# что проверка не выполнена, и что упала она именно по строгому режиму.
_skip() {
  if [[ "${STRICT}" == "1" ]]; then
    echo "  [FAIL] (strict: SKIP засчитан как FAIL) $1"; FAIL=$((FAIL + 1))
  else
    echo "  [SKIP] $1"; SKIP=$((SKIP + 1))
  fi
}
_warn() { echo "  [WARN] $1"; }
# WARN, который в strict становится FAIL: для находок, которые на рабочей машине
# терпимы, а на релизном коммите — нет (Dockerfile вне явного списка).
_warn_strict() {
  if [[ "${STRICT}" == "1" ]]; then
    echo "  [FAIL] (strict) $1"; FAIL=$((FAIL + 1))
  else
    _warn "$1"
  fi
}

_reset_counters() { PASS=0; FAIL=0; SKIP=0; }

HAVE_PY=0
HAVE_YAML=0
if command -v "${PY}" >/dev/null 2>&1; then
  HAVE_PY=1
  if "${PY}" -c "import yaml" >/dev/null 2>&1; then
    HAVE_YAML=1
  fi
fi

# Отсутствие интерпретатора или модуля yaml — FAIL, а не SKIP, в любом режиме:
# без них не выполняются проверки [1], [2], [4], [5], [8], [12], [13], и
# зелёный итог с семью невыполненными проверками был бы ложным. Текст один и
# тот же, чтобы в CI его было легко найти.
_fail_no_py() {
  _fail "$1: ${PY} не найден — установите python3 и python3-yaml (pip install pyyaml)"
}
_fail_no_yaml() {
  _fail "$1: модуль yaml для ${PY} не установлен — установите python3-yaml (pip install pyyaml)"
}

# Полный список Dockerfile для проверок [6/15] и [15/15]: явный DOCKERFILES плюс
# автообнаружение по дереву. Найденные вне списка попадают в DOCKERFILES_ALL и в
# DOCKERFILES_UNLISTED — по второму массиву проверка [6/15] печатает WARN
# (в strict — FAIL). Дубликаты и порядок: явный список первым, находки — по
# `sort`, чтобы вывод не зависел от порядка обхода find.
DOCKERFILES_ALL=()
DOCKERFILES_UNLISTED=()
_discover_dockerfiles() {
  local df found p listed
  local -a excl=()
  for p in ${NAME_SCAN_EXCLUDES[@]+"${NAME_SCAN_EXCLUDES[@]}"} \
           ${DOCKERFILE_SCAN_EXCLUDES[@]+"${DOCKERFILE_SCAN_EXCLUDES[@]}"}; do
    excl+=(-not -path "${p}")
  done
  for df in ${DOCKERFILES[@]+"${DOCKERFILES[@]}"}; do
    DOCKERFILES_ALL+=("${df}")
  done
  while IFS= read -r found; do
    [[ -n "${found}" ]] || continue
    listed=0
    for df in ${DOCKERFILES[@]+"${DOCKERFILES[@]}"}; do
      if [[ "${df}" == "${found}" ]]; then listed=1; break; fi
    done
    if [[ ${listed} -eq 0 ]]; then
      DOCKERFILES_ALL+=("${found}")
      DOCKERFILES_UNLISTED+=("${found}")
    fi
  done < <(find "${REPO_ROOT}" -type f \
      \( -name "Dockerfile" -o -name "Dockerfile.*" -o -name "*.Dockerfile" \) \
      ${excl[@]+"${excl[@]}"} 2>/dev/null | sort)
}

# Аргументы find. Две группы исключений, и они НЕ взаимозаменяемы:
#   FIND_HARD_EXCL — каталоги, которых в репозитории как бы нет (.git, вендоринг).
#     Их не смотрит ни одна проверка имён.
#   FIND_EXCL      — то же плюс артефакты смежных треков, у которых кириллица
#     в имени допустима. Только для проверки [1/15].
# Проверка [2/15] обязана идти по FIND_HARD_EXCL: двоеточие, звёздочка и вопрос
# в имени ломают git checkout на Windows у любого файла, включая .fig и docs/source,
# и «это зона дизайна» тут не аргумент — репозиторий не клонируется целиком.
FIND_HARD_EXCL=()
FIND_EXCL=()
FIND_WARN=()
_build_find_args() {
  local p n first=1
  for p in ${NAME_SCAN_EXCLUDES[@]+"${NAME_SCAN_EXCLUDES[@]}"}; do
    FIND_HARD_EXCL+=(-not -path "${p}")
  done
  FIND_EXCL=(${FIND_HARD_EXCL[@]+"${FIND_HARD_EXCL[@]}"})
  for p in ${NAME_SCAN_WARN_PATHS[@]+"${NAME_SCAN_WARN_PATHS[@]}"}; do
    FIND_EXCL+=(-not -path "${p}")
    if [[ ${first} -eq 1 ]]; then FIND_WARN+=(-path "${p}"); first=0
    else FIND_WARN+=(-o -path "${p}"); fi
  done
  for n in ${NAME_SCAN_WARN_NAMES[@]+"${NAME_SCAN_WARN_NAMES[@]}"}; do
    FIND_EXCL+=(-not -name "${n}")
    if [[ ${first} -eq 1 ]]; then FIND_WARN+=(-name "${n}"); first=0
    else FIND_WARN+=(-o -name "${n}"); fi
  done
}
_build_find_args

# Печатает пути, в basename которых встретился заданный класс символов.
_names_matching() {
  "${PY}" -c "
import sys, os, re
pattern = re.compile(sys.argv[1])
bad = []
for line in sys.stdin:
    path = line.rstrip('\n')
    if pattern.search(os.path.basename(path)):
        bad.append(path)
print('\n'.join(bad))
" "$1"
}

# ─────────────────────────────────────────────────────────────────────────────
# COMPLIANCE — 15 статических проверок
# ─────────────────────────────────────────────────────────────────────────────
run_compliance() {
  _reset_counters
  echo "=== compliance: статические проверки корп. шаблона ТН (${SERVICE}) ==="
  echo ""

  # Проверка 1: нет кириллицы в именах файлов и каталогов (§1.9)
  echo "[1/15] Имена файлов и каталогов — без кириллицы (§1.9)"
  if [[ ${HAVE_PY} -eq 0 ]]; then
    _fail_no_py "обход имён файлов не выполнен"
  else
    CYRILLIC=$(find "${REPO_ROOT}" -mindepth 1 ${FIND_EXCL[@]+"${FIND_EXCL[@]}"} \
      | _names_matching '[а-яёА-ЯЁ]' || true)
    CYRILLIC_WARN=""
    if [[ ${#FIND_WARN[@]} -gt 0 ]]; then
      CYRILLIC_WARN=$(find "${REPO_ROOT}" -mindepth 1 \
        ${FIND_HARD_EXCL[@]+"${FIND_HARD_EXCL[@]}"} \
        \( "${FIND_WARN[@]}" \) \
        | _names_matching '[а-яёА-ЯЁ]' || true)
    fi
    if [[ -z "${CYRILLIC}" ]]; then
      _pass "Кириллица в именах файлов и каталогов (инфра и код) не найдена"
      if [[ -n "${CYRILLIC_WARN}" ]]; then
        _warn "Кириллица в артефактах смежных треков (гейт не валит, переименуйте):"
        echo "${CYRILLIC_WARN}" | head -5 | sed 's/^/    /'
      fi
    else
      _fail "Найдена кириллица в именах файлов и каталогов:"
      echo "${CYRILLIC}" | head -20 | sed 's/^/    /'
    fi
  fi

  # Проверка 2: нет Windows-несовместимых символов в именах (§1.9)
  echo "[2/15] Имена файлов — без Windows-несовместимых символов (§1.9)"
  if [[ ${HAVE_PY} -eq 0 ]]; then
    _fail_no_py "обход имён файлов не выполнен"
  else
    WIN_INCOMPAT=$(find "${REPO_ROOT}" -mindepth 1 ${FIND_HARD_EXCL[@]+"${FIND_HARD_EXCL[@]}"} \
      | _names_matching '[:<>|"?*\\]' || true)
    if [[ -z "${WIN_INCOMPAT}" ]]; then
      _pass "Windows-несовместимые символы в именах не найдены"
    else
      _fail "Найдены Windows-несовместимые символы в путях:"
      echo "${WIN_INCOMPAT}" | head -20 | sed 's/^/    /'
    fi
  fi

  # Проверка 3: формат .env.* (§2.3)
  echo "[3/15] Формат .env.*: первая строка '#', файл оканчивается пустой строкой (§2.3)"
  ENV_ERRORS=""
  ENV_FOUND=0
  while IFS= read -r -d '' f; do
    ENV_FOUND=$((ENV_FOUND + 1))
    FIRST_LINE=$(head -1 "${f}")
    if [[ "${FIRST_LINE}" != \#* ]]; then
      ENV_ERRORS+="${f}: первая строка не '#' (найдено: '${FIRST_LINE}')"$'\n'
    fi
    LAST_CHAR=$(tail -c1 "${f}" | wc -c)
    if [[ "${LAST_CHAR}" -eq 0 ]]; then
      ENV_ERRORS+="${f}: файл не оканчивается пустой строкой (пустой файл)"$'\n'
    else
      LAST_LINE=$(tail -1 "${f}")
      if [[ -n "${LAST_LINE}" ]]; then
        ENV_ERRORS+="${f}: файл не оканчивается пустой строкой (последняя строка: '${LAST_LINE}')"$'\n'
      fi
    fi
    # После '.env.' точек больше быть не должно: .env.app, а не .env.app.local.
    case "$(basename "${f}")" in
      .env.*.*) ENV_ERRORS+="${f}: после '.env.' точек больше быть не должно (§2.3)"$'\n' ;;
    esac
  done < <(find ${ENV_DIRS[@]+"${ENV_DIRS[@]}"} -name ".env.*" -print0 2>/dev/null)

  if [[ ${ENV_FOUND} -eq 0 ]]; then
    _skip "Файлы .env.* не найдены в контурах — проверять нечего"
  elif [[ -z "${ENV_ERRORS}" ]]; then
    _pass "Файлы .env.* соответствуют формату (проверено: ${ENV_FOUND})"
  else
    _fail "Проблемы с .env.*:"
    echo "${ENV_ERRORS}" | sed '/^$/d' | sed 's/^/    - /'
  fi

  # Проверка 4: лимиты ресурсов и healthcheck у каждого сервиса (§2.2)
  echo "[4/15] docker-compose: deploy.resources.limits + healthcheck у всех сервисов (§2.2)"
  if [[ ! -f "${COMPOSE_FILE}" ]]; then
    _fail "${COMPOSE_FILE} не найден"
  elif [[ ${HAVE_YAML} -eq 0 ]]; then
    _fail_no_yaml "compose не разобран"
  else
    if ! COMPOSE_LIMITS=$("${PY}" - "${COMPOSE_FILE}" <<'PYEOF'
import sys
import yaml

with open(sys.argv[1]) as f:
    compose = yaml.safe_load(f) or {}

services = compose.get("services", {}) or {}
bad = []
for name, svc in services.items():
    svc = svc or {}
    if not svc.get("healthcheck"):
        bad.append(f"{name}: нет healthcheck")
    limits = (svc.get("deploy", {}) or {}).get("resources", {}).get("limits", {}) or {}
    if not limits.get("cpus") or not limits.get("memory"):
        bad.append(f"{name}: нет deploy.resources.limits.{{cpus,memory}}")

for b in bad:
    print(b)
PYEOF
    ); then
      _fail "compose не разобран: ${COMPOSE_FILE} — ошибка YAML (traceback выше)"
    elif [[ -z "${COMPOSE_LIMITS}" ]]; then
      _pass "У всех сервисов есть healthcheck и лимиты ресурсов"
    else
      _fail "Сервисы без healthcheck или лимитов:"
      awk '{ print "    - " $0 }' <<< "${COMPOSE_LIMITS}"
    fi
  fi

  # Проверка 5: container_name равен имени сервиса (§2.2)
  echo "[5/15] docker-compose: container_name совпадает с именем сервиса (§2.2)"
  if [[ ! -f "${COMPOSE_FILE}" ]]; then
    _fail "${COMPOSE_FILE} не найден"
  elif [[ ${HAVE_YAML} -eq 0 ]]; then
    _fail_no_yaml "compose не разобран"
  else
    if ! CONTAINER_NAME_ERRORS=$("${PY}" - "${COMPOSE_FILE}" <<'PYEOF'
import sys
import yaml

with open(sys.argv[1]) as f:
    compose = yaml.safe_load(f) or {}

services = compose.get("services", {}) or {}
bad = []
for name, svc in services.items():
    svc = svc or {}
    cn = svc.get("container_name")
    if cn and cn != name:
        bad.append(f"{name}: container_name='{cn}' не совпадает с именем сервиса")
    elif not cn:
        bad.append(f"{name}: container_name не задан")

for b in bad:
    print(b)
PYEOF
    ); then
      _fail "compose не разобран: ${COMPOSE_FILE} — ошибка YAML (traceback выше)"
    elif [[ -z "${CONTAINER_NAME_ERRORS}" ]]; then
      _pass "container_name совпадает с именем сервиса для всех сервисов"
    else
      _fail "Несоответствия container_name:"
      awk '{ print "    - " $0 }' <<< "${CONTAINER_NAME_ERRORS}"
    fi
  fi

  # Проверка 6: DOCKER_PROXY_HOST_1 в каждом Dockerfile (§2.1)
  # Список — явный DOCKERFILES плюс автообнаружение (см. _discover_dockerfiles).
  # Dockerfile вне явного списка проверяется наравне с остальными и печатается
  # как WARN: он проедет мимо job dockerfile в security.yaml и мимо
  # `make -C infra build`. В strict это FAIL — список обязан быть полным.
  echo "[6/15] DOCKER_PROXY_HOST_1 присутствует в каждом Dockerfile (§2.1)"
  _discover_dockerfiles
  for df in ${DOCKERFILES_UNLISTED[@]+"${DOCKERFILES_UNLISTED[@]}"}; do
    _warn_strict "Dockerfile вне явного списка DOCKERFILES: ${df} — допишите в DOCKERFILES (и в security.yaml) либо в DOCKERFILE_SCAN_EXCLUDES, если это не образ продукта"
  done
  DOCKERFILE_ERRORS=""
  for df in ${DOCKERFILES_ALL[@]+"${DOCKERFILES_ALL[@]}"}; do
    if [[ ! -f "${df}" ]]; then
      DOCKERFILE_ERRORS+="${df}: файл не найден"$'\n'
      continue
    fi
    if ! grep -q "DOCKER_PROXY_HOST_1" "${df}"; then
      DOCKERFILE_ERRORS+="${df}: ARG DOCKER_PROXY_HOST_1 не найден"$'\n'
      continue
    fi
    # Каждый FROM тянет образ через переменную либо ссылается на стадию сборки.
    # Флаги самого FROM (--platform и подобные) пропускаем: образ идёт после них.
    # scratch — не образ, а пустая ФС внутри Docker: проксировать нечего,
    # и для Go-бинаря это штатная финальная стадия. Гейт его не трогает.
    BAD_FROM=$(awk '
      /^[Ff][Rr][Oo][Mm][ \t]+/ {
        i = 2
        while (i <= NF && $i ~ /^--/) { i++ }
        img = (i <= NF) ? $i : ""
        if (img != "" && img != "scratch" && img !~ /^\$/ && !(img in stages)) { bad = bad $0 "\n" }
        for (j = i + 1; j <= NF; j++) { if (toupper($j) == "AS") { stages[$(j + 1)] = 1 } }
      }
      END { printf "%s", bad }
    ' "${df}")
    if [[ -n "${BAD_FROM}" ]]; then
      DOCKERFILE_ERRORS+="${df}: FROM без \${DOCKER_PROXY_HOST_1}: ${BAD_FROM}"$'\n'
    fi
  done
  if [[ -z "${DOCKERFILE_ERRORS}" ]]; then
    _pass "DOCKER_PROXY_HOST_1 присутствует во всех Dockerfile (проверено: ${#DOCKERFILES_ALL[@]})"
  else
    _fail "Проблемы с Dockerfile:"
    echo "${DOCKERFILE_ERRORS}" | sed '/^$/d' | sed 's/^/    - /'
  fi

  # Проверка 7: единый cloud-init (§2.5)
  echo "[7/15] Единый cloud-init: vm.yaml.tmpl + render.sh + targets/ (§2.5)"
  CLOUDINIT_ERRORS=""
  for f in "${CLOUDINIT_DIR}/vm.yaml.tmpl" "${CLOUDINIT_DIR}/render.sh"; do
    [[ -f "${f}" ]] || CLOUDINIT_ERRORS+="${f}: не найден"$'\n'
  done
  if [[ ! -d "${CLOUDINIT_DIR}/targets" ]]; then
    CLOUDINIT_ERRORS+="${CLOUDINIT_DIR}/targets/: каталог не найден"$'\n'
  elif ! ls "${CLOUDINIT_DIR}/targets"/*.env >/dev/null 2>&1; then
    CLOUDINIT_ERRORS+="${CLOUDINIT_DIR}/targets/: нет файлов *.env"$'\n'
  fi
  if [[ -z "${CLOUDINIT_ERRORS}" ]]; then
    _pass "Структура cloud-init корректна"
  else
    _fail "Проблемы с cloud-init:"
    echo "${CLOUDINIT_ERRORS}" | sed '/^$/d' | sed 's/^/    - /'
  fi

  # Проверка 8: нет hardcoded секретов в stage и prod (эвристика)
  echo "[8/15] Нет hardcoded секретов в контурах stage и prod (эвристика)"
  if [[ ${HAVE_PY} -eq 0 ]]; then
    _fail_no_py "эвристика по секретам не выполнена"
  else
    if ! HARDCODED_SECRETS=$("${PY}" - ${ENV_SECRET_DIRS[@]+"${ENV_SECRET_DIRS[@]}"} <<'PYEOF'
import sys, os, re

pattern = re.compile(r'(password|secret|key|token)\s*=\s*[A-Za-z0-9+/]{16,}', re.IGNORECASE)
found = []
for env_dir in sys.argv[1:]:
    if not os.path.isdir(env_dir):
        continue
    for fname in sorted(os.listdir(env_dir)):
        fpath = os.path.join(env_dir, fname)
        if not os.path.isfile(fpath):
            continue
        with open(fpath, errors='replace') as f:
            for i, line in enumerate(f, 1):
                if line.lstrip().startswith('#'):
                    continue
                if pattern.search(line):
                    found.append(f"{fpath}:{i}: {line.rstrip()}")
for x in found:
    print(x)
PYEOF
    ); then
      _fail "эвристика по секретам не выполнена: ${PY} завершился с ошибкой (traceback выше)"
    elif [[ -z "${HARDCODED_SECRETS}" ]]; then
      _pass "Явных hardcoded секретов в stage и prod не найдено"
    else
      _fail "Возможные hardcoded секреты в stage и prod:"
      echo "${HARDCODED_SECRETS}" | head -10 | sed 's/^/    - /'
    fi
  fi

  # Проверка 9: версия OpenAPI в зеркале контракта (§1.4)
  echo "[9/15] Зеркало контракта — версия OpenAPI 3.0.x (§1.4)"
  if [[ ! -f "${OPENAPI_MIRROR}" ]]; then
    _skip "${OPENAPI_MIRROR} не найден (зеркало появится после '${GEN_CMD}')"
  else
    # || true как в openapi-gate.sh: файла без строки «openapi:» (swagger 2.0 в
    # зеркале, битая копия) грепу нечего отдать, и под set -e с pipefail прогон
    # оборвался бы на [9/15] — без строк [10/15]–[15/15] и без сводки, а аудит
    # чужого MVP строился бы на обрезанном списке.
    OPENAPI_VERSION=$(grep -m1 '^openapi:' "${OPENAPI_MIRROR}" | awk '{print $2}' | tr -d '"'"'" || true)
    if [[ -z "${OPENAPI_VERSION}" ]]; then
      _fail "В зеркале ${OPENAPI_MIRROR} нет строки 'openapi:' — версия не определена (swagger 2.0 или битая копия?)"
    elif echo "${OPENAPI_VERSION}" | grep -qE '^3\.0\.'; then
      _pass "Версия OpenAPI: ${OPENAPI_VERSION}"
    else
      _fail "Версия OpenAPI '${OPENAPI_VERSION}' — ожидается 3.0.x"
    fi
  fi

  # Проверка 10: нет Loki, Grafana, Prometheus как сервисов (§1.8)
  echo "[10/15] docker-compose: нет Loki, Grafana, Prometheus как сервисов (§1.8)"
  if [[ ! -f "${COMPOSE_FILE}" ]]; then
    _fail "${COMPOSE_FILE} не найден"
  else
    FORBIDDEN=$(grep -iE '^[[:space:]]+(loki|grafana|prometheus):' "${COMPOSE_FILE}" || true)
    if [[ -z "${FORBIDDEN}" ]]; then
      _pass "Loki, Grafana, Prometheus отсутствуют как сервисы"
    else
      _fail "Запрещённые сервисы найдены:"
      awk '{ print "    " $0 }' <<< "${FORBIDDEN}"
    fi
  fi

  # Проверка 11: конфиг OTel Collector (§1.8)
  echo "[11/15] Конфиг OTel Collector присутствует (§1.8)"
  if [[ -f "${OTEL_CONFIG}" ]]; then
    if grep -q "otlp" "${OTEL_CONFIG}" && grep -q "receivers" "${OTEL_CONFIG}"; then
      _pass "Конфиг найден и содержит receivers и otlp"
    else
      _fail "Конфиг найден, но не содержит ожидаемых секций receivers и otlp"
    fi
  else
    _fail "${OTEL_CONFIG} не найден"
  fi

  # Проверка 12: набор линтеров в pre-commit и конфиги, на которые они ссылаются (§1.9)
  # Сверяем именно id хуков, а не текст файла. Голый grep по файлу считал линтер
  # подключённым, если его имя попадалось где угодно — в комментарии-шапке или
  # внутри URL репозитория (github.com/gitleaks/gitleaks). Конфиг с repos: []
  # и одной строкой-перечислением в комментарии проходил гейт целиком.
  # Хук засчитывается при точном совпадении id либо при префиксе «linter-»:
  # у hadolint id хука — hadolint-docker, у ruff рядом лежит ruff-format.
  #
  # Второй половиной проверяются САМИ КОНФИГИ. Подключённый хук без своего
  # конфига — гейт, зелёный вхолостую: yamllint с `-c .yamllint.yml` без файла
  # падает на каждом коммите, а локальный хук с несуществующим `.gosec.yaml`
  # молчит ровно до того дня, когда инструмент поставят. Пути не зашиты в
  # скрипт, а вынимаются из самого конфига — из `args` внешних хуков и из
  # строки `entry` локальных, — поэтому смена пути в pre-commit не разъезжается
  # с приёмкой. Строгость разная и это осознанно:
  #   - хук из внешнего repo выполняется всегда → нет конфига = FAIL;
  #   - хук из `repo: local` пропускает себя, пока инструмент не установлен,
  #     → нет конфига = WARN (в CI, где инструмент обязателен, это падение).
  # Конфиги по норме лежат в корне репозитория, поэтому ведущие `./` и `../`
  # (у gosec путь дан от backend/) отбрасываются и остаток берётся от корня.
  echo "[12/15] pre-commit: обязательные линтеры подключены и их конфиги на месте (§1.9)"
  PRECOMMIT_ERRORS=""
  PRECOMMIT_WARNS=""
  PRECOMMIT_SKIP=0
  if [[ ! -f "${PRECOMMIT_FILE}" ]]; then
    PRECOMMIT_ERRORS+="${PRECOMMIT_FILE} не найден"$'\n'
  elif [[ ${HAVE_YAML} -eq 0 ]]; then
    PRECOMMIT_SKIP=1
  else
    if ! PRECOMMIT_REPORT=$("${PY}" - "${PRECOMMIT_FILE}" "${REPO_ROOT}" \
      ${REQUIRED_LINTERS[@]+"${REQUIRED_LINTERS[@]}"} <<'PYEOF'
import os
import re
import sys

import yaml

path, repo_root, required = sys.argv[1], sys.argv[2], sys.argv[3:]

with open(path) as f:
    cfg = yaml.safe_load(f) or {}

# Флаги, которыми линтеры получают путь к своему конфигу. Завели хук с другим
# флагом — допишите его сюда, иначе конфиг проедет мимо проверки.
FLAGS = ("-c", "--config", "--conf", "-conf", "--ignorefile", "--config-file")
# Конфиги, которые инструмент подхватывает без флага: имя хука → файл.
IMPLICIT = {"codespell": ".codespellrc"}


def configs_from_args(args):
    out, expect = [], False
    for raw in args:
        arg = str(raw)
        if expect:
            out.append(arg)
            expect = False
            continue
        for flag in FLAGS:
            if arg == flag:
                expect = True
                break
            if arg.startswith(flag + "="):
                out.append(arg[len(flag) + 1:])
                break
    return out


def configs_from_entry(entry):
    out = []
    for flag in FLAGS:
        pattern = re.escape(flag) + r"[= ]+([^\s'\"]+)"
        out.extend(re.findall(pattern, entry))
    return out


def resolve(candidate):
    # По норме конфиги лежат в корне репозитория; ведущие ./ и ../ снимаем,
    # потому что путь записан относительно рабочего каталога хука.
    rel = candidate
    while rel.startswith("./") or rel.startswith("../"):
        rel = rel.split("/", 1)[1] if "/" in rel else ""
    return os.path.join(repo_root, rel) if rel else ""


ids = []
for repo in cfg.get("repos", []) or []:
    if not isinstance(repo, dict):
        continue
    is_local = str(repo.get("repo", "")) == "local"
    for hook in repo.get("hooks", []) or []:
        if not isinstance(hook, dict) or not hook.get("id"):
            continue
        hook_id = str(hook["id"])
        ids.append(hook_id)
        found = configs_from_args(hook.get("args") or [])
        found += configs_from_entry(str(hook.get("entry") or ""))
        level = "WARN" if is_local else "ERR"
        for candidate in found:
            resolved = resolve(candidate)
            if not resolved or not os.path.isfile(resolved):
                print(f"{level}:{hook_id}: конфиг {candidate} не найден ({resolved})")
        implicit = IMPLICIT.get(hook_id)
        if implicit and not os.path.isfile(os.path.join(repo_root, implicit)):
            print(f"WARN:{hook_id}: конфиг {implicit} не найден — линтер пойдёт с настройками по умолчанию")

for linter in required:
    if not any(i == linter or i.startswith(linter + "-") for i in ids):
        print(f"ERR:{linter}: нет хука с таким id в {path}")
PYEOF
    ); then
      PRECOMMIT_ERRORS="${PRECOMMIT_FILE} не разобран: ошибка YAML (traceback выше)"
      PRECOMMIT_WARNS=""
    else
      PRECOMMIT_ERRORS=$(echo "${PRECOMMIT_REPORT}" | sed -n 's/^ERR://p')
      PRECOMMIT_WARNS=$(echo "${PRECOMMIT_REPORT}" | sed -n 's/^WARN://p')
    fi
  fi
  if [[ -n "${PRECOMMIT_WARNS}" ]]; then
    while IFS= read -r line; do
      [[ -n "${line}" ]] && _warn "${line}"
    done <<< "${PRECOMMIT_WARNS}"
  fi
  if [[ ${PRECOMMIT_SKIP} -eq 1 ]]; then
    _fail_no_yaml "pre-commit не разобран"
  elif [[ -z "${PRECOMMIT_ERRORS}" ]]; then
    _pass "Обязательные линтеры подключены, конфиги обязательных хуков на месте"
  else
    _fail "Линтеры и конфиги, которых не хватает:"
    echo "${PRECOMMIT_ERRORS}" | sed '/^$/d' | sed 's/^/    - /'
  fi

  # Проверка 13: нет CREATE EXTENSION в миграциях (§1.1)
  echo "[13/15] Миграции: нет CREATE EXTENSION (§1.1)"
  if [[ ! -d "${MIGRATIONS_DIR}" ]]; then
    _skip "${MIGRATIONS_DIR} не найден — миграций пока нет"
  elif [[ ${HAVE_PY} -eq 0 ]]; then
    _fail_no_py "миграции не разобраны"
  else
    if ! CREATE_EXT=$("${PY}" - "${MIGRATIONS_DIR}" <<'PYEOF'
import sys, os, re

mig_dir = sys.argv[1]
found = []
for root, _dirs, files in os.walk(mig_dir):
    for fname in sorted(files):
        if not fname.endswith('.sql'):
            continue
        fpath = os.path.join(root, fname)
        with open(fpath, errors='replace') as f:
            for i, line in enumerate(f, 1):
                if line.lstrip().startswith('--'):
                    continue
                if re.search(r'CREATE\s+EXTENSION', line, re.IGNORECASE):
                    found.append(f"{fpath}:{i}: {line.rstrip()}")
for x in found:
    print(x)
PYEOF
    ); then
      _fail "миграции не разобраны: ${PY} завершился с ошибкой (traceback выше)"
    elif [[ -z "${CREATE_EXT}" ]]; then
      _pass "CREATE EXTENSION в миграциях не найден"
    else
      _fail "Найден CREATE EXTENSION вне SQL-комментария:"
      awk '{ print "    - " $0 }' <<< "${CREATE_EXT}"
    fi
  fi

  # Проверка 14: зеркало контракта синхронно с источником
  echo "[14/15] Зеркало контракта синхронно с источником"
  if [[ ! -f "${OPENAPI_SRC}" && ! -f "${OPENAPI_MIRROR}" ]]; then
    _skip "Источник ${OPENAPI_SRC} и зеркало ${OPENAPI_MIRROR} не найдены"
  elif [[ ! -f "${OPENAPI_SRC}" ]]; then
    _fail "Источник ${OPENAPI_SRC} не найден, а зеркало есть — рассинхрон"
  elif [[ ! -f "${OPENAPI_MIRROR}" ]]; then
    _fail "Зеркало ${OPENAPI_MIRROR} не найдено. Запустите: ${GEN_CMD}"
  elif diff -q "${OPENAPI_SRC}" "${OPENAPI_MIRROR}" >/dev/null 2>&1; then
    _pass "Зеркало совпадает с источником"
  else
    _fail "Зеркало ${OPENAPI_MIRROR} не совпадает с источником. Запустите: ${GEN_CMD}"
  fi

  # Проверка 15: non-root USER и отсутствие тега latest
  echo "[15/15] Dockerfile: non-root USER, нет тегов :latest"
  # Тот же объединённый список, что и в [6/15]: явный плюс найденные по дереву.
  HARDENING_ERRORS=""
  for df in ${DOCKERFILES_ALL[@]+"${DOCKERFILES_ALL[@]}"}; do
    if [[ ! -f "${df}" ]]; then
      HARDENING_ERRORS+="${df}: файл не найден"$'\n'
      continue
    fi
    if ! grep -qE '^USER[[:space:]]+(10001|nonroot)' "${df}"; then
      HARDENING_ERRORS+="${df}: нет USER 10001 или USER nonroot"$'\n'
    fi
    LATEST_FROM=$(grep -iE '^FROM[[:space:]].*:latest' "${df}" || true)
    if [[ -n "${LATEST_FROM}" ]]; then
      HARDENING_ERRORS+="${df}: найден FROM с тегом :latest"$'\n'
    fi
  done
  if [[ -z "${HARDENING_ERRORS}" ]]; then
    _pass "Dockerfile: non-root USER, без тега :latest (проверено: ${#DOCKERFILES_ALL[@]})"
  else
    _fail "Проблемы с hardening:"
    echo "${HARDENING_ERRORS}" | sed '/^$/d' | sed 's/^/    - /'
  fi

  echo ""
  if [[ "${STRICT}" == "1" ]]; then
    echo "=== Итог compliance (strict): PASS=${PASS} FAIL=${FAIL} SKIP=${SKIP} ==="
  else
    echo "=== Итог compliance: PASS=${PASS} FAIL=${FAIL} SKIP=${SKIP} ==="
  fi
  TOTAL_FAIL=$((TOTAL_FAIL + FAIL))
}

# ─────────────────────────────────────────────────────────────────────────────
# SMOKE — curl по healthz и readyz поднятого стенда; docker inspect для
# сервисов без портов на хосте
# ─────────────────────────────────────────────────────────────────────────────
run_smoke() {
  _reset_counters
  echo "=== smoke: проверка поднятого стенда (${SERVICE}) ==="
  echo ""

  local target label url extra container status
  for target in ${SMOKE_TARGETS[@]+"${SMOKE_TARGETS[@]}"}; do
    IFS='|' read -r label url extra <<<"${target}"
    if [[ "${url}" == docker-health:* ]]; then
      container="${url#docker-health:}"
      if ! command -v docker >/dev/null 2>&1; then
        _skip "${label}: docker не найден — состояние ${container} не проверено"
        continue
      fi
      # Health.Status есть только у контейнеров с healthcheck; у остальных
      # берём State.Status — он «running», а не «healthy», и это FAIL по
      # построению: сервис без healthcheck не проходит и [4/15].
      status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${container}" 2>/dev/null || true)"
      if [[ "${status}" == "healthy" ]]; then
        _pass "${label}: ${container} — healthy"
      else
        _fail "${label}: ${container} — состояние «${status:-не найден}», ожидается healthy"
      fi
      continue
    fi
    if ! command -v curl >/dev/null 2>&1; then
      _skip "${label}: curl не найден — ${url} не проверен"
      continue
    fi
    local extra_args=()
    if [[ -n "${extra}" ]]; then
      read -r -a extra_args <<<"${extra}"
    fi
    if curl -sf --max-time "${SMOKE_TIMEOUT}" ${extra_args[@]+"${extra_args[@]}"} "${url}" >/dev/null 2>&1; then
      _pass "${label}: ${url}"
    else
      _fail "${label}: ${url} — недоступен"
    fi
  done

  echo ""
  echo "=== Итог smoke: PASS=${PASS} FAIL=${FAIL} SKIP=${SKIP} ==="
  TOTAL_FAIL=$((TOTAL_FAIL + FAIL))
}

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
# Аргументы: режим (compliance|smoke|all, по умолчанию all) и флаг --strict в
# любом порядке. Флаг перекрывает COMPLIANCE_STRICT из окружения.
CMD="all"
CMD_SET=0
for arg in "$@"; do
  case "${arg}" in
    --strict) STRICT=1 ;;
    --no-strict) STRICT=0 ;;
    -h|--help)
      echo "Использование: $0 [compliance|smoke|all] [--strict]"
      echo "  --strict            SKIP считается FAIL, Dockerfile вне списка — FAIL (режим CI)"
      echo "  COMPLIANCE_STRICT=1 то же переменной окружения"
      exit 0
      ;;
    compliance|smoke|all)
      if [[ ${CMD_SET} -eq 1 ]]; then
        echo "run: ошибка: режим задан дважды: ${CMD} и ${arg}" >&2
        exit 2
      fi
      CMD="${arg}"; CMD_SET=1
      ;;
    *)
      echo "run: ошибка: неизвестный аргумент: ${arg}" >&2
      echo "Использование: $0 [compliance|smoke|all] [--strict]" >&2
      exit 2
      ;;
  esac
done

if [[ "${STRICT}" == "1" ]]; then
  echo "[strict] SKIP засчитывается как FAIL; Dockerfile вне явного списка — FAIL"
fi

case "${CMD}" in
  compliance)
    run_compliance
    ;;
  smoke)
    run_smoke
    ;;
  all)
    run_compliance
    echo ""
    run_smoke
    ;;
esac

if [[ "${TOTAL_FAIL}" -gt 0 ]]; then
  exit 1
fi
exit 0
