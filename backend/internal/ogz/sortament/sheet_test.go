package sortament

import (
	"math"
	"testing"
)

func TestSheetMassPerArea(t *testing.T) {
	cases := []struct {
		profile string
		want    float64
		ok      bool
	}{
		{"t4", 31.4, true},   // образец «Ведомость»
		{"t10", 78.5, true},  // образец
		{"t12", 94.2, true},  // образец
		{"16", 125.6, true},  // толщина без префикса
		{"δ8", 62.8, true},   // дельта-обозначение
		{"Лист 20", 157, true},
		{"профнастил", 0, false}, // нет толщины
	}
	for _, c := range cases {
		got, ok := SheetMassPerArea(c.profile)
		if ok != c.ok {
			t.Errorf("%q: ok=%v want %v", c.profile, ok, c.ok)
			continue
		}
		if c.ok && math.Abs(got-c.want) > 1e-6 {
			t.Errorf("%q: got %v want %v", c.profile, got, c.want)
		}
	}
}

func TestSpravkaURL(t *testing.T) {
	if got := SpravkaURL("balka", "40Б1"); got != "https://23met.ru/spravka/balka/40%D0%911" {
		t.Errorf("profile url = %q", got)
	}
	if got := SpravkaURL("", "40Б1"); got != "" {
		t.Errorf("empty category should yield no url, got %q", got)
	}
}
