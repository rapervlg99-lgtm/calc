package export

import (
	"fmt"
	"math"
	"strings"

	"github.com/xuri/excelize/v2"

	"ozm/backend/internal/models"
)

// Спецификация в формате Excel по легаси-отчёту «ИК ozm-calc»: лист на систему
// (TAIKOR по покрытию, АКЗ, ТЕХНО ОЗМ+ОЗБ), блок цен материалов, многоуровневая
// шапка с номерами колонок, группы конструкций, строки элементов с ТСП и
// расходом каждого материала, коэффициентом потерь, теоретическим и практическим
// расходом и стоимостью, строка «ИТОГО» с суммами.
//
// Отличия от легаси-файла: нет логотипа и QR-кода в шапке (в проекте нет этих
// ресурсов), у листа TAIKOR одна колонка площади — наш движок считает огнезащиту
// и АКЗ по одной и той же площади обогрева.

const (
	kindTaikor = "taikor"
	kindAkz    = "akz"
	kindOzm    = "ozm"

	rowPriceTitle = 7  // строка «Стоимость единицы материала:»
	priceStart    = 8  // первая строка блока цен
	headerLevels  = 3  // уровней в шапке таблицы
)

// rateCell — расход материала по элементу: ТСП (толщина сухого слоя, мм; для плит
// — толщина плиты) и расход на м² (кг/м², для плит — м³/м²).
type rateCell struct {
	Tsp  float64
	Rate float64
}

// reportRow — строка спецификации.
type reportRow struct {
	Group   string
	Title   string
	Profile string
	Length  float64
	Ptm     float64
	Limit   string
	Lining  string
	Area    float64
	Rates   map[string]rateCell
	Coef    float64
	Beton   bool
}

// sheetData — лист спецификации.
type sheetData struct {
	Name string
	Kind string
	Mats []string
	Rows []reportRow
}

func systemTitle(kind string) string {
	switch kind {
	case kindTaikor, kindAkz:
		return "T.M. TAIKOR"
	default:
		return "ТЕХНО ОЗ"
	}
}

func reportTitle(resp models.CalcResponse, system string) string {
	addr := strings.TrimSpace(resp.Inputs.Address)
	obj := strings.TrimSpace(resp.Inputs.ObjectName)
	switch {
	case obj != "" && addr != "":
		return fmt.Sprintf("СПЕЦИФИКАЦИЯ материалов %s. Объект «%s», адрес «%s»", system, obj, addr)
	case addr != "":
		return fmt.Sprintf("СПЕЦИФИКАЦИЯ материалов %s. Адрес «%s»", system, addr)
	case obj != "":
		return fmt.Sprintf("СПЕЦИФИКАЦИЯ материалов %s. Объект «%s»", system, obj)
	default:
		return fmt.Sprintf("СПЕЦИФИКАЦИЯ материалов %s", system)
	}
}

