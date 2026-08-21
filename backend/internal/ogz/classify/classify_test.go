package classify

import "testing"

func TestClassify(t *testing.T) {
	cases := []struct {
		name       string
		in         string
		wantCount  bool
		wantExcl   bool
		wantMixed  bool
		wantStatus string
	}{
		{"колонна", "Колонна К1", true, false, false, StatusCalculated},
		{"балка перекрытия", "Балка перекрытия Б12", true, false, false, StatusCalculated},
		{"вертикальные связи", "Связи вертикальные ВС-3", true, false, false, StatusCalculated},
		{"прогон", "Прогон Пр-5", true, false, false, StatusCalculated},
		{"ригель", "Ригель Р2", true, false, false, StatusCalculated},
		{"ферма", "Ферма ФС1", true, false, false, StatusCalculated},
		{"косоур", "Косоур КС-1", true, false, false, StatusCalculated},
		{"стены лестничных клеток", "Стены лестничной клетки", true, false, false, StatusCalculated},
		{"ограждение", "Ограждение лестницы", false, true, false, StatusExcluded},
		{"смешанная", "Балка с ограждением", true, true, true, StatusNeedsReview},
		{"неизвестное", "Закладная деталь ЗД1", false, false, false, StatusExcluded},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			r := Classify(c.in)
			if r.Counted != c.wantCount || r.Excluded != c.wantExcl || r.Mixed != c.wantMixed {
				t.Errorf("Classify(%q) = %+v, want counted=%v excluded=%v mixed=%v",
					c.in, r, c.wantCount, c.wantExcl, c.wantMixed)
			}
			if got := r.Status(); got != c.wantStatus {
				t.Errorf("Status(%q) = %q, want %q", c.in, got, c.wantStatus)
			}
		})
	}
}
