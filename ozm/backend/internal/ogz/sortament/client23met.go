package sortament

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strconv"
	"strings"
)

// DefaultBaseURL — корень справочника профильного проката.
const DefaultBaseURL = "https://23met.ru"

// browserUA — без браузерного User-Agent 23met отвечает 429 (rate-limit).
const browserUA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) " +
	"AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"

// massRe ищет «Масса 1 м</td><td>56.6 кг</td>» — каноническая строка карточки
// профиля на /spravka/<категория>/<профиль>. Десятичная точка или запятая.
var massRe = regexp.MustCompile(`Масса\s*1\s*м\s*</td>\s*<td>\s*([0-9]+(?:[.,][0-9]+)?)\s*кг`)

// Client23met — провайдер массы 1 пог. метра с 23met.ru/spravka.
//
// Запрашивает карточку профиля /spravka/<категория>/<профиль> (категория — из
// наименования группы, см. Category) и извлекает «Масса 1 м». При любой ошибке
// возвращает ошибку, а Resolver делает graceful degradation на ручной ввод
// («нет данных» — внимание проверяющего, ТЗ §5).
type Client23met struct {
	http    *http.Client
	baseURL string
}

// NewClient23met создаёт клиент. httpClient обязателен (таймауты — он + context).
func NewClient23met(httpClient *http.Client) *Client23met {
	return &Client23met{http: httpClient, baseURL: DefaultBaseURL}
}

// MassPerMeter запрашивает массу 1 пог. метра по slug категории и марке профиля.
func (c *Client23met) MassPerMeter(ctx context.Context, category, mark string) (float64, error) {
	if category == "" {
		return 0, fmt.Errorf("sortament: empty category")
	}
	if mark == "" {
		return 0, fmt.Errorf("sortament: empty mark")
	}
	u := fmt.Sprintf("%s/spravka/%s/%s", c.baseURL, category, url.PathEscape(mark))
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		return 0, err
	}
	req.Header.Set("User-Agent", browserUA)
	req.Header.Set("Accept-Language", "ru-RU,ru;q=0.9")

	resp, err := c.http.Do(req)
	if err != nil {
		return 0, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return 0, fmt.Errorf("sortament: 23met status %d for %s/%s", resp.StatusCode, category, mark)
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, 4<<20))
	if err != nil {
		return 0, err
	}
	return parseMassPerMeter(string(body))
}

// parseMassPerMeter извлекает массу 1 пог. метра (кг/м) из HTML карточки профиля.
func parseMassPerMeter(page string) (float64, error) {
	m := massRe.FindStringSubmatch(page)
	if m == nil {
		return 0, fmt.Errorf("sortament: mass not found in response")
	}
	v, err := strconv.ParseFloat(strings.ReplaceAll(m[1], ",", "."), 64)
	if err != nil {
		return 0, err
	}
	return v, nil
}
