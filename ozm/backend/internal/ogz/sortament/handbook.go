package sortament

import (
	_ "embed"
	"encoding/json"
	"sort"
	"strings"
)

//go:embed mass_handbook.json
var massHandbookJSON []byte

// SourceHandbook — масса из локального «Инженерного справочника масс металла».
// В API отдаём как cache: это тот же локальный справочник (enum OpenAPI без нового значения).
const SourceHandbook = SourceCache

type handbookFile struct {
	Entries []handbookEntry `json:"entries"`
}

type handbookEntry struct {
	Mark         string  `json:"mark"`
	Category     string  `json:"category"`
	MassPerMeter float64 `json:"massPerMeter"`
	Gost         string  `json:"gost"`
	Note         string  `json:"note"`
}

// handbookByKey: "category/mark" → масса. handbookByMark: mark → уникальная запись
// (только если марка встречается в ровно одной категории — иначе неоднозначность).
var (
	handbookByKey  map[string]float64
	handbookByMark map[string]handbookEntry
	handbookAll    []HandbookEntry // все записи «категория/марка» в порядке файла
)

func init() {
	handbookByKey, handbookByMark = loadHandbook(massHandbookJSON)
	handbookAll = collectHandbook(massHandbookJSON)
}

// collectHandbook — плоский список записей для /ext/profiles: одна запись на
// пару «категория/марка» (первая в файле), включая марки, встречающиеся в
// нескольких категориях — их различает поле Category.
func collectHandbook(raw []byte) []HandbookEntry {
	var f handbookFile
	if len(raw) == 0 || json.Unmarshal(raw, &f) != nil {
		return nil
	}
	seen := map[string]struct{}{}
	out := make([]HandbookEntry, 0, len(f.Entries))
	for _, e := range f.Entries {
		mark := strings.TrimSpace(e.Mark)
		cat := strings.TrimSpace(e.Category)
		if mark == "" || e.MassPerMeter <= 0 {
			continue
		}
		key := cat + "/" + mark
		if _, dup := seen[key]; dup {
			continue
		}
		seen[key] = struct{}{}
		out = append(out, HandbookEntry{Mark: mark, Category: cat, MassPerMeter: e.MassPerMeter})
	}
	return out
}

func loadHandbook(raw []byte) (byKey map[string]float64, byMark map[string]handbookEntry) {
	byKey = map[string]float64{}
	byMark = map[string]handbookEntry{}
	if len(raw) == 0 {
		return byKey, byMark
	}
	var f handbookFile
	if err := json.Unmarshal(raw, &f); err != nil {
		return byKey, byMark
	}
	// Сколько категорий на марку — чтобы byMark хранил только однозначные.
	catCount := map[string]map[string]struct{}{}
	for _, e := range f.Entries {
		mark := strings.TrimSpace(e.Mark)
		if mark == "" || e.MassPerMeter <= 0 {
			continue
		}
		cat := strings.TrimSpace(e.Category)
		key := mark
		if cat != "" {
			key = cat + "/" + mark
		}
		if _, ok := byKey[key]; !ok {
			byKey[key] = e.MassPerMeter
		}
		if catCount[mark] == nil {
			catCount[mark] = map[string]struct{}{}
		}
		catCount[mark][cat] = struct{}{}
		// Первая запись на марку — кандидат; ниже отфильтруем неоднозначные.
		if _, ok := byMark[mark]; !ok {
			byMark[mark] = e
		}
	}
	for mark, cats := range catCount {
		if len(cats) != 1 {
			delete(byMark, mark)
		}
	}
	return byKey, byMark
}

// HandbookEntry — запись встроенного справочника масс для внешних потребителей.
type HandbookEntry struct {
	Mark         string
	Category     string
	MassPerMeter float64
}

// HandbookEntries возвращает записи встроенного справочника (категория, марка,
// масса), отсортированные по марке и категории. Используется /ext/profiles:
// фронт считает длину из массы прямо в браузере для строк, импортированных из
// локального OCR, и различает одноимённые марки разных категорий («140Х5» —
// квадратная или круглая труба) по полю category.
func HandbookEntries() []HandbookEntry {
	out := make([]HandbookEntry, len(handbookAll))
	copy(out, handbookAll)
	sort.Slice(out, func(i, j int) bool {
		if out[i].Mark != out[j].Mark {
			return out[i].Mark < out[j].Mark
		}
		return out[i].Category < out[j].Category
	})
	return out
}

// handbookMass ищет массу 1 пог. метра в инженерном справочнике.
// Сначала точный ключ category/mark; если нет (или category пуста) — однозначная
// марка across категорий (например «50Х25Х2» только прямоугольная труба).
// ok=false — нет записи или неоднозначность.
func handbookMass(category, mark string) (mass float64, resolvedCat string, ok bool) {
	if mark == "" {
		return 0, "", false
	}
	if category != "" {
		if mpm, hit := handbookByKey[category+"/"+mark]; hit {
			return mpm, category, true
		}
	}
	if e, hit := handbookByMark[mark]; hit {
		return e.MassPerMeter, e.Category, true
	}
	return 0, category, false
}
