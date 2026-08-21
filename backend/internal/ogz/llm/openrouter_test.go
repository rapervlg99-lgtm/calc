package llm

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestOpenRouterVisionParsesContent(t *testing.T) {
	var gotAuth, gotBody string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotAuth = r.Header.Get("Authorization")
		b, _ := io.ReadAll(r.Body)
		gotBody = string(b)
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"choices":[{"message":{"content":"{\"rows\":[]}"}}]}`)
	}))
	defer srv.Close()

	c := NewOpenRouterClient(OpenRouterOptions{BaseURL: srv.URL, Model: "test/model:free", APIKey: "sk-test"})
	out, err := c.Vision(context.Background(), "извлеки таблицу", []byte{0x89, 0x50})
	if err != nil {
		t.Fatalf("Vision error: %v", err)
	}
	if out != `{"rows":[]}` {
		t.Errorf("content = %q, want JSON string", out)
	}
	if gotAuth != "Bearer sk-test" {
		t.Errorf("auth header = %q", gotAuth)
	}
	// Запрос должен нести мультимодальный image_url с data-URL base64.
	if !strings.Contains(gotBody, "data:image/png;base64,") {
		t.Errorf("request body missing data-url image: %s", gotBody)
	}
	// И модель из конфига.
	var req map[string]any
	if err := json.Unmarshal([]byte(gotBody), &req); err != nil {
		t.Fatalf("request not JSON: %v", err)
	}
	if req["model"] != "test/model:free" {
		t.Errorf("model = %v, want test/model:free", req["model"])
	}
}

func TestOpenRouterEmptyKey(t *testing.T) {
	c := NewOpenRouterClient(OpenRouterOptions{Model: "m", APIKey: ""})
	if _, err := c.Vision(context.Background(), "p", []byte{1}); err == nil {
		t.Fatal("expected error on empty api key")
	}
}

func TestOpenRouterNon200(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusTooManyRequests)
		_, _ = io.WriteString(w, `{"error":{"message":"rate limited"}}`)
	}))
	defer srv.Close()

	c := NewOpenRouterClient(OpenRouterOptions{BaseURL: srv.URL, Model: "m", APIKey: "k"})
	if _, err := c.Vision(context.Background(), "p", []byte{1}); err == nil {
		t.Fatal("expected error on 429")
	}
}
