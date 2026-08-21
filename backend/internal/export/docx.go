package export

import (
	"archive/zip"
	"bytes"
	"fmt"
	"strings"

	"ozm/backend/internal/models"
)

func buildMinimalDocx(resp models.CalcResponse) ([]byte, error) {
	var body strings.Builder
	body.WriteString(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>`)
	body.WriteString(`<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>`)
	p := func(text string) {
		body.WriteString(`<w:p><w:r><w:t>`)
		body.WriteString(xmlEscape(text))
		body.WriteString(`</w:t></w:r></w:p>`)
	}
	p("Расчёт огнезащиты конструкций")
	p("Объект: " + resp.Inputs.ObjectName)
	p("Адрес: " + resp.Inputs.Address)
	p("")
	p("Элементы:")
	for _, el := range resp.Elements {
		p(fmt.Sprintf("%s | %s | δпр=%.1f δ=%.1f %s", el.Title, el.Shape, el.Dpr, el.Delta, el.Exclusion))
	}
	p("")
	p("Материалы:")
	for _, m := range resp.Materials {
		p(fmt.Sprintf("%s — %.3f %s", m.Title, m.Quantity, m.Unit))
	}
	body.WriteString(`<w:sectPr/></w:body></w:document>`)

	var buf bytes.Buffer
	zw := zip.NewWriter(&buf)
	files := map[string]string{
		"[Content_Types].xml": `<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>`,
		"_rels/.rels": `<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>`,
		"word/document.xml": body.String(),
	}
	for name, content := range files {
		w, err := zw.Create(name)
		if err != nil {
			return nil, err
		}
		if _, err := w.Write([]byte(content)); err != nil {
			return nil, err
		}
	}
	if err := zw.Close(); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

func xmlEscape(s string) string {
	s = strings.ReplaceAll(s, "&", "&amp;")
	s = strings.ReplaceAll(s, "<", "&lt;")
	s = strings.ReplaceAll(s, ">", "&gt;")
	return s
}
