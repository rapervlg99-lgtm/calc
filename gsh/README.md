# gsh — конфигуратор гидрошпонки

Подбор ПВХ-гидрошпонки ТЕХНОНИКОЛЬ по назначению узла, типу и расположению
шва, ширине раскрытия и стадии строительства. На выходе — марка, код ЕКН,
расход, ссылка на техлист и PDF с примерами узлов; результат можно
выгрузить в PDF.

Исходник — страница `/references/gsh` сайта
[calclab.pro](https://github.com/tag120592-web/calclab.pro). Здесь лежит
копия файлов, относящихся только к этому конфигуратору, с сохранением
путей внутри того репозитория.

## Состав

| Путь | Что это |
|------|---------|
| `frontend/references/gsh.html` | HTML-точка входа страницы (Vite multi-page) |
| `frontend/src/pages/references/gsh/` | `App.vue` и `main.ts` страницы |
| `frontend/src/components/gsh/` | Компоненты: форма конфигуратора, схема узлов, «как это работает» с легендой маркировки, FAQ, CTA, титульная анимация |
| `frontend/src/composables/useGshConfigurator.ts` | Логика подбора: фильтрация таблицы марок по выбранным параметрам, зависимые списки, автозаполнение |
| `frontend/src/data/gsh.ts` | Данные: таблица марок (ЕКН, расход, техлисты), варианты назначений и швов, шаги, легенда и примеры маркировки, FAQ |
| `frontend/src/lib/gsh-pdf-export.ts` | Выгрузка результата подбора в PDF (pdfmake) |
| `frontend/src/styles/gsh.css` | Стили страницы |
| `img/references/gsh/` | Схема, картинки продуктов (`products/`, `products/full/`), PDF примеров узлов (`nodes/`) |

## Зависимости от общего кода calclab.pro

Файлы ссылаются на общие модули сайта, которых здесь нет:
`@/components/shared/ClCombobox.vue`, `@/components/landing/*`
(шапка, подвал, CTA), `@/composables/useAmbientMotion`,
`@/composables/useScrollReveal`, `@/lib/pdfmake-loader`,
`@/plugins/tn-icons`, а также UI-кит `@life_uikit/uikit` и токены
`css/calclab-tokens.css`. Автономно папка не собирается — она предназначена
для правок данных и логики с последующим переносом в calclab.pro.

## Как запустить

В клоне calclab.pro:

```bash
cd frontend
npm install
npm run dev
```

Страница: `http://localhost:5173/references/gsh.html`. Бэкенд не нужен.

## Как редактировать данные

- Добавить или поправить марку — строка в `GSH_RAW_DATA` в `data/gsh.ts`.
  Поле `k` — ссылка на техлист, `g` — код ЕКН, `h` — название (по нему
  ищутся картинка и PDF узлов в `img/references/gsh/`).
- Легенда маркировки — `GSH_MARKING`, примеры марок над легендой —
  `GSH_MARKING_EXAMPLES`; цвета фрагментов заданы переменными
  `--gsh-mark-*` в `styles/gsh.css`.
