# -*- coding: utf-8 -*-
"""Модульные тесты, не требующие PDF."""
import json
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ocrpdf.cell_reader import (TextLine, _overlap_frac, _resolve_engine, _worth_rotation,
                                should_try_rotation)
from ocrpdf.glyph_ocr import (_hollow_rect_score, _match_score, baseline_px, group_lines,
                              merge_counters, merge_diacritics)
from ocrpdf.models import Cell, RowCheck, Table
from ocrpdf.normalizer import (_fix_digit_context, canonical_size, extract_standards,
                               normalize_cell, parse_number, row_marker, strip_standards)
from ocrpdf.structure import (Column, LogicalRow, _dehyphenate, canonical_header,
                              canonical_profile_group, classify_table,
                              detect_header_rows, refine_structure, skeleton)
from ocrpdf.pdfbackend import fitz
from ocrpdf.validator import (Tolerance, check_grand_total, check_group_totals,
                              check_row_sums, summarize)
from ocrpdf.pipeline import Options, parse_pages, run
from ocrpdf.vector_grid import (Ruling, TableBlock, _build_grid, _merge_collinear,
                                _regularize_pitch, extract_rulings, find_table_blocks,
                                is_drawing_grid, looks_stamp_block)
from ocrpdf.webapp import _build_envelope, app_path, normalize_base_path
from ocrpdf.exporter import write_xlsx, xlsx_safe


# --------------------------------------------------------------------------- #
#  веб: префикс /ocr
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,expected", [
    ("", ""), ("/", ""), ("ocr", "/ocr"), ("/ocr", "/ocr"), ("/ocr/", "/ocr"),
])
def test_normalize_base_path(raw, expected):
    assert normalize_base_path(raw) == expected


def test_app_path_with_prefix():
    assert app_path("/ocr", "/ocr") == ""
    assert app_path("/ocr/", "/ocr") == "/"
    assert app_path("/ocr/api/extract", "/ocr") == "/api/extract"
    assert app_path("/ocr/healthz", "/ocr") == "/healthz"
    assert app_path("/", "/ocr") == ""
    assert app_path("/calculators", "/ocr") is None


def test_app_path_without_prefix():
    assert app_path("/", "") == "/"
    assert app_path("/api/extract", "") == "/api/extract"
    assert app_path("/healthz", "") == "/healthz"


# --------------------------------------------------------------------------- #
#  нормализация
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text,expected", [
    ("29,34", 29.34), ("13,04", 13.04), ("0,55", 0.55), ("4,0", 4.0),
    ("164,96", 164.96), ("-1,5", -1.5), ("7", 7.0), ("3.14", 3.14),
    ("", None), ("Итого", None), ("16П", None), ("29,?4", None), ("1 2", None),
])
def test_parse_number(text, expected):
    assert parse_number(text) == expected


def test_empty_cell_is_not_zero():
    """Пустая ячейка обязана отличаться от нуля."""
    cell = normalize_cell(Cell(row=0, col=5, text=""), "element_mass")
    assert cell.value_kind == "empty"
    assert cell.normalized_value is None

    zero = normalize_cell(Cell(row=0, col=5, text="0"), "element_mass")
    assert zero.value_kind == "number"
    assert zero.normalized_value == 0.0


def test_non_numeric_in_numeric_column_is_flagged():
    cell = normalize_cell(Cell(row=1, col=5, text="29,?4"), "element_mass")
    assert cell.normalized_value is None
    assert cell.requires_review is True


def test_ocr_space_instead_of_decimal_comma_is_recovered():
    """RapidOCR читает запятую как пробел; в числовой колонке ставим запятую.

    Цифры не угадываем: '23857 49' станет '23857,49' и уйдёт на проверку.
    '1 2' по-прежнему не число — слишком коротко, чтобы считать это запятой.
    """
    cell = normalize_cell(Cell(row=4, col=7, text="23857 49", source="ocr"),
                          "total_mass")
    assert cell.text == "23857,49"
    assert cell.normalized_value == 23857.49
    assert cell.requires_review is True
    assert any("запят" in n for n in cell.notes)

    glued = normalize_cell(Cell(row=1, col=5, text="1 2", source="ocr"),
                           "element_mass")
    assert glued.normalized_value is None
    assert glued.text == "1 2"

    layer = normalize_cell(Cell(row=4, col=7, text="23857 49", source="text_layer"),
                           "total_mass")
    assert layer.text == "23857 49"
    assert layer.normalized_value is None


@pytest.mark.parametrize("raw,fixed", [
    ("СЗ55-5", "С355-5"),            # 'З' рядом с цифрой -> '3'
    ("ГОСТ З0245-200З", "ГОСТ 30245-2003"),
    ("Сталь марки 6З", "Сталь марки 63"),
    ("8509-9З", "8509-93"),
    ("ГОСТ", "ГОСТ"),                # без цифр в токене — не трогаем
    ("16П", "16П"),                  # 'П' не двойник цифры
    ("35К1", "35К1"),
    ("t8", "t8"),
    ("В том числе", "В том числе"),   # 'В' без цифр рядом остаётся буквой
    ("Гн.□160х6", "Гн.□160х6"),
])
def test_digit_context_fix(raw, fixed):
    assert _fix_digit_context(raw)[0] == fixed


