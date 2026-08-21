package envconfig

import (
	"fmt"
	"time"

	"github.com/caarlos0/env/v11"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

const DefaultRetentionInterval = 24 * time.Hour

type Postgres struct {
	Addr     string `env:"CALC_OZM_PG_ADDR,required"`
	User     string `env:"CALC_OZM_PG_USER,required"`
	Password string `env:"CALC_OZM_PG_PASSWORD,required"`
	Database string `env:"CALC_OZM_PG_DATABASE,required"`
	TLSMode  string `env:"CALC_OZM_PG_TLS_MODE" envDefault:"disable"`
}

// OCR holds recognition /ext settings. Used when Enabled is true.
type OCR struct {
	Enabled             bool          `env:"CALC_OZM_APP_OCR_ENABLED" envDefault:"false"`
	AuthDevMode         bool          `env:"CALC_OZM_APP_AUTH_DEV_MODE" envDefault:"false"`
	StorageDir          string        `env:"CALC_OZM_APP_STORAGE_DIR" envDefault:"./data/blobs"`
	MaxUploadBytes      int64         `env:"CALC_OZM_APP_MAX_UPLOAD_BYTES" envDefault:"31457280"`
	VisionProvider      string        `env:"CALC_OZM_APP_VISION_PROVIDER" envDefault:"ollama"`
	OllamaURL           string        `env:"CALC_OZM_APP_OLLAMA_URL" envDefault:"http://localhost:11434"`
	OllamaModel         string        `env:"CALC_OZM_APP_OLLAMA_MODEL" envDefault:"qwen3.5:9b"`
	OllamaTimeout       time.Duration `env:"CALC_OZM_APP_OLLAMA_TIMEOUT" envDefault:"180s"`
	OllamaNumCtx        int           `env:"CALC_OZM_APP_OLLAMA_NUM_CTX" envDefault:"32768"`
	OllamaNumPredict    int           `env:"CALC_OZM_APP_OLLAMA_NUM_PREDICT" envDefault:"8192"`
	OllamaKeepAlive     string        `env:"CALC_OZM_APP_OLLAMA_KEEP_ALIVE" envDefault:"30m"`
	OpenRouterURL       string        `env:"CALC_OZM_APP_OPENROUTER_URL" envDefault:"https://openrouter.ai/api/v1"`
	OpenRouterModel     string        `env:"CALC_OZM_APP_OPENROUTER_MODEL" envDefault:"nvidia/nemotron-nano-12b-v2-vl:free"`
	OpenRouterAPIKey    string        `env:"CALC_OZM_APP_OPENROUTER_API_KEY"`
	OpenRouterTimeout   time.Duration `env:"CALC_OZM_APP_OPENROUTER_TIMEOUT" envDefault:"120s"`
	RecognitionDPI      int           `env:"CALC_OZM_APP_RECOGNITION_DPI" envDefault:"220"`
	VisionMaxEdge       int           `env:"CALC_OZM_APP_VISION_MAX_EDGE" envDefault:"2048"`
	PdftoppmBin         string        `env:"CALC_OZM_APP_PDFTOPPM_BIN" envDefault:"pdftoppm"`
	PipelineConcurrency int           `env:"CALC_OZM_APP_PIPELINE_CONCURRENCY" envDefault:"1"`
}

type Server struct {
	Postgres       Postgres
	OCR            OCR
	LogLevel       string `env:"CALC_OZM_APP_LOG_LEVEL" envDefault:"info"`
	HTTPAddr       string `env:"CALC_OZM_APP_HTTP_ADDR" envDefault:":8080"`
	AdminToken     string `env:"CALC_OZM_APP_ADMIN_TOKEN"`
	AllowedOrigins string `env:"CALC_OZM_APP_ALLOWED_ORIGINS"`
	EnableAPIDocs  bool   `env:"CALC_OZM_APP_ENABLE_API_DOCS" envDefault:"false"`
	EnableMetrics  bool   `env:"CALC_OZM_APP_ENABLE_METRICS" envDefault:"false"`
	LogPerf        bool   `env:"CALC_OZM_APP_LOG_PERF" envDefault:"false"`
	DictsDir       string `env:"DICTS_BASELINE_DIR" envDefault:""`
}

func (p Postgres) ConnString() string {
	return fmt.Sprintf("postgres://%s:%s@%s/%s?sslmode=%s",
		p.User, p.Password, p.Addr, p.Database, p.TLSMode)
}

func (p Postgres) ParsePoolConfig() (*pgxpool.Config, error) {
	return pgxpool.ParseConfig(p.ConnString())
}

func (p Postgres) ParseConnConfig() (*pgx.ConnConfig, error) {
	return pgx.ParseConfig(p.ConnString())
}

func LoadServer() (Server, error) {
	var cfg Server
	if err := env.Parse(&cfg); err != nil {
		return Server{}, err
	}
	return cfg, nil
}

func LoadDatabaseOnly() (Postgres, error) {
	var p Postgres
	if err := env.Parse(&p); err != nil {
		return Postgres{}, err
	}
	return p, nil
}
