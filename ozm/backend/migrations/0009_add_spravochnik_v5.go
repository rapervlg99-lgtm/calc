package migrations

import (
	"context"
	"database/sql"
	"fmt"
	"os"
	"path/filepath"

	"github.com/pressly/goose/v3"
)

// 0009 переносит в словари позиции из «Инженерного справочника масс металла v5.0»
// (скрипт backend/scripts/import-spravochnik-v5.py дописал их в dicts/roll.json
// с source=spravochnik-v5: СТО АСЧМ 20-93, ГОСТ Р 57837-2017, ГОСТ 8240-97/89,
// ГОСТ 8509-93, ГОСТ 19771/19772-93, ГОСТ 10704-91 и другие).
//
// Слияние то же, что в 0008: строки сопоставляются по ID+форма, отсутствующие
// добавляются, словарные правки из интерфейса не затираются.
func init() {
	goose.AddNamedMigrationContext("0009_add_spravochnik_v5.go", upAddSpravochnikV5, downAddSpravochnikV5)
}

func upAddSpravochnikV5(ctx context.Context, tx *sql.Tx) error {
	dir := os.Getenv("DICTS_BASELINE_DIR")
	if dir == "" {
		dir = "/config/dicts"
	}
	for _, name := range []string{"roll", "profiles"} {
		baseline, err := os.ReadFile(filepath.Join(dir, name+".json"))
		if err != nil {
			return fmt.Errorf("read %s: %w", name, err)
		}
		var current []byte
		err = tx.QueryRowContext(ctx, "select payload from dicts where name = $1 for update", name).Scan(&current)
		if err != nil && err != sql.ErrNoRows {
			return err
		}
		payload, err := mergeCalclabDictionary(name, current, baseline)
		if err != nil {
			return err
		}
		_, err = tx.ExecContext(ctx, `insert into dicts (name, payload, updated_by)
			values ($1, $2::jsonb, 'spravochnik-v5') on conflict (name) do update
			set payload = excluded.payload, updated_at = now(), updated_by = excluded.updated_by`, name, string(payload))
		if err != nil {
			return err
		}
	}
	return nil
}

// Удалять строки нельзя: на их стабильные ID ссылаются расчёты.
func downAddSpravochnikV5(ctx context.Context, tx *sql.Tx) error { return nil }
