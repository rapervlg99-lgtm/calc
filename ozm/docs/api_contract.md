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
