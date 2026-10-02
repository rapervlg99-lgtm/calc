package calc

import (
	"math"
	"ozm/backend/internal/config"
	"ozm/backend/internal/models"
	"testing"
)

func TestCalclabCatalogGeometryAndAreas(t *testing.T) {
	store, err := config.LoadFromFiles("../../dicts")
	if err != nil {
		t.Fatal(err)
	}
	engine := New(store)
	sides := models.HeatedSides{Left: true, Top: true, Right: true, Bottom: true}
	count := 0
	seen := map[string]bool{}
	standards := map[string]int{}
	for _, row := range store.Roll {
		if row.Source != "calclab-metalloprokat" {
			continue
		}
		count++
		if seen[row.ID] {
			t.Fatalf("duplicate imported id: %s", row.ID)
		}
		seen[row.ID] = true
		standards[row.Standard]++
		el := models.ElementInput{Shape: row.Shape, RollID: row.ID}
		dims := engine.resolveDims(el)
		area, ok := engine.catalogArea(el, dims)
		perimeter := heatedPerimeter(row.Shape, dims, sides)
		if !ok || area != row.AreaMM2 || perimeter <= 0 || math.IsNaN(perimeter) || math.IsInf(perimeter, 0) {
			t.Errorf("invalid geometry: %s (%s) A=%v P=%v", row.ID, row.Label, area, perimeter)
		}
		dims["h"] += 1
		if _, ok := engine.catalogArea(el, dims); ok {
			t.Errorf("manual override kept tabulated area: %s", row.ID)
		}
	}
	if count != 3555 || standards["ГОСТ 35087-2024"] != 350 || standards["ГОСТ 8281-80"] != 116 || standards["ГОСТ 33228-2015"] != 1442 {
		t.Fatalf("incomplete catalog: count=%d standards=%v", count, standards)
	}
}

func TestUnequalBentChannelPerimeterUsesBothFlanges(t *testing.T) {
	dims := map[string]float64{"h": 32, "b": 22, "b1": 12, "s": 3, "t": 3, "R": 0}
	sides := models.HeatedSides{Left: true, Top: true, Right: true, Bottom: true}
	want := 2*32.0 + 2*(22.0+12.0) - 2*3.0 + (math.Pi-4)*3
	if got := heatedPerimeter("channel_unequal", dims, sides); math.Abs(got-want) > 1e-9 {
		t.Fatalf("P=%v want %v", got, want)
	}
	if a := sectionArea("channel_unequal", dims); math.Abs(a-(3*(32+22+12-6)-(4-math.Pi)*9)) > 1e-9 {
		t.Fatalf("A=%v", a)
	}
	dims["b1"] = 22
	if p := heatedPerimeter("channel_unequal", dims, sides); p <= want {
		t.Fatal("smaller flange was ignored")
	}
}