// buildSheets раскладывает элементы расчёта по листам систем.
func (s *Service) buildSheets(resp models.CalcResponse) []sheetData {
	var out []sheetData
	at := map[string]int{}
	ensure := func(key, name, kind string) *sheetData {
		if i, ok := at[key]; ok {
			return &out[i]
		}
		out = append(out, sheetData{Name: name, Kind: kind})
		at[key] = len(out) - 1
		return &out[len(out)-1]
	}

	flat := 0
	for gi, g := range resp.Inputs.Groups {
		group := strings.TrimSpace(g.Title)
		if group == "" {
			group = fmt.Sprintf("Группа элементов %d", gi+1)
		}
		for ei, el := range g.Elements {
			res := models.ElementResult{}
			if flat < len(resp.Elements) {
				res = resp.Elements[flat]
			}
			flat++

			row := reportRow{
				Group: group, Title: elementTitle(el, ei), Profile: s.profileLabel(el),
				Length: el.LengthM, Ptm: res.Dpr, Area: res.AreaM2,
				Rates: map[string]rateCell{},
			}
			if el.HtLevel > 0 {
				row.Limit = fmt.Sprintf("R%.0f", el.HtLevel)
			}

			switch coatN := parseCoatN(el.Coat); {
			case coatN == 1:
				sh := ensure("ozm", "ТЕХНО ОЗМ+ОЗБ", kindOzm)
				row.Lining = liningName(res.Lining)
				row.Coef = s.ozmCoef()
				row.Rates["OZM"] = rateCell{Tsp: res.Delta, Rate: res.Delta / 1000}
				row.Rates["KCer"] = rateCell{Rate: s.matRate("KCer")}
				if el.Decor {
					row.Rates["KVer"] = rateCell{Rate: s.matRate("KVer")}
				}
				row.Rates["KAnk"] = rateCell{Rate: s.matRate("KAnk")}
				sh.Rows = append(sh.Rows, row)
			case coatN == 1.5:
				sh := ensure("akz", "АКЗ материалы TAIKOR", kindAkz)
				row.Coef = s.taikorCoef()
				s.addAkzRates(row.Rates, el)
				sh.Rows = append(sh.Rows, row)
			default:
				sh := ensure("taikor:"+el.Coat, sheetName(s.coatTitle(el.Coat)), kindTaikor)
				row.Coef = s.taikorCoef()
				if r, ok := s.taikorRate(el, res.Delta); ok {
					row.Rates["Taikor_"+el.Coat] = r
				}
				if heat, ok := s.taikorHeat(el); ok {
					row.Rates["Taikor_Extra"] = rateCell{Tsp: heat.Delta, Rate: heat.Rate}
				}
				s.addAkzRates(row.Rates, el)
				sh.Rows = append(sh.Rows, row)
			}
		}
	}

	// Бетонные конструкции — отдельным блоком листа ТЕХНО ОЗМ+ОЗБ.
	if b := resp.Inputs.Beton; b != nil && b.AreaM2 > 0 {
		sh := ensure("ozm", "ТЕХНО ОЗМ+ОЗБ", kindOzm)
		delta := s.ozbDelta(b.HtLevel)
		sh.Rows = append(sh.Rows, reportRow{
			Group: "Бетонные конструкции", Title: "Участок",
			Limit: fmt.Sprintf("R%.0f", b.HtLevel), Area: b.AreaM2, Coef: s.ozbCoef(), Beton: true,
			Rates: map[string]rateCell{
				"OZB":  {Tsp: delta, Rate: delta / 1000},
				"KVer": {Rate: s.matRate("KVer")},
				"KAnk": {Rate: s.matRate("KAnk")},
			},
		})
	}

	for i := range out {
		out[i].Mats = s.sheetMaterials(out[i])
	}
	return out
}

// addAkzRates — грунт и финиш по флагам элемента (материалы АКЗ/финиша TAIKOR).
func (s *Service) addAkzRates(rates map[string]rateCell, el models.ElementInput) {
	if el.Primer {
		rates["T150p"] = rateCell{Tsp: s.matLayer("T150p"), Rate: s.matRate("T150p")}
	}
	if el.Enamel {
		rates["T425t"] = rateCell{Tsp: s.matLayer("T425t"), Rate: s.matRate("T425t")}
	}
}

// sheetMaterials — материалы листа в порядке колонок.
func (s *Service) sheetMaterials(sh sheetData) []string {
	used := map[string]bool{}
	for _, r := range sh.Rows {
		for id := range r.Rates {
			used[id] = true
		}
	}
	pick := func(ids ...string) []string {
		out := make([]string, 0, len(ids))
		for _, id := range ids {
			if used[id] {
				out = append(out, id)
			}
		}
		return out
	}
	switch sh.Kind {
	case kindOzm:
		return append(pick("OZM", "OZB"), pick("KCer", "KVer", "KAnk")...)
	case kindAkz:
		return pick("T150p", "T425t")
	default:
		var fire []string
		for _, r := range sh.Rows {
			for _, id := range []string{"Taikor_2", "Taikor_3", "Taikor_4", "Taikor_Extra"} {
				if _, ok := r.Rates[id]; ok && !contains(fire, id) {
					fire = append(fire, id)
				}
			}
		}
		out := pick("T150p")
		out = append(out, fire...)
		return append(out, pick("T425t")...)
	}
}

func contains(list []string, v string) bool {
	for _, x := range list {
		if x == v {
			return true
		}
	}
	return false
}

// sheetName — имя листа: без «TAIKOR » (лимит Excel — 31 символ).
func sheetName(label string) string {
	name := strings.ReplaceAll(label, "TAIKOR ", "")
	name = strings.ReplaceAll(name, "TAIKOR", "")
	name = strings.TrimSpace(strings.ReplaceAll(name, "  ", " "))
	if name == "" {
		name = "FP"
	}
	full := "Taikor " + name
	if runes := []rune(full); len(runes) > 31 {
		full = string(runes[:31])
	}
	return full
}

// ---------- доступ к справочникам ----------

func parseCoatN(coat string) float64 {
	switch strings.TrimSpace(coat) {
	case "1.5":
		return 1.5
	case "2":
		return 2
	case "3":
		return 3
	case "4":
		return 4
	}
	return 1
}

func (s *Service) mat(id string) *models.MaterialRT {
	for i := range s.cfg.Materials {
		if s.cfg.Materials[i].ID == id {
			return &s.cfg.Materials[i]
		}
	}
	return nil
}

