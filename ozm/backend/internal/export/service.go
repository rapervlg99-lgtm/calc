package export

import (
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
