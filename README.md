# ozm-new — калькулятор огнезащиты + OCR таблиц ИД

Монорепо по шаблону blind-area-calc:

| Папка | Назначение |
|-------|------------|
| `backend/` | Go API (`ozm/backend`): calc + `/api/v1/ext` (OCR) |
| `frontend/` | Vue 3 SPA |
| `dev/` | compose local/test/prod-like, smoke, junctions → backend/frontend |
| `infra/` | stub stage/prod (Phase 5) |
| `docs/` | продуктовые/API спеки |

Slug: **ozm**. Env: **`CALC_OZM_*`**. Сервис: **`ozm-backend`**. DB: **`ozm`**.

Источники: calc ← `ozm-calc`, OCR ← `firefight/New project`, каркас ← `blind-area-calc`.

## Быстрый старт

```bash
cd dev
docker compose -f docker-compose.local.yml up --build
```

- UI: http://127.0.0.1:5173/
- API: http://127.0.0.1:8080/healthz

Smoke (при поднятом backend):

```powershell
powershell -File ./scripts/smoke-backend.ps1
```

## Документация

См. [dev/README.md](dev/README.md), [dev/CLAUDE.md](dev/CLAUDE.md), [docs/](docs/).
