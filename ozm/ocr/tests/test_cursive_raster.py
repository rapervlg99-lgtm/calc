# -*- coding: utf-8 -*-
"""Правки по листу с растровой таблицей чертёжным курсивом (file-14, 2026-09-09):
выбор движка по содержимому в пробнике и по перекрытию ячейки, выпрямление
курсива перед Tesseract, роли колонок при нечитаемой «№ п.п.», подписи
служебных строк, марки стали и ГОСТы, серии двутавров и уголков."""
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ocrpdf.cell_reader import TextLine, _resolve_engine
from ocrpdf.models import Cell
from ocrpdf.normalizer import (canon_grades_and_standards, canon_service_row,
                               extract_standards, fix_profile_series, row_marker)
from ocrpdf.ocr_backends import _deslant, _estimate_slant
from ocrpdf.structure import LogicalRow, _close_prefix


def _cell(text, source="ocr", **kw):
    base = dict(row=0, col=0, row_span=1, col_span=1, bbox=(0, 0, 1, 1), page=1,
                confidence=0.9, source=source)
    base.update(kw)
    return Cell(text=text, **base)


def _tl(text, engine):
    return TextLine(text, (0, 0, 10, 10), True, False, 0.9, engine=engine)


# ---------------------------------------------------------------- движок по содержимому

def test_short_word_without_digits_goes_to_tesseract():
    """Подпись «т» (единица массы) у RapidOCR выходит латиницей «m»: слово без
    цифр, даже короткое, читает Tesseract; чистое число — RapidOCR."""
    assert _resolve_engine([_tl("m", "rapidocr"), _tl("т", "tesseract")]) == "tesseract"
    assert _resolve_engine([_tl("1", "rapidocr"), _tl("ий", "tesseract")]) == "rapidocr"
    assert _resolve_engine([_tl("0,340", "rapidocr"), _tl("OHO", "tesseract")]) == "rapidocr"


# ---------------------------------------------------------------- наклон письма

def _text_strip(deg: float) -> np.ndarray:
    img = np.full((64, 700), 255, np.uint8)
    cv2.putText(img, "Itogo Vsego profilya 12345", (5, 48), cv2.FONT_HERSHEY_SIMPLEX, 1.4, 0, 3)
    t = float(np.tan(np.radians(deg)))
    M = np.float32([[1.0, -t, max(0.0, t * 64)], [0.0, 1.0, 0.0]])
    return cv2.warpAffine(img, M, (img.shape[1] + 40, 64), borderValue=255)


def test_slant_is_estimated_and_removed():
    assert abs(_estimate_slant([_text_strip(0)])) <= 1.5
    est = _estimate_slant([_text_strip(15)])
    assert 12.0 <= est <= 18.0
    back = _deslant(_text_strip(15), float(np.tan(np.radians(est))))
    assert abs(_estimate_slant([back])) <= 2.0
    # наклон влево тоже узнаётся со знаком
    assert -13.0 <= _estimate_slant([_text_strip(-10)]) <= -7.0


def test_rulings_do_not_pull_slant_to_zero():
    """Вертикальные линии таблицы в кропе не должны маскировать наклон текста."""
    strip = _text_strip(15)
    strip[:, 30:33] = 0
    strip[:, 400:403] = 0
    assert 12.0 <= _estimate_slant([strip]) <= 18.0


def test_deslant_keeps_content_and_pads_width():
    st = _text_strip(15)
    out = _deslant(st, float(np.tan(np.radians(15))))
    assert out.shape[0] == st.shape[0]
    assert out.shape[1] > st.shape[1]
    assert (out < 128).sum() > 0.8 * (st < 128).sum()


# ---------------------------------------------------------------- служебные строки

def test_garbled_service_labels_are_rewritten():
    cases = {
        "Мm020:": "Итого:",
        "Итог:": "Итого:",
        "„Итого“": "Итого",
        "Итого’": "Итого",
        "Вге20 профиия:": "Всего профиля:",
        "Всего прафиия": "Всего профиля",
        "В mоm числе nо маркам стали": "В том числе по маркам стали",
    }
    for raw, expect in cases.items():
        c = _cell(raw)
        assert canon_service_row(c) is True, raw
        assert c.text == expect, raw
        assert any("raw=" in n for n in c.notes)


def test_exact_service_labels_are_left_alone():
    for raw in ("Итого:", "Итого", "Всего профиля:", "Всего масса металла:", "Масса металла"):
        c = _cell(raw)
        assert canon_service_row(c) is False, raw
        assert c.text == raw


def test_data_rows_are_not_service_rows():
    for raw in ("Профили стальные", "Sеер", "C245-4", "160х160х5"):
        assert row_marker(raw) is None
        c = _cell(raw)
        assert canon_service_row(c) is False


