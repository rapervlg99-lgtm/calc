# -*- coding: utf-8 -*-
"""Правки распознавания чисел (2026-09-03): текстовый слой на повёрнутых
листах, ограничение шаблонов глифов, нормализация «0.14 5» и «５», плоский
лист без пустот, одиночная греческая буква не считается битой кодировкой."""
import os
import sys

import openpyxl

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ocrpdf.cell_reader import TextLine, _resolve_engine, build_text_lines
from ocrpdf.exporter import write_xlsx
from ocrpdf.fontfix import looks_broken
from ocrpdf.glyph_ocr import MAX_TEMPLATE_PX, _size_for, _templates, available_fonts
from ocrpdf.models import Cell, Table
from ocrpdf.normalizer import normalize_cell
from ocrpdf.pdfbackend import fitz
from ocrpdf.pipeline import classify_page
from ocrpdf.structure import Column, LogicalRow, column_key  # noqa: F401


def test_text_lines_follow_page_rotation():
    """На листе с /Rotate 270 строка текстового слоя должна лечь туда, где её
    видит зритель (и куда попадает сетка ячеек), а не в координаты mediabox."""
    doc = fitz.open()
    page = doc.new_page(width=200, height=100)
    page.insert_text((150, 80), "22.010", fontsize=8)
    page.set_rotation(270)
    assert tuple(round(x) for x in page.rect) == (0, 0, 100, 200)

    lines = build_text_lines(page, {})
    assert [t.text for t in lines] == ["22.010"]
    bb = lines[0].bbox
    # внутри повёрнутого листа 100×200
    assert -1 <= bb[0] and bb[2] <= page.rect.width + 1
    assert -1 <= bb[1] and bb[3] <= page.rect.height + 1
    # и там же, где слово отдаёт PyMuPDF после поворота
    words = page.get_text("words")
    expect = fitz.Rect(words[0][:4]) * page.rotation_matrix
    assert abs(bb[0] - expect.x0) < 0.5 and abs(bb[1] - expect.y0) < 0.5
    assert abs(bb[2] - expect.x1) < 0.5 and abs(bb[3] - expect.y1) < 0.5
    # строка, горизонтальная в mediabox, для зрителя повёрнутого листа вертикальна
    assert lines[0].horizontal is False
    doc.close()

    # и наоборот: текст, набранный на mediabox с поворотом 90°, после /Rotate 270
    # читается зрителем горизонтально — как числа в спецификации на file-3
    doc = fitz.open()
    page = doc.new_page(width=200, height=100)
    page.insert_text((150, 80), "7.210", fontsize=8, rotate=90)
    page.set_rotation(270)
    lines = build_text_lines(page, {})
    assert [t.text for t in lines] == ["7.210"]
    assert lines[0].horizontal is True
    bb = lines[0].bbox
    assert bb[2] - bb[0] > bb[3] - bb[1]
    doc.close()


def test_text_lines_unrotated_page_unchanged():
    doc = fitz.open()
    page = doc.new_page(width=200, height=100)
    page.insert_text((20, 50), "7.210", fontsize=8)
    lines = build_text_lines(page, {})
    assert [t.text for t in lines] == ["7.210"]
    raw = page.get_text("rawdict")["blocks"][0]["lines"][0]["bbox"]
    assert all(abs(a - b) < 1e-6 for a, b in zip(lines[0].bbox, raw))
    doc.close()


def test_single_greek_letter_is_not_broken_encoding():
    assert looks_broken("δ=4 мм") is False
    assert looks_broken("α, град") is False
    # битая кодировка: CID попали в Latin Extended-B / IPA либо серия греческих
    assert looks_broken("ȼɫɟɝɨ") is True
    assert looks_broken("αβγδ") is True
    assert looks_broken("Итого\x03") is True


def test_classify_page_layer_ok_with_thickness_marks():
    doc = fitz.open()
    page = doc.new_page()
    kind, layer = classify_page(page, 10, 5, "δ=4 мм\nδ=6 мм\n0.035")
    assert layer == "ok"
    kind, layer = classify_page(page, 10, 5, "ȼɫɟɝɨ\n0.035")
    assert layer == "broken_encoding"
    doc.close()


