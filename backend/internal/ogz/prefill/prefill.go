// Package prefill формирует контракт предзаполнения онлайн-калькулятора
// огнезащиты (nav.tn.ru/calculators/fireproof/) из подтверждённой формы ОГЗ
// (ТЗ §9). Контракт проектируем мы; приём реализует команда калькулятора.
// Выгрузки в файлы нет — это структура payload/deeplink.
package prefill

import (
	"strings"

	"ozm/backend/internal/ogz/classify"
)

// Version — версия контракта предзаполнения (для совместимости на стороне калькулятора).
const Version = "1.0"

// RowInput — строка подтверждённой формы (из storage.ogz_rows), нужная для payload.
type RowInput struct {
	ProfileMark  string
	Construction string
	IsSheet      bool
	LengthM      float64
	AreaM2       float64
	Status       string
	HeatingSides string
	FireLimit    string
	BearingType  string
	CoatingType  string
}

// Item — позиция профильного погонажа в калькуляторе.
type Item struct {
	ProfileMark  string  `json:"profileMark"`
	Construction string  `json:"construction,omitempty"`
	LengthM      float64 `json:"lengthM"`
	HeatingSides string  `json:"heatingSides,omitempty"`
	FireLimit    string  `json:"fireLimit,omitempty"`
	BearingType  string  `json:"bearingType,omitempty"`
	CoatingType  string  `json:"coatingType,omitempty"`
}

// Sheet — суммарная листовая сталь.
type Sheet struct {
	AreaM2 float64 `json:"areaM2"`
}

// Payload — контракт предзаполнения калькулятора огнезащиты.
type Payload struct {
	Version string `json:"version"`
	JobID   string `json:"jobId"`
	Items   []Item `json:"items"`
	Sheet   Sheet  `json:"sheet"`
}

// Build собирает payload из подтверждённых строк. В калькулятор попадают только
// рассчитанные строки (статус «Посчитано»/«Требует проверки») с назначенным
// пределом ОС (R); «Не считается» и «Нужен ввод массы» пропускаются.
// Листовая сталь суммируется по площади.
func Build(jobID string, rows []RowInput) Payload {
	p := Payload{Version: Version, JobID: jobID}
	for _, r := range rows {
		if !included(r.Status) {
			continue
		}
		if r.IsSheet {
			p.Sheet.AreaM2 += r.AreaM2
			continue
		}
		if r.LengthM <= 0 {
			continue
		}
		// Без R элемент не уходит из таблицы в калькулятор.
		if strings.TrimSpace(r.FireLimit) == "" {
			continue
		}
		p.Items = append(p.Items, Item{
			ProfileMark:  r.ProfileMark,
			Construction: r.Construction,
			LengthM:      r.LengthM,
			HeatingSides: r.HeatingSides,
			FireLimit:    r.FireLimit,
			BearingType:  r.BearingType,
			CoatingType:  r.CoatingType,
		})
	}
	return p
}

func included(status string) bool {
	return status == classify.StatusCalculated || status == classify.StatusNeedsReview
}
