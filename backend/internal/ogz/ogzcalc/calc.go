// package ogzcalc реализует расчётные правила ОГЗ (ТЗ §6): погонаж по массе и
// площадь листовой стали. Чистые функции без внешних зависимостей.
package ogzcalc

import (
	"math"
	"strings"
)

// ToKilograms нормализует массу к килограммам. Поддерживаются кг и тонны
// (а также русские псевдонимы). Неизвестная единица трактуется как кг.
func ToKilograms(value float64, unit string) float64 {
	if normalizeUnit(unit) == "t" {
		return value * 1000
	}
	return value
}

func normalizeUnit(u string) string {
	switch strings.ToLower(strings.TrimSpace(u)) {
	case "t", "т", "тн", "тонн", "тонна", "тонны":
		return "t"
	default:
		return "kg"
	}
}

// LinearMeters считает погонаж: Длина = Масса конструкции / Масса 1 пог. метра
// (ТЗ §6). Возвращает 0, если масса 1 м не задана (вызывающий помечает строку
// «Нужен ввод массы»). Результат округляется до 2 знаков.
func LinearMeters(massKg, massPerMeterKg float64) float64 {
	if massPerMeterKg <= 0 {
		return 0
	}
	return Round2(massKg / massPerMeterKg)
}

// SheetArea считает площадь листовой стали: Площадь = Масса / Масса 1 м².
// Листовая сталь выводится отдельным блоком (ТЗ §6).
func SheetArea(massKg, massPerSquareMeterKg float64) float64 {
	if massPerSquareMeterKg <= 0 {
		return 0
	}
	return Round2(massKg / massPerSquareMeterKg)
}

// Round2 округляет до 2 знаков после запятой (ТЗ §6).
func Round2(v float64) float64 {
	return math.Round(v*100) / 100
}
