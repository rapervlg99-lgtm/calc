package main

import (
	"context"
	"log"
	"os"

	"ozm/backend/internal/envconfig"
	"ozm/backend/migrations"
	pgstore "ozm/backend/internal/storage/pg"
)

func main() {
	// Роль владельца схемы, если контур её задал (PG_MIGRATE_USER): на stage и
	// prod рантайм-роль PGUSER не должна владеть схемой (решение D3 набора,
	// проверка [9/9] у infra/tests/check-env.sh).
	pg, err := envconfig.LoadMigrationDatabase()
	if err != nil {
		log.Fatal(err)
	}
	cfg, err := pg.ParseConnConfig()
	if err != nil {
		log.Fatal(err)
	}
	if err := pgstore.Migrate(context.Background(), cfg, migrations.FS); err != nil {
		log.Fatal(err)
	}
	log.Println("migrations ok")
	os.Exit(0)
}
