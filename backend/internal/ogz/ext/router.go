package ext

import (
	"encoding/json"
	"net/http"

	"github.com/go-chi/chi/v5"

	"ozm/backend/internal/ogz/bootstrap"
)

// Mount registers authenticated OCR routes under /ext on a chi router
// that is already mounted at /api/v1 (→ /api/v1/ext/...).
func Mount(r chi.Router, app *bootstrap.App) {
	h := &handlers{app: app}
	r.Route("/ext", func(r chi.Router) {
		r.Use(app.Auth.Middleware)
		r.Post("/jobs", h.createJob)
		r.Get("/jobs/{id}", h.getJob)
		r.Post("/jobs/{id}/rows", h.createRow)
		r.Patch("/jobs/{id}/rows/{rowId}", h.patchRow)
		r.Post("/jobs/{id}/rows/{rowId}/copy", h.copyRow)
		r.Delete("/jobs/{id}/rows/{rowId}", h.deleteRow)
		r.Post("/jobs/{id}/confirm", h.confirmJob)
		r.Get("/jobs/{id}/prefill", h.getPrefill)
		r.Get("/profiles", h.listProfiles)
		r.Post("/profiles", h.createProfile)
	})
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}
