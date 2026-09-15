package llm

// OpenRouter — облачный vision-провайдер (OpenAI-совместимый /chat/completions).
// Альтернатива локальному Ollama: инференс за секунды вместо минут на плотных
// листах. Подключается через тот же интерфейс VisionModel, без правок recognition.
//
// ВНИМАНИЕ по 152-ФЗ: OpenRouter маршрутизирует запрос на сторонних провайдеров
// (как правило вне РФ) — изображение чертежа покидает периметр. Включать только с
// согласия заказчика; РФ-резидентная альтернатива — Yandex Vision (см. план).
//
// Бесплатные модели OpenRouter (суффикс ":free") жёстко лимитированы (≈20 запросов/
// мин, ~50/сутки без баланса) и нестабильны — подходят для разработки/теста, для
// прода надёжнее дешёвая платная модель.

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

// DefaultOpenRouterURL — корень OpenAI-совместимого API OpenRouter.
const DefaultOpenRouterURL = "https://openrouter.ai/api/v1"

// DefaultOpenRouterModel — бесплатная vision-модель, тюнингованная под OCR/таблицы.
const DefaultOpenRouterModel = "nvidia/nemotron-nano-12b-v2-vl:free"

// OpenRouterClient вызывает /chat/completions OpenRouter в мультимодальном режиме.
type OpenRouterClient struct {
	baseURL string
	model   string
	apiKey  string
	referer string
	title   string
	maxEdge int
	http    *http.Client
}

// OpenRouterOptions конфигурирует клиента OpenRouter.
type OpenRouterOptions struct {
	BaseURL string        // по умолчанию https://openrouter.ai/api/v1
	Model   string        // напр. nvidia/nemotron-nano-12b-v2-vl:free
	APIKey  string        // обязателен (Bearer-токен OpenRouter)
	Timeout time.Duration // потолок на один vision-вызов
	// Referer/Title — необязательная атрибуция приложения в рейтингах OpenRouter
	// (заголовки HTTP-Referer и X-Title). Не влияют на результат.
	Referer string
	Title   string
	// MaxEdge — большая сторона изображения до отправки (см. FitMaxEdge). 0 → DefaultMaxImageEdge.
	MaxEdge int
}

// NewOpenRouterClient собирает клиента с безопасными дефолтами.
func NewOpenRouterClient(o OpenRouterOptions) *OpenRouterClient {
	if o.BaseURL == "" {
		o.BaseURL = DefaultOpenRouterURL
	}
	if o.Model == "" {
		o.Model = DefaultOpenRouterModel
	}
	if o.Timeout <= 0 {
		o.Timeout = 2 * time.Minute
	}
	if o.MaxEdge <= 0 {
		o.MaxEdge = DefaultMaxImageEdge
	}
	return &OpenRouterClient{
		baseURL: o.BaseURL,
		model:   o.Model,
		apiKey:  o.APIKey,
		referer: o.Referer,
		title:   o.Title,
		maxEdge: o.MaxEdge,
		http:    &http.Client{Timeout: o.Timeout},
	}
}

// Model возвращает имя используемой модели (для логов/метрик/источника).
func (c *OpenRouterClient) Model() string { return c.model }

// chatRequest — тело /chat/completions (подмножество OpenAI-схемы).
type chatRequest struct {
	Model          string         `json:"model"`
	Temperature    float64        `json:"temperature"`
	ResponseFormat map[string]any `json:"response_format,omitempty"`
	Messages       []chatMessage  `json:"messages"`
}

type chatMessage struct {
	Role    string        `json:"role"`
	Content []contentPart `json:"content"`
}

// contentPart — мультимодальная часть сообщения: текст или image_url (data-URL).
type contentPart struct {
	Type     string    `json:"type"`
	Text     string    `json:"text,omitempty"`
	ImageURL *imageURL `json:"image_url,omitempty"`
}

type imageURL struct {
	URL string `json:"url"`
}

type chatResponse struct {
	Choices []struct {
		Message struct {
			Content string `json:"content"`
		} `json:"message"`
	} `json:"choices"`
	Error *struct {
		Message string `json:"message"`
	} `json:"error"`
}

// Vision отправляет изображение и промпт модели и возвращает её ответ. Изображение
// передаётся data-URL с base64 (требование OpenAI-схемы). Контекст вызывающего
// соблюдается поверх HTTP-таймаута клиента.
func (c *OpenRouterClient) Vision(ctx context.Context, prompt string, image []byte) (string, error) {
	if c.apiKey == "" {
		return "", fmt.Errorf("llm: openrouter api key is empty")
	}
	fitted, err := FitMaxEdge(image, c.maxEdge)
	if err != nil {
		return "", err
	}
	dataURL := "data:image/png;base64," + base64.StdEncoding.EncodeToString(fitted)
	reqBody := chatRequest{
		Model:       c.model,
		Temperature: 0, // детерминированный вывод (как у Ollama)
		// Просим строгий JSON-объект. Часть бесплатных моделей игнорирует поле —
		// recognition.extractJSON всё равно вырежет JSON из обрамлённого ответа.
		ResponseFormat: map[string]any{"type": "json_object"},
		Messages: []chatMessage{{
			Role: "user",
			Content: []contentPart{
				{Type: "text", Text: prompt},
				{Type: "image_url", ImageURL: &imageURL{URL: dataURL}},
			},
		}},
	}
	buf, err := json.Marshal(reqBody)
	if err != nil {
		return "", fmt.Errorf("llm: marshal request: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+"/chat/completions", bytes.NewReader(buf))
	if err != nil {
		return "", fmt.Errorf("llm: build request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+c.apiKey)
	// Урок А1: на shared-шлюзе запрещаем кэширование чужих ответов.
	req.Header.Set("Cache-Control", "no-store")
	if c.referer != "" {
		req.Header.Set("HTTP-Referer", c.referer)
	}
	if c.title != "" {
		req.Header.Set("X-Title", c.title)
	}

	resp, err := c.http.Do(req)
	if err != nil {
		return "", fmt.Errorf("llm: call openrouter: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(io.LimitReader(resp.Body, 8<<20))
	if err != nil {
		return "", fmt.Errorf("llm: read response: %w", err)
	}
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("llm: openrouter status %d: %s", resp.StatusCode, string(body))
	}

	var cr chatResponse
	if err := json.Unmarshal(body, &cr); err != nil {
		return "", fmt.Errorf("llm: decode response: %w", err)
	}
	if cr.Error != nil && cr.Error.Message != "" {
		return "", fmt.Errorf("llm: openrouter error: %s", cr.Error.Message)
	}
	if len(cr.Choices) == 0 {
		return "", fmt.Errorf("llm: openrouter returned no choices")
	}
	return cr.Choices[0].Message.Content, nil
}
