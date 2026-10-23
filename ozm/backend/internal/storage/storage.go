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

// ShareRecord — «черновик» расчёта по ссылке: произвольный JSON состояния
// калькулятора (объект, адрес, конструкции, бетон). Сервер его не разбирает,
// поэтому формат состояния может меняться без миграций.
type ShareRecord struct {
	Token     string
	Payload   json.RawMessage
	CreatedAt time.Time
	UpdatedAt time.Time
}

type ShareStore interface {
	Create(ctx context.Context, rec ShareRecord) (string, error)
	Update(ctx context.Context, token string, payload json.RawMessage) error
	GetByToken(ctx context.Context, token string) (ShareRecord, error)
}