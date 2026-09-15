package pg

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/jackc/pgx/v5/stdlib"
	"github.com/pressly/goose/v3"

	"ozm/backend/internal/config"
	"ozm/backend/internal/storage"
)

type Pool struct {
	*pgxpool.Pool
}

func NewPool(ctx context.Context, cfg *pgxpool.Config) (*Pool, error) {
	p, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, err
	}
	if err := p.Ping(ctx); err != nil {
		p.Close()
		return nil, err
	}
	return &Pool{p}, nil
}

func Migrate(ctx context.Context, connConfig *pgx.ConnConfig, fsys fs.FS) error {
	db := stdlib.OpenDB(*connConfig)
	defer db.Close()
	goose.SetBaseFS(fsys)
	if err := goose.SetDialect("postgres"); err != nil {
		return err
	}
	return goose.UpContext(ctx, db, ".")
}

type DictStore struct {
	pool *pgxpool.Pool
}

func NewDictStore(p *pgxpool.Pool) *DictStore { return &DictStore{pool: p} }

func (d *DictStore) GetAll(ctx context.Context) (map[config.DictName][]byte, error) {
	rows, err := d.pool.Query(ctx, `select name, payload from dicts`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := map[config.DictName][]byte{}
	for rows.Next() {
		var name string
		var payload []byte
		if err := rows.Scan(&name, &payload); err != nil {
			return nil, err
		}
		out[config.DictName(name)] = payload
	}
	return out, rows.Err()
}

func (d *DictStore) Upsert(ctx context.Context, name config.DictName, payload []byte, updatedBy string) error {
	_, err := d.pool.Exec(ctx, `
		insert into dicts (name, payload, updated_by)
		values ($1, $2::jsonb, $3)
		on conflict (name) do update
		set payload = excluded.payload, updated_at = now(), updated_by = excluded.updated_by
	`, string(name), string(payload), updatedBy)
	return err
}

func (d *DictStore) Count(ctx context.Context) (int, error) {
	var n int
	err := d.pool.QueryRow(ctx, `select count(*) from dicts`).Scan(&n)
	return n, err
}

type CalculationStore struct {
	pool *pgxpool.Pool
}

func NewCalculationStore(p *pgxpool.Pool) *CalculationStore { return &CalculationStore{pool: p} }

func (s *CalculationStore) Insert(ctx context.Context, rec storage.CalculationRecord) (string, error) {
	id := rec.ID
	if id == "" {
		id = uuid.NewString()
	}
	_, err := s.pool.Exec(ctx, `
		insert into calculations (id, object_name, total_cents, request, response, fingerprint, ip, user_agent)
		values ($1,$2,$3,$4,$5,$6, nullif($7,'')::inet, $8)
	`, id, rec.ObjectName, rec.TotalCents, rec.Request, rec.Response, nullStr(rec.Fingerprint), rec.IP, nullStr(rec.UserAgent))
	return id, err
}

func (s *CalculationStore) GetByID(ctx context.Context, id string) (storage.CalculationRecord, error) {
	var rec storage.CalculationRecord
	var req, resp []byte
	err := s.pool.QueryRow(ctx, `
		select id, created_at, object_name, total_cents, request, response,
		       coalesce(fingerprint,''), coalesce(host(ip)::text,''), coalesce(user_agent,'')
		from calculations where id=$1
	`, id).Scan(&rec.ID, &rec.CreatedAt, &rec.ObjectName, &rec.TotalCents, &req, &resp, &rec.Fingerprint, &rec.IP, &rec.UserAgent)
	if errors.Is(err, pgx.ErrNoRows) {
		return rec, storage.ErrNotFound
	}
	if err != nil {
		return rec, err
	}
	rec.Request = json.RawMessage(req)
	rec.Response = json.RawMessage(resp)
	return rec, nil
}

type ExportStore struct {
	pool *pgxpool.Pool
}

func NewExportStore(p *pgxpool.Pool) *ExportStore { return &ExportStore{pool: p} }

func (s *ExportStore) Insert(ctx context.Context, rec storage.ExportRecord) (string, error) {
	id := rec.ID
	if id == "" {
		id = uuid.NewString()
	}
	_, err := s.pool.Exec(ctx, `
		insert into exports (id, calculation_id, format, bytes_hash)
		values ($1,$2,$3,$4)
	`, id, rec.CalculationID, rec.Format, nullStr(rec.BytesHash))
	return id, err
}

func nullStr(s string) any {
	if s == "" {
		return nil
	}
	return s
}

func EnsureJSON(v any) (json.RawMessage, error) {
	b, err := json.Marshal(v)
	if err != nil {
		return nil, fmt.Errorf("marshal: %w", err)
	}
	return b, nil
}
