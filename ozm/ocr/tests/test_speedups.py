# -*- coding: utf-8 -*-
"""Дешёвые оптимизации конвейера: результат обязан совпадать со старым до бита.

Что ускорено (2026-09-11):
  * кэш шаблонов глифов ограничен объёмом, а не числом записей, и дублируется
    на диск (`_TemplateCache`);
  * сравнение масок `_match_score` считает все сдвиги одной операцией numpy;
  * координаты чертежа переводятся в систему страницы массивом
    (`map_drawing_arrays`), а не по точке через `fitz.Point`;
  * сбор примитивов контуров (`_collect_primitives`) и линовки
    (`extract_rulings`) — два прохода вместо вызова PyMuPDF на каждую точку.

Каждый тест сравнивает новый код с прямой (прежней) реализацией, скопированной
сюда как эталон, на случайных данных и на синтетических страницах с /Rotate.
"""
from __future__ import annotations

import numpy as np
import pytest

from ocrpdf import glyph_ocr, vector_grid
from ocrpdf.glyph_ocr import (CHARSET_PROBE, CHARSET_TEXT, _bezier_samples, _collect_primitives,
                              _match_score, _render_templates, _templates, _TemplateCache,
                              available_fonts, dilate1)
from ocrpdf.pdfbackend import fitz, map_drawing_arrays, map_drawing_xy, page_drawings


# --------------------------------------------------------------------------- #
#  эталоны: прежние реализации
# --------------------------------------------------------------------------- #
def _and_count_ref(x, y, dy, dx):
    y0, x0 = max(0, dy), max(0, dx)
    y1 = min(x.shape[0], y.shape[0] + dy)
    x1 = min(x.shape[1], y.shape[1] + dx)
    if y1 <= y0 or x1 <= x0:
        return 0
    return int(np.count_nonzero(x[y0:y1, x0:x1] & y[y0 - dy:y1 - dy, x0 - dx:x1 - dx]))


def _match_score_ref(a, b, ad=None, bd=None, max_shift=1):
    na = int(a.sum())
    nb = int(b.sum())
    if na == 0 or nb == 0:
        return 0.0
    if ad is None:
        ad = dilate1(a)
    if bd is None:
        bd = dilate1(b)
    ab, bb = a.astype(bool), b.astype(bool)
    best = 0.0
    for dy in range(-max_shift, max_shift + 1):
        for dx in range(-max_shift, max_shift + 1):
            c1 = _and_count_ref(ab, bd, dy - 1, dx - 1) / na
            if c1 <= best:
                continue
            c2 = _and_count_ref(ad, bb, dy + 1, dx + 1) / nb
            v = c1 if c1 < c2 else c2
            if v > best:
                best = v
    return best


def _collect_primitives_ref(page, eps=0.05, glyph_max=12.0):
    pts, keys = [], []
    q = 1.0 / eps

    def k(x, y):
        return (int(round(x * q)), int(round(y * q)))

    for d in page_drawings(page):
        pen = float(d.get("width") or 0.0)
        pad = pen / 2.0 if (d.get("fill") is None and pen > 0) else 0.0
        for it in d["items"]:
            if it[0] == "l":
                x1, y1 = map_drawing_xy(page, it[1].x, it[1].y)
                x2, y2 = map_drawing_xy(page, it[2].x, it[2].y)
                dx, dy = abs(x2 - x1), abs(y2 - y1)
                if (dy <= 0.2 and dx >= 15) or (dx <= 0.2 and dy >= 15):
                    continue
                pts.append((min(x1, x2) - pad, min(y1, y2) - pad, max(x1, x2) + pad, max(y1, y2) + pad))
                keys.append((k(x1, y1), k(x2, y2)))
            elif it[0] == "c":
                p0, p1, p2, p3 = it[1], it[2], it[3], it[4]
                xs_c, ys_c = [], []
                for i8 in range(9):
                    t = i8 / 8.0
                    u = 1.0 - t
                    w0, w1, w2, w3 = u*u*u, 3*u*u*t, 3*u*t*t, t*t*t
                    cx = w0*p0.x + w1*p1.x + w2*p2.x + w3*p3.x
                    cy = w0*p0.y + w1*p1.y + w2*p2.y + w3*p3.y
                    px, py = map_drawing_xy(page, cx, cy)
                    xs_c.append(px)
                    ys_c.append(py)
                pts.append((min(xs_c) - pad, min(ys_c) - pad, max(xs_c) + pad, max(ys_c) + pad))
                e0x, e0y = map_drawing_xy(page, p0.x, p0.y)
                e3x, e3y = map_drawing_xy(page, p3.x, p3.y)
                keys.append((k(e0x, e0y), k(e3x, e3y)))
            elif it[0] in ("re", "qu"):
                raw = fitz.Rect(it[1]) if it[0] == "re" else fitz.Quad(it[1]).rect
                ax, ay = map_drawing_xy(page, raw.x0, raw.y0)
                bx, by = map_drawing_xy(page, raw.x1, raw.y1)
                r = fitz.Rect(min(ax, bx), min(ay, by), max(ax, bx), max(ay, by))
                if max(r.width, r.height) <= glyph_max:
                    pts.append((r.x0, r.y0, r.x1, r.y1))
                    keys.append(())
    return pts, keys


