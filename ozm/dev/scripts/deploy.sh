#!/usr/bin/env bash
# Развёртывание/обновление стека на сервере (Ubuntu/Debian с Docker).
# Запускать из каталога репозитория: bash dev/scripts/deploy.sh
# Идемпотентен: при повторном запуске пересобирает образы и перезапускает сервисы.
set -euo pipefail

cd "$(dirname "$0")/.."          # -> dev/
DEV_DIR="$(pwd)"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker не найден. Установка: curl -fsSL https://get.docker.com | sh" >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "Нужен плагин docker compose v2 (apt install docker-compose-plugin)" >&2
  exit 1
fi

# --- .env ------------------------------------------------------------------
if [ ! -f .env ]; then
  cp deploy/env.prod.example .env
  PG=$(openssl rand -hex 16); TOKEN=$(openssl rand -hex 24)
  sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$PG/; s/^API_TOKEN=.*/API_TOKEN=$TOKEN/" .env
  echo "Создан dev/.env со случайными POSTGRES_PASSWORD и API_TOKEN."
fi
set -a; . ./.env; set +a

# --- пароль на вход ----------------------------------------------------------
if [ ! -s deploy/htpasswd ]; then
  USER_NAME="${OZM_USER:-ozm}"
  if [ -z "${OZM_PASSWORD:-}" ]; then
    OZM_PASSWORD=$(openssl rand -base64 12 | tr -d '/+=' | cut -c1-14)
    GENERATED=1
  fi
  docker run --rm httpd:2.4-alpine htpasswd -nbB "$USER_NAME" "$OZM_PASSWORD" > deploy/htpasswd
  chmod 600 deploy/htpasswd
  echo "Создан deploy/htpasswd: пользователь $USER_NAME"
  [ -n "${GENERATED:-}" ] && echo "  пароль: $OZM_PASSWORD   (сохраните — больше он не показывается)"
fi

# --- шрифты для OCR ----------------------------------------------------------
FONTS="${OCR_FONTS_DIR:-./deploy/fonts}"
mkdir -p "$FONTS"
if ! ls "$FONTS"/*.ttf >/dev/null 2>&1; then
  echo "ВНИМАНИЕ: в $FONTS нет *.ttf. Скопируйте с Windows (C:\\Windows\\Fonts):" >&2
  echo "  arial.ttf arialn.ttf isocpeur.ttf isocpeui.ttf \"GOST Common.ttf\" \"GOST type A.ttf\" \"GOST type B.ttf\"" >&2
  echo "  Без них OCR листов без текстового слоя будет заметно хуже." >&2
fi

# --- сборка и запуск ---------------------------------------------------------
PROFILE=()
if [ -n "${PUBLIC_DOMAIN:-}" ] && [ "${PUBLIC_DOMAIN}" != "localhost" ]; then
  PROFILE=(--profile tls)
fi
docker compose -f docker-compose.yml "${PROFILE[@]}" up -d --build --remove-orphans
docker compose -f docker-compose.yml "${PROFILE[@]}" ps

echo
if [ ${#PROFILE[@]} -gt 0 ]; then
  echo "Готово: https://${PUBLIC_DOMAIN}/  (сертификат выпускается при первом обращении)"
else
  IP=$(hostname -I 2>/dev/null | awk '{print $1}')
  PORT="${HOST_PORT:-80}"
  case "$PORT" in *:*) PORT="${PORT##*:}";; esac
  if [ "$PORT" = "80" ]; then echo "Готово: http://${IP:-<ip-сервера>}/"; else echo "Готово: http://${IP:-<ip-сервера>}:${PORT}/"; fi
fi
echo "Логин/пароль — из deploy/htpasswd. Логи: docker compose -f dev/docker-compose.yml logs -f"