def test_digit_fix_is_logged_in_notes():
    cell = normalize_cell(Cell(row=1, col=1, text="СЗ45Б", source="vector_glyph"),
                          "steel_grade")
    assert cell.text == "С345Б"
    assert any("letter->digit" in n for n in cell.notes)


def test_digit_fix_never_touches_the_text_layer():
    """Текст из текстового слоя точен по построению — правка запрещена.

    Регрессия: на ведомости работ «Бетонирование фундаментов В25» превращалось
    в «825», то есть портился класс бетона.
    """
    cell = normalize_cell(
        Cell(row=1, col=1, text="Бетонирование фундаментов В25", source="text_layer"),
        "text")
    assert cell.text == "Бетонирование фундаментов В25"
    assert not any("letter->digit" in n for n in cell.notes)


def test_ocr_ruling_junk_stripped_from_profile_size():
    """Линовка, прочитанная как '|', не должна оставаться в обозначении."""
    cell = normalize_cell(Cell(row=1, col=2, text="|2651", source="ocr"), "profile_size")
    assert cell.text == "2651"
    # «|» перед номером двутавра — либо линовка, либо значок сечения; след в notes есть
    assert any("линовк" in n or "значок типа профиля" in n for n in cell.notes)
    assert cell.requires_review is True
    assert any("одних цифр" in n for n in cell.notes)


def test_channel_bracket_glyph_is_stripped():
    """'[' — схематический значок швеллера перед обозначением: снимается как и
    прочие значки сечения (□, Ι, L), в notes остаётся след."""
    cell = normalize_cell(Cell(row=1, col=2, text="[120х60х4", source="ocr"), "profile_size")
    assert cell.text == "120х60х4"
    assert any("значок типа профиля" in n for n in cell.notes)
    assert cell.requires_review is False


def test_ocr_homoglyphs_in_steel_grade_and_pipe_size():
    """RapidOCR пишет латиницу; это те же начертания, не угадывание."""
    grade = normalize_cell(Cell(row=1, col=1, text="C255", source="ocr"), "steel_grade")
    assert grade.text == "С255"
    size = normalize_cell(Cell(row=1, col=2, text="Tp 160x5", source="ocr"), "profile_size")
    assert size.normalized_value == "Тр 160х5"


def test_ocr_cleanup_never_touches_the_text_layer():
    cell = normalize_cell(Cell(row=1, col=2, text="|2651", source="text_layer"),
                          "profile_size")
    assert cell.text == "|2651"
    assert cell.requires_review is False


def test_letters_distinguishable_from_digits_are_not_replaced():
    """'В', 'Ч', 'Т', 'б' от цифр отличимы и в карту двойников не входят."""
    for raw in ("В25", "Ч7", "Т14", "б12"):
        assert _fix_digit_context(raw)[0] == raw


def test_header_numbering_tolerates_gaps():
    """Служебная строка «1 2 3 4  6» при 9 колонках всё ещё шапка.

    На листе КМ с /Rotate часть номеров пропадает, и порог «70% ячеек —
    цифры» не срабатывал: строка «6» в колонке масс уходила в суммы как 6 т.
    """
    grid = {}
    for c, t in enumerate(["1", "2", "3", "4", "", "6", "", "", ""]):
        grid[(2, c)] = Cell(row=2, col=c, text=t)
    hdr, num = detect_header_rows(grid, 10, 9)
    assert num == 2
    assert hdr == [0, 1, 2]


def test_header_on_span_filled_grid_keeps_numbering_row():
    """Merged-шапка занимает строки 0–1; номера колонок — строка 2.

    Так устроен file-4: без заполнения span probe не видел номера, шапкой
    оставалась только строка 0, и «Фахверк» попадал в массы.
    """
    grid = {}
    headers = [
        (0, 0, "Науменование профиля, ГОСТ, TY", 2, 1),
        (0, 1, "Наименование UNU марка металла ГОСТ, ТУ", 2, 1),
        (0, 2, "Номер uu размеры профиля, ММ", 2, 1),
        (0, 3, "Поз.", 2, 1),
        (0, 4, "Macca металла. по элементцм KOHCMPYKUUU, M", 1, 4),
        (0, 8, "Общая Macca, п", 2, 1),
    ]
    for r, c, t, rs, cs in headers:
        cell = Cell(row=r, col=c, text=t, row_span=rs, col_span=cs, source="ocr")
        for rr in range(r, r + rs):
            for cc in range(c, c + cs):
                grid[(rr, cc)] = cell
    grid[(1, 4)] = Cell(row=1, col=4, text="Фахверк", source="ocr")
    grid[(1, 5)] = Cell(row=1, col=5, text="Связи", source="ocr")
    for c, t in enumerate(["1", "2", "3", "4", "", "6", "", "", ""]):
        grid[(2, c)] = Cell(row=2, col=c, text=t, source="ocr")
    block = TableBlock((0, 0, 90, 40), list(range(0, 100, 10)), [0, 10, 20, 30],
                       [], 4, 9)
    hdr, cols = refine_structure(grid, 10, 9, block)
    assert hdr == [0, 1, 2]
    assert cols[0].role == "profile_group"
    assert cols[0].title == "Наименование профиля, ГОСТ, ТУ"
    assert cols[4].role == "element_mass"
    assert cols[4].element == "Фахверк"
    assert cols[5].element == "Связи"
    assert cols[8].role == "total_mass"


