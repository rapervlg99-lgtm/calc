// Package classify реализует правила отнесения строки спецификации к учитываемым
// или неучитываемым элементам (ТЗ §4). Приоритет — минимизация пропусков: при
// неоднозначности строка считается и помечается на проверку (ТЗ §14).
package classify

import "strings"

// Статусы строки формы ОГЗ (ТЗ §7).
const (
	StatusCalculated  = "Посчитано"
	StatusExcluded    = "Не считается"
	StatusNeedsReview = "Требует проверки"
	StatusNeedsMass   = "Нужен ввод массы"
	// StatusNoData — масса 1 пог. метра не найдена в справочнике (23met.ru недоступен
	// или профиль не распознан). Требует внимания проверяющего: ввести массу вручную
	// (ТЗ §5). Отличается от StatusNeedsMass тем, что строка учитывается и расчёт
	// возможен, не хватает только справочного значения.
	StatusNoData = "Нет данных"
)

// countedKeywords — основы наименований учитываемых элементов (ТЗ §4). Сравнение
// по подстроке в нижнем регистре, чтобы покрыть склонения и формы
// («колонна»/«колонны», «балка перекрытия» и т.п.).
var countedKeywords = []string{
	"колонн",
	"стойк",        // стойки (колонна столбца «Колонны/Стойки»)
	"вертикальн",   // вертикальные связи
	"горизонтальн", // горизонтальные связи
	"связ",         // связи
	"распорк",      // распорки
	"балк",         // балки, балки перекрытия/покрытия, балки лестничных клеток
	"прогон",       // прогоны
	"ригел",        // ригели
	"фахверк",      // фахверки
	"ферм",         // фермы
	"косоур",       // косоуры
	"стен",         // стены лестничных клеток
}

// excludedKeywords — элементы, которые явно НЕ считаются (ТЗ §4).
var excludedKeywords = []string{
	"огражден", // ограждения
}

// Result — итог классификации одной строки.
type Result struct {
	Counted  bool   // содержит учитываемый элемент
	Excluded bool   // содержит неучитываемый элемент
	Mixed    bool   // содержит и то и другое → «Требует проверки»
	Matched  string // первый совпавший учитываемый ключ
}

// Status возвращает рекомендуемый статус строки по результату классификации,
// без учёта наличия массы (это решает расчётный слой).
func (r Result) Status() string {
	switch {
	case r.Mixed:
		return StatusNeedsReview
	case r.Counted:
		return StatusCalculated
	default:
		return StatusExcluded
	}
}

// Classify разбирает наименование элемента. Смешанная строка (есть и
// учитываемые, и неучитываемые элементы) считается и помечается на проверку, а
// не отбрасывается (ТЗ §14).
func Classify(name string) Result {
	n := strings.ToLower(name)
	var res Result
	for _, kw := range countedKeywords {
		if strings.Contains(n, kw) {
			res.Counted = true
			if res.Matched == "" {
				res.Matched = kw
			}
		}
	}
	for _, kw := range excludedKeywords {
		if strings.Contains(n, kw) {
			res.Excluded = true
		}
	}
	res.Mixed = res.Counted && res.Excluded
	return res
}

// ClassifyConstruction классифицирует строку по типу конструкции — заголовку
// столбца «Масса металла по элементам конструкций» из спецификации (например
// «Колонны/Стойки», «Балки», «Связи», «Прогоны»). В отличие от Classify, где тип
// выводится из наименования, здесь он берётся напрямую из столбца, в котором
// стоит масса. Неизвестный (но непустой) тип не отбрасывается: считается и
// помечается на проверку (ТЗ §14, минимизация пропусков). Явно неучитываемый
// тип («Ограждения») исключается.
func ClassifyConstruction(construction string) Result {
	n := strings.ToLower(strings.TrimSpace(construction))
	var res Result
	if n == "" {
		return res
	}
	for _, kw := range excludedKeywords {
		if strings.Contains(n, kw) {
			res.Excluded = true
		}
	}
	for _, kw := range countedKeywords {
		if strings.Contains(n, kw) {
			res.Counted = true
			if res.Matched == "" {
				res.Matched = kw
			}
		}
	}
	switch {
	case res.Counted && res.Excluded:
		// Смешанный столбец — считаем и на проверку.
		res.Mixed = true
	case res.Excluded:
		// Чисто неучитываемый тип — исключаем.
	case res.Counted:
		// Распознанный учитываемый тип — считаем без пометки.
	default:
		// Неизвестный непустой тип: считаем, но помечаем на проверку, чтобы не
		// потерять элемент (ТЗ §14).
		res.Counted = true
		res.Mixed = true
	}
	return res
}
