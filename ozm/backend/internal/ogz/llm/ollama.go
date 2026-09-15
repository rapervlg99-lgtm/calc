// Package llm инкапсулирует обращения к LLM-провайдеру распознавания. В MVP это
// локальная мультимодальная модель через Ollama (qwen3.5:9b, capability vision),
// запускаемая на РФ-инфраструктуре — данные не покидают периметр (152-ФЗ).
//
// Архитектурно это первый провайдер цепочки `litellm → ollama → yandex`: интерфейс
// VisionModel позволяет подменить бэкенд, не трогая internal/recognition.
//
// Эмпирические настройки (подтверждены прогоном на реальных сканах спецификаций):
//   - think=false — обязательно: с включённым «размышлением» qwen3.5 жжёт минуты и
//     возвращает пустой ответ; с выkey — 60–90 с и корректный JSON;
//   - format=json + temperature=0 — для строгого, детерминированного вывода;
//   - shared-шлюз помечаем no-store на уровне HTTP (урок А1), для локального Ollama
//     это no-op, но контракт сохраняем при переходе на общий шлюз.
package llm

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

// VisionModel извлекает текстовый ответ модели по изображению и инструкции.
// Возвращаемая строка — сырой ответ модели (ожидается JSON по схеме recognition).
type VisionModel interface {
	Vision(ctx context.Context, prompt string, image []byte) (string, error)
}

// OllamaClient вызывает /api/generate локального Ollama в мультимодальном режиме.
type OllamaClient struct {
	baseURL    string
	model      string
	http       *http.Client
	numCtx     int
	numPredict int
	keepAlive  string
	maxEdge    int
}

// Options конфигурирует клиента Ollama.
type Options struct {
	BaseURL string        // напр. http://localhost:11434 или http://host.docker.internal:11434
	Model   string        // напр. qwen3.5:9b
	Timeout time.Duration // потолок на один vision-вызов
	// NumCtx — размер контекстного окна (num_ctx). Дефолт Ollama (~4096) мал: токены
	// изображения + промпт почти исчерпывают окно, и на плотной спецификации (A2, 50+
	// строк) модель не успевает дописать JSON — он обрывается на полуслове и не
	// парсится. Подтверждено эмпирически: при num_ctx=4096 ответ режется на ~9000
	// символах (done_reason=length), при 32768 — завершается естественно
	// (done_reason=stop) за 245 с и даёт валидные 52 строки. Парадоксально быстрее:
	// без запаса модель «убегает» до конца окна.
	NumCtx int
	// NumPredict — потолок токенов ответа. Держим высоким, чтобы длинная таблица
	// уместилась целиком; -1 = без ограничения (ограничивает только NumCtx).
	NumPredict int
	// KeepAlive — сколько Ollama держит модель в памяти после ответа (формат Ollama:
	// "30m", "24h", "-1" = бесконечно, "0" = выгружать сразу). По умолчанию Ollama
	// выгружает через ~5 мин простоя, и каждое новое задание перезагружает 9B-модель
	// (холодный старт — десятки секунд). Держим тёплой между заданиями.
	KeepAlive string
	// MaxEdge — большая сторона изображения до отправки (см. FitMaxEdge). 0 → DefaultMaxImageEdge.
	MaxEdge int
}

// NewOllamaClient собирает клиента с безопасными дефолтами.
func NewOllamaClient(o Options) *OllamaClient {
	if o.BaseURL == "" {
		o.BaseURL = "http://localhost:11434"
	}
	if o.Model == "" {
		o.Model = "qwen3.5:9b"
	}
	if o.Timeout <= 0 {
		o.Timeout = 3 * time.Minute
	}
	if o.NumCtx <= 0 {
		o.NumCtx = 32768
	}
	if o.NumPredict == 0 {
		o.NumPredict = 8192
	}
	if o.KeepAlive == "" {
		o.KeepAlive = "30m"
	}
	if o.MaxEdge <= 0 {
		o.MaxEdge = DefaultMaxImageEdge
	}
	return &OllamaClient{
		baseURL:    o.BaseURL,
		model:      o.Model,
		http:       &http.Client{Timeout: o.Timeout},
		numCtx:     o.NumCtx,
		numPredict: o.NumPredict,
		keepAlive:  o.KeepAlive,
		maxEdge:    o.MaxEdge,
	}
}

// Model возвращает имя используемой модели (для логов/метрик/источника).
func (c *OllamaClient) Model() string { return c.model }

type generateRequest struct {
	Model     string         `json:"model"`
	Prompt    string         `json:"prompt"`
	Images    []string       `json:"images,omitempty"`
	Stream    bool           `json:"stream"`
	Think     bool           `json:"think"`
	Format    string         `json:"format,omitempty"`
	KeepAlive string         `json:"keep_alive,omitempty"`
	Options   map[string]any `json:"options,omitempty"`
}

type generateResponse struct {
	Response   string `json:"response"`
	Done       bool   `json:"done"`
	DoneReason string `json:"done_reason"`
	EvalCount  int    `json:"eval_count"`
	Error      string `json:"error"`
}

// Vision отправляет изображение и промпт модели и возвращает её ответ. Изображение
// кодируется в base64 (требование Ollama). Контекст вызывающего соблюдается поверх
// HTTP-таймаута клиента.
func (c *OllamaClient) Vision(ctx context.Context, prompt string, image []byte) (string, error) {
	fitted, err := FitMaxEdge(image, c.maxEdge)
	if err != nil {
		return "", err
	}
	reqBody := generateRequest{
		Model:     c.model,
		Prompt:    prompt,
		Images:    []string{base64.StdEncoding.EncodeToString(fitted)},
		Stream:    false,
		Think:     false, // критично: иначе пустой ответ (см. doc пакета)
		Format:    "json",
		KeepAlive: c.keepAlive, // держим модель тёплой между заданиями (анти-холодный-старт)
		Options: map[string]any{
			"temperature": 0,
			// Без достаточного num_ctx JSON обрывается на плотных листах (см. doc Options).
			"num_ctx":     c.numCtx,
			"num_predict": c.numPredict,
		},
	}
	buf, err := json.Marshal(reqBody)
	if err != nil {
		return "", fmt.Errorf("llm: marshal request: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+"/api/generate", bytes.NewReader(buf))
	if err != nil {
		return "", fmt.Errorf("llm: build request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	// Урок А1: на shared-шлюзе запрещаем кэширование чужих ответов.
	req.Header.Set("Cache-Control", "no-store")

	resp, err := c.http.Do(req)
	if err != nil {
		return "", fmt.Errorf("llm: call ollama: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(io.LimitReader(resp.Body, 8<<20))
	if err != nil {
		return "", fmt.Errorf("llm: read response: %w", err)
	}
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("llm: ollama status %d: %s", resp.StatusCode, string(body))
	}

	var gr generateResponse
	if err := json.Unmarshal(body, &gr); err != nil {
		return "", fmt.Errorf("llm: decode response: %w", err)
	}
	if gr.Error != "" {
		return "", fmt.Errorf("llm: ollama error: %s", gr.Error)
	}
	if gr.DoneReason == "length" && gr.Response != "" {
		// Не фейлим здесь: recognition.Parse попробует salvage обрезанного JSON.
		// Маркер в ответе не добавляем — parse ждёт чистый JSON.
		return gr.Response, nil
	}
	return gr.Response, nil
}
