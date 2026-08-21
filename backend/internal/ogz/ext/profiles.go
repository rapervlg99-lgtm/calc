package ext

import (
	"encoding/json"
	"net/http"

	"ozm/backend/internal/ogz/auth"
	"ozm/backend/internal/ogz/sortament"
)

// listProfiles отдаёт справочник масс профилей (глобальные + записи владельца).
func (h *handlers) listProfiles(w http.ResponseWriter, r *http.Request) {
	p, ok := auth.PrincipalFrom(r.Context())
	if !ok {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	refs, err := h.app.Profiles.List(r.Context(), p.Sub)
	if err != nil {
		h.app.Log.Error().Err(err).Msg("list profiles")
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "internal"})
		return
	}
	out := make([]map[string]any, 0, len(refs))
	for _, ref := range refs {
		out = append(out, map[string]any{
			"id":           ref.ID,
			"mark":         ref.Mark,
			"massPerMeter": ref.MassPerMeter,
			"source":       ref.Source,
		})
	}
	writeJSON(w, http.StatusOK, out)
}

type profileInput struct {
	Mark         string  `json:"mark"`
	MassPerMeter float64 `json:"massPerMeter"`
}

// createProfile сохраняет ручной ввод массы профиля в справочник владельца (ТЗ §5).
func (h *handlers) createProfile(w http.ResponseWriter, r *http.Request) {
	p, ok := auth.PrincipalFrom(r.Context())
	if !ok {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var in profileInput
	if err := json.NewDecoder(r.Body).Decode(&in); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "bad_body"})
		return
	}
	mark := sortament.Normalize(in.Mark)
	if mark == "" || in.MassPerMeter <= 0 {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "mark_and_mass_required"})
		return
	}
	if err := h.app.Profiles.Put(r.Context(), mark, in.MassPerMeter, sortament.SourceManual, p.Sub); err != nil {
		h.app.Log.Error().Err(err).Msg("create profile")
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "internal"})
		return
	}
	writeJSON(w, http.StatusCreated, map[string]any{
		"mark":         mark,
		"massPerMeter": in.MassPerMeter,
		"source":       sortament.SourceManual,
	})
}
