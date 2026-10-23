package export

import (
	"fmt"
	"math"
	"strconv"
	"strings"

	"github.com/jung-kurt/gofpdf"

	"ozm/backend/internal/models"
)

// ---------- форматирование ----------

func fmtNum(v float64, digits int) string {
	s := strconv.FormatFloat(v, 'f', digits, 64)
	return strings.ReplaceAll(s, ".", ",")
}

// fmtDash — число или прочерк, когда значения нет.
func fmtDash(v float64, digits int) string {
	if v == 0 {
		return "–"
	}
	return fmtNum(v, digits)
}

// dimText — первый найденный размер из списка ключей (h, H, A, d …).
func dimText(dims map[string]float64, keys ...string) string {
	for _, k := range keys {
		if v, ok := dims[k]; ok && v != 0 {
			return strings.TrimSuffix(strings.TrimSuffix(fmtNum(v, 1), ",0"), ".")
		}
	}
	return "–"
}

// sidesText — стороны обогрева стрелками, как в легаси-отчёте.
func sidesText(s models.HeatedSides) string {
	var parts []string
	if s.Bottom {
		parts = append(parts, "↓")
	}
	if s.Left {
		parts = append(parts, "←")
	}
	if s.Top {
		parts = append(parts, "↑")
	}
	if s.Right {
		parts = append(parts, "→")
	}
	if len(parts) == 0 {
		return "все"
	}
	return strings.Join(parts, ", ")
}

// ---------- таблицы ----------

type pdfCol struct {
	title string
	width float64
	align string
}

type pdfRow struct {
	cells []string
	group bool
	// formulas — колонка → формула вместо текста, sketches — колонка → схема
	// сечения; minH — минимальная высота строки (для схем).
	formulas map[int][]func(*formula)
	sketches map[int]func(pdf *gofpdf.Fpdf, x, y, w, h float64)
	minH     float64
}

