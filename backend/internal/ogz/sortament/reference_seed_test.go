package sortament

import (
	"context"
	"errors"
	"testing"
)

// TestSeedMassKnownProfiles: курируемый сид (папка «Скриншоты с массой») отдаёт
// массу 1 пог. метра по нормализованной марке. Уголок покрыт в обеих записях —
// двухчисловой (как в спецификации) и развёрнутой трёхчисловой (как на 23met).
func TestSeedMassKnownProfiles(t *testing.T) {
	cases := map[string]float64{
		"26Б1":    28.0,
		"23Б1":    25.8,
		"30Б1":    32.0,
		"40Б1":    56.6,
		"75Х6":    6.89, // уголок 75×75×6, двухчисловая запись
		"75Х75Х6": 6.89, // тот же уголок, развёрнутая запись
		"50Х5":    3.77,
		"50Х50Х5": 3.77,
	}
	for mark, want := range cases {
		got, ok := seedMass(mark)
		if !ok {
			t.Errorf("seedMass(%q): not found, want %v", mark, want)
			continue
		}
		if got != want {
			t.Errorf("seedMass(%q) = %v, want %v", mark, got, want)
		}
	}
}

// TestSeedMassUnknownMarkMisses: марки вне эталонного комплекта в сиде нет — она
// уйдёт на 23met/ручной ввод (сид не «отравляет» произвольные профили).
func TestSeedMassUnknownMarkMisses(t *testing.T) {
	if _, ok := seedMass("35Б2"); ok {
		t.Errorf("seedMass(35Б2): unexpected hit (mark not in curated seed)")
	}
}

// TestResolveUsesSeedWhenCacheMiss: кэш пуст и 23met падает (429), но эталонный
// двутавр всё равно разрешается из сида → строка станет «Посчитано». Источник —
// cache (сид и есть локальный справочник), значение прогревается в store.
func TestResolveUsesSeedWhenCacheMiss(t *testing.T) {
	store := &fakeStore{}
	r := NewResolver(store, fakeProvider{err: errors.New("429")})
	got := r.Resolve(context.Background(), "Двутавр стальной по ГОСТ Р 57837-2017", "", "26Б1", "u")
	if !got.Found || got.MassPerMeter != 28.0 {
		t.Fatalf("seed resolve = %+v, want found 28.0", got)
	}
	if got.Source != SourceCache {
		t.Errorf("seed source = %q, want %q", got.Source, SourceCache)
	}
	if store.put["balka/26Б1"] != 28.0 {
		t.Errorf("seed not written through to cache: %+v", store.put)
	}
}

// TestResolveSeedAngleExpanded: уголок записан двумя числами (75Х6); сид найден по
// развёрнутой трёхчисловой марке (75Х75Х6) и прогрет под ключом категории.
func TestResolveSeedAngleExpanded(t *testing.T) {
	store := &fakeStore{}
	r := NewResolver(store, fakeProvider{err: errors.New("429")})
	got := r.Resolve(context.Background(), "Уголки стальные равнополочные ГОСТ 8509-93", "", "75Х6", "u")
	if !got.Found || got.MassPerMeter != 6.89 || got.Mark != "75Х75Х6" {
		t.Fatalf("seed angle resolve = %+v, want found 6.89 mark 75Х75Х6", got)
	}
	if store.put["ygolok/75Х75Х6"] != 6.89 {
		t.Errorf("seed angle not cached under category key: %+v", store.put)
	}
}

// TestResolveCacheBeatsSeed: запись справочника (ручная правка специалиста)
// приоритетнее сида — Resolve обязан вернуть её, не подменяя сидом.
func TestResolveCacheBeatsSeed(t *testing.T) {
	store := &fakeStore{get: map[string]float64{"balka/26Б1": 27.5}}
	r := NewResolver(store, fakeProvider{err: errors.New("429")})
	got := r.Resolve(context.Background(), "Двутавр стальной по ГОСТ Р 57837-2017", "", "26Б1", "u")
	if got.MassPerMeter != 27.5 {
		t.Fatalf("cache must beat seed: got %v, want 27.5", got.MassPerMeter)
	}
}
