package calc

import (
	"ozm/backend/internal/models"
)

func lookupT500(rows []models.T500Row, dpr, reqR float64) (delta float64, ok bool, rFact float64) {
	if len(rows) == 0 {
		return 0, false, 0
	}
	rPoints := uniqueBases(rows)
	base := rPoints[0]
	for _, p := range rPoints {
		if p <= dpr {
			base = p
		}
	}
	deltaOff := dpr - base
	type node struct{ minute, thick float64 }
	var nodes []node
	for _, r := range rows {
		if r.BaseDelta != base || r.Thickness == 20 {
			continue
		}
		nodes = append(nodes, node{
			minute: round0(r.A*deltaOff + r.B),
			thick:  r.Thickness,
		})
	}
	if len(nodes) == 0 {
		return 0, false, 0
	}
	rFact = nodes[len(nodes)-1].minute
	best := -1.0
	for _, n := range nodes {
		if n.minute >= reqR {
			if best < 0 || n.thick < best {
				best = n.thick
			}
		}
	}
	if best < 0 {
		return 0, false, rFact
	}
	return best, true, rFact
}

func uniqueBases(rows []models.T500Row) []float64 {
	seen := map[float64]bool{}
	var out []float64
	for _, r := range rows {
		if !seen[r.BaseDelta] {
			seen[r.BaseDelta] = true
			out = append(out, r.BaseDelta)
		}
	}
	// insertion order from file is fine; ensure ascending
	for i := 0; i < len(out); i++ {
		for j := i + 1; j < len(out); j++ {
			if out[j] < out[i] {
				out[i], out[j] = out[j], out[i]
			}
		}
	}
	return out
}

func lookupX500(coats []models.X500Coat, coatN int, reqR, dpr float64) (delta, rate float64, heat *models.X500Row, ok bool) {
	var coat *models.X500Coat
	for i := range coats {
		if coats[i].Index == coatN {
			coat = &coats[i]
			break
		}
	}
	if coat == nil {
		return 0, 0, nil, false
	}
	var col *models.X500RColumn
	for i := range coat.Columns {
		if coat.Columns[i].Min == reqR {
			col = &coat.Columns[i]
			break
		}
	}
	if col == nil || len(col.Rows) == 0 {
		return 0, 0, nil, false
	}
	row := col.Rows[0]
	found := false
	for _, r := range col.Rows {
		if r.Dpr == dpr {
			row = r
			found = true
			break
		}
		if r.Dpr <= dpr {
			row = r
			found = true
		}
	}
	if !found {
		row = col.Rows[len(col.Rows)-1]
	}
	if dpr > col.Rows[len(col.Rows)-1].Dpr {
		row = col.Rows[len(col.Rows)-1]
	}
	return row.Delta, row.Rate, col.Heat, true
}
