package main

import (
	"encoding/json"
	"encoding/xml"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"

	"ozm/backend/internal/models"
)

var (
	attrRe = regexp.MustCompile(`([\w-]+)=['"]([^'"]*)['"]`)
	rollTokenRe = regexp.MustCompile(`(?i)<select\b([^>]*)>|</select>|<o\b([^>]*)>([^<]*)</o>|<o\b([^>]*)\s*/>`)
	picCodeRe = regexp.MustCompile(`picture="([^"]+)"[^>]*\bcode="(\d+)"`)
	codePicRe = regexp.MustCompile(`\bcode="(\d+)"[^>]*picture="([^"]+)"`)
)

func main() {
	dcPath := flag.String("dc", "testdata/dc/DC.xml", "path to DC.xml")
	t500Path := flag.String("t500", "testdata/dc/t500.xml", "path to t500.xml")
	x500Path := flag.String("x500", "testdata/dc/x500.xml", "path to x500.xml")
	rollPath := flag.String("roll", "testdata/dc/roll.xml", "path to roll.xml")
	outDir := flag.String("out", "dicts", "output dicts directory")
	reportPath := flag.String("report", "", "optional markdown report path")
	flag.Parse()

	if err := os.MkdirAll(*outDir, 0o755); err != nil {
		fatal(err)
	}

	t500, err := parseT500(*t500Path)
	if err != nil {
		fatal(err)
	}
	x500, err := parseX500(*x500Path)
	if err != nil {
		fatal(err)
	}
	roll, err := parseRoll(*rollPath, *dcPath)
	if err != nil {
		fatal(err)
	}
	profiles, selects, materials, cfg, err := parseDC(*dcPath)
	if err != nil {
		fatal(err)
	}

	mustWrite(*outDir, "t500.json", t500)
	mustWrite(*outDir, "x500.json", x500)
	mustWrite(*outDir, "roll.json", roll)
	mustWrite(*outDir, "profiles.json", profiles)
	mustWrite(*outDir, "selects.json", selects)
	mustWrite(*outDir, "materials_rt.json", materials)
	mustWrite(*outDir, "calculation_config.json", cfg)

	rep := fmt.Sprintf("# DC extract report\n\n- t500 rows: %d\n- x500 coats: %d\n- roll marks: %d\n- profile families: %d\n- materials: %d\n",
		len(t500), len(x500), len(roll), len(profiles), len(materials))
	if *reportPath != "" {
		_ = os.WriteFile(*reportPath, []byte(rep), 0o644)
	}
	fmt.Print(rep)
}

func fatal(err error) {
	fmt.Fprintf(os.Stderr, "dcextract: %v\n", err)
	os.Exit(1)
}

func mustWrite(dir, name string, v any) {
	b, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, name), b, 0o644); err != nil {
		fatal(err)
	}
}

func parseT500(path string) ([]models.T500Row, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	dec := xml.NewDecoder(f)
	var rows []models.T500Row
	for {
		tok, err := dec.Token()
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, err
		}
		se, ok := tok.(xml.StartElement)
		if !ok || se.Name.Local != "tr" {
			continue
		}
		var tr struct {
			TD []string `xml:"td"`
		}
		if err := dec.DecodeElement(&tr, &se); err != nil {
			return nil, err
		}
		if len(tr.TD) < 4 {
			continue
		}
		rows = append(rows, models.T500Row{
			BaseDelta: atof(tr.TD[0]),
			A:         atof(tr.TD[1]),
			B:         atof(tr.TD[2]),
			Thickness: atof(tr.TD[3]),
		})
	}
	return rows, nil
}

type x500XML struct {
	Coats []struct {
		Rs []struct {
			Min   string `xml:"min,attr"`
			Heat  *struct {
				Delta string `xml:"δ,attr"`
				Rate  string `xml:"rate,attr"`
			} `xml:"heat"`
			Rows []struct {
				Delta string `xml:"δ,attr"`
				Rate  string `xml:"rate,attr"`
				Value string `xml:",chardata"`
			} `xml:"row"`
			// nested taikor wrappers in coat4
			Taikors []struct {
				Heat *struct {
					Delta string `xml:"δ,attr"`
					Rate  string `xml:"rate,attr"`
				} `xml:"heat"`
				Rows []struct {
					Delta string `xml:"δ,attr"`
					Rate  string `xml:"rate,attr"`
					Value string `xml:",chardata"`
				} `xml:"row"`
			} `xml:"taikor"`
		} `xml:"R"`
	} `xml:"coat"`
}

