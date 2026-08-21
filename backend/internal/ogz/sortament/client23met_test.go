package sortament

import "testing"

func TestParseMassPerMeter(t *testing.T) {
	cases := []struct {
		name string
		page string
		want float64
		err  bool
	}{
		// Каноническая строка карточки профиля 23met: «Масса 1 м</td><td>… кг</td>».
		{"comma decimal", `<tr><td>Масса 1 м</td><td>38,53 кг</td></tr>`, 38.53, false},
		{"dot decimal", `<td>Масса 1 м</td> <td>38.53 кг</td>`, 38.53, false},
		{"integer", `<td>Масса 1 м</td><td>42 кг</td>`, 42, false},
		{"not the row", `<td>Площадь сечения</td><td>49.1 см2</td>`, 0, true},
		{"not found", `<html>нет данных</html>`, 0, true},
	}
	for _, c := range cases {
		got, err := parseMassPerMeter(c.page)
		if c.err {
			if err == nil {
				t.Errorf("%s: expected error", c.name)
			}
			continue
		}
		if err != nil || got != c.want {
			t.Errorf("%s: parseMassPerMeter = %v, err=%v, want %v", c.name, got, err, c.want)
		}
	}
}
