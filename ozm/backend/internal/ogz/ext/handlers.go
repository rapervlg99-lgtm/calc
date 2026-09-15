package ext

import (
	"bytes"
	"database/sql"
	"errors"
	"io"
	"mime/multipart"
	"net/http"

	"github.com/google/uuid"
	"github.com/go-chi/chi/v5"

	"ozm/backend/internal/ogz/auth"
	"ozm/backend/internal/ogz/bootstrap"
	"ozm/backend/internal/ogz/storage"
)

type handlers struct{ app *bootstrap.App }

// pdfMagic — сигнатура начала PDF-файла (header чертежа/спецификации).
var pdfMagic = []byte("%PDF-")

var (
	errFileRequired = errors.New("file required")
	errNotPDF       = errors.New("not a pdf")
)

// createJob accepts a multipart PDF upload, stores it, registers a job, and
// enqueues the recognition pipeline (ingest → LLM-vision → форма ОГЗ). Обработка
// идёт в фоне; клиент опрашивает статус через GET /jobs/{id}.
func (h *handlers) createJob(w http.ResponseWriter, r *http.Request) {
	p, ok := auth.PrincipalFrom(r.Context())
	if !ok {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}

	// Ограничиваем тело до парсинга — защита от oversized-загрузок.
	r.Body = http.MaxBytesReader(w, r.Body, h.app.Cfg.MaxUploadBytes)
	file, header, err := r.FormFile("file")
	if err != nil {
		var maxErr *http.MaxBytesError
		if errors.As(err, &maxErr) {
			writeJSON(w, http.StatusRequestEntityTooLarge, map[string]string{"error": "file_too_large"})
			return
		}
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "file_required"})
		return
	}
	defer file.Close()

	if err := validateUpload(file, header); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid_pdf"})
		return
	}

	id := uuid.NewString()
	key := "jobs/" + id + "/source.pdf"
	if _, err := h.app.Blob.Put(r.Context(), key, "application/pdf", file); err != nil {
		h.app.Log.Error().Err(err).Msg("store pdf")
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "internal"})
		return
	}

	job := storage.Job{
		ID:           id,
		OwnerSub:     p.Sub,
		Status:       storage.JobStatusPending,
		SourcePDFKey: key,
	}
	if err := h.app.Jobs.Create(r.Context(), job); err != nil {
		h.app.Log.Error().Err(err).Msg("create job")
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "internal"})
		return
	}
	h.app.Metrics.JobsTotal.WithLabelValues(job.Status).Inc()

	// Фоновая обработка: рендер страниц → vision-распознавание → форма ОГЗ.
	h.app.Pipeline.Enqueue(job.ID, job.OwnerSub, job.SourcePDFKey)

	writeJSON(w, http.StatusCreated, map[string]string{"id": job.ID, "status": job.Status})
}

// validateUpload rejects empty files and anything that is not a PDF (by magic
// bytes, not by the client-declared content-type). The reader is rewound so the
// caller can stream it to storage afterwards.
func validateUpload(file multipart.File, header *multipart.FileHeader) error {
	if header == nil || header.Size == 0 {
		return errFileRequired
	}
	return looksLikePDF(file)
}

func looksLikePDF(rs io.ReadSeeker) error {
	buf := make([]byte, len(pdfMagic))
	n, err := io.ReadFull(rs, buf)
	if err != nil && !errors.Is(err, io.ErrUnexpectedEOF) {
		return err
	}
	if _, seekErr := rs.Seek(0, io.SeekStart); seekErr != nil {
		return seekErr
	}
	if n < len(pdfMagic) || !bytes.HasPrefix(buf, pdfMagic) {
		return errNotPDF
	}
	return nil
}

// getJob returns a job owned by the caller (ownership enforced in storage).
func (h *handlers) getJob(w http.ResponseWriter, r *http.Request) {
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
	rows, err := h.app.OgzRows.ListByJob(r.Context(), id, p.Sub)
	if err != nil {
		h.app.Log.Error().Err(err).Msg("list ogz rows")
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "internal"})
		return
	}
	profileRows, sheetRows := []any{}, []any{}
	for _, row := range rows {
		if row.IsSheet {
			sheetRows = append(sheetRows, rowJSON(row))
		} else {
			profileRows = append(profileRows, rowJSON(row))
		}
	}
	resp := map[string]any{
		"id":          job.ID,
		"status":      job.Status,
		"confirmed":   job.Confirmed,
		"createdAt":   job.CreatedAt,
		"updatedAt":   job.UpdatedAt,
		"profileRows": profileRows,
		"sheetRows":   sheetRows,
	}
	if job.ConfirmedAt.Valid {
		resp["confirmedAt"] = job.ConfirmedAt.Time
	}
	writeJSON(w, http.StatusOK, resp)
}
