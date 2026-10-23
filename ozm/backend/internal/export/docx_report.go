package export

import (
	"bytes"
	"fmt"
	"image"
	"image/color"
	"image/draw"
	"image/png"
	"math"
	"strconv"
	"strings"

	"ozm/backend/internal/models"
)

// docxReport собирает Word-выгрузку по образцу PDF-отчёта: тот же состав —
// титул, содержание, пять разделов с таблицами 1–9, приложения со схемами,
// сертификатами и техлистами, список литературы, те же колонтитулы. Числовые
// данные берутся из тех же функций, что и в PDF, поэтому расхождений в цифрах
// быть не может; отличается только вёрстка (Word пересобирает страницы сам).
type docxReport struct {
	*docxDoc
	svc   *Service
	resp  models.CalcResponse
	elems []elemInfo
	beton *models.BetonInput
	// data — переиспользуем расчётные помощники PDF-сборщика: они не рисуют,
	// а только считают по конфигу и результатам.
	data *pdfBuilder
}

func (s *Service) buildReportDocx(resp models.CalcResponse) ([]byte, error) {
	d := newDocx()
	d.title = "Расчет огнезащиты — " + resp.Inputs.ObjectName
	r := &docxReport{docxDoc: d, svc: s, resp: resp}
	r.elems = s.pdfElements(resp)
	r.beton = resp.Inputs.Beton
	r.data = &pdfBuilder{svc: s, resp: resp, elems: r.elems, beton: r.beton, record: map[string]int{}}

	d.SetHeader(func(*docxDoc) []byte { return r.header() })
	d.SetFooter(func(*docxDoc) []byte { return r.footer() })

	r.cover()
	r.contents()
	r.section1()
	r.section2()
	r.section3()
	r.section4()
	r.section5()
	r.appendices()
	r.literature()

	return d.Bytes()
}

// ---------- колонтитулы ----------

func (d *docxReport) header() []byte {
	var left, right strings.Builder
	if len(reportLogoPlainPNG) > 0 {
		rid := d.registerImage("logo.png", reportLogoPlainPNG)
		logoW := 45.6 * emuPerMM
		logoH := logoW * 49 / 281.0
		left.WriteString(inlineImage(rid, "logo", int(logoW), int(logoH), "left"))
	}
	for _, line := range []string{"Корпорация ТЕХНОНИКОЛЬ", "Техническая поддержка 8-800-600-05-65", "www.tn.ru, nav.tn.ru"} {
		right.WriteString(paraXML("right", 0, 0, []docxRun{{Text: line, Size: 7, Color: "464646"}}, ""))
	}
	if len(reportQRPNG) > 0 {
		rid := d.registerImage("qr.png", reportQRPNG)
		right.WriteString(inlineImage(rid, "qr", int(14*emuPerMM), int(14*emuPerMM), "right"))
	}
	// логотип слева, контакты и QR справа — как в PDF
	var b strings.Builder
	b.WriteString(`<w:tbl><w:tblPr><w:tblW w:w="9639" w:type="dxa"/><w:tblBorders>`)
	for _, side := range []string{"top", "left", "bottom", "right", "insideH", "insideV"} {
		b.WriteString(fmt.Sprintf(`<w:%s w:val="none" w:sz="0" w:space="0" w:color="FFFFFF"/>`, side))
	}
	b.WriteString(`</w:tblBorders><w:tblLayout w:type="fixed"/></w:tblPr>`)
	b.WriteString(`<w:tblGrid><w:gridCol w:w="5953"/><w:gridCol w:w="3686"/></w:tblGrid><w:tr>`)
	b.WriteString(`<w:tc><w:tcPr><w:tcW w:w="5953" w:type="dxa"/><w:vAlign w:val="center"/></w:tcPr>`)
	b.WriteString(left.String())
	b.WriteString(`</w:tc><w:tc><w:tcPr><w:tcW w:w="3686" w:type="dxa"/><w:vAlign w:val="center"/></w:tcPr>`)
	b.WriteString(right.String())
	b.WriteString(`</w:tc></w:tr></w:tbl>`)
	return []byte(b.String())
}

