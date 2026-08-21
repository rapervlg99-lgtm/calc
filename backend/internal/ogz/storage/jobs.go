package storage

import (
	"context"
	"database/sql"
	"time"
)

// Job statuses mirror the processing lifecycle (not the per-row ОГЗ statuses).
const (
	JobStatusPending    = "pending"
	JobStatusProcessing = "processing"
	JobStatusReady      = "ready"
	JobStatusFailed     = "failed"
)

type Job struct {
	ID           string
	OwnerSub     string
	Status       string
	SourcePDFKey string
	Error        string
	Confirmed    bool
	ConfirmedAt  sql.NullTime
	CreatedAt    time.Time
	UpdatedAt    time.Time
}

type JobRepo struct{ db *sql.DB }

func NewJobRepo(db *sql.DB) *JobRepo { return &JobRepo{db: db} }

func (r *JobRepo) Create(ctx context.Context, j Job) error {
	_, err := r.db.ExecContext(ctx,
		`INSERT INTO jobs (id, owner_sub, status, source_pdf_key) VALUES ($1, $2, $3, NULLIF($4, ''))`,
		j.ID, j.OwnerSub, j.Status, j.SourcePDFKey)
	return err
}

// Get enforces ownership in the query itself (lesson А9 / IDOR): a job is only
// returned to its owner.
func (r *JobRepo) Get(ctx context.Context, id, ownerSub string) (Job, error) {
	var j Job
	err := r.db.QueryRowContext(ctx,
		`SELECT id, owner_sub, status, COALESCE(source_pdf_key, ''), COALESCE(error, ''),
		        confirmed, confirmed_at, created_at, updated_at
		 FROM jobs WHERE id = $1 AND owner_sub = $2`, id, ownerSub).
		Scan(&j.ID, &j.OwnerSub, &j.Status, &j.SourcePDFKey, &j.Error,
			&j.Confirmed, &j.ConfirmedAt, &j.CreatedAt, &j.UpdatedAt)
	return j, err
}

// SetStatus переводит задание в новый статус (pending→processing→ready/failed)
// из пайплайна. На неуспехе сохраняет текст ошибки; на успехе — очищает.
// Без ownership-проверки: вызывается доверенным фоновым воркером по своему job_id.
func (r *JobRepo) SetStatus(ctx context.Context, id, status, errMsg string) error {
	_, err := r.db.ExecContext(ctx,
		`UPDATE jobs SET status = $2, error = NULLIF($3, ''), updated_at = now() WHERE id = $1`,
		id, status, errMsg)
	return err
}

// RequeueUnfinished возвращает в pending задания, зависшие в processing (например,
// после рестарта воркера до завершения). Возвращает их ID для повторной постановки
// в очередь (урок А3: watchdog/RequeueUnfinished, чтобы задания не терялись).
func (r *JobRepo) RequeueUnfinished(ctx context.Context) ([]Job, error) {
	rows, err := r.db.QueryContext(ctx,
		`UPDATE jobs SET status = $1, updated_at = now()
		 WHERE status = $2
		 RETURNING id, owner_sub, status, COALESCE(source_pdf_key, '')`,
		JobStatusPending, JobStatusProcessing)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Job
	for rows.Next() {
		var j Job
		if err := rows.Scan(&j.ID, &j.OwnerSub, &j.Status, &j.SourcePDFKey); err != nil {
			return nil, err
		}
		out = append(out, j)
	}
	return out, rows.Err()
}

// Confirm помечает форму подтверждённой (апрув) владельцем. Ownership — в запросе
// (урок А9 / IDOR). Возвращает sql.ErrNoRows, если задание не принадлежит владельцу.
func (r *JobRepo) Confirm(ctx context.Context, id, ownerSub string) error {
	res, err := r.db.ExecContext(ctx,
		`UPDATE jobs SET confirmed = true, confirmed_at = now(), updated_at = now()
		 WHERE id = $1 AND owner_sub = $2`, id, ownerSub)
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
