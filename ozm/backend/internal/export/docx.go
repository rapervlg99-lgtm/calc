package export

import (
	"archive/zip"
	"bytes"
	"fmt"
	"strconv"
	"strings"
)

// Мини-сборщик DOCX (OOXML) без внешних зависимостей: абзацы с оформленными
// фрагментами, таблицы с объединёнными ячейками, картинки, колонтитулы, разрывы
// страниц и поля (номер страницы, оглавление). Нужен, чтобы Word-выгрузка
// повторяла структуру PDF-отчёта, а не была текстовой заглушкой.
//
// Единицы: размеры в миллиметрах на входе, внутри — twips (1 мм ≈ 56,7) и EMU
// для картинок (1 мм = 36000 EMU).

const (
	twipsPerMM = 56.6929
	emuPerMM   = 36000
)

// docxRun — фрагмент абзаца с оформлением.
type docxRun struct {
	Text  string
	Bold  bool
	Ital  bool
	Font  string  // «Arial», «Times New Roman»; пусто — Arial
	Size  float64 // пункты; 0 — 10
	Color string  // RRGGBB без #
	Sub   bool
	Sup   bool
}

// docxCell — ячейка таблицы. Текст можно задать либо одним полем Text, либо
// готовыми фрагментами Runs (с оформлением).
type docxCell struct {
	Text string
	RowH float64 // высота строки, мм (для полос титула)
	// картинка в ячейке (схемы сечений таблицы 2)
	ImageName string
	ImageData []byte
	ImageW    float64
	ImageH    float64
	Runs      []docxRun
	Span      int    // объединение по горизонтали (1 — обычная)
	Align     string // left|center|right
	Fill      string // фон RRGGBB
	Bold      bool
	Size      float64 // пункты для всей ячейки
}

type docxMedia struct {
	Name string
	Data []byte
}

// docxDoc собирает тело документа и служебные части пакета.
type docxDoc struct {
	body   strings.Builder
	media  []docxMedia
	images map[string]string // имя → rId
	nextID int
	title  string
	header func(d *docxDoc) []byte
	footer func(d *docxDoc) []byte
}

func newDocx() *docxDoc { return &docxDoc{images: map[string]string{}} }

// ---------- оформление ----------

func runXML(r docxRun) string {
	var b strings.Builder
	b.WriteString("<w:r><w:rPr>")
	font := r.Font
	if font == "" {
		font = "Arial"
	}
	b.WriteString(`<w:rFonts w:ascii="` + font + `" w:hAnsi="` + font + `" w:cs="` + font + `"/>`)
	if r.Bold {
		b.WriteString("<w:b/>")
	}
	if r.Ital {
		b.WriteString("<w:i/>")
	}
	size := r.Size
	if size == 0 {
		size = 10
	}
	b.WriteString(`<w:sz w:val="` + strconv.Itoa(int(size*2)) + `"/>`)
	b.WriteString(`<w:szCs w:val="` + strconv.Itoa(int(size*2)) + `"/>`)
	if r.Color != "" {
		b.WriteString(`<w:color w:val="` + r.Color + `"/>`)
	}
	if r.Sub {
		b.WriteString(`<w:vertAlign w:val="subscript"/>`)
	}
	if r.Sup {
		b.WriteString(`<w:vertAlign w:val="superscript"/>`)
	}
	b.WriteString("</w:rPr><w:t xml:space=\"preserve\">")
	b.WriteString(xmlEscape(r.Text))
	b.WriteString("</w:t></w:r>")
	return b.String()
}

// paraXML — абзац: выравнивание, отступы, стиль.
func paraXML(align string, spaceBefore, spaceAfter float64, runs []docxRun, style string) string {
	var b strings.Builder
	b.WriteString("<w:p><w:pPr>")
	if style != "" {
		b.WriteString(`<w:pStyle w:val="` + style + `"/>`)
	}
	if align != "" {
		b.WriteString(`<w:jc w:val="` + align + `"/>`)
	}
	if spaceBefore > 0 || spaceAfter > 0 {
		b.WriteString(fmt.Sprintf(`<w:spacing w:before="%d" w:after="%d"/>`,
			int(spaceBefore*20), int(spaceAfter*20)))
	}
	b.WriteString("</w:pPr>")
	for _, r := range runs {
		b.WriteString(runXML(r))
	}
	b.WriteString("</w:p>")
	return b.String()
}

