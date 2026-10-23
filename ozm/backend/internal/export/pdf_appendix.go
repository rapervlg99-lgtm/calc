package export

import (
	"bytes"
	"math"
	"strconv"
	"strings"

	"github.com/jung-kurt/gofpdf"
)

// Приложения отчёта собираются из сканов корпоративной библиотеки
// (assets/appendix, встроены в бинарник):
//
//	Приложение A. Устройство огнезащиты конструкции — схемы систем;
//	Приложение Б. Сертификаты пожарной безопасности — сертификаты ЕАЭС;
//	Приложение В. Технические листы — техлисты систем и материалов.
//
// В отчёт попадают только приложения тех систем, которые есть в расчёте:
// ОЗМ (плиты, металл), ОЗБ (плиты, бетон), TAIKOR (по типам покрытия),
// плюс грунт и финиш, если они выбраны у конструкций.

type appendixPage struct {
	asset string // имя файла в assets/appendix
}

// appendixUzly — схемы устройства огнезащиты (Приложение A).
func (b *pdfBuilder) appendixUzly() []appendixPage {
	var out []appendixPage
	if b.hasCoat(1) {
		out = append(out, appendixPage{"a-ozm-1.jpg"}, appendixPage{"a-ozm-2.jpg"})
	}
	if coat := b.taikorCoat(); coat != "" {
		out = append(out, appendixPage{"a-t" + coat + ".png"})
	}
	if b.hasBeton() {
		out = append(out, appendixPage{"a-ozb-1.jpg"}, appendixPage{"a-ozb-2.jpg"})
	}
	return out
}

// appendixSheets — технические листы (Приложение В).
func (b *pdfBuilder) appendixSheets() []appendixPage {
	var out []appendixPage
	if b.hasCoat(1) {
		out = append(out, appendixPage{"v-tn-metall.jpg"}, appendixPage{"v-ozm-1.jpg"}, appendixPage{"v-ozm-2.jpg"})
	}
	if coat := b.taikorCoat(); coat != "" {
		switch coat {
		case "2":
			out = append(out, appendixPage{"v-epoxy-1.jpg"}, appendixPage{"v-epoxy-2.jpg"})
		case "3":
			out = append(out, appendixPage{"v-graphite-1.jpg"}, appendixPage{"v-graphite-2.jpg"})
		case "4":
			out = append(out, appendixPage{"v-graphite-1.jpg"}, appendixPage{"v-graphite-2.jpg"},
				appendixPage{"v-extra-1.jpg"}, appendixPage{"v-extra-2.jpg"})
		}
	}
	if b.hasPrimer() {
		out = append(out, appendixPage{"v-t150p-1.jpg"}, appendixPage{"v-t150p-2.jpg"})
	}
	if b.hasEnamel() {
		out = append(out, appendixPage{"v-t425t-1.jpg"}, appendixPage{"v-t425t-2.jpg"})
	}
	if b.hasBeton() {
		out = append(out, appendixPage{"v-tn-beton.jpg"})
		if b.betonDelta() >= 50 {
			out = append(out, appendixPage{"v-ozb50-1.jpg"}, appendixPage{"v-ozb50-2.jpg"})
		} else {
			out = append(out, appendixPage{"v-ozb40-1.jpg"}, appendixPage{"v-ozb40-2.jpg"})
		}
	}
	return out
}

// appendixCerts — сертификаты соответствия (Приложение Б): на плиты — ЕАЭС по
// ТР ЕАЭС 043/2017 и добровольный сертификат на минераловатные плиты, на
// покрытия TAIKOR — сертификаты по типу состава. Дубликаты не повторяются.
func (b *pdfBuilder) appendixCerts() []appendixPage {
	var out []appendixPage
	seen := map[string]bool{}
	add := func(name string) {
		if seen[name] {
			return
		}
		seen[name] = true
		out = append(out, appendixPage{name})
	}
	plates := b.hasCoat(1) || b.hasBeton()
	if plates {
		for _, n := range []string{"b-ozm-1.jpg", "b-ozm-2.jpg", "b-ozm-3.jpg"} {
			add(n)
		}
	}
	if b.hasCoat(1) || b.hasBeton() {
		for i := 1; i <= 6; i++ {
			add("b-kv-" + strconv.Itoa(i) + ".jpg")
		}
	}
	switch coat := b.taikorCoat(); coat {
	case "2":
		for i := 1; i <= 4; i++ {
			add("b-t2-" + strconv.Itoa(i) + ".jpg")
		}
	case "3":
		for i := 1; i <= 3; i++ {
			add("b-t3-" + strconv.Itoa(i) + ".jpg")
		}
	case "4":
		for i := 1; i <= 3; i++ {
			add("b-t3-" + strconv.Itoa(i) + ".jpg")
		}
		for i := 1; i <= 2; i++ {
			add("b-t4-" + strconv.Itoa(i) + ".jpg")
		}
	}
	return out
}

