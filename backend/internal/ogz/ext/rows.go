package ext

import (
	"database/sql"
	"encoding/json"
	"errors"
	"net/http"
	"strconv"

	"github.com/go-chi/chi/v5"

	"ozm/backend/internal/ogz/auth"
	"ozm/backend/internal/ogz/ogzform"
	"ozm/backend/internal/ogz/prefill"
	"ozm/backend/internal/ogz/sortament"
	"ozm/backend/internal/ogz/storage"
)

// rowJSON отображает строку формы ОГЗ в JSON по схеме OpenAPI OgzRow.
func rowJSON(r storage.OgzRow) map[string]any {
	return map[string]any{
		"id":             r.ID,
		"name":           r.Name,
		"profileMark":    r.ProfileMark,
		"profileRaw":     r.ProfileRaw,
		"gostProfile":    r.GostProfile,
		"steelGrade":     r.SteelGrade,
		"ppNumber":       r.PPNumber,
		"construction":   r.Construction,
		"mass":           r.Mass,
		"massUnit":       "kg",
		"massPerMeter":   r.MassPerMeter,
		"massSource":     r.MassSource,
		"sourceUrl":      r.SourceURL,
		"isSheet":        r.IsSheet,
		"lengthM":        r.LengthM,
		"areaM2":         r.AreaM2,
		"classification": r.Classification,
		"status":         r.Status,
		"heatingSides":   r.HeatingSides,
		"fireLimit":      r.FireLimit,
		"bearingType":    r.BearingType,
		"coatingType":    r.CoatingType,
	}
}

// rowPatch — частичная правка строки. Указатели отличают «поле задано» от «нуля».
type rowPatch struct {
	ProfileMark    *string  `json:"profileMark"`
	MassPerMeter   *float64 `json:"massPerMeter"`
	LengthM        *float64 `json:"lengthM"`
	Classification *string  `json:"classification"`
	Status         *string  `json:"status"`
	HeatingSides   *string  `json:"heatingSides"`
	FireLimit      *string  `json:"fireLimit"`
	BearingType    *string  `json:"bearingType"`
	CoatingType    *string  `json:"coatingType"`
	Construction   *string  `json:"construction"`
	Name           *string  `json:"name"`
}

// patchRow применяет правку строки: пересчитывает погонаж/площадь и статус (если
// статус не задан вручную) и сохраняет ручную массу в локальный справочник.
func (h *handlers) patchRow(w http.ResponseWriter, r *http.Request) {
	p, ok := auth.PrincipalFrom(r.Context())
	if !ok {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	jobID := chi.URLParam(r, "id")
	rowID, err := strconv.ParseInt(chi.URLParam(r, "rowId"), 10, 64)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "bad_row_id"})
		return
	}
	var patch rowPatch
	if err := json.NewDecoder(r.Body).Decode(&patch); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "bad_body"})
		return
	}

	row, err := h.app.OgzRows.GetRow(r.Context(), jobID, rowID, p.Sub)
	if errors.Is(err, sql.ErrNoRows) {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "not_found"})
		return
	}
	if err != nil {
		h.app.Log.Error().Err(err).Msg("get row")
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "internal"})
		return
	}

	manualMass := false
	if patch.ProfileMark != nil {
		row.ProfileMark = sortament.Normalize(*patch.ProfileMark)
	}
	if patch.MassPerMeter != nil {
		row.MassPerMeter = *patch.MassPerMeter
		row.MassSource = sortament.SourceManual
		manualMass = true
	}
	if patch.Classification != nil {
		row.Classification = *patch.Classification
	}
	applyStr(&row.HeatingSides, patch.HeatingSides)
	applyStr(&row.FireLimit, patch.FireLimit)
	applyStr(&row.BearingType, patch.BearingType)
	applyStr(&row.CoatingType, patch.CoatingType)
	applyStr(&row.Construction, patch.Construction)
	applyStr(&row.Name, patch.Name)

	// Пересчёт, если статус не переопределён вручную (специалист может зафиксировать).
	if patch.Status != nil {
		row.Status = *patch.Status
	} else if patch.LengthM == nil {
		// Ручной lengthM — override: не перетираем погонаж из массы.
		row.LengthM, row.AreaM2, row.Status = ogzform.Recompute(row.Name, row.Construction, row.Mass, row.MassPerMeter, row.IsSheet)
	} else {
		_, area, status := ogzform.Recompute(row.Name, row.Construction, row.Mass, row.MassPerMeter, row.IsSheet)
		row.AreaM2 = area
		row.Status = status
	}
	if patch.LengthM != nil {
		row.LengthM = *patch.LengthM
	}

	if err := h.app.OgzRows.Update(r.Context(), jobID, rowID, p.Sub, row); err != nil {
		h.app.Log.Error().Err(err).Msg("update row")
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "internal"})
		return
	}
	// Ручную массу сохраняем в справочник владельца для повторного использования (ТЗ §5).
	if manualMass && row.ProfileMark != "" && row.MassPerMeter > 0 {
		if err := h.app.Profiles.Put(r.Context(), row.ProfileMark, row.MassPerMeter, sortament.SourceManual, p.Sub); err != nil {
			h.app.Log.Warn().Err(err).Msg("cache manual mass")
		}
	}
	writeJSON(w, http.StatusOK, rowJSON(row))
}

