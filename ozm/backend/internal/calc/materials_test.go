package calc_test

import (
	"testing"

	"ozm/backend/internal/models"
)

// Ведомость материалов: состав, порядок и метаданные для отчётов. В легаси-выгрузке
// DC материалы несут базу расчёта, привязку к флагу (штукатурка — декор), толщину
// слоя, порядок в ведомости и точность печати; здесь проверяем, что движок ими
// пользуется, а не зашитыми в код числами.
func TestOzmMaterialsDecorAndMetadata(t *testing.T) {
	engine := newEngine(t)

	ozm := func(decor bool) []models.MaterialLine {
		resp, err := engine.Calculate(models.CalcRequest{
			ObjectName: "Ведомость", Address: "г. Рязань", Consent: true, FrDurability: "1",
			Groups: []models.GroupInput{{
				Quantity: 1,
				Elements: []models.ElementInput{{
					ID: "e1", Shape: "I-beam_sm", RollID: "79", FrType: "1", HtLevel: 60,
					Sides:   models.HeatedSides{Left: true, Top: true, Right: true, Bottom: true},
					LengthM: 3, Quantity: 1, Coat: "1", Method: "1", Decor: decor,
				}},
			}},
		})
		if err != nil {
			t.Fatalf("расчёт ОЗМ: %v", err)
		}
		return resp.Materials
	}

	with := ozm(true)
	byID := map[string]models.MaterialLine{}
	for _, m := range with {
		byID[m.ID] = m
	}
	for _, id := range []string{"OZM", "KCer", "KVer", "KAnk"} {
		if _, ok := byID[id]; !ok {
			t.Fatalf("нет материала %s при включённом декоре: %+v", id, with)
		}
	}
	// Толщина слоя и точность печати приходят из справочника: у анкера — целые,
	// у клея и штукатурки — два знака (DC r="0.##").
	if d := byID["KAnk"].Decimals; d == nil || *d != 0 {
		t.Fatalf("у анкеров точность должна быть целой, получили %v", d)
	}
	if d := byID["KVer"].Decimals; d == nil || *d != 2 {
		t.Fatalf("у штукатурки точность 2 знака, получили %v", d)
	}
	if byID["KAnk"].Unit != "шт" || byID["OZM"].Unit != "м³" {
		t.Fatalf("единицы материалов из справочника: %+v", byID)
	}
	// Расход не ниже минимального q_min, но и не ломается им (3.2 > 1.5).
	if byID["KVer"].Quantity <= 0 {
		t.Fatalf("штукатурка должна считаться по площади облицовки: %+v", byID["KVer"])
	}

	// Без галочки «декоративное покрытие» штукатурки в ведомости нет: в DC
	// <KVer type="fr_decor">, то есть это материал декоративного слоя.
	without := ozm(false)
	for _, m := range without {
		if m.ID == "KVer" {
			t.Fatalf("без декора штукатурка не должна попадать в ведомость: %+v", without)
		}
	}
	if len(without) != len(with)-1 {
		t.Fatalf("без декора ожидали на один материал меньше: %d против %d", len(without), len(with))
	}
}

func TestTaikorMaterialOrderAndLayerThickness(t *testing.T) {
	engine := newEngine(t)

	resp, err := engine.Calculate(models.CalcRequest{
		ObjectName: "Ведомость TAIKOR", Address: "г. Рязань", Consent: true, FrDurability: "1",
		Groups: []models.GroupInput{{
			Quantity: 1,
			Elements: []models.ElementInput{{
				ID: "e1", Shape: "I-beam_sm", RollID: "79", FrType: "1", HtLevel: 60,
				Sides:   models.HeatedSides{Left: true, Top: true, Right: true, Bottom: true},
				LengthM: 3, Quantity: 1, Coat: "2", Method: "0", Primer: true, Enamel: true,
			}},
		}},
	})
	if err != nil {
		t.Fatalf("расчёт TAIKOR: %v", err)
	}
	ids := make([]string, 0, len(resp.Materials))
	for _, m := range resp.Materials {
		ids = append(ids, m.ID)
	}
	// DC sort: грунт 1, состав 2, финиш 3 — порядок ведомости задан справочником.
	want := []string{"T150p", "Taikor_2", "T425t"}
	if len(ids) != len(want) {
		t.Fatalf("ожидали материалы %v, получили %v", want, ids)
	}
	for i := range want {
		if ids[i] != want[i] {
			t.Fatalf("порядок ведомости: ожидали %v, получили %v", want, ids)
		}
	}
	layers := map[string]float64{}
	for _, m := range resp.Materials {
		layers[m.ID] = m.LayerMm
	}
	if layers["T150p"] != 0.1 || layers["T425t"] != 0.06 {
		t.Fatalf("толщины слоёв из справочника: %+v", layers)
	}
}

func TestBetonMaterialsKeepPlasterAndAnchors(t *testing.T) {
	engine := newEngine(t)

	resp, err := engine.Calculate(models.CalcRequest{
		ObjectName: "ОЗБ", Address: "г. Рязань", Consent: true, FrDurability: "1",
		Groups: []models.GroupInput{{
			Quantity: 1,
			Elements: []models.ElementInput{{
				ID: "e1", Shape: "I-beam_sm", RollID: "79", FrType: "1", HtLevel: 60,
				Sides:   models.HeatedSides{Left: true, Top: true, Right: true, Bottom: true},
				LengthM: 3, Quantity: 1, Coat: "1", Method: "1",
			}},
		}},
		Beton: &models.BetonInput{AreaM2: 10, HtLevel: 180},
	})
	if err != nil {
		t.Fatalf("расчёт с ОЗБ: %v", err)
	}
	found := map[string]bool{}
	for _, m := range resp.Materials {
		found[m.ID] = true
		if m.ID == "OZB" && m.Title != "ТЕХНО ОЗБ 80" {
			t.Fatalf("у ОЗБ R180 название ТЕХНО ОЗБ 80, получили %q", m.Title)
		}
	}
	// У бетонной части нет флага декора — штукатурка и анкеры считаются всегда.
	for _, id := range []string{"OZB", "KVer", "KAnk"} {
		if !found[id] {
			t.Fatalf("нет материала %s в ОЗБ: %+v", id, resp.Materials)
		}
	}
}