func (s *Service) matTitle(id, fallback string) string {
	// В справочнике один «TAIKOR FP» на все составы, а в спецификации состав
	// называется по покрытию: FP Epoxy / FP Graphite / FP Extra.
	switch id {
	case "Taikor_2":
		return "TAIKOR FP Epoxy"
	case "Taikor_3", "Taikor_4":
		return "TAIKOR FP Graphite"
	case "Taikor_Extra":
		return "TAIKOR FP Extra"
	}
	if m := s.mat(id); m != nil && m.Title != "" {
		return m.Title
	}
	return fallback
}

// matRate — расход на м² с учётом минимального расхода q_min.
func (s *Service) matRate(id string) float64 {
	m := s.mat(id)
	if m == nil {
		return 0
	}
	if m.QMin > m.Rate {
		return m.QMin
	}
	return m.Rate
}

func (s *Service) matLayer(id string) float64 {
	if m := s.mat(id); m != nil {
		return m.LayerMm
	}
	return 0
}

func (s *Service) matUnit(id, fallback string) string {
	if m := s.mat(id); m != nil && m.Unit != "" {
		return m.Unit
	}
	return fallback
}

func (s *Service) coatTitle(coat string) string {
	for _, c := range s.cfg.Selects["fr_coat"] {
		if c.Value == coat {
			return c.Label
		}
	}
	return "TAIKOR"
}

// profileLabel — тип профиля: марка проката, иначе форма.
func (s *Service) profileLabel(el models.ElementInput) string {
	if el.RollID != "" {
		for _, r := range s.cfg.Roll {
			if r.ID == el.RollID && r.Label != "" {
				return r.Label
			}
		}
	}
	return el.Shape
}

// taikorRate — расход состава TAIKOR: строка x500, из которой движок взял
// толщину (delta), даёт и расход кг/м².
func (s *Service) taikorRate(el models.ElementInput, delta float64) (rateCell, bool) {
	coat := int(parseCoatN(el.Coat))
	for _, c := range s.cfg.X500 {
		if c.Index != coat {
			continue
		}
		for _, col := range c.Columns {
			if col.Min != el.HtLevel || len(col.Rows) == 0 {
				continue
			}
			best := col.Rows[0]
			bestDiff := math.Abs(best.Delta - delta)
			for _, row := range col.Rows {
				if math.Abs(row.Delta-delta) < 1e-6 {
					return rateCell{Tsp: row.Delta, Rate: row.Rate}, true
				}
				if d := math.Abs(row.Delta - delta); d < bestDiff {
					best, bestDiff = row, d
				}
			}
			return rateCell{Tsp: best.Delta, Rate: best.Rate}, true
		}
	}
	return rateCell{}, false
}

// taikorHeat — дополнительный состав (TAIKOR FP Extra) для coat 4.
func (s *Service) taikorHeat(el models.ElementInput) (models.X500Row, bool) {
	coat := int(parseCoatN(el.Coat))
	for _, c := range s.cfg.X500 {
		if c.Index != coat {
			continue
		}
		for _, col := range c.Columns {
			if col.Min == el.HtLevel && col.Heat != nil {
				return *col.Heat, true
			}
		}
	}
	return models.X500Row{}, false
}

func (s *Service) ozmCoef() float64 {
	if s.cfg.Config.OzmQ > 0 {
		return s.cfg.Config.OzmQ
	}
	return 1.25
}

func (s *Service) taikorCoef() float64 {
	if s.cfg.Config.TaikorQ > 0 {
		return s.cfg.Config.TaikorQ
	}
	return 1.43
}

func (s *Service) ozbCoef() float64 {
	if s.cfg.Config.OzbQ > 0 {
		return s.cfg.Config.OzbQ
	}
	return 1.03
}

func (s *Service) ozbDelta(r float64) float64 {
	if d, ok := s.cfg.Config.OzbByR[fmt.Sprintf("%.0f", r)]; ok {
		return d
	}
	if r >= 240 {
		return 40
	}
	return 50
}

func elementTitle(el models.ElementInput, ei int) string {
	if t := strings.TrimSpace(el.Title); t != "" {
		return t
	}
	return fmt.Sprintf("Элемент %d", ei+1)
}

func liningName(lining int) string {
	switch lining {
	case 1:
		return "короб"
	case 2:
		return "контур"
	case 3:
		return "по трубе"
	}
	return ""
}

// ---------- колонки листа ----------

type reportColumn struct {
	key   string
	group string // верхний уровень шапки (объединяется по колонкам)
	sub   string // средний уровень (например, материал)
	leaf  string // нижний уровень
	width float64
}

