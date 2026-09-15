package sortament

import "testing"

func TestCategoryFromMark(t *testing.T) {
	cases := map[string]string{
		"10Б1":  CatBalka,
		"35Ш2":  CatBalka,
		"20К1":  CatBalka,
		"20П":   CatShveller,
		"16У":   CatShveller,
		"12Э":   CatShveller,
		"50Х5":  "", // уголок/труба — без контекста не угадываем
		"75Х50Х5": "",
		"":      "",
	}
	for mark, want := range cases {
		if got := CategoryFromMark(mark); got != want {
			t.Errorf("CategoryFromMark(%q) = %q, want %q", mark, got, want)
		}
	}
}

func TestResolveCategoryPrefersNameThenMark(t *testing.T) {
	if got := ResolveCategory("Двутавры стальные", "", "20П"); got != CatBalka {
		t.Fatalf("name must beat mark series: got %q", got)
	}
	if got := ResolveCategory("", "", "10Б1"); got != CatBalka {
		t.Fatalf("mark series alone: got %q", got)
	}
	if got := ResolveCategory("", "СТО АСЧМ 20-93", "10Б1"); got != CatBalka {
		t.Fatalf("gost асчм: got %q", got)
	}
}

func TestHandbookMass10B1(t *testing.T) {
	mpm, cat, ok := handbookMass(CatBalka, "10Б1")
	if !ok || cat != CatBalka || mpm != 8.1 {
		t.Fatalf("handbookMass(balka,10Б1) = %v %q %v, want 8.1 balka true", mpm, cat, ok)
	}
	mpm, cat, ok = handbookMass("", "10Б1")
	if !ok || cat != CatBalka || mpm != 8.1 {
		t.Fatalf("handbookMass(,10Б1) = %v %q %v", mpm, cat, ok)
	}
}
