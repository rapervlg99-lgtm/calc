# syntax=docker/dockerfile:1.7
# Прокси сборки: пусто — прямой доступ, иначе хост:порт (норма §2.1)
ARG DOCKER_PROXY_HOST_1=
FROM ${DOCKER_PROXY_HOST_1}node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
# Bearer-токен для /api (см. utils/extApi.ts); на сервере nginx пропускает
# в /api/ только его. Локально остаётся dev-token.
ARG VITE_AUTH_DEV_TOKEN=dev-token
ENV VITE_AUTH_DEV_TOKEN=$VITE_AUTH_DEV_TOKEN
# Префикс, под которым приложение отдаётся наружу: «/» (свой домен) или
# «/ozm/» (скрытая страница calclab.pro). См. vite.config.ts.
ARG VITE_BASE_PATH=/
ENV VITE_BASE_PATH=$VITE_BASE_PATH
RUN npm run build

FROM ${DOCKER_PROXY_HOST_1}nginx:1.27-alpine

# non-root (норма §2.2, проверка [15/15]): nginx работает от uid 10001. Под
# непривилегированным пользователем :80 не забиндить — server в nginx.conf
# слушает 8080. Рабочие каталоги nginx (/var/cache — временные тела и прокси,
# /var/log — симлинки логов на stdout/stderr) и pid-файл отдаются тому же uid:
# без этого контейнер падает на старте с
# «open() "/var/run/nginx.pid" failed (13: Permission denied)».
# Каталог /etc/nginx/conf.d тоже отдаётся uid: в него entrypoint образа рендерит
# server прод-контура из /etc/nginx/templates (см. COPY ниже).
# «user nginx» в главном nginx.conf образ оставляет как есть: под non-root
# директива игнорируется с предупреждением, воркеры и так идут от 10001.
RUN addgroup -g 10001 -S appgroup \
 && adduser -u 10001 -S appuser -G appgroup \
 && chown -R appuser:appgroup /var/cache/nginx /var/log/nginx /etc/nginx/conf.d \
 && touch /var/run/nginx.pid \
 && chown appuser:appgroup /var/run/nginx.pid

# Файл отдаётся тому же uid: прод-контур (dev/docker-compose.yml) монтирует в
# /etc/nginx/templates свой server с basic auth и токеном, а entrypoint образа
# перезаписывает ИМЕННО этот default.conf. Файл, принадлежащий root, под uid
# 10001 не перезаписать («can't create /etc/nginx/conf.d/default.conf: Permission
# denied»), и наружу ушёл бы конфиг из образа — без пароля. Проверено запуском.
COPY --chown=appuser:appgroup nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build --chown=appuser:appgroup /app/dist /usr/share/nginx/html

USER 10001:10001
EXPOSE 8080