// pair — пара колонок материала «ТСП, мм» и «Расход, кг/м²».
func pair(id, group, sub string, width float64) []reportColumn {
	return []reportColumn{
		{key: "tsp:" + id, group: group, sub: sub, leaf: "ТСП, мм", width: width},
		{key: "rate:" + id, group: group, sub: sub, leaf: "Расход, кг/м²", width: width},
	}
}

func columnsFor(sh sheetData, s *Service) []reportColumn {
	cols := []reportColumn{
		{key: "n", leaf: "№", width: 2.9},
		{key: "elem", leaf: "Элемент", width: 29},
		{key: "profile", leaf: "Тип профиля", width: 14.9},
		{key: "len", leaf: "Длина элемента, м", width: 11.5},
		{key: "ptm", leaf: "ПТМ, мм", width: 7.3},
	}
	switch sh.Kind {
	case kindOzm:
		cols = append(cols,
			reportColumn{key: "r", leaf: "Требуемый предел огнестойкости", width: 14},
			reportColumn{key: "lining", leaf: "Конфигурация ОЗ", width: 14},
			reportColumn{key: "area", leaf: "Общая площадь покрытия, м²", width: 15.3},
		)
		if contains(sh.Mats, "OZM") {
			const g = "ОГЗ материалы Т.М. ТЕХНО"
			cols = append(cols,
				reportColumn{key: "tsp:OZM", group: g, sub: "ТЕХНО ОЗМ", leaf: "ТСП, мм", width: 9.7},
				reportColumn{key: "v:OZM", group: g, sub: "ТЕХНО ОЗМ", leaf: "V, м³/м²", width: 9.1},
				reportColumn{key: "coef:OZM", group: g, sub: "ТЕХНО ОЗМ", leaf: "Коэф. расхода", width: 9.1},
			)
		}
		if contains(sh.Mats, "OZB") {
			const g = "ОГЗ материалы Т.М. ТЕХНО"
			cols = append(cols,
				reportColumn{key: "tsp:OZB", group: g, sub: "ТЕХНО ОЗБ", leaf: "ТСП, мм", width: 9.7},
				reportColumn{key: "v:OZB", group: g, sub: "ТЕХНО ОЗБ", leaf: "V, м³/м²", width: 9.1},
				reportColumn{key: "coef:OZB", group: g, sub: "ТЕХНО ОЗБ", leaf: "Коэф. расхода", width: 9.1},
			)
		}
		const decor = "Материал декоративной отделки, клей, анкеры"
		if contains(sh.Mats, "KCer") {
			cols = append(cols,
				reportColumn{key: "sarse:KCer", group: decor, sub: "Клей Ceresit CT 190", leaf: "S нанесения, м²", width: 12.5},
				reportColumn{key: "rate:KCer", group: decor, sub: "Клей Ceresit CT 190", leaf: "Расход", width: 9.4},
			)
		}
		if contains(sh.Mats, "KVer") {
			cols = append(cols,
				reportColumn{key: "sarse:KVer", group: decor, sub: "Штукатурка Ceresit", leaf: "S декор. покр., м²", width: 13.5},
				reportColumn{key: "rate:KVer", group: decor, sub: "Штукатурка Ceresit", leaf: "Расход", width: 9.4},
			)
		}
		if contains(sh.Mats, "KAnk") {
			cols = append(cols, reportColumn{key: "rate:KAnk", group: decor, sub: "Металлический анкер с шайбой", leaf: "Расход", width: 15})
		}
		for _, id := range sh.Mats {
			cols = append(cols, reportColumn{
				key: "sum:" + id, group: "Расход материалов на всю площадь",
				leaf: fmt.Sprintf("%s, %s", s.matTitle(id, id), s.matUnit(id, "")), width: 14.6,
			})
		}
		for _, id := range sh.Mats {
			cols = append(cols, reportColumn{
				key: "price:" + id, group: "Стоимость материалов на всю площадь",
				leaf: fmt.Sprintf("%s, руб", s.matTitle(id, id)), width: 13.3,
			})
		}
	case kindAkz:
		cols = append(cols, reportColumn{key: "area", leaf: "Площадь покрытия, м²", width: 15.3})
		for _, id := range sh.Mats {
			cols = append(cols, pair(id, s.matTitle(id, id), "", 9.9)...)
		}
		cols = append(cols, reportColumn{key: "coef", leaf: "Коэффициент потерь", width: 11.5})
		for _, id := range sh.Mats {
			cols = append(cols, reportColumn{key: "sum:" + id, group: "Теоретический расход материалов TAIKOR на всю площадь (3)", leaf: fmt.Sprintf("%s, кг", s.matTitle(id, id)), width: 18.1})
		}
		for _, id := range sh.Mats {
			cols = append(cols, reportColumn{key: "prac:" + id, group: "Практический расход материалов TAIKOR на всю площадь (3)", leaf: fmt.Sprintf("%s, кг", s.matTitle(id, id)), width: 18.1})
		}
		for _, id := range sh.Mats {
			cols = append(cols, reportColumn{key: "price:" + id, group: "Стоимость материалов Т.М. TAIKOR на всю площадь", leaf: fmt.Sprintf("%s, руб", s.matTitle(id, id)), width: 17.1})
		}
	default:
		cols = append(cols,
			reportColumn{key: "r", leaf: "Требуемый предел огнестойкости", width: 14},
			reportColumn{key: "area", leaf: "Площадь покрытия, м²", width: 15.3},
		)
		var akz, fire, finish []string
		for _, id := range sh.Mats {
			switch {
			case id == "T150p":
				akz = append(akz, id)
			case id == "T425t":
				finish = append(finish, id)
			default:
				fire = append(fire, id)
			}
		}
		for _, id := range akz {
			cols = append(cols, pair(id, "АКЗ материалы Т.М. TAIKOR", s.matTitle(id, id), 9.9)...)
		}
		for _, id := range fire {
			cols = append(cols, pair(id, "ОГЗ материалы Т.М. TAIKOR", s.matTitle(id, id), 9.1)...)
		}
		for _, id := range finish {
			cols = append(cols, pair(id, "Финишное покрытие Т.М. TAIKOR (2)", s.matTitle(id, id), 9.1)...)
		}
		cols = append(cols, reportColumn{key: "coef", leaf: "Коэффициент потерь", width: 11.5})
		for _, id := range sh.Mats {
			cols = append(cols, reportColumn{key: "sum:" + id, group: "Теоретический расход материалов TAIKOR на всю площадь (3)", leaf: fmt.Sprintf("%s, кг", s.matTitle(id, id)), width: 13.1})
		}
		for _, id := range sh.Mats {
			cols = append(cols, reportColumn{key: "prac:" + id, group: "Практический расход материалов TAIKOR на всю площадь (3)", leaf: fmt.Sprintf("%s, кг", s.matTitle(id, id)), width: 13.1})
		}
		for _, id := range sh.Mats {
			cols = append(cols, reportColumn{key: "price:" + id, group: "Стоимость материалов Т.М. TAIKOR на всю площадь", leaf: fmt.Sprintf("%s, руб", s.matTitle(id, id)), width: 13.1})
		}
	}
	return cols
}

