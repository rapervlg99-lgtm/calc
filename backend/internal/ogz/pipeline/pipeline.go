// Package pipeline оркеструет фоновую обработку задания: PDF → растровые страницы
// (ingest) → строки таблицы (recognition, LLM-vision) → форма ОГЗ (классификация +
// масса 1 м + расчёт, ogzform) → запись в БД и смена статуса задания.
//
// Без брокера (Б7): загрузка кладёт задание в pending и зовёт Enqueue; обработка
// идёт в горутине под семафором (ограничение параллелизма — capacity Ollama, урок А6).
// Каждый этап — под общим job-таймаутом; внешний сбой (рендер/LLM/23met) не теряет
// задание: оно переходит в failed с текстом ошибки, а не падает воркер (уроки А3/А4).
package pipeline

import (
	"context"
	"database/sql"
	"fmt"
	"io"
	"sync"
	"time"

	"github.com/rs/zerolog"

	"ozm/backend/internal/ogz/blob"
	"ozm/backend/internal/ogz/ingest"
	"ozm/backend/internal/ogz/metrics"
	"ozm/backend/internal/ogz/ogzform"
	"ozm/backend/internal/ogz/recognition"
	"ozm/backend/internal/ogz/storage"
)

// pageRecognizer распознаёт одну страницу-изображение в строки спецификации.
// Реализуется recognition.Recognizer; интерфейс — ради подмены в тестах.
type pageRecognizer interface {
	RecognizePage(ctx context.Context, page int, image []byte) ([]recognition.Row, error)
}

// Deps — зависимости процессора (собираются в bootstrap).
type Deps struct {
	Log         zerolog.Logger
	Blob        blob.Store
	Renderer    ingest.Renderer
	Recognizer  pageRecognizer
	Resolver    ogzform.MassResolver
	Jobs        *storage.JobRepo
	Recognition *storage.RecognitionRowRepo
	OgzRows     *storage.OgzRowRepo
	Metrics     *metrics.Metrics
	Concurrency int
	JobTimeout  time.Duration
}

// Processor обрабатывает задания в фоне.
type Processor struct {
	deps       Deps
	sem        chan struct{}
	wg         sync.WaitGroup
	jobTimeout time.Duration
}

// New собирает процессор с семафором на Concurrency заданий.
func New(d Deps) *Processor {
	if d.Concurrency <= 0 {
		d.Concurrency = 1
	}
	if d.JobTimeout <= 0 {
		d.JobTimeout = 10 * time.Minute
	}
	return &Processor{
		deps:       d,
		sem:        make(chan struct{}, d.Concurrency),
		jobTimeout: d.JobTimeout,
	}
}

// Enqueue ставит задание в обработку. Неблокирующе: горутина ждёт слот семафора
// и прогоняет пайплайн под собственным таймаутом.
func (p *Processor) Enqueue(jobID, ownerSub, pdfKey string) {
	p.wg.Add(1)
	go func() {
		defer p.wg.Done()
		p.sem <- struct{}{}
		defer func() { <-p.sem }()

		ctx, cancel := context.WithTimeout(context.Background(), p.jobTimeout)
		defer cancel()
		p.process(ctx, jobID, ownerSub, pdfKey)
	}()
}

// RecoverUnfinished возвращает зависшие в processing задания в очередь (урок А3:
// после рестарта воркера задание не должно потеряться).
func (p *Processor) RecoverUnfinished(ctx context.Context) {
	jobs, err := p.deps.Jobs.RequeueUnfinished(ctx)
	if err != nil {
		p.deps.Log.Error().Err(err).Msg("pipeline: requeue unfinished")
		return
	}
	for _, j := range jobs {
		p.deps.Log.Info().Str("job", j.ID).Msg("pipeline: requeued unfinished job")
		p.Enqueue(j.ID, j.OwnerSub, j.SourcePDFKey)
	}
}

// Shutdown дожидается завершения активных заданий (graceful).
func (p *Processor) Shutdown() { p.wg.Wait() }

func (p *Processor) process(ctx context.Context, jobID, ownerSub, pdfKey string) {
	log := p.deps.Log.With().Str("job", jobID).Logger()
	if err := p.deps.Jobs.SetStatus(ctx, jobID, storage.JobStatusProcessing, ""); err != nil {
		log.Error().Err(err).Msg("pipeline: set processing")
		return
	}
	p.deps.Metrics.JobsTotal.WithLabelValues(storage.JobStatusProcessing).Inc()

	if err := p.run(ctx, jobID, ownerSub, pdfKey); err != nil {
		log.Error().Err(err).Msg("pipeline: job failed")
		// Статус пишем отдельным короткоживущим контекстом: основной мог истечь.
		sctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if serr := p.deps.Jobs.SetStatus(sctx, jobID, storage.JobStatusFailed, err.Error()); serr != nil {
			log.Error().Err(serr).Msg("pipeline: set failed")
		}
		p.deps.Metrics.JobsTotal.WithLabelValues(storage.JobStatusFailed).Inc()
		return
	}
	p.deps.Metrics.JobsTotal.WithLabelValues(storage.JobStatusReady).Inc()
	log.Info().Msg("pipeline: job ready")
}

