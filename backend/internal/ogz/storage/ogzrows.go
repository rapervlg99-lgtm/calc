package storage

import (
	"context"
	"database/sql"
	"errors"
)

// OgzRow — строка формы расчёта ОГЗ (таблица ogz_rows).
type OgzRow struct {
	ID               int64
	JobID            string
	RecognitionRowID sql.NullInt64
	Name             string
	ProfileRaw       string
	ProfileMark      string
	GostProfile      string
	SteelGrade       string
	PPNumber         string
	Construction     string
	Mass             float64
	MassUnit         string
	MassPerMeter     float64
	MassSource       string
	SourceURL        string
	IsSheet          bool
	LengthM          float64
	AreaM2           float64
	Classification   string
	Status           string
	HeatingSides     string
	FireLimit        string
	BearingType      string
	CoatingType      string
	UserEdited       bool
}

type OgzRowRepo struct{ db *sql.DB }

func NewOgzRowRepo(db *sql.DB) *OgzRowRepo { return &OgzRowRepo{db: db} }

const ogzRowCols = `id, job_id, recognition_row_id, COALESCE(name,''), COALESCE(profile_raw,''),
	COALESCE(profile_mark,''), COALESCE(gost_profile,''), COALESCE(steel_grade,''), COALESCE(pp_number,''),
	COALESCE(construction,''), COALESCE(mass,0), COALESCE(mass_unit,''), COALESCE(mass_per_meter,0),
	COALESCE(mass_source,''), COALESCE(source_url,''), is_sheet, COALESCE(length_m,0), COALESCE(area_m2,0),
	COALESCE(classification,''), status, COALESCE(heating_sides,''), COALESCE(fire_limit,''),
	COALESCE(bearing_type,''), COALESCE(coating_type,''), user_edited`

func scanRow(s interface{ Scan(...any) error }) (OgzRow, error) {
	var r OgzRow
	err := s.Scan(&r.ID, &r.JobID, &r.RecognitionRowID, &r.Name, &r.ProfileRaw, &r.ProfileMark,
		&r.GostProfile, &r.SteelGrade, &r.PPNumber, &r.Construction,
		&r.Mass, &r.MassUnit, &r.MassPerMeter, &r.MassSource, &r.SourceURL, &r.IsSheet, &r.LengthM, &r.AreaM2,
		&r.Classification, &r.Status, &r.HeatingSides, &r.FireLimit, &r.BearingType, &r.CoatingType,
		&r.UserEdited)
	return r, err
}

// InsertBatch сохраняет рассчитанные строки задания (используется пайплайном
// после распознавания). Выполняется в транзакции.
func (r *OgzRowRepo) InsertBatch(ctx context.Context, rows []OgzRow) error {
	if len(rows) == 0 {
		return nil
	}
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	for _, row := range rows {
		if _, err := tx.ExecContext(ctx,
			`INSERT INTO ogz_rows
			 (job_id, recognition_row_id, name, profile_raw, profile_mark, gost_profile, steel_grade,
			  pp_number, construction, mass, mass_unit,
			  mass_per_meter, mass_source, source_url, is_sheet, length_m, area_m2, classification, status)
			 VALUES ($1,$2,$3,$4,$5,NULLIF($6,''),NULLIF($7,''),NULLIF($8,''),NULLIF($9,''),$10,$11,
			  NULLIF($12::numeric,0),NULLIF($13,''),NULLIF($14,''),$15,NULLIF($16::numeric,0),NULLIF($17::numeric,0),NULLIF($18,''),$19)`,
			row.JobID, row.RecognitionRowID, row.Name, row.ProfileRaw, row.ProfileMark, row.GostProfile,
			row.SteelGrade, row.PPNumber, row.Construction, row.Mass,
			row.MassUnit, row.MassPerMeter, row.MassSource, row.SourceURL, row.IsSheet, row.LengthM, row.AreaM2,
			row.Classification, row.Status); err != nil {
			return err
		}
	}
	return tx.Commit()
}

// ListByJob возвращает строки задания. Ownership проверяется в запросе (IDOR).
func (r *OgzRowRepo) ListByJob(ctx context.Context, jobID, ownerSub string) ([]OgzRow, error) {
	rows, err := r.db.QueryContext(ctx,
		`SELECT `+ogzRowCols+` FROM ogz_rows
		 WHERE job_id = $1 AND EXISTS (SELECT 1 FROM jobs j WHERE j.id = ogz_rows.job_id AND j.owner_sub = $2)
		 ORDER BY id`, jobID, ownerSub)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []OgzRow
	for rows.Next() {
		row, err := scanRow(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, row)
	}
	return out, rows.Err()
}

// GetRow возвращает одну строку задания с проверкой владельца.
func (r *OgzRowRepo) GetRow(ctx context.Context, jobID string, rowID int64, ownerSub string) (OgzRow, error) {
	row := r.db.QueryRowContext(ctx,
		`SELECT `+ogzRowCols+` FROM ogz_rows
		 WHERE id = $1 AND job_id = $2
		   AND EXISTS (SELECT 1 FROM jobs j WHERE j.id = ogz_rows.job_id AND j.owner_sub = $3)`,
		rowID, jobID, ownerSub)
	return scanRow(row)
}

