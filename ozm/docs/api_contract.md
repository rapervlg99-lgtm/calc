# API contract (frozen for redesign)

Base: `/api/v1`

## GET /dicts → DictsResponse

`profiles`, `roll`, `selects`, `materials`, `config` — see `frontend/src/types/api.ts` and `backend/internal/models`.

## POST /calc

Request: `CalcRequest` (groups/elements/beton/consent…).  
Response: `CalcResponse` with `id`, `elements[]`, `materials[]`, `totals`, `trace`.

Money fields: `*Cents` int64.

## GET /calc/{id}

Persisted response JSON.

## POST /export/{pdf|xlsx|docx}

Body: `{ "calcId": "<uuid>" }` → file download.

**Redesign must not change these shapes.** Additive fields only via versioned agreement.
