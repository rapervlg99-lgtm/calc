// Package recognition превращает изображение страницы спецификации в структурные
// строки через мультимодальную модель (internal/llm). Приоритет — over-include
// (ТЗ §14): сомнительные строки не отбрасываются, а помечаются пониженной
// confidence → дальше статус «Требует проверки».
//
// Масса элемента в спецификации разнесена по столбцам «Масса металла по элементам
// конструкций» (Колонны/Стойки, Балки, Связи, Прогоны … Общая масса). Поэтому одну
// строку PDF мы раскладываем на несколько строк — по одной на тип конструкции с
// ненулевой массой (ТЗ §4: расчёт ведётся по конструкциям). Каждая такая строка
// несёт свой ГОСТ профиля для поиска массы 1 пог. метра на 23met.ru.
//
// Помимо модели работают детерминированные проверки: (1) сумма масс конструкций
// строки сверяется с её «Общей массой»; (2) сумма «Общих масс» группы сверяется с
// итогом «Всего профиля». Любое расхождение понижает confidence (ловит ошибки OCR
// массы, напр. 51.5 → 515 или 1.90 → 19.0).
package recognition

import (
	"context"
	"encoding/json"
	"fmt"
	"math"
	"regexp"
	"strings"
)

// Confidence-уровни (numeric(5,4) в recognition_rows).
const (
	ConfidenceHigh = 0.95 // модель уверена и суммы сходятся
	ConfidenceLow  = 0.40 // модель пометила uncertain либо расходится сумма
)

// Допуски сверки сумм (масса конструкций ↔ общая; суммы группы ↔ «Всего профиля»).
const (
	sumRelTolerance = 0.01 // 1%
	sumAbsTolerance = 0.05 // т — для маленьких групп/строк
)

// Row — одна расчётная строка формы ОГЗ: профиль в разрезе одного типа
// конструкции (соответствует recognition_rows). PDF-строка с массой в нескольких
// столбцах конструкций раскладывается на несколько Row.
type Row struct {
	Page         int
	Name         string  // наименование группы профиля
	Profile      string  // номер/марка профиля (26Б1, L125x10, t10 …)
	GostProfile  string  // ГОСТ/сортамент профиля из наименования (для 23met.ru)
	SteelGrade   string  // марка стали (С255/С345) — справочно
	PPNumber     string  // номер п/п (позиция в спецификации) — справочно
	Construction string  // тип конструкции (столбец); "" — лист/без разбивки
	Mass         float64 // масса этой конструкции, как распознано
	MassUnit     string  // нормализовано к "t" | "kg"
	TotalMass    float64 // общая масса элемента (для контекста/сверки)
	IsSheet      bool    // листовой прокат (отдельный блок формы ОГЗ)
	Confidence   float64
}

// modelConstruction — масса элемента в одном столбце конструкций.
type modelConstruction struct {
	Type  string   `json:"тип"`
	MassT *float64 `json:"масса_т"`
	Mass  *float64 `json:"масса"`
}

func (c modelConstruction) mass() float64 {
	if c.MassT != nil {
		return *c.MassT
	}
	if c.Mass != nil {
		return *c.Mass
	}
	return 0
}

// modelRow — строка в JSON-ответе модели. Схема задаётся промптом (см. Prompt).
type modelRow struct {
	Name          string              `json:"наименование"`
	GostProfile   string              `json:"гост_профиля"`
	SteelGrade    string              `json:"марка_стали"`
	Profile       string              `json:"профиль"`
	PPNumber      string              `json:"номер_пп"`
	Constructions []modelConstruction `json:"конструкции"`
	TotalMassT    *float64            `json:"общая_масса_т"`
	MassT         *float64            `json:"масса_т"` // фолбэк для строк без разбивки (лист)
	Mass          *float64            `json:"масса"`
	Unit          string              `json:"ед_изм"`
	Uncertain     bool                `json:"uncertain"`
}

type modelResponse struct {
	Rows []modelRow `json:"rows"`
}

// Recognizer извлекает строки спецификации со страницы через VisionModel.
type Recognizer struct {
	model interface {
		Vision(ctx context.Context, prompt string, image []byte) (string, error)
	}
}

// New собирает распознаватель поверх vision-модели.
func New(model interface {
	Vision(ctx context.Context, prompt string, image []byte) (string, error)
}) *Recognizer {
	return &Recognizer{model: model}
}

// RecognizePage прогоняет одно изображение страницы через модель и парсит ответ.
func (r *Recognizer) RecognizePage(ctx context.Context, page int, image []byte) ([]Row, error) {
	raw, err := r.model.Vision(ctx, Prompt(), image)
	if err != nil {
		return nil, fmt.Errorf("recognition: vision call: %w", err)
	}
	rows, err := Parse(raw)
	if err != nil {
		return nil, fmt.Errorf("recognition: parse page %d: %w", page, err)
	}
	for i := range rows {
		rows[i].Page = page
	}
	return rows, nil
}