func (d *docxReport) footer() []byte {
	// линия + номер страницы в красном квадрате: в Word квадрат не нарисовать
	// без фигур, поэтому номер в красном цвете и жирный.
	var b strings.Builder
	b.WriteString(`<w:p><w:pPr><w:pBdr><w:bottom w:val="single" w:sz="8" w:space="1" w:color="E31837"/></w:pBdr>`)
	b.WriteString(`<w:jc w:val="right"/></w:pPr>`)
	b.WriteString(`<w:r><w:rPr><w:b/><w:color w:val="E31837"/><w:sz w:val="16"/></w:rPr><w:t xml:space="preserve"> </w:t></w:r>`)
	b.WriteString(pageFieldXML(8))
	b.WriteString(`<w:r><w:rPr><w:color w:val="828282"/><w:sz w:val="14"/></w:rPr><w:t xml:space="preserve"> / </w:t></w:r>`)
	b.WriteString(`<w:fldSimple w:instr=" NUMPAGES "><w:r><w:rPr><w:color w:val="828282"/><w:sz w:val="14"/></w:rPr><w:t>1</w:t></w:r></w:fldSimple>`)
	b.WriteString("</w:p>")
	return []byte(b.String())
}

// ---------- титул и содержание ----------

func (d *docxReport) cover() {
	if len(reportLogoPlainPNG) > 0 {
		d.ImageSize("logo-cover.png", reportLogoPlainPNG, 72.3, 72.3*49/281, "right")
	}
	d.Spacer(30)
	addr := strings.TrimSpace(d.resp.Inputs.Address)
	if addr == "" {
		addr = strings.TrimSpace(d.resp.Inputs.ObjectName)
	}
	// серая полоса с адресом и названием — как в PDF
	d.TablePlain([]float64{170}, [][]docxCell{
		{{RowH: 100, Fill: "F3F3F3", Align: "center",
			Runs: []docxRun{{Text: "склад по адресу: " + addr, Size: 12, Color: "E31837"}}}},
	})
	d.Spacer(6)
	d.Para("center", docxRun{Text: "Расчет огнезащиты", Bold: true, Size: 24})
	d.Spacer(90)
	d.Para("center", docxRun{Text: strconv.Itoa(reportYear()), Size: 11})
	d.PageBreak()
}

// contents — оглавление: поле TOC, Word обновит его при открытии (updateFields).
func (d *docxReport) contents() {
	d.Para("left", docxRun{Text: "Содержание", Bold: true, Size: 13})
	d.Spacer(6)
	d.TOC([]string{
		"1. Общие данные",
		"2. Расчет приведенной толщины металла",
		"3. Определение толщины огнезащитной изоляции",
		"4. Расчёт площадей защищаемых элементов и объема защитных материалов",
		"5. Итоговая спецификация материалов",
		"Приложение A. Устройство огнезащиты конструкции",
		"Приложение Б. Сертификаты пожарной безопасности",
		"Приложение В. Технические листы",
		"Список используемой литературы",
	})
	d.PageBreak()
}

// ---------- разделы ----------

func (d *docxReport) heading(title string) {
	d.ParaStyle("Heading1", "left", docxRun{Text: title, Size: 13, Bold: true})
}

func (d *docxReport) sub(title string) {
	d.ParaStyle("Heading2", "left", docxRun{Text: title, Size: 10.5, Bold: true})
}

func (d *docxReport) para(text string) {
	d.Para("left", docxRun{Text: text, Size: 9.5})
}

func (d *docxReport) bullet(items ...string) {
	for _, it := range items {
		d.Para("left", docxRun{Text: "•  " + it, Size: 9.5})
	}
}

func (d *docxReport) caption(text string) {
	d.Para("right", docxRun{Text: text, Size: 9})
}