// colLetter — буква колонки по номеру (1 → A).
func colLetter(n int) string {
	name, _ := excelize.ColumnNumberToName(n)
	return name
}

// cell — адрес ячейки.
func cell(col string, row int) string { return fmt.Sprintf("%s%d", col, row) }

// ---------- запись листа ----------

func (s *Service) writeSheet(f *excelize.File, sh sheetData, resp models.CalcResponse) error {
	cols := columnsFor(sh, s)
	if len(sh.Mats) == 0 || len(cols) == 0 {
		return nil
	}

	// ширины колонок
	for i, c := range cols {
		letter := colLetter(i + 1)
		if err := f.SetColWidth(sh.Name, letter, letter, c.width); err != nil {
			return err
		}
	}

	// блок цен материалов: цена — редактируемое значение, формулы на неё ссылаются
	priceRow := map[string]int{}
	if err := f.SetCellValue(sh.Name, cell("B", rowPriceTitle), "Стоимость единицы материала:"); err != nil {
		return err
	}
	for i, id := range sh.Mats {
		r := priceStart + i
		priceRow[id] = r
		_ = f.SetCellValue(sh.Name, cell("B", r), s.matTitle(id, id))
		_ = f.SetCellValue(sh.Name, cell("C", r), 0)
		_ = f.SetCellValue(sh.Name, cell("D", r), "/"+s.matUnit(id, "кг"))
	}

	// заголовок листа и границы шапки
	titleRow := priceStart + len(sh.Mats) + 1
	headerTop := titleRow + 2
	numRow := headerTop + headerLevels
	dataStart := numRow + 1
	if err := f.SetCellValue(sh.Name, cell(colLetter(minInt(6, len(cols))), titleRow), reportTitle(resp, systemTitle(sh.Kind))); err != nil {
		return err
	}

	// шапка: группы, подгруппы, листья + объединения
	mergeRow := func(top, bottom int, fromCol, toCol int) {
		if top == bottom && fromCol == toCol {
			return
		}
		_ = f.MergeCell(sh.Name, cell(colLetter(fromCol), top), cell(colLetter(toCol), bottom))
	}
	i := 0
	for i < len(cols) {
		c := cols[i]
		start := i
		if c.group != "" {
			j := i
			for j+1 < len(cols) && cols[j+1].group == c.group {
				j++
			}
			_ = f.SetCellValue(sh.Name, cell(colLetter(start+1), headerTop), c.group)
			mergeRow(headerTop, headerTop, start+1, j+1)
			i = j + 1
			continue
		}
		// простая колонка: шапка на все уровни
		_ = f.SetCellValue(sh.Name, cell(colLetter(start+1), headerTop), c.leaf)
		mergeRow(headerTop, headerTop+headerLevels-1, start+1, start+1)
		i++
	}
	i = 0
	for i < len(cols) {
		c := cols[i]
		if c.group == "" {
			i++
			continue
		}
		if c.sub == "" {
			// группа с листом без подгруппы: лист на два нижних уровня
			_ = f.SetCellValue(sh.Name, cell(colLetter(i+1), headerTop+1), c.leaf)
			mergeRow(headerTop+1, headerTop+headerLevels-1, i+1, i+1)
			i++
			continue
		}
		j := i
		for j+1 < len(cols) && cols[j+1].group == c.group && cols[j+1].sub == c.sub {
			j++
		}
		_ = f.SetCellValue(sh.Name, cell(colLetter(i+1), headerTop+1), c.sub)
		mergeRow(headerTop+1, headerTop+1, i+1, j+1)
		for k := i; k <= j; k++ {
			_ = f.SetCellValue(sh.Name, cell(colLetter(k+1), headerTop+2), cols[k].leaf)
		}
		i = j + 1
	}

	// номера колонок
	for idx := range cols {
		_ = f.SetCellValue(sh.Name, cell(colLetter(idx+1), numRow), idx+1)
	}

	// строки: группы, элементы, ИТОГО
	row := dataStart
	lastGroup := ""
	index := 0
	for _, r := range sh.Rows {
		if r.Group != "" && r.Group != lastGroup {
			_ = f.SetCellValue(sh.Name, cell("B", row), r.Group)
			lastGroup = r.Group
			row++
		}
		index++
		if err := s.writeRow(f, sh, cols, r, index, row, priceRow); err != nil {
			return err
		}
		row++
	}
	totalRow := row
	_ = f.SetCellValue(sh.Name, cell("B", totalRow), "ИТОГО:")
	for idx, c := range cols {
		if !strings.HasPrefix(c.key, "sum:") && !strings.HasPrefix(c.key, "prac:") && !strings.HasPrefix(c.key, "price:") {
			continue
		}
		letter := colLetter(idx + 1)
		_ = f.SetCellFormula(sh.Name, cell(letter, totalRow), fmt.Sprintf("SUM(%s%d:%s%d)", letter, dataStart, letter, totalRow-1))
	}

	// оформление
	if err := s.styleSheet(f, sh, cols, titleRow, headerTop, numRow, dataStart, totalRow); err != nil {
		return err
	}

	// печать: как в легаси-файле — А4, альбом, поля 0.25
	paper, landscape := 9, "landscape"
	// вписываем таблицу в один лист по ширине — как печатается легаси-отчёт
	one, zero := 1, 0
	_ = f.SetPageLayout(sh.Name, &excelize.PageLayoutOptions{
		Size: &paper, Orientation: &landscape, FitToWidth: &one, FitToHeight: &zero,
	})
	m := 0.25
	_ = f.SetPageMargins(sh.Name, &excelize.PageLayoutMarginsOptions{
		Left: &m, Right: &m, Top: &m, Bottom: &m, Header: &m, Footer: &m,
	})
	return nil
}

