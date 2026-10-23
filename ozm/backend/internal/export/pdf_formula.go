package export

import (
	"github.com/jung-kurt/gofpdf"
)

// formula — маленький наборщик формул для отчёта: переменные курсивом, числа и
// операторы прямым, индексы и степени уменьшенным кеглем, дроби с чертой и
// корни с радикалом. Текст ставится по базовой линии (pdf.Text), поэтому
// смещения индексов и дробей точные и не зависят от высоты ячейки.
// Шрифт — DejaVu Serif (засечный, как в легаси-документе).
type formula struct {
	pdf  *gofpdf.Fpdf
	x    float64 // текущая позиция по горизонтали
	y    float64 // базовая линия
	size float64
	dry  bool
}

func newFormula(pdf *gofpdf.Fpdf, x, y, size float64) *formula {
	return &formula{pdf: pdf, x: x, y: y, size: size}
}

func (f *formula) font(italic bool, size float64) {
	style := ""
	if italic {
		style = "I"
	}
	f.pdf.SetFont("tns", style, size)
}

func (f *formula) width() float64 { return f.x }

// up — прямой текст (числа, операторы, скобки).
func (f *formula) up(s string) *formula {
	return f.run(s, false, f.size, 0)
}

// it — курсив (переменные).
func (f *formula) it(s string) *formula {
	return f.run(s, true, f.size, 0)
}

// sub — нижний индекс.
func (f *formula) sub(s string) *formula {
	return f.run(s, false, f.size*0.62, f.size*0.22)
}

// sup — верхний индекс.
func (f *formula) sup(s string) *formula {
	return f.run(s, false, f.size*0.62, -f.size*0.34)
}

// run — вывод фрагмента со сдвигом по вертикали относительно базовой линии.
func (f *formula) run(s string, italic bool, size, dy float64) *formula {
	if s == "" {
		return f
	}
	f.font(italic, size)
	w := f.pdf.GetStringWidth(s)
	if !f.dry {
		f.pdf.Text(f.x, f.y+dy, s)
	}
	f.x += w
	return f
}

// measure — ширина составной части без рисования.
func (f *formula) measure(build func(*formula)) float64 {
	start := f.x
	part := &formula{pdf: f.pdf, x: f.x, y: f.y, size: f.size, dry: true}
	build(part)
	f.x = start
	return part.x - start
}

// frac — дробь: числитель и знаменатель меньшим кеглем, между ними черта.
func (f *formula) frac(num, den func(*formula)) *formula {
	sub := f.size * 0.86
	numW := f.measure(func(g *formula) {
		g.size = sub
		num(g)
	})
	denW := f.measure(func(g *formula) {
		g.size = sub
		den(g)
	})
	w := numW
	if denW > w {
		w = denW
	}
	w += 1.8
	if !f.dry {
		mid := f.x + w/2
		f.pdf.SetDrawColor(40, 40, 40)
		f.pdf.SetLineWidth(0.2)
		g := &formula{pdf: f.pdf, x: mid - numW/2, y: f.y - f.size*0.75, size: sub}
		num(g)
		f.pdf.Line(f.x, f.y+0.9, f.x+w, f.y+0.9)
		g = &formula{pdf: f.pdf, x: mid - denW/2, y: f.y + f.size*0.55, size: sub}
		den(g)
	}
	f.x += w
	return f
}

// sqrt — корень: радикал рисуется линиями, над подкоренным выражением — черта.
func (f *formula) sqrt(build func(*formula)) *formula {
	w := f.measure(build)
	lead := f.size * 0.55
	if !f.dry {
		f.pdf.SetDrawColor(40, 40, 40)
		f.pdf.SetLineWidth(0.2)
		x0 := f.x
		top := f.y - f.size*0.92
		f.pdf.Line(x0, f.y-f.size*0.10, x0+lead*0.45, f.y+f.size*0.28)
		f.pdf.Line(x0+lead*0.45, f.y+f.size*0.28, x0+lead, top)
		f.pdf.Line(x0+lead, top, x0+lead+w+0.5, top)
		g := &formula{pdf: f.pdf, x: x0 + lead + 0.4, y: f.y, size: f.size}
		build(g)
	}
	f.x += lead + w + 0.6
	return f
}

// side — символ стороны обогрева: квадрат с линией-стрелкой внутри.
func (f *formula) side(arrow string) *formula {
	const box = 2.8
	if !f.dry {
		f.pdf.SetDrawColor(40, 40, 40)
		f.pdf.SetLineWidth(0.18)
		x0 := f.x
		y0 := f.y - 2.2
		f.pdf.Rect(x0, y0, box, box, "D")
		cx, cy := x0+box/2, y0+box/2
		e := box * 0.30 // половина длины стрелки
		f.pdf.SetLineWidth(0.22)
		switch arrow {
		case "←":
			f.pdf.Line(cx+e, cy, cx-e, cy)
			f.pdf.Line(cx-e, cy, cx-e*0.3, cy-e*0.55)
			f.pdf.Line(cx-e, cy, cx-e*0.3, cy+e*0.55)
		case "→":
			f.pdf.Line(cx-e, cy, cx+e, cy)
			f.pdf.Line(cx+e, cy, cx+e*0.3, cy-e*0.55)
			f.pdf.Line(cx+e, cy, cx+e*0.3, cy+e*0.55)
		case "↑":
			f.pdf.Line(cx, cy+e, cx, cy-e)
			f.pdf.Line(cx, cy-e, cx-e*0.55, cy-e*0.3)
			f.pdf.Line(cx, cy-e, cx+e*0.55, cy-e*0.3)
		default: // ↓
			f.pdf.Line(cx, cy-e, cx, cy+e)
			f.pdf.Line(cx, cy+e, cx-e*0.55, cy+e*0.3)
			f.pdf.Line(cx, cy+e, cx+e*0.55, cy+e*0.3)
		}
	}
	f.x += box + 0.4
	return f
}

// drawFormula — набирает формулу и возвращает её ширину.
func drawFormula(pdf *gofpdf.Fpdf, x, y, size float64, build func(*formula)) float64 {
	f := newFormula(pdf, x, y, size)
	build(f)
	pdf.SetTextColor(33, 33, 33)
	return f.width() - x
}

// formulaWidth — ширина формулы без рисования.
func formulaWidth(pdf *gofpdf.Fpdf, size float64, build func(*formula)) float64 {
	f := newFormula(pdf, 0, 0, size)
	f.dry = true
	build(f)
	return f.x
}
