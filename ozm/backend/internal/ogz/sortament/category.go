package sortament

import (
	"regexp"
	"strings"
)

// Категории справочника 23met.ru (/spravka/<slug>/<профиль>). Слаги взяты с
// индекса https://23met.ru/spravka. Масса 1 пог. метра профиля зависит от типа
// проката, поэтому категорию определяем по наименованию группы из колонки 1
// спецификации («Двутавры стальные…», «Уголки…», «Швеллеры…»).
const (
	CatBalka          = "balka"               // двутавр (Б, Ш, К, М, Д)
	CatUgolok         = "ygolok"              // уголок горячекатаный
	CatUgolokGnut     = "ygolok_gnyt"         // уголок гнутый
	CatShveller       = "shveller"            // швеллер горячекатаный
	CatShvellerGnut   = "shveller_gnyt"       // швеллер гнутый
	CatTrubaKvadr     = "tryba_es_kvadr"      // труба/профиль гнутый замкнутый квадратный
	CatTrubaPr        = "tryba_es_pr"         // труба/профиль прямоугольный
	CatTrubaPloskoval = "tryba_es_ploskooval" // труба плоскоовальная
	CatTrubaVGP       = "tryba_vgp"           // труба ВГП
	CatArmatura       = "armatura_a3"         // арматура А3
	CatShestigrannik  = "shestigrannik"       // шестигранник
)

// catRule — правило сопоставления: если наименование содержит хотя бы одно из
// any-слов (и при наличии — все из all-слов), категория совпала. Порядок важен:
// более специфичные правила (гнутый) проверяются раньше общих.
type catRule struct {
	slug string
	all  []string // все подстроки должны встретиться
	any  []string // хотя бы одна
}

var catRules = []catRule{
	// Гнутые — раньше горячекатаных, иначе «швеллер гнутый» поймает общий «швеллер».
	{CatShvellerGnut, []string{"швеллер", "гнут"}, nil},
	{CatUgolokGnut, []string{"уголок", "гнут"}, nil},
	{CatUgolokGnut, []string{"уголки", "гнут"}, nil},
	// Профили гнутые замкнутые сварные: квадрат / прямоугольник.
	{CatTrubaKvadr, []string{"квадрат"}, []string{"гнут", "замкн", "профил", "труб"}},
	{CatTrubaPr, []string{"прямоуголь"}, []string{"гнут", "замкн", "профил", "труб"}},
	{CatTrubaPloskoval, []string{"плоскоовал"}, nil},
	{CatTrubaVGP, []string{"водогазопровод"}, nil},
	{CatTrubaVGP, []string{"вгп"}, nil},
	// Двутавр / балка.
	{CatBalka, nil, []string{"двутавр", "балк"}},
	// Швеллер / уголок горячекатаные.
	{CatShveller, nil, []string{"швеллер"}},
	{CatUgolok, nil, []string{"уголок", "уголки"}},
	{CatArmatura, nil, []string{"арматур"}},
	{CatShestigrannik, nil, []string{"шестигран"}},
}

// gostRule сопоставляет номер ГОСТ сортамента с категорией 23met. ГОСТ печатается
// в каждой строке спецификации и потому надёжнее наименования: модель может
// исказить слово («Уголки»→«Углы»), но номер сортамента распознаётся стабильно.
// Сравнение по подстроке номера, без года ревизии (8509-93 → "8509").
type gostRule struct {
	slug string
	code string // характерная часть номера ГОСТ
}

var gostRules = []gostRule{
	{CatBalka, "57837"},      // двутавры стальные горячекатаные
	{CatBalka, "26020"},      // двутавры с параллельными гранями полок
	{CatBalka, "8239"},       // двутавры (старый сортамент)
	{CatBalka, "асчм"},       // СТО АСЧМ 20-93 (балки)
	{CatUgolok, "8509"},      // уголки равнополочные
	{CatUgolok, "8510"},      // уголки неравнополочные
	{CatUgolokGnut, "19771"}, // уголки гнутые равнополочные
	{CatUgolokGnut, "19772"}, // уголки гнутые неравнополочные
	{CatShveller, "8240"},    // швеллеры горячекатаные
	{CatShveller, "5267"},    // швеллеры специальные
	{CatTrubaKvadr, "30245"}, // профили гнутые замкнутые сварные (квадрат/прямоуг.)
	{CatTrubaVGP, "3262"},    // трубы стальные водогазопроводные
}

// markCatRe — однозначные серии по букве марки (без наименования/ГОСТ).
// «10Б1»/«30Ш1»/«20К1» → двутавр; «20П»/«16У» → швеллер.
var (
	beamSeriesRe    = regexp.MustCompile(`^[0-9]+(?:\.[0-9]+)?[БШКМД]\d*$`)
	channelSeriesRe = regexp.MustCompile(`^[0-9]+(?:\.[0-9]+)?[ПУЭ]$`)
)

// Category определяет slug категории 23met по наименованию группы профиля и (как
// более надёжный фолбэк) по номеру ГОСТ сортамента. Пустая строка — категория не
// распознана (профиль уйдёт на ручной ввод массы). Листовой прокат сюда не
// попадает: у него отдельный блок.
func Category(name, gost string) string {
	n := strings.ToLower(name)
	for _, r := range catRules {
		if matchAll(n, r.all) && matchAny(n, r.any) {
			return r.slug
		}
	}
	return CategoryFromGost(gost)
}

// ResolveCategory — категория по имени/ГОСТ, затем по букве серии марки
// («10Б1» → balka даже без слова «двутавр» в наименовании).
func ResolveCategory(name, gost, mark string) string {
	if cat := Category(name, gost); cat != "" {
		return cat
	}
	return CategoryFromMark(mark)
}

// CategoryFromMark выводит категорию из нормализованной марки по букве серии.
// Работает только для однозначных серий (Б/Ш/К/М/Д, П/У/Э); размерные марки
// (уголок/труба «50Х5») без контекста не угадываем.
func CategoryFromMark(mark string) string {
	if mark == "" {
		return ""
	}
	if beamSeriesRe.MatchString(mark) {
		return CatBalka
	}
	if channelSeriesRe.MatchString(mark) {
		return CatShveller
	}
	return ""
}

// CategoryFromGost выводит категорию по номеру ГОСТ сортамента (фолбэк, когда
// наименование группы не распозналось). Пустая строка — номер не сопоставлен.
func CategoryFromGost(gost string) string {
	g := strings.ToLower(gost)
	for _, r := range gostRules {
		if strings.Contains(g, r.code) {
			return r.slug
		}
	}
	return ""
}

func matchAll(n string, subs []string) bool {
	for _, s := range subs {
		if !strings.Contains(n, s) {
			return false
		}
	}
	return true
}

func matchAny(n string, subs []string) bool {
	if len(subs) == 0 {
		return true
	}
	for _, s := range subs {
		if strings.Contains(n, s) {
			return true
		}
	}
	return false
}