def test_split_decimal_is_glued_and_flagged():
    cell = normalize_cell(Cell(row=10, col=6, text="0.14 5", source="ocr"), "element_mass")
    assert cell.text == "0.145"
    assert cell.normalized_value == 0.145
    assert cell.requires_review is True
    cell = normalize_cell(Cell(row=19, col=8, text="2.4 05", source="ocr"), "total_mass")
    assert cell.normalized_value == 2.405
    # «1 2» по-прежнему не склеивается: разделителя нет, это может быть что угодно
    cell = normalize_cell(Cell(row=1, col=5, text="1 2", source="ocr"), "element_mass")
    assert cell.normalized_value is None
    # текстовый слой точен по построению — его не трогаем
    cell = normalize_cell(Cell(row=1, col=5, text="0.14 5", source="text_layer"), "element_mass")
    assert cell.text == "0.14 5" and cell.normalized_value is None


def test_numeric_column_letters_become_digits_but_text_columns_keep_them():
    """«0,В2» в колонке масс — это 0,82 (буква там невозможна), а «В25» в
    текстовой колонке — класс бетона, его трогать нельзя."""
    cell = normalize_cell(Cell(row=4, col=8, text="0,В2", source="vector_glyph"), "element_mass")
    assert cell.text == "0,82" and cell.normalized_value == 0.82
    assert cell.requires_review is True
    cell = normalize_cell(Cell(row=4, col=3, text="4З", source="ocr"), "position")
    assert cell.text == "43" and cell.normalized_value == 43
    cell = normalize_cell(Cell(row=4, col=0, text="В25", source="ocr"), "unknown")
    assert cell.text == "В25"
    cell = normalize_cell(Cell(row=4, col=2, text="tВ", source="ocr"), "profile_size")
    assert "8" not in cell.text
    # текстовый слой не правим даже в числовой колонке
    cell = normalize_cell(Cell(row=4, col=8, text="0,В2", source="text_layer"), "element_mass")
    assert cell.text == "0,В2"


def test_double_decimal_separator_is_collapsed():
    cell = normalize_cell(Cell(row=22, col=12, text="46.,9", source="ocr"), "total_mass")
    assert cell.text == "46,9" and cell.normalized_value == 46.9 and cell.requires_review is True
    cell = normalize_cell(Cell(row=22, col=12, text="46,9", source="ocr"), "total_mass")
    assert cell.normalized_value == 46.9 and cell.requires_review is False


def test_fullwidth_digits_are_narrowed():
    cell = normalize_cell(Cell(row=7, col=3, text="５", source="ocr"), "position")
    assert cell.text == "5" and cell.normalized_value == 5
    cell = normalize_cell(Cell(row=7, col=4, text="１２，５", source="ocr"), "element_mass")
    assert cell.text == "12,5" and cell.normalized_value == 12.5


def test_flat_sheet_keeps_unparsed_number_text(tmp_path):
    """Число, которое не разобралось («12,4?»), в плоском листе остаётся
    текстом, а не пустой ячейкой."""
    bad = Cell(row=1, col=5, text="12,4?", source="ocr", value_kind="text",
               normalized_value=None, requires_review=True)
    good = Cell(row=1, col=6, text="0,5", source="text_layer", value_kind="number",
                normalized_value=0.5)
    table = Table(index=1, title="t", kind="spec_main", n_rows=2, n_cols=7,
                  cells=[bad, good])
    cols = [Column(index=5, role="element_mass", title="Фермы", element="Фермы"),
            Column(index=6, role="total_mass", title="Общая масса, т")]
    rows = [LogicalRow(row=1, kind="data", position=1,
                       cells={column_key(cols[0]): bad, "total_mass": good})]
    path = tmp_path / "out.xlsx"
    write_xlsx(str(path), table, cols, rows)
    ws = openpyxl.load_workbook(path)["Плоская"]
    head = [c.value for c in ws[1]]
    data = [c.value for c in ws[2]]
    assert data[head.index("Фермы")] == "12,4?"
    assert data[head.index("Общая масса, т")] == 0.5