// table рисует таблицу с шапкой, переносом текста и повтором шапки на новой
// странице; строки-группы идут одной полосой на всю ширину.
func (b *pdfBuilder) table(cols []pdfCol, rows []pdfRow) {
	pdf := b.pdf
	total := 0.0
	for _, c := range cols {
		total += c.width
	}
	_, pageH := pdf.GetPageSize()
	bottom := pageH - 22

	// перенос по словам считаем сами: gofpdf SplitLines может разрезать строку
	// по байтам и «сломать» многобайтовый символ (паника в utf8toutf16)
	cellLines := func(text string, w float64) []string {
		words := strings.Fields(text)
		if len(words) == 0 {
			return []string{""}
		}
		var lines []string
		cur := ""
		for _, word := range words {
			// слово шире колонки — режем по символам, иначе оно налезет на соседей
			for pdf.GetStringWidth(word) > w-2 {
				runes := []rune(word)
				cut := len(runes)
				for cut > 1 && pdf.GetStringWidth(string(runes[:cut])) > w-2 {
					cut--
				}
				if cur != "" {
					lines = append(lines, cur)
					cur = ""
				}
				lines = append(lines, string(runes[:cut]))
				word = string(runes[cut:])
			}
			try := word
			if cur != "" {
				try = cur + " " + word
			}
			if cur == "" || pdf.GetStringWidth(try) <= w-2 {
				cur = try
			} else {
				lines = append(lines, cur)
				cur = word
			}
		}
		if cur != "" {
			lines = append(lines, cur)
		}
		return lines
	}

	drawHeader := func() {
		pdf.SetFont("tn", "B", 7)
		pdf.SetFillColor(pdfGray, pdfGray, pdfGray)
		heights := make([][]string, len(cols))
		maxLines := 1
		for i, c := range cols {
			heights[i] = cellLines(c.title, c.width)
			if len(heights[i]) > maxLines {
				maxLines = len(heights[i])
			}
		}
		h := float64(maxLines)*3.6 + 1.6
		y := pdf.GetY()
		x := 25.0
		for i, c := range cols {
			pdf.Rect(x, y, c.width, h, "F")
			pdf.Rect(x, y, c.width, h, "D")
			pdf.SetXY(x+1, y+0.8)
			for _, ln := range heights[i] {
				pdf.CellFormat(c.width-2, 3.6, ln, "", 2, "C", false, 0, "")
			}
			x += c.width
		}
		pdf.SetY(y + h)
	}
	// шапка не должна оставаться внизу страницы без строк
	if pdf.GetY()+14 > bottom {
		pdf.AddPage()
	}
	drawHeader()

	for _, row := range rows {
		if row.group {
			text := ""
			if len(row.cells) > 0 {
				text = row.cells[0]
			}
			pdf.SetFont("tn", "B", 8)
			lines := cellLines(text, total)
			h := float64(len(lines))*4 + 1.4
			if pdf.GetY()+h > bottom {
				pdf.AddPage()
				drawHeader()
			}
			y := pdf.GetY()
			pdf.SetFillColor(250, 250, 250)
			pdf.Rect(25, y, total, h, "F")
			pdf.Rect(25, y, total, h, "D")
			pdf.SetXY(26, y+0.7)
			for _, ln := range lines {
				pdf.CellFormat(total-2, 4, ln, "", 2, "L", false, 0, "")
			}
			pdf.SetY(y + h)
			continue
		}

		pdf.SetFont("tn", "", 7)
		heights := make([][]string, len(cols))
		maxLines := 1
		for i, c := range cols {
			text := ""
			if i < len(row.cells) {
				text = row.cells[i]
			}
			heights[i] = cellLines(text, c.width)
			if len(heights[i]) > maxLines {
				maxLines = len(heights[i])
			}
		}
		h := float64(maxLines)*3.8 + 1.2
		if row.minH > h {
			h = row.minH
		}
		if pdf.GetY()+h > bottom {
			pdf.AddPage()
			drawHeader()
			pdf.SetFont("tn", "", 7)
		}
		y := pdf.GetY()
		x := 25.0
		for i, c := range cols {
			pdf.Rect(x, y, c.width, h, "D")
			if fns, ok := row.formulas[i]; ok {
				for li, fn := range fns {
					drawFormula(pdf, x+1.5, y+5.6+float64(li)*4.8, 6.8, fn)
				}
				x += c.width
				continue
			}
			if fn, ok := row.sketches[i]; ok {
				fn(pdf, x+1, y+1, c.width-2, h-2)
				x += c.width
				continue
			}
			pdf.SetXY(x+1, y+0.6)
			align := c.align
			if align == "" {
				align = "L"
			}
			for _, ln := range heights[i] {
				pdf.CellFormat(c.width-2, 3.8, ln, "", 2, align, false, 0, "")
			}
			x += c.width
		}
		pdf.SetY(y + h)
	}
	pdf.Ln(4)
	pdf.SetFont("tn", "", 9.5)
}

// ---------- разделы ----------

func (b *pdfBuilder) section1() {
	pdf := b.pdf
	pdf.AddPage()
	b.heading("s1", "1. Общие данные")
	b.para("Для металлических конструкций, приведенных в таблице 1 необходимо вычислить:")
	b.bullet("приведенную толщину металла;", "толщину огнезащитной композиции;",
		"площади и объем защитных материалов;", "количество материалов для устройства защиты.")
	b.caption("Таблица 1.")

	b.para("Толщина сечения: в высоту h (h, H, A, d); в ширину b (b, B); стенки s (s, S, t, h); полки t (t, S1/S2); внутреннее закругление R; закругление полки r.")
	cols := []pdfCol{
		{"№", 7, "C"}, {"Марка элемента", 30, "L"}, {"Тип защитного покрытия", 30, "L"},
		{"Треб. предел огнест., мин", 16, "C"}, {"Обогрев", 16, "C"},
		{"Длина, мм", 14, "R"}, {"h", 10, "R"}, {"b", 10, "R"}, {"s", 10, "R"},
		{"t", 10, "R"}, {"R", 7, "R"}, {"r", 7, "R"},
	}
	var rows []pdfRow
	lastGroup := ""
	idx := 0
	for _, el := range b.elems {
		if el.group != lastGroup {
			rows = append(rows, pdfRow{group: true, cells: []string{el.group}})
			lastGroup = el.group
			idx = 0
		}
		idx++
		rows = append(rows, pdfRow{cells: []string{
			strconv.Itoa(idx), el.title, el.coatName, fmtDash(el.htLevel, 0), el.sides,
			fmtNum(el.lengthMM, 0),
			dimText(el.dims, "h", "H", "A", "d"),
			dimText(el.dims, "b", "B", "b1"),
			dimText(el.dims, "s", "S", "t", "h"),
			dimText(el.dims, "t", "S1", "S2"),
			dimText(el.dims, "R"),
			dimText(el.dims, "r", "tr"),
		}})
	}
	b.table(cols, rows)
	if b.beton != nil && b.beton.AreaM2 > 0 {
		b.para("Для железобетонных конструкций необходимо вычислить:")
		b.bullet("толщину огнезащитной композиции;", "площадь и объем плит огнезащиты;",
			"количество материалов для устройства огнезащиты.")
	}
}