func (d *docxReport) section1() {
	d.heading("1. Общие данные")
	d.para("Для металлических конструкций, приведенных в таблице 1 необходимо вычислить:")
	d.bullet("приведенную толщину металла;", "толщину огнезащитной композиции;",
		"площади и объем защитных материалов;", "количество материалов для устройства защиты.")
	d.caption("Таблица 1.")
	d.para("Толщина сечения: в высоту h (h, H, A, d); в ширину b (b, B); стенки s (s, S, t, h); полки t (t, S1/S2); внутреннее закругление R; закругление полки r.")

	widths := []float64{7, 30, 30, 16, 16, 14, 10, 10, 10, 10, 7, 7}
	rows := [][]docxCell{d.tableHead(widths, "№", "Марка элемента", "Тип защитного покрытия",
		"Треб. предел огнест., мин", "Обогрев", "Длина, мм", "h", "b", "s", "t", "R", "r")}
	lastGroup, idx := "", 0
	for _, el := range d.elems {
		if el.group != lastGroup {
			rows = append(rows, []docxCell{{Runs: []docxRun{{Text: el.group, Bold: true, Size: 8}},
				Span: len(widths), Align: "left", Fill: "FAFAFA"}})
			lastGroup = el.group
			idx = 0
		}
		idx++
		rows = append(rows, []docxCell{
			{Text: strconv.Itoa(idx), Align: "center"},
			{Text: el.title},
			{Text: el.coatName},
			{Text: fmtDash(el.htLevel, 0), Align: "center"},
			{Text: el.sides, Align: "center"},
			{Text: fmtNum(el.lengthMM, 0), Align: "right"},
			{Text: dimText(el.dims, "h", "H", "A", "d"), Align: "right"},
			{Text: dimText(el.dims, "b", "B", "b1"), Align: "right"},
			{Text: dimText(el.dims, "s", "S", "t", "h"), Align: "right"},
			{Text: dimText(el.dims, "t", "S1", "S2"), Align: "right"},
			{Text: dimText(el.dims, "R"), Align: "right"},
			{Text: dimText(el.dims, "r", "tr"), Align: "right"},
		})
	}
	d.Table(widths, rows)

	if d.beton != nil && d.beton.AreaM2 > 0 {
		d.para("Для железобетонных конструкций необходимо вычислить:")
		d.bullet("толщину огнезащитной композиции;", "площадь и объем плит огнезащиты;",
			"количество материалов для устройства огнезащиты.")
	}
	d.PageBreak()
}

func (d *docxReport) section2() {
	d.heading("2. Расчет приведенной толщины металла")
	d.para("Приведенная толщина металла вычисляется по формуле:")
	d.Para("center", docxRun{Text: "δпр = F / Π", Ital: true, Font: "Times New Roman", Size: 12})
	d.para("Где F — площадь поперечного сечения металлической конструкции; Π — периметр обогреваемой части конструкции. Оба параметра определяем согласно таблице 2.")

	d.caption("Таблица 2.")
	w2 := []float64{24, 38, 44, 64}
	rows2 := [][]docxCell{d.tableHead(w2, "Схема", "Тип сечения конструкции", "площадь F", "периметр Π")}
	rows2 = append(rows2, []docxCell{{Runs: []docxRun{{Text: "Формулы для расчета", Bold: true, Size: 8}}, Span: 4, Fill: "FAFAFA"}})
	for _, t := range table2Formulas() {
		rows2 = append(rows2, []docxCell{
			{Text: t[0], Align: "center"},
			{Text: t[1]},
			{Text: t[2]},
			{Text: t[3]},
		})
	}
	d.Table(w2, rows2)
	d.para("Здесь и далее формулы расчета используют символы □↓, □←, □↑, □→, которые равны 0, если обогрева с данной стороны нет, и 1, если обогрев с данной стороны есть; логическую операцию ИЛИ; сумму подверженных обогреву сторон по углам Σ = ИЛИ(□↓,□←) + ИЛИ(□←,□↑) + ИЛИ(□↑,□→) + ИЛИ(□→,□↓).")
	d.para("Результаты расчета приведены в таблице 3.")
	d.caption("Таблица 3.")
	widths := []float64{6, 30, 28, 34, 22, 20, 30}
	rows := [][]docxCell{d.tableHead(widths, "№", "Марка элемента", "Тип защитного покрытия",
		"Тип сечения конструкции", "Площадь сечения F, мм²", "Периметр Π, мм", "Приведенная толщина металла δпр, мм")}
	lastGroup, idx := "", 0
	for _, el := range d.elems {
		if el.group != lastGroup {
			rows = append(rows, []docxCell{{Runs: []docxRun{{Text: el.group, Bold: true, Size: 8}},
				Span: len(widths), Fill: "FAFAFA"}})
			lastGroup = el.group
			idx = 0
		}
		idx++
		rows = append(rows, []docxCell{
			{Text: strconv.Itoa(idx), Align: "center"},
			{Text: el.title},
			{Text: el.coatName},
			{Text: el.family},
			{Text: fmtNum(el.res.F, 0), Align: "right"},
			{Text: fmtNum(el.res.Pi, 0), Align: "right"},
			{Text: fmtNum(el.res.Dpr, 1), Align: "right"},
		})
	}
	d.Table(widths, rows)
	d.PageBreak()
}