def test_engine_choice_prefers_tesseract_when_rapidocr_dropped_digits():
    """На скане «0,34» RapidOCR прочитал как «'0», Tesseract — «0,34»:
    у Tesseract цифр больше и есть десятичный знак — верим ему."""
    box = (0.0, 0.0, 10.0, 5.0)
    pair = [TextLine("'0", box, engine="rapidocr"), TextLine("0,34", box, engine="tesseract")]
    assert _resolve_engine(pair) == "tesseract"
    # но обычное число с запятой у обоих по-прежнему берёт RapidOCR
    pair = [TextLine("5112,01", box, engine="rapidocr"), TextLine("5112,01", box, engine="tesseract")]
    assert _resolve_engine(pair) == "rapidocr"
    # и Tesseract без запятой ничего не выигрывает
    pair = [TextLine("23212,8", box, engine="rapidocr"), TextLine("232128", box, engine="tesseract")]
    assert _resolve_engine(pair) == "rapidocr"


def test_forwarded_prefix_drives_page_links():
    """nginx калькулятора ОЗМ проксирует /ocr/ и шлёт X-Forwarded-Prefix:
    страница строит ссылки от этого префикса; мусор в заголовке игнорируется."""
    from ocrpdf.webapp import forwarded_prefix, page_html
    assert forwarded_prefix({"X-Forwarded-Prefix": "/ocr"}) == "/ocr"
    assert forwarded_prefix({"X-Forwarded-Prefix": "/ocr/"}) == "/ocr"
    assert forwarded_prefix({}) == ""
    assert forwarded_prefix({"X-Forwarded-Prefix": "http://evil.example/x"}) == ""
    assert 'const BASE = "/ocr";' in page_html("/ocr")
    assert 'const BASE = "";' in page_html("")
    # режим встраивания передаёт результат родительскому окну
    assert "ocrpdf:result" in page_html("")


def test_profile_type_glyphs_are_dropped_from_size():
    """Схематический значок сечения перед обозначением (□, Ι, L, [) не входит в
    обозначение и не должен превращаться в цифру или букву."""
    def size(text, source="ocr"):
        return normalize_cell(Cell(row=3, col=2, text=text, source=source), "profile_size")
    assert size("口200×10").text == "200х10"
    assert size("I 35K1").text == "35К1"
    assert size("I35К1").text == "35К1"          # раньше «I» рядом с цифрой становилась «1»: «135К1»
    assert size("1 35К1").text == "35К1"          # значок прочитан как единица
    assert size("? 35К1").text == "35К1"          # значок не прочитан шаблонами
    assert size("L 140×x10").text == "140х10"
    assert size("L 125x80x8").text == "125х80х8"
    assert size("[ 20П").text == "20П"
    assert size("+40").text == "t40"              # чертёжное «t» прочитано как плюс
    assert size("t30").text == "t30"
    assert size("116").text == "116"              # без пробела единицу не трогаем
    assert size("СКН153-900-1,0").text == "СКН153-900-1,0"
    for c in (size("口200×10"), size("I35К1"), size("[ 20П")):
        assert any("значок типа профиля" in n for n in c.notes)
    # текстовый слой: символы и буквы-значки чертёжного шрифта снимаем, «|» там — текст
    assert size("□140х5", "text_layer").text == "140х5"
    assert size("∟100х8", "text_layer").text == "100х8"
    assert size("L100х8", "text_layer").text == "100х8"
    assert size("Ι 35К1", "text_layer").text == "35К1"
    assert size("|2651", "text_layer").text == "|2651"
    assert size("δ=4 мм", "text_layer").text == "δ=4 мм"


def test_series_letter_o_becomes_zero_in_ibeam_mark():
    from ocrpdf.normalizer import fix_series_zero
    assert fix_series_zero("25ШО") == "25Ш0"
    assert fix_series_zero("25ШO") == "25Ш0"
    assert fix_series_zero("20Шо") == "20Ш0"
    assert fix_series_zero("25Ш1") == "25Ш1"
    assert fix_series_zero("100Ш1") == "100Ш1"
    assert fix_series_zero("140х5") == "140х5"
    assert fix_series_zero("С255") == "С255"
    # полный путь: значок двутавра снят, латиница переведена, нуль восстановлен
    cell = normalize_cell(Cell(row=5, col=2, text="I25WO", source="ocr"), "profile_size")
    assert cell.text == "25Ш0" and cell.normalized_value == "25Ш0"
    assert any("вместо нуля" in n for n in cell.notes)
    # текстовый слой не трогаем
    cell = normalize_cell(Cell(row=5, col=2, text="25ШО", source="text_layer"), "profile_size")
    assert cell.text == "25ШО"


