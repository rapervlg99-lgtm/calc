package pipeline

import (
	"testing"

	"ozm/backend/internal/ogz/ogzform"
	"ozm/backend/internal/ogz/storage"
)

// TestToInputsCarriesRecognitionID проверяет, что связь recognition_row → форма
// сохраняется (RecognitionRowID), а масса/единица/лист переносятся без потерь.
func TestToInputsCarriesRecognitionID(t *testing.T) {
	p := &Processor{}
	saved := []storage.RecognitionRow{
		{ID: 7, Name: "Двутавры", Profile: "30Ш1", Mass: 14.3, MassUnit: "t", IsSheet: false},
		{ID: 8, Name: "Прокат листовой", Profile: "t10", Mass: 290.7, MassUnit: "t", IsSheet: true},
	}
	in := p.toInputs(saved)
	if len(in) != 2 {
		t.Fatalf("want 2 inputs, got %d", len(in))
	}
	if in[0].RecognitionRowID != 7 || in[0].Profile != "30Ш1" || in[0].MassUnit != "t" {
		t.Errorf("input[0] mismatch: %+v", in[0])
	}
	if !in[1].IsSheet || in[1].RecognitionRowID != 8 {
		t.Errorf("input[1] mismatch: %+v", in[1])
	}
}

// TestToOgzRowsMapsFormToStorage проверяет конверсию формы в строки БД: масса в кг,
// единица "kg", nullable recognition_row_id, маршрутизация листа.
func TestToOgzRowsMapsFormToStorage(t *testing.T) {
	p := &Processor{}
	form := []ogzform.Row{
		{RecognitionRowID: 7, Name: "Балки", ProfileRaw: "30Б1", ProfileMark: "30Б1",
			MassKg: 5000, MassPerMeter: 46.8, MassSource: "cache", LengthM: 106.84,
			Classification: "балк", Status: "Посчитано"},
		{RecognitionRowID: 0, Name: "Лист", IsSheet: true, MassKg: 1000, AreaM2: 12.5,
			Status: "Нужен ввод массы"},
	}
	out := p.toOgzRows("job-1", form)
	if len(out) != 2 {
		t.Fatalf("want 2 rows, got %d", len(out))
	}
	r0 := out[0]
	if r0.JobID != "job-1" || r0.Mass != 5000 || r0.MassUnit != "kg" {
		t.Errorf("row0 mass mapping wrong: %+v", r0)
	}
	if !r0.RecognitionRowID.Valid || r0.RecognitionRowID.Int64 != 7 {
		t.Errorf("row0 recognition id not set: %+v", r0.RecognitionRowID)
	}
	if r0.LengthM != 106.84 || r0.MassSource != "cache" {
		t.Errorf("row0 calc fields wrong: %+v", r0)
	}
	r1 := out[1]
	if r1.RecognitionRowID.Valid {
		t.Errorf("row1 recognition id should be NULL when 0: %+v", r1.RecognitionRowID)
	}
	if !r1.IsSheet || r1.AreaM2 != 12.5 {
		t.Errorf("row1 sheet mapping wrong: %+v", r1)
	}
}
