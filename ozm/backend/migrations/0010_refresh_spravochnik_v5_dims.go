package migrations

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"

	"github.com/pressly/goose/v3"
	"ozm/backend/internal/models"
)

// 0010 дополняет перенесённые позиции справочника v5 размерами сечений: скрипт
// backend/scripts/fill-dims-from-calclab.py взял их из каталога кальклаба по
// правилу «та же марка + совпавшая масса» (размеры зависят от редакции: 40Ш1 по
// 35087-2024 — 88,6 кг/м, по 26020-83 — 96,1).
//
// Миграция 0009 такие строки не перезаписывает: её слияние обновляет только
// записи calclab. Здесь строки с source=spravochnik-v5 берутся из файла целиком.
func init() {
	goose.AddNamedMigrationContext("0010_refresh_spravochnik_v5_dims.go",
		upRefreshSpravochnikDims, downRefreshSpravochnikDims)
}

func upRefreshSpravochnikDims(ctx context.Context, tx *sql.Tx) error {
	dir := os.Getenv("DICTS_BASELINE_DIR")
	if dir == "" {
		dir = "/config/dicts"
	}
	baseline, err := os.ReadFile(filepath.Join(dir, "roll.json"))
	if err != nil {
		return fmt.Errorf("read roll.json: %w", err)
	}
	var current []byte
	err = tx.QueryRowContext(ctx, "select payload from dicts where name = 'roll' for update").Scan(&current)
	if err != nil && err != sql.ErrNoRows {
		return err
	}
	payload, err := mergeSpravochnikDims(current, baseline)
	if err != nil {
		return err
	}
	_, err = tx.ExecContext(ctx, `insert into dicts (name, payload, updated_by)
		values ('roll', $1::jsonb, 'spravochnik-v5-dims') on conflict (name) do update
		set payload = excluded.payload, updated_at = now(), updated_by = excluded.updated_by`, string(payload))
	return err
}

// mergeSpravochnikDims: позиции справочника v5 берутся из файла (в них появились
// размеры сечения), остальное содержимое словаря сохраняется как есть — правки
// из интерфейса и записи calclab не затрагиваются.
func mergeSpravochnikDims(current, baseline []byte) ([]byte, error) {
	if len(current) == 0 {
		return baseline, nil
	}
	var old, fresh []models.RollMark
	if err := json.Unmarshal(current, &old); err != nil {
		return nil, err
	}
	if err := json.Unmarshal(baseline, &fresh); err != nil {
		return nil, err
	}
	positions := map[string]int{}
	for i, row := range old {
		positions[row.ID+"/"+row.Shape] = i
	}
	for _, row := range fresh {
		if row.Source != "spravochnik-v5" {
			continue
		}
		key := row.ID + "/" + row.Shape
		if i, exists := positions[key]; exists {
			old[i] = row
			continue
		}
		positions[key] = len(old)
		old = append(old, row)
	}
	return json.Marshal(old)
}

// Удалять строки нельзя: на их стабильные ID ссылаются расчёты.
func downRefreshSpravochnikDims(ctx context.Context, tx *sql.Tx) error { return nil }
