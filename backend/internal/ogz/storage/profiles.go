package storage

import (
	"context"
	"database/sql"
)

// ProfileRef — запись локального справочника масс профилей (ТЗ §5).
type ProfileRef struct {
	ID           int64
	Mark         string
	MassPerMeter float64
	Source       string // 23met | manual
	OwnerSub     string // "" = глобальная запись
}

type ProfileRepo struct{ db *sql.DB }

func NewProfileRepo(db *sql.DB) *ProfileRepo { return &ProfileRepo{db: db} }

// Get ищет массу по марке: запись владельца имеет приоритет над глобальной.
// Реализует sortament.ReferenceStore.
func (r *ProfileRepo) Get(ctx context.Context, mark, ownerSub string) (float64, string, bool, error) {
	var (
		mpm    float64
		source string
	)
	err := r.db.QueryRowContext(ctx,
		`SELECT mass_per_meter, source FROM profile_reference
		 WHERE mark = $1 AND (owner_sub = $2 OR owner_sub IS NULL)
		 ORDER BY owner_sub NULLS LAST
		 LIMIT 1`, mark, ownerSub).Scan(&mpm, &source)
	if err == sql.ErrNoRows {
		return 0, "", false, nil
	}
	if err != nil {
		return 0, "", false, err
	}
	return mpm, source, true, nil
}

// Put сохраняет/обновляет массу марки. Пустой ownerSub = глобальная запись.
// Реализует sortament.ReferenceStore.
func (r *ProfileRepo) Put(ctx context.Context, mark string, massPerMeter float64, source, ownerSub string) error {
	_, err := r.db.ExecContext(ctx,
		`INSERT INTO profile_reference (mark, mass_per_meter, source, owner_sub)
		 VALUES ($1, $2, $3, NULLIF($4, ''))
		 ON CONFLICT (mark, COALESCE(owner_sub, ''))
		 DO UPDATE SET mass_per_meter = EXCLUDED.mass_per_meter, source = EXCLUDED.source`,
		mark, massPerMeter, source, ownerSub)
	return err
}

// List возвращает справочник: глобальные записи и записи владельца.
func (r *ProfileRepo) List(ctx context.Context, ownerSub string) ([]ProfileRef, error) {
	rows, err := r.db.QueryContext(ctx,
		`SELECT id, mark, mass_per_meter, source, COALESCE(owner_sub, '')
		 FROM profile_reference
		 WHERE owner_sub = $1 OR owner_sub IS NULL
		 ORDER BY mark`, ownerSub)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []ProfileRef
	for rows.Next() {
		var p ProfileRef
		if err := rows.Scan(&p.ID, &p.Mark, &p.MassPerMeter, &p.Source, &p.OwnerSub); err != nil {
			return nil, err
		}
		out = append(out, p)
	}
	return out, rows.Err()
}
