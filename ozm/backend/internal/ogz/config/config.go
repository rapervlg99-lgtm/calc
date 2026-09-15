// Package config holds OCR runtime settings for the ogz subsystem.
// Values come from CALC_OZM_APP_* via envconfig.OCR (FromEnv).
package config

import (
	"time"

	"ozm/backend/internal/envconfig"
)

// Config is the typed OCR runtime configuration.
type Config struct {
	AuthDevMode     bool
	StorageDir      string
	MaxUploadBytes  int64
	VisionProvider  string
	OllamaURL       string
	OllamaModel     string
	OllamaTimeout   time.Duration
	OllamaNumCtx    int
	OllamaNumPredict int
	OllamaKeepAlive string
	OpenRouterURL   string
	OpenRouterModel string
	OpenRouterKey   string
	OpenRouterTimeout time.Duration
	RecognitionDPI  int
	VisionMaxEdge   int
	PdftoppmBin     string
	PipelineConcurrency int
}

// FromEnv maps envconfig.OCR into ogz Config.
func FromEnv(o envconfig.OCR) Config {
	return Config{
		AuthDevMode:         o.AuthDevMode,
		StorageDir:          o.StorageDir,
		MaxUploadBytes:      o.MaxUploadBytes,
		VisionProvider:      o.VisionProvider,
		OllamaURL:           o.OllamaURL,
		OllamaModel:         o.OllamaModel,
		OllamaTimeout:       o.OllamaTimeout,
		OllamaNumCtx:        o.OllamaNumCtx,
		OllamaNumPredict:    o.OllamaNumPredict,
		OllamaKeepAlive:     o.OllamaKeepAlive,
		OpenRouterURL:       o.OpenRouterURL,
		OpenRouterModel:     o.OpenRouterModel,
		OpenRouterKey:       o.OpenRouterAPIKey,
		OpenRouterTimeout:   o.OpenRouterTimeout,
		RecognitionDPI:      o.RecognitionDPI,
		VisionMaxEdge:       o.VisionMaxEdge,
		PdftoppmBin:         o.PdftoppmBin,
		PipelineConcurrency: o.PipelineConcurrency,
	}
}
