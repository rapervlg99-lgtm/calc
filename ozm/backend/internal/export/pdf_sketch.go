package export

import (
	"github.com/jung-kurt/gofpdf"
)

// Схемы сечений для таблицы 2: рисуются линиями, как в легаси-документе
// (там это тоже векторные фигуры). Размеры подписываются буквами h, b, s, t, R.

// drawSection рисует схему сечения kind в прямоугольнике (x, y, w, h).
func drawSection(pdf *gofpdf.Fpdf, x, y, w, h float64, kind string) {
	pdf.SetDrawColor(60, 60, 60)
	pdf.SetLineWidth(0.3)
	switch kind {
	case "ibeam_slope":
		drawIBeam(pdf, x, y, w, h, true)
	case "ibeam":
		drawIBeam(pdf, x, y, w, h, false)
	case "tube_sq":
		drawTube(pdf, x, y, w, h, true)
	default:
		drawTube(pdf, x, y, w, h, false)
	}
	pdf.SetDrawColor(40, 40, 40)
	pdf.SetLineWidth(0.2)
}

// drawIBeam — двутавр: с уклоном полок (slope) или простой, стенка вертикальная.
func drawIBeam(pdf *gofpdf.Fpdf, x, y, w, h float64, slope bool) {
	hh := h * 0.86
	bb := w * 0.60
	tf := hh * 0.14
	tw := bb * 0.15
	cx := x + w/2
	y0 := y + (h-hh)/2
	y1 := y0 + hh
	sl := 0.0
	if slope {
		sl = tf * 0.8 // полка толще у стенки и тоньше к краям
	}
	pts := [][2]float64{
		{cx - bb/2, y0},
		{cx + bb/2, y0},
		{cx + bb/2, y0 + tf},
		{cx + tw/2, y0 + tf + sl},
		{cx + tw/2, y1 - tf - sl},
		{cx + bb/2, y1 - tf},
		{cx + bb/2, y1},
		{cx - bb/2, y1},
		{cx - bb/2, y1 - tf},
		{cx - tw/2, y1 - tf - sl},
		{cx - tw/2, y0 + tf + sl},
		{cx - bb/2, y0 + tf},
	}
	for i := range pts {
		p1, p2 := pts[i], pts[(i+1)%len(pts)]
		pdf.Line(p1[0], p1[1], p2[0], p2[1])
	}

	label := func(s string, lx, ly float64) {
		pdf.SetFont("tns", "I", 6.5)
		pdf.SetXY(lx, ly)
		pdf.CellFormat(6, 3, s, "", 0, "C", false, 0, "")
	}
	pdf.SetLineWidth(0.15)
	pdf.SetDrawColor(150, 150, 150)
	// высота h слева
	pdf.Line(cx-bb/2-2.2, y0, cx-bb/2-2.2, y1)
	pdf.Line(cx-bb/2-3.0, y0, cx-bb/2-1.4, y0)
	pdf.Line(cx-bb/2-3.0, y1, cx-bb/2-1.4, y1)
	label("h", cx-bb/2-6.0, y0+hh/2-1.5)
	// ширина b снизу
	pdf.Line(cx-bb/2, y1+2.2, cx+bb/2, y1+2.2)
	pdf.Line(cx-bb/2, y1+1.4, cx-bb/2, y1+3.0)
	pdf.Line(cx+bb/2, y1+1.4, cx+bb/2, y1+3.0)
	label("b", cx-2, y1+2.1)
	// толщина стенки s
	pdf.Line(cx+tw/2+1.0, y0+hh*0.5, cx+tw/2+3.4, y0+hh*0.5)
	label("s", cx+tw/2+1.9, y0+hh*0.5-3.0)
	// толщина полки t
	pdf.Line(cx+bb/2-1.2, y0+tf/2, cx+bb/2+2.0, y0+tf/2)
	label("t", cx+bb/2+0.8, y0+tf/2-2.8)
	if !slope {
		// внутреннее закругление R
		pdf.Line(cx+tw/2+0.6, y1-tf-1.0, cx+tw/2+3.8, y1-tf-1.0)
		label("R", cx+tw/2+1.9, y1-tf-4.0)
	}
	pdf.SetDrawColor(40, 40, 40)
	pdf.SetLineWidth(0.3)
}

// drawTube — труба: квадратная со скруглением (chamfer) или прямоугольная.
func drawTube(pdf *gofpdf.Fpdf, x, y, w, h float64, rounded bool) {
	side := h * 0.76
	if w*0.78 < side {
		side = w * 0.78
	}
	cx := x + w/2
	cy := y + h/2
	x0, y0 := cx-side/2, cy-side/2
	wall := side * 0.13
	ch := 0.0
	if rounded {
		ch = side * 0.20
	}
	tube := func(px, py, ps, pc float64) {
		// контур с фаской в углах (имитация скругления R)
		pts := [][2]float64{
			{px + pc, py}, {px + ps - pc, py}, {px + ps, py + pc},
			{px + ps, py + ps - pc}, {px + ps - pc, py + ps}, {px + pc, py + ps},
			{px, py + ps - pc}, {px, py + pc},
		}
		for i := range pts {
			p1, p2 := pts[i], pts[(i+1)%len(pts)]
			pdf.Line(p1[0], p1[1], p2[0], p2[1])
		}
	}
	tube(x0, y0, side, ch)
	tube(x0+wall, y0+wall, side-2*wall, ch*0.6)

	pdf.SetLineWidth(0.15)
	pdf.SetDrawColor(150, 150, 150)
	pdf.Line(x0, y0+side+2.2, x0+side, y0+side+2.2)
	pdf.Line(x0, y0+side+1.4, x0, y0+side+3.0)
	pdf.Line(x0+side, y0+side+1.4, x0+side, y0+side+3.0)
	pdf.Line(x0-2.2, y0, x0-2.2, y0+side)
	pdf.Line(x0-3.0, y0, x0-1.4, y0)
	pdf.Line(x0-3.0, y0+side, x0-1.4, y0+side)
	pdf.Line(x0+side-wall/2, y0-0.8, x0+side-wall/2, y0-3.4)

	label := func(s string, lx, ly float64) {
		pdf.SetFont("tns", "I", 6.5)
		pdf.SetXY(lx, ly)
		pdf.CellFormat(6, 3, s, "", 0, "C", false, 0, "")
	}
	label("A", cx-2, y0+side+2.1)
	label("A", x0-6.5, cy-1.5)
	label("S", x0+side-wall/2-2.3, y0-5.8)
	if rounded {
		label("R", x0+side*0.34, y0+side*0.56)
	}
	pdf.SetDrawColor(40, 40, 40)
	pdf.SetLineWidth(0.3)
}

