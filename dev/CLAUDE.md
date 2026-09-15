# ozm-new — CLAUDE.md

Калькулятор огнезащиты (ПТМ) + распознавание таблиц ИД. Каркас как у отмостки (blind-area-calc).

## Источники истины

| Что | Где |
|-----|-----|
| Поведение расчёта | `docs/calc_rules_summary.md` + `backend/internal/calc` + golden |
| Поля UI/API | `docs/field_catalog.md` + `docs/api_contract.md` |
| UX inventory | `docs/ux_inventory.md` |
| OCR / ext API | `backend/internal/ogz` + firefight openapi-ext (Phase 1+) |
| Legacy oracle | `teplotech-ozm` /ares (не править без паритета) |

## Правила

1. UI не меняет формулы. Новые поля — только через изменение контракта + спеки + golden.
2. Деньги — копейки end-to-end.
3. Dicts baseline в `backend/dicts/*.json`, seed в Postgres.
4. OCR включается флагом `CALC_OZM_APP_OCR_ENABLED`; при `false` calc жив, `/ext` не монтируется.
5. Firefight `internal/calc` при переносе → `internal/ogz/ogzcalc` (не конфликтовать с ОЗМ engine).
6. Не коммитить секреты; infra stage/prod — stub до Phase 5.

## Стек

- Backend: Go 1.26, chi, pgx, goose — module `ozm/backend`
- Frontend: Vue 3 + Vite + Pinia
- OCR: Python 3.12, пакет `ocrpdf` в `ocr/` (PyMuPDF, OpenCV, RapidOCR + Tesseract), тесты `pytest ocr/tests`, журнал `ocr/WORKLOG.md`
- Compose: `dev/docker-compose.local.yml` → UI `:5173`, API `:8080`, OCR `:8000`
- Env prefix: `CALC_OZM_*`
- Service: `ozm-backend`, DB: `ozm`

## Локальный URL

`http://localhost:${HOST_PORT:-5173}/`