// Para добавляет абзац.
func (d *docxDoc) Para(align string, runs ...docxRun) {
	d.body.WriteString(paraXML(align, 0, 4, runs, ""))
}

// ParaStyle — абзац со стилем (Heading1/Heading2 — для оглавления).
func (d *docxDoc) ParaStyle(style, align string, runs ...docxRun) {
	d.body.WriteString(paraXML(align, 8, 4, runs, style))
}

// Spacer — пустой абзац-отступ.
func (d *docxDoc) Spacer(pts float64) {
	d.body.WriteString(fmt.Sprintf(`<w:p><w:pPr><w:spacing w:after="%d" w:line="%d" w:lineRule="exact"/></w:pPr></w:p>`,
		int(pts*20), int(pts*20)))
}

// PageBreak — разрыв страницы.
func (d *docxDoc) PageBreak() {
	d.body.WriteString(`<w:p><w:r><w:br w:type="page"/></w:r></w:p>`)
}

func (d *docxDoc) registerImage(name string, data []byte) string {
	if rid, ok := d.images[name]; ok {
		return rid
	}
	d.media = append(d.media, docxMedia{Name: name, Data: data})
	d.nextID++
	rid := fmt.Sprintf("rIdImg%d", d.nextID)
	d.images[name] = rid
	return rid
}

// ImageSize — картинка заданного размера (мм).
func (d *docxDoc) ImageSize(name string, data []byte, widthMM, heightMM float64, align string) {
	rid := d.registerImage(name, data)
	d.nextID++
	d.body.WriteString(inlineImage(rid, fmt.Sprintf("img%d", d.nextID),
		int(widthMM*emuPerMM), int(heightMM*emuPerMM), align))
}

func inlineImage(rid, name string, cx, cy int, align string) string {
	var b strings.Builder
	b.WriteString("<w:p><w:pPr>")
	if align != "" {
		b.WriteString(`<w:jc w:val="` + align + `"/>`)
	}
	b.WriteString("</w:pPr><w:r><w:drawing>")
	b.WriteString(`<wp:inline distT="0" distB="0" distL="0" distR="0">`)
	b.WriteString(fmt.Sprintf(`<wp:extent cx="%d" cy="%d"/>`, cx, cy))
	b.WriteString(fmt.Sprintf(`<wp:docPr id="%d" name="%s"/>`, cy+cx, name))
	b.WriteString(`<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">`)
	b.WriteString(`<pic:pic>`)
	b.WriteString(`<pic:nvPicPr><pic:cNvPr id="0" name="` + name + `"/><pic:cNvPicPr/></pic:nvPicPr>`)
	b.WriteString(fmt.Sprintf(`<pic:blipFill><a:blip r:embed="%s"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>`, rid))
	b.WriteString(fmt.Sprintf(`<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="%d" cy="%d"/></a:xfrm>`, cx, cy))
	b.WriteString(`<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>`)
	b.WriteString(`</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>`)
	return b.String()
}

// Table рисует таблицу: widths — ширины колонок в мм.
func (d *docxDoc) Table(widths []float64, rows [][]docxCell) {
	d.tableXML(widths, rows, true)
}

// TablePlain — таблица без рамок: раскладка колонтитула и оглавления.
func (d *docxDoc) TablePlain(widths []float64, rows [][]docxCell) {
	d.tableXML(widths, rows, false)
}

