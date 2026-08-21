package ingest

import (
	"context"
	"testing"
)

func TestRenderRejectsEmptyPDF(t *testing.T) {
	r := NewPdftoppmRenderer("", 0)
	if _, err := r.Render(context.Background(), nil); err == nil {
		t.Fatal("expected error on empty pdf")
	}
}

func TestNewPdftoppmRendererDefaults(t *testing.T) {
	r := NewPdftoppmRenderer("", 0)
	if r.bin != "pdftoppm" {
		t.Errorf("bin default = %q, want pdftoppm", r.bin)
	}
	if r.dpi != 220 {
		t.Errorf("dpi default = %d, want 220", r.dpi)
	}
}
