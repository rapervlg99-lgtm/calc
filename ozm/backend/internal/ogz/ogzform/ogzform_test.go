package ogzform

import (
	"context"
	"testing"

	"ozm/backend/internal/ogz/classify"
	"ozm/backend/internal/ogz/sortament"
)

// fakeResolver: масса есть для марок из found, иначе не найдена.
type fakeResolver struct{ found map[string]float64 }

func (f fakeResolver) Resolve(_ context.Context, _, _, raw, _ string) sortament.Lookup {
	mark := sortament.Normalize(raw)
	if mpm, ok := f.found[mark]; ok {
		return sortament.Lookup{Mark: mark, MassPerMeter: mpm, Source: sortament.Source23met, Found: true}
	}
	return sortament.Lookup{Mark: mark}
}

func TestBuildStatuses(t *testing.T) {
	r := fakeResolver{found: map[string]float64{"35Б2": 38.53}}
	in := []Input{
		{Name: "Колонна К1", Profile: "35Б2", Mass: 770.6, MassUnit: "kg"},   // Посчитано
		{Name: "Ограждение лестницы", Profile: "", Mass: 50},                  // Не считается
		{Name: "Балка Б7", Profile: "40Ш1", Mass: 1000, MassUnit: "kg"},      // Нет данных (нет в кэше)
		{Name: "Балка с ограждением", Profile: "35Б2", Mass: 100},            // Требует проверки (смешанная)
	}
	rows := Build(context.Background(), in, r, "user1")

	if got := rows[0].Status; got != classify.StatusCalculated {
		t.Errorf("row0 status = %q, want Посчитано", got)
	}
	if rows[0].LengthM != 20 {
		t.Errorf("row0 length = %v, want 20", rows[0].LengthM)
	}
	if rows[0].MassSource != sortament.Source23met {
		t.Errorf("row0 source = %q", rows[0].MassSource)
	}
	if rows[1].Status != classify.StatusExcluded {
		t.Errorf("row1 status = %q, want Не считается", rows[1].Status)
	}
	if rows[2].Status != classify.StatusNoData {
		t.Errorf("row2 status = %q, want Нет данных", rows[2].Status)
	}
	if rows[3].Status != classify.StatusNeedsReview {
		t.Errorf("row3 status = %q, want Требует проверки", rows[3].Status)
	}
	if rows[3].LengthM == 0 {
		t.Errorf("row3 (mixed) should still be computed, length=%v", rows[3].LengthM)
	}
}

// TestBuildClassifiesByConstruction: один профиль (26Б1) с массой в столбцах
// «Колонны/Стойки» и «Балки» приходит двумя Input; классификация — по столбцу.
func TestBuildClassifiesByConstruction(t *testing.T) {
	r := fakeResolver{found: map[string]float64{"26Б1": 36.0}}
	in := []Input{
		{Name: "Двутавры стальные", Profile: "26Б1", Construction: "Колонны/Стойки", Mass: 2380, MassUnit: "kg"},
		{Name: "Двутавры стальные", Profile: "26Б1", Construction: "Балки", Mass: 16410, MassUnit: "kg"},
		{Name: "Двутавры стальные", Profile: "26Б1", Construction: "Ограждения", Mass: 500, MassUnit: "kg"},
		{Name: "Двутавры стальные", Profile: "26Б1", Construction: "Нечто новое", Mass: 100, MassUnit: "kg"},
	}
	rows := Build(context.Background(), in, r, "u")
	if rows[0].Status != classify.StatusCalculated || rows[0].Construction != "Колонны/Стойки" {
		t.Errorf("row0 = %+v, want Посчитано/Колонны", rows[0])
	}
	if rows[1].Status != classify.StatusCalculated {
		t.Errorf("row1 (Балки) status = %q, want Посчитано", rows[1].Status)
	}
	if rows[2].Status != classify.StatusExcluded {
		t.Errorf("row2 (Ограждения) status = %q, want Не считается", rows[2].Status)
	}
	// Неизвестный тип конструкции считается, но на проверку (ТЗ §14).
	if rows[3].Status != classify.StatusNeedsReview {
		t.Errorf("row3 (unknown construction) status = %q, want Требует проверки", rows[3].Status)
	}
}

