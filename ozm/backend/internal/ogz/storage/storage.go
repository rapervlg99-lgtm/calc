package storage

import (
	"database/sql"
	"fmt"

	_ "github.com/jackc/pgx/v5/stdlib"
)

// Open dials PostgreSQL via pgx/stdlib and verifies connectivity.
// Prefer OpenFromDB when sharing the ozm-backend pgx pool.
func Open(dsn string) (*sql.DB, error) {
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		return nil, err
	}
	if err := db.Ping(); err != nil {
		return nil, fmt.Errorf("ping db: %w", err)
	}
	return db, nil
}

// OpenFromDB wraps an existing *sql.DB (e.g. from pgxpool via stdlib.OpenDBFromPool).
func OpenFromDB(db *sql.DB) *sql.DB { return db }