// Update сохраняет правку строки (включая пересчёт и ручные атрибуты), помечает
// user_edited. Ownership — в запросе. sql.ErrNoRows, если строки нет у владельца.
func (r *OgzRowRepo) Update(ctx context.Context, jobID string, rowID int64, ownerSub string, row OgzRow) error {
	res, err := r.db.ExecContext(ctx,
		`UPDATE ogz_rows SET
		   profile_mark = NULLIF($1,''), mass_per_meter = NULLIF($2::numeric,0), mass_source = NULLIF($3,''),
		   length_m = NULLIF($4::numeric,0), area_m2 = NULLIF($5::numeric,0), classification = NULLIF($6,''), status = $7,
		   heating_sides = NULLIF($8,''), fire_limit = NULLIF($9,''), bearing_type = NULLIF($10,''),
		   coating_type = NULLIF($11,''), construction = NULLIF($12,''), name = NULLIF($13,''),
		   user_edited = true, updated_at = now()
		 WHERE id = $14 AND job_id = $15
		   AND EXISTS (SELECT 1 FROM jobs j WHERE j.id = ogz_rows.job_id AND j.owner_sub = $16)`,
		row.ProfileMark, row.MassPerMeter, row.MassSource, row.LengthM, row.AreaM2, row.Classification,
		row.Status, row.HeatingSides, row.FireLimit, row.BearingType, row.CoatingType,
		row.Construction, row.Name,
		rowID, jobID, ownerSub)
	if err != nil {
		return err
	}
	n, err := res.RowsAffected()
	if err != nil {
		return err
	}
	if n == 0 {
		return sql.ErrNoRows
	}
	return nil
}

// Delete удаляет строку задания. Ownership — в запросе.
func (r *OgzRowRepo) Delete(ctx context.Context, jobID string, rowID int64, ownerSub string) error {
	res, err := r.db.ExecContext(ctx,
		`DELETE FROM ogz_rows
		 WHERE id = $1 AND job_id = $2
		   AND EXISTS (SELECT 1 FROM jobs j WHERE j.id = ogz_rows.job_id AND j.owner_sub = $3)`,
		rowID, jobID, ownerSub)
	if err != nil {
		return err
	}
	n, err := res.RowsAffected()
	if err != nil {
		return err
	}
	if n == 0 {
		return sql.ErrNoRows
	}
	return nil
}

// Duplicate копирует строку задания и возвращает новую запись.
func (r *OgzRowRepo) Duplicate(ctx context.Context, jobID string, rowID int64, ownerSub string) (OgzRow, error) {
	src, err := r.GetRow(ctx, jobID, rowID, ownerSub)
	if err != nil {
		return OgzRow{}, err
	}
	var id int64
	err = r.db.QueryRowContext(ctx,
		`INSERT INTO ogz_rows
		 (job_id, recognition_row_id, name, profile_raw, profile_mark, gost_profile, steel_grade,
		  pp_number, construction, mass, mass_unit,
		  mass_per_meter, mass_source, source_url, is_sheet, length_m, area_m2, classification, status,
		  heating_sides, fire_limit, bearing_type, coating_type, user_edited)
		 VALUES ($1,$2,$3,$4,$5,NULLIF($6,''),NULLIF($7,''),NULLIF($8,''),NULLIF($9,''),$10,$11,
		  NULLIF($12::numeric,0),NULLIF($13,''),NULLIF($14,''),$15,NULLIF($16::numeric,0),NULLIF($17::numeric,0),NULLIF($18,''),$19,
		  NULLIF($20,''),NULLIF($21,''),NULLIF($22,''),NULLIF($23,''), true)
		 RETURNING id`,
		src.JobID, src.RecognitionRowID, src.Name, src.ProfileRaw, src.ProfileMark, src.GostProfile,
		src.SteelGrade, src.PPNumber, src.Construction, src.Mass,
		src.MassUnit, src.MassPerMeter, src.MassSource, src.SourceURL, src.IsSheet, src.LengthM, src.AreaM2,
		src.Classification, src.Status, src.HeatingSides, src.FireLimit, src.BearingType, src.CoatingType,
	).Scan(&id)
	if err != nil {
		return OgzRow{}, err
	}
	return r.GetRow(ctx, jobID, id, ownerSub)
}

// CreateManual добавляет пустую профильную строку (ручной ввод специалистом).
// Ownership проверяется через jobs.owner_sub.
func (r *OgzRowRepo) CreateManual(ctx context.Context, jobID, ownerSub string, row OgzRow) (OgzRow, error) {
	var id int64
	err := r.db.QueryRowContext(ctx,
		`INSERT INTO ogz_rows
		 (job_id, name, profile_raw, profile_mark, gost_profile, steel_grade,
		  pp_number, construction, mass, mass_unit,
		  mass_per_meter, mass_source, is_sheet, length_m, area_m2, classification, status,
		  heating_sides, fire_limit, bearing_type, coating_type, user_edited)
		 SELECT $1,$2,$3,$4,NULLIF($5,''),NULLIF($6,''),NULLIF($7,''),NULLIF($8,''),$9,$10,
		  NULLIF($11::numeric,0),NULLIF($12,''),$13,NULLIF($14::numeric,0),NULLIF($15::numeric,0),NULLIF($16,''),$17,
		  NULLIF($18,''),NULLIF($19,''),NULLIF($20,''),NULLIF($21,''), true
		 FROM jobs j
		 WHERE j.id = $1 AND j.owner_sub = $22
		 RETURNING id`,
		jobID, row.Name, row.ProfileRaw, row.ProfileMark, row.GostProfile,
		row.SteelGrade, row.PPNumber, row.Construction, row.Mass, row.MassUnit,
		row.MassPerMeter, row.MassSource, row.IsSheet, row.LengthM, row.AreaM2,
		row.Classification, row.Status, row.HeatingSides, row.FireLimit, row.BearingType, row.CoatingType,
		ownerSub,
	).Scan(&id)
	if err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return OgzRow{}, sql.ErrNoRows
		}
		return OgzRow{}, err
	}
	return r.GetRow(ctx, jobID, id, ownerSub)
}
