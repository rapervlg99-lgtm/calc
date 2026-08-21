package llm

import (
	"bytes"
	"fmt"
	"image"
	"image/jpeg"
	"image/png"
)

// DefaultMaxImageEdge — максимальная сторона PNG/JPEG перед отправкой в vision.
// Эмпирически: A2 @150 DPI (~5200×2500) даёт пустой/обрезанный JSON у qwen3.5:9b;
// после fit до ~2048 модель стабильно возвращает строки (проверено на том же листе).
const DefaultMaxImageEdge = 2048

// FitMaxEdge уменьшает изображение так, чтобы большая сторона была ≤ maxEdge.
// Если уже меньше — возвращает исходные байты без перекодирования.
// Поддерживаются PNG и JPEG; результат всегда PNG (контракт VisionModel).
func FitMaxEdge(img []byte, maxEdge int) ([]byte, error) {
	if maxEdge <= 0 {
		maxEdge = DefaultMaxImageEdge
	}
	if len(img) == 0 {
		return img, nil
	}
	src, _, err := image.Decode(bytes.NewReader(img))
	if err != nil {
		// Не PNG/JPEG — не трогаем байты (как раньше уходило в модель as-is).
		return img, nil
	}
	b := src.Bounds()
	w, h := b.Dx(), b.Dy()
	if w <= maxEdge && h <= maxEdge {
		return img, nil
	}
	scale := float64(maxEdge) / float64(w)
	if h > w {
		scale = float64(maxEdge) / float64(h)
	}
	nw := int(float64(w)*scale + 0.5)
	nh := int(float64(h)*scale + 0.5)
	if nw < 1 {
		nw = 1
	}
	if nh < 1 {
		nh = 1
	}
	dst := image.NewRGBA(image.Rect(0, 0, nw, nh))
	for y := 0; y < nh; y++ {
		sy := b.Min.Y + y*h/nh
		for x := 0; x < nw; x++ {
			sx := b.Min.X + x*w/nw
			dst.Set(x, y, src.At(sx, sy))
		}
	}
	var buf bytes.Buffer
	if err := png.Encode(&buf, dst); err != nil {
		return nil, fmt.Errorf("llm: encode png: %w", err)
	}
	return buf.Bytes(), nil
}

// Ensure JPEG decoder is linked (сканы иногда приходят как JPEG).
var _ = jpeg.Decode
