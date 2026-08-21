# Export spec

| Format | Endpoint | Content |
|--------|----------|---------|
| Excel | `/export/xlsx` | Объект, элементы (δпр/δ/exclusion), материалы с editable unit price (руб) и формулами сумм |
| PDF | `/export/pdf` | Title, inputs, elements, materials (core font translit scaffold) |
| Word | `/export/docx` | Minimal OOXML: title, inputs, elements, materials |

Цены по умолчанию 0; overrides через `materialPriceEditsCents` на calc.

Паритет с legacy Word (OMML-формулы, сертификаты) — следующий инкремент фазы 5; каркас уже отдаёт docx/pdf/xlsx.