@pytest.mark.parametrize("raw,canon", [
    ("Науменование профиля, ГОСТ, TY", "Наименование профиля, ГОСТ, ТУ"),
    ("Наименование UNU марка металла ГОСТ, ТУ",
     "Наименование или марка металла, ГОСТ, ТУ"),
    ("Номер uu размеры профиля, ММ", "Номер или размеры профиля, мм"),
    ("Масса металла. по элементцм КОНСМРУКUUU, М",
     "Масса металла по элементам конструкций, т"),
    ("Общая Масса, п", "Общая масса, т"),
])
def test_canonical_header(raw, canon):
    got, ratio = canonical_header(raw)
    assert got == canon
    assert ratio >= 0.78


@pytest.mark.parametrize("raw,canon", [
    ("Мроdunu стцльные еНУМbIЕ замкнутые сбарные квадратные u "
     "NРАМОУZОNbНbIЕ бля строительных конструкции ГОСТ 30245-2003.",
     "Профили стальные гнутые замкнутые сварные квадратные и прямоугольные "
     "для строительных конструкций"),
    ("Двутабры стальные сОРАУеКАМАНbIЕ с NАРААNеNbНbIМU гранями полок.",
     "Двутавры стальные горячекатаные с параллельными гранями полок"),
    ("У20nku стальные горячекатаные нерабнополочные",
     "Уголки стальные горячекатаные неравнополочные"),
    ("У20nku стальные горячекатаные рабнополочные ОСТ 8509-93",
     "Уголки стальные горячекатаные равнополочные"),
    ("Прокат. nuсmоbоu горячекатаный", "Прокат листовой горячекатаный"),
])
def test_canonical_profile_group(raw, canon):
    got, ratio = canonical_profile_group(raw)
    assert got == canon
    assert ratio >= 0.68


def test_canonical_profile_group_skips_totals_and_short_noise():
    assert canonical_profile_group("Всего профиля:")[0] == ""
    assert canonical_profile_group("Итого")[0] == ""
    assert canonical_profile_group("Φaxbepk")[0] == ""
    assert canonical_profile_group("С255 ГОСТ 27772-2021")[0] == ""


def test_profile_group_canon_keeps_gost_and_drops_low_conf():
    cell = normalize_cell(
        Cell(row=3, col=0, text="У20nku стальные горячекатаные рабнополочные ОСТ 8509-93",
             source="ocr", requires_review=True),
        "profile_group")
    assert "Уголки стальные горячекатаные равнополочные" in cell.text
    assert "8509-93" in cell.text
    assert cell.requires_review is False
    assert any("каноническ" in n for n in cell.notes)


def test_classify_table():
    spec = [Column(3, "position", "№"), Column(4, "element_mass", "Фермы", element="Фермы"),
            Column(5, "total_mass", "Общая масса")]
    other = [Column(0, "position", "№ п/п"), Column(1, "unknown", "Наименование"),
             Column(2, "unknown", "Стоимость")]
    assert classify_table(spec) == "spec_main"
    assert classify_table(other) == "generic"


def test_total_mass_inferred_after_element_group():
    """OCR «масса, Ш» справа от «массы по элементам» — это общая масса.

    Без этой подстановки спецификация file-3 оставалась generic, и проверки
    масс не запускались.
    """
    grid = {}
    mass = Cell(row=0, col=4, text="Масса металла по элементам конструкций, т",
                col_span=4, source="ocr")
    for c in range(4, 8):
        grid[(0, c)] = mass
    grid[(0, 0)] = Cell(row=0, col=0, text="Наименование профиля, ГОСТ, ТУ", source="ocr")
    grid[(0, 1)] = Cell(row=0, col=1, text="Наименование или марка металла, ГОСТ, ТУ", source="ocr")
    grid[(0, 2)] = Cell(row=0, col=2, text="Номер или размеры", source="ocr")
    grid[(0, 3)] = Cell(row=0, col=3, text="№ п.п.", source="ocr")
    grid[(0, 8)] = Cell(row=0, col=8, text="масса, Ш", source="ocr")
    for c, t in enumerate("123456789"):
        grid[(1, c)] = Cell(row=1, col=c, text=t, source="ocr")
    block = TableBlock((0, 0, 90, 20), list(range(0, 100, 10)), [0, 10, 20], [], 3, 9)
    hdr, cols = refine_structure(grid, 5, 9, block)
    assert cols[2].role == "profile_size"
    assert cols[8].role == "total_mass"
    assert cols[8].title == "Общая масса, т"
    assert classify_table(cols) == "spec_main"


def test_canonical_size():
    assert canonical_size("Гн.□160x6") == "Гн.□160х6"
    assert canonical_size("L 100*7") == "L 100х7"
    assert canonical_size("100 × 7") == "100х7"


