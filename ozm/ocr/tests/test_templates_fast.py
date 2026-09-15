# -*- coding: utf-8 -*-
"""Шаблоны глифов на тесном холсте и очередь заданий веб-сервера.

Зачем: лист АП 2502-19 читался больше пяти минут. Профиль показал, что три
минуты уходят на рендер шаблонов (холст (3·кегль)² на каждый символ), а два
задания, запущенные параллельно, уводили контейнер в своп и одно из них
зависало со статусом running.
"""
from __future__ import annotations

import json
import threading
import time

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from ocrpdf import glyph_ocr, webapp
from ocrpdf.glyph_ocr import CHARSET_TEXT, _render, _templates, available_fonts


def _slow_template(font_path: str, size_px: int, ch: str):
    """Старый способ: большой холст. Эталон для сравнения."""
    f = ImageFont.truetype(font_path, size_px)
    ascent, _ = f.getmetrics()
    pad = size_px
    side = size_px * 3 + 2 * pad
    im = Image.new("L", (side, side), 0)
    ImageDraw.Draw(im).text((pad, pad), ch, font=f, fill=255)
    a = np.array(im) > 110
    ys, xs = np.nonzero(a)
    if len(xs) == 0:
        return None
    return (a[ys.min():ys.max() + 1, xs.min():xs.max() + 1],
            float(ys.max() - (pad + ascent)), float(xs.min() - pad))


@pytest.mark.parametrize("size", [18, 47, 120])
def test_tight_canvas_matches_big_canvas(size):
    fonts = available_fonts()
    for font in fonts[:3]:
        for tpl in _templates(font, size, CHARSET_TEXT):
            ref = _slow_template(font, size, tpl.ch)
            assert ref is not None, (font, tpl.ch)
            bm, bot, lsb = ref
            assert bm.shape == tpl.bm.shape, (font, tpl.ch)
            assert np.array_equal(bm, tpl.bm), (font, tpl.ch)
            assert bot == tpl.bot and lsb == tpl.lsb, (font, tpl.ch)
            # маска — самостоятельный массив, а не срез большого холста
            assert tpl.bm.base is None


def test_render_returns_small_canvas():
    f = ImageFont.truetype(available_fonts()[0], 200)
    a, ox, oy = _render(f, "Н")
    assert a.shape[0] < 300 and a.shape[1] < 300
    assert a.any()


def test_font_metrics_unchanged_by_canvas():
    font = available_fonts()[0]
    cap, xh = glyph_ocr._font_metrics(font, 60)
    ref = []
    f = ImageFont.truetype(font, 60)
    for probe in ("Н", "х"):
        im = Image.new("L", (180, 180), 0)
        ImageDraw.Draw(im).text((30, 30), probe, font=f, fill=255)
        ys, _ = np.nonzero(np.array(im) > 110)
        ref.append(float(ys.max() - ys.min() + 1))
    assert (cap, xh) == tuple(ref)


def test_jobs_run_one_at_a_time(monkeypatch, tmp_path):
    monkeypatch.setattr(webapp, "_jobs_root", str(tmp_path))
    active, peak, lock = [0], [0], threading.Lock()

    def fake_run(src, out_dir, opts):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.15)
        with lock:
            active[0] -= 1
        return {"tables_found": 0, "pages": [], "table_quality": [],
                "cells_total": 0, "cells_non_empty": 0, "cells_low_confidence": 0,
                "cells_by_source": {}, "tables_unreadable": 0,
                "arithmetic_checks": {}, "failed_checks": []}

    monkeypatch.setattr(webapp, "run", fake_run)
    monkeypatch.setattr(webapp, "_build_envelope",
                        lambda job, filename, report, out_dir: {"job": job, "report": report})
    jobs = [webapp._prepare_job("x.pdf", b"%PDF-1.4") for _ in range(3)]
    threads = [threading.Thread(target=webapp._run_job, args=(j, "x.pdf", webapp.Options()))
               for j in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert peak[0] == 1
    for j in jobs:
        st = (tmp_path / j / "status.json").read_text(encoding="utf-8")
        assert '"done"' in st


def test_orphaned_running_jobs_marked_on_start(monkeypatch, tmp_path):
    monkeypatch.setattr(webapp, "_jobs_root", str(tmp_path))
    running = webapp._prepare_job("a.pdf", b"%PDF-1.4")
    done = webapp._prepare_job("b.pdf", b"%PDF-1.4")
    webapp._write_status(done, {"status": "done", "filename": "b.pdf"})
    assert webapp._mark_orphaned_jobs() == 1
    st = json.loads((tmp_path / running / "status.json").read_text(encoding="utf-8"))
    assert st["status"] == "error" and "перезапуск" in st["error"]
    st2 = json.loads((tmp_path / done / "status.json").read_text(encoding="utf-8"))
    assert st2["status"] == "done"
