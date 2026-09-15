package migrations

import (
	"context"
	"database/sql"
	"fmt"
	"os"
	"path/filepath"

	"github.com/pressly/goose/v3"
)

func init() {
	goose.AddNamedMigrationContext("0007_reseed_roll_gost26020.go", upReseedRollGost26020, downReseedRollGost26020)
}

// upReseedRollGost26020 подтягивает в dicts.roll двутавры ГОСТ 26020-83,
// которых не было в АСЧМ-сортементе (в т.ч. 23Б1, 26Б1) — без них OCR-prefill
// не находит геометрию в калькуляторе.
func upReseedRollGost26020(ctx context.Context, tx *sql.Tx) error {
	dir := os.Getenv("DICTS_BASELINE_DIR")
	if dir == "" {
		dir = "/config/dicts"
	}
	path := filepath.Join(dir, "roll.json")
	data, err := os.ReadFile(path)
	if err != nil {
		return fmt.Errorf("read roll.json: %w", err)
	}
	_, err = tx.ExecContext(ctx, `
		insert into dicts (name, payload, updated_by)
		values ('roll', $1::jsonb, 'baseline-reseed-gost26020')
		on conflict (name) do update
		set payload = excluded.payload,
		    updated_at = now(),
		    updated_by = excluded.updated_by
	`, string(data))
	if err != nil {
		return fmt.Errorf("upsert roll: %w", err)
	}
	return nil
}

func downReseedRollGost26020(ctx context.Context, tx *sql.Tx) error {
	return nil
}
