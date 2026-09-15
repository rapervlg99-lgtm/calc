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
	pg, err := envconfig.LoadDatabaseOnly()
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