def test_position_with_two_numbers():
    """Merged-ячейка без разделительной линии содержит несколько позиций."""
    cell = normalize_cell(Cell(row=28, col=3, text="26\n27"), "position")
    assert cell.value_kind == "int_list"
    assert cell.normalized_value == [26, 27]


def test_standards_split():
    assert extract_standards("С355-5 ГОСТ 27772-2015") == ["ГОСТ 27772-2015"]
    assert strip_standards("С355-5 ГОСТ 27772-2015") == "С355-5"
    assert extract_standards("ГОСТ Р 53866-2010 Рельсы") == ["ГОСТ Р 53866-2010"]


@pytest.mark.parametrize("text,kind", [
    ("Итого", "group_total"),
    ("Всего профиля", "profile_total"),
    ("Масса металла", "grand_total"),
    ("В том числе по маркам или наименованиям", "section_header"),
    ("Гн.□160х6", None),
    # текст из растрового OCR: мусор слева и латинские двойники кириллицы
    ("|Итого:", "group_total"),
    ('"""Итого:"', "group_total"),
    ("Всего масса металла:", "grand_total"),
    ("|B том числе по маркам или наименованиям:", "section_header"),
    ("C255 ГОСТ 27772-2015", None),
])
def test_row_marker(text, kind):
    assert row_marker(text) == kind


def test_dehyphenate():
    assert _dehyphenate("Надколон- ник") == "Надколонник"
    assert _dehyphenate("Распорки по колоннам") == "Распорки по колоннам"
    assert _dehyphenate("огражде- ния") == "ограждения"


def test_skeleton():
    assert skeleton("Общая масса, т") == "общаямассат"
    # шапка с латинскими двойниками RapidOCR
    assert "массаметаллапоэлемент" in skeleton("Macca металла. по элементцм")
    assert "размерыпрофил" in skeleton("Номер uu размеры профиля, ММ")


# --------------------------------------------------------------------------- #
#  геометрия
# --------------------------------------------------------------------------- #
def test_merge_collinear():
    rl = _merge_collinear([Ruling(10.0, 0, 50), Ruling(10.1, 49, 100),
                           Ruling(30.0, 0, 20)], tol=0.6)
    assert len(rl) == 2
    long = [r for r in rl if abs(r.const - 10) < 1][0]
    assert (long.a, long.b) == (0, 100)


def test_regularize_pitch_inserts_missing_separator():
    """Пропущенная линия при кратном зазоре достраивается (случай поз. 26/27)."""
    ys = [0.0, 10.0, 20.0, 30.0, 50.0, 60.0, 70.0]      # зазор 20 == 2 шага
    out = _regularize_pitch(ys)
    assert 40.0 in out
    assert len(out) == len(ys) + 1


def test_regularize_pitch_keeps_irregular_grid():
    ys = [0.0, 7.0, 31.0, 44.0]
    assert _regularize_pitch(ys) == ys


def _grid_lines(xs, ys, skip_h=(), skip_v=()):
    h = [Ruling(y, xs[0], xs[-1]) for y in ys]
    v = []
    for x in xs:
        for j in range(len(ys) - 1):
            if (x, j) in skip_v:
                continue
            v.append(Ruling(x, ys[j], ys[j + 1]))
    h = [r for i, r in enumerate(h) if i not in skip_h]
    return h, _merge_collinear(v, 0.6)


def test_build_grid_joins_gapped_column_separator():
    """Вертикаль, разорванная на строках «Итого», всё равно колонка.

    Каждый кусок короче 0.3 высоты — по одному отрезку разделитель
    отбрасывался, и «наименование» слипалось с «маркой».
    """
    xs = [0.0, 40.0, 80.0, 120.0]
    ys = [0.0, 20.0, 40.0, 60.0, 80.0, 100.0]
    h = [Ruling(y, xs[0], xs[-1]) for y in ys]
    v = []
    for x in xs:
        if abs(x - 40.0) < 0.1:
            v.append(Ruling(x, 0.0, 20.0))
            v.append(Ruling(x, 40.0, 60.0))
            v.append(Ruling(x, 80.0, 100.0))
        else:
            v.append(Ruling(x, ys[0], ys[-1]))
    blk = _build_grid(h, v, (xs[0], ys[0], xs[-1], ys[-1]))
    assert blk.n_cols == 3
    assert any(abs(x - 40.0) < 1 for x in blk.xs)


def test_build_grid_detects_merged_cells():
    """Отсутствие разделителя = объединённая ячейка."""
    xs = [0.0, 30.0, 60.0, 90.0]
    ys = [0.0, 20.0, 40.0, 60.0]
    # убираем вертикаль x=30 на первой строке -> ячейки (0,0)+(0,1) слиты
    h, v = _grid_lines(xs, ys, skip_v={(30.0, 0)})
    blk = _build_grid(h, v, (xs[0], ys[0], xs[-1], ys[-1]))
    assert (blk.n_rows, blk.n_cols) == (3, 3)
    merged = [c for c in blk.cells if c.col_span > 1 or c.row_span > 1]
    assert len(merged) == 1
    assert (merged[0].row, merged[0].col, merged[0].col_span) == (0, 0, 2)


