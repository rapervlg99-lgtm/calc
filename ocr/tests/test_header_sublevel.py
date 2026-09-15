# -*- coding: utf-8 -*-
"""Двухуровневая шапка без строки номеров и кандидаты марки двутавра (file-13).

На листе file-13 названия элементов конструкций стоят строкой ниже
объединённой ячейки «Масса металла по элементам конструкции», а служебной
строки номеров колонок нет. Раньше шапкой была только строка 0, элементы
уходили в данные, массы получали колонки «col4»…«col8». Второе: «I20Ш1»
прочитано как «2011» — вместо тихого флага конвейер отдаёт варианты.
"""
from __future__ import annotations

from ocrpdf.models import Cell
from ocrpdf.normalizer import fix_profile_series
from ocrpdf.structure import LogicalRow, detect_header_rows, refine_structure
from ocrpdf.vector_grid import TableBlock

HEADERS = [
    # (row, col, text, row_span, col_span)
    (0, 0, "Наименование профиля, ГОСТ", 2, 1),
    (0, 1, "Наименование или марка металла, ГОСТ", 2, 1),
    (0, 2, "Номер или размеры профиля, мм", 2, 1),
    (0, 3, "Поз.", 2, 1),
    (0, 4, "Масса металла по\nэлементам конструкции, т", 1, 5),
    (0, 9, "Общая\nмасса,\nт", 2, 1),
]
SUB = ["Колонны", "Балки", "Связи\nвертикальные", "Связи\nгоризонтальные", "Прогоны"]
DATA = ["Двутавры стальные", "С345-6", "I30K1", "1", "8,92", "10,12", "", "", "", "19,04"]


def _probe(with_data: bool = True) -> dict:
    """Как read_header: merged-ячейки только в якоре."""
    grid = {}
    for r, c, t, rs, cs in HEADERS:
        grid[(r, c)] = Cell(row=r, col=c, text=t, row_span=rs, col_span=cs, source="ocr")
    for i, t in enumerate(SUB):
        grid[(1, 4 + i)] = Cell(row=1, col=4 + i, text=t, source="ocr")
    if with_data:
        for c, t in enumerate(DATA):
            grid[(2, c)] = Cell(row=2, col=c, text=t, source="ocr")
    return grid


def _full() -> dict:
    """Как полная сетка: merged-ячейки скопированы в каждую накрытую клетку."""
    grid = {}
    for r, c, t, rs, cs in HEADERS:
        cell = Cell(row=r, col=c, text=t, row_span=rs, col_span=cs, source="ocr")
        for rr in range(r, r + rs):
            for cc in range(c, c + cs):
                grid[(rr, cc)] = cell
    for i, t in enumerate(SUB):
        grid[(1, 4 + i)] = Cell(row=1, col=4 + i, text=t, source="ocr")
    for c, t in enumerate(DATA):
        grid[(2, c)] = Cell(row=2, col=c, text=t, source="ocr")
    return grid


def test_sub_header_row_joins_header_in_probe_and_full_grid():
    assert detect_header_rows(_probe(), 16, 10) == ([0, 1], None)
    assert detect_header_rows(_full(), 16, 10) == ([0, 1], None)


def test_element_columns_get_names_from_sub_header():
    block = TableBlock((0, 0, 100, 60), list(range(0, 110, 10)), [0, 10, 20, 30, 40, 50], [], 5, 10)
    hdr, cols = refine_structure(_full(), 16, 10, block)
    assert hdr == [0, 1]
    assert [c.role for c in cols[4:9]] == ["element_mass"] * 5
    assert [c.element for c in cols[4:9]] == [
        "Колонны", "Балки", "Связи вертикальные", "Связи горизонтальные", "Прогоны"]
    assert cols[9].role == "total_mass"
    assert cols[0].role == "profile_group"


def test_data_row_with_numbers_is_not_absorbed():
    grid = _probe(with_data=False)
    # вторая строка — данные с номером позиции и массами
    for c, t in enumerate(DATA):
        grid[(1, c)] = Cell(row=1, col=c, text=t, source="ocr")
    for i in range(4, 9):
        grid.pop((1, i), None)
    grid[(1, 4)] = Cell(row=1, col=4, text="8,92", source="ocr")
    assert detect_header_rows(grid, 16, 10) == ([0], None)


def test_single_level_header_stays_single():
    grid = {}
    for c, t in enumerate(["Наименование", "Марка", "Размер", "Поз.", "Масса, т"]):
        grid[(0, c)] = Cell(row=0, col=c, text=t, source="ocr")
    grid[(1, 0)] = Cell(row=1, col=0, text="Итого", source="ocr")   # текст, но шапка сверху не накрывает
    assert detect_header_rows(grid, 8, 5) == ([0], None)


def test_header_never_eats_all_rows():
    grid = {}
    grid[(0, 0)] = Cell(row=0, col=0, text="Шапка", row_span=3, source="ocr")
    for r in range(1, 3):
        grid[(r, 1)] = Cell(row=r, col=1, text="подпись %d" % r, source="ocr")
    assert detect_header_rows(grid, 3, 2) == ([0, 1], None)


def _cell(text: str, alt: str = "") -> Cell:
    return Cell(row=1, col=2, text=text, source="ocr", alt_text=alt)


def test_ibeam_candidates_when_series_letter_is_lost():
    beams = Cell(row=1, col=0, text="Двутавры стальные горячекатаные ГОСТ 26020-83", source="ocr")
    rows = [
        LogicalRow(1, "data", 1, {"profile_group": beams, "profile_size": _cell("2011")}),
        LogicalRow(2, "data", 2, {"profile_group": beams, "profile_size": _cell("301")}),
        LogicalRow(3, "data", 3, {"profile_group": beams, "profile_size": _cell("2011", alt="I20W1")}),
        LogicalRow(4, "data", 4, {"profile_group": beams, "profile_size": _cell("30К1")}),
    ]
    fix_profile_series(rows)
    a, b, c, d = (r.cells["profile_size"] for r in rows)
    assert a.text == "2011" and a.candidates == ["20Б1", "20Ш1", "20К1"] and a.requires_review
    assert b.text == "301" and b.candidates == ["30Б1", "30Ш1", "30К1"] and b.requires_review
    assert c.text == "20Ш1" and c.candidates == []        # второй движок видел букву
    assert d.text == "30К1" and d.candidates == []
