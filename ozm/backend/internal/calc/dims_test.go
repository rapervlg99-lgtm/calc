package calc

import (
	"math"
	"testing"

	"ozm/backend/internal/models"
)

// Размеры, как они лежат в dicts/roll.json для каждой формы.
func TestNormalizeDimsMapsRollKeysToFormulaKeys(t *testing.T) {
	cases := []struct {
		shape string
		in    map[string]float64
		want  map[string]float64
	}{
		{"tube_sq", map[string]float64{"A": 100, "s": 5}, map[string]float64{"h": 100, "b": 100, "s": 5}},
		{"tube_sm", map[string]float64{"d": 355.6, "h": 7}, map[string]float64{"h": 355.6, "s": 7}},
		{"corner_e", map[string]float64{"b": 63, "t": 5, "R": 7, "r": 2.3}, map[string]float64{"h": 63, "b": 63, "s": 5, "t": 5}},
		{"corner_ue", map[string]float64{"B": 140, "b": 90, "t": 8, "R": 12, "r": 4}, map[string]float64{"h": 140, "b": 90, "s": 8}},
		{"profile_sm", map[string]float64{"h": 140, "b": 100, "t": 6}, map[string]float64{"h": 140, "b": 100, "s": 6, "t": 6}},
		{"brands_sm", map[string]float64{"h": 100, "b": 100, "S": 6, "S1": 9, "S2": 12}, map[string]float64{"t": 9, "tr": 12}},
		// двутавр уже в ключах формул — ничего не меняется
		{"I-beam_sm", map[string]float64{"h": 298, "b": 149, "s": 5.5, "t": 8, "R": 13}, map[string]float64{"h": 298, "s": 5.5}},
	}
	for _, c := range cases {
		dims := map[string]float64{}
		for k, v := range c.in {
			dims[k] = v
		}
		normalizeDims(c.shape, dims)
		for k, v := range c.want {
			if math.Abs(dims[k]-v) > 1e-9 {
				t.Errorf("%s: %s = %v, want %v (dims=%v)", c.shape, k, dims[k], v, dims)
			}
		}
	}
}

func TestNormalizeDimsKeepsExplicitValues(t *testing.T) {
	dims := map[string]float64{"A": 100, "s": 5, "h": 120}
	normalizeDims("tube_sq", dims)
	if dims["h"] != 120 || dims["b"] != 100 {
		t.Fatalf("explicit h must win: %v", dims)
	}
}

func TestRollDimsGivePositiveSectionForEveryShape(t *testing.T) {
	sides := models.HeatedSides{Left: true, Top: true, Right: true, Bottom: true}
	cases := map[string]map[string]float64{
		"tube_sq":    {"A": 100, "s": 5},
		"tube_sm":    {"d": 108, "h": 4},
		"corner_e":   {"b": 63, "t": 5, "R": 7, "r": 2.3},
		"corner_ue":  {"B": 140, "b": 90, "t": 8, "R": 12, "r": 4},
		"profile_sm": {"h": 140, "b": 100, "t": 6},
		"brands_sm":  {"h": 100, "b": 100, "S": 6, "S1": 9, "S2": 12},
	}
	for shape, dims := range cases {
		normalizeDims(shape, dims)
		f := sectionArea(shape, dims)
		p := heatedPerimeter(shape, dims, sides)
		if f <= 0 || p <= 0 {
			t.Errorf("%s: F=%.1f P=%.1f must be positive (dims=%v)", shape, f, p, dims)
		}
	}
	// контроль по справочнику: L63x5 — 6,13 см², труба 100х5 — 18,4 см²
	angle := map[string]float64{"b": 63, "t": 5, "R": 7, "r": 2.3}
	normalizeDims("corner_e", angle)
	if f := sectionArea("corner_e", angle); math.Abs(f-600) > 40 {
		t.Errorf("L63x5: F=%.0f, want ~600 (формула с поправкой на радиусы)", f)
	}
	tube := map[string]float64{"A": 100, "s": 5}
	normalizeDims("tube_sq", tube)
	if f := sectionArea("tube_sq", tube); math.Abs(f-1840) > 60 {
		t.Errorf("tube 100x5: F=%.0f, want ~1840", f)
	}
}
