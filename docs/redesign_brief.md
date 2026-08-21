# Redesign brief — краткое ТЗ

Полное задание: **`docs/tz_ui_redesign.md`**.

**Статус:** UI в репо — утилитарный паритет. Визуал + закрытие пробелов (consent, beton, BOM, results) — по ТЗ и макету.

## Constraints (нельзя)

1. Не менять `POST /calc` / `GET /dicts` / export payloads (`docs/api_contract.md`).
2. Не менять формулы, округления, тексты exclusion (`docs/calc_rules_summary.md` + golden).
3. Не удалять поля из `docs/field_catalog.md` / `docs/ux_inventory.md`.
4. Backend / dicts / calc / export — **read-only**.

## Можно (по макету)

- Токены, типографика, spacing, layout
- Naive UI / кастомные обёртки (один подход)
- Адаптив
- Figma assets → `frontend/public/figma/...`
- Довести UI до `screen_map` (поля и панели, уже поддержанные API)

## Acceptance

См. checklist в `docs/tz_ui_redesign.md` §9.

## Figma / макет

Пока нет — `docs/figma.md`.  
Когда макет готов: file key / assets → Claude Code по `docs/redesign_prompt.md`.
