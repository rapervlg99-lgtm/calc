package ext

import (
	"bytes"
	"context"
	"errors"
	"io"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"ozm/backend/internal/ogz/blob"
)

func TestLooksLikePDFAcceptsHeader(t *testing.T) {
	rs := strings.NewReader("%PDF-1.5\nrest of the file")
	if err := looksLikePDF(rs); err != nil {
		t.Fatalf("expected valid PDF, got %v", err)
	}
	// Reader must be rewound for the subsequent store step.
	all, _ := io.ReadAll(rs)
	if !strings.HasPrefix(string(all), "%PDF-1.5") {
		t.Fatalf("reader not rewound: %q", string(all))
	}
}

func TestLooksLikePDFRejectsNonPDF(t *testing.T) {
	for _, in := range []string{"", "hi", "PK\x03\x04zipfile", "<html></html>"} {
		if err := looksLikePDF(strings.NewReader(in)); err == nil {
			t.Fatalf("expected rejection for %q", in)
		}
	}
}

// multipartBody builds a multipart/form-data body with a single "file" field.
func multipartBody(t *testing.T, content string) (*bytes.Buffer, string) {
	t.Helper()
	var buf bytes.Buffer
	mw := multipart.NewWriter(&buf)
	fw, err := mw.CreateFormFile("file", "drawing.pdf")
	if err != nil {
		t.Fatalf("CreateFormFile: %v", err)
	}
	if _, err := io.WriteString(fw, content); err != nil {
		t.Fatalf("write: %v", err)
	}
	if err := mw.Close(); err != nil {
		t.Fatalf("close: %v", err)
	}
	return &buf, mw.FormDataContentType()
}

// TestUploadPipelineStoresPDF exercises the same pre-DB path as createJob:
// multipart parse → FormFile → validateUpload → blob.Put.
func TestUploadPipelineStoresPDF(t *testing.T) {
	body, ct := multipartBody(t, "%PDF-1.5\nbinary drawing bytes")
	r := httptest.NewRequest(http.MethodPost, "/api/v1/ext/jobs", body)
	r.Header.Set("Content-Type", ct)
	r.Body = http.MaxBytesReader(httptest.NewRecorder(), r.Body, 1<<20)

	file, header, err := r.FormFile("file")
	if err != nil {
		t.Fatalf("FormFile: %v", err)
	}
	defer file.Close()

	if err := validateUpload(file, header); err != nil {
		t.Fatalf("validateUpload: %v", err)
	}

	store, err := blob.NewLocalStore(t.TempDir())
	if err != nil {
		t.Fatalf("NewLocalStore: %v", err)
	}
	key, err := store.Put(context.Background(), "jobs/test-id/source.pdf", "application/pdf", file)
	if err != nil {
		t.Fatalf("Put: %v", err)
	}
	if key != "jobs/test-id/source.pdf" {
		t.Fatalf("key = %q", key)
	}
}

// TestUploadPipelineRejectsOversize confirms the MaxBytesReader guard trips
// before the file is accepted.
func TestUploadPipelineRejectsOversize(t *testing.T) {
	body, ct := multipartBody(t, "%PDF-1.5\n"+strings.Repeat("A", 4096))
	r := httptest.NewRequest(http.MethodPost, "/api/v1/ext/jobs", body)
	r.Header.Set("Content-Type", ct)
	r.Body = http.MaxBytesReader(httptest.NewRecorder(), r.Body, 64)

	_, _, err := r.FormFile("file")
	if err == nil {
		t.Fatal("expected oversize error")
	}
	var maxErr *http.MaxBytesError
	if !errors.As(err, &maxErr) {
		t.Fatalf("expected *http.MaxBytesError, got %T: %v", err, err)
	}
}
