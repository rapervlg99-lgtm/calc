# -*- coding: utf-8 -*-
"""Единая точка импорта PyMuPDF.

Начиная с PyMuPDF 1.24.3 канонический модуль называется `pymupdf`, а старое имя
`fitz` печатает предупреждение об устаревании при каждом запуске. Импорт собран
здесь, чтобы работать и на новых, и на старых версиях без правок в остальных
модулях.
"""
from __future__ import annotations

import numpy as np

try:
    import pymupdf as fitz            # PyMuPDF >= 1.24.3
except ModuleNotFoundError:           # pragma: no cover
    import fitz                       # старые версии

__all__ = ["fitz", "map_drawing_xy", "map_drawing_arrays", "page_drawings"]


def page_drawings(page: fitz.Page) -> list:
    """`get_drawings()` с кэшем на страницу: линовка и глифы ходят по одним векторам."""
    cached = getattr(page, "_ocrpdf_drawings", None)
    if cached is None:
        cached = page.get_drawings()
        page._ocrpdf_drawings = cached
    return cached


def map_drawing_xy(page: fitz.Page, x: float, y: float) -> tuple[float, float]:
    """Точка из `get_drawings()` -> система `page.rect` / `get_text` / pixmap.

    PyMuPDF на время разбора векторов обнуляет `/Rotate`, поэтому линовка и
    «взорванный» текст приходят в координатах mediabox. Текст, растр и
    `page.rect` живут уже в повёрнутой системе. Без перевода сетка
    транспонируется: спецификация ~40×12 становится 12×42, а кропы ячеек
    берутся не с тех мест.
    """
    if not getattr(page, "rotation", 0):
        return float(x), float(y)
    p = fitz.Point(float(x), float(y)) * page.rotation_matrix
    return p.x, p.y


def map_drawing_arrays(page: fitz.Page, xs, ys) -> tuple[np.ndarray, np.ndarray]:
    """То же, что `map_drawing_xy`, но сразу для массивов точек — одной операцией.

    `fitz.Point * Matrix` считается в MuPDF на float32:
        x' = x·a + y·c + e,   y' = x·b + y·d + f.
    Здесь та же формула повторяется в float32 средствами numpy, поэтому числа
    совпадают с поточечным переводом до бита (у /Rotate 90/180/270 матрица
    состоит из 0, ±1 и размеров страницы, и каждая координата округляется
    ровно один раз, как и в C). Раньше ~90 тысяч точек листа переводились по
    одной через `fitz.Point` — 5–7 с на каждом векторном листе.
    """
    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)
    if not getattr(page, "rotation", 0):
        return xs, ys
    m = page.rotation_matrix
    a, b, c, d, e, f = (np.float32(v) for v in (m.a, m.b, m.c, m.d, m.e, m.f))
    x32 = xs.astype(np.float32)
    y32 = ys.astype(np.float32)
    ox = (x32 * a + y32 * c) + e
    oy = (x32 * b + y32 * d) + f
    return ox.astype(np.float64), oy.astype(np.float64)
