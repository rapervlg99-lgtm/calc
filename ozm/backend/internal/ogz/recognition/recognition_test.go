package recognition

import (
	"context"
	"errors"
	"testing"
)

// realQwenOutput — фактический JSON, полученный от локальной qwen3.5:9b на скане
// спецификации ST-0028 (Бункер сырого угля). Содержит реальную OCR-ошибку: масса
// листа t20 прочитана как 19.0 вместо 1.90 — её должна поймать сверка сумм.
const realQwenOutput = `{"rows":[
{"наименование":"Двутавры стальные горячекатаные с параллельными гранями полок по ГОСТ Р 57837-2017","профиль":"30Ш1","масса_т":14.3,"uncertain":false},
{"наименование":"Двутавры стальные горячекатаные с параллельными гранями полок по ГОСТ Р 57837-2017","профиль":"50Б1","масса_т":59.4,"uncertain":false},
{"наименование":"Двутавры стальные горячекатаные с параллельными гранями полок по ГОСТ Р 57837-2017","профиль":"Всего профиля","масса_т":73.7,"uncertain":false},
{"наименование":"Уголки стальные горячекатаные равнополочные ГОСТ 8509-93","профиль":"L125x10","масса_т":12.8,"uncertain":false},
{"наименование":"Уголки стальные горячекатаные равнополочные ГОСТ 8509-93","профиль":"L180x12","масса_т":39.0,"uncertain":false},
{"наименование":"Уголки стальные горячекатаные равнополочные ГОСТ 8509-93","профиль":"Всего профиля","масса_т":51.8,"uncertain":false},
{"наименование":"Прокат листовой горячекатаный по ГОСТ 19903-2015","профиль":"16","масса_т":2.5,"uncertain":false},
{"наименование":"Прокат листовой горячекатаный по ГОСТ 19903-2015","профиль":"18","масса_т":136.3,"uncertain":false},
{"наименование":"Прокат листовой горячекатаный по ГОСТ 19903-2015","профиль":"t10","масса_т":290.7,"uncertain":false},
{"наименование":"Прокат листовой горячекатаный по ГОСТ 19903-2015","профиль":"t12","масса_т":228.2,"uncertain":false},
{"наименование":"Прокат листовой горячекатаный по ГОСТ 19903-2015","профиль":"t16","масса_т":99.4,"uncertain":false},
{"наименование":"Прокат листовой горячекатаный по ГОСТ 19903-2015","профиль":"t20","масса_т":19.0,"uncertain":false},
{"наименование":"Прокат листовой горячекатаный по ГОСТ 19903-2015","профиль":"t25","масса_т":82.7,"uncertain":false},
{"наименование":"Прокат листовой горячекатаный по ГОСТ 19903-2015","профиль":"t30","масса_т":9.6,"uncertain":false},
{"наименование":"Прокат листовой горячекатаный по ГОСТ 19903-2015","профиль":"Всего профиля","масса_т":851.3,"uncertain":false},
{"наименование":"Всего металла","профиль":"","масса_т":976.8,"uncertain":false},
{"наименование":"Всего стали","профиль":"","масса_т":51.8,"uncertain":false},
{"наименование":"Всего стали","профиль":"","масса_т":925.0,"uncertain":false}
]}`

func TestParseDropsAnchorRows(t *testing.T) {
	rows, err := Parse(realQwenOutput)
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	// 18 строк в ответе минус 5 итогов (3×"Всего профиля"/стали в профиле + 3 grand
	// total в наименовании) → остаются только элементы-данные: 2+2+8 = 12.
	if len(rows) != 12 {
		t.Fatalf("want 12 data rows, got %d", len(rows))
	}
	for _, r := range rows {
		if isAnchorRow(r.Name, r.Profile) {
			t.Fatalf("anchor row leaked into data: %+v", r)
		}
	}
}

// gradeTotalOutput воспроизводит реальную ведомость расхода стали: grand-total
// «Всего стали» с маркой стали в колонке профиля (С345/С355). До фикса такие строки
// протекали в форму, т.к. isGrandTotal требовал пустого профиля.
const gradeTotalOutput = `{"rows":[
{"наименование":"Двутавры стальные горячекатаные по ГОСТ Р 57837-2017","профиль":"35Ш1","масса_т":22.45,"uncertain":false},
{"наименование":"Двутавры стальные горячекатаные по ГОСТ Р 57837-2017","профиль":"30Б1","масса_т":50.2,"uncertain":false},
{"наименование":"Всего стали","профиль":"С345-6","масса_т":0.55,"uncertain":false},
{"наименование":"Всего стали","профиль":"С355-6","масса_т":1286.65,"uncertain":false}
]}`

