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

func init() {
	goose.AddNamedMigrationContext("0008_add_calclab_sortament.go", upAddCalclabSortament, downAddCalclabSortament)
}

func upAddCalclabSortament(ctx context.Context, tx *sql.Tx) error {
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
			values ($1, $2::jsonb, 'calclab-sortament') on conflict (name) do update
			set payload = excluded.payload, updated_at = now(), updated_by = excluded.updated_by`, name, string(payload))
		if err != nil {
			return err
		}
	}
	return nil
}

// Merge rather than replace: keep local/custom dictionaries and saved roll IDs.
func mergeCalclabDictionary(name string, current, baseline []byte) ([]byte, error) {
	if len(current) == 0 {
		return baseline, nil
	}
	if name == "roll" {
		var old, added []models.RollMark
		if err := json.Unmarshal(current, &old); err != nil {
			return nil, err
		}
		if err := json.Unmarshal(baseline, &added); err != nil {
			return nil, err
		}
		positions := map[string]int{}
		for i, row := range old {
			positions[row.ID+"/"+row.Shape] = i
		}
		for _, row := range added {
			key := row.ID + "/" + row.Shape
			if i, exists := positions[key]; exists {
				if row.Source == "calclab-metalloprokat" && old[i].Source == row.Source {
					old[i] = row
				}
				continue
			}
			positions[key] = len(old)
			old = append(old, row)
		}
		return json.Marshal(old)
	}
	var old, added []models.ProfileFamily
	if err := json.Unmarshal(current, &old); err != nil {
		return nil, err
	}
	if err := json.Unmarshal(baseline, &added); err != nil {
		return nil, err
	}
	for _, family := range added {
		found := false
		for i := range old {
			if old[i].ID != family.ID {
				continue
			}
			found = true
			for _, shape := range family.Shapes {
				exists := false
				for _, s := range old[i].Shapes {
					if s.ID == shape.ID {
						exists = true
						break
					}
				}
				if !exists {
					old[i].Shapes = append(old[i].Shapes, shape)
				}
			}
			break
		}
		if !found {
			old = append(old, family)
		}
	}
	return json.Marshal(old)
}

// Removing rows would break calculations that now reference their stable IDs.
func downAddCalclabSortament(ctx context.Context, tx *sql.Tx) error { return nil }