func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}

// styleSheet оформляет лист: шрифт Times New Roman, тонкие рамки, перенос в
// шапке, числовые форматы по смыслу колонки, жирные шапка и ИТОГО.
func (s *Service) styleSheet(f *excelize.File, sh sheetData, cols []reportColumn, titleRow, headerTop, numRow, dataStart, totalRow int) error {
	tnr := func(size float64, bold bool) *excelize.Font {
		return &excelize.Font{Family: "Times New Roman", Size: size, Bold: bold}
	}
	thin := []excelize.Border{
		{Type: "left", Color: "000000", Style: 1},
		{Type: "right", Color: "000000", Style: 1},
		{Type: "top", Color: "000000", Style: 1},
		{Type: "bottom", Color: "000000", Style: 1},
	}
	last := colLetter(len(cols))

	// заголовок листа
	titleStyle, err := f.NewStyle(&excelize.Style{Font: tnr(12, true), Alignment: &excelize.Alignment{Vertical: "center"}})
	if err != nil {
		return err
	}
	_ = f.SetCellStyle(sh.Name, cell("A", titleRow), cell(last, titleRow), titleStyle)

	// блок цен: подпись и строки материалов
	priceTitleStyle, err := f.NewStyle(&excelize.Style{Font: tnr(11, true)})
	if err != nil {
		return err
	}
	_ = f.SetCellStyle(sh.Name, cell("B", rowPriceTitle), cell("B", rowPriceTitle), priceTitleStyle)
	priceNameStyle, err := f.NewStyle(&excelize.Style{Font: tnr(11, false), Border: thin, Alignment: &excelize.Alignment{Horizontal: "left", Vertical: "center"}})
	if err != nil {
		return err
	}
	priceValStyle, err := f.NewStyle(&excelize.Style{Font: tnr(11, false), Border: thin, CustomNumFmt: strPtr(`#,##0" ₽"`), Alignment: &excelize.Alignment{Horizontal: "right", Vertical: "center"}})
	if err != nil {
		return err
	}
	unitStyle, err := f.NewStyle(&excelize.Style{Font: tnr(11, false), Border: thin, Alignment: &excelize.Alignment{Vertical: "center"}})
	if err != nil {
		return err
	}
	priceBottom := priceStart + len(sh.Mats) - 1
	_ = f.SetCellStyle(sh.Name, cell("B", priceStart), cell("B", priceBottom), priceNameStyle)
	_ = f.SetCellStyle(sh.Name, cell("C", priceStart), cell("C", priceBottom), priceValStyle)
	_ = f.SetCellStyle(sh.Name, cell("D", priceStart), cell("D", priceBottom), unitStyle)

	// шапка таблицы и строка номеров колонок
	headerStyle, err := f.NewStyle(&excelize.Style{Font: tnr(11, true), Border: thin, Alignment: &excelize.Alignment{Horizontal: "center", Vertical: "center", WrapText: true}})
	if err != nil {
		return err
	}
	_ = f.SetCellStyle(sh.Name, cell("A", headerTop), cell(last, numRow), headerStyle)
	_ = f.SetRowHeight(sh.Name, headerTop, 45)
	_ = f.SetRowHeight(sh.Name, headerTop+1, 40)
	_ = f.SetRowHeight(sh.Name, headerTop+2, 30)

	// данные и ИТОГО: стиль на колонку (числовой формат по смыслу)
	for i, c := range cols {
		letter := colLetter(i + 1)
		format, align := columnFormat(c.key, sh.Kind)
		st, err := f.NewStyle(&excelize.Style{
			Font: tnr(11, false), Border: thin, CustomNumFmt: strPtr(format),
			Alignment: &excelize.Alignment{Horizontal: align, Vertical: "center", WrapText: c.key == "elem" || c.key == "profile"},
		})
		if err != nil {
			return err
		}
		_ = f.SetCellStyle(sh.Name, cell(letter, dataStart), cell(letter, totalRow-1), st)
	}
	// строка ИТОГО — жирная
	for i := range cols {
		letter := colLetter(i + 1)
		format, align := columnFormat(cols[i].key, sh.Kind)
		st, err := f.NewStyle(&excelize.Style{
			Font: tnr(11, true), Border: thin, CustomNumFmt: strPtr(format),
			Alignment: &excelize.Alignment{Horizontal: align, Vertical: "center"},
		})
		if err != nil {
			return err
		}
		_ = f.SetCellStyle(sh.Name, cell(letter, totalRow), cell(letter, totalRow), st)
	}
	// строки групп конструкций — жирные подписи без чисел
	for r := dataStart; r < totalRow; r++ {
		val, err := f.GetCellValue(sh.Name, cell("B", r))
		if err != nil {
			continue
		}
		if strings.HasPrefix(val, "Группа элементов") || val == "Бетонные конструкции" {
			st, err := f.NewStyle(&excelize.Style{Font: tnr(11, true), Border: thin, Alignment: &excelize.Alignment{Horizontal: "left", Vertical: "center"}})
			if err != nil {
				return err
			}
			_ = f.SetCellStyle(sh.Name, cell("A", r), cell(last, r), st)
		}
	}
	return nil
}

