package storage

import (
	"context"
	"database/sql"
)

// RecognitionRow — сырая строка распознавания (LLM-vision), якорь для ogz_rows.
// Одна строка = профиль в разрезе одного типа конструкции (см. recognition.Row).
type RecognitionRow struct {
	ID           int64
	JobID        string
	Page         int
	Name         string
	Profile      string
	GostProfile  string
	SteelGrade   string
	PPNumber     string
	Construction string
	Mass         float64
	MassUnit     string
	TotalMass    float64
	IsSheet      bool
	Confidence   float64
}

type RecognitionRowRepo struct{ db *sql.DB }

func NewRecognitionRowRepo(db *sql.DB) *RecognitionRowRepo { return &RecognitionRowRepo{db: db} }

// InsertBatch сохраняет распознанные строки задания и возвращает их в том же
// порядке с проставленными сгенерированными ID (нужны для связи с ogz_rows).
// Выполняется в транзакции.
func (r *RecognitionRowRepo) InsertBatch(ctx context.Context, rows []RecognitionRow) ([]RecognitionRow, error) {
	if len(rows) == 0 {
		return nil, nil
	}
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()
	out := make([]RecognitionRow, len(rows))
	for i, row := range rows {
		var id int64
		if err := tx.QueryRowContext(ctx,
			`INSERT INTO recognition_rows
			 (job_id, page, name, profile, gost_profile, steel_grade, pp_number, construction,
			  mass, mass_unit, total_mass, is_sheet, confidence)
			 VALUES ($1,$2,$3,$4,NULLIF($5,''),NULLIF($6,''),NULLIF($7,''),NULLIF($8,''),
			  NULLIF($9::numeric,0),NULLIF($10,''),NULLIF($11::numeric,0),$12,$13)
			 RETURNING id`,
			row.JobID, row.Page, row.Name, row.Profile, row.GostProfile, row.SteelGrade,
			row.PPNumber, row.Construction, row.Mass, row.MassUnit, row.TotalMass,
			row.IsSheet, row.Confidence).Scan(&id); err != nil {
			return nil, err
		}
		row.ID = id
		out[i] = row
	}
	if err := tx.Commit(); err != nil {
		return nil, err
	}
	return out, nil
}