func (b *pdfBuilder) section2() {
	pdf := b.pdf
	pdf.AddPage()
	b.heading("s2", "2. Расчет приведенной толщины металла")
	b.para("Приведенная толщина металла вычисляется по формуле:")
	b.displayFormula(12, func(f *formula) {
		f.it("δ").sub("пр").up(" = ").frac(
			func(g *formula) { g.it("F") },
			func(g *formula) { g.it("Π") },
		)
	})
	b.para("Где F — площадь поперечного сечения металлической конструкции; Π — периметр обогреваемой части конструкции. Оба параметра определяем согласно таблице 2.")
	b.captionTable("Таблица 2.", []pdfCol{
		{"Схема", 24, "C"},
		{"Тип сечения конструкции", 38, "L"},
		{"площадь F", 44, "L"},
		{"периметр Π", 64, "L"},
	}, b.formulaRows())
	b.para("Здесь и далее формулы расчета используют символы □↓, □←, □↑, □→, которые равны 0, если обогрева с данной стороны нет, и 1, если обогрев с данной стороны есть; логическую операцию ИЛИ; сумму подверженных обогреву сторон по углам Σ = ИЛИ(□↓,□←) + ИЛИ(□←,□↑) + ИЛИ(□↑,□→) + ИЛИ(□→,□↓).")
	b.para("Результаты расчета приведены в таблице 3.")
	b.caption("Таблица 3.")
	cols := []pdfCol{
		{"№", 6, "C"}, {"Марка элемента", 30, "L"}, {"Тип защитного покрытия", 28, "L"},
		{"Тип сечения конструкции", 34, "L"}, {"Площадь сечения F, мм²", 22, "R"},
		{"Периметр Π, мм", 20, "R"}, {"Приведенная толщина металла δпр, мм", 30, "R"},
	}
	var rows []pdfRow
	lastGroup := ""
	idx := 0
	for _, el := range b.elems {
		if el.group != lastGroup {
			rows = append(rows, pdfRow{group: true, cells: []string{el.group}})
			lastGroup = el.group
			idx = 0
		}
		idx++
		rows = append(rows, pdfRow{cells: []string{
			strconv.Itoa(idx), el.title, el.coatName, el.family,
			fmtNum(el.res.F, 0), fmtNum(el.res.Pi, 0), fmtNum(el.res.Dpr, 1),
		}})
	}
	b.table(cols, rows)
}