func (d *docxDoc) tableXML(widths []float64, rows [][]docxCell, borders bool) {
	// Ширина полосы набора A4 при полях 25/15 мм — 170 мм. Внутри ячеек есть
	// отступы (по ~0,55 мм с каждой стороны), поэтому колонки масштабируем так,
	// чтобы таблица не выезжала за поле — как в PDF.
	total := 0.0
	for _, w := range widths {
		total += w
	}
	if borders && total > 0 {
		avail := 170.0 - 1.2*float64(len(widths))
		if total > avail {
			scale := avail / total
			for i := range widths {
				widths[i] *= scale
			}
			total = 0
			for _, w := range widths {
				total += w
			}
		}
	}
	var b strings.Builder
	b.WriteString("<w:tbl><w:tblPr>")
	b.WriteString(fmt.Sprintf(`<w:tblW w:w="%d" w:type="dxa"/>`, int(total*twipsPerMM)))
	if borders {
		b.WriteString(`<w:tblBorders>`)
		for _, side := range []string{"top", "left", "bottom", "right", "insideH", "insideV"} {
			b.WriteString(fmt.Sprintf(`<w:%s w:val="single" w:sz="4" w:space="0" w:color="808080"/>`, side))
		}
		b.WriteString(`</w:tblBorders>`)
	} else {
		b.WriteString(`<w:tblBorders>`)
		for _, side := range []string{"top", "left", "bottom", "right", "insideH", "insideV"} {
			b.WriteString(fmt.Sprintf(`<w:%s w:val="none" w:sz="0" w:space="0" w:color="FFFFFF"/>`, side))
		}
		b.WriteString(`</w:tblBorders>`)
	}
	b.WriteString(`<w:tblLayout w:type="fixed"/><w:tblCellMar>`)
	b.WriteString(`<w:top w:w="28" w:type="dxa"/><w:left w:w="57" w:type="dxa"/>`)
	b.WriteString(`<w:bottom w:w="28" w:type="dxa"/><w:right w:w="57" w:type="dxa"/></w:tblCellMar>`)
	b.WriteString("</w:tblPr><w:tblGrid>")
	for _, w := range widths {
		b.WriteString(fmt.Sprintf(`<w:gridCol w:w="%d"/>`, int(w*twipsPerMM)))
	}
	b.WriteString("</w:tblGrid>")
	for rowIdx, row := range rows {
		rowH := 0.0
		for _, c := range row {
			if c.RowH > rowH {
				rowH = c.RowH
			}
		}
		b.WriteString("<w:tr>")
		if rowIdx == 0 {
			// шапка повторяется на каждой странице, как в PDF
			b.WriteString(`<w:trPr><w:tblHeader/></w:trPr>`)
		}
		if rowH > 0 {
			b.WriteString(fmt.Sprintf(`<w:trPr><w:trHeight w:val="%d" w:hRule="atLeast"/></w:trPr>`, int(rowH*twipsPerMM)))
		}
		col := 0
		for _, c := range row {
			span := c.Span
			if span <= 0 {
				span = 1
			}
			w := 0.0
			for i := 0; i < span && col+i < len(widths); i++ {
				w += widths[col+i]
			}
			col += span
			b.WriteString("<w:tc><w:tcPr>")
			b.WriteString(fmt.Sprintf(`<w:tcW w:w="%d" w:type="dxa"/>`, int(w*twipsPerMM)))
			if span > 1 {
				b.WriteString(fmt.Sprintf(`<w:gridSpan w:val="%d"/>`, span))
			}
			if c.Fill != "" {
				b.WriteString(`<w:shd w:val="clear" w:color="auto" w:fill="` + c.Fill + `"/>`)
			}
			b.WriteString(`<w:vAlign w:val="center"/></w:tcPr>`)
			runs := make([]docxRun, len(c.Runs))
			copy(runs, c.Runs)
			if len(runs) == 0 && c.Text != "" {
				runs = []docxRun{{Text: c.Text}}
			}
			for i := range runs {
				if c.Bold {
					runs[i].Bold = true
				}
				if c.Size > 0 && runs[i].Size == 0 {
					runs[i].Size = c.Size
				}
			}
			if len(c.ImageData) > 0 {
				rid := d.registerImage(c.ImageName, c.ImageData)
				b.WriteString(inlineImage(rid, c.ImageName,
					int(c.ImageW*emuPerMM), int(c.ImageH*emuPerMM), c.Align))
			} else {
				b.WriteString(paraXML(c.Align, 0, 0, runs, ""))
			}
			b.WriteString("</w:tc>")
		}
		b.WriteString("</w:tr>")
	}
	b.WriteString("</w:tbl>")
	d.body.WriteString(b.String())
	d.Spacer(2)
}

// SetHeader/SetFooter — колонтитулы (по одному на документ).
func (d *docxDoc) SetHeader(fn func(d *docxDoc) []byte) { d.header = fn }
func (d *docxDoc) SetFooter(fn func(d *docxDoc) []byte) { d.footer = fn }