def test_vsego_metalla_is_grand_total():
    assert row_marker("Всего металла:") == "grand_total"
    assert row_marker("Всеzо металла") == "grand_total"


# ---------------------------------------------------------------- марки и стандарты

def test_paren_before_grade_becomes_letter_s_and_standards_are_canonical():
    assert canon_grades_and_standards("(245-4\nГОСТ 27772-2021") == "С245-4\nГОСТ 27772-2021"
    assert canon_grades_and_standards("(245-4 [ОСТ 27772-2021") == "С245-4 ГОСТ 27772-2021"
    assert canon_grades_and_standards("250 [ОСТ Р 52246-2004") == "250 ГОСТ Р 52246-2004"
    assert canon_grades_and_standards("250 ГОСГ Р 52246-2004") == "250 ГОСТ Р 52246-2004"
    assert canon_grades_and_standards("FОСТ 19903-2015") == "ГОСТ 19903-2015"
    # уже правильное — без изменений; размер профиля со скобкой не марка
    assert canon_grades_and_standards("С255 по ГОСТ 27772-2021") == "С255 по ГОСТ 27772-2021"
    assert canon_grades_and_standards("ТУ 14-1-5399-2000") == "ТУ 14-1-5399-2000"
    assert canon_grades_and_standards("(160х160х5") == "(160х160х5"
    assert extract_standards("ГОСГ Р 52246-2004") == ["ГОСТ Р 52246-2004"]


# ---------------------------------------------------------------- серии профилей

def test_ibeam_six_becomes_series_letter_and_angle_one_is_dropped():
    beams = _cell("Двутавры стальные горячекатаные ГОСТ Р 57837-2017")
    angles = _cell("Y20/KU CMO/bHbIE неравнополочные ГОСТ 8510-86")
    sheets = _cell("Сталь листовая горячекатаная")
    rows = [
        LogicalRow(1, "data", 1, {"profile_group": beams, "profile_size": _cell("3061")}),
        LogicalRow(2, "data", 2, {"profile_group": beams, "profile_size": _cell("35Ш1")}),
        LogicalRow(3, "data", 3, {"profile_group": beams, "profile_size": _cell("3061", "text_layer")}),
        LogicalRow(4, "data", 4, {"profile_group": angles, "profile_size": _cell("1140х90х8")}),
        LogicalRow(5, "data", 5, {"profile_group": angles, "profile_size": _cell("125х8")}),
        LogicalRow(6, "data", 6, {"profile_group": angles, "profile_size": _cell("163х5")}),
        LogicalRow(7, "data", 7, {"profile_group": sheets, "profile_size": _cell("1140х90х8")}),
        LogicalRow(8, "group_total", None, {"profile_group": beams, "profile_size": _cell("3061")}),
    ]
    assert fix_profile_series(rows) == 3
    got = [r.cells["profile_size"].text for r in rows]
    assert got == ["30Б1", "35Ш1", "3061", "140х90х8", "125х8", "63х5", "1140х90х8", "3061"]
    assert rows[0].cells["profile_size"].requires_review is True
    assert any("«Б»" in n for n in rows[0].cells["profile_size"].notes)


# ---------------------------------------------------------------- шапка

def test_close_prefix_tolerates_ocr_errors_in_mass_header():
    assert _close_prefix("массаметаллапозиементамт", "массаметаллапоэлементам")
    assert not _close_prefix("наименованиепрофиля", "массаметаллапоэлементам")
    assert not _close_prefix("масса", "массаметаллапоэлементам")


# ---------------------------------------------------------------- штамп, скобка, границы ячейки

def test_paren_before_word_is_letter_s():
    from ocrpdf.structure import fix_paren_s
    assert fix_paren_s("(Вязи покрытия") == "Связи покрытия"
    assert fix_paren_s("(редняя школа") == "Средняя школа"
    # настоящие скобки (есть закрывающая) и скобка перед цифрой не трогаются
    assert fix_paren_s("Итого (Всего)") == "Итого (Всего)"
    assert fix_paren_s("(с245") == "(с245"


def test_stamp_labels_are_canonicalised_only_for_labels():
    from ocrpdf.structure import canonical_stamp_label
    assert canonical_stamp_label("Проберил") == "Проверил"
    assert canonical_stamp_label("И3М.") == "Изм."
    assert canonical_stamp_label("Разроботал") == "Разработал"
    assert canonical_stamp_label("Стадия") == "Стадия"
    for other in ("09-25", "22.08.25", "Сапрыкин", "Спецификация металлопроката", "1"):
        assert canonical_stamp_label(other) == "", other


