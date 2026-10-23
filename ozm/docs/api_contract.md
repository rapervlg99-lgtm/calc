# API contract (frozen for redesign)

Base: `/api/v1`

## GET /dicts → DictsResponse

`profiles`, `roll`, `selects`, `materials`, `config` — see `frontend/src/types/api.ts` and `backend/internal/models`.

### Сортамент CalcLab (дополнение 2026-09-30)

Записи `roll` дополнены необязательными полями `standard`, `standardLabel`,
`standardStatus`, `familyLabel`, `source`, `sourceRowId`, `areaMm2`, `massPerMeter`.
У перенесённых записей `source=calclab-metalloprokat`, идентификатор —
`calclab:<sourceRowId>`. Площадь дана в мм², масса — в кг/м. Старые записи и их
идентификаторы сохранены. В `profiles` добавлены `channel_bent` и
`channel_unequal`; у неравнополочного швеллера `dims.b1` — меньшая полка, мм.
Запрос `/calc` по-прежнему использует `shape`, `rollId`, `dims`; отдельное поле
ГОСТа не требуется, стандарт определяется выбранной записью `roll`.

## POST /calc

Request: `CalcRequest` (groups/elements/beton/consent…).  
Response: `CalcResponse` with `id`, `elements[]`, `materials[]`, `totals`, `trace`.

Money fields: `*Cents` int64.

## GET /calc/{id}

Persisted response JSON.

## POST /export/{pdf|xlsx|docx}

Body: `{ "calcId": "<uuid>" }` → file download.

**Redesign must not change these shapes.** Additive fields only via versioned agreement.

## Ссылки обмена расчётами

| Метод | Путь | Тело | Ответ |
|---|---|---|---|
| POST | `/api/v1/share` | `{"payload": {…}}` | `{"token": "n…"}` |
| GET | `/api/v1/share/{token}` | — | `{"token", "payload", "updatedAt"}` |
| PUT | `/api/v1/share/{token}` | `{"payload": {…}}` | `{"token"}` |

Токен — «n» + миллисекунды (13 цифр), при коллизии — с трёхзначным хвостом.
`payload` — состояние калькулятора (объект, адрес, конструкции, бетон), сервер
хранит его как есть; размер ограничен 256 КБ (413 при превышении).
Ошибки: 400 (битый токен/тело), 404 (нет ссылки), 503 (нет БД).