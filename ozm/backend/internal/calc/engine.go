package calc

import (
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"

	"ozm/backend/internal/config"
	"ozm/backend/internal/models"
)

type Engine struct {
	cfg *config.Store
}

func New(cfg *config.Store) *Engine {
	return &Engine{cfg: cfg}
}

// material — запись справочника материалов для строки ведомости. Идентификаторы
// TAIKOR идут с суффиксом покрытия (Taikor_2 … Taikor_4) и с «Taikor_Extra»,
// поэтому ищем по базовому имени.
func (e *Engine) material(id string) *models.MaterialRT {
	base := materialBaseID(id)
	for i := range e.cfg.Materials {
		if e.cfg.Materials[i].ID == base {
			return &e.cfg.Materials[i]
		}
	}
	return nil
}

func materialBaseID(id string) string {
	if strings.HasPrefix(id, "Taikor_") {
		return "Taikor"
	}
	return id
}

// rateOf — расход материала на единицу расчётной базы: из справочника, но не
// ниже минимального расхода q_min из легаси-выгрузки (у штукатурки — 1.5).
func rateOf(m *models.MaterialRT) float64 {
	if m == nil {
		return 0
	}
	if m.QMin > m.Rate {
		return m.QMin
	}
	return m.Rate
}

// materialLine собирает строку ведомости: название, единицу, толщину слоя и
// точность печати берём из справочника, количество считает вызывающая сторона.
// title == "" — название из справочника (у ОЗБ оно зависит от предела R).
func (e *Engine) materialLine(id, title, groupID, elID string, qty float64) models.MaterialLine {
	ln := models.MaterialLine{
		ID: id, Title: title, Quantity: qty,
		SourceElementID: elID, SourceGroupID: groupID,
	}
	if m := e.material(id); m != nil {
		if ln.Title == "" {
			ln.Title = m.Title
		}
		ln.Unit = m.Unit
		ln.LayerMm = m.LayerMm
		ln.Decimals = m.Round
	}
	return ln
}

// sortOf — порядок материала в ведомости (DC sort), 0 — без порядка.
func (e *Engine) sortOf(id string) int {
	if m := e.material(id); m != nil {
		return m.Sort
	}
	return 0
}

func (e *Engine) Calculate(req models.CalcRequest) (models.CalcResponse, error) {
	resp := models.CalcResponse{
		Inputs:    stripPriceEdits(req),
		Elements:  nil,
		Materials: nil,
		Trace:     nil,
	}
	matAgg := map[string]*models.MaterialLine{}
	var matOrder []string

	for gi, g := range req.Groups {
		gQty := g.Quantity
		if gQty <= 0 {
			gQty = 1
		}
		gID := g.ID
		if gID == "" {
			gID = fmt.Sprintf("g%d", gi+1)
		}
		for ei, el := range g.Elements {
			elID := el.ID
			if elID == "" {
				elID = fmt.Sprintf("%s-e%d", gID, ei+1)
			}
			er, lines, trace := e.calcElement(gID, elID, el, gQty)
			resp.Elements = append(resp.Elements, er)
			resp.Trace = append(resp.Trace, trace...)
			for _, ln := range lines {
				key := ln.ID
				if existing, ok := matAgg[key]; ok {
					existing.Quantity = round3(existing.Quantity + ln.Quantity)
				} else {
					cp := ln
					matAgg[key] = &cp
					matOrder = append(matOrder, key)
				}
			}
		}
	}

	if req.Beton != nil && req.Beton.AreaM2 > 0 {
		blines, tr := e.calcBeton(*req.Beton)
		resp.Trace = append(resp.Trace, tr...)
		for _, ln := range blines {
			if existing, ok := matAgg[ln.ID]; ok {
				existing.Quantity = round3(existing.Quantity + ln.Quantity)
			} else {
				cp := ln
				matAgg[ln.ID] = &cp
				matOrder = append(matOrder, ln.ID)
			}
		}
	}

	var total int64
	// Порядок ведомости — по справочнику (DC sort): материалы без порядка идут
	// в порядке появления, а внутри одинакового sort сохраняется порядок
	// появления — поэтому собираем по matOrder и сортируем стабильно.
	for _, id := range matOrder {
		m := matAgg[id]
		price := int64(0)
		if req.MaterialPriceEditsCents != nil {
			if p, ok := req.MaterialPriceEditsCents[m.ID]; ok {
				price = p
			}
		}
		m.UnitPriceCents = price
		m.TotalCents = int64(math.Round(m.Quantity * float64(price)))
		total += m.TotalCents
		resp.Materials = append(resp.Materials, *m)
	}
	sort.SliceStable(resp.Materials, func(i, j int) bool {
		return e.sortOf(resp.Materials[i].ID) < e.sortOf(resp.Materials[j].ID)
	})
	resp.Totals = models.Totals{MaterialsCents: total, GrandCents: total}
	return resp, nil
}

func stripPriceEdits(req models.CalcRequest) models.CalcRequest {
	out := req
	out.MaterialPriceEditsCents = nil
	return out
}

