package blob

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestLocalStorePutWritesNestedKey(t *testing.T) {
	dir := t.TempDir()
	s, err := NewLocalStore(dir)
	if err != nil {
		t.Fatalf("NewLocalStore: %v", err)
	}
	key, err := s.Put(context.Background(), "jobs/abc/source.pdf", "application/pdf",
		strings.NewReader("%PDF-1.5 hello"))
	if err != nil {
		t.Fatalf("Put: %v", err)
	}
	if key != "jobs/abc/source.pdf" {
		t.Fatalf("key = %q", key)
	}
	got, err := os.ReadFile(filepath.Join(dir, "jobs", "abc", "source.pdf"))
	if err != nil {
		t.Fatalf("read back: %v", err)
	}
	if string(got) != "%PDF-1.5 hello" {
		t.Fatalf("content = %q", got)
	}
}

func TestLocalStoreRejectsTraversal(t *testing.T) {
	s, err := NewLocalStore(t.TempDir())
	if err != nil {
		t.Fatalf("NewLocalStore: %v", err)
	}
	if _, err := s.Put(context.Background(), "../../etc/passwd", "", strings.NewReader("x")); err == nil {
		t.Fatal("expected traversal to be rejected")
	}
}
