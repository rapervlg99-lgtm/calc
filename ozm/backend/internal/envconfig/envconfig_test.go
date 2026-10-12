package envconfig

import (
	"strings"
	"testing"
)

// Имена переменных подключения — канонические из §12 нормы; контуры
// infra/env.<контур>/.env.pg несут ровно их. Тест держит этот контракт: переезд
// на продуктовый префикс снова сделает контуры поставки неработающими.
func TestLoadDatabaseUsesCanonicalNames(t *testing.T) {
	t.Setenv("PGHOST", "ozm-postgres")
	t.Setenv("PGPORT", "6432")
	t.Setenv("PGDATABASE", "ozm")
	t.Setenv("PGUSER", "ozm_stage")
	t.Setenv("PGPASSWORD", "s3cret")
	t.Setenv("PGSSLMODE", "verify-full")
	t.Setenv("PGSSLROOTCERT", "/etc/ssl/certs/pg-root.crt")

	p, err := LoadDatabaseOnly()
	if err != nil {
		t.Fatalf("LoadDatabaseOnly: %v", err)
	}
	if p.Host != "ozm-postgres" || p.Port != "6432" || p.Database != "ozm" || p.User != "ozm_stage" {
		t.Fatalf("прочитано не то: %+v", p)
	}

	dsn := p.ConnString()
	for _, want := range []string{"postgres://", "ozm-postgres:6432", "/ozm", "sslmode=verify-full", "sslrootcert=%2Fetc%2Fssl%2Fcerts%2Fpg-root.crt"} {
		if !strings.Contains(dsn, want) {
			t.Fatalf("в строке подключения нет %q: %s", want, dsn)
		}
	}
}

// Пароль со символами, ломающими наивную склейку, обязан быть закодирован, а не
// разорвать строку подключения на части.
func TestConnStringEscapesPassword(t *testing.T) {
	p := Postgres{Host: "db", Port: "5432", Database: "ozm", User: "ozm", Password: "p@ss/w:rd?x#1", SSLMode: "disable"}
	dsn := p.ConnString()
	if strings.Contains(dsn, "p@ss/w:rd?x#1") {
		t.Fatalf("пароль попал в строку подключения как есть: %s", dsn)
	}
	cfg, err := p.ParseConnConfig()
	if err != nil {
		t.Fatalf("ParseConnConfig: %v", err)
	}
	if cfg.Password != "p@ss/w:rd?x#1" {
		t.Fatalf("пароль разобран неверно: %q", cfg.Password)
	}
	if cfg.Host != "db" || cfg.Port != 5432 || cfg.Database != "ozm" {
		t.Fatalf("адрес разобран неверно: host=%q port=%d db=%q", cfg.Host, cfg.Port, cfg.Database)
	}
}

// Миграции идут под владельцем схемы, когда контур его задал, и под PGUSER,
// когда PG_MIGRATE_USER пуст (локальный стенд).
func TestForMigration(t *testing.T) {
	runtime := Postgres{Host: "db", Port: "5432", Database: "ozm", User: "ozm_api", Password: "api"}

	if got := runtime.ForMigration(); got.User != "ozm_api" || got.Password != "api" {
		t.Fatalf("без PG_MIGRATE_USER роль менять нельзя: %+v", got)
	}

	runtime.MigrateUser = "ozm_migrate"
	runtime.MigratePassword = "mig"
	got := runtime.ForMigration()
	if got.User != "ozm_migrate" || got.Password != "mig" {
		t.Fatalf("миграции должны идти под владельцем схемы: %+v", got)
	}
	if runtime.User != "ozm_api" {
		t.Fatalf("исходное подключение не должно меняться: %+v", runtime)
	}
}