func (b *pdfBuilder) section3() {
	pdf := b.pdf
	pdf.AddPage()
	b.heading("s3", "3. Определение толщины огнезащитной изоляции")

	ozm := b.elemsOf("1")
	if len(ozm) > 0 {
		b.sub("Тип защитного покрытия: плиты огнезащитные ТЕХНО ОЗМ и ТЕХНО ОЗБ")
		b.para("Определение толщины огнезащитной композиции металлоконструкций, δ, выполняется по методике, приведенной в документе: «Инструкция по расчету фактических пределов огнестойкости стальных конструкций с композицией огнезащитной, выполненной из минераловатных плит ТЕХНО». Согласно пункта 3.4 ГОСТ 53295-2009, определение толщины ведем для критической температуры металла 500 °С.")
		b.para("Толщина плиты определяется по таблицам ТН для приведенной толщины металла и требуемого предела огнестойкости (рисунок 1). Полученные значения заносим в таблицу 4.")
		b.chart()
		b.caption("Рисунок 1. Определение толщины изоляции элементов")
		b.caption("Таблица 4.")
		cols := []pdfCol{
			{"№", 7, "C"}, {"Марка элемента", 45, "L"},
			{"δпр, мм", 24, "R"}, {"Треб. предел, мин", 28, "R"},
			{"δ, мм", 30, "R"}, {"R факт., мин", 36, "R"},
		}
		var rows []pdfRow
		lastGroup, idx := "", 0
		for _, el := range ozm {
			if el.group != lastGroup {
				rows = append(rows, pdfRow{group: true, cells: []string{el.group}})
				lastGroup = el.group
				idx = 0
			}
			idx++
			rows = append(rows, pdfRow{cells: []string{
				strconv.Itoa(idx), el.title, fmtNum(el.res.Dpr, 1), fmtNum(el.htLevel, 0),
				fmtNum(el.res.Delta, 0), fmtNum(b.factRFor(el.res.Delta, el.res.Dpr), 0),
			}})
		}
		b.table(cols, rows)
	}

	if b.beton != nil && b.beton.AreaM2 > 0 {
		delta := b.ozbDelta(b.beton.HtLevel)
		title := "ТЕХНО ОЗБ 80"
		if b.beton.HtLevel >= 240 {
			title = "ТЕХНО ОЗБ 110"
		}
		b.para(fmt.Sprintf("Толщина огнезащитной композиции железобетонных конструкций принимается на основании документа: «СЕРТИФИКАТ СООТВЕТСТВИЯ № CСБК RU.ПБ10.Н00132». δ = %.0f мм (%s). Предел огнестойкости конструкции составит %.0f минут (RE%.0f).", delta, title, b.beton.HtLevel, b.beton.HtLevel))
	}

	taikor := b.elemsOfCoats("2", "3", "4")
	if len(taikor) > 0 {
		b.sub("Тип защитного покрытия: защитное покрытие TAIKOR")
		b.para("Определение толщины огнезащитной композиции металлоконструкций, δ, выполняется по методике, приведенной в документе: СТО АРСС 1 1251254.001-018-03. Согласно пункта 5.5 СТО АРСС 1 1251254.001-018-03, определение толщины ведем для критической температуры металла 500 °C. Толщина и расход огнезащиты металлических конструкций определяются в соответствии с Инструкцией (предоставляется по отдельному запросу). Полученные значения заносим в таблицу 5.")
		b.caption("Таблица 5.")
		cols := []pdfCol{
			{"№", 7, "C"}, {"Марка элемента", 32, "L"},
			{"δпр, мм", 18, "R"}, {"Треб. предел, мин", 20, "R"},
			{"Тип защитного покрытия", 47, "L"},
			{"δ, мм", 16, "R"}, {"Расход, кг/м²", 30, "R"},
		}
		var rows []pdfRow
		lastGroup, idx := "", 0
		for _, el := range taikor {
			if el.group != lastGroup {
				rows = append(rows, pdfRow{group: true, cells: []string{el.group}})
				lastGroup = el.group
				idx = 0
			}
			idx++
			rates := b.taikorMaterials(el)
			if len(rates) == 0 {
				rows = append(rows, pdfRow{cells: []string{strconv.Itoa(idx), el.title, fmtNum(el.res.Dpr, 1), fmtNum(el.htLevel, 0), el.coatName, "–", "–"}})
				continue
			}
			for i, m := range rates {
				if i == 0 {
					rows = append(rows, pdfRow{cells: []string{
						strconv.Itoa(idx), el.title, fmtNum(el.res.Dpr, 1), fmtNum(el.htLevel, 0),
						m.title, fmtNum(m.tsp, 2), fmtNum(m.rate, 2),
					}})
				} else {
					rows = append(rows, pdfRow{cells: []string{"", "", "", "", m.title, fmtNum(m.tsp, 2), fmtNum(m.rate, 2)}})
				}
			}
		}
		b.table(cols, rows)
	}
}

