package calc_test

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"ozm/backend/internal/calc"
	"ozm/backend/internal/config"
	"ozm/backend/internal/models"
)

// Конструкции бывают без огнезащиты: у них только антикоррозионная защита (АКЗ,
// coat "1.5"), и предел огнестойкости им не задают. Такая конструкция обязана
// войти в расчёт со своей площадью окраски, без огнезащитного материала и без
// сообщения об ошибке. Для огнезащитного покрытия без R сообщение остаётся —
// иначе материал молча не посчитается.
func TestAkzElementIsCountedWithoutMaterial(t *testing.T) {
	engine := newEngine(t)

	resp, err := engine.Calculate(models.CalcRequest{
		ObjectName:   "Проверка АКЗ",
		Address:      "г. Рязань",
		Consent:      true,
		FrDurability: "1",
		Groups: []models.GroupInput{{
			Title:    "",
			Quantity: 1,
			Elements: []models.ElementInput{{
				ID: "e1", Title: "Связь по АКЗ", Shape: "I-beam_sm", RollID: "79",
				FrType: "1", HtLevel: 0, // предел не задан — для АКЗ он не нужен
				Sides:   models.HeatedSides{Left: true, Top: true, Right: true, Bottom: true},
				LengthM: 6, Quantity: 2, Coat: "1.5", Method: "0",
			}},
		}},
	})
	if err != nil {
		t.Fatalf("расчёт АКЗ: %v", err)
	}
	if len(resp.Elements) != 1 {
		t.Fatalf("в ответе %d элементов, ожидали 1", len(resp.Elements))
	}
	el := resp.Elements[0]
	if el.Exclusion != "" {
		t.Fatalf("АКЗ не должна попадать в исключения: %q", el.Exclusion)
	}
	if el.AreaM2 <= 0 {
		t.Fatalf("площадь окраски АКЗ не посчитана: %.3f", el.AreaM2)
	}
	if el.Volume != 0 {
		t.Fatalf("огнезащитный объём для АКЗ должен быть нулевым: %.3f", el.Volume)
	}
	for _, m := range resp.Materials {
		if m.SourceElementID == "e1" {
			t.Fatalf("для АКЗ не должно быть материалов, нашли %s (%s)", m.ID, m.Title)
		}
	}
	// Площадь АКЗ видна в строке элемента, но в итог огнезащиты не входит:
	// это считает фронт (totalsOf), здесь проверяем только саму строку.
	if el.LengthM != 6 || el.Quantity != 2 {
		t.Fatalf("длина и количество должны сохраниться: %.1f × %.0f", el.LengthM, el.Quantity)
	}
}

func TestFireproofElementWithoutLimitReportsR(t *testing.T) {
	engine := newEngine(t)

	for _, coat := range []string{"1", "2"} {
		resp, err := engine.Calculate(models.CalcRequest{
			ObjectName: "Проверка R", Address: "г. Рязань", Consent: true, FrDurability: "1",
			Groups: []models.GroupInput{{
				Quantity: 1,
				Elements: []models.ElementInput{{
					ID: "e1", Shape: "I-beam_sm", RollID: "79", FrType: "1", HtLevel: 0,
					Sides:   models.HeatedSides{Left: true, Top: true, Right: true, Bottom: true},
					LengthM: 3, Quantity: 1, Coat: coat, Method: "0",
				}},
			}},
		})
		if err != nil {
			t.Fatalf("coat %s: расчёт: %v", coat, err)
		}
		if len(resp.Elements) != 1 || resp.Elements[0].Exclusion == "" {
			t.Fatalf("coat %s: без R элемент обязан получить понятное сообщение, получили %+v", coat, resp.Elements)
		}
		if !strings.HasPrefix(resp.Elements[0].Exclusion, "не задан предел огнестойкости R") {
			t.Fatalf("coat %s: текст сообщения: %q", coat, resp.Elements[0].Exclusion)
		}
	}
}

func newEngine(t *testing.T) *calc.Engine {
	t.Helper()
	dictsDir := filepath.Join("..", "..", "dicts")
	if _, err := os.Stat(filepath.Join(dictsDir, "t500.json")); err != nil {
		dictsDir = filepath.Join("..", "..", "..", "dicts")
	}
	store, err := config.LoadFromFiles(dictsDir)
	if err != nil {
		t.Fatalf("load dicts: %v", err)
	}
	return calc.New(store)
}
