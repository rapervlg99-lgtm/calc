#!/usr/bin/env bash
# Шаблон скилла tnlife-miniapp-engineering: рендер cloud-init под площадку.
# Норма — 01-corp-standard.md, «cloud-init».
#
# КУДА КЛАСТЬ: infra/infra/cloud-init/render.sh (удвоение infra — норма §2.5,
# см. шапку vm.yaml.tmpl). Проверка [7/15] требует этот файл рядом с шаблоном
# и каталогом targets/ минимум с одним *.env.
#
# НЕ ПУТАТЬ targets/*.env с infra/env.{local,stage,prod}/.env.* — это разные
# вещи. Здесь переменные ВРЕМЕНИ РЕНДЕРА cloud-init (куда клонировать, чей
# ключ, какой каталог облака), они не попадают в процесс приложения.
# Единственный владелец списка переменных приложения — templates/code/env.example.
#
# Использование:
#   bash infra/infra/cloud-init/render.sh [--allow-placeholders] <target> [output-file]
# Targets: имена файлов в targets/ без расширения .env.
#
# КОД ВОЗВРАТА: незаполненный плейсхолдер — ошибка, а не WARN при exit 0,
# иначе брак уезжает на ВМ.
# | Ситуация                                                        | Что делает скрипт                             | exit |
# |-----------------------------------------------------------------|-----------------------------------------------|------|
# | плейсхолдеров в выводе нет                                      | пишет файл, печатает «Готово»                 | 0    |
# | REPLACE_WITH_* или <service> в выводе, любая цель               | ERROR со списком строк, выходной файл УДАЛЁН  | 1    |
# | то же при --allow-placeholders и DEPLOYMENT_TARGET=local        | WARN со списком строк, файл остаётся          | 0    |
# | --allow-placeholders при DEPLOYMENT_TARGET≠local (yc-stage/prod) | ERROR до рендера: флаг не действует           | 1    |
# | вывод не разбирается как YAML (есть python3 с PyYAML)           | ERROR, файл удалён                            | 1    |
# | обязательная переменная target'а пуста или env не прочитался   | ERROR до рендера                              | 1    |
# | значение переменной target'а содержит перевод строки            | ERROR до рендера: инъекция YAML               | 1    |
# Почему файл удаляется: user-data с плейсхолдером клонирует репозиторий по
# адресу REPLACE_WITH_GIT_REPO_URL и кладёт cron.d с именем <service>; оставить
# его рядом со скриптом — дать следующему шагу подхватить брак.
# Зачем флаг локальным площадкам (libvirt, vagrant — у них DEPLOYMENT_TARGET=local):
# у них в targets/*.env остаются плейсхолдеры адреса репозитория и ключа
# администратора (REPLACE_WITH_GIT_REPO_URL, REPLACE_WITH_LOCAL_ADMIN_SSH_KEY),
# пока разработчик не передал свои значения окружением; на локальной ВМ это
# безвредно. Переменные Yandex Cloud (yc CLI, отпечаток git-хоста) на local
# пусты, и ветки, которые их читают, пропускают себя по detect-env.sh. Для
# yc-* те же плейсхолдеры смертельны — флаг не действует.
# Строки-комментарии (первый непробельный символ #) не считаются: там имена
# плейсхолдеров стоят в инструкциях.
#
# ОТКУДА ЗНАЧЕНИЯ. targets/*.env написаны в форме VAR=${VAR:-плейсхолдер}:
# значение берётся из окружения процесса рендера, плейсхолдер — только когда
# окружения нет. В CI (ci/service-contour.yaml, workflow_dispatch → render.sh
# <target> → пересоздание ВМ, readme-deploy §4.3) переменные приходят из
# секретов GitHub environment контура; руками в файл их не вписывают.
#
# Как проверить: bash -n render.sh; shellcheck render.sh; затем
#   bash render.sh yc-stage /tmp/ud && echo OK   # с заполненными env и шаблоном — 0
#   bash render.sh yc-stage /tmp/ud; echo $?     # с плейсхолдером — 1, /tmp/ud удалён
#   IMAGE_TAG=main-abc12345 ADMIN_SSH_KEY="ssh-ed25519 AAAA…" … bash render.sh yc-stage /tmp/ud   # окружение вместо плейсхолдеров

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMPL="${SCRIPT_DIR}/vm.yaml.tmpl"
TARGETS_DIR="${SCRIPT_DIR}/targets"

