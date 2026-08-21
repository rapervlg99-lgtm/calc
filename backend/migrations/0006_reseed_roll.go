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
	goose.AddNamedMigrationContext("0006_reseed_roll.go", upReseedRoll, downReseedRoll)
}

func upReseedRoll(ctx context.Context, tx *sql.Tx) error {
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
		values ('roll', $1::jsonb, 'baseline-reseed')
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

func downReseedRoll(ctx context.Context, tx *sql.Tx) error {
	// Keep current roll; baseline restore is one-way for this fix.
	return nil
}