def _extract_rulings_ref(page, min_len=8.0, tol=0.6, max_thickness=3.5):
    raw_h, raw_v = [], []
    R = vector_grid.Ruling

    def add(kind, const, a, b, w):
        if b - a >= min_len:
            (raw_h if kind == "h" else raw_v).append(R(const, a, b, w))

    for d in page_drawings(page):
        w = float(d.get("width") or 0.0)
        for it in d["items"]:
            if it[0] == "l":
                x1, y1 = map_drawing_xy(page, it[1].x, it[1].y)
                x2, y2 = map_drawing_xy(page, it[2].x, it[2].y)
                dx, dy = abs(x2 - x1), abs(y2 - y1)
                if dy <= 0.2 and dx > dy:
                    add("h", (y1 + y2) / 2, min(x1, x2), max(x1, x2), w)
                elif dx <= 0.2 and dy > dx:
                    add("v", (x1 + x2) / 2, min(y1, y2), max(y1, y2), w)
            elif it[0] in ("re", "qu"):
                raw = fitz.Rect(it[1]) if it[0] == "re" else fitz.Quad(it[1]).rect
                ax, ay = map_drawing_xy(page, raw.x0, raw.y0)
                bx, by = map_drawing_xy(page, raw.x1, raw.y1)
                r = fitz.Rect(min(ax, bx), min(ay, by), max(ax, bx), max(ay, by))
                if r.height <= max_thickness and r.width > r.height:
                    add("h", (r.y0 + r.y1) / 2, r.x0, r.x1, r.height)
                elif r.width <= max_thickness and r.height > r.width:
                    add("v", (r.x0 + r.x1) / 2, r.y0, r.y1, r.width)
                elif r.width > max_thickness and r.height > max_thickness:
                    if d.get("fill") is None:
                        add("h", r.y0, r.x0, r.x1, w); add("h", r.y1, r.x0, r.x1, w)
                        add("v", r.x0, r.y0, r.y1, w); add("v", r.x1, r.y0, r.y1, w)
    return vector_grid._merge_collinear(raw_h, tol), vector_grid._merge_collinear(raw_v, tol)


# --------------------------------------------------------------------------- #
#  сравнение масок
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("seed", range(4))
def test_match_score_bit_exact_on_random_masks(seed):
    rng = np.random.default_rng(seed)
    for _ in range(250):
        h, w = (int(v) for v in rng.integers(1, 36, 2))
        h2 = max(1, h + int(rng.integers(-6, 7)))
        w2 = max(1, w + int(rng.integers(-6, 7)))
        a = rng.random((h, w)) < rng.uniform(0.05, 0.9)
        b = rng.random((h2, w2)) < rng.uniform(0.05, 0.9)
        for ms in (0, 1, 2):
            assert _match_score(a, b, max_shift=ms) == _match_score_ref(a, b, max_shift=ms)
        ad, bd = dilate1(a), dilate1(b)
        assert _match_score(a, b, ad, bd) == _match_score_ref(a, b, ad, bd)
    z = np.zeros((3, 3), bool)
    assert _match_score(z, a) == 0.0 == _match_score_ref(z, a)
    assert _match_score(a, z) == 0.0


def test_match_score_bit_exact_on_real_templates():
    font = available_fonts()[0]
    tpl = _render_templates(font, 40, CHARSET_PROBE)
    for t in tpl:
        for u in tpl[:14]:
            assert _match_score(t.bm, u.bm, t.bmd, u.bmd) == _match_score_ref(t.bm, u.bm, t.bmd, u.bmd)
            assert _match_score(t.bm, u.bm) == _match_score_ref(t.bm, u.bm)


# --------------------------------------------------------------------------- #
#  кэш шаблонов
# --------------------------------------------------------------------------- #
def _same_templates(x, y):
    assert len(x) == len(y)
    for p, r in zip(x, y):
        assert (p.ch, p.h, p.w, p.bot, p.adv, p.lsb) == (r.ch, r.h, r.w, r.bot, r.adv, r.lsb)
        assert p.bm.dtype == r.bm.dtype == bool
        assert np.array_equal(p.bm, r.bm) and np.array_equal(p.bmd, r.bmd)