func strPtr(v string) *string { return &v }

// columnFormat — числовой формат и выравнивание колонки.
func columnFormat(key, kind string) (string, string) {
	switch {
	case key == "n":
		return "0", "center"
	case key == "elem" || key == "profile" || key == "r" || key == "lining":
		return "@", "left"
	case key == "len":
		return "#,##0.##", "right"
	case key == "ptm":
		return "#,##0.00", "right"
	case key == "area" || strings.HasPrefix(key, "sarse:"):
		return "#,##0.00", "right"
	case strings.HasPrefix(key, "tsp:"):
		return "#,##0.0#", "right"
	case strings.HasPrefix(key, "v:") || strings.HasPrefix(key, "rate:"):
		return "#,##0.00", "right"
	case key == "coef" || strings.HasPrefix(key, "coef:"):
		return "#,##0.00", "right"
	case strings.HasPrefix(key, "sum:"):
		if kind == kindOzm && (key == "sum:OZM" || key == "sum:OZB") {
			return "#,##0.000", "right"
		}
		return "#,##0.00", "right"
	case strings.HasPrefix(key, "prac:"):
		return "#,##0.00", "right"
	case strings.HasPrefix(key, "price:"):
		return `#,##0" ₽"`, "right"
	}
	return "General", "left"
}