func (d *docxReport) section3() {
	d.heading("3. Определение толщины огнезащитной изоляции")
	ozm := d.data.elemsOf("1")
	if len(ozm) > 0 {
		d.sub("Тип защитного покрытия: плиты огнезащитные ТЕХНО ОЗМ и ТЕХНО ОЗБ")
		d.para("Определение толщины огнезащитной композиции металлоконструкций, δ, выполняется по методике, приведенной в документе: «Инструкция по расчету фактических пределов огнестойкости стальных конструкций с композицией огнезащитной, выполненной из минераловатных плит ТЕХНО». Согласно пункта 3.4 ГОСТ 53295-2009, определение толщины ведем для критической температуры металла 500 °С.")
		d.para("Толщина плиты определяется по таблицам ТН для приведенной толщины металла и требуемого предела огнестойкости (рисунок 1). Полученные значения заносим в таблицу 4.")
		if img, err := d.chartPNG(); err == nil {
			d.ImageSize("chart.png", img, 150, 98, "center")
			d.caption("Рисунок 1. Определение толщины изоляции элементов")
		}
		d.caption("Таблица 4.")
		widths := []float64{7, 45, 24, 28, 30, 36}
		rows := [][]docxCell{d.tableHead(widths, "№", "Марка элемента", "δпр, мм",
			"Треб. предел, мин", "δ, мм", "R факт., мин")}
		lastGroup, idx := "", 0
		for _, el := range ozm {
			if el.group != lastGroup {
				rows = append(rows, []docxCell{{Runs: []docxRun{{Text: el.group, Bold: true, Size: 8}},
					Span: len(widths), Fill: "FAFAFA"}})
				lastGroup = el.group
				idx = 0
			}
			idx++
			rows = append(rows, []docxCell{
				{Text: strconv.Itoa(idx), Align: "center"},
				{Text: el.title},
				{Text: fmtNum(el.res.Dpr, 1), Align: "right"},
				{Text: fmtNum(el.htLevel, 0), Align: "right"},
				{Text: fmtNum(el.res.Delta, 0), Align: "right"},
				{Text: fmtNum(d.data.factRFor(el.res.Delta, el.res.Dpr), 0), Align: "right"},
			})
		}
		d.Table(widths, rows)
	}

	if d.beton != nil && d.beton.AreaM2 > 0 {
		delta := d.svc.ozbDelta(d.beton.HtLevel)
		title := "ТЕХНО ОЗБ 80"
		if d.beton.HtLevel >= 240 {
			title = "ТЕХНО ОЗБ 110"
		}
		d.para(fmt.Sprintf("Толщина огнезащитной композиции железобетонных конструкций принимается на основании документа: «СЕРТИФИКАТ СООТВЕТСТВИЯ № CСБК RU.ПБ10.Н00132». δ = %.0f мм (%s). Предел огнестойкости конструкции составит %.0f минут (RE%.0f).",
			delta, title, d.beton.HtLevel, d.beton.HtLevel))
	}

	taikor := d.data.elemsOfCoats("2", "3", "4")
	if len(taikor) > 0 {
		d.sub("Тип защитного покрытия: защитное покрытие TAIKOR")
		d.para("Определение толщины огнезащитной композиции металлоконструкций, δ, выполняется по методике, приведенной в документе: СТО АРСС 1 1251254.001-018-03. Согласно пункта 5.5 СТО АРСС 1 1251254.001-018-03, определение толщины ведем для критической температуры металла 500 °C. Толщина и расход огнезащиты металлических конструкций определяются в соответствии с Инструкцией (предоставляется по отдельному запросу). Полученные значения заносим в таблицу 5.")
		d.caption("Таблица 5.")
		widths := []float64{7, 32, 18, 20, 47, 16, 30}
		rows := [][]docxCell{d.tableHead(widths, "№", "Марка элемента", "δпр, мм",
			"Треб. предел, мин", "Тип защитного покрытия", "δ, мм", "Расход, кг/м²")}
		lastGroup, idx := "", 0
		for _, el := range taikor {
			if el.group != lastGroup {
				rows = append(rows, []docxCell{{Runs: []docxRun{{Text: el.group, Bold: true, Size: 8}},
					Span: len(widths), Fill: "FAFAFA"}})
				lastGroup = el.group
				idx = 0
			}
			idx++
			rates := d.data.taikorMaterials(el)
			if len(rates) == 0 {
				rows = append(rows, []docxCell{
					{Text: strconv.Itoa(idx), Align: "center"}, {Text: el.title},
					{Text: fmtNum(el.res.Dpr, 1), Align: "right"}, {Text: fmtNum(el.htLevel, 0), Align: "right"},
					{Text: el.coatName}, {Text: "–", Align: "right"}, {Text: "–", Align: "right"},
				})
				continue
			}
			for i, m := range rates {
				first := strconv.Itoa(idx)
				title := el.title
				dpr := fmtNum(el.res.Dpr, 1)
				limit := fmtNum(el.htLevel, 0)
				if i > 0 {
					first, title, dpr, limit = "", "", "", ""
				}
				rows = append(rows, []docxCell{
					{Text: first, Align: "center"}, {Text: title},
					{Text: dpr, Align: "right"}, {Text: limit, Align: "right"},
					{Text: m.title}, {Text: fmtNum(m.tsp, 2), Align: "right"}, {Text: fmtNum(m.rate, 2), Align: "right"},
				})
			}
		}
		d.Table(widths, rows)
	}
	d.PageBreak()
}