func TestRecompute(t *testing.T) {
	// Специалист ввёл массу 1 м для ранее «Нет данных».
	l, a, st := Recompute("Колонна К1", "", 770.6, 38.53, false)
	if st != classify.StatusCalculated || l != 20 || a != 0 {
		t.Errorf("recompute counted = (%v,%v,%q)", l, a, st)
	}
	// Масса убрана → снова нет данных.
	if _, _, st := Recompute("Колонна К1", "", 100, 0, false); st != classify.StatusNoData {
		t.Errorf("recompute no mass = %q, want Нет данных", st)
	}
	// Не считается остаётся не считается.
	if _, _, st := Recompute("Ограждение", "", 100, 5, false); st != classify.StatusExcluded {
		t.Errorf("recompute excluded = %q", st)
	}
	// Смешанная.
	if _, _, st := Recompute("Балка с ограждением", "", 100, 5, false); st != classify.StatusNeedsReview {
		t.Errorf("recompute mixed = %q", st)
	}
	// Классификация по конструкции при пересчёте.
	if _, _, st := Recompute("Двутавры стальные", "Ограждения", 100, 5, false); st != classify.StatusExcluded {
		t.Errorf("recompute construction excluded = %q", st)
	}
	// Лист считается по площади независимо от классификации наименования: «Сталь
	// листовая горячекатаная» — не «считаемая» конструкция, но площадь обязательна.
	if l, a, st := Recompute("Сталь листовая горячекатаная", "", 785, 78.5, true); st != classify.StatusCalculated || a != 10 || l != 0 {
		t.Errorf("recompute sheet = (%v,%v,%q), want (0,10,Посчитано)", l, a, st)
	}
	// Лист без массы 1 м² → нет данных, а не «Не считается».
	if _, _, st := Recompute("Сталь листовая горячекатаная", "", 785, 0, true); st != classify.StatusNoData {
		t.Errorf("recompute sheet no mass = %q, want Нет данных", st)
	}
}

func TestBuildTonnesAndSheet(t *testing.T) {
	r := fakeResolver{found: map[string]float64{"10": 78.5}}
	in := []Input{
		{Name: "Колонна К2", Profile: "35Б2", Mass: 2, MassUnit: "т"}, // 2т=2000кг, нет массы марки → Нужен ввод
		{Name: "Стены лестничной клетки", Profile: "Лист 10", Mass: 785, MassUnit: "kg", IsSheet: true},
	}
	rows := Build(context.Background(), in, r, "u")
	if rows[0].MassKg != 2000 {
		t.Errorf("tonne normalization: massKg=%v, want 2000", rows[0].MassKg)
	}
	if rows[1].AreaM2 != 10 {
		t.Errorf("sheet area = %v, want 10", rows[1].AreaM2)
	}
	// Номер профиля листа — «Т<толщина>» (как Т10), а не нормализованная марка.
	if rows[1].ProfileMark != "Т10" {
		t.Errorf("sheet mark = %q, want Т10", rows[1].ProfileMark)
	}
}

// TestBuildSheetNotGatedByClassification: лист с реальным наименованием «Сталь
// листовая горячекатаная» (НЕ «считаемая» конструкция) обязан получить массу 1 м²
// по формуле 7.85×толщина и площадь — классификация колонн/связей к листу не
// применяется. Регресс на ordering-баг: проверка IsSheet идёт РАНЬШЕ cl.Counted,
// иначе лист молча отсекается как «Не считается» и теряет площадь.
func TestBuildSheetNotGatedByClassification(t *testing.T) {
	r := fakeResolver{} // лист не ходит в резолвер — масса из формулы
	in := []Input{
		{Name: "Сталь листовая горячекатаная", Profile: "-10", Mass: 785, MassUnit: "kg", IsSheet: true},
	}
	rows := Build(context.Background(), in, r, "u")
	if rows[0].Status != classify.StatusCalculated {
		t.Fatalf("sheet status = %q, want Посчитано (не должен гаситься классификацией)", rows[0].Status)
	}
	if rows[0].MassPerMeter != 78.5 {
		t.Errorf("sheet mass 1 м² = %v, want 78.5 (7.85×10)", rows[0].MassPerMeter)
	}
	if rows[0].AreaM2 != 10 {
		t.Errorf("sheet area = %v, want 10", rows[0].AreaM2)
	}
	if rows[0].MassSource != sortament.SourceFormula {
		t.Errorf("sheet source = %q, want formula", rows[0].MassSource)
	}
	if rows[0].ProfileMark != "Т10" {
		t.Errorf("sheet mark = %q, want Т10", rows[0].ProfileMark)
	}
}

// TestBuildUncertainDowngrades: нечётко распознанная строка («40У»↔«409») должна
// уйти на проверку, даже если масса нашлась (приоритет ТЗ §14 — не терять элемент).
func TestBuildUncertainDowngrades(t *testing.T) {
	r := fakeResolver{found: map[string]float64{"35Б2": 38.53}}
	in := []Input{
		{Name: "Колонна К1", Profile: "35Б2", Mass: 770.6, MassUnit: "kg", Uncertain: true},
		{Name: "Ограждение", Profile: "", Mass: 50, Uncertain: true},
	}
	rows := Build(context.Background(), in, r, "u")
	if rows[0].Status != classify.StatusNeedsReview {
		t.Errorf("uncertain counted status = %q, want Требует проверки", rows[0].Status)
	}
	if rows[0].LengthM == 0 {
		t.Errorf("uncertain row should still be computed, length=%v", rows[0].LengthM)
	}
	if rows[1].Status != classify.StatusNeedsReview {
		t.Errorf("uncertain excluded status = %q, want Требует проверки", rows[1].Status)
	}
}
