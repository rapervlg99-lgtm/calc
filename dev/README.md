# ozm-new — calc + OCR (стек отмостки)

Монорепо: `backend` (Go) + `frontend` (Vue 3) + `dev` (compose) + `infra` (stub) + `docs`.

- Calc: порт legacy `teplotech-ozm` /ares → `ozm-calc`.
- OCR: `firefight/New project` → `backend/internal/ogz` (Phase 1+).
- Эталон стека: `blind-area-calc`.

## Быстрый старт

```bash
cd dev
docker compose -f docker-compose.local.yml up --build
```

Открыть: http://127.0.0.1:5173/

API: http://127.0.0.1:8080/healthz

Compose contexts `./backend` и `./frontend` — Windows junctions на соседние папки
(создаются локально, в git не коммитятся). Если их нет:

```powershell
cmd /c mklink /J backend ..\backend
cmd /c mklink /J frontend ..\frontend
```

## Smoke

```powershell
powershell -File ./scripts/smoke-backend.ps1
# или: BASE_URL=http://localhost:8080 bash ./scripts/smoke-backend.sh
```

## Перегенерация справочников из DC.xml

```bash
cd ../backend
python scripts/dcextract.py
```

## Тесты calc

```bash
docker run --rm -v "%CD%/../backend:/src" -w /src golang:1.26-alpine go test ./internal/calc/...
```

Интеграция с Postgres:

```bash
docker compose -f docker-compose.test.yml up -d
# TEST_DATABASE_URL=postgres://test:test@localhost:15432/ozm_test?sslmode=disable
```

## API

- `GET /api/v1/dicts`
- `POST /api/v1/calc`
- `GET /api/v1/calc/{id}`
- `POST /api/v1/export/pdf|xlsx|docx` body `{ "calcId": "..." }`
- ` /api/v1/ext/*` — OCR (только при `CALC_OZM_APP_OCR_ENABLED=true`)

Деньги — копейки (`int64`).

## OCR: кнопка «Распознать таблицу ИД»

`/recognize` встраивает во фрейм OCR-сервис `ocrpdf` (папка `ocr/`, контейнер
`ocr` в compose, порт 8000). nginx фронта проксирует `/ocr/` -> `ocr:8000/` и шлёт
`X-Forwarded-Prefix: /ocr`, vite dev-сервер делает то же для `/ocr` (на
`localhost:8000`, порт опубликован из контейнера). Адрес можно переопределить
сборочной переменной `VITE_OCR_URL`.

Контейнеру нужны чертёжные шрифты для шаблонов глифов (листы без текстового
слоя): по умолчанию монтируется `C:/Windows/Fonts`; на другой ОС задайте
`OCR_FONTS_DIR` в `.env`. Без Docker сервис можно запустить и на хосте:
`python ocr/webapp.py --port 8000` (venv с `requirements.txt` + rapidocr-onnxruntime,
pytesseract и бинарник Tesseract) — nginx контейнера его не увидит, а vite
dev-сервер (`npm run dev`) увидит. Тесты OCR: `pytest ocr/tests`.

Поток: PDF загружается прямо в окно OCR -> после распознавания кнопка «Передать в
калькулятор огнезащиты» (появляется только во фрейме, `?embed=1`) шлёт
`postMessage {type:"ocrpdf:result", tables}` -> `utils/ocrImport.ts` собирает из
строк спецификации задание ОГЗ в памяти браузера (id `ocr-…`, как демо-форма) ->
открывается обычная `/recognize/jobs/:id` -> prefill калькулятора как раньше.

Длина строки = масса / погонная масса. Погонная масса берётся из встроенного
справочника масс бэкенда (`GET /api/v1/ext/profiles`, теперь отдаёт весь
справочник с полем `category`), иначе считается по размерам сечения из
справочника проката (статус «Требует проверки»), иначе — «Нужен ввод массы».

Запуск OCR-сервиса на этой машине:

```bash
cd "../ocr (распознавание пдф)" && D:/dev/venvs/ocrpdf/Scripts/python.exe webapp.py --port 8000
```

Серверный путь через `/ext/jobs` (Ollama) и демо-форма остались под спойлером
«Другие способы».

## UI: дизайн-система TN Life

Фронтенд оформлен по макету Claude Design «Калькулятор огнезащиты» на дизайн-системе **TN Life**
(TN Life UI Kit ТЕХНОНИКОЛЬ): `frontend/src/styles/tn/` — токены, CSS компонентов, шрифты Proxima Nova
(`frontend/public/fonts`), подмножество спрайта иконок встроено в `frontend/index.html`.
Vue-обёртки компонентов — `frontend/src/components/ui/` (TnButton, TnInput, TnSelect, TnSearchSelect,
TnCheckbox, TnTumbler, TnCard, TnTag, TnIcon), блоки калькулятора — `frontend/src/components/calc/`.

Поведение по `docs/tz_ui_redesign.md`: явное согласие ПДн, группы конструкций с количеством,
кнопка «Рассчитать» вместо авторасчёта, таблица результатов и ведомость материалов без цен,
панель ОЗБ, трейс расчёта, экспорт после успешного расчёта. Prefill из `/recognize` сохранён.

Разработка без Docker-сборки фронта: `cd frontend && npm install && npm run dev` (порт 5173 занят
контейнером — `npx vite --port 5174`), прокси `/api` → :8080 и `/ocr` → :8000 уже настроены.

## Env

См. [`.env.example`](.env.example). Prefix: `CALC_OZM_*`.