func (d *docxReport) section4() {
	d.heading("4. Расчёт площадей защищаемых элементов и объема защитных материалов")
	ozm := d.data.elemsOf("1")
	if len(ozm) > 0 || (d.beton != nil && d.beton.AreaM2 > 0) {
		d.sub("Тип защитного покрытия: плиты огнезащитные ТЕХНО ОЗМ и ТЕХНО ОЗБ")
		d.para("Объём (м³) огнезащитных плит определяется по формуле:")
		d.Para("center", docxRun{Text: "V = δ · S", Ital: true, Font: "Times New Roman", Size: 11})
		d.para("где δ — толщина огнезащиты (определено в предыдущем разделе), S — площадь огнезащитных плит. Для металлоконструкций площадь огнезащитных плит S, а также площади нанесения клея и декоративного покрытия определяем согласно таблицы 6.")
		d.caption("Таблица 6.")
		w6 := []float64{40, 45, 40, 45}
		rows6 := [][]docxCell{
			d.tableHead(w6, "Конфигурация огнезащиты", "площадь огнезащитных плит S", "площадь под нанесение клея", "декоративное покрытие"),
			{{Runs: []docxRun{{Text: "Формулы для расчета", Bold: true, Size: 8}}, Span: 4, Fill: "FAFAFA"}},
			{{Text: "короб"}, {Text: "(P + Zδ)L + 0,1A·(h − 2t)L/0,6, где A = □← + □→ для двутавров"}, {Text: "(P + Zδ)L"}, {Text: "(P + 2Zδ)L"}},
			{{Text: "контур"}, {Text: "(P + Zδ)L"}, {Text: "(P + Zδ)L"}, {Text: "(P + 2Zδ)L"}},
		}
		d.Table(w6, rows6)
		d.para("Здесь P — периметр принятых к защите сторон элемента:")
		d.Para("center", docxRun{Text: "P = (□← + □→)h + (□↓ + □←)b", Ital: true, Font: "Times New Roman", Size: 11})
		d.para("Z — сумма углов, подверженных обогреву.")
		d.para("Результаты расчета занесены в таблицу 7.")
		d.caption("Таблица 7.")
		widths := []float64{7, 36, 12, 20, 16, 12, 16, 18, 18}
		rows := [][]docxCell{d.tableHead(widths, "№", "Марка элемента", "L, м", "Конфиг.",
			"S, м²", "δ, мм", "V, м³", "S клея, м²", "S декора, м²")}
		lastGroup, idx := "", 0
		for _, el := range ozm {
			if el.group != lastGroup {
				rows = append(rows, []docxCell{{Runs: []docxRun{{Text: el.group, Bold: true, Size: 8}},
					Span: len(widths), Fill: "FAFAFA"}})
				lastGroup = el.group
				idx = 0
			}
			idx++
			rows = append(rows, []docxCell{
				{Text: strconv.Itoa(idx), Align: "center"}, {Text: el.title},
				{Text: fmtNum(el.res.LengthM, 0), Align: "right"},
				{Text: liningName(el.res.Lining), Align: "center"},
				{Text: fmtNum(el.res.AreaM2, 2), Align: "right"},
				{Text: fmtNum(el.res.Delta, 0), Align: "right"},
				{Text: fmtNum(el.res.Volume, 3), Align: "right"},
				{Text: fmtNum(el.res.AreaM2, 2), Align: "right"},
				{Text: fmtNum(el.res.AreaM2, 2), Align: "right"},
			})
		}
		d.Table(widths, rows)
	}

	if d.beton != nil && d.beton.AreaM2 > 0 {
		delta := d.svc.ozbDelta(d.beton.HtLevel)
		q := d.svc.ozbCoef()
		d.para("Производим расчет для железобетонных конструкций.")
		d.para(fmt.Sprintf("Площадь железобетонных конструкций S = %s м².", fmtNum(d.beton.AreaM2, 0)))
		d.para(fmt.Sprintf("Объем V = %s м · %s м² = %s м³.",
			fmtNum(delta/1000, 2), fmtNum(d.beton.AreaM2, 0), fmtNum(d.beton.AreaM2*delta/1000*q, 3)))
	}

	taikor := d.data.elemsOfCoats("2", "3", "4")
	if len(taikor) > 0 {
		d.sub("Тип защитного покрытия: защитное покрытие TAIKOR")
		d.para("Объём (кг) защитного покрытия TAIKOR определяется по формуле:")
		d.Para("center", docxRun{Text: "M = q · S", Ital: true, Font: "Times New Roman", Size: 11})
		d.para("где q — расход защитного состава для металлических конструкций, S — площадь защищаемых металлических конструкций. Площадь S металлоконструкций определяется в зависимости от периметра принятых к защите сторон элемента Π, а также его длины L:")
		d.Para("center", docxRun{Text: "S = (Π / 1000) · L", Ital: true, Font: "Times New Roman", Size: 11})
		d.para("Результаты расчета занесены в таблицу 8.")
		d.caption("Таблица 8.")
		widths := []float64{7, 32, 12, 16, 16, 42, 18, 18}
		rows := [][]docxCell{d.tableHead(widths, "№", "Марка элемента", "L, м", "Π, мм",
			"S, м²", "Тип защитного покрытия", "q, кг/м²", "M, кг")}
		lastGroup, idx := "", 0
		for _, el := range taikor {
			if el.group != lastGroup {
				rows = append(rows, []docxCell{{Runs: []docxRun{{Text: el.group, Bold: true, Size: 8}},
					Span: len(widths), Fill: "FAFAFA"}})
				lastGroup = el.group
				idx = 0
			}
			idx++
			rates := d.data.taikorMaterials(el)
			fullPerimeter := d.data.fullPerimeter(el) * 1000
			for i, m := range rates {
				area := el.res.AreaM2
				if m.akz {
					area = el.res.AkzAreaM2
				}
				first, title, length, perim := strconv.Itoa(idx), el.title, fmtNum(el.res.LengthM, 0), fmtNum(fullPerimeter, 0)
				if i > 0 {
					first, title, length, perim = "", "", "", ""
				}
				rows = append(rows, []docxCell{
					{Text: first, Align: "center"}, {Text: title},
					{Text: length, Align: "right"}, {Text: perim, Align: "right"},
					{Text: fmtNum(area, 2), Align: "right"}, {Text: m.title},
					{Text: fmtNum(m.rate, 2), Align: "right"}, {Text: fmtNum(area*m.rate, 2), Align: "right"},
				})
			}
		}
		d.Table(widths, rows)
	}
	d.PageBreak()
}

