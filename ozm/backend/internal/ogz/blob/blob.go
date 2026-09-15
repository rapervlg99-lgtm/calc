// Package blob persists opaque binary objects (uploaded PDFs, generated files)
// under string keys. The local-filesystem implementation backs dev/stage; an
// S3-backed Store (Yandex Object Storage, 152-ФЗ) satisfies the same interface.
package blob

import (
	"context"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

// Store persists objects by key. Keys are slash-separated, S3-style
// (e.g. "jobs/<id>/source.pdf").
type Store interface {
	Put(ctx context.Context, key, contentType string, r io.Reader) (string, error)
	// Get opens the object stored under key for reading. The caller closes it.
	Get(ctx context.Context, key string) (io.ReadCloser, error)
}

// LocalStore writes objects to a directory tree under root.
type LocalStore struct{ root string }

// NewLocalStore creates (if needed) the root directory and returns a store.
func NewLocalStore(root string) (*LocalStore, error) {
	if root == "" {
		return nil, fmt.Errorf("blob: empty root")
	}
	abs, err := filepath.Abs(root)
	if err != nil {
		return nil, fmt.Errorf("blob: resolve root: %w", err)
	}
	if err := os.MkdirAll(abs, 0o750); err != nil {
		return nil, fmt.Errorf("blob: create root: %w", err)
	}
	return &LocalStore{root: abs}, nil
}

// Put streams r into the file mapped from key. contentType is ignored locally
// (kept for S3 parity). Returns the stored key.
func (s *LocalStore) Put(_ context.Context, key, _ string, r io.Reader) (string, error) {
	path, err := s.resolve(key)
	if err != nil {
		return "", err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o750); err != nil {
		return "", fmt.Errorf("blob: mkdir: %w", err)
	}
	f, err := os.Create(path)
	if err != nil {
		return "", fmt.Errorf("blob: create: %w", err)
	}
	defer f.Close()
	if _, err := io.Copy(f, r); err != nil {
		return "", fmt.Errorf("blob: write: %w", err)
	}
	return key, nil
}

// Get opens the file mapped from key. The caller is responsible for closing it.
func (s *LocalStore) Get(_ context.Context, key string) (io.ReadCloser, error) {
	path, err := s.resolve(key)
	if err != nil {
		return nil, err
	}
	f, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("blob: open: %w", err)
	}
	return f, nil
}

// resolve maps a slash-separated key to an absolute path under root, rejecting
// path-traversal attempts ("..") and absolute keys.
func (s *LocalStore) resolve(key string) (string, error) {
	if key == "" {
		return "", fmt.Errorf("blob: empty key")
	}
	clean := filepath.Clean(filepath.FromSlash(key))
	if filepath.IsAbs(clean) || clean == ".." || strings.HasPrefix(clean, ".."+string(os.PathSeparator)) {
		return "", fmt.Errorf("blob: invalid key: %q", key)
	}
	path := filepath.Join(s.root, clean)
	if path != s.root && !strings.HasPrefix(path, s.root+string(os.PathSeparator)) {
		return "", fmt.Errorf("blob: key escapes root: %q", key)
	}
	return path, nil
}
