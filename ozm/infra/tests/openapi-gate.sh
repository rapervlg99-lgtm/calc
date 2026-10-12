#!/usr/bin/env bash
# Шаблон скилла tnlife-miniapp-engineering. Гейт зеркал HTTP-контракта:
# раскладка зеркал из источника и падение при расхождении — по цели gen в
# infra/Makefile каркаса, проверкам [9/15] и [14/15] run.sh и CI-шлюзу
# readme-deploy.md §1.11; один и тот же во всех формах продукта. Скопируйте в
# infra/tests/openapi-gate.sh (scaffold.sh кладёт его сам), подставьте путь к
# источнику контракта, список зеркал и команду генерации в блоке настроек.
#
# Использование:
#   bash infra/tests/openapi-gate.sh          # check: зеркало совпадает с источником
#   bash infra/tests/openapi-gate.sh gen      # разложить зеркала из источника
#   bash infra/tests/openapi-gate.sh ci       # gen + требование чистого рабочего дерева
#   bash infra/tests/openapi-gate.sh --help   # эта шапка
#
# Правится только источник. Зеркала раскладывает gen, это обычное копирование.
# Код возврата: 0 — FAIL нет; 1 — есть FAIL; 2 — ошибка аргументов (неизвестная
# команда). Печать подсказки по --help кодом возврата не считается ошибкой.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ─────────────────────────────────────────────────────────────────────────────
# НАСТРОЙКИ ПРОЕКТА — правьте только этот блок
# ─────────────────────────────────────────────────────────────────────────────

# Базовое имя сервиса — используется только в заголовке вывода.
SERVICE="${SERVICE:-ozm}"

# Корень репозитория. По умолчанию — два уровня вверх от скрипта (infra/tests/).
REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"

# Источник правды HTTP-контракта. Единственный файл, который правят руками.
OPENAPI_SRC="${REPO_ROOT}/backend/openapi/openapi.yaml"

# Зеркала. Первое — то, которое читают проверки [9/15] и [14/15]; путь
# нестандартный и зафиксирован в 01-corp-standard.md, менять его нельзя.
OPENAPI_MIRRORS=(
  "${REPO_ROOT}/docs/api/openapi.yaml"
  "${REPO_ROOT}/api/openapi.yaml"
)

# Требуемая версия спецификации: корп. шаблон и приёмка идут по 3.0.x.
REQUIRED_OPENAPI_PREFIX="3.0."

# Команда, которой чинится рассинхрон зеркал.
GEN_HINT="bash infra/tests/openapi-gate.sh gen"

# ─────────────────────────────────────────────────────────────────────────────
# СЛУЖЕБНОЕ — ниже правки не требуются
# ─────────────────────────────────────────────────────────────────────────────

PASS=0
FAIL=0
SKIP=0

_pass() { echo "  [PASS] $1"; PASS=$((PASS + 1)); }
_fail() { echo "  [FAIL] $1"; FAIL=$((FAIL + 1)); }
_skip() { echo "  [SKIP] $1"; SKIP=$((SKIP + 1)); }

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "${WORK_DIR}"' EXIT

_openapi_version() {
  grep -m1 '^openapi:' "$1" 2>/dev/null | awk '{print $2}' | tr -d '"'"'" || true
}

_finish() {
  echo ""
  echo "=== Итог openapi-gate: PASS=${PASS} FAIL=${FAIL} SKIP=${SKIP} ==="
  if [[ "${FAIL}" -gt 0 ]]; then
    exit 1
  fi
  exit 0
}

# ─────────────────────────────────────────────────────────────────────────────
# GEN — разложить зеркала из источника
# ─────────────────────────────────────────────────────────────────────────────
run_gen() {
  echo "=== openapi-gate gen: раскладка зеркал контракта (${SERVICE}) ==="
  echo ""
  if [[ ! -f "${OPENAPI_SRC}" ]]; then
    _fail "Источник ${OPENAPI_SRC} не найден — генерировать нечего"
    return
  fi
  local mirror
  for mirror in ${OPENAPI_MIRRORS[@]+"${OPENAPI_MIRRORS[@]}"}; do
    mkdir -p "$(dirname "${mirror}")"
    if cp "${OPENAPI_SRC}" "${mirror}"; then
      _pass "${OPENAPI_SRC} → ${mirror}"
    else
      _fail "не удалось записать ${mirror}"
    fi
  done
}

