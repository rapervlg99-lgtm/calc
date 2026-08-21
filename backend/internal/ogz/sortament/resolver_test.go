package sortament

import (
	"context"
	"errors"
	"testing"
)

type fakeStore struct {
	get map[string]float64
	put map[string]float64
}

func (f *fakeStore) Get(_ context.Context, mark, _ string) (float64, string, bool, error) {
	if f.get == nil {
		return 0, "", false, nil
	}
	v, ok := f.get[mark]
	return v, SourceManual, ok, nil
}

func (f *fakeStore) Put(_ context.Context, mark string, mpm float64, _, _ string) error {
	if f.put == nil {
		f.put = map[string]float64{}
	}
	f.put[mark] = mpm
	return nil
}

type fakeProvider struct {
	mpm float64
	err error
}

func (p fakeProvider) MassPerMeter(context.Context, string, string) (float64, error) {
	return p.mpm, p.err
}

func TestResolveFromCache(t *testing.T) {
	// Ключ справочника = "<категория>/<марка>": двутавр → balka/35Б2.
	r := NewResolver(&fakeStore{get: map[string]float64{"balka/35Б2": 38.53}}, fakeProvider{mpm: 99})
	got := r.Resolve(context.Background(), "Двутавр стальной по ГОСТ 26020-83", "", "35Б2", "user1")
	if !got.Found || got.MassPerMeter != 38.53 || got.Source != SourceCache {
		t.Fatalf("cache resolve = %+v", got)
	}
	if got.Category != "balka" {
		t.Errorf("expected category balka, got %q", got.Category)
	}
}

func TestResolveFrom23metAndCaches(t *testing.T) {
	store := &fakeStore{}
	r := NewResolver(store, fakeProvider{mpm: 38.53})
	// Марка вне handbook — идём на 23met.
	got := r.Resolve(context.Background(), "Двутавр стальной", "", "999Б9", "user1")
	if !got.Found || got.MassPerMeter != 38.53 || got.Source != Source23met {
		t.Fatalf("23met resolve = %+v", got)
	}
	if store.put["balka/999Б9"] != 38.53 {
		t.Errorf("expected mark cached under category key, got %+v", store.put)
	}
}

func TestResolveProviderErrorDegrades(t *testing.T) {
	r := NewResolver(&fakeStore{}, fakeProvider{err: errors.New("timeout")})
	// Марка вне handbook/сида: при ошибке 23met — Found=false.
	got := r.Resolve(context.Background(), "Двутавр стальной", "", "999Б9", "user1")
	if got.Found {
		t.Fatalf("expected not found on provider error, got %+v", got)
	}
	if got.Mark != "999Б9" {
		t.Errorf("expected normalized mark preserved, got %q", got.Mark)
	}
}

func TestResolveUnknownCategory(t *testing.T) {
	// Нет серии в марке и нет записи в справочнике → провайдер не вызывается.
	r := NewResolver(&fakeStore{}, fakeProvider{mpm: 10})
	if got := r.Resolve(context.Background(), "Нечто непонятное", "", "ZZZ999", "u"); got.Found {
		t.Fatalf("unknown category should not resolve online, got %+v", got)
	}
}

func TestResolveHandbookByMarkAlone(t *testing.T) {
	// OCR дал только марку «10Б1» / «10 Б1» без слова «двутавр» — категория из серии,
	// масса из инженерного справочника; геометрия потом из roll.json по той же марке.
	r := NewResolver(&fakeStore{}, fakeProvider{err: errors.New("offline")})
	for _, raw := range []string{"10Б1", "10 Б1", "10B1"} {
		got := r.Resolve(context.Background(), "", "", raw, "u")
		if !got.Found || got.Category != CatBalka || got.MassPerMeter != 8.1 {
			t.Fatalf("handbook resolve(%q) = %+v, want balka 8.1", raw, got)
		}
		if got.Mark != "10Б1" {
			t.Errorf("mark(%q) = %q, want 10Б1", raw, got.Mark)
		}
	}
}

func TestResolveEmptyMark(t *testing.T) {
	r := NewResolver(&fakeStore{}, fakeProvider{mpm: 10})
	if got := r.Resolve(context.Background(), "Уголок стальной", "", "С255", "u"); got.Found {
		t.Fatalf("steel grade only should not resolve, got %+v", got)
	}
}

// TestResolveCategoryFromGost: наименование не распозналось, но ГОСТ 8509-93 даёт
// категорию уголка — масса находится онлайн (приоритет ГОСТ как надёжного сигнала).
func TestResolveCategoryFromGost(t *testing.T) {
	store := &fakeStore{}
	r := NewResolver(store, fakeProvider{mpm: 4.81})
	got := r.Resolve(context.Background(), "Углы стальные", "ГОСТ 8509-93", "63Х63Х5", "u")
	if !got.Found || got.Category != CatUgolok {
		t.Fatalf("gost-based category resolve = %+v", got)
	}
}

// TestResolveAngleExpandsEqualLeg: спецификация пишет равнополочный уголок двумя
// числами «63Х5» — карточка 23met трёхчисловая «63Х63Х5». Марка и ключ кэша
// должны быть развёрнуты.
func TestResolveAngleExpandsEqualLeg(t *testing.T) {
	store := &fakeStore{}
	r := NewResolver(store, fakeProvider{mpm: 4.81})
	got := r.Resolve(context.Background(), "Уголок стальной", "", "63Х5", "u")
	if got.Mark != "63Х63Х5" {
		t.Fatalf("equal-leg angle mark = %q, want 63Х63Х5", got.Mark)
	}
	if _, ok := store.put["ygolok/63Х63Х5"]; !ok {
		t.Errorf("expected cache key ygolok/63Х63Х5, got %+v", store.put)
	}
}
