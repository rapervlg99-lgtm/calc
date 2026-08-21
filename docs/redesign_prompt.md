# Redesign prompt — для Claude Code (когда макет отдан)

Сейчас **не запускать Code-фазу без макета**. Design-фаза: по `docs/tz_ui_redesign.md` §4 и §8.

```
Ты делаешь РЕДИЗАЙН frontend калькулятора огнезащиты (ozm-new) по макету владельца / Claude Design.

Прочитай по порядку:
1. docs/tz_ui_redesign.md          ← полное ТЗ
2. docs/product_brief.md
3. docs/ux_inventory.md
4. docs/screen_map.md
5. docs/field_catalog.md
6. docs/api_contract.md
7. docs/calc_rules_summary.md
8. docs/redesign_brief.md
9. docs/figma.md (+ assets / приложенный макет)

Правила:
- Меняй ТОЛЬКО frontend/ (и docs/figma* при необходимости)
- Не трогай backend/, dicts, calc, export
- Не меняй типы API и store contract кроме отображения
- Сохрани все поля и сценарии из field_catalog / ux_inventory
- Закрой пробелы из tz_ui_redesign.md §5 (consent, beton, results table, BOM, trace)
- После правок: npm run build должен проходить
- Отрисовывай строго по макету; не выдумывай свой бренд-редизайн поверх макета

В конце — checklist acceptance из tz_ui_redesign.md §9.
```