// roundedRect — прямоугольник со скруглёнными углами (четверти окружностей).
func roundedRect(pdf *gofpdf.Fpdf, x, y, w, h, r float64) {
	if r > w/2 {
		r = w / 2
	}
	if r > h/2 {
		r = h / 2
	}
	pdf.Line(x+r, y, x+w-r, y)
	pdf.Line(x+w, y+r, x+w, y+h-r)
	pdf.Line(x+w-r, y+h, x+r, y+h)
	pdf.Line(x, y+h-r, x, y+r)
	pdf.Arc(x+r, y+r, r, r, 0, 180, 270, "D")
	pdf.Arc(x+w-r, y+r, r, r, 0, 270, 360, "D")
	pdf.Arc(x+w-r, y+h-r, r, r, 0, 0, 90, "D")
	pdf.Arc(x+r, y+h-r, r, r, 0, 90, 180, "D")
}

// formulaRows — таблица 2: схема сечения, тип конструкции и формулы F и Π,
// набранные формулами (курсивные переменные, индексы, степени, дроби, корни).
func (b *pdfBuilder) formulaRows() []pdfRow {
	sketch := func(kind string) func(pdf *gofpdf.Fpdf, x, y, w, h float64) {
		return func(pdf *gofpdf.Fpdf, x, y, w, h float64) {
			drawSection(pdf, x, y, w, h, kind)
		}
	}
	fArea := func(withRadius bool) []func(*formula) {
		return []func(*formula){func(f *formula) {
			f.it("h").it("s").up(" + 2").it("t").up("(").it("b").up(" − ").it("s").up(")")
			if withRadius {
				f.up(" + (4 − π)").it("R").sup("2")
			}
		}}
	}
	angles := func() []func(*formula) {
		return []func(*formula){func(f *formula) {
			f.up("(").side("↓").up(" + ").side("←").up(" + ").side("↑").up(" + ").side("→").up(")").it("h")
		}}
	}
	return []pdfRow{
		{group: true, cells: []string{"Формулы для расчета"}},
		{
			cells: []string{"", "двутавр с уклоном полок", "", ""},
			minH:  34,
			sketches: map[int]func(pdf *gofpdf.Fpdf, x, y, w, h float64){
				0: sketch("ibeam_slope"),
			},
			formulas: map[int][]func(*formula){
				2: fArea(false),
				3: {
					func(f *formula) {
						f.up("(").side("←").up(" + ").side("→").up(")(").it("h").up(" − 4").it("t").up(" + 2")
						f.sqrt(func(g *formula) {
							g.up("((").it("b").up(" − ").it("s").up(")/2)").sup("2").up(" + 4").it("t").sup("2")
						})
						f.up(")")
					},
					func(f *formula) {
						f.up("+ (").side("↓").up(" + ").side("←").up(")").it("b")
					},
				},
			},
		},
		{
			cells: []string{"", "двутавр простой", "", ""},
			minH:  34,
			sketches: map[int]func(pdf *gofpdf.Fpdf, x, y, w, h float64){
				0: sketch("ibeam"),
			},
			formulas: map[int][]func(*formula){
				2: fArea(true),
				3: {
					func(f *formula) {
						f.up("(").side("←").up(" + ").side("→").up(")(").it("h").up(" + ").it("b").up(" − ").it("s").up(" − (4 − π)").it("R").up(")")
					},
					func(f *formula) {
						f.up("+ (").side("↓").up(" + ").side("←").up(")").it("b")
					},
				},
			},
		},
		{
			cells: []string{"", "труба квадратная", "", ""},
			minH:  34,
			sketches: map[int]func(pdf *gofpdf.Fpdf, x, y, w, h float64){
				0: sketch("tube_sq"),
			},
			formulas: map[int][]func(*formula){
				2: {func(f *formula) {
					f.up("4").it("s").up("(").it("h").up(" − 1,43").it("s").up(")")
				}},
				3: {
					func(f *formula) {
						f.up("(").side("↓").up(" + ").side("←").up(" + ").side("↑").up(" + ").side("→").up(")(").it("h").up(" − 2").it("R").up(")")
					},
					func(f *formula) {
						f.up("+ Σ · ").it("π").it("R").up("/2")
					},
					func(f *formula) {
						f.it("R").up(" = 1,5").it("s")
					},
				},
			},
		},
		{
			cells: []string{"", "труба", "", ""},
			minH:  34,
			sketches: map[int]func(pdf *gofpdf.Fpdf, x, y, w, h float64){
				0: sketch("tube"),
			},
			formulas: map[int][]func(*formula){
				2: {func(f *formula) {
					f.up("4").it("s").up("(").it("h").up(" − ").it("s").up(")")
				}},
				3: angles(),
			},
		},
	}
}
