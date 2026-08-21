package models

// Domain models for OZM (fire protection) calculator.

type SelectOption struct {
	Value string `json:"value"`
	Label string `json:"label"`
	Extra map[string]string `json:"extra,omitempty"`
}

type ProfileFamily struct {
	ID     string          `json:"id"`
	Label  string          `json:"label"`
	Hard   int             `json:"hard"`
	Shapes []ProfileShape  `json:"shapes"`
}

type ProfileShape struct {
	ID    string `json:"id"`
	Label string `json:"label"`
	Code  string `json:"code,omitempty"`
	Picture string `json:"picture,omitempty"`
}

type RollMark struct {
	ID     string             `json:"id"`
	Shape  string             `json:"shape"`
	Label  string             `json:"label"`
	Dims   map[string]float64 `json:"dims"`
}

type T500Row struct {
	BaseDelta float64 `json:"baseDelta"`
	A         float64 `json:"a"`
	B         float64 `json:"b"`
	Thickness float64 `json:"thickness"`
}

type X500Row struct {
	Dpr  float64 `json:"dpr"`
	Delta float64 `json:"delta"`
	Rate  float64 `json:"rate"`
}

type X500RColumn struct {
	Min  float64   `json:"min"`
	Heat *X500Row  `json:"heat,omitempty"`
	Rows []X500Row `json:"rows"`
}

type X500Coat struct {
	Index   int            `json:"index"`
	Columns []X500RColumn  `json:"columns"`
}

type MaterialRT struct {
	ID    string  `json:"id"`
	Title string  `json:"title"`
	Unit  string  `json:"unit"`
	Q     float64 `json:"q,omitempty"`
	Rate  float64 `json:"rate,omitempty"`
	Delta float64 `json:"delta,omitempty"`
	Extra map[string]any `json:"extra,omitempty"`
}

type CalcConfig struct {
	TaikorQ       float64 `json:"taikorQ"`
	OzmQ          float64 `json:"ozmQ"`
	OzbQ          float64 `json:"ozbQ"`
	SteelDensity  float64 `json:"steelDensity"`
	OzbByR        map[string]float64 `json:"ozbByR"` // "180"→50, "240"→40
}

type DictsResponse struct {
	Profiles []ProfileFamily `json:"profiles"`
	Roll     []RollMark      `json:"roll"`
	Selects  map[string][]SelectOption `json:"selects"`
	Materials []MaterialRT   `json:"materials"`
	Config   CalcConfig      `json:"config"`
}

// --- Calc request / response ---

type HeatedSides struct {
	Left   bool `json:"left"`
	Top    bool `json:"top"`
	Right  bool `json:"right"`
	Bottom bool `json:"bottom"`
}

type ElementInput struct {
	ID           string             `json:"id,omitempty"`
	Title        string             `json:"title,omitempty"`
	Shape        string             `json:"shape" validate:"required"`
	RollID       string             `json:"rollId,omitempty"`
	Dims         map[string]float64 `json:"dims,omitempty"`
	FrType       string             `json:"frType" validate:"required"` // "1" bearing / "0" self
	HtLevel      float64            `json:"htLevel" validate:"required,min=15,max=240"`
	Sides        HeatedSides        `json:"sides"`
	LengthM      float64            `json:"lengthM" validate:"required,gt=0"`
	Quantity     float64            `json:"quantity" validate:"required,gt=0"`
	Coat         string             `json:"coat" validate:"required"` // "1","2","3","4","1.5"
	Method       string             `json:"method" validate:"required,oneof=0 1"` // 0 contour 1 box
	Primer       bool               `json:"primer"`
	Enamel       bool               `json:"enamel"`
	Decor        bool               `json:"decor"`
}

type GroupInput struct {
	ID       string         `json:"id,omitempty"`
	Title    string         `json:"title,omitempty"`
	Quantity float64        `json:"quantity" validate:"required,gt=0"`
	Elements []ElementInput `json:"elements" validate:"required,min=1,dive"`
}

type BetonInput struct {
	AreaM2  float64 `json:"areaM2" validate:"gt=0"`
	HtLevel float64 `json:"htLevel" validate:"oneof=180 240"`
}

type CalcRequest struct {
	ObjectName   string       `json:"objectName" validate:"required,min=1,max=200"`
	Address      string       `json:"address" validate:"required,min=1,max=300"`
	Consent      bool         `json:"consent" validate:"eq=true"`
	Dominance    string       `json:"dominance,omitempty"`
	FrDurability string       `json:"frDurability" validate:"required"`
	Groups       []GroupInput `json:"groups" validate:"required,min=1,dive"`
	Beton        *BetonInput  `json:"beton,omitempty"`
	// Unit price overrides in kopecks (optional, for Excel-like costing).
	MaterialPriceEditsCents map[string]int64 `json:"materialPriceEditsCents,omitempty"`
}

type MaterialLine struct {
	ID               string  `json:"id"`
	Title            string  `json:"title"`
	Unit             string  `json:"unit"`
	Quantity         float64 `json:"quantity"`
	UnitPriceCents   int64   `json:"unitPriceCents"`
	TotalCents       int64   `json:"totalCents"`
	SourceElementID  string  `json:"sourceElementId,omitempty"`
	SourceGroupID    string  `json:"sourceGroupId,omitempty"`
}

type ElementResult struct {
	ID          string  `json:"id"`
	GroupID     string  `json:"groupId"`
	Title       string  `json:"title"`
	Shape       string  `json:"shape"`
	F           float64 `json:"f"`           // mm²
	Pi          float64 `json:"pi"`          // mm
	Dpr         float64 `json:"dpr"`         // mm
	Delta       float64 `json:"delta"`       // mm coating thickness
	Lining      int     `json:"lining"`      // 1 box 2 contour 3 round
	AreaM2      float64 `json:"areaM2"`
	Volume      float64 `json:"volume"`
	Exclusion   string  `json:"exclusion,omitempty"`
	Coat        string  `json:"coat"`
	HtLevel     float64 `json:"htLevel"`
	LengthM     float64 `json:"lengthM"`
	Quantity    float64 `json:"quantity"`
}

type Totals struct {
	MaterialsCents int64 `json:"materialsCents"`
	GrandCents     int64 `json:"grandCents"`
}

type CalcResponse struct {
	ID        string          `json:"id,omitempty"`
	Inputs    CalcRequest     `json:"inputs"`
	Elements  []ElementResult `json:"elements"`
	Materials []MaterialLine  `json:"materials"`
	Totals    Totals          `json:"totals"`
	Trace     []string        `json:"trace,omitempty"`
}

type ExportRequest struct {
	CalcID string `json:"calcId" validate:"required,uuid"`
}
