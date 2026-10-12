package api

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"
)

// /readyz — проба готовности для балансировщика и smoke приёмки: живой процесс
// отвечает за /healthz, а готовность означает доступную зависимость (БД).
// Ошибка зависимости обязана давать 503: иначе выкат уводит трафик на сервис,
// который не может обслужить запрос.
func TestReadyz(t *testing.T) {
	s := &Server{}

	rec := httptest.NewRecorder()
	s.handleReady(rec, httptest.NewRequest(http.MethodGet, "/readyz", nil))
	if rec.Code != http.StatusOK {
		t.Fatalf("без проверки зависимостей ожидали 200, получили %d", rec.Code)
	}

	s.opts.Ready = func(context.Context) error { return errors.New("pg down") }
	rec = httptest.NewRecorder()
	s.handleReady(rec, httptest.NewRequest(http.MethodGet, "/readyz", nil))
	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("недоступная БД: ожидали 503, получили %d", rec.Code)
	}

	s.opts.Ready = func(context.Context) error { return nil }
	rec = httptest.NewRecorder()
	s.handleReady(rec, httptest.NewRequest(http.MethodGet, "/readyz", nil))
	if rec.Code != http.StatusOK {
		t.Fatalf("доступная БД: ожидали 200, получили %d", rec.Code)
	}
}