func (d *docxReport) section5() {
	d.heading("5. Итоговая спецификация материалов")
	d.para("Итоговое количество материала для устройства огнезащиты по проекту представлено в таблице 9.")
	d.caption("Таблица 9.")

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
	for _, m := range d.resp.Materials {
		byID[m.ID] = m
	}
	widths := []float64{6, 58, 30, 34, 32}
	rows := [][]docxCell{d.tableHead(widths, "№", "Название материала",
		"Базовое значение", "Коэф. расхода", "Итоговое количество")}
	for _, g := range groups {
		var lines [][]docxCell
		n := 0
		for _, id := range g.ids {
			m, ok := byID[id]
			if !ok {
				continue
			}
			n++
			base, coef := d.data.baseAndCoef(id, m)
			lines = append(lines, []docxCell{
				{Text: strconv.Itoa(n), Align: "center"},
				{Text: d.svc.matTitle(id, m.Title)},
				{Text: base, Align: "right"},
				{Text: coef, Align: "right"},
				{Text: fmt.Sprintf("%s %s", fmtNum(m.Quantity, decimalsFor(m)), m.Unit), Align: "right"},
			})
		}
		if len(lines) == 0 {
			continue
		}
		rows = append(rows, []docxCell{{Runs: []docxRun{{Text: g.title, Bold: true, Size: 8}},
			Span: len(widths), Fill: "FAFAFA"}})
		rows = append(rows, lines...)
	}
	d.Table(widths, rows)

	if kver, ok := byID["KVer"]; ok && kver.Quantity > 0 {
		area := safeDiv(kver.Quantity, d.svc.matRate("KVer"))
		d.para(fmt.Sprintf("В качестве декоративного покрытия плит огнезащиты используется материал Штукатурка Ceresit. Данный материал наносится на поверхность минераловатных плит без предварительного нанесения клеевого состава с армирующей сеткой. Расход декоративного покрытия зависит от марки выбранного материала и способа нанесения (1,5–3,2 кг/м²). В расчете принят максимальный ориентировочный расход — 3,2 кг/м². Площадь плит огнезащиты для декоративного покрытия — %s м². Суммарный расход Штукатурка Ceresit — %s кг.",
			fmtNum(area, 2), fmtNum(kver.Quantity, 2)))
	}
	d.PageBreak()
}

