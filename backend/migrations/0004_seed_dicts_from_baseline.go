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
	goose.AddMigrationContext(upSeedDictsFromBaseline, downSeedDictsFromBaseline)
}

var dictFiles = []string{
	"profiles",
	"roll",
	"t500",
	"x500",
	"materials_rt",
	"selects",
	"calculation_config",
}

func upSeedDictsFromBaseline(ctx context.Context, tx *sql.Tx) error {
	dir := os.Getenv("DICTS_BASELINE_DIR")
	if dir == "" {
		dir = "/config/dicts"
	}
	for _, name := range dictFiles {
		path := filepath.Join(dir, name+".json")
		data, err := os.ReadFile(path)
		if err != nil {
			return fmt.Errorf("read dict %s: %w", name, err)
		}
		_, err = tx.ExecContext(ctx, `
			insert into dicts (name, payload, updated_by)
			values ($1, $2::jsonb, 'baseline')
			on conflict (name) do update
			set payload = excluded.payload,
			    updated_at = now(),
			    updated_by = excluded.updated_by
		`, name, string(data))
		if err != nil {
			return fmt.Errorf("upsert dict %s: %w", name, err)
		}
	}
	return nil
}

func downSeedDictsFromBaseline(ctx context.Context, tx *sql.Tx) error {
	for _, name := range dictFiles {
		if _, err := tx.ExecContext(ctx, `delete from dicts where name = $1`, name); err != nil {
			return err
		}
	}
	return nil
}