# ─────────────────────────────────────────────────────────────────────────────
# CHECK — версия спецификации и совпадение зеркал с источником
# ─────────────────────────────────────────────────────────────────────────────
run_check() {
  echo "=== openapi-gate check: зеркала контракта (${SERVICE}) ==="
  echo ""

  local mirrors_present=0 mirror
  for mirror in ${OPENAPI_MIRRORS[@]+"${OPENAPI_MIRRORS[@]}"}; do
    [[ -f "${mirror}" ]] && mirrors_present=$((mirrors_present + 1))
  done

  # Проверка 1: источник на месте
  echo "[1/3] Источник контракта на месте"
  if [[ -f "${OPENAPI_SRC}" ]]; then
    _pass "${OPENAPI_SRC}"
  elif [[ ${mirrors_present} -eq 0 ]]; then
    _skip "Источник и зеркала не найдены — контракта пока нет"
    _skip "Версия спецификации не проверена: нет файлов"
    _skip "Совпадение зеркал не проверено: нет файлов"
    return
  else
    _fail "Источник ${OPENAPI_SRC} не найден, а зеркала есть — рассинхрон"
    _skip "Версия спецификации не проверена: нет источника"
    _skip "Совпадение зеркал не проверено: нет источника"
    return
  fi

  # Проверка 2: версия спецификации
  echo "[2/3] Версия спецификации ${REQUIRED_OPENAPI_PREFIX}x"
  local version
  version="$(_openapi_version "${OPENAPI_SRC}")"
  if [[ -z "${version}" ]]; then
    _fail "В источнике нет строки 'openapi:' — версия не определена"
  elif [[ "${version}" == "${REQUIRED_OPENAPI_PREFIX}"* ]]; then
    _pass "Версия OpenAPI: ${version}"
  else
    _fail "Версия OpenAPI '${version}' — ожидается ${REQUIRED_OPENAPI_PREFIX}x"
  fi

  # Проверка 3: каждое зеркало совпадает с только что сгенерированным
  echo "[3/3] Зеркала совпадают с источником"
  local generated="${WORK_DIR}/openapi.yaml"
  cp "${OPENAPI_SRC}" "${generated}"
  local diff_errors=""
  for mirror in ${OPENAPI_MIRRORS[@]+"${OPENAPI_MIRRORS[@]}"}; do
    if [[ ! -f "${mirror}" ]]; then
      diff_errors+="${mirror}: зеркало не найдено. Запустите: ${GEN_HINT}"$'\n'
    elif ! diff -q "${generated}" "${mirror}" >/dev/null 2>&1; then
      diff_errors+="${mirror}: не совпадает с источником. Запустите: ${GEN_HINT}"$'\n'
    fi
  done
  if [[ -z "${diff_errors}" ]]; then
    _pass "Все зеркала совпадают с источником"
  else
    _fail "Расхождение зеркал:"
    echo "${diff_errors}" | sed '/^$/d' | sed 's/^/    - /'
  fi
}

# ─────────────────────────────────────────────────────────────────────────────
# CI — сгенерировать и потребовать чистого рабочего дерева
# ─────────────────────────────────────────────────────────────────────────────
run_ci() {
  run_gen
  echo ""
  echo "[git] Рабочее дерево после генерации чистое"
  if ! command -v git >/dev/null 2>&1; then
    _skip "git не найден — рабочее дерево не проверено"
    return
  fi
  if ! git -C "${REPO_ROOT}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    _skip "${REPO_ROOT} не репозиторий git — рабочее дерево не проверено"
    return
  fi
  # status --porcelain, а не diff: он видит и правку зеркала, и зеркало,
  # которое забыли добавить в индекс.
  local dirty
  dirty="$(git -C "${REPO_ROOT}" status --porcelain -- ${OPENAPI_MIRRORS[@]+"${OPENAPI_MIRRORS[@]}"} || true)"
  if [[ -z "${dirty}" ]]; then
    _pass "Зеркала в коммите актуальны"
  else
    _fail "Источник правили без генерации зеркал. Запустите '${GEN_HINT}' и включите зеркала в тот же коммит:"
    awk '{ print "    - " $0 }' <<< "${dirty}"
  fi
}

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
usage() {
  # Шапка файла до первой непустой строки кода — без привязки к номерам строк.
  awk 'NR > 1 && !/^#/ { exit } NR > 1' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

CMD="${1:-check}"

case "${CMD}" in
  check) run_check ;;
  gen) run_gen ;;
  ci) run_ci ;;
  -h|--help) usage; exit 0 ;;
  *)
    echo "openapi-gate: ошибка: неизвестная команда '${CMD}'" >&2
    echo "Использование: $0 {check|gen|ci} (см. --help)" >&2
    exit 2
    ;;
esac

_finish