def test_frame_filter_keeps_separators_of_a_full_height_table():
    """Рамку отбираем по положению, а не по одной длине.

    На листе-скане «Техническая спецификация металла» таблица занимает почти
    всю высоту листа. Пока рамкой считалась любая длинная линия, вертикали
    таблицы уходили в мусор вместе с рамкой и из 10 колонок оставалось 6.
    """
    page = fitz.Rect(0, 0, 1191, 842)
    xs = [57.0, 165.0, 245.0, 325.0, 630.0]      # 57 — вдоль левого края листа
    ys = [50.0 + 52.0 * i for i in range(16)]    # высота 780 pt = 0.93 листа
    h = [Ruling(y, xs[0], xs[-1]) for y in ys]
    v = [Ruling(x, ys[0], ys[-1]) for x in xs]
    blocks = find_table_blocks(h, v, page_rect=page)
    assert len(blocks) == 1
    assert blocks[0].n_cols == 4
    assert 245.0 in [pytest.approx(x) for x in blocks[0].xs]


def test_frame_filter_still_drops_the_sheet_frame():
    """Рамка листа по-прежнему не участвует в группировке."""
    page = fitz.Rect(0, 0, 1191, 842)
    xs = [300.0, 400.0, 500.0]
    ys = [300.0 + 40.0 * i for i in range(5)]
    h = [Ruling(y, xs[0], xs[-1]) for y in ys]
    v = [Ruling(x, ys[0], ys[-1]) for x in xs]
    # рамка: 20 мм слева, 5 мм справа, пересекает линовку таблицы
    frame_v = [Ruling(56.7, 14.2, 827.8), Ruling(1176.8, 14.2, 827.8)]
    frame_h = [Ruling(14.2, 56.7, 1176.8), Ruling(827.8, 56.7, 1176.8)]
    blocks = find_table_blocks(h + frame_h, v + frame_v, page_rect=page)
    assert len(blocks) == 1
    assert blocks[0].bbox[0] == pytest.approx(300.0)
    assert blocks[0].bbox[2] == pytest.approx(500.0)


def _grid_block(n_rows, n_cols, row_pitch=22.0, col_pitch=50.0, col_gaps=None):
    ys = [10.0 + i * row_pitch for i in range(n_rows + 1)]
    if col_gaps is None:
        xs = [10.0 + i * col_pitch for i in range(n_cols + 1)]
    else:
        xs = [10.0]
        for g in col_gaps:
            xs.append(xs[-1] + g)
    return TableBlock((xs[0], ys[0], xs[-1], ys[-1]), xs, ys, [], n_rows, n_cols)


def test_drawing_grid_skips_dimension_mesh_keeps_spec():
    """Чертёж рядом со спекой: оси и размеры — не таблица металлопроката.

    На file-3 сетка 105×46 (шаг строк 4 pt) и полосы 3×28 / 4×16 — это
    чертёж. Спека 25×9 и широкий КМ1 83×17 должны остаться.
    """
    assert is_drawing_grid(_grid_block(105, 46, row_pitch=3.9)) is True
    assert is_drawing_grid(_grid_block(3, 28)) is True
    assert is_drawing_grid(_grid_block(4, 16)) is True
    assert is_drawing_grid(_grid_block(
        3, 16, col_gaps=[20, 180, 15, 90, 12, 200, 18, 40, 250, 10, 80, 15, 120, 30, 70, 25]
    )) is True
    assert is_drawing_grid(_grid_block(25, 9)) is False
    assert is_drawing_grid(_grid_block(40, 9)) is False
    assert is_drawing_grid(_grid_block(83, 17)) is False


def test_stamp_block_is_the_narrow_title_column():
    """Боковая графа листа (42×425) — штамп, спека 40×9 — нет."""
    stamp = TableBlock((15.0, 752.0, 57.0, 1177.0), n_rows=7, n_cols=5)
    spec = _grid_block(40, 9)
    assert looks_stamp_block(stamp) is True
    assert looks_stamp_block(spec) is False


def test_should_try_rotation_only_for_single_tall_header_cells():
    """«Фахверк» 62×43 крутим; merged-наименование профиля — нет."""
    fachwerk = (587.36, 86.16, 629.9, 148.5)
    profile = (303.86, 159.84, 388.94, 273.24)
    assert should_try_rotation(fachwerk, row_span=1) is True
    assert should_try_rotation(profile, row_span=5) is False
    assert should_try_rotation((0, 0, 85, 85), row_span=1) is False


def test_worth_rotation_skips_already_cyrillic_text():
    assert _worth_rotation("poroHbl") is True
    assert _worth_rotation("5 а 8 a}") is True
    assert _worth_rotation("Наименование профиля") is False
    assert _worth_rotation("Поз.") is False


def test_overlap_frac_for_thin_numbering_row():
    cell = (303.86, 148.5, 388.94, 159.84)
    word = (310.0, 147.8, 322.0, 160.5)
    assert _inside_strict_would_fail(word, cell)
    assert _overlap_frac(word, cell) > 0.45


