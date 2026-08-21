package calc

import (
	"fmt"
	"math"
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

func (e *Engine) Calculate(req models.CalcRequest) (models.CalcResponse, error) {
	resp := models.CalcResponse{
		Inputs:    stripPriceEdits(req),
		Elements:  nil,
		Materials: nil,
		Trace:     nil,
	}
	matAgg := map[string]*models.MaterialLine{}

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
			}
		}
	}

	var total int64
	for _, m := range matAgg {
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
	pi := heatedPerimeter(el.Shape, dims, el.Sides)
	dpr := deltaPr(f, pi)
	trace = append(trace, fmt.Sprintf("%s: F=%.0f Π=%.0f δпр=%.1f", elID, f, pi, dpr))

	er := models.ElementResult{
		ID: groupID + "/" + elID, // keep stable path
		GroupID: groupID,
		Title: el.Title,
		Shape: el.Shape,
		F: f, Pi: pi, Dpr: dpr,
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
		er.Exclusion = "АКЗ: требуется ручной ввод состава антикоррозионной защиты"
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
		lines = append(lines, models.MaterialLine{
			ID: "OZM", Title: "ТЕХНО ОЗМ", Unit: "м³", Quantity: er.Volume,
			SourceElementID: elID, SourceGroupID: groupID,
		})
		// glue / plaster / anchors on Sm / Lh
		lh := claddingPerimeter(lining, dims, el.Sides, el.Shape, delta)
		sh := lh / 1000 * el.LengthM
		lines = append(lines,
			models.MaterialLine{ID: "KCer", Title: "Клей Ceresit CT 190", Unit: "кг", Quantity: round3(sm * 1.2 * qtyMul), SourceElementID: elID, SourceGroupID: groupID},
			models.MaterialLine{ID: "KVer", Title: "Штукатурка Ceresit", Unit: "кг", Quantity: round3(sh * 3.2 * qtyMul), SourceElementID: elID, SourceGroupID: groupID},
			models.MaterialLine{ID: "KAnk", Title: "Металлический анкер с шайбой", Unit: "шт", Quantity: round3(sm * 7 * qtyMul), SourceElementID: elID, SourceGroupID: groupID},
		)
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
	lines = append(lines, models.MaterialLine{
		ID: fmt.Sprintf("Taikor_%s", el.Coat), Title: title, Unit: "кг", Quantity: er.Volume,
		SourceElementID: elID, SourceGroupID: groupID,
	})
	if heat != nil {
		heatMass := round3(s * heat.Rate * tq * qtyMul)
		lines = append(lines, models.MaterialLine{
			ID: "Taikor_Extra", Title: "TAIKOR FP Extra", Unit: "кг", Quantity: heatMass,
			SourceElementID: elID, SourceGroupID: groupID,
		})
	}
	if el.Primer {
		lines = append(lines, models.MaterialLine{
			ID: "T150p", Title: "TAIKOR Primer 150", Unit: "кг", Quantity: round3(s * 0.230 * qtyMul),
			SourceElementID: elID, SourceGroupID: groupID,
		})
	}
	if el.Enamel {
		lines = append(lines, models.MaterialLine{
			ID: "T425t", Title: "TAIKOR Top 425", Unit: "кг", Quantity: round3(s * 0.170 * qtyMul),
			SourceElementID: elID, SourceGroupID: groupID,
		})
	}
	trace = append(trace, fmt.Sprintf("%s: TAIKOR δ=%.2f rate=%.3f mass=%.3f", elID, delta, rate, er.Volume))
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
		{ID: "OZB", Title: title, Unit: "м³", Quantity: round3(vol)},
		{ID: "KVer", Title: "Штукатурка Ceresit", Unit: "кг", Quantity: round3(b.AreaM2 * 3.2)},
		{ID: "KAnk", Title: "Металлический анкер с шайбой", Unit: "шт", Quantity: round3(b.AreaM2 * 7)},
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
	return dims
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
