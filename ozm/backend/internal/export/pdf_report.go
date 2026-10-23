package export

import (
	"bytes"
	"fmt"
	"strings"

	"github.com/jung-kurt/gofpdf"

	"ozm/backend/internal/models"
)

// PDF-отчёт «Расчет огнезащиты» по образцу легаси-документа: титул, содержание,
// пять разделов с таблицами (общие данные, приведённая толщина металла,
// определение толщины изоляции, площади и объёмы, итоговая спецификация) и
// список литературы. Приложения (сертификаты, технические листы, узлы
// устройства огнезащиты) — статичные материалы компании и в генератор не входят.

const (
	pdfRed   = 227
	pdfGreen = 24
	pdfBlue  = 55
	pdfGray  = 243
)

// elemInfo — данные элемента для PDF-таблиц (входные + справочные + результат).
type elemInfo struct {
	group    string
	title    string
	coatID   string
	coatName string
	htLevel  float64
	sides    string
	lengthMM float64
	dims     map[string]float64
	shape    string
	profile  string
	family   string
	input    models.ElementInput
	res      models.ElementResult
}

type pdfBuilder struct {
	pdf    *gofpdf.Fpdf
	svc    *Service
	resp   models.CalcResponse
	elems  []elemInfo
	beton  *models.BetonInput
	record map[string]int
}

// Делегирование справочников из Service: коэффициенты, расходы, названия.
func (b *pdfBuilder) ozmCoef() float64                    { return b.svc.ozmCoef() }
func (b *pdfBuilder) ozbCoef() float64                    { return b.svc.ozbCoef() }
func (b *pdfBuilder) taikorCoef() float64                 { return b.svc.taikorCoef() }
func (b *pdfBuilder) ozbDelta(r float64) float64          { return b.svc.ozbDelta(r) }
func (b *pdfBuilder) matRate(id string) float64           { return b.svc.matRate(id) }
func (b *pdfBuilder) matTitle(id, fallback string) string { return b.svc.matTitle(id, fallback) }
func (b *pdfBuilder) t500Rows() []models.T500Row          { return b.svc.cfg.T500 }

// PDF собирает отчёт: первый проход считает страницы разделов, второй пишет
// документ уже с номерами в содержании.
func (s *Service) PDF(resp models.CalcResponse) ([]byte, error) {
	_, pages, err := s.buildPDF(resp, nil)
	if err != nil {
		return nil, err
	}
	data, _, err := s.buildPDF(resp, pages)
	return data, err
}

func (s *Service) buildPDF(resp models.CalcResponse, contents map[string]int) ([]byte, map[string]int, error) {
	pdf := gofpdf.New("P", "mm", "A4", "")
	pdf.SetMargins(25, 20, 15)
	pdf.SetAutoPageBreak(true, 22)
	pdf.AddUTF8FontFromBytes("tn", "", dejaVuSans)
	pdf.AddUTF8FontFromBytes("tn", "B", dejaVuSansBold)
	// засечный шрифт для формул: переменные курсивом, числа прямым
	pdf.AddUTF8FontFromBytes("tns", "", dejaVuSerif)
	pdf.AddUTF8FontFromBytes("tns", "I", dejaVuSerifItalic)
	pdf.AliasNbPages("{nb}")
	pdf.SetTitle("Расчет огнезащиты — "+resp.Inputs.ObjectName, false)
	pdf.SetCreator("ОЗМ — калькулятор огнезащиты ТЕХНОНИКОЛЬ", false)

	// картинки регистрируем один раз: имена должны быть уникальны в документе
	if len(reportLogoPNG) > 0 {
		opt := gofpdf.ImageOptions{ImageType: "PNG", ReadDpi: true}
		pdf.RegisterImageOptionsReader("tn-logo", opt, bytes.NewReader(reportLogoPNG))
	}
	if len(reportQRPNG) > 0 {
		opt := gofpdf.ImageOptions{ImageType: "PNG", ReadDpi: true}
		pdf.RegisterImageOptionsReader("tn-qr", opt, bytes.NewReader(reportQRPNG))
	}

	b := &pdfBuilder{pdf: pdf, svc: s, resp: resp, record: map[string]int{}}
	b.elems = s.pdfElements(resp)
	b.beton = resp.Inputs.Beton
	pdf.SetHeaderFuncMode(b.header, true)
	pdf.SetFooterFunc(b.footer)

	// Содержание рисуем в обоих проходах: высота страницы фиксирована, поэтому
	// нумерация разделов совпадает, а во втором проходе в него попадут номера.
	pages := contents
	if pages == nil {
		pages = map[string]int{}
	}
	b.cover()
	b.contents(pages)
	b.record = map[string]int{}
	b.section1()
	b.section2()
	b.section3()
	b.section4()
	b.section5()
	b.appendices()
	b.literature()

	if contents == nil {
		return nil, b.record, nil
	}
	var buf bytes.Buffer
	if err := pdf.Output(&buf); err != nil {
		return nil, nil, err
	}
	return buf.Bytes(), b.record, nil
}