def _inside_strict_would_fail(inner, outer, tol=0.5):
    return not (inner[0] >= outer[0] - tol and inner[2] <= outer[2] + tol
                and inner[1] >= outer[1] - tol and inner[3] <= outer[3] + tol)


def test_build_grid_recovers_missing_outer_border():
    """У левой таблицы листа нет левой границы — она восстанавливается."""
    xs = [30.0, 60.0, 90.0]
    ys = [0.0, 20.0, 40.0, 60.0]
    h, v = _grid_lines(xs, ys)
    # горизонтали тянутся левее самой левой вертикали
    h = [Ruling(y, 0.0, xs[-1]) for y in ys]
    blk = _build_grid(h, v, (xs[0], ys[0], xs[-1], ys[-1]))
    assert blk.xs[0] == pytest.approx(0.0)
    assert blk.n_cols == 3


# --------------------------------------------------------------------------- #
#  распознавание глифов: вспомогательные функции
# --------------------------------------------------------------------------- #
def test_merge_counters_joins_inner_contour_only():
    outer = (0.0, 0.0, 10.0, 10.0)
    inner = (2.0, 2.0, 8.0, 8.0)          # «дырка» внутри '0'
    neighbour = (10.5, 0.0, 20.0, 10.0)   # соседний символ
    out = merge_counters([outer, inner, neighbour])
    assert len(out) == 2


def test_merge_counters_keeps_touching_neighbours_apart():
    """'□' и '1' почти касаются — склеивать их нельзя."""
    square = (0.0, 0.0, 8.0, 8.0)
    one = (8.1, 0.0, 10.0, 8.0)
    assert len(merge_counters([square, one])) == 2


def test_merge_diacritics_requires_adjacency():
    base = (0.0, 10.0, 5.0, 17.0)
    breve = (0.5, 8.5, 4.5, 9.8)          # прямо над базой -> 'й'
    far = (0.5, 0.0, 4.5, 1.0)            # дефис верхней строки -> не приклеивать
    assert len(merge_diacritics([base, breve])) == 1
    assert len(merge_diacritics([base, far])) == 2


def test_group_lines_attaches_comma_to_its_line():
    """Запятая стоит низко; она обязана попасть в свою строку, а не в отдельную."""
    digits = [(0.0, 0.0, 4.0, 7.0), (5.0, 0.0, 9.0, 7.0), (12.0, 0.0, 16.0, 7.0)]
    comma = (9.5, 5.5, 11.0, 8.2)
    lines = group_lines(digits + [comma])
    assert len(lines) == 1
    assert len(lines[0]) == 4


def test_baseline_is_mode_not_max():
    """Базовую линию задаёт большинство глифов, а не выносной элемент 'р'."""
    line = [(0.0, 0.0, 4.0, 7.0), (5.0, 0.0, 9.0, 7.0),
            (10.0, 0.0, 14.0, 7.0), (15.0, 2.0, 19.0, 9.5)]      # 'р'
    assert baseline_px(line, 1.0) == pytest.approx(7.0, abs=0.3)


def test_match_score_prefers_correct_shape():
    """Симметричное покрытие различает 'с' и 'о' (обычный IoU — нет)."""
    ring = np.zeros((21, 21), bool)
    ring[0:3, 3:18] = ring[18:21, 3:18] = True
    ring[3:18, 0:3] = ring[3:18, 18:21] = True
    arc = ring.copy()
    arc[7:14, 18:21] = False          # разрыв справа -> 'с'
    assert _match_score(arc, arc) > _match_score(arc, ring)
    assert _match_score(ring, ring) > _match_score(ring, arc)


def test_hollow_rect_rejects_filled_interior():
    """'в' закрашена внутри и не должна выдавать себя за '□'."""
    h = w = 24
    box = np.zeros((h, w), bool)
    box[0:3, :] = box[-3:, :] = True
    box[:, 0:3] = box[:, -3:] = True
    assert _hollow_rect_score(box) > 0.7
    with_bar = box.copy()
    with_bar[10:13, :] = True          # средняя перекладина
    assert _hollow_rect_score(with_bar) == 0.0


# --------------------------------------------------------------------------- #
#  проверка арифметики
# --------------------------------------------------------------------------- #
def _cell(value, row=0, col=0):
    c = Cell(row=row, col=col, text=str(value).replace(".", ","))
    return normalize_cell(c, "element_mass")


def _cols():
    return [Column(4, "element_mass", "A", element="A"),
            Column(5, "element_mass", "B", element="B"),
            Column(6, "total_mass", "Итого")]


def test_row_sum_ok_and_failed():
    cols = _cols()
    good = LogicalRow(1, "data", 1, {"element:4": _cell(3.44), "element:5": _cell(2.90),
                                     "total_mass": _cell(6.34)})
    bad = LogicalRow(2, "data", 2, {"element:4": _cell(3.44), "element:5": _cell(2.90),
                                    "total_mass": _cell(9.99)})
    checks = check_row_sums([good, bad], cols, Tolerance())
    assert checks[0].status == "ok"
    assert checks[1].status == "failed"
    assert checks[1].reason == "row total mismatch"
    assert checks[1].calculated == pytest.approx(6.34)


