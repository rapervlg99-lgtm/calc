package sortament

import (
	"regexp"
	"strconv"
	"strings"
)

// SourceFormula — масса 1 м² листа вычислена по формуле (плотность стали), а не
// взята с 23met. Совпадает с enum OgzRow.massSource в OpenAPI.
const SourceFormula = "formula"

// SheetSpravkaURL — справочная ссылка на листовой прокат 23met (масса 1 м²).
const SheetSpravkaURL = DefaultBaseURL + "/spravka/list"

// sheetSurfaceDensity — масса 1 м² листового проката на 1 мм толщины, кг.
// Плотность стали 7850 кг/м³ × 1 м² × 0.001 м = 7.85 кг (образец «Ведомость»:
// t4→31.4, t10→78.5). Поэтому масса 1 м² = 7.85 × толщина(мм).
const sheetSurfaceDensity = 7.85

// thicknessRe вытаскивает толщину листа из обозначения: «t10», «т12», «16», «δ8».
var thicknessRe = regexp.MustCompile(`(?:^|[^0-9])([0-9]+(?:[.,][0-9]+)?)`)

// SheetThicknessMm парсит толщину листа (мм) из обозначения профиля. Поддержаны
// «t10»/«т10»/«δ10» и просто «10». ok=false, если толщина не распознана.
func SheetThicknessMm(profile string) (float64, bool) {
	m := thicknessRe.FindStringSubmatch(strings.TrimSpace(profile))
	if m == nil {
		return 0, false
	}
	v, err := strconv.ParseFloat(strings.ReplaceAll(m[1], ",", "."), 64)
	if err != nil || v <= 0 {
		return 0, false
	}
	return v, true
}

// SheetMassPerArea возвращает массу 1 м² листа (кг/м²) по обозначению толщины.
// Детерминированно (формула плотности), 23met не требуется. ok=false — толщина
// не распознана → строке нужен ручной ввод/проверка.
func SheetMassPerArea(profile string) (float64, bool) {
	t, ok := SheetThicknessMm(profile)
	if !ok {
		return 0, false
	}
	return sheetSurfaceDensity * t, true
}

// SheetMark формирует обозначение номера профиля листовой стали в форме ОГЗ:
// «Т<толщина>» (кириллическая Т), как заполняет специалист — Т4, Т6, Т10
// (по аналогии с номером профиля двутавра 35Б1). Если толщина не распознана —
// возвращаем исходное обозначение как есть (уйдёт на ручную проверку).
func SheetMark(profile string) string {
	t, ok := SheetThicknessMm(profile)
	if !ok {
		return strings.TrimSpace(profile)
	}
	return "Т" + strconv.FormatFloat(t, 'f', -1, 64)
}
