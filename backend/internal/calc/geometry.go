package calc

import (
	"math"
	"strings"

	"ozm/backend/internal/models"
)

func dim(dims map[string]float64, keys ...string) float64 {
	for _, k := range keys {
		if v, ok := dims[k]; ok {
			return v
		}
	}
	return 0
}

// normalizeDims приводит ключи размеров из справочника проката (dicts/roll.json)
// к ключам, которыми оперируют формулы sectionArea/heatedPerimeter (h, b, s, t).
// В справочнике квадратная труба задана как A/s, круглая — d/h (где h — стенка),
// уголок — b (B)/t, гнутый профиль — h/b/t, тавр — S/S1/S2. Без приведения
// у трубы 100х5 выходили F = -143 мм² и P = -17 мм, у круглой трубы и гнутого
// профиля F = 0, у уголков — половина сечения; приведённая толщина падала в 0,
// и расчёт брал максимальную толщину покрытия. Заполняются только отсутствующие
// ключи: размеры, введённые пользователем, не трогаются. Сами формулы прежние.
func normalizeDims(shape string, dims map[string]float64) {
	setIfMissing := func(k string, v float64) {
		if _, ok := dims[k]; !ok && v != 0 {
			dims[k] = v
		}
	}
	switch {
	case strings.HasPrefix(shape, "tube_sq"):
		if a, ok := dims["A"]; ok {
			setIfMissing("h", a)
			setIfMissing("b", a)
		}
		if bb, ok := dims["B"]; ok {
			setIfMissing("b", bb)
		}
	case shape == "tube_sm", shape == "tube_":
		// в справочнике круглой трубы d — диаметр, h — толщина стенки;
		// в формулах h — диаметр, s — стенка
		if d, ok := dims["d"]; ok {
			if wall, ok2 := dims["h"]; ok2 {
				setIfMissing("s", wall)
			}
			dims["h"] = d
		}
	case strings.HasPrefix(shape, "corner"):
		if bb, ok := dims["B"]; ok {
			setIfMissing("h", bb)
		} else if b, ok := dims["b"]; ok {
			setIfMissing("h", b)
		}
		if t, ok := dims["t"]; ok {
			setIfMissing("s", t)
		}
	case strings.HasPrefix(shape, "profile"):
		if t, ok := dims["t"]; ok {
			setIfMissing("s", t)
		}
	case strings.HasPrefix(shape, "brands"):
		if v, ok := dims["S1"]; ok {
			setIfMissing("t", v)
		}
		if v, ok := dims["S2"]; ok {
			setIfMissing("tr", v)
		}
	}
}

func sectionArea(shape string, dims map[string]float64) float64 {
	h := dim(dims, "h", "H")
	b := dim(dims, "b", "B")
	s := dim(dims, "s", "S")
	t := dim(dims, "t", "T")
	tr := dim(dims, "t-r", "tr")
	R := dim(dims, "R")
	r := dim(dims, "r")
	pi := math.Pi

	switch {
	case strings.HasPrefix(shape, "I-beam"), strings.HasPrefix(shape, "channel"):
		return h*s + 2*t*(b-s) + (4-pi)*R*R
	case strings.HasPrefix(shape, "brands"):
		return h*s + (t+tr)*(b-s)/2
	case strings.HasPrefix(shape, "corner"):
		f := h*s + t*b - t*t
		if shape != "corner_" && R > 0 {
			f += (R*R - 2*r*r) * (1 - pi/2)
		}
		return f
	case shape == "profile_sm":
		tb := tBase(t)
		Rs := tb * s
		return 2*s*(h+b-4*Rs) + pi*s*(s+Rs)
	case strings.HasPrefix(shape, "profile"):
		return 2 * s * (h + b - 2*s)
	case shape == "tube_sm":
		return pi * h * s
	case strings.HasPrefix(shape, "tube"):
		k := 1.0
		if shape != "tube_" {
			k = 1.43
		}
		return 4 * s * (h - k*s)
	default:
		return h*s + 2*t*(b-s)
	}
}

func tBase(t float64) float64 {
	if t > 10 {
		return 3
	}
	if t > 6 {
		return 2.5
	}
	return 2
}

func sideVal(b bool) float64 {
	if b {
		return 1
	}
	return 0
}

