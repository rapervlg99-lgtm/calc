# syntax=docker/dockerfile:1.7
FROM node:22-alpine AS build
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

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
