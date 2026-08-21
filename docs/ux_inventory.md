# UX inventory — текущий/паритетный UI

## User journey

1. Meta объекта: название, адрес, согласие ПДн, степень огнестойкости здания
2. Группы → элементы:
   - профиль (семья/форма) + ГОСТ сортамент или ручные размеры
   - тип конструкции (несущая / самонесущая)
   - R15…R240
   - стороны нагрева L/T/R/B
   - длина, количество
   - покрытие (ОЗМ / TAIKOR Epoxy / Graphite / Extra+Graphite / АКЗ)
   - метод (короб / контур)
   - для TAIKOR: primer / enamel flags
3. Опционально бетон: площадь + R180/R240
4. Рассчитать → таблица элементов (δпр, δ, V, exclusion) + BOM
5. Выгрузка Excel / PDF / Word

## Валидации

- consent = true обязателен
- objectName, address обязательны
- lengthM > 0, quantity > 0, ≥1 группа и элемент

## Exclusion / aside сообщения

- АКЗ: нужен ручной ввод
- недостижимый R при данном δпр (t500 / x500)

## Состояния

- loading dicts / error dicts / empty result / calc error / success
