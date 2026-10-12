package envconfig

import (
	"net"
	"net/url"
	"time"

	"github.com/caarlos0/env/v11"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

const DefaultRetentionInterval = 24 * time.Hour

// Postgres — подключение к БД. Имена переменных канонические, из §12
// корпоративного шаблона («Файлы окружения»), и ровно они лежат в контурах
// infra/env.<контур>/.env.pg: PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD,
// PGSSLMODE, PGSSLROOTCERT. Продуктового префикса здесь нет и быть не может:
// имя переменной одно на все продукты, иначе контур поставки перестаёт
// настраивать сервис (проверка [3/15] и tests/check-env.sh знают эти имена).
//
// PGHOST — только хост, порт живёт отдельно в PGPORT: склейка «хост:порт» в
// одной переменной (прежнее CALC_OZM_PG_ADDR) не даёт задать порт политикой
// контура и ломается на хост-нейме, который уже содержит двоеточие.
//
// PGSSLROOTCERT нужен там, где контур требует проверки сервера
// (PGSSLMODE=verify-full на stage и prod): без него pgx падает на разборе
// строки подключения, а не молча ослабляет проверку.
type Postgres struct {
	Host        string `env:"PGHOST,required"`
	Port        string `env:"PGPORT" envDefault:"5432"`
	Database    string `env:"PGDATABASE,required"`
	User        string `env:"PGUSER,required"`
	Password    string `env:"PGPASSWORD,required"`
	SSLMode     string `env:"PGSSLMODE" envDefault:"disable"`
	SSLRootCert string `env:"PGSSLROOTCERT"`

	// Роль владельца схемы: миграции идут под ней, рантайм — под PGUSER
	// (решение D3 набора, проверка [9/9] у tests/check-env.sh). Переменные
	// необязательные: там, где роли совпадают (локальный стенд), они пусты и
	// миграции идут под PGUSER.
	MigrateUser     string `env:"PG_MIGRATE_USER"`
	MigratePassword string `env:"PG_MIGRATE_PASSWORD"`
}

// ConnString собирает строку подключения через net/url: логин, пароль и имя БД
// могут содержать символы, которые ломают наивную склейку «postgres://user:pass@…»
// (а пароль, попавший в ошибку разбора, утекает в лог). Значения
// url.URL закодирует сам.
func (p Postgres) ConnString() string {
	q := url.Values{}
	q.Set("sslmode", p.SSLMode)
	if p.SSLRootCert != "" {
		q.Set("sslrootcert", p.SSLRootCert)
	}
	u := url.URL{
		Scheme:   "postgres",
		User:     url.UserPassword(p.User, p.Password),
		Host:     net.JoinHostPort(p.Host, p.Port),
		Path:     "/" + p.Database,
		RawQuery: q.Encode(),
	}
	return u.String()
}

// ForMigration возвращает подключение под ролью владельца схемы, если контур её
// задал (PG_MIGRATE_USER). Пустая переменная — миграции под PGUSER.
func (p Postgres) ForMigration() Postgres {
	if p.MigrateUser == "" {
		return p
	}
	p.User = p.MigrateUser
	if p.MigratePassword != "" {
		p.Password = p.MigratePassword
	}
	return p
}

func (p Postgres) ParsePoolConfig() (*pgxpool.Config, error) {
	return pgxpool.ParseConfig(p.ConnString())
}

func (p Postgres) ParseConnConfig() (*pgx.ConnConfig, error) {
	return pgx.ParseConfig(p.ConnString())
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

// Server — рантайм API. HTTP_ADDR, LOG_LEVEL и CORS_ALLOWED_ORIGINS названы
// именами контуров (класс 2 нормы: состав переменных продукт задаёт сам, но имя
// настройки одно — иначе в .env.app рядом окажутся два имени для одной
// величины). Всё, что специфично только для ОЗМ (распознавание, зрение, выгрузки),
// остаётся под префиксом CALC_OZM_APP_*: у этих настроек канонического имени в
// норме нет, а префикс защищает от столкновения в общем окружении.
type Server struct {
	Postgres       Postgres
	OCR            OCR
	LogLevel       string `env:"LOG_LEVEL" envDefault:"info"`
	HTTPAddr       string `env:"HTTP_ADDR" envDefault:":8080"`
	AdminToken     string `env:"CALC_OZM_APP_ADMIN_TOKEN"`
	AllowedOrigins string `env:"CORS_ALLOWED_ORIGINS"`
	EnableAPIDocs  bool   `env:"CALC_OZM_APP_ENABLE_API_DOCS" envDefault:"false"`
	EnableMetrics  bool   `env:"CALC_OZM_APP_ENABLE_METRICS" envDefault:"false"`
	LogPerf        bool   `env:"CALC_OZM_APP_LOG_PERF" envDefault:"false"`
	DictsDir       string `env:"DICTS_BASELINE_DIR" envDefault:""`
}

func LoadServer() (Server, error) {
	var cfg Server
	if err := env.Parse(&cfg); err != nil {
		return Server{}, err
	}
	return cfg, nil
}

// LoadDatabaseOnly читает только подключение к БД — для бинаря миграций.
func LoadDatabaseOnly() (Postgres, error) {
	var p Postgres
	if err := env.Parse(&p); err != nil {
		return Postgres{}, err
	}
	return p, nil
}

// LoadMigrationDatabase — подключение под ролью владельца схемы
// (PG_MIGRATE_USER), когда контур её задал.
func LoadMigrationDatabase() (Postgres, error) {
	p, err := LoadDatabaseOnly()
	if err != nil {
		return Postgres{}, err
	}
	return p.ForMigration(), nil
}