def test_bare_number_in_sheet_group_becomes_thickness():
    """«116», «10» в группе «Прокат листовой» — это t16, t10 (RapidOCR теряет или
    превращает в единицу перекладину чертёжного «t»). Вне листовой группы не трогаем."""
    from ocrpdf.normalizer import fix_sheet_thickness
    sheet = Cell(row=9, col=0, text="Прокат листовой горячекатаный", source="ocr", row_span=4)
    beams = Cell(row=2, col=0, text="Двутавры стальные", source="ocr")
    rows = [
        LogicalRow(row=9, kind="data", cells={"profile_group": sheet,
                                                "profile_size": Cell(row=9, col=2, text="116", source="ocr")}),
        LogicalRow(row=10, kind="data", cells={"profile_group": sheet,
                                                 "profile_size": Cell(row=10, col=2, text="10", source="ocr")}),
        LogicalRow(row=11, kind="data", cells={"profile_group": sheet,
                                                 "profile_size": Cell(row=11, col=2, text="t8", source="ocr")}),
        LogicalRow(row=12, kind="data", cells={"profile_group": sheet,
                                                 "profile_size": Cell(row=12, col=2, text="14", source="text_layer")}),
        LogicalRow(row=3, kind="data", cells={"profile_group": beams,
                                                "profile_size": Cell(row=3, col=2, text="10", source="ocr")}),
        LogicalRow(row=13, kind="group_total", cells={"profile_group": sheet,
                                                        "profile_size": Cell(row=13, col=2, text="12", source="ocr")}),
    ]
    assert fix_sheet_thickness(rows) == 2
    assert rows[0].cells["profile_size"].text == "t16"
    assert rows[0].cells["profile_size"].requires_review is True
    assert rows[1].cells["profile_size"].text == "t10"
    assert rows[2].cells["profile_size"].text == "t8"           # уже толщина
    assert rows[3].cells["profile_size"].text == "14"           # текстовый слой не правим
    assert rows[4].cells["profile_size"].text == "10"           # не листовая группа
    assert rows[5].cells["profile_size"].text == "12"           # не строка данных

    # наименование группы прочитано в кашу — листовую группу выдаёт содержимое:
    # большинство обозначений «tNN»
    junk = Cell(row=34, col=0, text="nроkаm 20рАНеКОmаНblU F", source="ocr", row_span=6)
    def r(row, size, src="ocr"):
        return LogicalRow(row=row, kind="data", cells={"profile_group": junk,
                                                        "profile_size": Cell(row=row, col=2, text=size, source=src)})
    rows2 = [r(34, "t40"), r(35, "t30"), r(36, "116"), r(37, "t12"), r(38, "10"), r(39, "250")]
    assert fix_sheet_thickness(rows2) == 2
    assert [x.cells["profile_size"].text for x in rows2] == ["t40", "t30", "t16", "t12", "t10", "250"]
    # а в группе, где толщин мало, одинокие числа не трогаем
    rows3 = [r(50, "20П"), r(51, "10"), r(52, "t8")]
    assert fix_sheet_thickness(rows3) == 0


def test_tolerance_follows_sheet_decimals():
    """Массы в одну десятую («23,2») округлены до 0,05 т каждая — допуск
    масштабируется, и честное расхождение итога на 0,1 не краснеет."""
    from ocrpdf.validator import Tolerance, check_row_sums, mass_decimals
    cols = [Column(index=4, role="element_mass", title="Фермы", element="Фермы"),
            Column(index=5, role="element_mass", title="Балки", element="Балки"),
            Column(index=6, role="total_mass", title="Общая масса, т")]
    def num(row, col, text):
        c = Cell(row=row, col=col, text=text, source="ocr", value_kind="number",
                 normalized_value=float(text.replace(",", ".")))
        return c
    row = LogicalRow(row=14, kind="data", position=12, cells={
        column_key(cols[0]): num(14, 4, "11,2"), column_key(cols[1]): num(14, 5, "12,1"),
        "total_mass": num(14, 6, "23,2")})
    assert mass_decimals([row], cols) == 1
    assert check_row_sums([row], cols, Tolerance()).pop().status == "failed"      # допуск под сотые
    tol = Tolerance().for_decimals(mass_decimals([row], cols))
    assert (tol.base, tol.per_term) == (0.2, 0.06)
    assert check_row_sums([row], cols, tol).pop().status == "ok"
    # два знака — допуск прежний
    row2 = LogicalRow(row=3, kind="data", position=1, cells={
        column_key(cols[0]): num(3, 4, "7,21"), "total_mass": num(3, 6, "7,21")})
    assert mass_decimals([row2], cols) == 2
    assert Tolerance().for_decimals(2) == Tolerance()
    assert Tolerance().for_decimals(3) == Tolerance()


