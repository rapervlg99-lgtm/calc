package api

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/go-chi/chi/v5"

	"ozm/backend/internal/storage"
)

type memShareStore struct {
	mu   sync.Mutex
	data map[string]storage.ShareRecord
}

func (m *memShareStore) Create(_ context.Context, rec storage.ShareRecord) (string, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.data == nil {
		m.data = map[string]storage.ShareRecord{}
	}
	if _, ok := m.data[rec.Token]; ok {
		return "", errDuplicate{}
	}
	rec.CreatedAt = time.Now()
	rec.UpdatedAt = rec.CreatedAt
	m.data[rec.Token] = rec
	return rec.Token, nil
}

func (m *memShareStore) Update(_ context.Context, token string, payload json.RawMessage) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	rec, ok := m.data[token]
	if !ok {
		return storage.ErrNotFound
	}
	rec.Payload = payload
	rec.UpdatedAt = time.Now()
	m.data[token] = rec
	return nil
}

func (m *memShareStore) GetByToken(_ context.Context, token string) (storage.ShareRecord, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	rec, ok := m.data[token]
	if !ok {
		return storage.ShareRecord{}, storage.ErrNotFound
	}
	return rec, nil
}

type errDuplicate struct{}

func (errDuplicate) Error() string { return "duplicate" }

// Ссылка обмена: создаётся при входе в калькулятор, отдаётся по токену и
// обновляется по мере правок. Формат токена — «n» + цифры, как ?n1792668187385.
func TestShareLifecycle(t *testing.T) {
	store := &memShareStore{}
	s := &Server{persistence: Persistence{Shares: store}}
	r := chi.NewRouter()
	r.Post("/share", s.handleCreateShare)
	r.Get("/share/{token}", s.handleGetShare)
	r.Put("/share/{token}", s.handleUpdateShare)

	body := `{"payload":{"objectName":"Склад","address":"Рязань","elements":[{"shape":"I-beam_sm"}]}}`
	rec := httptest.NewRecorder()
	r.ServeHTTP(rec, httptest.NewRequest(http.MethodPost, "/share", strings.NewReader(body)))
	if rec.Code != http.StatusOK {
		t.Fatalf("создание: %d %s", rec.Code, rec.Body.String())
	}
	var created shareResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &created); err != nil {
		t.Fatalf("ответ: %v", err)
	}
	if !shareTokenRe.MatchString(created.Token) {
		t.Fatalf("токен «%s» не похож на ?n…", created.Token)
	}

	rec = httptest.NewRecorder()
	r.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/share/"+created.Token, nil))
	if rec.Code != http.StatusOK {
		t.Fatalf("чтение: %d %s", rec.Code, rec.Body.String())
	}
	var got shareResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &got); err != nil {
		t.Fatalf("чтение: %v", err)
	}
	if !strings.Contains(string(got.Payload), "Склад") {
		t.Fatalf("payload потерян: %s", got.Payload)
	}

	// правка: адрес и набор конструкций меняются, ссылка та же
	upd := `{"payload":{"objectName":"Склад","address":"Рязань, ул. Дмитрова, 56"}}`
	rec = httptest.NewRecorder()
	r.ServeHTTP(rec, httptest.NewRequest(http.MethodPut, "/share/"+created.Token, strings.NewReader(upd)))
	if rec.Code != http.StatusOK {
		t.Fatalf("обновление: %d %s", rec.Code, rec.Body.String())
	}
	rec = httptest.NewRecorder()
	r.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/share/"+created.Token, nil))
	if !strings.Contains(rec.Body.String(), "Дмитрова") {
		t.Fatalf("правка не сохранилась: %s", rec.Body.String())
	}
}

func TestShareErrors(t *testing.T) {
	store := &memShareStore{}
	s := &Server{persistence: Persistence{Shares: store}}
	r := chi.NewRouter()
	r.Post("/share", s.handleCreateShare)
	r.Get("/share/{token}", s.handleGetShare)
	r.Put("/share/{token}", s.handleUpdateShare)

	cases := []struct {
		name, method, path, body string
		want                     int
	}{
		{"пустое тело", http.MethodPost, "/share", "", http.StatusBadRequest},
		{"payload не объект", http.MethodPost, "/share", `{"payload":[1,2]}`, http.StatusBadRequest},
		{"без payload", http.MethodPost, "/share", `{}`, http.StatusBadRequest},
		{"кривой токен", http.MethodGet, "/share/abc", "", http.StatusBadRequest},
		{"нет токена", http.MethodGet, "/share/n1700000000000", "", http.StatusNotFound},
		{"обновление несуществующего", http.MethodPut, "/share/n1700000000000", `{"payload":{"a":1}}`, http.StatusNotFound},
	}
	for _, c := range cases {
		rec := httptest.NewRecorder()
		r.ServeHTTP(rec, httptest.NewRequest(c.method, c.path, strings.NewReader(c.body)))
		if rec.Code != c.want {
			t.Fatalf("%s: ожидали %d, получили %d (%s)", c.name, c.want, rec.Code, rec.Body.String())
		}
	}

	// слишком большое состояние — 413, чтобы ссылка не превращалась в файлохранилище
	big := strings.Repeat("x", shareMaxBytes)
	rec := httptest.NewRecorder()
	r.ServeHTTP(rec, httptest.NewRequest(http.MethodPost, "/share", strings.NewReader(`{"payload":{"data":"`+big+`"}}`)))
	if rec.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("большое тело: ожидали 413, получили %d", rec.Code)
	}
}

// Токен — «n» + 13 цифр в обычном случае и с хвостом при коллизии.
func TestShareToken(t *testing.T) {
	now := time.UnixMilli(1792668187385)
	if got := newShareToken(now, 0); got != "n1792668187385" {
		t.Fatalf("токен «%s», ожидали n1792668187385", got)
	}
	tail := newShareToken(now, 1)
	if len(tail) != 17 || !shareTokenRe.MatchString(tail) {
		t.Fatalf("токен с хвостом «%s» не подходит под формат", tail)
	}
}
