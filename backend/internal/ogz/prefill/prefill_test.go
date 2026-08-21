package prefill

import (
	"testing"

	"ozm/backend/internal/ogz/classify"
)

func TestBuildPayload(t *testing.T) {
	rows := []RowInput{
		{ProfileMark: "35Б2", Construction: "Балки", LengthM: 20, Status: classify.StatusCalculated, FireLimit: "R45", HeatingSides: "3"},
		{ProfileMark: "40Ш1", LengthM: 12, Status: classify.StatusNeedsReview, CoatingType: "СГК"}, // без R — пропуск
		{ProfileMark: "20П", LengthM: 5, Status: classify.StatusNeedsMass},                         // пропускается
		{Status: classify.StatusExcluded},                                                          // пропускается
		{IsSheet: true, AreaM2: 10, Status: classify.StatusCalculated},
		{IsSheet: true, AreaM2: 5.5, Status: classify.StatusCalculated},
	}
	p := Build("job-1", rows)

	if p.Version != Version || p.JobID != "job-1" {
		t.Fatalf("payload meta = %+v", p)
	}
	if len(p.Items) != 1 {
		t.Fatalf("items = %d, want 1 (%+v)", len(p.Items), p.Items)
	}
	if p.Items[0].ProfileMark != "35Б2" || p.Items[0].FireLimit != "R45" {
		t.Errorf("item0 = %+v", p.Items[0])
	}
	if p.Items[0].Construction != "Балки" {
		t.Errorf("item0 construction = %q, want Балки", p.Items[0].Construction)
	}
	if p.Sheet.AreaM2 != 15.5 {
		t.Errorf("sheet area = %v, want 15.5", p.Sheet.AreaM2)
	}
}

func TestBuildSkipsZeroLength(t *testing.T) {
	rows := []RowInput{{ProfileMark: "35Б2", LengthM: 0, Status: classify.StatusCalculated, FireLimit: "R60"}}
	if p := Build("j", rows); len(p.Items) != 0 {
		t.Errorf("zero-length item should be skipped, got %+v", p.Items)
	}
}

func TestBuildSkipsMissingFireLimit(t *testing.T) {
	rows := []RowInput{{ProfileMark: "35Б2", LengthM: 10, Status: classify.StatusCalculated}}
	if p := Build("j", rows); len(p.Items) != 0 {
		t.Errorf("item without R should be skipped, got %+v", p.Items)
	}
}
