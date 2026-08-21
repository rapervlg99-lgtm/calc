package config

import (
	"os"
	"path/filepath"
)

func osReadFile(dir, name string) ([]byte, error) {
	return os.ReadFile(filepath.Join(dir, name))
}
