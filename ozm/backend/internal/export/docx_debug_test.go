package export_test

import (
	"os"
	"testing"

	"ozm/backend/internal/calc"
	"ozm/backend/internal/export"
	"ozm/backend/internal/models"
)

// Отладочная выгрузка DOCX по демо-расчёту — чтобы проверять Word-отчёт
// отдельно от API. Запуск:
//
//	OZM_DOCX_OUT=report.docx go test ./internal/export/ -run TestDebugDocx
func TestDebugDocx(t *testing.T) {
	out := os.Getenv("OZM_DOCX_OUT")
	if out == "" {
		t.Skip("нет OZM_DOCX_OUT")
	}
	st := testStore(t)
	engine := calc.New(st)

	taikorEl := element("taikor", "2", 90, true, true, false)
	taikorEl.Sides = models.HeatedSides{Top: true}
	ozmEl := element("ozm", "1", 120, false, false, true)
	ozmEl.Shape = "I-beam_sm"

	resp, err := engine.Calculate(models.CalcRequest{
		ObjectName: "Склад", Address: "Рязань, ул. Дмитрова, 56", Consent: true, FrDurability: "1",
		Groups: []models.GroupInput{{
			Title: "Балки покрытия", Quantity: 1,
			Elements: []models.ElementInput{ozmEl, taikorEl},
		}},
	})
	if err != nil {
		t.Fatalf("расчёт: %v", err)
	}

	data, err := export.New(st).DOCX(resp)
	if err != nil {
		t.Fatalf("docx: %v", err)
	}
	if len(data) < 5000 {
		t.Fatalf("docx подозрительно мал: %d байт", len(data))
	}
	if err := os.WriteFile(out, data, 0o644); err != nil {
		t.Fatalf("запись: %v", err)
	}
	t.Logf("docx: %d байт в %s", len(data), out)
}
