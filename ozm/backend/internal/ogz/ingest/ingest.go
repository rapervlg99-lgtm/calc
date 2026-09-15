// Package ingest превращает загруженный PDF в постраничные растровые изображения
// для vision-распознавания. Сканы спецификаций металлопроката не имеют текстового
// слоя, поэтому страницы рендерятся в PNG (pdftoppm/poppler) и далее уходят в
// internal/recognition. Рендер — отдельный внешний процесс с таймаутом: его сбой
// не должен ронять воркер (ТЗ §11, уроки А3).
package ingest

import (
	"bytes"
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
)

// Renderer преобразует PDF в по одному изображению на страницу.
type Renderer interface {
	Render(ctx context.Context, pdf []byte) ([][]byte, error)
}

// PdftoppmRenderer рендерит страницы через утилиту pdftoppm (poppler-utils).
// Бинарь и DPI конфигурируются; DPI ~220 — компромисс точность/размер для сканов
// спецификаций (подтверждён экспериментом на эталонных PDF).
type PdftoppmRenderer struct {
	bin string
	dpi int
}

// NewPdftoppmRenderer собирает рендерер. Пустой bin → "pdftoppm" из PATH;
// dpi<=0 → 220.
func NewPdftoppmRenderer(bin string, dpi int) *PdftoppmRenderer {
	if bin == "" {
		bin = "pdftoppm"
	}
	if dpi <= 0 {
		dpi = 220
	}
	return &PdftoppmRenderer{bin: bin, dpi: dpi}
}

// Render пишет PDF во временный каталог, прогоняет pdftoppm и возвращает PNG-страницы
// по порядку. Временные файлы удаляются по завершении.
func (p *PdftoppmRenderer) Render(ctx context.Context, pdf []byte) ([][]byte, error) {
	if len(pdf) == 0 {
		return nil, fmt.Errorf("ingest: empty pdf")
	}
	dir, err := os.MkdirTemp("", "ogz-render-*")
	if err != nil {
		return nil, fmt.Errorf("ingest: tempdir: %w", err)
	}
	defer os.RemoveAll(dir)

	prefix := filepath.Join(dir, "page")
	cmd := exec.CommandContext(ctx, p.bin, "-png", "-r", fmt.Sprint(p.dpi), "-", prefix)
	cmd.Stdin = bytes.NewReader(pdf)
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		return nil, fmt.Errorf("ingest: pdftoppm: %w: %s", err, stderr.String())
	}

	matches, err := filepath.Glob(prefix + "*.png")
	if err != nil {
		return nil, fmt.Errorf("ingest: glob pages: %w", err)
	}
	if len(matches) == 0 {
		return nil, fmt.Errorf("ingest: no pages rendered")
	}
	sort.Strings(matches) // page-1.png, page-2.png … — лексикографически = по порядку

	pages := make([][]byte, 0, len(matches))
	for _, m := range matches {
		b, err := os.ReadFile(m)
		if err != nil {
			return nil, fmt.Errorf("ingest: read page %s: %w", m, err)
		}
		pages = append(pages, b)
	}
	return pages, nil
}