def test_template_cache_evicts_oldest_by_bytes():
    font = available_fonts()[0]
    t1 = _render_templates(font, 20, "12")
    t2 = _render_templates(font, 21, "12")
    tiny = (sum(t.bm.nbytes + t.bmd.nbytes for t in t1) + 2000) / (1024 * 1024)
    cache = _TemplateCache(limit_mb=tiny, disk_dir=None, disk_mb=1)
    cache.put(("a",), t1)
    cache.put(("b",), t2)
    assert cache.get(("a",)) is None            # вытеснен самый старый
    assert cache.get(("b",)) is t2              # хотя бы одна запись живёт всегда
    assert cache.info()["entries"] == 1
    big = _TemplateCache(limit_mb=64, disk_dir=None, disk_mb=1)
    for i in range(50):
        big.put((i,), t1)
    assert big.info()["entries"] == 50          # прежний lru_cache(160) сюда бы не влез при большом кегле


def test_template_cache_disk_roundtrip_is_exact(tmp_path):
    cache = _TemplateCache(64, str(tmp_path), 64)
    font = available_fonts()[0]
    tpl = _render_templates(font, 47, CHARSET_TEXT)
    cache.save_disk(font, 47, CHARSET_TEXT, tpl)
    files = list(tmp_path.glob("*.tpl"))
    assert len(files) == 1
    back = cache.load_disk(font, 47, CHARSET_TEXT)
    assert back is not None
    _same_templates(tpl, back)
    assert all(t.bm.base is None for t in back)        # самостоятельные массивы
    assert cache.load_disk(font, 48, CHARSET_TEXT) is None      # другой кегль — другой ключ
    assert cache.load_disk(font, 47, CHARSET_PROBE) is None     # другой алфавит — другой ключ
    files[0].write_bytes(b"garbage")                            # битый файл: молча удалить
    assert cache.load_disk(font, 47, CHARSET_TEXT) is None
    assert not files[0].exists()


def test_templates_go_memory_then_disk_then_render(monkeypatch, tmp_path):
    cache = _TemplateCache(64, str(tmp_path), 64)
    monkeypatch.setattr(glyph_ocr, "_TEMPLATE_CACHE", cache)
    font = available_fonts()[0]
    a = _templates(font, 33, CHARSET_PROBE)
    assert _templates(font, 33, CHARSET_PROBE) is a              # из памяти
    assert cache.info()["hits"] == 1
    cache.clear()
    b = _templates(font, 33, CHARSET_PROBE)                      # с диска
    assert cache.info()["disk_hits"] == 1
    _same_templates(a, b)
    _same_templates(b, _render_templates(font, 33, CHARSET_PROBE))


def test_templates_without_disk_dir(monkeypatch, tmp_path):
    cache = _TemplateCache(64, "", 64)
    monkeypatch.setattr(glyph_ocr, "_TEMPLATE_CACHE", cache)
    font = available_fonts()[0]
    _same_templates(_templates(font, 30, "12"), _render_templates(font, 30, "12"))
    assert not list(tmp_path.iterdir())


def test_disk_trim_keeps_folder_under_limit(tmp_path):
    font = available_fonts()[0]
    cache = _TemplateCache(64, str(tmp_path), 64)
    for size in (30, 31, 32, 33):
        cache.save_disk(font, size, CHARSET_PROBE, _render_templates(font, size, CHARSET_PROBE))
    sizes = [p.stat().st_size for p in tmp_path.glob("*.tpl")]
    assert len(sizes) == 4
    cache.disk_limit = int(sum(sizes) * 0.6)
    cache._trim_disk()
    left = [p.stat().st_size for p in tmp_path.glob("*.tpl")]
    assert 0 < len(left) < 4 and sum(left) <= cache.disk_limit


# --------------------------------------------------------------------------- #
#  координаты чертежа
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("rot", [0, 90, 180, 270])
def test_map_drawing_arrays_matches_pointwise(rot):
    doc = fitz.open()
    page = doc.new_page(width=841.89, height=595.28)
    page.set_rotation(rot)
    rng = np.random.default_rng(rot + 1)
    xs = np.concatenate([rng.uniform(-50, 900, 3000), rng.integers(0, 900, 500).astype(float),
                         [0.0, -0.0, 841.89, 595.28, 0.1, 1e-3, 123456.789]])
    ys = np.concatenate([rng.uniform(-50, 650, 3000), rng.integers(0, 650, 500).astype(float),
                         [0.0, 595.28, -0.0, 841.89, 0.1, 1e-3, -98765.4321]])
    ox, oy = map_drawing_arrays(page, xs, ys)
    assert ox.dtype == oy.dtype == np.float64 and ox.shape == xs.shape
    ref = [map_drawing_xy(page, float(x), float(y)) for x, y in zip(xs, ys)]
    assert [(x, y) for x, y in zip(ox.tolist(), oy.tolist())] == ref
    ox2, oy2 = map_drawing_arrays(page, list(xs[:10]), list(ys[:10]))
    assert np.array_equal(ox2, ox[:10]) and np.array_equal(oy2, oy[:10])
    e = map_drawing_arrays(page, [], [])
    assert e[0].shape == (0,)


