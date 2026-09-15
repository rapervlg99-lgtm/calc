package ogzcalc

import "testing"

func TestToKilograms(t *testing.T) {
	cases := []struct {
		val  float64
		unit string
		want float64
	}{
		{5, "kg", 5},
		{5, "кг", 5},
		{2, "t", 2000},
		{2, "т", 2000},
		{1.5, "тонн", 1500},
		{10, "", 10},
		{10, "unknown", 10},
	}
	for _, c := range cases {
		if got := ToKilograms(c.val, c.unit); got != c.want {
			t.Errorf("ToKilograms(%v, %q) = %v, want %v", c.val, c.unit, got, c.want)
		}
	}
}

func TestLinearMeters(t *testing.T) {
	// 35Б2 ~ 38.53 кг/м; масса конструкции 770.6 кг → 20 м.
	if got := LinearMeters(770.6, 38.53); got != 20 {
		t.Errorf("LinearMeters = %v, want 20", got)
	}
	// округление до 2 знаков.
	if got := LinearMeters(100, 3); got != 33.33 {
		t.Errorf("LinearMeters round = %v, want 33.33", got)
	}
	// нет массы 1 м → 0 (строка пойдёт в «Нужен ввод массы»).
	if got := LinearMeters(100, 0); got != 0 {
		t.Errorf("LinearMeters zero-mpm = %v, want 0", got)
	}
}

func TestSheetArea(t *testing.T) {
	// лист 10 мм ~ 78.5 кг/м²; масса 785 кг → 10 м².
	if got := SheetArea(785, 78.5); got != 10 {
		t.Errorf("SheetArea = %v, want 10", got)
	}
	if got := SheetArea(100, 0); got != 0 {
		t.Errorf("SheetArea zero = %v, want 0", got)
	}
}

func TestRound2(t *testing.T) {
	if got := Round2(1.005); got != 1.0 && got != 1.01 {
		t.Errorf("Round2(1.005) = %v", got)
	}
	if got := Round2(2.346); got != 2.35 {
		t.Errorf("Round2(2.346) = %v, want 2.35", got)
	}
}