def test_mixed_script_is_folded_only_when_it_becomes_cyrillic():
    from ocrpdf.structure import fold_mixed_script
    assert fold_mixed_script("Осmроbсkuu") == "Островскии"
    # мало латиницы, чистая латиница или обозначение — как есть
    assert fold_mixed_script("Аlаmа") == "Аlаmа"
    assert fold_mixed_script("L 125x8") == "L 125x8"
    assert fold_mixed_script("creer eee") == "creer eee"


def test_element_name_recovers_svyazi_pokrytiya():
    from ocrpdf.structure import element_name
    assert element_name("(Вязи покрытия") == "Связи покрытия"
    assert element_name("Фонари") == "Фонари"


def test_cell_border_lines_are_stripped_before_rotated_read():
    from ocrpdf.cell_reader import _strip_cell_border
    img = np.full((120, 300), 255, np.uint8)
    cv2.putText(img, "Fonari", (40, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.6, 0, 3)
    img[:, :3] = 0          # левая граница ячейки
    img[:, -2:] = 0         # правая
    img[:2, :] = 0          # верхняя
    out = _strip_cell_border(img)
    # границы срезаны, вокруг — белое поле, буквы на месте
    assert out[0].min() == 255 and out[:, 0].min() == 255 and out[:, -1].min() == 255
    assert (out < 128).sum() >= 0.9 * ((img < 128).sum() - 3 * 120 - 2 * 120 - 2 * 300)
    # кроп без линовки возвращается как есть (только белое поле)
    plain = np.full((60, 200), 255, np.uint8)
    cv2.putText(plain, "Balki", (10, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 0, 2)
    out2 = _strip_cell_border(plain)
    assert (out2 < 128).sum() == (plain < 128).sum()


# ---------------------------------------------------------------- марки, серии, позиции (второй заход)

def test_steel_grade_tokens_are_canonicalised_by_dictionary():
    from ocrpdf.normalizer import fix_steel_grade
    assert fix_steel_grade("6255 ГОСТ 27772-2021") == "С255 ГОСТ 27772-2021"
    assert fix_steel_grade("(3556 ГОСТ Р 57837-2017 табл.5") == "С355Б ГОСТ Р 57837-2017 табл.5"
    assert fix_steel_grade("(245-4") == "С245-4"
    # уже канон, неизвестный номер, не марка — без изменений
    for t in ("С355 ГОСТ 27772-2021", "С345-6", "250 ГОСТ Р 52246-2004", "09Г2С", "6999"):
        assert fix_steel_grade(t) == t, t


def test_latin_r_in_gost_is_recognised():
    assert canon_grades_and_standards("С355 rОСТ 27772-2021") == "С355 ГОСТ 27772-2021"
    assert extract_standards("rОСТ 27772-2021") == ["ГОСТ 27772-2021"]


def test_beam_glyph_letters_channels_and_broken_three():
    beams = _cell("Двутавры стальные горячекатаные")
    ch = _cell("Швеллеры стальные горячекатаные ГОСТ 8240-97")
    rows = [
        LogicalRow(1, "data", 1, {"profile_group": beams, "profile_size": _cell("2011", alt_text="I20W1")}),
        LogicalRow(2, "data", 2, {"profile_group": beams, "profile_size": _cell("Т+30Ш2", "text_layer")}),
        LogicalRow(3, "data", 3, {"profile_group": beams, "profile_size": _cell("Ш+э5Ш1", "text_layer")}),
        LogicalRow(4, "data", 4, {"profile_group": ch, "profile_size": _cell("27n")}),
        LogicalRow(5, "data", 5, {"profile_group": ch, "profile_size": _cell("?14П")}),
        LogicalRow(6, "data", 6, {"profile_group": ch, "profile_size": _cell("14П", "text_layer")}),
        LogicalRow(7, "data", 7, {"profile_group": ch, "profile_size": _cell("t+э0", "text_layer")}),
    ]
    fix_profile_series(rows)
    assert [r.cells["profile_size"].text for r in rows] == ["20Ш1", "30Ш2", "35Ш1", "27П", "14П", "14П", "t30"]


def test_file37_and_file13_cases():
    from ocrpdf.normalizer import canon_grades_and_standards
    beams = _cell("Двутавры стальные горячекатаные")
    ch = _cell("Швеллеры стальные горячекатаные ГОСТ 8240-97")
    rails = _cell("Крановые рельсы ГОСТ Р 53866-2010")
    angles = _cell("Уголки стальные горячекатаные равнополочные ГОСТ 8509-93")
    tube_folded = _cell("Труба квадратная 120х120х6. ГОСТ 8639-82")
    rows = [
        LogicalRow(1, "data", 1, {"profile_group": beams, "profile_size": _cell("20К31", "vector_glyph")}),
        LogicalRow(2, "data", 2, {"profile_group": beams, "profile_size": _cell("Ш+э5Кх1", "vector_glyph")}),
        LogicalRow(3, "data", 3, {"profile_group": beams, "profile_size": _cell("2011")}),          # без второго движка
        LogicalRow(4, "data", 4, {"profile_group": beams, "profile_size": _cell("3061")}),
        LogicalRow(5, "data", 5, {"profile_group": ch, "profile_size": _cell("?++0П", "vector_glyph")}),
        LogicalRow(6, "data", 6, {"profile_group": rails, "profile_size": _cell("КхР70", "vector_glyph")}),
        LogicalRow(7, "data", 7, {"profile_group": angles, "profile_size": _cell("150х150х10")}),
        LogicalRow(8, "data", 8, {"profile_group": angles, "profile_size": _cell("1140х90х8")}),
        LogicalRow(9, "data", 9, {"profile_group": tube_folded, "profile_size": _cell("")}),
    ]
    fix_profile_series(rows)
    got = [r.cells["profile_size"].text for r in rows]
    assert got == ["20К1", "35К1", "2011", "30Б1", "30П", "КР70", "150х150х10", "140х90х8", "120х120х6"]
    assert any("возможны" in n for n in rows[2].cells["profile_size"].notes)
    # годы известных стандартов
    assert canon_grades_and_standards("С345-6 ГОСТ 27772-20861") == "С345-6 ГОСТ 27772-2021"
    assert canon_grades_and_standards("ГОСТ 8509-93") == "ГОСТ 8509-93"
    assert canon_grades_and_standards("ГОСТ 12345-2099") == "ГОСТ 12345-2099"


def test_missing_positions_are_filled_from_neighbours():
    from ocrpdf.normalizer import fill_positions
    rows = [LogicalRow(1, "data", 1, {"position": _cell("1")}),
            LogicalRow(2, "data", None, {"position": _cell("m")}),
            LogicalRow(3, "data", 3, {"position": _cell("3")}),
            LogicalRow(4, "data", None, {"position": _cell("(-")}),
            LogicalRow(5, "data", None, {"position": _cell("О Ж ?Д")}),
            LogicalRow(6, "data", 6, {"position": _cell("6")}),
            LogicalRow(7, "data", None, {"position": _cell("x")}),
            LogicalRow(8, "data", 9, {"position": _cell("9")})]
    assert fill_positions(rows) == 3
    assert [r.position for r in rows] == [1, 2, 3, 4, 5, 6, None, 9]
    assert rows[1].cells["position"].text == "2" and rows[1].cells["position"].requires_review


def test_glyph_junk_is_worth_rotation():
    from ocrpdf.cell_reader import _worth_rotation
    assert _worth_rotation("ж ?Ф % К% № ?№")
    assert _worth_rotation("?+ ?ж")
    assert not _worth_rotation("Наименование профиля")


def test_element_names_tolerate_cursive_letter_confusions():
    from ocrpdf.structure import element_name
    assert element_name("BaNKU") == "Балки"
    assert element_name("Ванки") == "Балки"
    assert element_name("Соази бертикольные") == "Связи вертикальные"
    assert element_name("Надколонникиу") == "Надколонники"
    # незнакомое слово остаётся как есть
    assert element_name("Косоуры") == "Косоуры"


def test_group_name_falls_back_to_second_engine_and_keeps_tube_size():
    from ocrpdf.normalizer import normalize_cell
    c = _cell("Теуеа_КеggраТНаn 120х120х6. ГОСТ 8639-82")
    c.alt_text = "TpY6Q KBOAPOTHOA 120x120x6. F0CT 8639-82"
    normalize_cell(c, "profile_group")
    assert c.text.startswith("Труба квадратная 120х120х6")
    assert "ГОСТ 8639-82" in c.text


def test_trailing_profile_glyph_is_stripped_from_text_layer_marks():
    from ocrpdf.normalizer import strip_trailing_glyph
    cases = {"25Б1 т": "25Б1", "25К1 L": "25К1", "45М 7": "45М", "25х3 □": "25х3",
             "8П С": "8П", "160х80х5 С": "160х80х5", "Гн 100х5\n□": "Гн 100х5",
             "25Б1 1": "25Б1", "40К4 I": "40К4"}
    for raw, want in cases.items():
        assert strip_trailing_glyph(raw)[0] == want, raw
    for keep in ("RD18", "Ромб 12", "Н75-750-0,8", "30К1", "t4х140", "Всего профиля"):
        assert strip_trailing_glyph(keep) == (keep, ""), keep