// Parse разбирает JSON-ответ модели в расчётные строки: отбрасывает итоги,
// раскладывает каждый элемент по конструкциям и проставляет confidence с учётом
// двух сверок сумм. Экспортирован для модульных тестов на реальных ответах.
func Parse(raw string) ([]Row, error) {
	jsonText := extractJSON(raw)
	var mr modelResponse
	if err := json.Unmarshal([]byte(jsonText), &mr); err != nil {
		// На CPU модель часто обрывает JSON mid-object (done_reason=length или
		// ранний stop). Достаём уже закрытые элементы rows — лучше частичный
		// результат, чем полный fail задания.
		if salvaged, ok := salvageTruncatedJSON(jsonText); ok {
			if err2 := json.Unmarshal([]byte(salvaged), &mr); err2 != nil {
				return nil, fmt.Errorf("decode model json: %w", err)
			}
		} else {
			return nil, fmt.Errorf("decode model json: %w", err)
		}
	}

	// Якоря «Всего профиля» по группам — для сверки сумм общих масс.
	anchors := map[string]float64{}
	for _, m := range mr.Rows {
		if isSubtotalAnchor(m.Profile) {
			anchors[normalizeGroup(m.Name)] = totalMassOf(m)
		}
	}

	groupSum := map[string]float64{} // Σ общих масс строк-данных по группам
	var data []Row
	for _, m := range mr.Rows {
		if isAnchorRow(m.Name, m.Profile) {
			continue // итоги/субитоги — не элементы формы
		}
		total := totalMassOf(m)
		groupSum[normalizeGroup(m.Name)] += total

		conf := ConfidenceHigh
		if m.Uncertain {
			conf = ConfidenceLow
		}
		// Сверка: сумма масс конструкций строки ↔ её общая масса.
		if !constructionsMatchTotal(m, total) {
			conf = ConfidenceLow
		}

		base := Row{
			Name:        strings.TrimSpace(m.Name),
			Profile:     strings.TrimSpace(m.Profile),
			GostProfile: strings.TrimSpace(m.GostProfile),
			SteelGrade:  strings.TrimSpace(m.SteelGrade),
			PPNumber:    strings.TrimSpace(m.PPNumber),
			MassUnit:    unitOf(m),
			TotalMass:   total,
			IsSheet:     isSheet(m.Name),
			Confidence:  conf,
		}

		consRows := constructionRows(m)
		if len(consRows) == 0 {
			// Лист или строка без разбивки: одна строка с общей массой.
			row := base
			row.Mass = total
			data = append(data, row)
			continue
		}
		for _, cr := range consRows {
			row := base
			row.Construction = strings.TrimSpace(cr.Type)
			row.Mass = cr.mass()
			data = append(data, row)
		}
	}

	// Сверка сумм групп с якорями «Всего профиля»: расхождение понижает группу.
	mismatched := map[string]bool{}
	for g, anchor := range anchors {
		if anchor <= 0 {
			continue
		}
		got, ok := groupSum[g]
		if !ok {
			continue
		}
		tol := math.Max(anchor*sumRelTolerance, sumAbsTolerance)
		if math.Abs(got-anchor) > tol {
			mismatched[g] = true
		}
	}
	for i := range data {
		if mismatched[normalizeGroup(data[i].Name)] {
			data[i].Confidence = ConfidenceLow
		}
	}
	return data, nil
}

// constructionRows возвращает столбцы конструкций строки с ненулевой массой.
func constructionRows(m modelRow) []modelConstruction {
	out := make([]modelConstruction, 0, len(m.Constructions))
	for _, c := range m.Constructions {
		if c.mass() > 0 {
			out = append(out, c)
		}
	}
	return out
}

// constructionsMatchTotal проверяет, что сумма масс конструкций совпала с общей
// массой строки. Если разбивки нет — проверять нечего (true).
func constructionsMatchTotal(m modelRow, total float64) bool {
	if len(m.Constructions) == 0 || total <= 0 {
		return true
	}
	var sum float64
	for _, c := range m.Constructions {
		sum += c.mass()
	}
	tol := math.Max(total*sumRelTolerance, sumAbsTolerance)
	return math.Abs(sum-total) <= tol
}

// totalMassOf — общая масса элемента: общая_масса_т, иначе масса_т/масса (лист),
// иначе сумма столбцов конструкций.
func totalMassOf(m modelRow) float64 {
	if m.TotalMassT != nil {
		return *m.TotalMassT
	}
	if m.MassT != nil {
		return *m.MassT
	}
	if m.Mass != nil {
		return *m.Mass
	}
	var sum float64
	for _, c := range m.Constructions {
		sum += c.mass()
	}
	return sum
}

// unitOf нормализует единицу: схема спецификации — тонны; явный кг тоже поддержан.
func unitOf(m modelRow) string {
	u := strings.ToLower(strings.TrimSpace(m.Unit))
	switch {
	case strings.HasPrefix(u, "kg") || strings.HasPrefix(u, "кг"):
		return "kg"
	case strings.HasPrefix(u, "t") || strings.HasPrefix(u, "т"):
		return "t"
	default:
		return "t" // спецификации металлопроката ведутся в тоннах
	}
}