func (d *docxReport) literature() {
	d.heading("Список используемой литературы")
	items := []string{
		"Федеральный закон от 22 июля 2008 г. N 123 ФЗ «Технический регламент о требованиях пожарной безопасности».",
		"Технические условия ТУ.5762-004-74182181-2014. Плиты технические минераловатные, теплоизоляционные ТЕХНО.",
		"ИНСТРУКЦИЯ по расчету фактических пределов огнестойкости стальных конструкций с композицией огнезащитной, выполненной из минераловатных плит ТЕХНО марки «Плита огнезащитная для изоляции конструкций из металла ТЕХНОНИКОЛЬ».",
		"Технологический регламент. Рабочая инструкция композиции огнезащитной для железобетонных конструкций из минераловатных плит ТЕХНО марки «Плита огнезащитная для изоляции конструкций из бетона ТЕХНОНИКОЛЬ». ТУ.5762-004-74182181-2014.",
		"СТО АРСС 1 1251254.001-018-03.",
	}
	for i, it := range items {
		d.Para("left", docxRun{Text: fmt.Sprintf("%d. %s", i+1, it), Size: 9.5})
	}
}

// ---------- приложения ----------

func (d *docxReport) appendices() {
	d.PageBreak()
	d.heading("Приложение A. Устройство огнезащиты конструкции")
	for _, p := range d.data.appendixUzly() {
		d.appendixPage(p.asset)
	}
	d.PageBreak()
	d.heading("Приложение Б. Сертификаты пожарной безопасности")
	for _, p := range d.data.appendixCerts() {
		d.appendixPage(p.asset)
	}
	d.PageBreak()
	d.heading("Приложение В. Технические листы")
	for _, p := range d.data.appendixSheets() {
		d.appendixPage(p.asset)
	}
}

// appendixPage — одна страница приложения: скан на всю ширину полосы.
func (d *docxReport) appendixPage(asset string) {
	data, err := appendixFS.ReadFile("assets/appendix/" + asset)
	if err != nil {
		return
	}
	name := "ap-" + strings.NewReplacer(".", "-", "_", "-").Replace(asset)
	// страница A4: ширина полосы набора 170 мм
	d.PageBreak()
	d.ImageSize(name, data, 170, 240, "center")
}