# Переменные, которые подставляются в шаблон. Список ОБЯЗАТЕЛЬНЫЙ и закрытый —
# см. блок про envsubst ниже. Завели в targets/*.env новую переменную и
# используете её в vm.yaml.tmpl — допишите её сюда, иначе она не подставится.
# YC_CLI_VERSION, YC_CLI_SHA256 и GIT_HOST_KEY стоят здесь, а не литералами в
# vm.yaml.tmpl: иначе ОДНО значение живёт в двух файлах (шаблон и env job'а
# ci/service-contour.yaml) и обновляется двумя MR, а рендер yc-* падает на
# них всегда, даже когда все переменные target'а заданы.
# shellcheck disable=SC2016  # это НЕ подстановка: envsubst принимает список
# имён литеральным текстом ${VAR}, поэтому одинарные кавычки обязательны.
SUBST_VARS='${ADMIN_SSH_KEY} ${GIT_REPO_URL} ${DEPLOYMENT_TARGET} ${IMAGE_TAG} ${YC_CLOUD_ID} ${YC_FOLDER_ID} ${KMS_KEY_ID} ${DEPLOY_SSH_KEY_ENCRYPTED_B64} ${YC_CLI_VERSION} ${YC_CLI_SHA256} ${GIT_HOST_KEY}'

# Отступ для многострочных сообщений об ошибках.
indent() { sed 's/^/    /'; }

usage() {
  echo "Usage: $0 [--allow-placeholders] <target> [output-file]"
  echo "Targets: $(find "${TARGETS_DIR}" -name '*.env' -exec basename {} .env \; | sort | tr '\n' ' ')"
  echo "  --allow-placeholders  оставить REPLACE_WITH_* и <service> в выводе как WARN;"
  echo "                        только для DEPLOYMENT_TARGET=local (libvirt, vagrant)"
  exit "${1:-1}"
}

ALLOW_PLACEHOLDERS=0
POSITIONAL=()
for arg in "$@"; do
  case "${arg}" in
    --allow-placeholders) ALLOW_PLACEHOLDERS=1 ;;
    -h|--help) usage 0 ;;
    --*) echo "ERROR: неизвестный флаг: ${arg}" >&2; usage 1 ;;
    *) POSITIONAL+=("${arg}") ;;
  esac
done
# Идиома ${arr[@]+"${arr[@]}"}: пустой массив под set -u в bash 3.2 (macOS) —
# ошибка «unbound variable», а разработчик рендерит и с macOS.
set -- ${POSITIONAL[@]+"${POSITIONAL[@]}"}

