package migrations

import (
	"context"
	"database/sql"
	"fmt"
	"os"
	"path/filepath"

	"github.com/pressly/goose/v3"
)

// 0011 переносит в словари свежий сортамент кальклаба (клон на 09.10.2026,
// коммит a4a45e1): каталог профилей вырос с 3755 до 6060 строк, эталонная модель
// даёт 5984 профиля против 3555 в базе. Заодно в репозитории кальклаба появились
// data/references/solid-steel-catalog.json (сортовой прокат) и отчёт покрытия
// калькулятора — их разбираем отдельно.
//
// Слияние то же, что в 0008 и 0009: строки calclab сопоставляются по ID+форма и
// обновляются, новые добавляются, записи справочника v5 (источник
// spravochnik-v5) и правки из интерфейса остаются нетронутыми.
func init() {
	goose.AddNamedMigrationContext("0011_sync_calclab_2026_10_09.go",
		upSyncCalclab20261009, downSyncCalclab20261009)
}

func upSyncCalclab20261009(ctx context.Context, tx *sql.Tx) error {
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
			values ($1, $2::jsonb, 'calclab-2026-10-09') on conflict (name) do update
			set payload = excluded.payload, updated_at = now(), updated_by = excluded.updated_by`, name, string(payload))
		if err != nil {
			return err
		}
	}
	return nil
}

// Удалять строки нельзя: на их стабильные ID ссылаются расчёты.
func downSyncCalclab20261009(ctx context.Context, tx *sql.Tx) error { return nil }
