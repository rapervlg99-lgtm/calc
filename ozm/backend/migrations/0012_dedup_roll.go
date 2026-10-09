package migrations

import (
	"context"
	"database/sql"
	"fmt"
	"os"
	"path/filepath"

	"github.com/pressly/goose/v3"
)

// 0012 приводит словарь roll в базе к дедуплицированному файлу.
//
// После синхронизации 0011 в базе накопились и устаревшие записи calclab (их ID
// в новом каталоге кальклаба уже нет), и дубликаты справочника v5, совпадавшие с
// каталогом. По решению Олега дубликаты удаляются, уникальные значения
// сохраняются — файл dicts/roll.json после scripts/dedup-roll.py содержит ровно
// уникальные записи (9247: 2593 legacy + 670 справочника v5 + 5984 calclab), и он
// полный, поэтому payload заменяется целиком. Справочник profiles не трогаем.
func init() {
	goose.AddNamedMigrationContext("0012_dedup_roll.go", upDedupRoll, downDedupRoll)
}

func upDedupRoll(ctx context.Context, tx *sql.Tx) error {
	dir := os.Getenv("DICTS_BASELINE_DIR")
	if dir == "" {
		dir = "/config/dicts"
	}
	baseline, err := os.ReadFile(filepath.Join(dir, "roll.json"))
	if err != nil {
		return fmt.Errorf("read roll.json: %w", err)
	}
	_, err = tx.ExecContext(ctx, `insert into dicts (name, payload, updated_by)
		values ('roll', $1::jsonb, 'dedup-roll') on conflict (name) do update
		set payload = excluded.payload, updated_at = now(), updated_by = excluded.updated_by`, string(baseline))
	return err
}

// Вернуть прежний (с дубликатами) словарь нельзя — копии лежат рядом с файлом
// (roll.json.dedup.bak), восстановление делается ими.
func downDedupRoll(ctx context.Context, tx *sql.Tx) error { return nil }