// writeRow заполняет строку элемента значениями и формулами.
func (s *Service) writeRow(f *excelize.File, sh sheetData, cols []reportColumn, r reportRow, index, row int, priceRow map[string]int) error {
	at := map[string]string{} // ключ колонки → буква
	for i, c := range cols {
		at[c.key] = colLetter(i + 1)
	}
	coefLetter := at["coef"]
	areaLetter := at["area"]
	put := func(key string, v any) {
		if letter, ok := at[key]; ok {
			_ = f.SetCellValue(sh.Name, cell(letter, row), v)
		}
	}
	put("n", index)
	put("elem", r.Title)
	put("profile", r.Profile)
	put("len", r.Length)
	put("ptm", r.Ptm)
	put("r", r.Limit)
	put("lining", r.Lining)
	put("area", r.Area)

	for id, rate := range r.Rates {
		if _, ok := at["tsp:"+id]; ok {
			put("tsp:"+id, rate.Tsp)
		}
		if _, ok := at["v:"+id]; ok {
			put("v:"+id, rate.Rate)
		}
		if _, ok := at["rate:"+id]; ok {
			put("rate:"+id, rate.Rate)
		}
		if _, ok := at["sarse:"+id]; ok {
			put("sarse:"+id, r.Area)
		}
		if _, ok := at["coef:"+id]; ok {
			put("coef:"+id, r.Coef)
		}
	}
	if coefLetter != "" {
		put("coef", r.Coef)
	}

	// формулы: теоретический расход → практический (TAIKOR/АКЗ) → стоимость
	for id := range r.Rates {
		sumLetter, hasSum := at["sum:"+id]
		if !hasSum {
			continue
		}
		switch {
		case sh.Kind == kindOzm && id == "OZM", sh.Kind == kindOzm && id == "OZB":
			// объём: площадь × V × коэффициент расхода
			vLetter, coefMat := at["v:"+id], at["coef:"+id]
			if areaLetter != "" && vLetter != "" && coefMat != "" {
				_ = f.SetCellFormula(sh.Name, cell(sumLetter, row),
					fmt.Sprintf("ROUND(%s%d*%s%d*%s%d,3)", areaLetter, row, vLetter, row, coefMat, row))
			}
		case sh.Kind == kindOzm && (id == "KCer" || id == "KVer"):
			// клей и штукатурка: площадь нанесения × расход
			sLetter, rateLetter := at["sarse:"+id], at["rate:"+id]
			if sLetter != "" && rateLetter != "" {
				_ = f.SetCellFormula(sh.Name, cell(sumLetter, row),
					fmt.Sprintf("ROUND(%s%d*%s%d,2)", sLetter, row, rateLetter, row))
			}
		case sh.Kind == kindOzm && id == "KAnk":
			rateLetter := at["rate:"+id]
			if areaLetter != "" && rateLetter != "" {
				_ = f.SetCellFormula(sh.Name, cell(sumLetter, row),
					fmt.Sprintf("ROUND(%s%d*%s%d,0)", areaLetter, row, rateLetter, row))
			}
		default:
			rateLetter := at["rate:"+id]
			if areaLetter != "" && rateLetter != "" {
				_ = f.SetCellFormula(sh.Name, cell(sumLetter, row),
					fmt.Sprintf("ROUND(%s%d*%s%d,2)", areaLetter, row, rateLetter, row))
			}
		}

		baseLetter := sumLetter
		if pracLetter, ok := at["prac:"+id]; ok && coefLetter != "" {
			_ = f.SetCellFormula(sh.Name, cell(pracLetter, row), fmt.Sprintf("ROUND(%s%d*%s%d,2)", sumLetter, row, coefLetter, row))
			baseLetter = pracLetter
		}
		if priceLetter, ok := at["price:"+id]; ok {
			if pr, ok := priceRow[id]; ok {
				_ = f.SetCellFormula(sh.Name, cell(priceLetter, row), fmt.Sprintf("%s%d*$C$%d", baseLetter, row, pr))
			}
		}
	}
	return nil
}
