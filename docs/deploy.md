# Развёртывание на сервере

Цель: постоянная ссылка на калькулятор с OCR для нескольких пользователей.
Стек: `dev/docker-compose.yml` (Postgres, миграции, бэкенд, фронтенд с nginx,
OCR, по желанию Caddy для HTTPS). Всё на одной машине.

## Требования к серверу

| Что | Минимум | Комментарий |
|-----|---------|-------------|
| ОС | Ubuntu 22.04/24.04 или Debian 12 | любой Linux с Docker подойдёт |
| CPU / RAM | 2 vCPU, 4 ГБ | OCR одного листа — от 10 с до 2 мин CPU (пик памяти ~0,6 ГБ плюс кэш шаблонов до 512 МБ, `OCRPDF_TEMPLATE_CACHE_MB`); задания идут по одному, при нескольких пользователях лучше 4 vCPU. Пределы на задание — `OCRPDF_MAX_PAGES`, `OCRPDF_MAX_SEC_PER_PAGE` в `.env` |
| Диск | 15 ГБ | образ OCR 1,4 ГБ, результаты заданий живут 6 часов, дисковый кэш шаблонов глифов — до 512 МБ (`OCRPDF_TEMPLATE_DISK_MB`) |
| Сеть | открыт входящий 80 (и 443 для HTTPS) | остальные порты наружу не публикуются |
| Домен | по желанию | без домена ссылка вида `http://<ip>/`, HTTPS невозможен |

## Шаги

1. Установить Docker:
   ```bash
   curl -fsSL https://get.docker.com | sh
   ```
2. Скопировать репозиторий `ozm-new` на сервер (git clone или `scp -r`).
   Служебные папки `dev/backend`, `dev/frontend`, `dev/ocr` не нужны, compose
   ссылается на `../backend` и т.п.
3. Положить чертёжные шрифты в `dev/deploy/fonts/` (с Windows-машины из
   `C:\Windows\Fonts`): `arial.ttf`, `arialn.ttf`, `isocpeur.ttf`, `isocpeui.ttf`,
   `GOST Common.ttf`, `GOST type A.ttf`, `GOST type B.ttf`. Без них OCR читает
   листы без текстового слоя заметно хуже. Шрифты в репозиторий не коммитить.
4. Запустить:
   ```bash
   bash dev/scripts/deploy.sh
   ```
   Скрипт создаст `dev/.env` со случайными паролем БД и API-токеном, файл
   `dev/deploy/htpasswd` с пользователем `ozm` и случайным паролем (печатается
   один раз), соберёт образы и поднимет стек. Свои логин/пароль можно задать
   заранее: `OZM_USER=ivanov OZM_PASSWORD='...' bash dev/scripts/deploy.sh`.
5. Открыть `http://<ip-сервера>/`, ввести логин и пароль.

## HTTPS

Нужен домен, A-запись которого указывает на сервер. В `dev/.env` задать
`PUBLIC_DOMAIN=calc.example.ru` и `HOST_PORT=127.0.0.1:8081`, затем снова
`bash dev/scripts/deploy.sh`: скрипт включит профиль `tls`, Caddy получит
сертификат Let's Encrypt и будет обновлять его сам. Ссылка: `https://calc.example.ru/`.

## Как защищён доступ

- Вход на сайт и в OCR закрыт паролем nginx (`dev/deploy/htpasswd`, bcrypt).
- Бэкенд снаружи не публикуется. В `/api/` nginx пропускает только запросы с
  токеном `API_TOKEN`, который зашивается в бандл фронтенда при сборке, а бандл
  отдаётся только после ввода пароля.
- Собственной аутентификации у бэкенда пока нет (OIDC отмечен как TODO в
  `backend/internal/ogz/auth`), поэтому он работает в dev-режиме. Это допустимо
  только за nginx с паролем; порт 8080 наружу открывать нельзя.
- Postgres и OCR доступны только внутри сети compose.

## Добавить или сменить пользователя

```bash
docker run --rm httpd:2.4-alpine htpasswd -nbB petrov 'пароль' >> dev/deploy/htpasswd
docker compose -f dev/docker-compose.yml exec frontend nginx -s reload
```

## Обновление

```bash
git pull            # или заново скопировать исходники
bash dev/scripts/deploy.sh
```

Данные Postgres лежат в томе `pgdata`, результаты OCR в `ocr-jobs`; при
пересборке они сохраняются.

## Вариант: скрытая страница на calclab.pro

Вместо своего сервера калькулятор можно отдать под префиксом на существующем
сайте: https://calclab.pro/ozm/ (в меню ссылки нет). Фронт собирается с
`VITE_BASE_PATH=/ozm/` (vite `base`; роутер, `/api/v1` и адрес OCR-фрейма
считаются от него), образы собираются здесь и заливаются на сервер готовыми:

```powershell
powershell -File dev\scripts\build-calclab-images.ps1   # -> D:\dev\ozm-release\
```

Compose, шаблон nginx и скрипты установки лежат в репозитории calclab.pro
(`deploy/ozm/`, `deploy/OZM.ru.md`). Пароля на вход там нет — как у остальных
скрытых страниц сайта; `/api/` по-прежнему принимает только токен из бандла.

## Проверка после запуска

```bash
docker compose -f dev/docker-compose.yml ps
curl -s -o /dev/null -w '%{http_code}\n' http://localhost/            # 401 без пароля
curl -s -u ozm:пароль http://localhost/ocr/api/capabilities           # движки OCR
```