func (b *pdfBuilder) section4() {
	pdf := b.pdf
	pdf.AddPage()
	b.heading("s4", "4. Расчёт площадей защищаемых элементов и объема защитных материалов")

	ozm := b.elemsOf("1")
	if len(ozm) > 0 || (b.beton != nil && b.beton.AreaM2 > 0) {
		b.sub("Тип защитного покрытия: плиты огнезащитные ТЕХНО ОЗМ и ТЕХНО ОЗБ")
		b.para("Объём (м³) огнезащитных плит определяется по формуле:")
		b.displayFormula(11, func(f *formula) {
			f.it("V").up(" = ").it("δ").up(" · ").it("S")
		})
		b.para("где δ — толщина огнезащиты (определено в предыдущем разделе), S — площадь огнезащитных плит. Для металлоконструкций площадь огнезащитных плит S, а также площади нанесения клея и декоративного покрытия определяем согласно таблицы 6.")
		b.captionTable("Таблица 6.", []pdfCol{
			{"Конфигурация огнезащиты", 40, "L"},
			{"площадь огнезащитных плит S", 45, "L"},
			{"площадь под нанесение клея", 40, "L"},
			{"декоративное покрытие", 45, "L"},
		}, []pdfRow{
			{group: true, cells: []string{"Формулы для расчета"}},
			{cells: []string{"короб", "(P + Zδ)L + 0,1A·(h − 2t)L/0,6, где A = □← + □→ для двутавров", "(P + Zδ)L", "(P + 2Zδ)L"}},
			{cells: []string{"контур", "(P + Zδ)L", "(P + Zδ)L", "(P + 2Zδ)L"}},
		})
		b.para("Здесь P — периметр принятых к защите сторон элемента:")
		b.displayFormula(11, func(f *formula) {
			f.it("P").up(" = (").up("□←").up(" + ").up("□→").up(")").it("h").up(" + (").up("□↓").up(" + ").up("□←").up(")").it("b")
		})
		b.para("Z — сумма углов, подверженных обогреву.")
		b.para("Результаты расчета занесены в таблицу 7.")
		b.caption("Таблица 7.")
		cols := []pdfCol{
			{"№", 7, "C"}, {"Марка элемента", 36, "L"}, {"L, м", 12, "R"},
			{"Конфиг.", 20, "C"}, {"S, м²", 16, "R"},
			{"δ, мм", 12, "R"}, {"V, м³", 16, "R"},
			{"S клея, м²", 18, "R"}, {"S декора, м²", 18, "R"},
		}
		var rows []pdfRow
		lastGroup, idx := "", 0
		for _, el := range ozm {
			if el.group != lastGroup {
				rows = append(rows, pdfRow{group: true, cells: []string{el.group}})
				lastGroup = el.group
				idx = 0
			}
			idx++
			rows = append(rows, pdfRow{cells: []string{
				strconv.Itoa(idx), el.title, fmtNum(el.res.LengthM, 0), liningName(el.res.Lining),
				fmtNum(el.res.AreaM2, 2), fmtNum(el.res.Delta, 0), fmtNum(el.res.Volume, 3),
				fmtNum(el.res.AreaM2, 2), fmtNum(el.res.AreaM2, 2),
			}})
		}
		b.table(cols, rows)
	}

	if b.beton != nil && b.beton.AreaM2 > 0 {
		delta := b.ozbDelta(b.beton.HtLevel)
		q := b.ozbCoef()
		b.para("Производим расчет для железобетонных конструкций.")
		b.para(fmt.Sprintf("Площадь железобетонных конструкций S = %s м².", fmtNum(b.beton.AreaM2, 0)))
		b.para(fmt.Sprintf("Объем V = %s м · %s м² = %s м³.", fmtNum(delta/1000, 2), fmtNum(b.beton.AreaM2, 0), fmtNum(b.beton.AreaM2*delta/1000*q, 3)))
	}

	taikor := b.elemsOfCoats("2", "3", "4")
	if len(taikor) > 0 {
		b.sub("Тип защитного покрытия: защитное покрытие TAIKOR")
		b.para("Объём (кг) защитного покрытия TAIKOR определяется по формуле:")
		b.displayFormula(11, func(f *formula) {
			f.it("M").up(" = ").it("q").up(" · ").it("S")
		})
		b.para("где q — расход защитного состава для металлических конструкций, S — площадь защищаемых металлических конструкций. Площадь S металлоконструкций определяется в зависимости от периметра принятых к защите сторон элемента Π, а также его длины L:")
		b.displayFormula(11, func(f *formula) {
			f.it("S").up(" = ").frac(
				func(g *formula) { g.it("Π") },
				func(g *formula) { g.up("1000") },
			).up(" · ").it("L")
		})
		b.para("Результаты расчета занесены в таблицу 8.")
		b.caption("Таблица 8.")
		cols := []pdfCol{
			{"№", 7, "C"}, {"Марка элемента", 32, "L"}, {"L, м", 12, "R"},
			{"Π, мм", 16, "R"}, {"S, м²", 16, "R"},
			{"Тип защитного покрытия", 42, "L"}, {"q, кг/м²", 18, "R"}, {"M, кг", 18, "R"},
		}
		var rows []pdfRow
		lastGroup, idx := "", 0
		for _, el := range taikor {
			if el.group != lastGroup {
				rows = append(rows, pdfRow{group: true, cells: []string{el.group}})
				lastGroup = el.group
				idx = 0
			}
			idx++
			rates := b.taikorMaterials(el)
			fullPerimeter := b.fullPerimeter(el) * 1000
			for i, m := range rates {
				area := el.res.AreaM2
				if m.akz {
					area = el.res.AkzAreaM2
				}
				if i == 0 {
					rows = append(rows, pdfRow{cells: []string{
						strconv.Itoa(idx), el.title, fmtNum(el.res.LengthM, 0), fmtNum(fullPerimeter, 0),
						fmtNum(area, 2), m.title, fmtNum(m.rate, 2), fmtNum(area*m.rate, 2),
					}})
				} else {
					rows = append(rows, pdfRow{cells: []string{"", "", "", "", fmtNum(area, 2), m.title, fmtNum(m.rate, 2), fmtNum(area*m.rate, 2)}})
				}
			}
		}
		b.table(cols, rows)
	}
}