// isSheet распознаёт листовой прокат по наименованию группы (отдельный блок ОГЗ).
func isSheet(name string) bool {
	return strings.Contains(strings.ToLower(name), "лист")
}

// isAnchorRow — строка-итог (не элемент): «Всего профиля/стали/металла» или
// субитог-разбивка по маркам стали («В том числе … : С245 / С255»).
func isAnchorRow(name, profile string) bool {
	return isSubtotalAnchor(profile) || isGrandTotal(name) || isGradeBreakdown(name, profile)
}

// steelGradeRe ловит «голую» марку стали в колонке профиля: латиница C или
// кириллица С + 3 цифры (C245, С255, С345-6…). У реального профиля так не бывает
// (двутавр 26Б1, швеллер 30П, уголок L75x6, лист t10), поэтому совпадение —
// надёжный признак, что это разбивка по маркам стали, а не элемент.
var steelGradeRe = regexp.MustCompile(`^[CcСс]\d{3}`)

// isGradeBreakdown отсекает строки-разбивки «в том числе по маркам стали»: они
// дублируют массу, уже учтённую в строках-элементах выше (двойной счёт), и не
// являются конструкциями. Признак — подзаголовок «в том числе …» в наименовании
// или голая марка стали (С245/С255) в колонке профиля.
func isGradeBreakdown(name, profile string) bool {
	if strings.Contains(strings.ToLower(name), "в том числе") {
		return true
	}
	return steelGradeRe.MatchString(strings.TrimSpace(profile))
}

// isSubtotalAnchor — субитог группы в колонке профиля («Всего профиля»).
func isSubtotalAnchor(profile string) bool {
	p := strings.ToLower(strings.TrimSpace(profile))
	return strings.HasPrefix(p, "всего") || strings.HasPrefix(p, "итого")
}

// isGrandTotal — общий итог документа («Всего металла/стали») в колонке
// наименования. Колонку профиля НЕ проверяем: на реальных ведомостях расхода стали
// модель кладёт в неё марку стали (С345/С355), и при проверке «профиль пуст» итог
// «Всего стали» + профиль «С355-6» протекал в форму как элемент. Имя реального
// элемента никогда не начинается с «Всего»/«Итого», так что префикса достаточно.
func isGrandTotal(name string) bool {
	n := strings.ToLower(strings.TrimSpace(name))
	return strings.HasPrefix(n, "всего") || strings.HasPrefix(n, "итого") ||
		strings.Contains(n, "масса металла") || strings.Contains(n, "масса стали")
}

// normalizeGroup приводит наименование группы к ключу сравнения.
func normalizeGroup(name string) string {
	return strings.Join(strings.Fields(strings.ToLower(name)), " ")
}

// extractJSON вырезает JSON-объект из ответа модели (на случай обрамления текстом
// или markdown-блоком ```json … ```).
func extractJSON(s string) string {
	s = strings.TrimSpace(s)
	if i := strings.Index(s, "{"); i >= 0 {
		if j := strings.LastIndex(s, "}"); j > i {
			return s[i : j+1]
		}
		return s[i:]
	}
	return s
}

// salvageTruncatedJSON закрывает обрезанный JSON вида {"rows":[{...},{... incomplete
// так, чтобы остались только полностью записанные объекты в массиве rows.
func salvageTruncatedJSON(s string) (string, bool) {
	s = strings.TrimSpace(s)
	if s == "" || s[0] != '{' {
		return "", false
	}
	// Ищем начало массива rows — дальше режем по полным объектам.
	rowsKey := strings.Index(s, `"rows"`)
	if rowsKey < 0 {
		return "", false
	}
	bracket := strings.Index(s[rowsKey:], "[")
	if bracket < 0 {
		return "", false
	}
	arrStart := rowsKey + bracket // позиция '['

	var (
		objects      []string
		i            = arrStart + 1
		inString     bool
		escape       bool
		depth        int
		objStart     = -1
	)
	for i < len(s) {
		ch := s[i]
		if inString {
			if escape {
				escape = false
			} else if ch == '\\' {
				escape = true
			} else if ch == '"' {
				inString = false
			}
			i++
			continue
		}
		switch ch {
		case '"':
			inString = true
		case '{':
			if depth == 0 {
				objStart = i
			}
			depth++
		case '}':
			if depth > 0 {
				depth--
				if depth == 0 && objStart >= 0 {
					objects = append(objects, s[objStart:i+1])
					objStart = -1
				}
			}
		case ']':
			if depth == 0 {
				// Массив закрыт штатно — salvage не нужен (должен был распарситься).
				return "", false
			}
		}
		i++
	}
	if len(objects) == 0 {
		return "", false
	}
	return `{"rows":[` + strings.Join(objects, ",") + `]}`, true
}
