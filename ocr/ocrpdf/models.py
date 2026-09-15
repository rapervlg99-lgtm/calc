# -*- coding: utf-8 -*-
"""Модель данных PoC.

Ключевое решение: единица истины — *ячейка* (`Cell`), а не строка.
Строки/колонки — это производные представления. Так merged cells, координаты
и confidence сохраняются без потерь, а «плоский» DataFrame получается проекцией.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

BBox = tuple[float, float, float, float]   # (x0, y0, x1, y1) в PDF-точках, origin top-left


@dataclass
class Glyph:
    """Один распознанный символ — самый нижний уровень трассируемости."""
    char: str
    bbox: BBox
    confidence: float
    alternatives: list[tuple[str, float]] = field(default_factory=list)


@dataclass
class Cell:
    row: int                  # индекс логической строки (верхняя строка merged-области)
    col: int                  # индекс логической колонки (левая колонка merged-области)
    row_span: int = 1
    col_span: int = 1
    text: str = ""
    normalized_value: Optional[Any] = None      # float | str | None
    value_kind: str = "empty"                   # empty|number|text|code|int
    bbox: BBox = (0.0, 0.0, 0.0, 0.0)
    page: int = 1
    confidence: float = 1.0
    source: str = "none"                        # text_layer|vector_glyph|ocr|none
    requires_review: bool = False
    glyphs: list[Glyph] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # чтение ДРУГИМ движком гибридного OCR (RapidOCR ↔ Tesseract) той же
    # ячейки — нормализатор сверяется с ним, когда основной вариант двусмыслен
    alt_text: str = ""
    # Равновероятные прочтения, между которыми конвейер выбрать не может
    # («2011» → 20Б1 / 20Ш1 / 20К1): наружу они уходят списком, чтобы
    # интерфейс предложил выбор, а не оставил тихий флаг «проверить».
    candidates: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        # пустая ячейка != 0: отсутствие значения кодируется None, а не нулём
        return self.text.strip() == ""


@dataclass
class RowCheck:
    row: int
    kind: str                 # row_sum|group_total|grand_total
    expected: Optional[float]
    calculated: Optional[float]
    delta: Optional[float]
    tolerance: float
    status: str               # ok|failed|skipped
    column: str = ""          # роль/имя колонки, по которой шла проверка
    reason: str = ""
    terms: list[float] = field(default_factory=list)


@dataclass
class Table:
    index: int
    title: str
    kind: str                 # spec_main | mass_by_grade | generic | unreadable
    part: str = ""            # начало | окончание | продолжение (для спецификаций)
    page: int = 1
    bbox: BBox = (0.0, 0.0, 0.0, 0.0)
    n_rows: int = 0
    n_cols: int = 0
    columns: list[dict] = field(default_factory=list)   # {index, letter, role, title, bbox}
    cells: list[Cell] = field(default_factory=list)
    header_rows: list[int] = field(default_factory=list)
    checks: list[RowCheck] = field(default_factory=list)
    continues_table: Optional[int] = None               # индекс таблицы-начала
    notes: list[str] = field(default_factory=list)

    def grid(self) -> dict[tuple[int, int], Cell]:
        return {(c.row, c.col): c for c in self.cells}


@dataclass
class PageInfo:
    number: int
    width: float
    height: float
    content_kind: str          # vector | raster | mixed
    text_layer: str            # ok | broken_encoding | absent | partial
    n_ruling_lines: int = 0
    n_vector_glyphs: int = 0
    n_text_chars: int = 0
    notes: list[str] = field(default_factory=list)


def to_jsonable(obj):
    """dataclass -> dict с округлением координат (в JSON не нужны 15 знаков)."""
    def fix(o):
        if isinstance(o, float):
            return round(o, 3)
        if isinstance(o, dict):
            return {k: fix(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [fix(v) for v in o]
        return o
    return fix(asdict(obj) if hasattr(obj, "__dataclass_fields__") else obj)