func (e *Engine) calcElement(groupID, elID string, el models.ElementInput, groupQty float64) (models.ElementResult, []models.MaterialLine, []string) {
	trace := []string{}
	dims := e.resolveDims(el)
	f := sectionArea(el.Shape, dims)
	if area, ok := e.catalogArea(el, dims); ok {
		f = area
	}
	pi := heatedPerimeter(el.Shape, dims, el.Sides)
	dpr := deltaPr(f, pi)
	trace = append(trace, fmt.Sprintf("%s: F=%.0f Π=%.0f δпр=%.1f", elID, f, pi, dpr))

	// Полный периметр: АКЗ и финишное покрытие наносят по всей поверхности, а
	// огнезащиту считают по нагреваемым сторонам — в спецификации это две
	// разные площади.
	piFull := heatedPerimeter(el.Shape, dims, models.HeatedSides{Left: true, Top: true, Right: true, Bottom: true})
	fullArea := piFull / 1000 * el.LengthM

	er := models.ElementResult{
		ID:      groupID + "/" + elID, // keep stable path
		GroupID: groupID,
		Title:   el.Title,
		Shape:   el.Shape,
		F:       f, Pi: pi, Dpr: dpr,
		Coat: el.Coat, HtLevel: el.HtLevel,
		LengthM: el.LengthM, Quantity: el.Quantity * groupQty,
	}
	er.ID = elID

	coatN := parseCoat(el.Coat)
	lining := liningType(el.Shape, el.Method)
	er.Lining = lining

	var lines []models.MaterialLine
	qtyMul := el.Quantity * groupQty

	if coatN == 1.5 {
		// АКЗ — только антикоррозионная защита: конструкции с ней входят в расчёт
		// (в ведомости видно, сколько красить), но огнезащитный материал для них
		// не считается, и это не ошибка и не исключение. Состав АКЗ вводится
		// вручную, предел огнестойкости для неё не нужен. Площадь — вся
		// поверхность конструкции (полный периметр), её и красят.
		er.AreaM2 = round3(fullArea * qtyMul)
		er.AkzAreaM2 = er.AreaM2
		trace = append(trace, fmt.Sprintf("%s: АКЗ — огнезащитный материал не считается, площадь окраски %.2f м²", elID, er.AreaM2))
		return er, lines, trace
	}

	if el.HtLevel <= 0 {
		er.Exclusion = "не задан предел огнестойкости R — укажите его для огнезащитного покрытия"
		return er, lines, trace
	}

	if coatN <= 1 {
		delta, ok, rFact := lookupT500(e.cfg.T500, dpr, el.HtLevel)
		er.Delta = delta
		if !ok {
			er.Exclusion = fmt.Sprintf("недостижимый предел огнестойкости R%.0f при δпр=%.1f (Rфакт≈%.0f)", el.HtLevel, dpr, rFact)
			return er, lines, trace
		}
		sv, sm := ozmAreas(lining, dims, el.Sides, el.Shape, delta, el.LengthM)
		er.AreaM2 = round3(sm * qtyMul)
		q := e.cfg.Config.OzmQ
		if q == 0 {
			q = 1.25
		}
		vol := sv * (delta / 1000) * q
		er.Volume = round3(vol * qtyMul)
		lines = append(lines, e.materialLine("OZM", "", groupID, elID, er.Volume))
		// клей и анкеры — по площади огнезащиты, штукатурка — по площади
		// облицовки; расход и толщина слоя берутся из справочника материалов
		lh := claddingPerimeter(lining, dims, el.Sides, el.Shape, delta)
		sh := lh / 1000 * el.LengthM
		lines = append(lines, e.materialLine("KCer", "", groupID, elID, round3(sm*rateOf(e.material("KCer"))*qtyMul)))
		// штукатурка — декоративное покрытие: в легаси-выгрузке
		// <KVer type="fr_decor">, поэтому без галочки «Декоративное покрытие»
		// материала в ведомости нет (ОЗБ считается всегда — там флага нет)
		if el.Decor {
			lines = append(lines, e.materialLine("KVer", "", groupID, elID, round3(sh*rateOf(e.material("KVer"))*qtyMul)))
		}
		lines = append(lines, e.materialLine("KAnk", "", groupID, elID, round3(sm*rateOf(e.material("KAnk"))*qtyMul)))
		trace = append(trace, fmt.Sprintf("%s: δ=%.0f lining=%d Sv→V=%.3f", elID, delta, lining, er.Volume))
		return er, lines, trace
	}

	// TAIKOR coats 2/3/4
	delta, rate, heat, ok := lookupX500(e.cfg.X500, int(coatN), el.HtLevel, dpr)
	if !ok {
		er.Exclusion = fmt.Sprintf("нет данных x500 для coat=%s R%.0f δпр=%.1f", el.Coat, el.HtLevel, dpr)
		return er, lines, trace
	}
	er.Delta = delta
	s := pi / 1000 * el.LengthM
	er.AreaM2 = round3(s * qtyMul)
	er.AkzAreaM2 = round3(fullArea * qtyMul)
	tq := e.cfg.Config.TaikorQ
	if tq == 0 {
		tq = 1.43
	}
	mass := s * rate * tq
	er.Volume = round3(mass * qtyMul) // kg stored in Volume for paint
	title := "TAIKOR FP Graphite"
	if coatN == 2 {
		title = "TAIKOR FP Epoxy"
	}
	lines = append(lines, e.materialLine(fmt.Sprintf("Taikor_%s", el.Coat), title, groupID, elID, er.Volume))
	if heat != nil {
		heatMass := round3(s * heat.Rate * tq * qtyMul)
		lines = append(lines, e.materialLine("Taikor_Extra", "TAIKOR FP Extra", groupID, elID, heatMass))
	}
	// Грунт и финиш — по площади окраски (вся поверхность), не по нагреваемой.
	if el.Primer {
		lines = append(lines, e.materialLine("T150p", "", groupID, elID, round3(fullArea*rateOf(e.material("T150p"))*qtyMul)))
	}
	if el.Enamel {
		lines = append(lines, e.materialLine("T425t", "", groupID, elID, round3(fullArea*rateOf(e.material("T425t"))*qtyMul)))
	}
	trace = append(trace, fmt.Sprintf("%s: TAIKOR δ=%.2f rate=%.3f mass=%.3f, S акз=%.2f", elID, delta, rate, er.Volume, er.AkzAreaM2))
	return er, lines, trace
}