// pdfElements собирает данные элементов: входные параметры, размеры проката,
// семью профиля и результат расчёта.
func (s *Service) pdfElements(resp models.CalcResponse) []elemInfo {
	var out []elemInfo
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
			info := elemInfo{
				group: group, title: elementTitle(el, ei), input: el,
				coatID: el.Coat, coatName: s.coatTitle(el.Coat),
				htLevel: el.HtLevel, sides: sidesText(el.Sides),
				lengthMM: el.LengthM * 1000, shape: el.Shape,
				profile: s.profileLabel(el), family: s.familyLabel(el.Shape),
				res: res,
			}
			info.dims = s.rollDims(el)
			out = append(out, info)
		}
	}
	return out
}

// rollDims — размеры сечения: из справочника проката по марке, иначе заданные.
func (s *Service) rollDims(el models.ElementInput) map[string]float64 {
	dims := map[string]float64{}
	if el.RollID != "" {
		for _, r := range s.cfg.Roll {
			if r.ID == el.RollID {
				for k, v := range r.Dims {
					dims[k] = v
				}
				break
			}
		}
	}
	for k, v := range el.Dims {
		if _, ok := dims[k]; !ok {
			dims[k] = v
		}
	}
	return dims
}

// familyLabel — тип сечения конструкции: подпись формы («двутавр простой»),
// иначе подпись семейства, иначе идентификатор формы.
func (s *Service) familyLabel(shape string) string {
	for _, f := range s.cfg.Profiles {
		for _, sh := range f.Shapes {
			if sh.ID == shape {
				if sh.Label != "" {
					return sh.Label
				}
				if f.Label != "" {
					return f.Label
				}
				return shape
			}
		}
	}
	return shape
}

// ---------- рамка документа ----------

func (b *pdfBuilder) header() {
	pdf := b.pdf
	if pdf.PageNo() <= 1 {
		return
	}
	if len(reportLogoPNG) > 0 {
		opt := gofpdf.ImageOptions{ImageType: "PNG", ReadDpi: true}
		pdf.ImageOptions("tn-logo", 25, 8, 38, 0, false, opt, 0, "")
	}
	pdf.SetFont("tn", "", 7)
	pdf.SetTextColor(70, 70, 70)
	for i, line := range []string{"Корпорация ТЕХНОНИКОЛЬ", "Техническая поддержка 8-800-600-05-65", "www.tn.ru, nav.tn.ru"} {
		pdf.SetXY(90, 8+float64(i)*3.4)
		pdf.CellFormat(70, 3.4, line, "", 0, "R", false, 0, "")
	}
	if len(reportQRPNG) > 0 {
		opt := gofpdf.ImageOptions{ImageType: "PNG", ReadDpi: true}
		pdf.ImageOptions("tn-qr", 172, 7.5, 14, 0, false, opt, 0, "")
	}
	pdf.SetTextColor(33, 33, 33)
	pdf.SetY(24)
}

