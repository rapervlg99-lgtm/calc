package export

import (
	"bytes"
	"fmt"
	"strings"

	"github.com/jung-kurt/gofpdf"
	"github.com/xuri/excelize/v2"

	"ozm/backend/internal/models"
)

type Service struct{}

func New() *Service { return &Service{} }

func (s *Service) PDF(resp models.CalcResponse) ([]byte, error) {
	pdf := gofpdf.New("P", "mm", "A4", "")
	pdf.SetTitle("Расчёт огнезащиты — "+resp.Inputs.ObjectName, false)
	pdf.AddPage()
	pdf.SetFont("Arial", "B", 14)
	pdf.Cell(0, 10, toLatin("Расчёт огнезащиты конструкций"))
	pdf.Ln(12)
	pdf.SetFont("Arial", "", 11)
	pdf.Cell(0, 7, toLatin("Объект: "+resp.Inputs.ObjectName))
	pdf.Ln(7)
	pdf.Cell(0, 7, toLatin("Адрес: "+resp.Inputs.Address))
	pdf.Ln(10)
	pdf.SetFont("Arial", "B", 12)
	pdf.Cell(0, 8, toLatin("Элементы"))
	pdf.Ln(8)
	pdf.SetFont("Arial", "", 10)
	for _, el := range resp.Elements {
		line := fmt.Sprintf("%s | %s | dpr=%.1f d=%.1f | %s", el.Title, el.Shape, el.Dpr, el.Delta, el.Exclusion)
		pdf.MultiCell(0, 6, toLatin(line), "", "", false)
	}
	pdf.Ln(6)
	pdf.SetFont("Arial", "B", 12)
	pdf.Cell(0, 8, toLatin("Материалы"))
	pdf.Ln(8)
	pdf.SetFont("Arial", "", 10)
	for _, m := range resp.Materials {
		pdf.Cell(0, 6, toLatin(fmt.Sprintf("%s — %.3f %s", m.Title, m.Quantity, m.Unit)))
		pdf.Ln(6)
	}
	var buf bytes.Buffer
	if err := pdf.Output(&buf); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

func (s *Service) XLSX(resp models.CalcResponse) ([]byte, error) {
	f := excelize.NewFile()
	sheet := "Отчёт"
	_ = f.SetSheetName("Sheet1", sheet)
	_ = f.SetCellValue(sheet, "A1", "Расчёт огнезащиты")
	_ = f.SetCellValue(sheet, "A2", "Объект")
	_ = f.SetCellValue(sheet, "B2", resp.Inputs.ObjectName)
	_ = f.SetCellValue(sheet, "A3", "Адрес")
	_ = f.SetCellValue(sheet, "B3", resp.Inputs.Address)

	_ = f.SetCellValue(sheet, "A5", "Элемент")
	_ = f.SetCellValue(sheet, "B5", "Профиль")
	_ = f.SetCellValue(sheet, "C5", "δпр")
	_ = f.SetCellValue(sheet, "D5", "δ")
	_ = f.SetCellValue(sheet, "E5", "Исключение")
	row := 6
	for _, el := range resp.Elements {
		_ = f.SetCellValue(sheet, fmt.Sprintf("A%d", row), el.Title)
		_ = f.SetCellValue(sheet, fmt.Sprintf("B%d", row), el.Shape)
		_ = f.SetCellValue(sheet, fmt.Sprintf("C%d", row), el.Dpr)
		_ = f.SetCellValue(sheet, fmt.Sprintf("D%d", row), el.Delta)
		_ = f.SetCellValue(sheet, fmt.Sprintf("E%d", row), el.Exclusion)
		row++
	}
	row += 2
	_ = f.SetCellValue(sheet, fmt.Sprintf("A%d", row), "Материал")
	_ = f.SetCellValue(sheet, fmt.Sprintf("B%d", row), "Кол-во")
	_ = f.SetCellValue(sheet, fmt.Sprintf("C%d", row), "Ед.")
	_ = f.SetCellValue(sheet, fmt.Sprintf("D%d", row), "Цена ед., руб")
	_ = f.SetCellValue(sheet, fmt.Sprintf("E%d", row), "Сумма, руб")
	row++
	start := row
	for _, m := range resp.Materials {
		_ = f.SetCellValue(sheet, fmt.Sprintf("A%d", row), m.Title)
		_ = f.SetCellValue(sheet, fmt.Sprintf("B%d", row), m.Quantity)
		_ = f.SetCellValue(sheet, fmt.Sprintf("C%d", row), m.Unit)
		_ = f.SetCellValue(sheet, fmt.Sprintf("D%d", row), float64(m.UnitPriceCents)/100)
		_ = f.SetCellFormula(sheet, fmt.Sprintf("E%d", row), fmt.Sprintf("B%d*D%d", row, row))
		row++
	}
	if row > start {
		_ = f.SetCellValue(sheet, fmt.Sprintf("A%d", row), "Итого")
		_ = f.SetCellFormula(sheet, fmt.Sprintf("E%d", row), fmt.Sprintf("SUM(E%d:E%d)", start, row-1))
	}
	buf, err := f.WriteToBuffer()
	if err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

func (s *Service) DOCX(resp models.CalcResponse) ([]byte, error) {
	// Minimal OOXML Word package as ZIP-like flat XML alternative:
	// produce a simple UTF-8 text document wrapped as docx-compatible minimal package is heavy;
	// for parity scaffold we emit a UTF-8 "Word HTML" that Word opens, stored as .docx bytes via simple document.xml zip.
	return buildMinimalDocx(resp)
}

// toLatin transliterates common Cyrillic for core font Arial in gofpdf without UTF-8 font files.
func toLatin(s string) string {
	repl := strings.NewReplacer(
		"а", "a", "б", "b", "в", "v", "г", "g", "д", "d", "е", "e", "ё", "e", "ж", "zh",
		"з", "z", "и", "i", "й", "y", "к", "k", "л", "l", "м", "m", "н", "n", "о", "o",
		"п", "p", "р", "r", "с", "s", "т", "t", "у", "u", "ф", "f", "х", "h", "ц", "c",
		"ч", "ch", "ш", "sh", "щ", "sch", "ъ", "", "ы", "y", "ь", "", "э", "e", "ю", "yu", "я", "ya",
		"А", "A", "Б", "B", "В", "V", "Г", "G", "Д", "D", "Е", "E", "Ё", "E", "Ж", "Zh",
		"З", "Z", "И", "I", "Й", "Y", "К", "K", "Л", "L", "М", "M", "Н", "N", "О", "O",
		"П", "P", "Р", "R", "С", "S", "Т", "T", "У", "U", "Ф", "F", "Х", "H", "Ц", "C",
		"Ч", "Ch", "Ш", "Sh", "Щ", "Sch", "Ъ", "", "Ы", "Y", "Ь", "", "Э", "E", "Ю", "Yu", "Я", "Ya",
		"δ", "d", "п", "p", "р", "r",
	)
	return repl.Replace(s)
}