// TOC — поле оглавления. Результат заполняем списком разделов: до обновления
// полей в Word видно структуру, после обновления (F9) Word подставит номера
// страниц сам (dirty + updateFields).
func (d *docxDoc) TOC(entries []string) {
	d.body.WriteString(`<w:p><w:pPr><w:spacing w:after="120"/></w:pPr>`)
	d.body.WriteString(`<w:r><w:fldChar w:fldCharType="begin" w:dirty="true"/></w:r>`)
	d.body.WriteString(`<w:r><w:instrText xml:space="preserve"> TOC \o "1-2" \h \z \u </w:instrText></w:r>`)
	d.body.WriteString(`<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t xml:space="preserve"> </w:t></w:r>`)
	d.body.WriteString(`</w:p>`)
	for _, e := range entries {
		d.body.WriteString(`<w:p><w:pPr><w:spacing w:after="60"/></w:pPr>`)
		d.body.WriteString(`<w:r><w:rPr><w:sz w:val="19"/></w:rPr><w:t xml:space="preserve">` + xmlEscape(e) + `</w:t></w:r>`)
		d.body.WriteString(`</w:p>`)
	}
	d.body.WriteString(`<w:p><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>`)
}

// pageFieldXML — поле номера страницы.
func pageFieldXML(size float64) string {
	return fmt.Sprintf(`<w:fldSimple w:instr=" PAGE "><w:r><w:rPr><w:sz w:val="%d"/></w:rPr><w:t>1</w:t></w:r></w:fldSimple>`,
		int(size*2))
}

// ---------- сборка пакета ----------