def test_bezier_samples_match_scalar_loop():
    rng = np.random.default_rng(7)
    ctrl = rng.uniform(-100, 1000, (300, 8))
    xs, ys = _bezier_samples(ctrl)
    for row, (rx, ry) in zip(ctrl, zip(xs.tolist(), ys.tolist())):
        p = [(row[0], row[1]), (row[2], row[3]), (row[4], row[5]), (row[6], row[7])]
        for i8 in range(9):
            t = i8 / 8.0
            u = 1.0 - t
            w0, w1, w2, w3 = u*u*u, 3*u*u*t, 3*u*t*t, t*t*t
            assert rx[i8] == w0*p[0][0] + w1*p[1][0] + w2*p[2][0] + w3*p[3][0]
            assert ry[i8] == w0*p[0][1] + w1*p[1][1] + w2*p[2][1] + w3*p[3][1]


def _synthetic_page(rot: int, seed: int):
    """Страница с линовкой, штрихами, кривыми и точками-прямоугольниками."""
    doc = fitz.open()
    page = doc.new_page(width=841.89, height=595.28)
    rng = np.random.default_rng(seed)
    sh = page.new_shape()
    # линовка: длинные осевые линии и тонкие залитые прямоугольники
    for i in range(6):
        y = 60 + 40 * i
        sh.draw_line((40, y), (700, y))
    for i in range(8):
        x = 40 + 90 * i
        sh.draw_line((x, 60), (x, 260))
    sh.finish(width=0.6, color=(0, 0, 0))
    for i in range(5):
        sh.draw_rect(fitz.Rect(300, 300 + 12 * i, 700, 300.9 + 12 * i))
    sh.finish(fill=(0, 0, 0), color=None)
    # «взорванные» глифы: короткие штрихи с общими концами, кривые, точки
    for _ in range(120):
        x, y = rng.uniform(50, 650), rng.uniform(300, 560)
        h = rng.uniform(2, 7)
        sh.draw_line((x, y), (x, y - h))
        sh.draw_line((x, y - h), (x + h * 0.6, y - h))
        sh.draw_line((x + h * 0.6, y - h), (x + h * 0.6, y))
    sh.finish(width=0.35, color=(0, 0, 0))
    for _ in range(60):
        x, y = rng.uniform(50, 650), rng.uniform(300, 560)
        r = rng.uniform(1, 4)
        sh.draw_bezier((x, y), (x + r, y - r * 1.3), (x + 2 * r, y - r * 1.3), (x + 3 * r, y))
    sh.finish(width=0.0, color=(0, 0, 0))
    for _ in range(40):
        x, y = rng.uniform(50, 650), rng.uniform(300, 560)
        sh.draw_rect(fitz.Rect(x, y, x + rng.uniform(0.3, 1.2), y + rng.uniform(0.3, 1.2)))
    sh.finish(fill=(0, 0, 0), color=None)
    # рамка без заливки и залитый крупный прямоугольник (не глиф)
    sh.draw_rect(fitz.Rect(20, 20, 820, 575))
    sh.finish(width=1.0, color=(0, 0, 0))
    sh.draw_rect(fitz.Rect(720, 60, 800, 200))
    sh.finish(fill=(0.5, 0.5, 0.5), color=None)
    sh.commit()
    page.set_rotation(rot)
    return doc, page


@pytest.mark.parametrize("rot", [0, 90, 270])
def test_collect_primitives_matches_reference(rot):
    doc, page = _synthetic_page(rot, seed=rot + 3)
    assert len(page_drawings(page)) > 0
    pts, keys = _collect_primitives(page)
    pts_ref, keys_ref = _collect_primitives_ref(page)
    assert len(pts) == len(pts_ref) > 200
    assert pts == pts_ref
    assert keys == keys_ref
    assert all(isinstance(v, float) for p in pts for v in p)


@pytest.mark.parametrize("rot", [0, 90, 270])
def test_extract_rulings_matches_reference(rot):
    doc, page = _synthetic_page(rot, seed=rot + 11)
    h, v = vector_grid.extract_rulings(page)
    h_ref, v_ref = _extract_rulings_ref(page)
    assert h == h_ref and v == v_ref
    assert len(h) >= 6 and len(v) >= 8