func (b *pdfBuilder) footer() {
	pdf := b.pdf
	if pdf.PageNo() <= 1 {
		// титульный лист без колонтитула
		return
	}
	w, h := pdf.GetPageSize()
	y := h - 13
	pdf.SetDrawColor(pdfRed, pdfGreen, pdfBlue)
	pdf.SetLineWidth(0.5)
	pdf.Line(25, y, w-15, y)
	pdf.SetFillColor(pdfRed, pdfGreen, pdfBlue)
	pdf.Rect(w-15, y+1.5, 6, 6, "F")
	pdf.SetFont("tn", "", 8)
	pdf.SetTextColor(255, 255, 255)
	pdf.SetXY(w-15, y+1.6)
	pdf.CellFormat(6, 5.8, fmt.Sprintf("%d", pdf.PageNo()), "", 0, "C", false, 0, "")
	pdf.SetTextColor(120, 120, 120)
	pdf.SetXY(w-9, y+1.6)
	pdf.CellFormat(9, 5.8, "/{nb}", "", 0, "R", false, 0, "")
	pdf.SetTextColor(33, 33, 33)
}

// ---------- текстовые блоки ----------

func (b *pdfBuilder) heading(key, title string) {
	pdf := b.pdf
	if y := pdf.GetY(); y > 230 {
		pdf.AddPage()
	}
	if b.record != nil {
		b.record[key] = pdf.PageNo()
	}
	pdf.Ln(2)
	pdf.SetFont("tn", "B", 13)
	pdf.SetTextColor(33, 33, 33)
	pdf.MultiCell(170, 7, title, "", "L", false)
	pdf.Ln(2)
	pdf.SetFont("tn", "", 9.5)
}

func (b *pdfBuilder) sub(title string) {
	pdf := b.pdf
	pdf.Ln(2)
	pdf.SetFont("tn", "B", 10)
	pdf.MultiCell(170, 5.5, title, "", "L", false)
	pdf.Ln(1)
	pdf.SetFont("tn", "", 9.5)
}

func (b *pdfBuilder) para(text string) {
	b.pdf.SetFont("tn", "", 9.5)
	b.pdf.MultiCell(170, 5, text, "", "L", false)
	b.pdf.Ln(1.5)
}

// caption — подпись таблицы; если внизу страницы мало места, подпись уходит на
// новую страницу вместе с таблицей.
func (b *pdfBuilder) caption(text string) {
	if _, pageH := b.pdf.GetPageSize(); b.pdf.GetY()+22 > pageH-22 {
		b.pdf.AddPage()
	}
	b.pdf.SetFont("tn", "", 9)
	b.pdf.CellFormat(170, 6, text, "", 1, "R", false, 0, "")
	b.pdf.SetFont("tn", "", 9.5)
}

// captionTable — подпись и таблица как одно целое (подпись не отрывается).
func (b *pdfBuilder) captionTable(text string, cols []pdfCol, rows []pdfRow) {
	b.caption(text)
	b.table(cols, rows)
}

// displayFormula — формула по центру строки (набор засечным шрифтом).
func (b *pdfBuilder) displayFormula(size float64, build func(*formula)) {
	pdf := b.pdf
	w := formulaWidth(pdf, size, build)
	// над базовой линией нужен запас под числитель дроби, под ней — под знаменатель
	above, below := size*1.15, size*0.85
	if _, pageH := pdf.GetPageSize(); pdf.GetY()+above+below+4 > pageH-22 {
		pdf.AddPage()
	}
	y := pdf.GetY() + above
	drawFormula(pdf, 25+(170-w)/2, y, size, build)
	pdf.SetFont("tn", "", 9.5)
	pdf.SetTextColor(33, 33, 33)
	pdf.SetY(y + below)
}

func (b *pdfBuilder) bullet(items ...string) {
	pdf := b.pdf
	for _, it := range items {
		pdf.SetX(30)
		pdf.CellFormat(4, 5, "•", "", 0, "L", false, 0, "")
		pdf.MultiCell(162, 5, it, "", "L", false)
	}
	pdf.Ln(1)
}

// ---------- титул, содержание, литература ----------