def test_garbled_group_names_and_totals_are_recognised():
    """Каша чертёжного курсива сопоставляется со словарём групп и маркерами
    служебных строк (file-7): текст ячейки не выдумывается, а приводится к канону."""
    from ocrpdf.structure import canonical_profile_group
    from ocrpdf.normalizer import row_marker
    assert canonical_profile_group("nроkаm\n20рАНеКОmаНblU\nFОСТ 19903-2015")[0] == "Прокат горячекатаный"
    assert canonical_profile_group("Аbуmаbрbl сМα /bНblе 20МеКQmQНblе С nа.рQ/1/е/lb НbIМU")[0].startswith("Двутавры стальные горячекатаные")
    assert canonical_profile_group("у20АКU сmα/bНblе 209еКаmQНblе рuВНОnО04НbIе F")[0] == "Уголки стальные горячекатаные равнополочные"
    assert canonical_profile_group("Прокат листовой горячекатаный\nГОСТ 19903-2015")[0] == "Прокат листовой горячекатаный"
    assert canonical_profile_group("С255-5\nГОСТ 27772-2021") == ("", 0.0)
    assert row_marker("Все20 nроΦu/9:") == "profile_total"
    assert row_marker("Всеzо nро中u/9:") == "profile_total"
    assert row_marker("Все20mассаМеmа//nа:") == "grand_total"
    assert row_marker("ВmОМ qUСnе nо МорКQМ U/IU НQUМеНОВQНUАМ:") == "section_header"
    assert row_marker("В том числе nо марком:") == "section_header"
    for junk in ("Vmс20:", "Мm020:", "Мmсz0:"):
        assert row_marker(junk) == "group_total"
    assert row_marker("120х6") is None
    assert row_marker("С255") is None


def test_standards_are_extracted_from_ocr_variants():
    """ГОСТ с точкой/переносом и латинскими двойниками приводится к канону."""
    from ocrpdf.normalizer import extract_standards, strip_standards
    assert extract_standards("355 ГОСТ.\n27772-2021") == ["ГОСТ 27772-2021"]
    assert extract_standards("nроkаm\nFОСТ 19903-2015") == ["ГОСТ 19903-2015"]
    assert extract_standards("гранями полок\nTOCT P\n57837-2017") == ["ГОСТ Р 57837-2017"]
    assert extract_standards("Двутавры ГOCT P 57837-2017") == ["ГОСТ Р 57837-2017"]
    assert extract_standards("Уголки ГОСТ 8509-93 и ТУ 14-1-5") == ["ГОСТ 8509-93", "ТУ 14-1-5"]
    assert extract_standards("ОСТ 36-72-82") == ["ОСТ 36-72-82"]
    assert extract_standards("неравнополочные ОСТ 8510-86") == ["ГОСТ 8510-86"]   # потерянная «Г»
    assert extract_standards("стальные 355") == []
    assert strip_standards("С355-5 ГОСТ 27772-2015") == "С355-5"
    # слово «ГОСТ» потеряно OCR: в наименовании профиля голый номер — ГОСТ,
    # в марке стали и размерах — нет
    bare = "Профулиу\nстальные\nгнутые\nзамкнутые\nпрямоцеольные\n30245-2003"
    assert extract_standards(bare) == []
    assert extract_standards(bare, bare=True) == ["ГОСТ 30245-2003"]
    assert strip_standards(bare, bare=True) == "Профулиу стальные гнутые замкнутые прямоцеольные"
    assert extract_standards("Уголки ГОСТ 8509-93", bare=True) == ["ГОСТ 8509-93"]
    assert extract_standards("160х160х5 С255-5 8510-86", bare=True) == ["ГОСТ 8510-86"]
    assert extract_standards("140х5 С255-5", bare=True) == []
    assert extract_standards("ТУ 14-1-5 и 36-72-82", bare=True) == ["ТУ 14-1-5"]


