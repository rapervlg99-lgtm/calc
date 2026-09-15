package llm

import (
	"bytes"
	"image"
	"image/png"
	"testing"
)

func TestFitMaxEdgeDownscales(t *testing.T) {
	src := image.NewRGBA(image.Rect(0, 0, 4000, 2000))
	var buf bytes.Buffer
	if err := png.Encode(&buf, src); err != nil {
		t.Fatal(err)
	}
	out, err := FitMaxEdge(buf.Bytes(), 1000)
	if err != nil {
		t.Fatal(err)
	}
	img, err := png.Decode(bytes.NewReader(out))
	if err != nil {
		t.Fatal(err)
	}
	b := img.Bounds()
	if b.Dx() != 1000 || b.Dy() != 500 {
		t.Fatalf("got %dx%d, want 1000x500", b.Dx(), b.Dy())
	}
}

func TestFitMaxEdgeNoopWhenSmall(t *testing.T) {
	src := image.NewRGBA(image.Rect(0, 0, 100, 80))
	var buf bytes.Buffer
	if err := png.Encode(&buf, src); err != nil {
		t.Fatal(err)
	}
	in := buf.Bytes()
	out, err := FitMaxEdge(in, 2048)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(in, out) {
		t.Fatal("expected original bytes when already within max edge")
	}
}
