package migrations

import (
	"context"
	"database/sql"
	"fmt"
	"os"
	"path/filepath"

	"github.com/pressly/goose/v3"
)

// 0014 переносит в словарь materials_rt метаданные легаси-выгрузки DC (<RT>):
// базу расчёта, привязку к флагу (штукатурка — декоративное покрытие), минимальный
// расход, толщину слоя, порядок в ведомости и точность печати. Раньше словарь
// состоял только из названий, единиц и расходов: ведомость печатала материалы в
// произвольном порядке (сборка шла по map), а отчётам не хватало толщины слоя.
//
// Словарь остаётся полным (backend/dicts/materials_rt.json генерируется из DC
// командой dcextract), поэтому payload заменяется целиком — как в 0012 и 0013.
func init() {
	goose.AddNamedMigrationContext("0014_reseed_materials_from_baseline.go", upReseedMaterials, downReseedMaterials)
}

func upReseedMaterials(ctx context.Context, tx *sql.Tx) error {
	dir := os.Getenv("DICTS_BASELINE_DIR")
	if dir == "" {
		dir = "/config/dicts"
	}
	baseline, err := os.ReadFile(filepath.Join(dir, "materials_rt.json"))
	if err != nil {
		return fmt.Errorf("read materials_rt.json: %w", err)
	}
	_, err = tx.ExecContext(ctx, `insert into dicts (name, payload, updated_by)
		values ('materials_rt', $1::jsonb, 'baseline') on conflict (name) do update
		set payload = excluded.payload, updated_at = now(), updated_by = excluded.updated_by`, string(baseline))
	return err
}

// Восстановление — прежним составом справочника (без метаданных DC).
func downReseedMaterials(ctx context.Context, tx *sql.Tx) error {
	_, err := tx.ExecContext(ctx, `update dicts set payload = $1::jsonb, updated_at = now(), updated_by = 'baseline'
		where name = 'materials_rt'`, legacyMaterialsPayload)
	return err
}

// Прежний справочник материалов: названия, единицы и расходы, без метаданных.
const legacyMaterialsPayload = `[
  {"id": "OZM", "title": "ТЕХНО ОЗМ", "unit": "м³", "q": 1.25},
  {"id": "OZB", "title": "ТЕХНО ОЗБ", "unit": "м³", "q": 1.03},
  {"id": "KCer", "title": "Клей Ceresit CT 190", "unit": "кг", "rate": 1.2},
  {"id": "KVer", "title": "Штукатурка Ceresit", "unit": "кг", "rate": 3.2},
  {"id": "KAnk", "title": "Металлический анкер с шайбой", "unit": "шт", "rate": 7},
  {"id": "T150p", "title": "TAIKOR Primer 150", "unit": "кг", "rate": 0.23},
  {"id": "Taikor", "title": "TAIKOR FP", "unit": "кг"},
  {"id": "T425t", "title": "TAIKOR Top 425", "unit": "кг", "rate": 0.17}
]`
