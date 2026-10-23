package export_test

import (
	"bytes"
	"os"
	"strings"
	"testing"

	"github.com/xuri/excelize/v2"

	"ozm/backend/internal/calc"
	"ozm/backend/internal/config"
	"ozm/backend/internal/export"
	"ozm/backend/internal/models"
)

func testStore(t *testing.T) *config.Store {
	t.Helper()
	st, err := config.LoadFromFiles("../../dicts")
	if err != nil {
		t.Fatalf("справочники: %v", err)
	}
	return st
}

func element(id, coat string, ht float64, primer, enamel, decor bool) models.ElementInput {
	return models.ElementInput{
		ID: id, Title: "Элемент " + id, Shape: "I-beam_sm", RollID: "79", FrType: "1", HtLevel: ht,
		Sides:   models.HeatedSides{Left: true, Top: true, Right: true, Bottom: true},
		LengthM: 6, Quantity: 2, Coat: coat, Method: "1",
		Primer: primer, Enamel: enamel, Decor: decor,
	}
}

// Спецификация: лист на систему, блок цен, шапка, формулы и ИТОГО — как в
// легаси-отчёте, по которому её просили повторить.
func TestXlsxReportStructure(t *testing.T) {
	st := testStore(t)
	engine := calc.New(st)

	// балка с обогревом только сверху: площади огнезащиты и АКЗ различаются,
	// как в легаси-отчёте, поэтому видно, что материалы делятся по разным площадям
	taikorEl := element("taikor", "2", 90, true, true, false)
	taikorEl.Sides = models.HeatedSides{Top: true}

	resp, err := engine.Calculate(models.CalcRequest{
		ObjectName: "Склад", Address: "Рязань, ул. Дмитрова, 56", Consent: true, FrDurability: "1",
		Groups: []models.GroupInput{{
			Title: "Группа элементов 1", Quantity: 1,
			Elements: []models.ElementInput{
				element("ozm", "1", 60, false, false, true),
				taikorEl,
				element("akz", "1.5", 0, true, true, false),
			},
		}},
		Beton: &models.BetonInput{AreaM2: 40, HtLevel: 180},
	})
	if err != nil {
		t.Fatalf("расчёт: %v", err)
	}

	data, err := export.New(st).XLSX(resp)
	if err != nil {
		t.Fatalf("спецификация: %v", err)
	}
	// по запросу сохраняем пример отчёта — его удобно открыть в Excel и сравнить
	// с легаси-файлом (OZM_REPORT_OUT=<путь>.xlsx go test ./internal/export/)
	if out := os.Getenv("OZM_REPORT_OUT"); out != "" {
		if err := os.WriteFile(out, data, 0o644); err != nil {
			t.Fatalf("записать пример: %v", err)
		}
	}

	f, err := excelize.OpenReader(bytes.NewReader(data))
	if err != nil {
		t.Fatalf("открыть xlsx: %v", err)
	}
	defer f.Close()

	sheets := f.GetSheetList()
	want := map[string]bool{"ТЕХНО ОЗМ+ОЗБ": false, "Taikor FP Epoxy": false, "АКЗ материалы TAIKOR": false}
	for _, name := range sheets {
		if _, ok := want[name]; ok {
			want[name] = true
		}
	}
	for name, found := range want {
		if !found {
			t.Fatalf("нет листа %q, есть: %v", name, sheets)
		}
	}

	const ozm = "ТЕХНО ОЗМ+ОЗБ"
	// заголовок спецификации и блок цен
	if v, _ := f.GetCellValue(ozm, "B8"); v != "ТЕХНО ОЗМ" {
		t.Fatalf("в блоке цен ожидали «ТЕХНО ОЗМ», получили %q", v)
	}
	title := ""
	for r := 1; r <= 20; r++ {
		for c := 1; c <= 8; c++ {
			name, _ := excelize.ColumnNumberToName(c)
			if v, _ := f.GetCellValue(ozm, name+itoa(r)); strings.Contains(v, "СПЕЦИФИКАЦИЯ материалов") {
				title = v
			}
		}
	}
	if !strings.Contains(title, "СПЕЦИФИКАЦИЯ материалов ТЕХНО ОЗ") || !strings.Contains(title, "Дмитрова") {
		t.Fatalf("заголовок спецификации: %q", title)
	}

	// объединения шапки есть (многоуровневая шапка)
	merges, err := f.GetMergeCells(ozm)
	if err != nil {
		t.Fatalf("merges: %v", err)
	}
	if len(merges) < 6 {
		t.Fatalf("ожидали объединения шапки, получили %d", len(merges))
	}

	// строки: группа, элемент, бетон; ИТОГО с формулами SUM
	rows, err := f.GetRows(ozm)
	if err != nil {
		t.Fatalf("rows: %v", err)
	}
	width := 0
	for _, r := range rows {
		if len(r) > width {
			width = len(r)
		}
	}
	var formulaCells, sumCells int
	for r := 1; r <= len(rows); r++ {
		for c := 1; c <= width; c++ {
			name, _ := excelize.ColumnNumberToName(c)
			if form, _ := f.GetCellFormula(ozm, name+itoa(r)); form != "" {
				formulaCells++
				if strings.HasPrefix(form, "SUM(") {
					sumCells++
				}
			}
		}
	}
	if formulaCells == 0 {
		t.Fatal("в спецификации нет формул")
	}
	if sumCells == 0 {
		t.Fatal("в строке ИТОГО нет формул SUM")
	}

	// TAIKOR-лист: в шапке есть пары «ТСП, мм» / «Расход, кг/м²» и название состава
	const taikor = "Taikor FP Epoxy"
	foundTsp, foundRate, foundFit := false, false, false
	for r := 1; r <= 25; r++ {
		for c := 1; c <= 12; c++ {
			name, _ := excelize.ColumnNumberToName(c)
			v, _ := f.GetCellValue(taikor, name+itoa(r))
			switch v {
			case "ТСП, мм":
				foundTsp = true
			case "Расход, кг/м²":
				foundRate = true
			}
			if strings.Contains(v, "TAIKOR FP Epoxy") || strings.Contains(v, "FP Epoxy") {
				foundFit = true
			}
		}
	}
	if !foundTsp || !foundRate {
		t.Fatalf("в шапке TAIKOR-листа нет пары ТСП/Расход (tsp=%v rate=%v)", foundTsp, foundRate)
	}
	if !foundFit {
		t.Fatal("в шапке TAIKOR-листа нет названия состава")
	}

	// Две площади: огнезащита — по нагреваемым сторонам, АКЗ — по всей
	// поверхности. АКЗ-материалы и финиш считаются по площади АКЗ.
	foundFire, foundAkz := false, false
	for r := 1; r <= 25; r++ {
		for c := 1; c <= 12; c++ {
			name, _ := excelize.ColumnNumberToName(c)
			v, _ := f.GetCellValue(taikor, name+itoa(r))
			if strings.HasPrefix(v, "Площадь покрытия огнезащиты") {
				foundFire = true
			}
			if strings.HasPrefix(v, "Площадь покрытия АКЗ") {
				foundAkz = true
			}
		}
	}
	if !foundFire || !foundAkz {
		t.Fatalf("на листе TAIKOR должны быть две площади (огнезащита=%v акз=%v)", foundFire, foundAkz)
	}
	// формулы: состав огнезащиты считается по площади огнезащиты, грунт и финиш —
	// по площади АКЗ, то есть первая ссылка в ROUND у них разная
	areaLetters := map[string]bool{}
	for r := 1; r <= len(rows)+2; r++ {
		for c := 1; c <= width; c++ {
			name, _ := excelize.ColumnNumberToName(c)
			form, _ := f.GetCellFormula(taikor, name+itoa(r))
			if strings.HasPrefix(form, "ROUND(") && strings.Contains(form, "*") {
				if i := strings.Index(form, "*"); i > 6 {
					areaLetters[form[6:i]] = true
				}
			}
		}
	}
	if len(areaLetters) < 2 {
		t.Fatalf("ожидали формулы с двумя разными площадями, получили %v", areaLetters)
	}

	// шапка листа: картинка с логотипом и QR-кодом
	pics, err := f.GetPictures(ozm, "A1")
	if err != nil {
		t.Fatalf("pictures: %v", err)
	}
	if len(pics) == 0 || len(pics[0].File) == 0 {
		t.Fatal("в спецификации нет картинки шапки")
	}
}

func itoa(v int) string {
	if v == 0 {
		return "0"
	}
	var b []byte
	for v > 0 {
		b = append([]byte{byte('0' + v%10)}, b...)
		v /= 10
	}
	return string(b)
}
