package calc_test

import (
	"math"
	"testing"

	"ozm/backend/internal/models"
)

// Огнезащиту считают по нагреваемым сторонам, а АКЗ и финишное покрытие — по
// всей поверхности конструкции: в спецификации это две разные площади, и
// материалы делятся между ними (как в легаси-отчёте).
func TestAkzAreaIsFullSurface(t *testing.T) {
	engine := newEngine(t)

	resp, err := engine.Calculate(models.CalcRequest{
		ObjectName: "Площади", Address: "г. Рязань", Consent: true, FrDurability: "1",
		Groups: []models.GroupInput{{
			Quantity: 1,
			Elements: []models.ElementInput{{
				ID: "e1", Shape: "I-beam_sm", RollID: "79", FrType: "1", HtLevel: 60,
				// обогрев только сверху: площадь огнезащиты меньше полной
				Sides:   models.HeatedSides{Top: true},
				LengthM: 10, Quantity: 1, Coat: "2", Method: "0", Primer: true, Enamel: true,
			}},
		}},
	})
	if err != nil {
		t.Fatalf("расчёт: %v", err)
	}
	el := resp.Elements[0]
	if el.AreaM2 >= el.AkzAreaM2 {
		t.Fatalf("площадь АКЗ должна быть больше огнезащиты: %.3f против %.3f", el.AkzAreaM2, el.AreaM2)
	}

	byID := map[string]models.MaterialLine{}
	for _, m := range resp.Materials {
		byID[m.ID] = m
	}
	// грунт и финиш — по площади АКЗ (0.23 и 0.17 кг/м² из справочника)
	for id, rate := range map[string]float64{"T150p": 0.23, "T425t": 0.17} {
		m, ok := byID[id]
		if !ok {
			t.Fatalf("нет материала %s: %+v", id, resp.Materials)
		}
		want := math.Round(el.AkzAreaM2*rate*1000) / 1000
		if math.Abs(m.Quantity-want) > 0.002 {
			t.Fatalf("%s: %.3f кг, ожидали %.3f (S акз=%.3f)", id, m.Quantity, want, el.AkzAreaM2)
		}
	}
	if byID["Taikor_2"].Quantity <= 0 {
		t.Fatalf("нет огнезащитного состава: %+v", resp.Materials)
	}
	t.Logf("S огнезащиты %.3f, S акз %.3f, состав %.3f кг, грунт %.3f кг, финиш %.3f кг",
		el.AreaM2, el.AkzAreaM2, byID["Taikor_2"].Quantity, byID["T150p"].Quantity, byID["T425t"].Quantity)
}

// Конструкция только с АКЗ красится по всей поверхности — это её площадь.
func TestAkzOnlyElementUsesFullArea(t *testing.T) {
	engine := newEngine(t)

	resp, err := engine.Calculate(models.CalcRequest{
		ObjectName: "АКЗ", Address: "г. Рязань", Consent: true, FrDurability: "1",
		Groups: []models.GroupInput{{
			Quantity: 1,
			Elements: []models.ElementInput{{
				ID: "e1", Shape: "I-beam_sm", RollID: "79", FrType: "1", HtLevel: 0,
				Sides:   models.HeatedSides{Top: true},
				LengthM: 10, Quantity: 1, Coat: "1.5", Method: "0",
			}},
		}},
	})
	if err != nil {
		t.Fatalf("расчёт: %v", err)
	}
	el := resp.Elements[0]
	if el.AreaM2 <= 0 || math.Abs(el.AreaM2-el.AkzAreaM2) > 1e-6 {
		t.Fatalf("у АКЗ площадь = площадь окраски: %.3f и %.3f", el.AreaM2, el.AkzAreaM2)
	}
}
