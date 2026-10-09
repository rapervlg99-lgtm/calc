package migrations

import (
	"context"
	"database/sql"
	"fmt"
	"os"
	"path/filepath"

	"github.com/pressly/goose/v3"
)

// 0013 переносит в словарь roll сортовой прокат из кальклаба
// (data/references/solid-steel-catalog.json, 771 позиция: полосы ГОСТ 103-2006,
// круги ГОСТ 2590-2006, квадраты ГОСТ 2591-2006) — скрипт
// backend/scripts/import-solid-steel.py дописал их в dicts/roll.json с
// source=calclab-solid-steel.
//
// Файл остаётся полным словарём (legacy + справочник v5 + профили calclab +
// сортовой прокат), поэтому payload заменяется целиком — так же, как в 0012.
func init() {
	goose.AddNamedMigrationContext("0013_add_solid_steel.go", upAddSolidSteel, downAddSolidSteel)
}

func upAddSolidSteel(ctx context.Context, tx *sql.Tx) error {
	dir := os.Getenv("DICTS_BASELINE_DIR")
	if dir == "" {
		dir = "/config/dicts"
	}
	baseline, err := os.ReadFile(filepath.Join(dir, "roll.json"))
	if err != nil {
		return fmt.Errorf("read roll.json: %w", err)
	}
	_, err = tx.ExecContext(ctx, `insert into dicts (name, payload, updated_by)
		values ('roll', $1::jsonb, 'solid-steel') on conflict (name) do update
		set payload = excluded.payload, updated_at = now(), updated_by = excluded.updated_by`, string(baseline))
	return err
}

// Восстановление — из копии roll.json.solid.bak рядом с файлом.
func downAddSolidSteel(ctx context.Context, tx *sql.Tx) error { return nil }
