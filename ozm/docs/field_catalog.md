# Field catalog

| UI label | API path | Type | Required | Notes |
|----------|----------|------|----------|-------|
| Наименование объекта | `objectName` | string | yes | |
| Адрес | `address` | string | yes | |
| Согласие ПДн | `consent` | bool | yes eq true | |
| Степень огнестойкости | `frDurability` | string | yes | I–V |
| Группа.title | `groups[].title` | string | no | |
| Группа.quantity | `groups[].quantity` | number | yes >0 | |
| Элемент.title | `groups[].elements[].title` | string | no | |
| Профиль | `...shape` | string | yes | I-beam_ / channel_ / … |
| Сортамент | `...rollId` | string | no | dims from roll |
| Размеры | `...dims` | map | if no roll | h,b,s,t,R,… |
| Тип конструкции | `...frType` | "0"|"1" | yes | |
| R | `...htLevel` | number | yes | 15…240 |
| Стороны | `...sides.*` | bool | | default all if none |
| Длина м | `...lengthM` | number | yes | |
| Кол-во | `...quantity` | number | yes | |
| Покрытие | `...coat` | string | yes | 1/2/3/4/1.5 |
| Метод | `...method` | "0"|"1" | yes | |
| Primer | `...primer` | bool | no | TAIKOR |
| Enamel | `...enamel` | bool | no | TAIKOR |
| Бетон S | `beton.areaM2` | number | if beton | |
| Бетон R | `beton.htLevel` | 180\|240 | if beton | |
| Цена материала | `materialPriceEditsCents[id]` | int64 | no | копейки |