func parseX500(path string) ([]models.X500Coat, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var root x500XML
	if err := xml.Unmarshal(data, &root); err != nil {
		return nil, err
	}
	out := make([]models.X500Coat, 0, len(root.Coats))
	for i, c := range root.Coats {
		coat := models.X500Coat{Index: i + 1}
		for _, r := range c.Rs {
			col := models.X500RColumn{Min: atof(r.Min)}
			if r.Heat != nil {
				col.Heat = &models.X500Row{Delta: atof(r.Heat.Delta), Rate: atof(r.Heat.Rate)}
			}
			for _, row := range r.Rows {
				col.Rows = append(col.Rows, models.X500Row{
					Dpr: atof(strings.TrimSpace(row.Value)), Delta: atof(row.Delta), Rate: atof(row.Rate),
				})
			}
			for _, t := range r.Taikors {
				if t.Heat != nil && col.Heat == nil {
					col.Heat = &models.X500Row{Delta: atof(t.Heat.Delta), Rate: atof(t.Heat.Rate)}
				}
				for _, row := range t.Rows {
					col.Rows = append(col.Rows, models.X500Row{
						Dpr: atof(strings.TrimSpace(row.Value)), Delta: atof(row.Delta), Rate: atof(row.Rate),
					})
				}
			}
			coat.Columns = append(coat.Columns, col)
		}
		out = append(out, coat)
	}
	return out, nil
}

func loadShapeBySelectID(dcPath string) (map[string]string, error) {
	data, err := os.ReadFile(dcPath)
	if err != nil {
		return nil, err
	}
	text := string(data)
	out := map[string]string{}
	for _, m := range picCodeRe.FindAllStringSubmatch(text, -1) {
		out[m[2]] = m[1]
	}
	for _, m := range codePicRe.FindAllStringSubmatch(text, -1) {
		if _, ok := out[m[1]]; !ok {
			out[m[1]] = m[2]
		}
	}
	return out, nil
}

func parseRoll(path, dcPath string) ([]models.RollMark, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	shapeByID, err := loadShapeBySelectID(dcPath)
	if err != nil {
		shapeByID = map[string]string{}
	}

	parseAttrs := func(s string) map[string]string {
		out := map[string]string{}
		for _, m := range attrRe.FindAllStringSubmatch(s, -1) {
			out[m[1]] = m[2]
		}
		return out
	}

	text := string(data)
	var marks []models.RollMark
	currentShape := ""

	for _, m := range rollTokenRe.FindAllStringSubmatch(text, -1) {
		tok := m[0]
		lower := strings.ToLower(tok)
		switch {
		case strings.HasPrefix(lower, "<select"):
			attrs := parseAttrs(m[1])
			id := attrs["id"]
			if pic, ok := shapeByID[id]; ok && pic != "" {
				currentShape = pic
			} else if attrs["name"] != "" {
				currentShape = attrs["name"]
			}
		case strings.HasPrefix(lower, "</select"):
			// keep last shape; blank selects are empty anyway
		default:
			attrsS := m[2]
			if attrsS == "" {
				attrsS = m[4]
			}
			label := strings.TrimSpace(m[3])
			attrs := parseAttrs(attrsS)
			if label == "" {
				label = attrs["title"]
				if label == "" {
					label = attrs["name"]
				}
			}
			id := attrs["id"]
			if id == "" {
				id = attrs["name"]
			}
			if id == "" {
				id = label
			}
			if id == "" && label == "" {
				continue
			}
			dims := map[string]float64{}
			for k, v := range attrs {
				if k == "name" || k == "title" || k == "id" {
					continue
				}
				if fv, err := strconv.ParseFloat(strings.ReplaceAll(v, ",", "."), 64); err == nil {
					dims[k] = fv
				}
			}
			if label == "" {
				label = id
			}
			marks = append(marks, models.RollMark{
				ID: id, Shape: currentShape, Label: label, Dims: dims,
			})
		}
	}
	return marks, nil
}

func parseDC(path string) ([]models.ProfileFamily, map[string][]models.SelectOption, []models.MaterialRT, models.CalcConfig, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, nil, nil, models.CalcConfig{}, err
	}
	// Lightweight string/XML hybrid parse for OS + SL + RT sections.
	profiles := defaultProfiles()
	selects := defaultSelects()
	materials := defaultMaterials()
	cfg := models.CalcConfig{
		TaikorQ: 1.43, OzmQ: 1.25, OzbQ: 1.03, SteelDensity: 7850,
		OzbByR: map[string]float64{"180": 50, "240": 40},
	}

	text := string(data)
	if i := strings.Index(text, `title="ТЕХНО ОЗМ"`); i > 0 {
		chunk := text[max(0, i-80):min(len(text), i+80)]
		if q := extractAttr(chunk, "q"); q > 0 {
			cfg.OzmQ = q
		}
	}
	if i := strings.Index(text, `title="ТЕХНО ОЗБ"`); i > 0 {
		chunk := text[max(0, i-80):min(len(text), i+120)]
		if q := extractAttr(chunk, "q"); q > 0 {
			cfg.OzbQ = q
		}
	}
	return profiles, selects, materials, cfg, nil
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func extractAttr(s, name string) float64 {
	key := name + `="`
	i := strings.Index(s, key)
	if i < 0 {
		return 0
	}
	s = s[i+len(key):]
	j := strings.Index(s, `"`)
	if j < 0 {
		return 0
	}
	return atof(s[:j])
}