func TestParseDropsGradeGrandTotals(t *testing.T) {
	rows, err := Parse(gradeTotalOutput)
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if len(rows) != 2 {
		t.Fatalf("want 2 data rows (grade totals dropped), got %d: %+v", len(rows), rows)
	}
	for _, r := range rows {
		if r.Name == "Всего стали" {
			t.Fatalf("grade grand-total leaked into form: %+v", r)
		}
	}
}

// gradeBreakdownOutput воспроизводит разбивку «в том числе по маркам стали»: после
// строки-элемента (26Б1) идут субитоги по маркам — латиница C245 и кириллица С255.
// Они дублируют уже учтённую массу и не являются конструкциями (Item 1: не выводить
// в форму). Проверяем оба алфавита: модель путает латинскую C и кириллическую С.
const gradeBreakdownOutput = `{"rows":[
{"наименование":"Двутавры стальные горячекатаные по ГОСТ Р 57837-2017","профиль":"26Б1","масса_т":18.79,"uncertain":false},
{"наименование":"В том числе по маркам или наименованиям:","профиль":"C245","масса_т":10.0,"uncertain":false},
{"наименование":"В том числе по маркам или наименованиям:","профиль":"С255","масса_т":8.79,"uncertain":false}
]}`

func TestParseDropsGradeBreakdownRows(t *testing.T) {
	rows, err := Parse(gradeBreakdownOutput)
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if len(rows) != 1 {
		t.Fatalf("want 1 data row (grade breakdown dropped), got %d: %+v", len(rows), rows)
	}
	if rows[0].Profile != "26Б1" {
		t.Fatalf("expected real element 26Б1 to survive, got %+v", rows[0])
	}
}

// constructionBreakdown — строка профиля с массой в нескольких столбцах конструкций.
// 26Б1: Колонны/Стойки 2.38 + Балки 16.41 = 18.79 (общая). Должна раскладываться на
// две расчётные строки с общим ГОСТ профиля.
const constructionBreakdown = `{"rows":[
{"наименование":"Двутавры стальные горячекатаные по ГОСТ Р 57837-2017","гост_профиля":"ГОСТ Р 57837-2017","профиль":"26Б1","конструкции":[{"тип":"Колонны/Стойки","масса_т":2.38},{"тип":"Балки","масса_т":16.41}],"общая_масса_т":18.79,"uncertain":false}
]}`

func TestParseSplitsByConstruction(t *testing.T) {
	rows, err := Parse(constructionBreakdown)
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if len(rows) != 2 {
		t.Fatalf("want 2 construction rows, got %d: %+v", len(rows), rows)
	}
	byType := map[string]Row{}
	for _, r := range rows {
		byType[r.Construction] = r
		if r.Profile != "26Б1" || r.GostProfile != "ГОСТ Р 57837-2017" {
			t.Errorf("row lost shared fields: %+v", r)
		}
		if r.TotalMass != 18.79 {
			t.Errorf("row %q: want total 18.79, got %v", r.Construction, r.TotalMass)
		}
		if r.Confidence != ConfidenceHigh {
			t.Errorf("row %q: want high confidence (sum matches), got %v", r.Construction, r.Confidence)
		}
	}
	if byType["Колонны/Стойки"].Mass != 2.38 {
		t.Errorf("Колонны/Стойки mass: want 2.38, got %v", byType["Колонны/Стойки"].Mass)
	}
	if byType["Балки"].Mass != 16.41 {
		t.Errorf("Балки mass: want 16.41, got %v", byType["Балки"].Mass)
	}
}

// constructionMismatch — сумма конструкций (2.38+16.41=18.79) ≠ общая (187.9): OCR
// добавил ноль в общую массу. Сверка должна понизить confidence обеих строк.
const constructionMismatch = `{"rows":[
{"наименование":"Двутавры по ГОСТ Р 57837-2017","профиль":"26Б1","конструкции":[{"тип":"Колонны/Стойки","масса_т":2.38},{"тип":"Балки","масса_т":16.41}],"общая_масса_т":187.9,"uncertain":false}
]}`

func TestParseFlagsConstructionSumMismatch(t *testing.T) {
	rows, err := Parse(constructionMismatch)
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	for _, r := range rows {
		if r.Confidence != ConfidenceLow {
			t.Errorf("row %q expected low confidence on sum mismatch, got %v", r.Construction, r.Confidence)
		}
	}
}

