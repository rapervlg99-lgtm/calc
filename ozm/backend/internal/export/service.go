package export

import (
	"bytes"
	"fmt"
	"strings"

	"github.com/jung-kurt/gofpdf"
	"github.com/xuri/excelize/v2"

	"ozm/backend/internal/config"
	"ozm/backend/internal/models"
)

// Service формирует выгрузки расчёта. Справочники нужны спецификации:
// марки проката (тип профиля), расходы и толщины слоёв материалов, таблицы x500
// и коэффициенты расчёта.
type Service struct {
	cfg *config.Store
}

func New(cfg *config.Store) *Service { return &Service{cfg: cfg} }

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

// XLSX собирает спецификацию по системам (см. xlsx_report.go): лист на систему,
// блок цен, многоуровневая шапка, группы конструкций, формулы и ИТОГО.
func (s *Service) XLSX(resp models.CalcResponse) ([]byte, error) {
	sheets := s.buildSheets(resp)
	f := excelize.NewFile()
	if len(sheets) == 0 {
		// расчёт без конструкций: пустой лист с заголовком, чтобы файл открывался
		_ = f.SetSheetName("Sheet1", "Спецификация")
		_ = f.SetCellValue("Спецификация", "B2", reportTitle(resp, "T.M. TAIKOR"))
		buf, err := f.WriteToBuffer()
		if err != nil {
			return nil, err
		}
		return buf.Bytes(), nil
	}
	for i, sh := range sheets {
		if i == 0 {
			if err := f.SetSheetName("Sheet1", sh.Name); err != nil {
				return nil, err
			}
		} else if _, err := f.NewSheet(sh.Name); err != nil {
			return nil, err
		}
		if err := s.writeSheet(f, sh, resp); err != nil {
			return nil, err
		}
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
