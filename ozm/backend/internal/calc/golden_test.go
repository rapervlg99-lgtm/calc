package calc_test

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"ozm/backend/internal/calc"
	"ozm/backend/internal/config"
	"ozm/backend/internal/models"
)

func TestGoldenCases(t *testing.T) {
	dictsDir := filepath.Join("..", "..", "dicts")
	if _, err := os.Stat(filepath.Join(dictsDir, "t500.json")); err != nil {
		dictsDir = filepath.Join("..", "..", "..", "dicts")
	}
	store, err := config.LoadFromFiles(dictsDir)
	if err != nil {
		t.Fatalf("load dicts: %v", err)
	}
	engine := calc.New(store)

	dir := filepath.Join("testdata", "golden")
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	for _, e := range entries {
		if e.IsDir() || filepath.Ext(e.Name()) != ".json" {
			continue
		}
		t.Run(e.Name(), func(t *testing.T) {
			raw, err := os.ReadFile(filepath.Join(dir, e.Name()))
			if err != nil {
				t.Fatal(err)
			}
			var fx struct {
				Name     string             `json:"name"`
				Request  models.CalcRequest `json:"request"`
				Expected struct {
					Elements []struct {
						Dpr   float64 `json:"dpr"`
						Delta float64 `json:"delta"`
					} `json:"elements"`
					MaterialQty map[string]float64 `json:"materialQty"`
				} `json:"expected"`
			}
			if err := json.Unmarshal(raw, &fx); err != nil {
				t.Fatal(err)
			}
			resp, err := engine.Calculate(fx.Request)
			if err != nil {
				t.Fatal(err)
			}
			if len(fx.Expected.Elements) > 0 {
				if len(resp.Elements) == 0 {
					t.Fatal("no elements in response")
				}
				got := resp.Elements[0]
				exp := fx.Expected.Elements[0]
				if abs(got.Dpr-exp.Dpr) > 0.15 {
					t.Fatalf("dpr got %.2f want %.2f", got.Dpr, exp.Dpr)
				}
				if exp.Delta > 0 && abs(got.Delta-exp.Delta) > 0.5 {
					t.Fatalf("delta got %.2f want %.2f", got.Delta, exp.Delta)
				}
			}
			for id, want := range fx.Expected.MaterialQty {
				found := false
				for _, m := range resp.Materials {
					if m.ID == id {
						found = true
						if abs(m.Quantity-want)/max(want, 0.001) > 0.05 {
							t.Fatalf("material %s qty got %.4f want %.4f", id, m.Quantity, want)
						}
					}
				}
				if !found && want > 0 {
					t.Fatalf("missing material %s", id)
				}
			}
		})
	}
}

func abs(v float64) float64 {
	if v < 0 {
		return -v
	}
	return v
}

func max(a, b float64) float64 {
	if a > b {
		return a
	}
	return b
}