func (e *Engine) calcBeton(b models.BetonInput) ([]models.MaterialLine, []string) {
	key := strconv.FormatFloat(b.HtLevel, 'f', 0, 64)
	delta := 50.0
	if e.cfg.Config.OzbByR != nil {
		if d, ok := e.cfg.Config.OzbByR[key]; ok {
			delta = d
		}
	} else if b.HtLevel >= 240 {
		delta = 40
	}
	q := e.cfg.Config.OzbQ
	if q == 0 {
		q = 1.03
	}
	vol := b.AreaM2 * (delta / 1000) * q
	title := "ТЕХНО ОЗБ 80"
	if b.HtLevel >= 240 {
		title = "ТЕХНО ОЗБ 110"
	}
	lines := []models.MaterialLine{
		e.materialLine("OZB", title, "", "", round3(vol)),
		e.materialLine("KVer", "", "", "", round3(b.AreaM2*rateOf(e.material("KVer")))),
		e.materialLine("KAnk", "", "", "", round3(b.AreaM2*rateOf(e.material("KAnk")))),
	}
	return lines, []string{fmt.Sprintf("beton: S=%.2f R%.0f δ=%.0f V=%.3f", b.AreaM2, b.HtLevel, delta, vol)}
}

func (e *Engine) resolveDims(el models.ElementInput) map[string]float64 {
	dims := map[string]float64{}
	for k, v := range el.Dims {
		dims[k] = v
	}
	if el.RollID != "" {
		for _, r := range e.cfg.Roll {
			if r.ID == el.RollID || (r.Shape == el.Shape && r.Label == el.RollID) {
				for k, v := range r.Dims {
					if _, ok := dims[k]; !ok {
						dims[k] = v
					}
				}
				break
			}
		}
	}
	normalizeDims(el.Shape, dims)
	return dims
}

// Imported profiles carry the tabulated area, not an approximation from nominal
// dimensions. Use it only while the selected profile's dimensions are unchanged;
// manual overrides must still be evaluated from their own geometry.
func (e *Engine) catalogArea(el models.ElementInput, dims map[string]float64) (float64, bool) {
	for _, r := range e.cfg.Roll {
		if r.ID != el.RollID || r.Shape != el.Shape || r.Source != "calclab-metalloprokat" || r.AreaMM2 <= 0 {
			continue
		}
		expected := map[string]float64{}
		for k, v := range r.Dims {
			expected[k] = v
		}
		normalizeDims(r.Shape, expected)
		for _, k := range []string{"h", "b", "b1", "s", "t", "tr", "R", "r"} {
			if math.Abs(dims[k]-expected[k]) > 1e-6 {
				return 0, false
			}
		}
		return r.AreaMM2, true
	}
	return 0, false
}

func parseCoat(s string) float64 {
	s = strings.TrimSpace(s)
	v, err := strconv.ParseFloat(s, 64)
	if err != nil {
		return 1
	}
	return v
}

func liningType(shape, method string) int {
	if strings.HasPrefix(shape, "tube_sm") && method == "0" {
		return 3
	}
	if strings.HasPrefix(shape, "brands") || strings.HasPrefix(shape, "corner") {
		return 2
	}
	return 1
}

func deltaPr(f, pi float64) float64 {
	if pi <= 0 {
		return 0
	}
	return round1(f / pi)
}

func round1(v float64) float64 { return math.Round(v*10) / 10 }
func round3(v float64) float64 { return math.Round(v*1000) / 1000 }
func round0(v float64) float64 { return math.Round(v) }
