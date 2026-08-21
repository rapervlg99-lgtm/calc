package storage

import (
	"context"
	"encoding/json"
	"errors"
	"time"
)

var ErrNotFound = errors.New("not found")

func IsNotFound(err error) bool {
	return errors.Is(err, ErrNotFound)
}

type CalculationRecord struct {
	ID          string
	CreatedAt   time.Time
	ObjectName  string
	TotalCents  int64
	Request     json.RawMessage
	Response    json.RawMessage
	Fingerprint string
	IP          string
	UserAgent   string
}

type ExportRecord struct {
	ID            string
	CalculationID string
	Format        string
	GeneratedAt   time.Time
	BytesHash     string
}

type CalculationStore interface {
	Insert(ctx context.Context, rec CalculationRecord) (string, error)
	GetByID(ctx context.Context, id string) (CalculationRecord, error)
}

type ExportStore interface {
	Insert(ctx context.Context, rec ExportRecord) (string, error)
}
