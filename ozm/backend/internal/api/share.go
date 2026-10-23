package api

import (
	"crypto/rand"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"math/big"
	"net/http"
	"regexp"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/jackc/pgx/v5/pgconn"

	"ozm/backend/internal/storage"
)

// Ссылки для обмена расчётами.
//
// Состояние калькулятора (объект, адрес, конструкции, бетон) хранится целиком
// как JSON и сервером не разбирается: так формат формы можно менять без
// миграций. Токен — «n» + миллисекунды, как в расчётах на calc.tn.ru
// (?n1792668187385); при коллизии добавляются случайные цифры.

const shareMaxBytes = 256 << 10

var shareTokenRe = regexp.MustCompile(`^n\d{13,17}$`)

// shareBody — тело запроса на создание/обновление черновика.
type shareBody struct {
	Payload json.RawMessage `json:"payload"`
}

// shareResponse — ответ с черновиком.
type shareResponse struct {
	Token     string          `json:"token"`
	Payload   json.RawMessage `json:"payload,omitempty"`
	UpdatedAt time.Time       `json:"updatedAt,omitempty"`
}

// newShareToken — «n» + миллисекунды; при повторах добавляет случайный хвост,
// чтобы не отдать пользователю чужую ссылку.
func newShareToken(now time.Time, attempt int) string {
	base := now.UnixMilli()
	if attempt == 0 {
		return "n" + itoa(base)
	}
	suffix, err := rand.Int(rand.Reader, big.NewInt(1000))
	if err != nil {
		return "n" + itoa(base) + itoa(int64(attempt))
	}
	return "n" + itoa(base) + pad3(suffix.Int64())
}

func itoa(v int64) string {
	if v == 0 {
		return "0"
	}
	neg := v < 0
	if neg {
		v = -v
	}
	var buf [20]byte
	i := len(buf)
	for v > 0 {
		i--
		buf[i] = byte('0' + v%10)
		v /= 10
	}
	if neg {
		i--
		buf[i] = '-'
	}
	return string(buf[i:])
}

func pad3(v int64) string {
	s := itoa(v)
	for len(s) < 3 {
		s = "0" + s
	}
	return s
}

// handleCreateShare — создать ссылку: POST /api/v1/share {payload}.
func (s *Server) handleCreateShare(w http.ResponseWriter, r *http.Request) {
	if s.persistence.Shares == nil {
		writeErr(w, http.StatusServiceUnavailable, "persistence required for share")
		return
	}
	payload, ok := readSharePayload(w, r)
	if !ok {
		return
	}
	// 3 попытки: миллисекунда уникальна почти всегда, хвост — на гонку.
	var lastErr error
	for attempt := 0; attempt < 4; attempt++ {
		token := newShareToken(time.Now(), attempt)
		_, err := s.persistence.Shares.Create(r.Context(), storage.ShareRecord{Token: token, Payload: payload})
		if err == nil {
			writeJSON(w, http.StatusOK, shareResponse{Token: token})
			return
		}
		if isUniqueViolation(err) {
			lastErr = err
			continue
		}
		slog.Error("share create", slog.Any("err", err))
		writeErr(w, http.StatusInternalServerError, err.Error())
		return
	}
	slog.Error("share create: токен не сгенерирован", slog.Any("err", lastErr))
	writeErr(w, http.StatusInternalServerError, "token collision")
}

// handleGetShare — прочитать черновик: GET /api/v1/share/{token}.
func (s *Server) handleGetShare(w http.ResponseWriter, r *http.Request) {
	if s.persistence.Shares == nil {
		writeErr(w, http.StatusServiceUnavailable, "persistence required for share")
		return
	}
	token := chi.URLParam(r, "token")
	if !shareTokenRe.MatchString(token) {
		writeErr(w, http.StatusBadRequest, "bad token")
		return
	}
	rec, err := s.persistence.Shares.GetByToken(r.Context(), token)
	if storage.IsNotFound(err) {
		writeErr(w, http.StatusNotFound, "not found")
		return
	}
	if err != nil {
		writeErr(w, http.StatusInternalServerError, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, shareResponse{Token: rec.Token, Payload: rec.Payload, UpdatedAt: rec.UpdatedAt})
}

// handleUpdateShare — сохранить правки: PUT /api/v1/share/{token} {payload}.
func (s *Server) handleUpdateShare(w http.ResponseWriter, r *http.Request) {
	if s.persistence.Shares == nil {
		writeErr(w, http.StatusServiceUnavailable, "persistence required for share")
		return
	}
	token := chi.URLParam(r, "token")
	if !shareTokenRe.MatchString(token) {
		writeErr(w, http.StatusBadRequest, "bad token")
		return
	}
	payload, ok := readSharePayload(w, r)
	if !ok {
		return
	}
	err := s.persistence.Shares.Update(r.Context(), token, payload)
	if storage.IsNotFound(err) {
		writeErr(w, http.StatusNotFound, "not found")
		return
	}
	if err != nil {
		writeErr(w, http.StatusInternalServerError, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, shareResponse{Token: token})
}

// readSharePayload читает и проверяет тело: JSON-объект разумного размера.
func readSharePayload(w http.ResponseWriter, r *http.Request) (json.RawMessage, bool) {
	body, err := io.ReadAll(io.LimitReader(r.Body, shareMaxBytes+1))
	if err != nil {
		writeErr(w, http.StatusBadRequest, "read body")
		return nil, false
	}
	if len(body) > shareMaxBytes {
		writeErr(w, http.StatusRequestEntityTooLarge, "payload too large")
		return nil, false
	}
	var parsed shareBody
	if err := json.Unmarshal(body, &parsed); err != nil {
		writeErr(w, http.StatusBadRequest, "invalid json")
		return nil, false
	}
	if len(parsed.Payload) == 0 || string(parsed.Payload) == "null" {
		writeErr(w, http.StatusBadRequest, "payload required")
		return nil, false
	}
	var probe map[string]any
	if err := json.Unmarshal(parsed.Payload, &probe); err != nil {
		writeErr(w, http.StatusBadRequest, "payload must be an object")
		return nil, false
	}
	return parsed.Payload, true
}

// isUniqueViolation — ошибка уникальности Postgres (SQLSTATE 23505).
func isUniqueViolation(err error) bool {
	var pgErr *pgconn.PgError
	return errors.As(err, &pgErr) && pgErr.Code == "23505"
}