def test_row_sum_tolerance_absorbs_rounding():
    """Значения округлены до 2 знаков — сумма может слегка не сходиться."""
    cols = _cols()
    row = LogicalRow(1, "data", 1, {"element:4": _cell(0.005), "element:5": _cell(0.005),
                                    "total_mass": _cell(0.02)})
    assert check_row_sums([row], cols, Tolerance()).pop().status == "ok"


def test_group_total_uses_only_its_own_group():
    cols = _cols()
    rows = [
        LogicalRow(1, "data", 1, {"element:4": _cell(0.02), "total_mass": _cell(0.02)}),
        LogicalRow(2, "data", 2, {"element:4": _cell(0.61), "total_mass": _cell(0.61)}),
        LogicalRow(3, "group_total", 3, {"element:4": _cell(0.63), "total_mass": _cell(0.63)}),
        LogicalRow(4, "data", 4, {"element:5": _cell(4.0), "total_mass": _cell(4.0)}),
        LogicalRow(5, "group_total", 5, {"element:5": _cell(4.0), "total_mass": _cell(4.0)}),
    ]
    checks = check_group_totals(rows, cols, Tolerance())
    assert all(c.status == "ok" for c in checks), [c for c in checks if c.status != "ok"]


def test_grand_total_falls_back_to_group_totals():
    """Строк «Всего профиля» на листе может не быть — складываем «Итого»."""
    cols = _cols()
    rows = [
        LogicalRow(1, "group_total", 1, {"element:4": _cell(2.93), "total_mass": _cell(31.85)}),
        LogicalRow(2, "group_total", 2, {"element:4": _cell(2.98), "total_mass": _cell(9.98)}),
        LogicalRow(3, "grand_total", 3, {"element:4": _cell(5.91), "total_mass": _cell(41.83)}),
    ]
    checks = check_grand_total([(rows, cols)], Tolerance())
    assert checks and all(c.status == "ok" for c in checks),         [c for c in checks if c.status != "ok"]


def test_grand_total_without_terms_is_skipped_not_failed():
    """Складывать нечего — проверка пропущена, а не провалена."""
    cols = _cols()
    rows = [LogicalRow(1, "data", 1, {"element:4": _cell(1.0), "total_mass": _cell(1.0)}),
            LogicalRow(2, "grand_total", 2, {"total_mass": _cell(1.0)})]
    checks = check_grand_total([(rows, cols)], Tolerance())
    assert [c.status for c in checks] == ["skipped"]


def test_summarize_maps_ok_to_passed():
    checks = [RowCheck(1, "row_sum", 1.0, 1.0, 0.0, 0.02, "ok"),
              RowCheck(2, "row_sum", 1.0, 2.0, 1.0, 0.02, "failed")]
    assert summarize(checks) == {"passed": 1, "failed": 1, "skipped": 0}


# --------------------------------------------------------------------------- #
#  выбор движка в гибридном OCR
# --------------------------------------------------------------------------- #
def _pair(rapid: str, tess: str) -> list[TextLine]:
    """Два варианта одной ячейки: как её прочитали RapidOCR и Tesseract."""
    box = (0.0, 0.0, 10.0, 5.0)
    out = []
    if rapid:
        out.append(TextLine(rapid, box, engine="rapidocr"))
    if tess:
        out.append(TextLine(tess, box, engine="tesseract"))
    return out


@pytest.mark.parametrize("rapid,tess,expected", [
    # слова: у RapidOCR нет кириллицы, три буквы и больше — к Tesseract
    ("NTOFO:", "ИТОГО:", "tesseract"),
    ("C255 10 F0CT 27772-2021", "(255 ПО ГОСТ 27772-2021", "tesseract"),
    ("HEY4 TEHHbIN META//, 2%", "НЕУЧТЕННЫЙ МЕТАЛЛ, 2%", "tesseract"),
    # числа и обозначения размеров — к RapidOCR: Tesseract теряет запятую
    ("23212,8", "232128", "rapidocr"),
    ("5112,01", "5112,01", "rapidocr"),
    ("180×140x5", "о 180х140х5", "rapidocr"),
    ("L 125x8", "L", "rapidocr"),
    ("H60-845-0,8", "Н60-845-0,8", "rapidocr"),
    ("[24", "С24П", "rapidocr"),
    # RapidOCR выдал не число, а Tesseract — чистое число: значение не теряем
    ("E'698E", "3869,3", "tesseract"),
    # RapidOCR съел десятичную запятую, Tesseract её сохранил
    ("23857 49", "23857,19", "tesseract"),
    ("3869 3", "3869,3", "tesseract"),
    # Tesseract тоже без запятой — оставляем RapidOCR (запятую восставит нормализатор)
    ("23857 49", "2385749", "rapidocr"),
    # ячейку прочитал только один движок
    ("", "ИТОГО:", "tesseract"),
    ("492,6", "", "rapidocr"),
])
def test_resolve_engine(rapid, tess, expected):
    assert _resolve_engine(_pair(rapid, tess)) == expected


