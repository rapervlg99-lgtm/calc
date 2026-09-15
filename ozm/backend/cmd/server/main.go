package main

import (
	"context"
	"flag"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/jackc/pgx/v5/stdlib"
	"github.com/rs/zerolog"

	"ozm/backend/internal/api"
	"ozm/backend/internal/bgpersist"
	"ozm/backend/internal/calc"
	"ozm/backend/internal/config"
	"ozm/backend/internal/envconfig"
	"ozm/backend/internal/export"
	ogzbootstrap "ozm/backend/internal/ogz/bootstrap"
	ogzconfig "ozm/backend/internal/ogz/config"
	pgstore "ozm/backend/internal/storage/pg"
)

func main() {
	healthcheck := flag.Bool("healthcheck", false, "probe /healthz and exit")
	flag.Parse()

	cfgEnv, err := envconfig.LoadServer()
	if err != nil {
		slog.Error("env", slog.Any("err", err))
		os.Exit(1)
	}
	initLogger(cfgEnv.LogLevel)

	if *healthcheck {
		port := "8080"
		if strings.HasPrefix(cfgEnv.HTTPAddr, ":") {
			port = strings.TrimPrefix(cfgEnv.HTTPAddr, ":")
		}
		client := &http.Client{Timeout: 3 * time.Second}
		resp, err := client.Get("http://127.0.0.1:" + port + "/healthz")
		if err != nil || resp.StatusCode != 200 {
			os.Exit(1)
		}
		os.Exit(0)
	}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	poolCfg, err := cfgEnv.Postgres.ParsePoolConfig()
	if err != nil {
		slog.Error("pg config", slog.Any("err", err))
		os.Exit(1)
	}
	pool, err := pgstore.NewPool(ctx, poolCfg)
	if err != nil {
		slog.Error("pg connect", slog.Any("err", err))
		os.Exit(1)
	}
	defer pool.Close()

	dictStore := pgstore.NewDictStore(pool.Pool)
	store, err := config.LoadFromDB(ctx, dictStore)
	if err != nil {
		slog.Error("load dicts", slog.Any("err", err))
		os.Exit(1)
	}

	engine := calc.New(store)
	exporter := export.New()
	origins := strings.Split(cfgEnv.AllowedOrigins, ",")
	srv := api.New(store, engine, exporter, api.Options{
		AllowedOrigins: origins,
		EnableAPIDocs:  cfgEnv.EnableAPIDocs,
		LogPerf:        cfgEnv.LogPerf,
	}).WithPersistence(api.Persistence{
		Calculations: pgstore.NewCalculationStore(pool.Pool),
		Exports:      pgstore.NewExportStore(pool.Pool),
		Pool:         bgpersist.New(8),
	})

	var ogzApp *ogzbootstrap.App
	if cfgEnv.OCR.Enabled {
		sqlDB := stdlib.OpenDBFromPool(pool.Pool)
		zlog := zerolog.New(os.Stdout).With().Timestamp().Logger()
		ogzApp, err = ogzbootstrap.New(ogzconfig.FromEnv(cfgEnv.OCR), zlog, sqlDB)
		if err != nil {
			slog.Error("ogz bootstrap", slog.Any("err", err))
			os.Exit(1)
		}
		ogzApp.Pipeline.RecoverUnfinished(ctx)
		srv = srv.WithOgz(ogzApp)
		slog.Info("ocr enabled", slog.String("provider", cfgEnv.OCR.VisionProvider))
	} else {
		slog.Info("ocr disabled", slog.String("hint", "set CALC_OZM_APP_OCR_ENABLED=true to mount /api/v1/ext"))
	}

	httpSrv := &http.Server{Addr: cfgEnv.HTTPAddr, Handler: srv.Router()}
	go func() {
		slog.Info("listening", slog.String("addr", cfgEnv.HTTPAddr))
		if err := httpSrv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			slog.Error("http", slog.Any("err", err))
			os.Exit(1)
		}
	}()

	<-ctx.Done()
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	_ = httpSrv.Shutdown(shutdownCtx)
	if ogzApp != nil {
		ogzApp.Pipeline.Shutdown()
	}
}

func initLogger(level string) {
	var lv slog.Level
	switch strings.ToLower(level) {
	case "debug":
		lv = slog.LevelDebug
	case "warn":
		lv = slog.LevelWarn
	case "error":
		lv = slog.LevelError
	default:
		lv = slog.LevelInfo
	}
	slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: lv})))
}
