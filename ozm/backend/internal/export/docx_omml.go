package export

import (
	"strconv"
	"strings"
)

// OMML — Office Math Markup Language: наборные формулы Word. Собираем их сами
// (как и весь пакет DOCX): дроби, степени, индексы, корни и скобки — те же
// формулы, что в PDF набраны засечным шрифтом с дробной чертой.

// mi — переменная курсивом.
func mi(s string) string { return ommlRun(s, true) }

// mt — обычный текст: числа, знаки, символы (□←, Σ, π).
func mt(s string) string { return ommlRun(s, false) }

// ommlSize — кегль формул в полупунктах: в таблицах мельче, в тексте крупнее.
var ommlSize = 20

func ommlRun(s string, italic bool) string {
	style := "p"
	if italic {
		style = "i"
	}
	return `<m:r><m:rPr><m:sty m:val="` + style + `"/></m:rPr>` +
		`<w:rPr><w:sz w:val="` + strconv.Itoa(ommlSize) + `"/><w:szCs w:val="` + strconv.Itoa(ommlSize) + `"/></w:rPr>` +
		`<m:t xml:space="preserve">` + xmlEscape(s) + `</m:t></m:r>`
}

// msub — индекс: основание и подстрочный текст.
func msub(base, sub string) string {
	return `<m:sSub><m:e>` + base + `</m:e><m:sub>` + sub + `</m:sub></m:sSub>`
}

// msup — степень.
func msup(base, sup string) string {
	return `<m:sSup><m:e>` + base + `</m:e><m:sup>` + sup + `</m:sup></m:sSup>`
}

// mfrac — дробь.
func mfrac(num, den string) string {
	return `<m:f><m:num>` + num + `</m:num><m:den>` + den + `</m:den></m:f>`
}

// mrad — корень (без показателя степени).
func mrad(body string) string {
	return `<m:rad><m:radPr><m:degHide m:val="1"/></m:radPr><m:deg/>` +
		`<m:e>` + body + `</m:e></m:rad>`
}

// mdelim — выражение в скобках.
func mdelim(body string) string {
	return `<m:d><m:dPr/><m:e>` + body + `</m:e></m:d>`
}

// mathPara — абзац с наборной формулой по центру.
func mathPara(align, omml string) string {
	if omml == "" {
		return ""
	}
	return `<w:p><w:pPr><w:jc w:val="` + align + `"/></w:pPr>` +
		`<m:oMathPara><m:oMath>` + omml + `</m:oMath></m:oMathPara></w:p>`
}

// Math добавляет формулу отдельным абзацем.
func (d *docxDoc) Math(omml string) {
	d.body.WriteString(mathPara("center", omml))
}

// formulaDeltaPr — δпр = F / Π.
func formulaDeltaPr() string {
	return msub(mi("δ"), mt("пр")) + mt(" = ") + mfrac(mi("F"), mi("Π"))
}

// ommlV — V = δ · S.
func ommlV() string { return mi("V") + mt(" = ") + mi("δ") + mt(" · ") + mi("S") }

// ommlM — M = q · S.
func ommlM() string { return mi("M") + mt(" = ") + mi("q") + mt(" · ") + mi("S") }

// ommlS — S = (Π / 1000) · L.
func ommlS() string {
	return mi("S") + mt(" = ") + mdelim(mfrac(mi("Π"), mt("1000"))) + mt(" · ") + mi("L")
}

// ommlP — P = (□← + □→)h + (□↓ + □←)b.
func ommlP() string {
	return mi("P") + mt(" = ") +
		mdelim(mt("□←")+mt(" + ")+mt("□→")) + mi("h") + mt(" + ") +
		mdelim(mt("□↓")+mt(" + ")+mt("□←")) + mi("b")
}

// ommlSigma — Σ = ИЛИ(□↓,□←) + ИЛИ(□←,□↑) + ИЛИ(□↑,□→) + ИЛИ(□→,□↓).
func ommlSigma() string {
	and := func(a, b string) string {
		return mt("ИЛИ") + mdelim(mt(a)+mt(",")+mt(b))
	}
	return mi("Σ") + mt(" = ") + and("□↓", "□←") + mt(" + ") + and("□←", "□↑") +
		mt(" + ") + and("□↑", "□→") + mt(" + ") + and("□→", "□↓")
}

// Таблица 2: формулы площади F и периметра Π для четырёх типов сечения.

// table2Omml — формулы таблицы 2 по индексу строки: F одной строкой, Π —
// одной-двумя, как в PDF. В таблице знаки ставим без пробелов: колонка узкая,
// иначе формула не влезает (в PDF её ужимает наборный движок).
func table2Omml(row int) ([]string, []string) {
	par := func(s string) string { return mdelim(s) }
	switch row {
	case 0:
		f := mi("h") + mi("s") + mt("+2") + mi("t") + par(mi("b")+mt("−")+mi("s"))
		root := msup(mfrac(mi("b")+mt("−")+mi("s"), mt("2")), mt("2")) + mt("+4") + msup(mi("t"), mt("2"))
		p1 := par(mt("←")+mt("+")+mt("→")) +
			par(mi("h")+mt("−4")+mi("t")+mt("+2")+mrad(root))
		p2 := mt("+") + par(mt("↓")+mt("+")+mt("←")) + mi("b")
		return []string{f}, []string{p1, p2}
	case 1:
		f := mi("h") + mi("s") + mt("+2") + mi("t") + par(mi("b")+mt("−")+mi("s")) +
			mt("+(4−π)") + msup(mi("R"), mt("2"))
		p1 := par(mt("←")+mt("+")+mt("→")) +
			par(mi("h")+mt("+")+mi("b")+mt("−")+mi("s")+mt("−(4−π)")+mi("R"))
		p2 := mt("+") + par(mt("↓")+mt("+")+mt("←")) + mi("b")
		return []string{f}, []string{p1, p2}
	case 2:
		f := mt("4") + mi("s") + par(mi("h")+mt("−1,43")+mi("s"))
		p1 := par(mt("↓")+mt("+")+mt("←")+mt("+")+mt("↑")+mt("+")+mt("→")) +
			par(mi("h")+mt("−2")+mi("R"))
		p2 := mt("+") + mi("Σ") + mt("·") + mfrac(mi("π")+mi("R"), mt("2")) + mt(",") + mi("R") + mt("=1,5") + mi("s")
		return []string{f}, []string{p1, p2}
	default:
		f := mt("4") + mi("s") + par(mi("h")+mt("−")+mi("s"))
		p := par(mt("↓")+mt("+")+mt("←")+mt("+")+mt("↑")+mt("+")+mt("→")) + mi("h")
		return []string{f}, []string{p}
	}
}

// stripSpaces — для сравнения текстов формул в тестах.
func stripSpaces(s string) string {
	return strings.ReplaceAll(strings.ReplaceAll(s, " ", ""), "\u00a0", "")
}