func (p *Processor) run(ctx context.Context, jobID, ownerSub, pdfKey string) error {
	pdf, err := p.loadPDF(ctx, pdfKey)
	if err != nil {
		return err
	}

	pages, err := p.deps.Renderer.Render(ctx, pdf)
	if err != nil {
		return fmt.Errorf("render pages: %w", err)
	}

	var recognized []recognition.Row
	for i, img := range pages {
		rows, err := p.deps.Recognizer.RecognizePage(ctx, i+1, img)
		if err != nil {
			return fmt.Errorf("recognize page %d: %w", i+1, err)
		}
		recognized = append(recognized, rows...)
	}

	saved, err := p.saveRecognition(ctx, jobID, recognized)
	if err != nil {
		return fmt.Errorf("save recognition rows: %w", err)
	}

	formRows := ogzform.Build(ctx, p.toInputs(saved), p.deps.Resolver, ownerSub)
	if err := p.deps.OgzRows.InsertBatch(ctx, p.toOgzRows(jobID, formRows)); err != nil {
		return fmt.Errorf("save ogz rows: %w", err)
	}
	return p.deps.Jobs.SetStatus(ctx, jobID, storage.JobStatusReady, "")
}

func (p *Processor) loadPDF(ctx context.Context, pdfKey string) ([]byte, error) {
	rc, err := p.deps.Blob.Get(ctx, pdfKey)
	if err != nil {
		return nil, fmt.Errorf("load pdf: %w", err)
	}
	defer rc.Close()
	pdf, err := io.ReadAll(rc)
	if err != nil {
		return nil, fmt.Errorf("read pdf: %w", err)
	}
	return pdf, nil
}

func (p *Processor) saveRecognition(ctx context.Context, jobID string, rows []recognition.Row) ([]storage.RecognitionRow, error) {
	in := make([]storage.RecognitionRow, len(rows))
	for i, r := range rows {
		in[i] = storage.RecognitionRow{
			JobID:        jobID,
			Page:         r.Page,
			Name:         r.Name,
			Profile:      r.Profile,
			GostProfile:  r.GostProfile,
			SteelGrade:   r.SteelGrade,
			PPNumber:     r.PPNumber,
			Construction: r.Construction,
			Mass:         r.Mass,
			MassUnit:     r.MassUnit,
			TotalMass:    r.TotalMass,
			IsSheet:      r.IsSheet,
			Confidence:   r.Confidence,
		}
	}
	return p.deps.Recognition.InsertBatch(ctx, in)
}

func (p *Processor) toInputs(rows []storage.RecognitionRow) []ogzform.Input {
	in := make([]ogzform.Input, len(rows))
	for i, r := range rows {
		in[i] = ogzform.Input{
			RecognitionRowID: r.ID,
			Name:             r.Name,
			Profile:          r.Profile,
			GostProfile:      r.GostProfile,
			SteelGrade:       r.SteelGrade,
			PPNumber:         r.PPNumber,
			Construction:     r.Construction,
			Mass:             r.Mass,
			MassUnit:         r.MassUnit,
			IsSheet:          r.IsSheet,
			// Низкая confidence (модель пометила uncertain либо разошлись суммы) →
			// строку на проверку специалистом (ТЗ §14, приоритет — не терять элемент).
			Uncertain: r.Confidence > 0 && r.Confidence < recognition.ConfidenceHigh,
		}
	}
	return in
}

func (p *Processor) toOgzRows(jobID string, rows []ogzform.Row) []storage.OgzRow {
	out := make([]storage.OgzRow, len(rows))
	for i, r := range rows {
		out[i] = storage.OgzRow{
			JobID:            jobID,
			RecognitionRowID: sql.NullInt64{Int64: r.RecognitionRowID, Valid: r.RecognitionRowID != 0},
			Name:             r.Name,
			ProfileRaw:       r.ProfileRaw,
			ProfileMark:      r.ProfileMark,
			GostProfile:      r.GostProfile,
			SteelGrade:       r.SteelGrade,
			PPNumber:         r.PPNumber,
			Construction:     r.Construction,
			Mass:             r.MassKg,
			MassUnit:         "kg",
			MassPerMeter:     r.MassPerMeter,
			MassSource:       r.MassSource,
			SourceURL:        r.SourceURL,
			IsSheet:          r.IsSheet,
			LengthM:          r.LengthM,
			AreaM2:           r.AreaM2,
			Classification:   r.Classification,
			Status:           r.Status,
			// По умолчанию обогрев с 4 сторон (канон для двутавра).
			HeatingSides: "4",
		}
	}
	return out
}