func (b *pdfBuilder) section5() {
	pdf := b.pdf
	pdf.AddPage()
	b.heading("s5", "5. Итоговая спецификация материалов")
	b.para("Итоговое количество материала для устройства огнезащиты по проекту представлено в таблице 9.")
	b.caption("Таблица 9.")

	groups := []struct {
		title string
		ids   []string
	}{
		{"Защита металлоконструкций огнезащитными плитами", []string{"OZM", "KCer"}},
		{"Защита бетонных конструкций огнезащитными плитами", []string{"OZB", "KAnk"}},
		{"Защита металлоконструкций покрытием TAIKOR", []string{"T150p", "Taikor_2", "Taikor_3", "Taikor_4", "Taikor_Extra", "T425t"}},
		{"Декоративное покрытие плит огнезащиты", []string{"KVer"}},
	}
	byID := map[string]models.MaterialLine{}
	for _, m := range b.resp.Materials {
		byID[m.ID] = m
	}
	cols := []pdfCol{
		{"№", 6, "C"}, {"Название материала", 58, "L"},
		{"Базовое значение", 30, "R"}, {"Коэф. расхода", 34, "R"}, {"Итоговое количество", 32, "R"},
	}
	var rows []pdfRow
	for _, g := range groups {
		var lines []pdfRow
		n := 0
		for _, id := range g.ids {
			m, ok := byID[id]
			if !ok {
				continue
			}
			n++
			base, coef := b.baseAndCoef(id, m)
			lines = append(lines, pdfRow{cells: []string{
				strconv.Itoa(n), b.matTitle(id, m.Title), base, coef,
				fmt.Sprintf("%s %s", fmtNum(m.Quantity, decimalsFor(m)), m.Unit),
			}})
		}
		if len(lines) == 0 {
			continue
		}
		rows = append(rows, pdfRow{group: true, cells: []string{g.title}})
		rows = append(rows, lines...)
	}
	b.table(cols, rows)

	if kver, ok := byID["KVer"]; ok && kver.Quantity > 0 {
		area := safeDiv(kver.Quantity, b.matRate("KVer"))
		b.para(fmt.Sprintf("В качестве декоративного покрытия плит огнезащиты используется материал Штукатурка Ceresit. Данный материал наносится на поверхность минераловатных плит без предварительного нанесения клеевого состава с армирующей сеткой. Расход декоративного покрытия зависит от марки выбранного материала и способа нанесения (1,5–3,2 кг/м²). В расчете принят максимальный ориентировочный расход — 3,2 кг/м². Площадь плит огнезащиты для декоративного покрытия — %s м². Суммарный расход Штукатурка Ceresit — %s кг.", fmtNum(area, 2), fmtNum(kver.Quantity, 2)))
	}
}