def test_cancel_stops_pipeline_between_stages(tmp_path):
    """Флаг отмены проверяется перед страницей/блоком/OCR: конвейер бросает
    Cancelled, а веб-сервер переводит задание в cancelled."""
    import pytest
    from ocrpdf.pipeline import Cancelled, Options, run
    from ocrpdf.webapp import request_cancel
    pdf = tmp_path / "one.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Спецификация", fontsize=10)
    doc.save(pdf)
    doc.close()
    opts = Options(dpi=120, ocr_backend="none", should_cancel=lambda: True)
    with pytest.raises(Cancelled):
        run(str(pdf), str(tmp_path / "out"), opts)
    # без флага тот же файл разбирается
    report = run(str(pdf), str(tmp_path / "out2"), Options(dpi=120, ocr_backend="none"))
    assert report["pages_processed"] == 1
    # отмена несуществующего задания
    assert request_cancel("0" * 32) == "unknown"


def test_glyph_template_size_is_capped():
    fonts = available_fonts()
    assert fonts, "нужен хотя бы один системный шрифт для шаблонов"
    font = fonts[0]
    assert _size_for(font, 5000.0, "cap") <= MAX_TEMPLATE_PX
    tpl = _templates(font, 100000, "1")
    assert tpl and tpl[0].h <= MAX_TEMPLATE_PX * 1.5


def test_element_names_are_canonicalised_from_drawing_italic():
    from ocrpdf.structure import element_name
    # растровый OCR по чертёжному курсиву -> словарное имя элемента
    assert element_name("ΦepMbl") == "Фермы"
    assert element_name("φepmbl") == "Фермы"
    assert element_name("5αAKU") == "Балки"
    assert element_name("CB93U") == "Связи"
    assert element_name("nodcmponunbuble фермы") == "Подстропильные фермы"
    assert element_name("Фермы nodcmponunbuble") == "Фермы подстропильные"
    assert element_name("Связи, pacnopku") == "Связи, распорки"
    assert element_name("Рамы nod лЮку дымоудаления") == "Рамы под люки дымоудаления"
    assert element_name("Балочные клетку") == "Балочные клетки"
    # опечатки OCR и переносы
    assert element_name("Траберсы") == "Траверсы"
    assert element_name("Надколонникиу") == "Надколонники"
    assert element_name("Надколон-\nник") == "Надколонник"
    # многострочные подписи после исправленного порядка строк
    assert element_name("Связи,\nраспорки") == "Связи, распорки"
    assert element_name("Колонны,\nбазы колонн") == "Колонны, базы колонн"
    # незнакомое, но нормальное слово не трогаем
    assert element_name("Косоуры") == "Косоуры"
    assert element_name("") == ""


def test_duplicate_canonical_elements_fall_back_to_raw():
    from ocrpdf.structure import Column, dedupe_elements
    cols = [Column(index=4, role="element_mass", title="Балки", element="Балки"),
            Column(index=5, role="element_mass", title="5αAKU", element="Балки"),
            Column(index=6, role="element_mass", title="Фермы", element="Фермы")]
    dedupe_elements(cols, {4: "Балки", 5: "5αAKU", 6: "Фермы"})
    assert [c.element for c in cols] == ["Балки", "5αAKU", "Фермы"]


def test_rotated_label_keeps_line_order():
    from ocrpdf.cell_reader import TextLine, _group_words
    # после поворота на 90°: строка 1 «Связи,» (короткая, отцентрована) сверху,
    # строка 2 «распорки» снизу и начинается левее
    w = [TextLine(text="распорки", bbox=(2, 20, 60, 36), direction=(1, 0)),
         TextLine(text="Связи,", bbox=(14, 2, 50, 18), direction=(1, 0))]
    lines = _group_words(w)
    assert [" ".join(x.text for x in L) for L in lines] == ["Связи,", "распорки"]
