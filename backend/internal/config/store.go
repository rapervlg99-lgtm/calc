package config

import (
	"context"
	"encoding/json"
	"fmt"

	"ozm/backend/internal/models"
)

type DictName string

const (
	DictProfiles   DictName = "profiles"
	DictRoll       DictName = "roll"
	DictT500       DictName = "t500"
	DictX500       DictName = "x500"
	DictMaterials  DictName = "materials_rt"
	DictSelects    DictName = "selects"
	DictCalcConfig DictName = "calculation_config"
)

type DictStore interface {
	GetAll(ctx context.Context) (map[DictName][]byte, error)
	Upsert(ctx context.Context, name DictName, payload []byte, updatedBy string) error
	Count(ctx context.Context) (int, error)
}

type Store struct {
	Profiles  []models.ProfileFamily
	Roll      []models.RollMark
	T500      []models.T500Row
	X500      []models.X500Coat
	Materials []models.MaterialRT
	Selects   map[string][]models.SelectOption
	Config    models.CalcConfig
}

func LoadFromDB(ctx context.Context, ds DictStore) (*Store, error) {
	raw, err := ds.GetAll(ctx)
	if err != nil {
		return nil, err
	}
	s := &Store{Selects: map[string][]models.SelectOption{}}
	if err := unmarshal(raw, DictProfiles, &s.Profiles); err != nil {
		return nil, err
	}
	if err := unmarshal(raw, DictRoll, &s.Roll); err != nil {
		return nil, err
	}
	if err := unmarshal(raw, DictT500, &s.T500); err != nil {
		return nil, err
	}
	if err := unmarshal(raw, DictX500, &s.X500); err != nil {
		return nil, err
	}
	if err := unmarshal(raw, DictMaterials, &s.Materials); err != nil {
		return nil, err
	}
	if err := unmarshal(raw, DictSelects, &s.Selects); err != nil {
		return nil, err
	}
	if err := unmarshal(raw, DictCalcConfig, &s.Config); err != nil {
		return nil, err
	}
	return s, nil
}

func LoadFromFiles(dir string) (*Store, error) {
	// Used by unit tests / dcextract verification without PG.
	read := func(name string, dest any) error {
		data, err := osReadFile(dir, name)
		if err != nil {
			return err
		}
		return json.Unmarshal(data, dest)
	}
	s := &Store{Selects: map[string][]models.SelectOption{}}
	if err := read("profiles.json", &s.Profiles); err != nil {
		return nil, err
	}
	if err := read("roll.json", &s.Roll); err != nil {
		return nil, err
	}
	if err := read("t500.json", &s.T500); err != nil {
		return nil, err
	}
	if err := read("x500.json", &s.X500); err != nil {
		return nil, err
	}
	if err := read("materials_rt.json", &s.Materials); err != nil {
		return nil, err
	}
	if err := read("selects.json", &s.Selects); err != nil {
		return nil, err
	}
	if err := read("calculation_config.json", &s.Config); err != nil {
		return nil, err
	}
	return s, nil
}

func (s *Store) DictsResponse() models.DictsResponse {
	return models.DictsResponse{
		Profiles:  s.Profiles,
		Roll:      s.Roll,
		Selects:   s.Selects,
		Materials: s.Materials,
		Config:    s.Config,
	}
}

func unmarshal(raw map[DictName][]byte, name DictName, dest any) error {
	b, ok := raw[name]
	if !ok {
		return fmt.Errorf("missing dict %s", name)
	}
	if err := json.Unmarshal(b, dest); err != nil {
		return fmt.Errorf("unmarshal dict %s: %w", name, err)
	}
	return nil
}
