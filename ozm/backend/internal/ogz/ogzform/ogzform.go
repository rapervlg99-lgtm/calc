// Package ogzform собирает строки формы расчёта ОГЗ из распознанных строк:
// классификация (ТЗ §4) + масса 1 пог. метра (ТЗ §5) + расчёт (ТЗ §6) → статус
// строки (ТЗ §7). Результат отображается специалисту на фронте для верификации
// и апрува; выгрузки в файлы нет.
//
// Масса элемента разнесена по конструкциям (Колонны/Стойки, Балки, Связи…), поэтому
// на вход приходит уже по одной Input на тип конструкции (см. internal/recognition).
// Классификация ведётся по типу конструкции (столбцу), а не по наименованию.
package ogzform

import (
	"context"

	"ozm/backend/internal/ogz/ogzcalc"
	"ozm/backend/internal/ogz/classify"
	"ozm/backend/internal/ogz/sortament"
)

// MassResolver разрешает марку профиля в массу 1 пог. метра. Реализуется
// sortament.Resolver; интерфейс — ради подмены в тестах. Наименование группы нужно
// для вывода категории справочника 23met.ru (двутавр/уголок/швеллер…).
type MassResolver interface {
	Resolve(ctx context.Context, name, gost, rawMark, ownerSub string) sortament.Lookup
}

// Input — распознанная строка спецификации в разрезе одной конструкции
// (из internal/recognition).
type Input struct {
	RecognitionRowID int64
	Name             string  // наименование группы профиля
	Profile          string  // номер/марка профиля
	GostProfile      string  // ГОСТ/сортамент профиля (справочно)
	SteelGrade       string  // марка стали (справочно)
	PPNumber         string  // номер позиции (справочно)
	Construction     string  // тип конструкции (столбец); "" — лист/без разбивки
	Mass             float64 // масса этой конструкции, как распознано
	MassUnit         string  // kg | t | "" (нормализуется к кг)
	IsSheet          bool
	Uncertain        bool // модель не уверена в строке → строку на проверку (ТЗ §14)
}

// Row — строка формы расчёта ОГЗ.
type Row struct {
	RecognitionRowID int64
	Name             string
	ProfileRaw       string
	ProfileMark      string  // нормализованная марка
	GostProfile      string  // ГОСТ/сортамент профиля (справочно)
	SteelGrade       string  // марка стали (справочно)
	PPNumber         string  // номер позиции (справочно)
	Construction     string  // тип конструкции
	MassKg           float64 // масса конструкции, кг
	MassPerMeter     float64 // кг/м (профиль) или кг/м² (лист)
	MassSource       string  // cache | 23met | formula | manual | ""
	SourceURL        string  // ссылка на карточку 23met (столбец «Источник 23met»)
	IsSheet          bool
	LengthM          float64 // погонаж
	AreaM2           float64 // площадь листа
	Classification   string  // совпавший учитываемый ключ ("" — не считается)
	Status           string
}

// Build собирает строки формы по распознанным строкам. Внешний сбой разрешения
// массы не роняет сборку — строка просто получает статус «Нет данных».
func Build(ctx context.Context, in []Input, r MassResolver, ownerSub string) []Row {
	rows := make([]Row, 0, len(in))
	for _, it := range in {
		rows = append(rows, buildRow(ctx, it, r, ownerSub))
	}
	return rows
}

// classifyInput выбирает правило классификации: по типу конструкции (столбцу) для
// профильных строк, по наименованию — для строк без разбивки и листа.
func classifyInput(it Input) classify.Result {
	if !it.IsSheet && it.Construction != "" {
		return classify.ClassifyConstruction(it.Construction)
	}
	return classify.Classify(it.Name)
}

