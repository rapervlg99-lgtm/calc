package migrations

import (
	"encoding/json"
	"ozm/backend/internal/models"
	"testing"
)

func TestCalclabMergePreservesCustomAndLegacyRows(t *testing.T) {
	current := []byte(`[{"id":"custom","shape":"I-beam_sm","label":"custom","dims":{"h":999}},
		{"id":"old","shape":"I-beam_sm","label":"old","dims":{"h":100}},
		{"id":"old","shape":"channel_","label":"channel","dims":{"h":50}}]`)
	baseline := []byte(`[{"id":"old","shape":"I-beam_sm","label":"changed","dims":{"h":200}},
		{"id":"calclab:1","shape":"channel_unequal","label":"32x22x12x3","dims":{"b1":12},"source":"calclab-metalloprokat","standard":"ГОСТ 8281-80"}]`)
	merged, err := mergeCalclabDictionary("roll", current, baseline)
	if err != nil {
		t.Fatal(err)
	}
	var rows []models.RollMark
	if err := json.Unmarshal(merged, &rows); err != nil {
		t.Fatal(err)
	}
	if len(rows) != 4 || rows[0].Dims["h"] != 999 || rows[1].Dims["h"] != 100 || rows[2].Shape != "channel_" {
		t.Fatalf("existing rows changed: %s", merged)
	}
	second, err := mergeCalclabDictionary("roll", merged, baseline)
	if err != nil || string(second) != string(merged) {
		t.Fatalf("merge is not idempotent: %v", err)
	}
}

func TestCalclabMergePreservesCustomShapes(t *testing.T) {
	current := []byte(`[{"id":"channel","label":"custom label","hard":2,"shapes":[{"id":"custom","label":"custom"}]}]`)
	baseline := []byte(`[{"id":"channel","label":"channel","hard":0,"shapes":[{"id":"channel_unequal","label":"unequal"}]}]`)
	merged, err := mergeCalclabDictionary("profiles", current, baseline)
	if err != nil {
		t.Fatal(err)
	}
	var rows []models.ProfileFamily
	if err := json.Unmarshal(merged, &rows); err != nil {
		t.Fatal(err)
	}
	if rows[0].Label != "custom label" || len(rows[0].Shapes) != 2 {
		t.Fatalf("custom family lost: %s", merged)
	}
}