def test_resolve_engine_without_tags_falls_back_to_text():
    """Негибридный OCR слова не помечает — выбирать не из чего."""
    assert _resolve_engine([TextLine("18513,65", (0.0, 0.0, 10.0, 5.0))]) == "tesseract"


# --------------------------------------------------------------------------- #
#  несколько страниц
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("spec,n,expected", [
    ("", 3, [0, 1, 2]),
    ("1", 3, [0]),
    ("2", 3, [1]),
    ("1-2", 4, [0, 1]),
    ("1,3", 4, [0, 2]),
])
def test_parse_pages(spec, n, expected):
    assert parse_pages(spec, n) == expected


def _minimal_table_json(index: int, page: int) -> dict:
    return {
        "index": index, "title": "Таблица %d" % index, "kind": "spec_main",
        "part": "", "page": page, "notes": [], "continues_table": None,
        "n_rows": 2, "n_cols": 2, "header_rows": [0], "columns": [],
        "cells": [], "rows": [], "checks": [],
    }


def test_envelope_loads_tables_from_every_page(tmp_path):
    """Веб собирает все table_N.json, а не только последний номер."""
    for i, page in ((1, 1), (2, 2)):
        with open(tmp_path / ("table_%d.json" % i), "w", encoding="utf-8") as fh:
            json.dump(_minimal_table_json(i, page), fh)
    env = _build_envelope("jobid", "x.pdf", {"tables_found": 2}, str(tmp_path))
    assert [t["page"] for t in env["tables"]] == [1, 2]
    assert [t["index"] for t in env["tables"]] == [1, 2]


def _draw_grid(page, x0, y0, rows, cols, cell_w=70, cell_h=22, label=""):
    x1, y1 = x0 + cols * cell_w, y0 + rows * cell_h
    for r in range(rows + 1):
        y = y0 + r * cell_h
        page.draw_line((x0, y), (x1, y), width=0.6)
    for c in range(cols + 1):
        x = x0 + c * cell_w
        page.draw_line((x, y0), (x, y1), width=0.6)
    for r in range(rows):
        for c in range(cols):
            page.insert_text((x0 + c * cell_w + 6, y0 + r * cell_h + 15),
                             "%sR%dC%d" % (label, r, c), fontsize=8)


def test_rulings_follow_page_rotation():
    """Линовка с /Rotate 270 должна совпадать с тем, что видит зритель.

    get_drawings() отдаёт координаты mediabox. Без перевода сетка 4×3
    (строки×колонки в пространстве чертежа) остаётся 4×3 на повёрнутом
    листе 100×200, хотя на экране это уже 3×4.
    """
    doc = fitz.open()
    page = doc.new_page(width=200, height=100)
    _draw_grid(page, 20, 10, rows=4, cols=3, cell_w=50, cell_h=20)
    page.set_rotation(270)
    assert tuple(round(x) for x in page.rect) == (0, 0, 100, 200)
    h, v = extract_rulings(page)
    blocks = find_table_blocks(h, v, page_rect=page.rect, min_rows=3, min_cols=2)
    assert len(blocks) == 1
    blk = blocks[0]
    assert (blk.n_rows, blk.n_cols) == (3, 4)
    assert blk.bbox[0] >= -1 and blk.bbox[2] <= page.rect.width + 1
    assert blk.bbox[1] >= -1 and blk.bbox[3] <= page.rect.height + 1
    doc.close()


def test_multipage_pdf_keeps_every_page_table(tmp_path):
    """Две страницы с таблицами не должны затирать файлы друг друга."""
    pdf_path = tmp_path / "two_pages.pdf"
    doc = fitz.open()
    for label in ("A", "B"):
        page = doc.new_page()
        _draw_grid(page, 80, 80, rows=4, cols=4, label=label)
    doc.save(pdf_path)
    doc.close()
    out = tmp_path / "out"
    report = run(str(pdf_path), str(out), Options(dpi=150, ocr_backend="none"))
    assert report["pages_processed"] == 2
    jsons = sorted(p.name for p in out.iterdir() if p.name.startswith("table_")
                   and p.name.endswith(".json"))
    assert len(jsons) >= 2, jsons
    pages = []
    texts = []
    for name in jsons:
        with open(out / name, encoding="utf-8") as fh:
            payload = json.load(fh)
        pages.append(payload["page"])
        texts.append(" ".join(c["text"] for c in payload["cells"]))
    assert 1 in pages and 2 in pages
    assert any("A" in t for t in texts)
    assert any("B" in t for t in texts)


def test_xlsx_strips_illegal_control_chars(tmp_path):
    """OCR иногда кладёт в ячейку \\x00/\\x08 — openpyxl из-за них валит весь прогон."""
    dirty = "Зеп\x00halia масса, т"
    assert xlsx_safe(dirty) == "Зепhalia масса, т"
    table = Table(
        index=1, title="t", kind="generic",
        n_rows=1, n_cols=1,
        cells=[Cell(row=0, col=0, text="Зеп\x08halia масса, т", value_kind="text")],
    )
    path = tmp_path / "out.xlsx"
    write_xlsx(str(path), table, [], [])
    assert path.is_file() and path.stat().st_size > 0