if [[ $# -lt 1 || $# -gt 2 ]]; then
  usage 1
fi

TARGET="$1"
OUTPUT="${2:-${SCRIPT_DIR}/cloud-init.rendered.yaml}"
ENV_FILE="${TARGETS_DIR}/${TARGET}.env"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "ERROR: не найден файл target'а: ${ENV_FILE}" >&2
  echo "Доступные targets:" >&2
  find "${TARGETS_DIR}" -name "*.env" -exec basename {} .env \; >&2
  exit 1
fi

if [[ ! -f "${TMPL}" ]]; then
  echo "ERROR: не найден шаблон: ${TMPL}" >&2
  exit 1
fi

if ! command -v envsubst >/dev/null 2>&1; then
  echo "ERROR: не найден envsubst (пакет gettext)" >&2
  exit 1
fi

echo "Рендеринг cloud-init для target: ${TARGET}"
echo "  Шаблон:  ${TMPL}"
echo "  Env:     ${ENV_FILE}"
echo "  Вывод:   ${OUTPUT}"

# Загружаем переменные target'а в окружение
set -a
# shellcheck source=/dev/null
if ! source "${ENV_FILE}"; then
  echo "ERROR: ${ENV_FILE} не прочитался как shell-файл." >&2
  echo "       Значения с пробелами (SSH-ключ) берите в кавычки: ADMIN_SSH_KEY=\"ssh-ed25519 AAAA… user@host\"" >&2
  exit 1
fi
set +a

# Пустое значение — тот же брак, что плейсхолдер: envsubst подставит пустую
# строку, и ВМ приедет без ключа администратора или без адреса репозитория.
# Частая причина — ключ без кавычек: bash читает `ADMIN_SSH_KEY=ssh-ed25519 AAAA…`
# как команду AAAA… с временной переменной, и ADMIN_SSH_KEY остаётся пустым.
# IMAGE_TAG обязателен на всех площадках: up-app.sh на ВМ зовёт
# `make -C infra up … IMAGE_TAG=<тег>`, и пустой тег — стек без образов.
# YC_CLI_*, GIT_HOST_KEY и параметры облака обязательны только вне local:
# на libvirt и vagrant ветки setup-yc.sh и clone-repo.sh сами себя пропускают
# по detect-env.sh, и пустая подстановка там безвредна.
REQUIRED_VARS=(DEPLOYMENT_TARGET GIT_REPO_URL ADMIN_SSH_KEY IMAGE_TAG)
if [[ "${DEPLOYMENT_TARGET:-}" != "local" ]]; then
  REQUIRED_VARS+=(YC_CLOUD_ID YC_FOLDER_ID KMS_KEY_ID DEPLOY_SSH_KEY_ENCRYPTED_B64)
  REQUIRED_VARS+=(YC_CLI_VERSION YC_CLI_SHA256 GIT_HOST_KEY)
fi
MISSING_VARS=""
for v in "${REQUIRED_VARS[@]}"; do
  [[ -n "${!v:-}" ]] || MISSING_VARS+=" ${v}"
done
if [[ -n "${MISSING_VARS}" ]]; then
  echo "ERROR: в ${ENV_FILE} пустые обязательные переменные:${MISSING_VARS}" >&2
  echo "       Для yc-* обязательны и YC_CLOUD_ID, YC_FOLDER_ID, KMS_KEY_ID, DEPLOY_SSH_KEY_ENCRYPTED_B64," >&2
  echo "       а также YC_CLI_VERSION, YC_CLI_SHA256 и GIT_HOST_KEY (их даёт env job'а ci/service-contour.yaml)." >&2
  echo "       Файлы targets/*.env читают значения из окружения (форма \${VAR:-плейсхолдер}); в CI их передаёт service-contour.yaml." >&2
  exit 1
fi

# Перевод строки в значении — инъекция в YAML: ADMIN_SSH_KEY из двух строк
# после подстановки становится вторым элементом ssh_authorized_keys, и на ВМ
# приезжает чужой ключ (проверено: yaml.safe_load такой вывод принимает).
# Все подставляемые значения однострочные по построению.
# shellcheck disable=SC2086  # разбиение SUBST_VARS по пробелам намеренное
for v in ${SUBST_VARS//[\$\{\}]/}; do
  case "${!v:-}" in
    *$'\n'* | *$'\r'*)
      echo "ERROR: ${v} в ${ENV_FILE} содержит перевод строки — в cloud-init это инъекция YAML" >&2
      exit 1
      ;;
  esac
done

# Флаг действует только для локальных площадок — см. таблицу кодов возврата.
if [[ ${ALLOW_PLACEHOLDERS} -eq 1 && "${DEPLOYMENT_TARGET:-}" != "local" ]]; then
  echo "ERROR: --allow-placeholders допустим только при DEPLOYMENT_TARGET=local" >&2
  echo "       (libvirt, vagrant); у target'а ${TARGET} DEPLOYMENT_TARGET=${DEPLOYMENT_TARGET:-<пусто>}." >&2
  echo "       Для облачных площадок заполните плейсхолдеры в targets/${TARGET}.env и в vm.yaml.tmpl." >&2
  exit 1
fi

# ГРАБЛИ: envsubst БЕЗ аргумента подставляет ВСЕ ссылки вида $VAR и ${VAR},
# а неизвестные ему переменные заменяет пустой строкой. В шаблоне лежат
# встроенные shell-скрипты, и голый `envsubst < tmpl` молча съедает $ENV_TYPE,
# $IAM_TOKEN, $VERSION_CODENAME и $UPTIME —
# cloud-init отрендерится, приедет на ВМ и там сломается. Поэтому подстановка
# идёт по ЗАКРЫТОМУ списку.
envsubst "${SUBST_VARS}" < "${TMPL}" > "${OUTPUT}"

# Плейсхолдеры, до которых не дошли руки эксплуатации, ловим здесь, а не в
# логе cloud-init на ВМ: REPLACE_WITH_* — из targets/*.env (в самом шаблоне
# литеральных плейсхолдеров нет, всё приходит подстановкой);
# <service> — имя сервиса, которое
# подставляется руками при заводке репозитория и незамеченным уезжает в
# путь cron.d и имя лога. Комментарии пропускаем — там имена стоят в инструкциях.
# Маркер имени сервиса собран из двух строк намеренно: scaffold.sh заменяет
# литерал «<serv»+«ice>» во ВСЕХ скопированных файлах, в том числе в этом
# скрипте, и цельный маркер в шаблоне grep превратился бы в имя продукта —
# после чего рендер падал бы на каждой строке с этим именем (найдено прогоном
# на каркасе набора). Оболочка склеивает половины только во время выполнения.
SERVICE_MARK='<serv''ice>'
LEFTOVERS="$(grep -nE "REPLACE_WITH_[A-Z0-9_]+|${SERVICE_MARK}" "${OUTPUT}" | grep -vE '^[0-9]+:[[:space:]]*#' || true)"
if [[ -n "${LEFTOVERS}" ]]; then
  if [[ ${ALLOW_PLACEHOLDERS} -eq 1 ]]; then
    echo "WARN: в выводе остались незаполненные плейсхолдеры (разрешено флагом для локальной площадки):" >&2
    echo "${LEFTOVERS}" | indent >&2
  else
    echo "ERROR: в выводе остались незаполненные плейсхолдеры — такой user-data на ВМ не поедет:" >&2
    echo "${LEFTOVERS}" | indent >&2
    echo "       Заполните их в targets/${TARGET}.env или передайте окружением (в CI — env job'а ci/service-contour.yaml)." >&2
    rm -f "${OUTPUT}"
    echo "       Выходной файл удалён: ${OUTPUT}" >&2
    exit 1
  fi
fi

# Синтаксис YAML: user-data, который не разобрался, cloud-init отбрасывает
# целиком — на ВМ одна строка в логе и пустой стек. Проверка зависит от
# python3 с PyYAML; нет — печатаем, что пропущена, и не падаем.
if command -v python3 >/dev/null 2>&1 && python3 -c 'import yaml' >/dev/null 2>&1; then
  if ! YAML_ERR="$(python3 -c 'import sys, yaml; yaml.safe_load(open(sys.argv[1], encoding="utf-8"))' "${OUTPUT}" 2>&1)"; then
    echo "ERROR: вывод не разбирается как YAML:" >&2
    echo "${YAML_ERR}" | indent >&2
    rm -f "${OUTPUT}"
    echo "       Выходной файл удалён: ${OUTPUT}" >&2
    exit 1
  fi
else
  echo "  YAML-проверка пропущена: нет python3 с модулем yaml"
fi

echo "Готово: ${OUTPUT}"
