# -*- coding: utf-8 -*-
"""Резервная детекция линовки по РАСТРУ (для сканированных листов).

Используется только если на странице нет векторной линовки (`vector_grid`
вернул пусто). Алгоритм классический и намеренно простой:
  бинаризация (адаптивная) -> морфология длинным горизонтальным/вертикальным
  ядром -> проекции -> кластеры позиций линий.

Отдаёт те же `Ruling`, поэтому дальше конвейер не различает источник геометрии.
"""
from __future__ import annotations

import cv2
import numpy as np

from .pdfbackend import fitz
from .vector_grid import Ruling, TableBlock, find_table_blocks


def rulings_from_raster(page: fitz.Page, dpi: int = 200, min_len_pt: float = 20.0,
                        clip: fitz.Rect | None = None
                        ) -> tuple[list[Ruling], list[Ruling]]:
    """Линовка по растру. `clip` ограничивает область (например, вставленной
    картинкой), координаты всё равно возвращаются в системе страницы."""
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, clip=clip)
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
    z = dpi / 72.0
    off_x = clip.x0 if clip is not None else 0.0
    off_y = clip.y0 if clip is not None else 0.0
    bw = cv2.adaptiveThreshold(img, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                               cv2.THRESH_BINARY_INV, 25, 10)
    min_len_px = max(8, int(min_len_pt * z))

    def extract(kernel_shape, horizontal: bool) -> list[Ruling]:
        k = cv2.getStructuringElement(cv2.MORPH_RECT, kernel_shape)
        mor = cv2.morphologyEx(bw, cv2.MORPH_OPEN, k, iterations=1)
        n, _, stats, _ = cv2.connectedComponentsWithStats(mor, connectivity=8)
        out: list[Ruling] = []
        for x, y, w, h, area in stats[1:]:
            if horizontal and w >= min_len_px and h <= max(3, int(0.05 * w)):
                out.append(Ruling(off_y + (y + h / 2) / z, off_x + x / z,
                                  off_x + (x + w) / z, h / z))
            elif not horizontal and h >= min_len_px and w <= max(3, int(0.05 * h)):
                out.append(Ruling(off_x + (x + w / 2) / z, off_y + y / z,
                                  off_y + (y + h) / z, w / z))
        return out

    h = extract((min_len_px, 1), True)
    v = extract((1, min_len_px), False)
    return h, v


def blocks_from_raster(page: fitz.Page, dpi: int = 200,
                       clip: fitz.Rect | None = None) -> list[TableBlock]:
    h, v = rulings_from_raster(page, dpi=dpi, clip=clip)
    return find_table_blocks(h, v, page_rect=page.rect)


def large_image_rects(page: fitz.Page, min_area_ratio: float = 0.05
                      ) -> list[fitz.Rect]:
    """Прямоугольники крупных вставленных картинок.

    В них может лежать целая таблица: у листа «Спецификация металла образец»
    вся спецификация — одна картинка 3184 x 4322 px, а векторами нарисованы
    только рамка листа и штамп.
    """
    page_area = abs(page.rect.get_area()) or 1.0
    out: list[fitz.Rect] = []
    for info in page.get_image_info():
        r = fitz.Rect(info["bbox"]) & page.rect
        if abs(r.get_area()) >= min_area_ratio * page_area:
            out.append(r)
    return out