func (b *pdfBuilder) cover() {
	pdf := b.pdf
	pdf.AddPage()
	if len(reportLogoPNG) > 0 {
		opt := gofpdf.ImageOptions{ImageType: "PNG", ReadDpi: true}
		pdf.ImageOptions("tn-logo", 128, 18, 52, 0, false, opt, 0, "")
	}
	pdf.SetFillColor(pdfGray, pdfGray, pdfGray)
	pdf.Rect(0, 85, 210, 100, "F")
	pdf.SetFont("tn", "", 12)
	pdf.SetTextColor(pdfRed, pdfGreen, pdfBlue)
	addr := strings.TrimSpace(b.resp.Inputs.Address)
	if addr == "" {
		addr = strings.TrimSpace(b.resp.Inputs.ObjectName)
	}
	pdf.SetXY(0, 103)
	pdf.CellFormat(210, 8, "склад по адресу: "+addr, "", 1, "C", false, 0, "")
	pdf.SetFont("tn", "B", 24)
	pdf.SetXY(0, 120)
	pdf.CellFormat(210, 14, "Расчет огнезащиты", "", 1, "C", false, 0, "")
	pdf.SetFont("tn", "", 11)
	pdf.SetTextColor(33, 33, 33)
	pdf.SetXY(0, 262)
	pdf.CellFormat(210, 8, fmt.Sprintf("%d", reportYear()), "", 1, "C", false, 0, "")
}

func (b *pdfBuilder) contents(pages map[string]int) {
	pdf := b.pdf
	pdf.AddPage()
	pdf.SetFont("tn", "B", 13)
	pdf.CellFormat(170, 7, "Содержание", "", 1, "L", false, 0, "")
	pdf.Ln(3)
	items := [][2]string{
		{"s1", "1. Общие данные"},
		{"s2", "2. Расчет приведенной толщины металла"},
		{"s3", "3. Определение толщины огнезащитной изоляции"},
		{"s4", "4. Расчёт площадей защищаемых элементов и объема защитных материалов"},
		{"s5", "5. Итоговая спецификация материалов"},
		{"appA", "Приложение A. Устройство огнезащиты конструкции"},
		{"appB", "Приложение Б. Сертификаты пожарной безопасности"},
		{"appV", "Приложение В. Технические листы"},
		{"lit", "Список используемой литературы"},
	}
	pdf.SetFont("tn", "", 9.5)
	for _, it := range items {
		page := pages[it[0]]
		if page == 0 {
			page = 2
		}
		pdf.SetFont("tn", "", 9.5)
		pdf.SetTextColor(33, 33, 33)
		pdf.CellFormat(130, 6, it[1], "", 0, "L", false, 0, "")
		dots := int(35 / (pdf.GetStringWidth(".") + 0.01))
		pdf.SetTextColor(150, 150, 150)
		pdf.CellFormat(35, 6, strings.Repeat(".", dots), "", 0, "R", false, 0, "")
		pdf.SetTextColor(33, 33, 33)
		pdf.CellFormat(5, 6, fmt.Sprintf("%d", page), "", 1, "R", false, 0, "")
	}
}

func (b *pdfBuilder) literature() {
	pdf := b.pdf
	pdf.AddPage()
	b.heading("lit", "Список используемой литературы")
	items := []string{
		"Федеральный закон от 22 июля 2008 г. N 123 ФЗ «Технический регламент о требованиях пожарной безопасности».",
		"Технические условия ТУ.5762-004-74182181-2014. Плиты технические минераловатные, теплоизоляционные ТЕХНО.",
		"ИНСТРУКЦИЯ по расчету фактических пределов огнестойкости стальных конструкций с композицией огнезащитной, выполненной из минераловатных плит ТЕХНО марки «Плита огнезащитная для изоляции конструкций из металла ТЕХНОНИКОЛЬ».",
		"Технологический регламент. Рабочая инструкция композиции огнезащитной для железобетонных конструкций из минераловатных плит ТЕХНО марки «Плита огнезащитная для изоляции конструкций из бетона ТЕХНОНИКОЛЬ». ТУ.5762-004-74182181-2014.",
		"СТО АРСС 1 1251254.001-018-03.",
	}
	for i, it := range items {
		pdf.SetFont("tn", "", 9.5)
		pdf.SetX(25)
		pdf.CellFormat(6, 5, fmt.Sprintf("%d.", i+1), "", 0, "L", false, 0, "")
		pdf.MultiCell(162, 5, it, "", "L", false)
		pdf.Ln(1.5)
	}
}