func heatedPerimeter(shape string, dims map[string]float64, sides models.HeatedSides) float64 {
	h := dim(dims, "h", "H")
	b := dim(dims, "b", "B")
	s := dim(dims, "s", "S")
	t := dim(dims, "t", "T")
	R := dim(dims, "R")
	L, T, Rr, B := sideVal(sides.Left), sideVal(sides.Top), sideVal(sides.Right), sideVal(sides.Bottom)
	pi := math.Pi
	sigma := L + T + Rr + B
	if sigma == 0 {
		// default all sides heated when none selected
		L, T, Rr, B = 1, 1, 1, 1
		sigma = 4
	}

	switch {
	case strings.HasPrefix(shape, "I-beam"):
		calcLR := h + (b - s) - (4-pi)*R
		if strings.Contains(shape, "_sl") {
			calcLR = h + (b - s)
		}
		return (L+Rr)*calcLR + (T+B)*b
	case strings.HasPrefix(shape, "channel"):
		calcR := h + (b - s) - (4-pi)*R
		return L*h + Rr*calcR + (T+B)*b
	case strings.HasPrefix(shape, "brands"):
		return L*(h-t) + Rr*(h-t) + (T+B)*b + T*s
	case strings.HasPrefix(shape, "corner"):
		return L*h + B*b + T*(b-s) + Rr*(h-s)
	case shape == "tube_sm":
		return sigma * pi * h / 4
	case shape == "profile_sm", strings.HasPrefix(shape, "tube_sq"):
		tb := tBase(t)
		Rs := tb * s
		if Rs == 0 {
			Rs = s
		}
		return (L+Rr)*(h-2*Rs) + (T+B)*(b-2*Rs) + sigma*pi*Rs/2
	default:
		return (L+Rr)*h + (T+B)*b
	}
}

func ozmAreas(lining int, dims map[string]float64, sides models.HeatedSides, shape string, delta, lengthM float64) (sv, sm float64) {
	h := dim(dims, "h", "H")
	b := dim(dims, "b", "B")
	t := dim(dims, "t", "T")
	L, T, Rr, Btm := sideVal(sides.Left), sideVal(sides.Top), sideVal(sides.Right), sideVal(sides.Bottom)
	if L+T+Rr+Btm == 0 {
		L, T, Rr, Btm = 1, 1, 1, 1
	}
	prot1 := 0.0
	if T > 0 && Rr > 0 {
		prot1 = 1
	}
	prot4 := 0.0
	if L > 0 && T > 0 {
		prot4 = 1
	}
	zeta := prot1
	if Rr > 0 && Btm > 0 {
		zeta++
	}
	if Btm > 0 && L > 0 {
		zeta++
	}
	zeta += prot4

	var lm float64
	if lining == 3 {
		sigma := L + T + Rr + Btm
		lm = (math.Pi * (h + 2*delta) / 4) * sigma
	} else {
		lm = (L+Rr)*h + (T+Btm)*b + zeta*delta
	}

	alfa := 0.0
	if lining == 1 {
		alfa = Rr
		if strings.HasPrefix(shape, "I-beam") {
			alfa += L
		}
	}
	lv := alfa * (h - 2*t)
	sm = lm / 1000 * lengthM
	sv = sm + (lv/1000)*0.1*(lengthM/0.6)
	return sv, sm
}

func claddingPerimeter(lining int, dims map[string]float64, sides models.HeatedSides, shape string, delta float64) float64 {
	h := dim(dims, "h", "H")
	b := dim(dims, "b", "B")
	L, T, Rr, Btm := sideVal(sides.Left), sideVal(sides.Top), sideVal(sides.Right), sideVal(sides.Bottom)
	if L+T+Rr+Btm == 0 {
		L, T, Rr, Btm = 1, 1, 1, 1
	}
	prot1 := 0.0
	if T > 0 && Rr > 0 {
		prot1 = 1
	}
	prot4 := 0.0
	if L > 0 && T > 0 {
		prot4 = 1
	}
	zeta := prot1
	if Rr > 0 && Btm > 0 {
		zeta++
	}
	if Btm > 0 && L > 0 {
		zeta++
	}
	zeta += prot4

	var lm float64
	if lining == 3 {
		sigma := L + T + Rr + Btm
		lm = (math.Pi * (h + 2*delta) / 4) * sigma
	} else {
		lm = (L+Rr)*h + (T+Btm)*b + zeta*delta
	}
	beta := 0.0
	if lining == 2 {
		beta = prot1
		if strings.HasPrefix(shape, "brands") {
			beta += prot4
		}
	}
	if lining == 3 {
		return lm
	}
	return lm + (zeta+beta)*delta
}
