package api

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"github.com/go-playground/validator/v10"
	"github.com/google/uuid"

	"ozm/backend/internal/bgpersist"
	"ozm/backend/internal/calc"
	"ozm/backend/internal/config"
	"ozm/backend/internal/export"
	"ozm/backend/internal/models"
	"ozm/backend/internal/storage"
	pgstore "ozm/backend/internal/storage/pg"
	ogzbootstrap "ozm/backend/internal/ogz/bootstrap"
	"ozm/backend/internal/ogz/ext"
)

type Persistence struct {
	Calculations storage.CalculationStore
	Exports      storage.ExportStore
	Pool         *bgpersist.Pool
}

type Options struct {
	AllowedOrigins []string
	EnableAPIDocs  bool
	LogPerf        bool
}

type Server struct {
	cfg         *config.Store
	engine      *calc.Engine
	exporter    *export.Service
	validate    *validator.Validate
	persistence Persistence
	opts        Options
	ogzApp      *ogzbootstrap.App
}

func New(cfg *config.Store, engine *calc.Engine, exporter *export.Service, opts Options) *Server {
	return &Server{
		cfg:      cfg,
		engine:   engine,
		exporter: exporter,
		validate: validator.New(),
		opts:     opts,
	}
}

func (s *Server) WithPersistence(p Persistence) *Server {
	s.persistence = p
	return s
}

// WithOgz mounts /api/v1/ext when OCR is enabled.
func (s *Server) WithOgz(app *ogzbootstrap.App) *Server {
	s.ogzApp = app
	return s
}

func (s *Server) Router() http.Handler {
	r := chi.NewRouter()
	r.Use(middleware.RequestID)
	r.Use(middleware.RealIP)
	r.Use(middleware.Recoverer)
	r.Use(s.cors)

	r.Get("/healthz", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	})

	if s.ogzApp != nil && s.ogzApp.Metrics != nil {
		r.Handle("/metrics", s.ogzApp.Metrics.Handler())
	}

	r.Route("/api/v1", func(r chi.Router) {
		r.Get("/dicts", s.handleDicts)
		r.Post("/calc", s.handleCalc)
		r.Get("/calc/{id}", s.handleGetCalc)
		r.Post("/export/pdf", s.handleExport("pdf"))
		r.Post("/export/xlsx", s.handleExport("xlsx"))
		r.Post("/export/docx", s.handleExport("docx"))
		if s.ogzApp != nil {
			ext.Mount(r, s.ogzApp)
		}
	})
	return r
}

func (s *Server) cors(next http.Handler) http.Handler {
	allowed := map[string]bool{}
	for _, o := range s.opts.AllowedOrigins {
		o = strings.TrimSpace(o)
		if o != "" {
			allowed[o] = true
		}
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		origin := r.Header.Get("Origin")
		if origin != "" && (len(allowed) == 0 || allowed[origin]) {
			w.Header().Set("Access-Control-Allow-Origin", origin)
			w.Header().Set("Vary", "Origin")
			w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization")
			w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PATCH, OPTIONS")
		}
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func (s *Server) handleDicts(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, s.cfg.DictsResponse())
}

func (s *Server) handleCalc(w http.ResponseWriter, r *http.Request) {
	start := time.Now()
	var req models.CalcRequest
	if err := json.NewDecoder(io.LimitReader(r.Body, 1<<20)).Decode(&req); err != nil {
		writeErr(w, http.StatusBadRequest, "invalid json")
		return
	}
	if err := s.validate.Struct(req); err != nil {
		writeErr(w, http.StatusBadRequest, err.Error())
		return
	}
	resp, err := s.engine.Calculate(req)
	if err != nil {
		writeErr(w, http.StatusUnprocessableEntity, err.Error())
		return
	}
	id := uuid.NewString()
	resp.ID = id

	if s.persistence.Calculations != nil {
		reqJSON, _ := pgstore.EnsureJSON(req)
		respJSON, _ := pgstore.EnsureJSON(resp)
		rec := storage.CalculationRecord{
			ID: id, ObjectName: req.ObjectName, TotalCents: resp.Totals.GrandCents,
			Request: reqJSON, Response: respJSON,
			IP: r.RemoteAddr, UserAgent: r.UserAgent(),
		}
		submit := func(ctx context.Context) {
			if _, err := s.persistence.Calculations.Insert(ctx, rec); err != nil {
				slog.Error("persist calc", slog.String("id", id), slog.Any("err", err))
			}
		}
		if s.persistence.Pool != nil {
			s.persistence.Pool.Submit(r.Context(), submit)
		} else {
			go submit(context.Background())
		}
	}

	if s.opts.LogPerf {
		slog.Info("calc done", slog.Duration("ms", time.Since(start)), slog.String("id", id))
	}
	writeJSON(w, http.StatusOK, resp)
}

func (s *Server) handleGetCalc(w http.ResponseWriter, r *http.Request) {
	if s.persistence.Calculations == nil {
		writeErr(w, http.StatusNotFound, "persistence disabled")
		return
	}
	id := chi.URLParam(r, "id")
	rec, err := s.persistence.Calculations.GetByID(r.Context(), id)
	if storage.IsNotFound(err) {
		writeErr(w, http.StatusNotFound, "not found")
		return
	}
	if err != nil {
		writeErr(w, http.StatusInternalServerError, err.Error())
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(rec.Response)
}

func (s *Server) handleExport(format string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var body models.ExportRequest
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			writeErr(w, http.StatusBadRequest, "invalid json")
			return
		}
		if s.persistence.Calculations == nil {
			writeErr(w, http.StatusServiceUnavailable, "persistence required for export")
			return
		}
		rec, err := s.persistence.Calculations.GetByID(r.Context(), body.CalcID)
		if storage.IsNotFound(err) {
			writeErr(w, http.StatusNotFound, "calc not found")
			return
		}
		if err != nil {
			writeErr(w, http.StatusInternalServerError, err.Error())
			return
		}
		var resp models.CalcResponse
		if err := json.Unmarshal(rec.Response, &resp); err != nil {
			writeErr(w, http.StatusInternalServerError, "corrupt calc")
			return
		}
		var data []byte
		var ctype, filename string
		switch format {
		case "pdf":
			data, err = s.exporter.PDF(resp)
			ctype = "application/pdf"
			filename = "ozm-report.pdf"
		case "xlsx":
			data, err = s.exporter.XLSX(resp)
			ctype = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
			filename = "ozm-report.xlsx"
		case "docx":
			data, err = s.exporter.DOCX(resp)
			ctype = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
			filename = "ozm-report.docx"
		default:
			writeErr(w, http.StatusBadRequest, "unknown format")
			return
		}
		if err != nil {
			writeErr(w, http.StatusInternalServerError, err.Error())
			return
		}
		if s.persistence.Exports != nil {
			sum := sha256.Sum256(data)
			_, _ = s.persistence.Exports.Insert(r.Context(), storage.ExportRecord{
				CalculationID: body.CalcID, Format: format, BytesHash: hex.EncodeToString(sum[:]),
			})
		}
		w.Header().Set("Content-Type", ctype)
		w.Header().Set("Content-Disposition", "attachment; filename="+filename)
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(data)
	}
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}

func writeErr(w http.ResponseWriter, code int, msg string) {
	writeJSON(w, code, map[string]string{"error": msg})
}