func (d *docxDoc) Bytes() ([]byte, error) {
	var buf bytes.Buffer
	zw := zip.NewWriter(&buf)
	write := func(name, content string) error {
		w, err := zw.Create(name)
		if err != nil {
			return err
		}
		_, err = w.Write([]byte(content))
		return err
	}

	var ct strings.Builder
	ct.WriteString(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>`)
	ct.WriteString(`<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">`)
	ct.WriteString(`<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>`)
	ct.WriteString(`<Default Extension="xml" ContentType="application/xml"/>`)
	ct.WriteString(`<Default Extension="png" ContentType="image/png"/>`)
	ct.WriteString(`<Default Extension="jpg" ContentType="image/jpeg"/>`)
	ct.WriteString(`<Default Extension="jpeg" ContentType="image/jpeg"/>`)
	ct.WriteString(`<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>`)
	ct.WriteString(`<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>`)
	ct.WriteString(`<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>`)
	if d.header != nil {
		ct.WriteString(`<Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>`)
	}
	if d.footer != nil {
		ct.WriteString(`<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>`)
	}
	ct.WriteString(`<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>`)
	ct.WriteString(`<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>`)
	ct.WriteString(`</Types>`)
	if err := write("[Content_Types].xml", ct.String()); err != nil {
		return nil, err
	}

	rels := `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
		`<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">` +
		`<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>` +
		`<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>` +
		`<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>` +
		`</Relationships>`
	if err := write("_rels/.rels", rels); err != nil {
		return nil, err
	}

	var dr strings.Builder
	dr.WriteString(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>`)
	dr.WriteString(`<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">`)
	dr.WriteString(`<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>`)
	dr.WriteString(`<Relationship Id="rIdSettings" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>`)
	if d.header != nil {
		dr.WriteString(`<Relationship Id="rIdHeader" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>`)
	}
	if d.footer != nil {
		dr.WriteString(`<Relationship Id="rIdFooter" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>`)
	}
	for imgName, rid := range d.images {
		dr.WriteString(fmt.Sprintf(`<Relationship Id="%s" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/%s"/>`, rid, imgName))
	}
	dr.WriteString(`</Relationships>`)
	if err := write("word/_rels/document.xml.rels", dr.String()); err != nil {
		return nil, err
	}

	var doc strings.Builder
	doc.WriteString(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>`)
	doc.WriteString(`<w:document ` + docNamespaces + `><w:body>`)
	doc.WriteString(d.body.String())
	doc.WriteString(d.sectPr())
	doc.WriteString(`</w:body></w:document>`)
	if err := write("word/document.xml", doc.String()); err != nil {
		return nil, err
	}

	if err := write("word/styles.xml", docxStyles); err != nil {
		return nil, err
	}
	if err := write("word/settings.xml", docxSettings); err != nil {
		return nil, err
	}

	// картинки из колонтитула подключаются в его собственных rels: rId в
	// header1.xml резолвятся против header1.xml.rels, а не document.xml.rels
	imagesRels := func() string {
		var ir strings.Builder
		ir.WriteString(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>`)
		ir.WriteString(`<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">`)
		for imgName, rid := range d.images {
			ir.WriteString(fmt.Sprintf(`<Relationship Id="%s" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/%s"/>`, rid, imgName))
		}
		ir.WriteString(`</Relationships>`)
		return ir.String()
	}
	if d.header != nil {
		var h strings.Builder
		h.WriteString(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>`)
		h.WriteString(`<w:hdr ` + docNamespaces + `>`)
		h.Write(d.header(d))
		h.WriteString(`</w:hdr>`)
		if err := write("word/header1.xml", h.String()); err != nil {
			return nil, err
		}
		if err := write("word/_rels/header1.xml.rels", imagesRels()); err != nil {
			return nil, err
		}
	}
	if d.footer != nil {
		var f strings.Builder
		f.WriteString(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>`)
		f.WriteString(`<w:ftr ` + docNamespaces + `>`)
		f.Write(d.footer(d))
		f.WriteString(`</w:ftr>`)
		if err := write("word/footer1.xml", f.String()); err != nil {
			return nil, err
		}
		if err := write("word/_rels/footer1.xml.rels", imagesRels()); err != nil {
			return nil, err
		}
	}

	core := `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
		`<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" ` +
		`xmlns:dc="http://purl.org/dc/elements/1.1/">` +
		`<dc:title>` + xmlEscape(d.title) + `</dc:title>` +
		`<dc:creator>ОЗМ — калькулятор огнезащиты ТЕХНОНИКОЛЬ</dc:creator>` +
		`</cp:coreProperties>`
	if err := write("docProps/core.xml", core); err != nil {
		return nil, err
	}
	app := `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
		`<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">` +
		`<Application>ОЗМ</Application></Properties>`
	if err := write("docProps/app.xml", app); err != nil {
		return nil, err
	}

	for _, m := range d.media {
		w, err := zw.Create("word/media/" + m.Name)
		if err != nil {
			return nil, err
		}
		if _, err := w.Write(m.Data); err != nil {
			return nil, err
		}
	}

	if err := zw.Close(); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

// sectPr — параметры страницы: A4, поля, колонтитулы.
func (d *docxDoc) sectPr() string {
	var b strings.Builder
	b.WriteString("<w:sectPr>")
	if d.header != nil {
		b.WriteString(`<w:headerReference w:type="default" r:id="rIdHeader"/>`)
	}
	if d.footer != nil {
		b.WriteString(`<w:footerReference w:type="default" r:id="rIdFooter"/>`)
	}
	b.WriteString(`<w:pgSz w:w="11906" w:h="16838"/>`)
	b.WriteString(`<w:pgMar w:top="1134" w:right="851" w:bottom="1134" w:left="1417" ` +
		`w:header="567" w:footer="567" w:gutter="0"/>`)
	b.WriteString(`<w:titlePg/>`)
	b.WriteString(`<w:cols w:space="708"/>`)
	b.WriteString(`<w:docGrid w:linePitch="360"/>`)
	b.WriteString("</w:sectPr>")
	return b.String()
}

const docNamespaces = `xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" ` +
	`xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" ` +
	`xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" ` +
	`xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" ` +
	`xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"`

// docxStyles — базовые стили: обычный текст Arial 10, заголовки для оглавления.
const docxStyles = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:docDefaults><w:rPrDefault><w:rPr>
    <w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/>
    <w:sz w:val="20"/><w:szCs w:val="20"/>
  </w:rPr></w:rPrDefault>
  <w:pPrDefault><w:pPr><w:spacing w:after="30" w:line="228" w:lineRule="auto"/></w:pPr></w:pPrDefault>
  </w:docDefaults>
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/>
    <w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
    <w:pPr><w:keepNext/><w:outlineLvl w:val="0"/><w:spacing w:before="240" w:after="120"/></w:pPr>
    <w:rPr><w:b/><w:sz w:val="26"/><w:szCs w:val="26"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/>
    <w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
    <w:pPr><w:keepNext/><w:outlineLvl w:val="1"/><w:spacing w:before="200" w:after="80"/></w:pPr>
    <w:rPr><w:b/><w:sz w:val="21"/><w:szCs w:val="21"/></w:rPr>
  </w:style>
</w:styles>`

const docxSettings = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:zoom w:percent="100"/>
  <w:defaultTabStop w:val="708"/>
  <w:updateFields w:val="true"/>
  <w:compat><w:compatSetting w:name="compatibilityMode" w:uri="http://schemas.microsoft.com/office/word" w:val="15"/></w:compat>
</w:settings>`

// xmlEscape — экранирование текста для OOXML.
func xmlEscape(s string) string {
	r := strings.NewReplacer("&", "&amp;", "<", "&lt;", ">", "&gt;", `"`, "&quot;", "'", "&apos;")
	return r.Replace(s)
}
