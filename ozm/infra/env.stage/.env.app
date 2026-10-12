# Шаблон скилла tnlife-miniapp-engineering: переменные приложения продукта.
# Норма — 01-corp-standard.md, «Файлы окружения». Подставьте stage,
# <домен контура>, <домен-суперапа> (только мини-апп), <владелец>; секреты —
# при деплое.
#
# Формат обязателен (§2.3 корп. шаблона и проверка [3/15]): первая строка —
# комментарий, после «.env.» точек больше нет, файл кончается пустой строкой,
# обязательные переменные раскомментированы, необязательные — закомментированы.
#
# Три вида значений, и конфиг (internal/config) различает их:
#   - настоящее значение — у каждой активной строки локального стенда;
#   - REPLACE_WITH_* — подставляет служба эксплуатации при деплое (проверка
#     check-env.sh [8/8]); вне local с таким значением сервис не стартует, на
#     local dev-значение генерирует scaffold.sh (--set или openssl rand);
#   - угловые скобки <…> — подставить до запуска: с ними сервис не стартует ни
#     на одном контуре.

# Контур: local, stage или prod. Вне local конфигурация fail-closed —
# пустой или небезопасный параметр не даёт сервису подняться.
APP_ENV=stage
LOG_LEVEL=info
# Слушатель API и проб: /api/v1/*, /healthz, /readyz.
HTTP_ADDR=:8080
# Отдельный слушатель /metrics (08-observability.md §9): в compose у сервиса
# только expose, на хост не публикуется, скрейпит коллектор внутри сети
# compose. Обязан отличаться от HTTP_ADDR — конфиг это проверяет.
METRICS_ADDR=:9090
# Вход стека на хосте: единственный порт, который compose публикует без
# профиля. Локальный стенд — 127.0.0.1:8088 (traefik держит :80/:443, а наружу
# смотреть не нужно); stage и prod — 0.0.0.0 и 80, TLS терминирует балансировщик
# (readme-deploy §1.3). Порт ниже 1024 внутри контейнера не нужен: nginx
# слушает 8080 под непривилегированным пользователем.
WEB_HOST_IP=127.0.0.1
WEB_HOST_PORT=8088
APP_VERSION=REPLACE_WITH_IMAGE_TAG
TZ_APP=Europe/Moscow
SHUTDOWN_TIMEOUT=15s

# Секрет подписи сессионной cookie, минимум 32 байта: openssl rand -base64 48.
# Вне local пустое значение — отказ старта, а не молчаливый дефолт.
SESSION_SECRET=REPLACE_WITH_SESSION_SECRET
# Ротация без разлогина всех: новый ключ — в SESSION_SECRET, прежний — сюда на
# один SESSION_TTL (старые сессии ещё принимаются), затем строку закомментировать.
# SESSION_SECRET_PREVIOUS=REPLACE_WITH_SESSION_SECRET_PREVIOUS
# Срок жизни своей сессии (access и refresh). Дефолта в коде нет — значение
# задаётся здесь; ориентир набора 12 часов (references/03-auth-profile.md,
# матрица переменных).
SESSION_TTL=12h
# Cookie сессии ставится с Path=/api/v1/auth; samesite принимает
# lax | none | strict, none работает только вместе с secure=true (HTTPS).
SESSION_COOKIE_SECURE=true
# Без суперапа документ не встраивается: lax (03 §4).
SESSION_COOKIE_SAMESITE=lax

# Базовый https-адрес контура без завершающего слэша: из него бэкенд строит
# абсолютные ссылки в письмах и дефолты redirect-URL.
PUBLIC_URL=https://<домен контура>

# Куда бэкенд редиректит браузер после успешного OIDC-callback. Путь ОБЯЗАН
# существовать в SPA: nginx отдаёт на любой навигационный маршрут index.html,
# и на несуществующем маршруте пользователь увидит пустой экран, а не ошибку.
# Канон пути — /auth/callback (маршрут во frontend/src/router/index.ts);
# меняете здесь — заводите маршрут там же одним MR.
FRONTEND_SUCCESS_URL=https://<домен контура>/auth/callback
# Origin'ы, которым разрешён кросс-доменный запрос: свой домен и, если API зовут
# браузерные клиенты с другого домена, их домены поимённо. «*» запрещена.
CORS_ALLOWED_ORIGINS=https://<домен контура>

# Доверенный прокси. ОДНА сеть в CIDR-нотации, из которой nginx фронта верит
# X-Forwarded-For и подменяет client_ip (модуль realip; realip.conf.template,
# NGINX_ENVSUBST_FILTER в Dockerfile.frontend). Переменная ОБЯЗАТЕЛЬНА на всех
# контурах: без неё realip выключен, client_ip в логе nginx и X-Real-IP на
# бэкенде равны адресу балансировщика — и весь rate-limit входа сидит на одном
# ключе, то есть 21 запрос в минуту от любого клиента блокирует вход всей
# компании (RATE_LIMIT_AUTH_PER_MIN ниже).
# stage и prod — сеть балансировщика, значение даёт служба эксплуатации.
# ЗАПРЕЩЕНО подставлять широкие диапазоны (10.0.0.0/8, 172.16.0.0/12,
# 192.168.0.0/16): доверие всей приватной сети делает «доверенным прокси»
# любого сотрудника, и он подставит чужой адрес в лог ИБ.
# Проверка: `docker exec ozm-web cat /etc/nginx/conf.d/realip.conf`
# печатает set_real_ip_from с этой сетью; tests/check-env.sh требует
# переменную вне local.
TRUSTED_PROXY_CIDR=REPLACE_WITH_LB_CIDR