// ---------- данные для разделов ----------

type pdfMaterial struct {
	title string
	tsp   float64
	rate  float64
	akz   bool
}

// elemsOf — элементы с указанным покрытием (1 — ОЗМ).
func (b *pdfBuilder) elemsOf(coatID string) []elemInfo {
	var out []elemInfo
	for _, el := range b.elems {
		if parseCoatN(el.coatID) == parseCoatN(coatID) {
			out = append(out, el)
		}
	}
	return out
}

func (b *pdfBuilder) elemsOfCoats(coats ...string) []elemInfo {
	var out []elemInfo
	for _, el := range b.elems {
		for _, c := range coats {
			if parseCoatN(el.coatID) == parseCoatN(c) {
				out = append(out, el)
				break
			}
		}
	}
	return out
}

// taikorMaterials — составы TAIKOR по элементу: огнезащитные составы идут по
// площади огнезащиты, грунт и финиш — по площади АКЗ (akz = true).
func (b *pdfBuilder) taikorMaterials(el elemInfo) []pdfMaterial {
	var out []pdfMaterial
	if r, ok := b.svc.taikorRate(el.input, el.res.Delta); ok {
		out = append(out, pdfMaterial{title: b.svc.matTitle("Taikor_"+el.coatID, el.coatName), tsp: r.Tsp, rate: r.Rate})
	}
	if heat, ok := b.svc.taikorHeat(el.input); ok {
		out = append(out, pdfMaterial{title: "TAIKOR FP Extra", tsp: heat.Delta, rate: heat.Rate})
	}
	if el.input.Primer {
		out = append(out, pdfMaterial{title: b.svc.matTitle("T150p", "TAIKOR Primer 150"), tsp: b.svc.matLayer("T150p"), rate: b.svc.matRate("T150p"), akz: true})
	}
	if el.input.Enamel {
		out = append(out, pdfMaterial{title: b.svc.matTitle("T425t", "TAIKOR Top 425"), tsp: b.svc.matLayer("T425t"), rate: b.svc.matRate("T425t"), akz: true})
	}
	return out
}

// fullPerimeter — полный периметр сечения, м.
func (b *pdfBuilder) fullPerimeter(el elemInfo) float64 {
	if el.res.AkzAreaM2 > 0 && el.res.LengthM > 0 && el.res.Quantity > 0 {
		return el.res.AkzAreaM2 / (el.res.LengthM * el.res.Quantity)
	}
	return 0
}

// baseAndCoef — базовое значение и коэффициент расхода для итоговой таблицы.
func (b *pdfBuilder) baseAndCoef(id string, m models.MaterialLine) (string, string) {
	q := b.taikorCoef()
	switch id {
	case "OZM":
		q = b.ozmCoef()
		return fmt.Sprintf("%s м³", fmtNum(m.Quantity/q, 3)), fmtNum(q, 2)
	case "OZB":
		q = b.ozbCoef()
		return fmt.Sprintf("%s м³", fmtNum(m.Quantity/q, 3)), fmtNum(q, 2)
	case "KCer":
		r := b.matRate("KCer")
		return fmt.Sprintf("%s м²", fmtNum(safeDiv(m.Quantity, r), 2)), fmt.Sprintf("%s кг на 1 м²", fmtNum(r, 1))
	case "KVer":
		r := b.matRate("KVer")
		return fmt.Sprintf("%s м²", fmtNum(safeDiv(m.Quantity, r), 2)), fmt.Sprintf("%s кг на 1 м²", fmtNum(r, 1))
	case "KAnk":
		r := b.matRate("KAnk")
		return fmt.Sprintf("%s м²", fmtNum(safeDiv(m.Quantity, r), 2)), fmt.Sprintf("%s шт на 1 м²", fmtNum(r, 0))
	case "T150p":
		return fmt.Sprintf("%s кг", fmtNum(m.Quantity/q, 2)), fmtNum(q, 2)
	case "T425t":
		return fmt.Sprintf("%s кг", fmtNum(m.Quantity/q, 2)), fmtNum(q, 2)
	}
	return fmt.Sprintf("%s кг", fmtNum(m.Quantity/q, 2)), fmtNum(q, 2)
}