// createRow добавляет пустую профильную строку для ручного заполнения.
func (h *handlers) createRow(w http.ResponseWriter, r *http.Request) {
	p, ok := auth.PrincipalFrom(r.Context())
	if !ok {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	jobID := chi.URLParam(r, "id")
	row, err := h.app.OgzRows.CreateManual(r.Context(), jobID, p.Sub, storage.OgzRow{
		JobID:          jobID,
		Name:           "Элемент",
		Construction:   "Балки",
		MassUnit:       "kg",
		Classification: "учитывается",
		Status:         "Нужен ввод массы",
		HeatingSides:   "4",
		LengthM:        1,
		IsSheet:        false,
		UserEdited:     true,
	})
	if errors.Is(err, sql.ErrNoRows) {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "not_found"})
		return
	}
	if err != nil {
		h.app.Log.Error().Err(err).Msg("create row")
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "internal"})
		return
	}
	writeJSON(w, http.StatusCreated, rowJSON(row))
}

// copyRow дублирует строку формы ОГЗ.
func (h *handlers) copyRow(w http.ResponseWriter, r *http.Request) {
	p, ok := auth.PrincipalFrom(r.Context())
	if !ok {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	jobID := chi.URLParam(r, "id")
	rowID, err := strconv.ParseInt(chi.URLParam(r, "rowId"), 10, 64)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "bad_row_id"})
		return
	}
	row, err := h.app.OgzRows.Duplicate(r.Context(), jobID, rowID, p.Sub)
	if errors.Is(err, sql.ErrNoRows) {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "not_found"})
		return
	}
	if err != nil {
		h.app.Log.Error().Err(err).Msg("copy row")
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "internal"})
		return
	}
	writeJSON(w, http.StatusCreated, rowJSON(row))
}

// deleteRow удаляет строку формы ОГЗ.
func (h *handlers) deleteRow(w http.ResponseWriter, r *http.Request) {
	p, ok := auth.PrincipalFrom(r.Context())
	if !ok {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	jobID := chi.URLParam(r, "id")
	rowID, err := strconv.ParseInt(chi.URLParam(r, "rowId"), 10, 64)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "bad_row_id"})
		return
	}
	err = h.app.OgzRows.Delete(r.Context(), jobID, rowID, p.Sub)
	if errors.Is(err, sql.ErrNoRows) {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "not_found"})
		return
	}
	if err != nil {
		h.app.Log.Error().Err(err).Msg("delete row")
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "internal"})
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// confirmJob фиксирует апрув формы специалистом (ТЗ §8) — предусловие prefill.
func (h *handlers) confirmJob(w http.ResponseWriter, r *http.Request) {
	p, ok := auth.PrincipalFrom(r.Context())
	if !ok {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	id := chi.URLParam(r, "id")
	err := h.app.Jobs.Confirm(r.Context(), id, p.Sub)
	if errors.Is(err, sql.ErrNoRows) {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "not_found"})
		return
	}
	if err != nil {
		h.app.Log.Error().Err(err).Msg("confirm job")
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "internal"})
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// getPrefill отдаёт payload предзаполнения калькулятора. Доступен только после
// апрува формы (ТЗ §9).
func (h *handlers) getPrefill(w http.ResponseWriter, r *http.Request) {
	p, ok := auth.PrincipalFrom(r.Context())
	if !ok {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	id := chi.URLParam(r, "id")
	job, err := h.app.Jobs.Get(r.Context(), id, p.Sub)
	if errors.Is(err, sql.ErrNoRows) {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "not_found"})
		return
	}
	if err != nil {
		h.app.Log.Error().Err(err).Msg("get job")
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "internal"})
		return
	}
	if !job.Confirmed {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "not_confirmed"})
		return
	}
	rows, err := h.app.OgzRows.ListByJob(r.Context(), id, p.Sub)
	if err != nil {
		h.app.Log.Error().Err(err).Msg("list ogz rows")
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "internal"})
		return
	}
	in := make([]prefill.RowInput, 0, len(rows))
	for _, row := range rows {
		in = append(in, prefill.RowInput{
			ProfileMark:  row.ProfileMark,
			Construction: row.Construction,
			IsSheet:      row.IsSheet,
			LengthM:      row.LengthM,
			AreaM2:       row.AreaM2,
			Status:       row.Status,
			HeatingSides: row.HeatingSides,
			FireLimit:    row.FireLimit,
			BearingType:  row.BearingType,
			CoatingType:  row.CoatingType,
		})
	}
	writeJSON(w, http.StatusOK, prefill.Build(id, in))
}

func applyStr(dst *string, src *string) {
	if src != nil {
		*dst = *src
	}
}