// Recompute пересчитывает погонаж/площадь и статус строки после ручной правки
// (например, специалист ввёл массу 1 пог. метра). Статус выводится из классификации
// (по конструкции/наименованию) и наличия массы. Возвращает (lengthM, areaM2, status).
func Recompute(name, construction string, massKg, massPerMeter float64, isSheet bool) (float64, float64, string) {
	// Лист — отдельный блок формы ОГЗ (площадь, не погонаж). Классификация
	// «считать/не считать» (про типы конструкций) к листу НЕ применяется: проверяем
	// isSheet РАНЬШЕ cl.Counted, иначе лист с наименованием «Сталь листовая
	// горячекатаная» отсекается как «Не считается» и теряет массу 1 м²/площадь —
	// та же ловушка, что в buildRow.
	if isSheet {
		if massPerMeter <= 0 {
			return 0, 0, classify.StatusNoData
		}
		return 0, ogzcalc.SheetArea(massKg, massPerMeter), classify.StatusCalculated
	}
	cl := classifyInput(Input{Name: name, Construction: construction, IsSheet: isSheet})
	if !cl.Counted {
		return 0, 0, classify.StatusExcluded
	}
	if massPerMeter <= 0 {
		// Нет справочной массы 1 пог. метра → внимание проверяющего (ТЗ §5).
		return 0, 0, classify.StatusNoData
	}
	length := ogzcalc.LinearMeters(massKg, massPerMeter)
	if cl.Mixed {
		return length, 0, classify.StatusNeedsReview
	}
	return length, 0, classify.StatusCalculated
}

func buildRow(ctx context.Context, it Input, r MassResolver, ownerSub string) Row {
	massKg := ogzcalc.ToKilograms(it.Mass, it.MassUnit)
	cl := classifyInput(it)
	row := Row{
		RecognitionRowID: it.RecognitionRowID,
		Name:             it.Name,
		ProfileRaw:       it.Profile,
		GostProfile:      it.GostProfile,
		SteelGrade:       it.SteelGrade,
		PPNumber:         it.PPNumber,
		Construction:     it.Construction,
		MassKg:           massKg,
		IsSheet:          it.IsSheet,
		Classification:   cl.Matched,
	}

	// Лист — отдельный блок формы ОГЗ (площадь, не погонаж). Масса 1 м²
	// детерминирована формулой 7.85 × толщина (мм), 23met не нужен. Классификация
	// «считать/не считать» (она про типы конструкций — колонны/связи/ограждения) к
	// листу НЕ применяется: проверяем IsSheet РАНЬШЕ cl.Counted, иначе лист с
	// наименованием «Сталь листовая горячекатаная» отсекается как «Не считается» и
	// молча теряет массу/площадь. Номер профиля листа в форме — «Т<толщина>» (Т6,
	// Т10…), как у двутавра 35Б1.
	if it.IsSheet {
		row.ProfileMark = sortament.SheetMark(it.Profile)
		row.SourceURL = sortament.SheetSpravkaURL
		mpm, ok := sortament.SheetMassPerArea(it.Profile)
		if !ok {
			row.Status = classify.StatusNoData // толщину не распознали → проверка
			return row
		}
		row.MassPerMeter = mpm
		row.MassSource = sortament.SourceFormula
		row.AreaM2 = ogzcalc.SheetArea(massKg, mpm)
		row.Status = applyUncertain(classify.StatusCalculated, it.Uncertain)
		return row
	}

	if !cl.Counted {
		row.Status = applyUncertain(classify.StatusExcluded, it.Uncertain)
		return row
	}

	lk := r.Resolve(ctx, it.Name, it.GostProfile, it.Profile, ownerSub)
	row.ProfileMark = lk.Mark
	row.SourceURL = lk.SourceURL
	if !lk.Found {
		// Нет массы в справочнике → внимание проверяющего, ручной ввод (ТЗ §5, §14).
		row.Status = classify.StatusNoData
		return row
	}

	row.MassPerMeter = lk.MassPerMeter
	row.MassSource = lk.Source
	row.LengthM = ogzcalc.LinearMeters(massKg, lk.MassPerMeter)
	row.Status = applyUncertain(statusFor(cl), it.Uncertain)
	return row
}

// statusFor — статус посчитанной строки: смешанная идёт на проверку (ТЗ §14).
func statusFor(cl classify.Result) string {
	if cl.Mixed {
		return classify.StatusNeedsReview
	}
	return classify.StatusCalculated
}

// applyUncertain понижает «спокойный» статус (Посчитано/Не считается) до «Требует
// проверки», если модель не уверена в распознавании строки (профиль с нечёткой
// цифрой/буквой, напр. «40У»↔«409»). Статусы, уже требующие внимания
// (Нет данных/Нужен ввод массы), не трогаем — они и так подсвечены. Приоритет
// ТЗ §14: лучше лишняя проверка, чем потерянный элемент.
func applyUncertain(status string, uncertain bool) string {
	if !uncertain {
		return status
	}
	switch status {
	case classify.StatusCalculated, classify.StatusExcluded:
		return classify.StatusNeedsReview
	default:
		return status
	}
}