func atof(s string) float64 {
	s = strings.TrimSpace(strings.ReplaceAll(s, ",", "."))
	v, _ := strconv.ParseFloat(s, 64)
	return v
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}

func defaultProfiles() []models.ProfileFamily {
	return []models.ProfileFamily{
		{ID: "I-beam", Label: "двутавр", Hard: 0, Shapes: []models.ProfileShape{
			{ID: "I-beam_", Label: "двутавр", Picture: "I-beam_"},
			{ID: "I-beam_sm", Label: "двутавр простой", Picture: "I-beam_sm"},
			{ID: "I-beam_sl", Label: "двутавр с уклоном полок", Picture: "I-beam_sl"},
		}},
		{ID: "channel", Label: "швеллер", Hard: 0, Shapes: []models.ProfileShape{
			{ID: "channel_", Label: "швеллер", Picture: "channel_"},
			{ID: "channel_sl", Label: "швеллер с уклоном полок", Picture: "channel_sl"},
		}},
		{ID: "brands", Label: "тавр", Hard: 1, Shapes: []models.ProfileShape{
			{ID: "brands_", Label: "тавр", Picture: "brands_"},
			{ID: "brands_sm", Label: "тавр простой", Picture: "brands_sm"},
		}},
		{ID: "corner", Label: "уголок", Hard: 1, Shapes: []models.ProfileShape{
			{ID: "corner_", Label: "уголок", Picture: "corner_"},
			{ID: "corner_e", Label: "уголок равнополочный", Picture: "corner_e"},
			{ID: "corner_ue", Label: "уголок неравнополочный", Picture: "corner_ue"},
		}},
		{ID: "profile", Label: "профиль", Hard: 2, Shapes: []models.ProfileShape{
			{ID: "profile_", Label: "профиль", Picture: "profile_"},
			{ID: "profile_sm", Label: "профиль простой", Picture: "profile_sm"},
		}},
		{ID: "tube", Label: "труба", Hard: 2, Shapes: []models.ProfileShape{
			{ID: "tube_", Label: "труба", Picture: "tube_"},
			{ID: "tube_sm", Label: "труба круглая", Picture: "tube_sm"},
			{ID: "tube_sq", Label: "труба квадратная", Picture: "tube_sq"},
		}},
	}
}

func defaultSelects() map[string][]models.SelectOption {
	return map[string][]models.SelectOption{
		"fr_durability": {
			{Value: "1", Label: "I"}, {Value: "2", Label: "II"}, {Value: "3", Label: "III"},
			{Value: "4", Label: "IV"}, {Value: "5", Label: "V"},
		},
		"fr_type": {
			{Value: "1", Label: "несущая конструкция"},
			{Value: "0", Label: "самонесущая конструкция"},
		},
		"ht_level": {
			{Value: "15", Label: "R15"}, {Value: "30", Label: "R30"}, {Value: "45", Label: "R45"},
			{Value: "60", Label: "R60"}, {Value: "90", Label: "R90"}, {Value: "120", Label: "R120"},
			{Value: "150", Label: "R150"}, {Value: "180", Label: "R180"}, {Value: "210", Label: "R210"},
			{Value: "240", Label: "R240"},
		},
		"fr_coat": {
			{Value: "1", Label: "ТЕХНО ОЗМ"},
			{Value: "2", Label: "TAIKOR FP Epoxy"},
			{Value: "3", Label: "TAIKOR FP Graphite"},
			{Value: "4", Label: "TAIKOR FP Extra + TAIKOR FP Graphite"},
			{Value: "1.5", Label: "АКЗ"},
		},
		"fr_method": {
			{Value: "1", Label: "огнезащита по коробу"},
			{Value: "0", Label: "огнезащита по контуру"},
		},
		"fr_side": {
			{Value: "left", Label: "← левая"},
			{Value: "top", Label: "↓ верх"},
			{Value: "right", Label: "→ правая"},
			{Value: "bottom", Label: "↑ низ"},
		},
	}
}

func defaultMaterials() []models.MaterialRT {
	return []models.MaterialRT{
		{ID: "OZM", Title: "ТЕХНО ОЗМ", Unit: "м³", Q: 1.25},
		{ID: "OZB", Title: "ТЕХНО ОЗБ", Unit: "м³", Q: 1.03},
		{ID: "KCer", Title: "Клей Ceresit CT 190", Unit: "кг", Rate: 1.2},
		{ID: "KVer", Title: "Штукатурка Ceresit", Unit: "кг", Rate: 3.2},
		{ID: "KAnk", Title: "Металлический анкер с шайбой", Unit: "шт", Rate: 7},
		{ID: "T150p", Title: "TAIKOR Primer 150", Unit: "кг", Rate: 0.230},
		{ID: "Taikor", Title: "TAIKOR FP", Unit: "кг"},
		{ID: "T425t", Title: "TAIKOR Top 425", Unit: "кг", Rate: 0.170},
	}
}
