package bootstrap

import (
	"database/sql"
	"net/http"
	"time"

	"github.com/rs/zerolog"

	"ozm/backend/internal/ogz/auth"
	"ozm/backend/internal/ogz/blob"
	"ozm/backend/internal/ogz/config"
	"ozm/backend/internal/ogz/ingest"
	"ozm/backend/internal/ogz/llm"
	"ozm/backend/internal/ogz/metrics"
	"ozm/backend/internal/ogz/pipeline"
	"ozm/backend/internal/ogz/recognition"
	"ozm/backend/internal/ogz/sortament"
	"ozm/backend/internal/ogz/storage"
)

// externalHTTPTimeout — потолок на внешние вызовы (23met.ru) поверх context-таймаута
// вызывающего (ТЗ §5: внешний сбой не должен ронять задание).
const externalHTTPTimeout = 10 * time.Second

// App wires together the long-lived dependencies shared across transports.
type App struct {
	Cfg       config.Config
	Log       zerolog.Logger
	DB        *sql.DB
	Metrics   *metrics.Metrics
	Auth      *auth.Authenticator
	Jobs      *storage.JobRepo
	OgzRows   *storage.OgzRowRepo
	Profiles  *storage.ProfileRepo
	Sortament *sortament.Resolver
	Blob      blob.Store
	Pipeline  *pipeline.Processor
}

func New(cfg config.Config, log zerolog.Logger, db *sql.DB) (*App, error) {
	profiles := storage.NewProfileRepo(db)
	httpClient := &http.Client{Timeout: externalHTTPTimeout}
	resolver := sortament.NewResolver(profiles, sortament.NewClient23met(httpClient))
	blobStore, err := blob.NewLocalStore(cfg.StorageDir)
	if err != nil {
		return nil, err
	}

	met := metrics.New()
	jobs := storage.NewJobRepo(db)
	ogzRows := storage.NewOgzRowRepo(db)

	// Распознавание: vision-модель извлекает строки спецификации; результат сразу
	// идёт в форму ОГЗ. Провайдер выбирается конфигом (локальный Ollama или облачный
	// OpenRouter) за единым интерфейсом llm.VisionModel — recognition его не различает.
	visionClient, visionTimeout := newVisionModel(cfg, log)
	processor := pipeline.New(pipeline.Deps{
		Log:         log,
		Blob:        blobStore,
		Renderer:    ingest.NewPdftoppmRenderer(cfg.PdftoppmBin, cfg.RecognitionDPI),
		Recognizer:  recognition.New(visionClient),
		Resolver:    resolver,
		Jobs:        jobs,
		Recognition: storage.NewRecognitionRowRepo(db),
		OgzRows:     ogzRows,
		Metrics:     met,
		Concurrency: cfg.PipelineConcurrency,
		JobTimeout:  visionTimeout * 4, // запас на несколько страниц + рендер + 23met
	})

	return &App{
		Cfg:       cfg,
		Log:       log,
		DB:        db,
		Metrics:   met,
		Auth:      auth.New(cfg.AuthDevMode),
		Jobs:      jobs,
		OgzRows:   ogzRows,
		Profiles:  profiles,
		Sortament: resolver,
		Blob:      blobStore,
		Pipeline:  processor,
	}, nil
}

// newVisionModel выбирает провайдера распознавания по конфигу и возвращает клиента
// вместе с таймаутом одного vision-вызова (нужен для расчёта общего job-таймаута).
// openrouter — облако (секунды/страница, но данные покидают периметр); ollama —
// локально (приватно, но минуты/страница). Неизвестное значение → ollama (дефолт).
func newVisionModel(cfg config.Config, log zerolog.Logger) (llm.VisionModel, time.Duration) {
	if cfg.VisionProvider == "openrouter" {
		if cfg.OpenRouterKey == "" {
			// Fail-soft: без ключа облако не поднять — честно падаем обратно на Ollama,
			// а не молча шлём запросы без авторизации (получили бы 401 на каждом задании).
			log.Warn().Msg("bootstrap: VISION_PROVIDER=openrouter, но OPENROUTER_API_KEY пуст — откат на Ollama")
		} else {
			log.Info().Str("model", cfg.OpenRouterModel).Msg("bootstrap: vision provider = openrouter")
			return llm.NewOpenRouterClient(llm.OpenRouterOptions{
				BaseURL: cfg.OpenRouterURL,
				Model:   cfg.OpenRouterModel,
				APIKey:  cfg.OpenRouterKey,
				Timeout: cfg.OpenRouterTimeout,
				Title:   "OGZ pogonazh",
				MaxEdge: cfg.VisionMaxEdge,
			}), cfg.OpenRouterTimeout
		}
	}
	log.Info().Str("model", cfg.OllamaModel).Msg("bootstrap: vision provider = ollama")
	return llm.NewOllamaClient(llm.Options{
		BaseURL:    cfg.OllamaURL,
		Model:      cfg.OllamaModel,
		Timeout:    cfg.OllamaTimeout,
		NumCtx:     cfg.OllamaNumCtx,
		NumPredict: cfg.OllamaNumPredict,
		KeepAlive:  cfg.OllamaKeepAlive,
		MaxEdge:    cfg.VisionMaxEdge,
	}), cfg.OllamaTimeout
}
