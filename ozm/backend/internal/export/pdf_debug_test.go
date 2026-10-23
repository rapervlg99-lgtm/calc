package export

import (
	"bytes"
	"fmt"
	"os"
	"testing"

	"github.com/jung-kurt/gofpdf"
)

// Отладочная страница с формулами таблицы 2 — чтобы проверять их вёрстку
// отдельно от таблицы. Запуск:
//
//	OZM_DEBUG_FORMULA_OUT=formulas.pdf go test ./internal/export/ -run TestDebugFormula
func TestDebugFormulaLayout(t *testing.T) {
	out := os.Getenv("OZM_DEBUG_FORMULA_OUT")
	if out == "" {
		t.Skip("нет OZM_DEBUG_FORMULA_OUT")
	}
	pdf := gofpdf.New("P", "mm", "A4", "")
	pdf.SetMargins(20, 20, 15)
	pdf.AddUTF8FontFromBytes("tns", "", dejaVuSerif)
	pdf.AddUTF8FontFromBytes("tns", "I", dejaVuSerifItalic)
	pdf.AddUTF8FontFromBytes("tn", "", dejaVuSans)
	pdf.AddPage()

	b := &pdfBuilder{pdf: pdf}
	rows := b.formulaRows()
	y := 30.0
	pdf.SetFont("tn", "", 8)
	pdf.SetXY(20, 20)
	pdf.CellFormat(0, 5, "Формулы таблицы 2 (построчно)", "", 1, "L", false, 0, "")
	for i, row := range rows {
		if row.group {
			continue
		}
		pdf.SetFont("tn", "", 7)
		pdf.SetXY(20, y-4)
		pdf.CellFormat(60, 4, fmt.Sprintf("строка %d", i), "", 0, "L", false, 0, "")
		pdf.Line(20, y-4.6, 190, y-4.6)
		y += 2
		for col, fns := range row.formulas {
			yy := y
			for _, fn := range fns {
				drawFormula(pdf, 70+float64(col-2)*55, yy, 7, fn)
				yy += 5
			}
		}
		if row.sketches != nil {
			for _, fn := range row.sketches {
				fn(pdf, 22, y, 26, 26)
			}
		}
		y += 30
	}
	var buf bytes.Buffer
	if err := pdf.Output(&buf); err != nil {
		t.Fatalf("output: %v", err)
	}
	if err := os.WriteFile(out, buf.Bytes(), 0o644); err != nil {
		t.Fatal(err)
	}
}
