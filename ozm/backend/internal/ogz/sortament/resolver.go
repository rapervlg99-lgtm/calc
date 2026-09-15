package sortament

import (
	"context"
	"net/url"
)

// Источники массы 1 пог. метра (совпадают с enum OgzRow.massSource в OpenAPI).
const (
	SourceCache  = "cache"  // взято из локального справочника
	Source23met  = "23met"  // получено онлайн с 23met.ru
	SourceManual = "manual" // введено вручную (хранится в справочнике)
)

// ReferenceStore — локальный справочник масс (кэш 23met.ru + ручные вводы).
// Реализуется storage.ProfileRepo.
type ReferenceStore interface {
	// Get ищет массу по марке: приоритет у записи владельца, затем глобальная.
	Get(ctx context.Context, mark, ownerSub string) (massPerMeter float64, source string, found bool, err error)
	// Put сохраняет/обновляет массу. Пустой ownerSub = глобальная запись.
	Put(ctx context.Context, mark string, massPerMeter float64, source, ownerSub string) error
}

// Provider достаёт массу 1 пог. метра из внешнего источника (23met.ru). Категория
// (slug справочника) выводится из наименования группы профиля (см. Category).
type Provider interface {
	MassPerMeter(ctx context.Context, category, mark string) (float64, error)
}

// Lookup — результат разрешения марки.
type Lookup struct {
	Mark         string  // нормализованная марка
	Category     string  // slug категории 23met ("" — категория не распознана)
	MassPerMeter float64 // масса 1 пог. метра, кг; 0 при Found=false
	Source       string  // cache | 23met
	SourceURL    string  // ссылка на карточку 23met (для проверки специалистом)
	Found        bool
}

// SpravkaURL строит ссылку на карточку профиля 23met (категория/марка) — её видит
// специалист в столбце «Источник 23met» для ручной сверки.
func SpravkaURL(category, mark string) string {
	if category == "" || mark == "" {
		return ""
	}
	return DefaultBaseURL + "/spravka/" + category + "/" + url.PathEscape(mark)
}

// Resolver разрешает марку профиля в массу 1 пог. метра. Стратегия: локальный
// кэш → 23met.ru (с записью в кэш). Любая ошибка внешнего источника —
// graceful degradation: возвращаем Found=false, вызывающий ставит строке статус
// «Нужен ввод массы» (ТЗ §5, приоритет — не падать на внешнем сбое).
type Resolver struct {
	store    ReferenceStore
	provider Provider
}

func NewResolver(store ReferenceStore, provider Provider) *Resolver {
	return &Resolver{store: store, provider: provider}
}

// Resolve нормализует марку, выводит категорию и ищет массу 1 пог. метра.
// Стратегия: БД-кэш → инженерный справочник масс → курируемый сид → 23met.ru.
// Не возвращает ошибку: внешний сбой или ненайденный профиль трактуется как
// «масса не найдена» (Found=false) → вызывающий ставит «нет данных» (ТЗ §5).
//
// Ключ справочника — "<категория>/<марка>": одна и та же марка («75x5») в разных
// категориях (уголок/гнутый уголок) имеет разную массу, поэтому кэшируем раздельно.
//
// Категория: наименование группы → ГОСТ → буква серии марки («10Б1» → двутавр).
// Геометрия в калькулятор уходит отдельно из roll.json по той же марке (prefill).
func (r *Resolver) Resolve(ctx context.Context, name, gost, rawMark, ownerSub string) Lookup {
	mark := Normalize(rawMark)
	if mark == "" {
		return Lookup{}
	}
	cat := ResolveCategory(name, gost, mark)
	// Уголок в спецификации часто записан двумя числами («63Х5»), а карточка 23met —
	// тремя («63Х63Х5»). Разворачиваем равнополочный уголок под формат справочника.
	if cat == CatUgolok || cat == CatUgolokGnut {
		mark = ExpandAngleMark(mark)
	}
	srcURL := SpravkaURL(cat, mark)
	key := mark
	if cat != "" {
		key = cat + "/" + mark
	}
	if r.store != nil {
		if mpm, _, ok, err := r.store.Get(ctx, key, ownerSub); err == nil && ok && mpm > 0 {
			return Lookup{Mark: mark, Category: cat, MassPerMeter: mpm, Source: SourceCache, SourceURL: srcURL, Found: true}
		}
	}
	// Инженерный справочник масс металла (Excel → mass_handbook.json): полная
	// офлайн-таблица кг/м.п. «10Б1»/«10 Б1» → balka + 8.1 без сети.
	if mpm, hbCat, ok := handbookMass(cat, mark); ok {
		if cat == "" {
			cat = hbCat
			srcURL = SpravkaURL(cat, mark)
			key = mark
			if cat != "" {
				key = cat + "/" + mark
			}
		}
		if r.store != nil {
			_ = r.store.Put(ctx, key, mpm, SourceHandbook, "")
		}
		return Lookup{Mark: mark, Category: cat, MassPerMeter: mpm, Source: SourceHandbook, SourceURL: srcURL, Found: true}
	}
	// Курируемый офлайн-сид (reference_seed.go) — до 23met: эталонные профили
	// заказчика всегда разрешаются локально, даже когда 23met отдаёт 429 на пачку.
	if mpm, ok := seedMass(mark); ok {
		if r.store != nil {
			_ = r.store.Put(ctx, key, mpm, SourceCache, "")
		}
		return Lookup{Mark: mark, Category: cat, MassPerMeter: mpm, Source: SourceCache, SourceURL: srcURL, Found: true}
	}
	if r.provider != nil && cat != "" {
		if mpm, err := r.provider.MassPerMeter(ctx, cat, mark); err == nil && mpm > 0 {
			if r.store != nil {
				_ = r.store.Put(ctx, key, mpm, Source23met, "") // кэшируем глобально
			}
			return Lookup{Mark: mark, Category: cat, MassPerMeter: mpm, Source: Source23met, SourceURL: srcURL, Found: true}
		}
	}
	return Lookup{Mark: mark, Category: cat, SourceURL: srcURL}
}