func TestParseFlagsSheetGroupOnSumMismatch(t *testing.T) {
	rows, err := Parse(realQwenOutput)
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	// Лист: сумма строк 868.4 ≠ якорь 851.3 (из-за 19.0 вместо 1.9) → вся группа low.
	// Двутавры/уголки сходятся → high.
	for _, r := range rows {
		if r.IsSheet {
			if r.Confidence != ConfidenceLow {
				t.Errorf("sheet row %q expected low confidence, got %v", r.Profile, r.Confidence)
			}
		} else {
			if r.Confidence != ConfidenceHigh {
				t.Errorf("profile row %q expected high confidence, got %v", r.Profile, r.Confidence)
			}
		}
	}
}

func TestParseDetectsSheet(t *testing.T) {
	rows, err := Parse(realQwenOutput)
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	sheet := 0
	for _, r := range rows {
		if r.IsSheet {
			sheet++
		}
		if r.MassUnit != "t" {
			t.Errorf("row %q: expected unit t, got %q", r.Profile, r.MassUnit)
		}
	}
	if sheet != 8 {
		t.Fatalf("want 8 sheet rows (t6..t30), got %d", sheet)
	}
}

func TestParseCleanGroupStaysHighConfidence(t *testing.T) {
	// Если массы листа корректны, сумма сходится (851.3) → группа high.
	clean := `{"rows":[
	{"наименование":"Прокат листовой по ГОСТ 19903-2015","профиль":"t6","масса_т":2.5},
	{"наименование":"Прокат листовой по ГОСТ 19903-2015","профиль":"t8","масса_т":136.3},
	{"наименование":"Прокат листовой по ГОСТ 19903-2015","профиль":"Всего профиля","масса_т":138.8}
	]}`
	rows, err := Parse(clean)
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if len(rows) != 2 {
		t.Fatalf("want 2 data rows, got %d", len(rows))
	}
	for _, r := range rows {
		if r.Confidence != ConfidenceHigh {
			t.Errorf("row %q expected high confidence, got %v", r.Profile, r.Confidence)
		}
	}
}

func TestParseHandlesMarkdownWrappedJSON(t *testing.T) {
	wrapped := "```json\n{\"rows\":[{\"наименование\":\"Балки\",\"профиль\":\"30Б1\",\"масса_т\":5.0}]}\n```"
	rows, err := Parse(wrapped)
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if len(rows) != 1 || rows[0].Profile != "30Б1" {
		t.Fatalf("unexpected rows: %+v", rows)
	}
}

// stubModel реализует VisionModel для проверки RecognizePage без сети.
type stubModel struct {
	out string
	err error
}

func (s stubModel) Vision(_ context.Context, _ string, _ []byte) (string, error) {
	return s.out, s.err
}

func TestRecognizePageSetsPageAndPropagatesError(t *testing.T) {
	r := New(stubModel{out: `{"rows":[{"наименование":"Балки","профиль":"30Б1","масса_т":5.0}]}`})
	rows, err := r.RecognizePage(context.Background(), 3, []byte("img"))
	if err != nil {
		t.Fatalf("RecognizePage: %v", err)
	}
	if len(rows) != 1 || rows[0].Page != 3 {
		t.Fatalf("expected 1 row on page 3, got %+v", rows)
	}

	rErr := New(stubModel{err: errors.New("boom")})
	if _, err := rErr.RecognizePage(context.Background(), 1, nil); err == nil {
		t.Fatal("expected error from vision call")
	}
}

func TestParseSalvagesTruncatedJSON(t *testing.T) {
	// Обрезанный ответ: два полных объекта + недописанный третий.
	raw := `{"rows":[{"наименование":"Двутавры","профиль":"30Б1","масса_т":5.0,"uncertain":false},{"наименование":"Двутавры","профиль":"35Б1","масса_т":7.2,"uncertain":false},{"наименование":"Уголки","профиль":"L`
	rows, err := Parse(raw)
	if err != nil {
		t.Fatalf("Parse salvaged: %v", err)
	}
	if len(rows) != 2 {
		t.Fatalf("want 2 salvaged rows, got %d: %+v", len(rows), rows)
	}
	if rows[0].Profile != "30Б1" || rows[1].Profile != "35Б1" {
		t.Fatalf("unexpected profiles: %+v", rows)
	}
}