// ---------- таблица 2 и рисунок ----------

// table2Formulas — строки таблицы 2: схема (подписью), тип сечения, F и Π
// в линейной записи (в PDF те же формулы набраны засечным начертанием).
func table2Formulas() [][4]string {
	return [][4]string{
		{"двутавр, уклон полок", "двутавр с уклоном полок",
			"hs + 2t(b − s)",
			"(←+→)(h − 4t + 2√(((b − s)/2)² + 4t²)) + (↓+←)b"},
		{"двутавр, парал. полки", "двутавр простой",
			"hs + 2t(b − s) + (4 − π)R²",
			"(←+→)(h + b − s − (4 − π)R) + (↓+←)b"},
		{"труба кв.", "труба квадратная",
			"4s(h − 1,43s)",
			"(↓+←+↑+→)(h − 2R) + Σ·πR/2, R = 1,5s"},
		{"труба", "труба",
			"4s(h − s)",
			"(↓+←+↑+→)h"},
	}
}

// chartPNG рисует рисунок 1 (предел огнестойкости от приведённой толщины
// металла) в PNG: в Word картинкой, как в образце.
func (d *docxReport) chartPNG() ([]byte, error) {
	const w, h = 800, 560
	const left, right, top, bottom = 70, 30, 20, 60
	img := image.NewRGBA(image.Rect(0, 0, w, h))
	draw.Draw(img, img.Bounds(), &image.Uniform{color.White}, image.Point{}, draw.Src)
	plotW, plotH := w-left-right, h-top-bottom
	x0, y0 := left, top+plotH

	set := func(x, y int, c color.Color) {
		if x >= 0 && x < w && y >= 0 && y < h {
			img.Set(x, y, c)
		}
	}
	hline := func(y int, c color.Color) {
		for x := x0; x <= x0+plotW; x++ {
			set(x, y, c)
		}
	}
	vline := func(x int, c color.Color) {
		for y := top; y <= y0; y++ {
			set(x, y, c)
		}
	}
	gray := color.RGBA{120, 120, 120, 255}
	light := color.RGBA{210, 210, 210, 255}
	const maxX, maxY = 50.0, 250.0
	for i := 0; i <= 5; i++ {
		x := x0 + plotW*i/5
		hline(top, light)
		vline(x, light)
	}
	hline(top, gray)
	hline(y0, gray)
	vline(x0, gray)
	vline(x0+plotW, gray)

	// линии толщин: R = factRFor(толщина, δпр)
	for ti, th := range []float64{30, 40, 50, 60, 70, 80, 90} {
		g := 40 + ti*25
		if g > 200 {
			g = 200
		}
		col := color.RGBA{uint8(g), uint8(g), uint8(g), 255}
		px, py, started := 0, 0, false
		for step := 0.0; step <= maxX; step += 0.5 {
			r := d.data.factRFor(th, step)
			if r <= 0 {
				started = false
				continue
			}
			x := x0 + int(float64(plotW)*step/maxX)
			y := y0 - int(float64(plotH)*math.Min(r, maxY)/maxY)
			if started {
				// линия Брезенхэма
				dx, dy := x-px, y-py
				steps := int(math.Abs(float64(dx)))
				if int(math.Abs(float64(dy))) > steps {
					steps = int(math.Abs(float64(dy)))
				}
				for s := 0; s <= steps; s++ {
					t := 0.0
					if steps > 0 {
						t = float64(s) / float64(steps)
					}
					set(px+int(float64(dx)*t), py+int(float64(dy)*t), col)
				}
			}
			px, py, started = x, y, true
		}
	}
	var buf bytes.Buffer
	if err := png.Encode(&buf, img); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

// tableHead — строка заголовка таблицы.
func (d *docxReport) tableHead(widths []float64, titles ...string) []docxCell {
	out := make([]docxCell, 0, len(titles))
	for _, t := range titles {
		out = append(out, docxCell{Runs: []docxRun{{Text: t, Bold: true}}, Align: "center", Fill: "F3F3F3"})
	}
	return out
}