func safeDiv(a, b float64) float64 {
	if b == 0 {
		return 0
	}
	return a / b
}

// decimalsFor — точность печати количества из справочника.
func decimalsFor(m models.MaterialLine) int {
	if m.Decimals != nil {
		return *m.Decimals
	}
	return 3
}

// chart — рисунок 1: предел огнестойкости от приведённой толщины металла.
func (b *pdfBuilder) chart() {
	pdf := b.pdf
	const w, h = 95.0, 62.0
	maxX, maxY := 50.0, 250.0
	if pdf.GetY()+h+30 > 268 {
		pdf.AddPage()
	}
	top := pdf.GetY() + 6
	x0, y0 := 45.0, top+h
	pdf.SetDrawColor(120, 120, 120)
	pdf.SetLineWidth(0.2)
	pdf.Rect(x0, y0-h, w, h, "D")
	// сетка и подписи осей
	pdf.SetFont("tn", "", 6.5)
	for i := 0; i <= 5; i++ {
		x := x0 + w*float64(i)/5
		pdf.Line(x, y0-h, x, y0)
		pdf.SetXY(x-6, y0+1)
		pdf.CellFormat(12, 3, fmtNum(maxX*float64(i)/5, 0), "", 0, "C", false, 0, "")
	}
	for i := 0; i <= 5; i++ {
		y := y0 - h*float64(i)/5
		pdf.Line(x0, y, x0+w, y)
		pdf.SetXY(x0-11, y-1.5)
		pdf.CellFormat(10, 3, fmtNum(maxY*float64(i)/5, 0), "", 0, "R", false, 0, "")
	}
	pdf.SetXY(x0+w/2-20, y0+5)
	pdf.CellFormat(40, 3, "Приведенная толщина металла (δпр, мм)", "", 0, "C", false, 0, "")
	pdf.SetFont("tn", "", 6.5)
	pdf.SetXY(x0+w+2, y0-h-6)
	pdf.CellFormat(30, 3, "Предел огнестойкости (мин.)", "", 0, "L", false, 0, "")

	// линии по толщинам плит: R = a·(δпр − base) + b
	thicknesses := []float64{30, 40, 50, 60, 70, 80, 90}
	pdf.SetLineWidth(0.3)
	for ti, th := range thicknesses {
		gray := 40 + ti*25
		if gray > 200 {
			gray = 200
		}
		pdf.SetDrawColor(int(gray), int(gray), int(gray))
		started := false
		var px, py float64
		for step := 0.0; step <= maxX; step += 1 {
			r := b.factRFor(th, step)
			if r <= 0 {
				started = false
				continue
			}
			x := x0 + w*step/maxX
			y := y0 - h*math.Min(r, maxY)/maxY
			if started {
				pdf.Line(px, py, x, y)
			}
			px, py = x, y
			started = true
		}
		pdf.SetXY(x0+w+2, y0-h+float64(ti)*4)
		pdf.CellFormat(20, 3, fmt.Sprintf("%.0f мм", th), "", 0, "L", false, 0, "")
	}
	pdf.SetTextColor(33, 33, 33)
	pdf.SetY(y0 + 8)
}

// factRFor — предел огнестойкости плиты толщиной thickness при δпр (по таблице t500).
func (b *pdfBuilder) factRFor(thickness, dpr float64) float64 {
	var rows []models.T500Row
	for _, r := range b.t500Rows() {
		if r.Thickness == thickness {
			rows = append(rows, r)
		}
	}
	if len(rows) == 0 {
		return 0
	}
	base := rows[0].BaseDelta
	for _, r := range rows {
		if r.BaseDelta <= dpr && r.BaseDelta >= base {
			base = r.BaseDelta
		}
	}
	for _, r := range rows {
		if r.BaseDelta == base {
			return r.A*math.Max(0, dpr-base) + r.B
		}
	}
	return 0
}