// hasCoat — есть ли в расчёте покрытие с таким кодом (1 — ОЗМ).
func (b *pdfBuilder) hasCoat(coat float64) bool {
	for _, el := range b.elems {
		if parseCoatN(el.coatID) == coat {
			return true
		}
	}
	return false
}

// taikorCoat — тип покрытия TAIKOR из расчёта (2, 3 или 4; при нескольких —
// первый по порядку), "" если покрытия нет.
func (b *pdfBuilder) taikorCoat() string {
	for _, want := range []string{"2", "3", "4"} {
		for _, el := range b.elems {
			if parseCoatN(el.coatID) == parseCoatN(want) {
				return want
			}
		}
	}
	return ""
}

func (b *pdfBuilder) hasPrimer() bool {
	for _, el := range b.elems {
		if el.input.Primer {
			return true
		}
	}
	return false
}

func (b *pdfBuilder) hasEnamel() bool {
	for _, el := range b.elems {
		if el.input.Enamel {
			return true
		}
	}
	return false
}

func (b *pdfBuilder) hasBeton() bool {
	return b.beton != nil && b.beton.AreaM2 > 0
}

func (b *pdfBuilder) betonDelta() float64 {
	if b.beton == nil {
		return 0
	}
	return b.ozbDelta(b.beton.HtLevel)
}

// appendices добавляет приложения A, Б и В.
func (b *pdfBuilder) appendices() {
	if pages := b.appendixUzly(); len(pages) > 0 {
		b.appendixSection("appA", "Приложение A. Устройство огнезащиты конструкции", pages)
	}
	if pages := b.appendixCerts(); len(pages) > 0 {
		b.appendixSection("appB", "Приложение Б. Сертификаты пожарной безопасности", pages)
	}
	if pages := b.appendixSheets(); len(pages) > 0 {
		b.appendixSection("appV", "Приложение В. Технические листы", pages)
	}
}

// appendixSection — заголовок приложения на отдельной странице и по странице
// на каждый скан.
func (b *pdfBuilder) appendixSection(key, title string, pages []appendixPage) {
	b.pdf.AddPage()
	b.heading(key, title)
	for i, p := range pages {
		y := 30.0
		if i > 0 {
			b.pdf.AddPage()
			y = 26.0
		}
		b.appendixImage(p.asset, y)
	}
}

// appendixImage вписывает скан в область под колонтитулами, сохраняя пропорции.
func (b *pdfBuilder) appendixImage(asset string, y float64) {
	data, err := appendixFS.ReadFile("assets/appendix/" + asset)
	if err != nil {
		return
	}
	opt := gofpdf.ImageOptions{ImageType: strings.ToUpper(strings.TrimPrefix(fileExt(asset), ".")), ReadDpi: false}
	name := "ap-" + strings.NewReplacer(".", "-", "_", "-").Replace(asset)
	info := b.pdf.RegisterImageOptionsReader(name, opt, bytes.NewReader(data))
	if info == nil {
		return
	}
	width, height := info.Width(), info.Height()
	if width <= 0 || height <= 0 {
		return
	}
	const maxW, bottom = 170.0, 262.0
	scale := math.Min(maxW/width, (bottom-y)/height)
	b.pdf.ImageOptions(name, 25+(maxW-width*scale)/2, y, width*scale, 0, false, opt, 0, "")
}

// fileExt — расширение файла вместе с точкой.
func fileExt(name string) string {
	if i := strings.LastIndex(name, "."); i >= 0 {
		return name[i:]
	}
	return ""
}
