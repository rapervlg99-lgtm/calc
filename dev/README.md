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

## Env

См. [`.env.example`](.env.example). Prefix: `CALC_OZM_*`.
