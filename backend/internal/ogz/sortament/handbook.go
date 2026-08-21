package sortament

import (
	_ "embed"
	"encoding/json"
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
)

func init() {
	handbookByKey, handbookByMark = loadHandbook(massHandbookJSON)
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
