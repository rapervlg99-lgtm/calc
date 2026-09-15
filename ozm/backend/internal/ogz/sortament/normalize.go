// Package sortament нормализует марку профиля и достаёт массу 1 пог. метра
// (ТЗ §5). Источник массы — 23met.ru с кэшем в локальном справочнике
// (profile_reference). Нет данных → строка получает статус «Нужен ввод массы».
package sortament

import (
	"regexp"
	"strings"
)

// dropWords — описательные слова, которые не входят в марку профиля.
var dropWords = map[string]bool{
	"ДВУТАВР": true, "БАЛКА": true, "ШВЕЛЛЕР": true, "УГОЛОК": true,
	"ТРУБА": true, "ЛИСТ": true, "КОЛОННА": true, "ПРОФИЛЬ": true,
	"ПРОКАТ": true, "СТАЛЬ": true, "КВАДРАТ": true, "КРУГ": true,
	"ПОЛОСА": true, "ГНУТОСВАРНОЙ": true,
}

// stdPrefixes — начало ссылки на стандарт; всё начиная с такого токена отбрасываем.
var stdPrefixes = []string{"ГОСТ", "ОСТ", "ТУ", "СТО", "DIN", "EN", "ЕН"}

// gradeRe — марки стали (С235…С440, Ст3пс, 09Г2С), не относящиеся к профилю.
var gradeRe = regexp.MustCompile(`^(С\d{3}|СТ\d\S*|\d{2}Г\dС)$`)

// sepReplacer приводит разделители размеров (x, ×, *) к кириллической «х».
var sepReplacer = strings.NewReplacer("×", "х", "*", "х", "x", "х", "X", "х")

// seriesLetterRe — марка с буквенной серией: «10Б1», «20П», «30Ш2».
// OCR / PDF часто подставляют латинские lookalike (B/K/P…) — канонизируем в кириллицу.
var seriesLetterRe = regexp.MustCompile(`^([0-9]+(?:[.,][0-9]+)?)([A-ZА-ЯЁ]+)([0-9]*)$`)

// seriesLatinToCyr приводит латинские lookalike букв серии к кириллице справочника.
var seriesLatinToCyr = strings.NewReplacer(
	"B", "Б", // балка
	"K", "К", // колонна
	"M", "М", // двутавр М
	"D", "Д", // двутавр Д
	"H", "Ш", // wide-flange (редко)
	"W", "Ш",
	"P", "П", // швеллер параллельный
	"Y", "У", // швеллер с уклоном
	"U", "У",
)

// Normalize приводит сырую марку профиля к канонической форме для поиска на
// 23met.ru и ключа кэша: верхний регистр, единый разделитель размеров «Х»,
// без ссылок на ГОСТ/ТУ, без марок стали и описательных слов.
//
//	"Двутавр 35Б2 ГОСТ 26020-83" → "35Б2"
//	"10 Б1" / "10B1"             → "10Б1"
//	"Уголок 75x75x6"            → "75Х75Х6"
//	"С255"                       → ""  (только марка стали)
func Normalize(raw string) string {
	s := sepReplacer.Replace(strings.TrimSpace(raw))
	if s == "" {
		return ""
	}
	s = strings.ToUpper(s)
	var out []string
	for _, f := range strings.Fields(s) {
		if isStdRef(f) {
			break // ссылка на стандарт — всё дальше не относится к марке
		}
		if dropWords[f] || gradeRe.MatchString(f) {
			continue
		}
		out = append(out, f)
	}
	return canonicalizeSeriesLetters(strings.Join(out, ""))
}

// canonicalizeSeriesLetters: «10B1»→«10Б1», «20P»→«20П». Размерные марки с «Х»
// (уголок/труба) не трогаем — там нет буквенной серии.
func canonicalizeSeriesLetters(mark string) string {
	m := seriesLetterRe.FindStringSubmatch(mark)
	if m == nil {
		return mark
	}
	return m[1] + seriesLatinToCyr.Replace(m[2]) + m[3]
}

func isStdRef(token string) bool {
	for _, p := range stdPrefixes {
		if strings.HasPrefix(token, p) {
			return true
		}
	}
	return false
}

// angle2NumRe ловит равнополочный уголок из двух чисел: «63Х5» (полка×толщина).
var angle2NumRe = regexp.MustCompile(`^([0-9]+)Х([0-9]+(?:[.,][0-9]+)?)$`)

// ExpandAngleMark разворачивает марку равнополочного уголка из двухчисловой записи
// спецификации («63Х5» = полка 63, толщина 5) в трёхчисловую карточку 23met
// («63Х63Х5»: полка×полка×толщина). Неравнополочный («75Х50Х5») и уже
// трёхчисловой формат не трогаем. Применять только для категорий уголка.
func ExpandAngleMark(mark string) string {
	m := angle2NumRe.FindStringSubmatch(mark)
	if m == nil {
		return mark
	}
	return m[1] + "Х" + m[1] + "Х" + m[2]
}