# Частота запросов: /api/v1/auth/* — на IP, мутации — на пользователя.
RATE_LIMIT_AUTH_PER_MIN=20
RATE_LIMIT_MUTATIONS_PER_MIN=120

# Предел тела JSON-запроса — одно число на весь продукт: 1 МиБ в байтах.
# То же число стоит в nginx (client_max_body_size 1m): разъедутся — отказ
# payload_too_large придёт с прокси и с бэкенда по-разному.
MAX_JSON_BODY=1048576

# TTL персональных данных: сколько дней от входа записи в терминальный статус
# до стирания (06-data-privacy.md §4). Ориентир набора — 30; итоговое
# значение утверждает владелец продукта <владелец> вместе с юристом. Ноль
# выключает автоудаление и допустим только на local.
PDN_RETENTION_DAYS=30

# Ключ шифрования колонок AES-256-GCM (06-data-privacy.md §9): base64 ровно
# от 32 байт — openssl rand -base64 32. Вне local пустое значение — отказ старта.
ENCRYPTION_KEY=REPLACE_WITH_ENCRYPTION_KEY
# Ротация ключа: новый — в ENCRYPTION_KEY, прежний — сюда на время
# перешифровки данных скриптом, затем строку закомментировать.
# ENCRYPTION_KEY_PREVIOUS=REPLACE_WITH_ENCRYPTION_KEY_PREVIOUS

# Пул подключений к БД. Ориентир: на prod 20, на local и stage — 10.
PG_MAX_CONNS=10

# Ежедневный дайджест на общий ящик подразделения — если продукт шлёт письма.
# DIGEST_ENABLED=true
# DIGEST_SEND_AT=08:00
# DIGEST_RECIPIENTS=REPLACE_WITH_TEAM_MAILBOX

# Автонапоминания до контрольной даты — если продукт шлёт письма.
# REMINDER_DAYS_BEFORE — список смещений в днях через запятую.
# REMINDERS_ENABLED=true
# REMINDER_DAYS_BEFORE=7,2
# REMINDER_SEND_AT=09:00

# Bootstrap-администраторы: кому выдать полный набор ролей при первом входе,
# пока некому раздавать права через интерфейс. Список кодов сотрудника (ЕКС)
# через запятую; значения даёт бизнес-владелец, это вопрос Q6 в
# templates/project-docs/go-live-auth.md. Fallback по адресу почты — только если код
# сотрудника недоступен (нет scope employee.read).
# BOOTSTRAP_ADMIN_PORTAL_CODE=REPLACE_WITH_PORTAL_CODES
# BOOTSTRAP_ADMIN_EMAIL=REPLACE_WITH_ADMIN_EMAIL

# Параметры домена: сроки SLA, лимиты, режимы продукта.
# Имена — латиницей, по одному значению на строку.
# <КЛЮЧ_ПРОДУКТА>=<значение>

# Локальный стенд: подробный лог, версия dev, CORS только на SPA стенда
# (домен суперапа локально не нужен). Блок раскомментирует scaffold.sh для
# env.local, одноимённые строки контура выше он комментирует.
# LOG_LEVEL=debug
# APP_VERSION=dev
# CORS_ALLOWED_ORIGINS=https://app.localhost
# Сеть compose, в которой живёт traefik. Значение своё на каждой машине —
# Compose выдаёт подсеть из пула Docker, поэтому в шаблоне плейсхолдер, а не
# число: `docker network inspect ozm_ozm-net \
#   --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}'` после первого `up`
# (шаг 5 в env.local/README.md). Пока не заполнено, работает дефолт образа
# 127.0.0.1/32 — realip выключен, и локально это безвредно.
# TRUSTED_PROXY_CIDR=REPLACE_WITH_COMPOSE_SUBNET

# ── Продукт OZM (класс 2 нормы) ──────────────────────────────────────────────
# Настройки, которых нет в корпоративной норме: распознавание таблиц ИД и
# провайдер зрения. Имена — контракт продукта с префиксом CALC_OZM_APP_
# (backend/internal/envconfig), у каждой настройки ровно одно имя.
CALC_OZM_APP_OCR_ENABLED=true
# Аутентификации у продукта пока нет (OIDC — TODO): false закрывает /ext на
# контуре (401). Включать true можно только временно и вместе с закрытым входом.
CALC_OZM_APP_AUTH_DEV_MODE=false
CALC_OZM_APP_STORAGE_DIR=/tmp/ozm-blobs
CALC_OZM_APP_MAX_UPLOAD_BYTES=31457280
CALC_OZM_APP_VISION_PROVIDER=ollama
# Адрес модели зрения и токен провайдера подставляет эксплуатация.
CALC_OZM_APP_OLLAMA_URL=REPLACE_WITH_VISION_URL
CALC_OZM_APP_OLLAMA_MODEL=qwen3.5:9b
CALC_OZM_APP_ADMIN_TOKEN=REPLACE_WITH_ADMIN_TOKEN

