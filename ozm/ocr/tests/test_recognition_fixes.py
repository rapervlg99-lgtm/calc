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


# ---- лист «01-П_02.08.2015-2-КМ1 лист 2» (2026-09-16): чертёжный курсив ISOCPEUR --------

def _rows_in_group(group_text, sizes):
    group = Cell(row=3, col=0, text=group_text, source="ocr", row_span=len(sizes))
    return [LogicalRow(row=3 + i, kind="data", cells={"profile_group": group,
            "profile_size": Cell(row=3 + i, col=2, text=size, source="ocr", alt_text=alt)})
            for i, (size, alt) in enumerate(sizes)]


def test_ibeam_series_digit_five_and_alt_engine():
    """«2051» — это 20Б1 («Б» прочитана пятёркой, высоты 205 не бывает), а не
    двутавр 205 с потерянной буквой; чтение второго движка с буквой серии — главнее."""
    from ocrpdf.normalizer import fix_profile_series
    rows = _rows_in_group("Двутавры стальные горячекатаные", [
        ("2051", "Т20Б1"), ("1651", "T1661"), ("3051", "3051"), ("301", "I30Ш1"), ("2551", ""),
        ("2011", ""), ("352", "")])
    fix_profile_series(rows)
    sizes = [r.cells["profile_size"] for r in rows]
    assert [s.text for s in sizes] == ["20Б1", "16Б1", "30Б1", "30Ш1", "25Б1", "2011", "352"]
    assert all(s.requires_review for s in sizes)
    assert sizes[0].candidates == [] and sizes[5].candidates == ["20Б1", "20Ш1", "20К1"]
    assert sizes[6].candidates == ["35Б2", "35Ш2", "35К2"]


def test_channel_series_digit_seven():
    """«227»/«167» в швеллерах — 22П/16П: «П» прочитана семёркой. Высота сверяется
    с ГОСТ 8240 («237» не трогаем), второй движок с буквой — главнее."""
    from ocrpdf.normalizer import fix_profile_series
    rows = _rows_in_group("Швеллеры стальные горячекатаные", [
        ("227", "[221"), ("167", "[16П"), ("237", ""), ("27", ""), ("407", "")])
    fix_profile_series(rows)
    assert [r.cells["profile_size"].text for r in rows] == ["22П", "16П", "237", "27", "40П"]
    assert rows[0].cells["profile_size"].requires_review is True
    assert any("вторым движком" in n for n in rows[1].cells["profile_size"].notes)


def test_sheet_dash_glyph_before_thickness():
    """«—t16», «—+20», «—14»: значок листа по ЕСКД перед толщиной. Перед «t»/«+»
    снимается сразу, одинокое число после тире — только в листовой группе."""
    from ocrpdf.normalizer import fix_sheet_thickness
    assert normalize_cell(Cell(row=1, col=2, text="-t16", source="ocr"), "profile_size").text == "t16"
    assert normalize_cell(Cell(row=1, col=2, text="-+20", source="ocr"), "profile_size").text == "t20"
    assert normalize_cell(Cell(row=1, col=2, text="—t8", source="ocr"), "profile_size").text == "t8"
    assert normalize_cell(Cell(row=1, col=2, text="-t16", source="text_layer"), "profile_size").text == "-t16"
    rows = _rows_in_group("Прокат листовой\nГОСТ 19903-74", [("-14", "-14"), ("-10", "-110"), ("-t9", "-19"), ("t8", "")])
    assert fix_sheet_thickness(rows) == 3
    sizes = [r.cells["profile_size"] for r in rows]
    assert [s.text for s in sizes] == ["t14", "t10", "t9", "t8"]
    # число после тире взято целиком — без пометки; «-110» → t10 — догадка, на проверку
    assert sizes[0].requires_review is False and sizes[1].requires_review is False
    assert sizes[2].requires_review is False
    rows3 = _rows_in_group("Прокат листовой", [("-110", ""), ("116", "")])
    assert fix_sheet_thickness(rows3) == 2
    assert [r.cells["profile_size"].text for r in rows3] == ["t10", "t16"]
    assert all(r.cells["profile_size"].requires_review for r in rows3)
    # вне листовой группы тире с числом не трогаем
    rows2 = _rows_in_group("Двутавры стальные", [("-14", "")])
    assert fix_sheet_thickness(rows2) == 0 and rows2[0].cells["profile_size"].text == "-14"


def test_expanded_metal_sheet_mark():
    """«NВ-506» / «HB-406» в листах — просечно-вытяжной лист ПВ."""
    from ocrpdf.normalizer import fix_profile_series
    rows = _rows_in_group("Листы стальные просечно-вытяжные\nТУ 36.26.11-5-89",
                          [("NВ-506", "ПВ-506"), ("HB-406", ""), ("ПВ-508", "")])
    assert fix_profile_series(rows) == 2
    assert [r.cells["profile_size"].text for r in rows] == ["ПВ-506", "ПВ-406", "ПВ-508"]


def test_profile_group_follows_sortament_standard():
    """Номер ГОСТ/ТУ читается надёжнее слов: он решает вид профиля, когда словарь
    подобрал не то («Трубы квадратные» при ГОСТ 10704) или подобрать нечего
    («Листы стальные» + ТУ 36.26.11 — просечно-вытяжные; короткое «Прокат листовой»)."""
    from ocrpdf.normalizer import group_by_standard
    def grp(text):
        return normalize_cell(Cell(row=1, col=0, text=text, source="ocr", confidence=0.9), "profile_group")
    c = grp("Трубы\nэлектросварные\nГОСТ 10704-91")
    assert c.text.startswith("Трубы стальные электросварные") and c.requires_review is False
    c = grp("Трубы квадратные\nГОСТ 10704-91")
    assert c.text == "Трубы стальные электросварные прямошовные\nГОСТ 10704-91" and c.requires_review is True
    assert any("расходится со стандартом" in n for n in c.notes)
    c = grp("Уголки стальные горячекатаные\nравнополочные\nГОСТ 8510-86")
    assert c.text == "Уголки стальные горячекатаные неравнополочные\nГОСТ 8510-86" and c.requires_review is True
    c = grp("Уголки стальные горячекатаные\nравнополочные\nГОСТ 8509-93")
    assert c.text == "Уголки стальные горячекатаные равнополочные\nГОСТ 8509-93" and c.requires_review is False
    # словарь ошибся в сторону «неравнополочные» (file-14), стандарт 8509 возвращает — с пометкой
    c = grp("Уголки стальные\nZОРАТЕК ОМ СНАВIС\nрайнополочные ГОСТ 8509-93")
    assert c.text == "Уголки стальные горячекатаные равнополочные\nГОСТ 8509-93" and c.requires_review is True
    # менее точное имя уточняется по стандарту без пометки (Estakada: «Прокат горячекатаный»)
    c = grp("листовой Прокат.\nгорячекатаный\nгост.\n19903-2015")
    assert c.text == "Прокат листовой горячекатаный\nГОСТ 19903-2015" and c.requires_review is False
    assert any("уточнено по стандарту" in n for n in c.notes)
    c = grp("Листы стальные |\nТУ 36.26.11-5-89")
    assert c.text == "Листы стальные просечно-вытяжные\nТУ 36.26.11-5-89"
    c = grp("[Прокат листовой |\nГОСТ 19903-74")
    assert c.text == "Прокат листовой горячекатаный\nГОСТ 19903-74"
    assert any("артефакт линовки перед наименованием" in n for n in c.notes)
    # общая группа ГОСТ 30245 согласна и с «квадратные», и с «прямоугольные»; размер сохраняется
    c = grp("Труба квадратная 120х120х6\nГОСТ 30245-2003")
    assert c.text == "Труба квадратная 120х120х6\nГОСТ 30245-2003"
    # два разных стандарта в одной ячейке — подсказки нет
    assert group_by_standard(["ГОСТ 8509-93", "ГОСТ 8510-86"]) is None
    assert group_by_standard(["ГОСТ Р 57837-2017"])[0].startswith("Двутавры")
    # без стандарта словарь работает как раньше
    assert grp("Швеллеры стальные горячекатаные").text == "Швеллеры стальные горячекатаные"
    # примечание к таблице ссылается на ГОСТ, но группой не является (file-4)
    note = ("Примечания:\n1. Окончательная масса металла подлежит уточнению при разработке КМД.\n"
            "2. Листовой прокат по ГОСТ 19903-2015, сталь по ГОСТ 27772-2015.")
    assert grp(note).text == note
    long_name = "Прокат листовой горячекатаный повышенной точности для ответственных сварных конструкций зданий и сооружений\nГОСТ 19903-2015"
    assert grp(long_name).text.startswith("Прокат листовой горячекатаный")


def test_steel_grade_five_as_s_and_junk_line():
    """«5245» — С245 («С» прочитана пятёркой); строка из одной буквы под маркой — артефакт."""
    c = normalize_cell(Cell(row=1, col=1, text="5245\nГОСТ 27772-88\nэ", source="ocr"), "steel_grade")
    assert c.text.startswith("С245") and "э" not in c.text and "ГОСТ 27772-88" in c.text
    # текстовый слой не трогаем
    c = normalize_cell(Cell(row=1, col=1, text="5245", source="text_layer"), "steel_grade")
    assert c.text == "5245"
    # «Сm20» — углеродистая Ст20
    assert normalize_cell(Cell(row=1, col=1, text="Cm20", source="ocr"), "steel_grade").text == "Ст20"
    assert normalize_cell(Cell(row=1, col=1, text="Ст3сп", source="ocr"), "steel_grade").text == "Ст3сп"


# ---- пять листов из Telegram (2026-09-18): растр из Word и вектор А1 ---------------------

def test_header_mass_unit_kg_and_conversion():
    """«Общая масса, кг» (растр читает «масса, Ке»): колонки масс получают единицу
    «кг», значения делятся на 1000, текст ячейки остаётся как на чертеже. Допуск
    арифметики считается по трём лишним знакам."""
    from ocrpdf.normalizer import apply_mass_unit
    from ocrpdf.structure import header_mass_unit
    from ocrpdf.validator import mass_decimals
    grid = {(0, 4): Cell(row=0, col=4, text="Масса металла по элементам конструкций, кг", source="ocr", col_span=2),
            (0, 8): Cell(row=0, col=8, text="масса,\nКе", source="ocr"),
            (3, 8): Cell(row=3, col=8, text="13634.00", source="ocr", value_kind="number", normalized_value=13634.0),
            (3, 4): Cell(row=3, col=4, text="8815", source="ocr", value_kind="number", normalized_value=8815.0)}
    assert header_mass_unit(grid, [0, 1], None, 9) == "кг"
    cols = [Column(index=4, role="element_mass", title="Колонны", element="Колонны", unit="кг"),
            Column(index=8, role="total_mass", title="Общая масса, т", unit="кг")]
    assert apply_mass_unit(grid, cols, [0, 1]) == 2
    assert grid[(3, 8)].normalized_value == 13.634 and grid[(3, 8)].text == "13634.00"
    assert grid[(3, 4)].normalized_value == 8.815
    assert any("переведена в т" in n for n in grid[(3, 8)].notes)
    row = LogicalRow(row=3, kind="data", cells={column_key(cols[0]): grid[(3, 4)], "total_mass": grid[(3, 8)]})
    assert mass_decimals([row], cols) == 5          # «13634.00» → два знака + три
    # тонны и смешанные подписи — единица по умолчанию
    grid_t = {(0, 8): Cell(row=0, col=8, text="Общая масса,\nт", source="ocr")}
    assert header_mass_unit(grid_t, [0], None, 9) == "т"
    # подписи противоречат друг другу (Obshchaga_KM): «кг?», решает порядок чисел
    from ocrpdf.normalizer import resolve_mass_unit
    grid_mix = {(0, 4): Cell(row=0, col=4, text="Масса металла по элементам, т", source="ocr"),
                (0, 8): Cell(row=0, col=8, text="масса, кг", source="ocr"),
                (3, 8): Cell(row=3, col=8, text="13634", source="ocr", value_kind="number", normalized_value=13634.0)}
    assert header_mass_unit(grid_mix, [0], None, 9) == "кг?"
    cols_q = [Column(index=4, role="element_mass", title="Колонны", element="Колонны", unit="кг?"),
              Column(index=8, role="total_mass", title="Общая масса, т", unit="кг?")]
    assert resolve_mass_unit(grid_mix, cols_q, [0]) == "кг" and cols_q[0].unit == "кг"
    grid_mix[(3, 8)].normalized_value = 136.34
    for c in cols_q:
        c.unit = "кг?"
    assert resolve_mass_unit(grid_mix, cols_q, [0]) == "т"
    cols_t = [Column(index=8, role="total_mass", title="Общая масса, т")]
    assert apply_mass_unit(grid, cols_t, [0]) == 0


def test_numbering_row_without_first_cell():
    """Строка нумерации граф «_ 2 3 4 5 6 7 8 9»: единица в первой клетке не
    прочиталась на растре. Пропуски внутри («1 2 3 4 _ 6») по-прежнему допустимы,
    а строка данных «2 … 4» без третьего номера — нет."""
    from ocrpdf.structure import detect_header_rows
    grid = {}
    for c, txt in enumerate(["", "2", "3", "4", "5", "6", "7", "8", "9"]):
        grid[(2, c)] = Cell(row=2, col=c, text=txt)
    assert detect_header_rows(grid, 10, 9) == ([0, 1, 2], 2)
    grid2 = {(2, 1): Cell(row=2, col=1, text="2"), (2, 3): Cell(row=2, col=3, text="4"),
             (2, 5): Cell(row=2, col=5, text="6")}
    assert detect_header_rows(grid2, 10, 9)[1] is None


def test_total_mass_role_fuzzy_and_before_area():
    """«Общая масса, т» правее блока масс получает роль и когда подпись прочитана
    «Maced, т», и когда за ней стоит «Площадь окрашиваемой поверхности»."""
    from ocrpdf.structure import _fuzzy_mass_title, skeletons
    assert _fuzzy_mass_title(skeletons("Maced, т")) is True
    assert _fuzzy_mass_title(skeletons("Оdwаа Масса, m")) is True
    assert _fuzzy_mass_title(skeletons("Прогоны")) is False
    assert _fuzzy_mass_title(skeletons("Площадь окрашиваемой поверхности, м2")) is False


def test_channel_bare_number_confirmed_by_alt_engine():
    """«[16П» прочитано «[16» → «16»; второй движок видел букву («c16n», «[ 16nl»),
    ставим П. Без подтверждения («|[2%П») голое число остаётся: для калькулятора
    «24» — допустимое обозначение швеллера."""
    from ocrpdf.normalizer import fix_profile_series
    rows = _rows_in_group("Швеллеры стальные горячекатаные", [("16", "c16n"), ("16", "[ 16nl"), ("24", "|[2%П"), ("6,5", "6,5П")])
    assert fix_profile_series(rows) == 3
    assert [r.cells["profile_size"].text for r in rows] == ["16П", "16П", "24", "6,5П"]


def test_ibeam_glued_glyph_one():
    """«I23Ш1» без пробела → «123Ш1»: высоты 123 нет, 23 есть — единица это значок."""
    from ocrpdf.normalizer import fix_profile_series
    rows = _rows_in_group("Двутавры стальные горячекатаные с параллельными гранями полок",
                          [("123Ш1", "123Ш1"), ("135Ш1", ""), ("100Б1", ""), ("120Б1", "")])
    fix_profile_series(rows)
    # 100Б1 и 120Б1 — настоящие высоты 100 и 120 (120 в сортаменте нет, но 20 есть → снимаем)
    assert [r.cells["profile_size"].text for r in rows] == ["23Ш1", "35Ш1", "100Б1", "20Б1"]


def test_split_integer_joined_only_with_alt_confirmation():
    """«4 72» в колонке масс: одна цифра слева — не потерянная запятая. Склейка
    только если второй движок дал «472»; при «872» ячейка остаётся спорным текстом."""
    c = normalize_cell(Cell(row=10, col=5, text="4 72", source="ocr", alt_text="472"), "element_mass")
    assert c.normalized_value == 472.0 and c.requires_review is True
    c = normalize_cell(Cell(row=13, col=8, text="4 12.00", source="ocr", alt_text="412.00"), "total_mass")
    assert c.normalized_value == 412.0
    c = normalize_cell(Cell(row=10, col=5, text="4 72", source="ocr", alt_text="872"), "element_mass")
    assert c.normalized_value is None and c.value_kind == "text"
    # «23857 49» — потерянная запятая, как раньше
    c = normalize_cell(Cell(row=10, col=5, text="23857 49", source="ocr", alt_text="2385749"), "element_mass")
    assert c.normalized_value == 23857.49
    # «9.» — разделитель без дробной части (так напечатано на KM_GARAZH)
    c = normalize_cell(Cell(row=4, col=4, text="9.", source="ocr", alt_text="9."), "element_mass")
    assert c.normalized_value == 9.0 and c.value_kind == "number"


def test_bent_profile_prefix():
    """«Гн.100х5» в гнутых замкнутых профилях: «Г» потеряна, «н» латиницей — «H.100x5»."""
    from ocrpdf.normalizer import fix_profile_series
    rows = _rows_in_group("Профили стальные гнутые замкнутые сварные квадратные и прямоугольные\nГОСТ 30245-2012",
                          [("Н.100х5", "|Гн100хо"), ("H160x5", ""), ("Гн.100х5", ""), ("100х5", "")])
    assert fix_profile_series(rows) == 2
    assert [r.cells["profile_size"].text for r in rows] == ["Гн.100х5", "Гн.160x5", "Гн.100х5", "100х5"]
    # профнастил «Н75-750-0,8» в группе гнутых профилей с гофрами — «Н» настоящая (file-37, file-14)
    rows2 = _rows_in_group("Профили стальные листовые гнутые с трапецеидальными гофрами\nГОСТ 24045-2016",
                           [("Н75-750-0,8", ""), ("H60-845-0,7", "")])
    assert fix_profile_series(rows2) == 0
    assert [r.cells["profile_size"].text for r in rows2] == ["Н75-750-0,8", "H60-845-0,7"]


def test_square_tube_glyph_junk_and_side_sanity():
    """Растр из Word («Рама для вентилятора»): «□120х5» → «/20х5», «□80х5» → «080х5»,
    «□100х5» → «700х5». Черта и ноль перед размером снимаются; сторона вне
    сортамента (700, 20) помечается — молча такие размеры в калькулятор не идут."""
    from ocrpdf.normalizer import fix_profile_series, fix_sheet_thickness
    rows = _rows_in_group("Профиль стальной гнутый замкнутый сварной квадратный\nГОСТ 30245-2012",
                          [("/20х5", "OS"), ("080х5", "[12"), ("060х5", ""), ("700х5", ""), ("140х5", "")])
    fix_profile_series(rows)
    sizes = [r.cells["profile_size"] for r in rows]
    assert [s.text for s in sizes] == ["20х5", "80х5", "60х5", "700х5", "140х5"]
    assert sizes[0].requires_review and sizes[3].requires_review        # 20 и 700 — не стороны ГОСТ 30245
    assert sizes[1].requires_review and not sizes[4].requires_review     # снятый ноль — на проверку, 140 — норма
    # «D40х40х4» (Estakada): латинская D вместо «□» снимается без пометки
    rows3 = _rows_in_group("Трубы стальные квадратные\nГОСТ 30245-2003", [("D40х40х4", ""), ("口 100х5", "")])
    fix_profile_series(rows3)
    assert [r.cells["profile_size"].text for r in rows3] == ["40х40х4", "100х5"]
    assert not any(r.cells["profile_size"].requires_review for r in rows3)
    assert any("не встречается" in n for n in sizes[3].notes)
    # «δ=4 мм» растром: «5=4ММ», «6=8 НМ», «d=10 мм» → t4, t8, t10 в листовой группе
    rows2 = _rows_in_group("Сталь листовая горячекатаная\nГОСТ 19903-2015", [("5=4ММ", "d=4 мы"), ("6=8 НМ", ""), ("d=10 мм", ""), ("t6", "")])
    assert fix_sheet_thickness(rows2) == 3
    assert [r.cells["profile_size"].text for r in rows2] == ["t4", "t8", "t10", "t6"]


# ---- скриншот в PDF из Word («Рама для вентилятора», 96 dpi) -----------------------------

def _page_with_image(px: int, page_pt: float = 400.0, rotate: int = 0):
    """Страница page_pt×page_pt pt с картинкой px×px, растянутой почти на весь лист."""
    import cv2
    import numpy as np
    doc = fitz.open()
    page = doc.new_page(width=page_pt, height=page_pt)
    img = np.full((px, px), 255, np.uint8)
    cv2.rectangle(img, (px // 8, px // 8), (px - px // 8, px - px // 8), 0, 1)
    cv2.putText(img, "12", (px // 3, px // 2), cv2.FONT_HERSHEY_SIMPLEX, px / 120.0, 0, 1)
    ok, png = cv2.imencode(".png", img)
    assert ok
    page.insert_image(fitz.Rect(10, 10, page_pt - 10, page_pt - 10), stream=png.tobytes())
    if rotate:
        page.set_rotation(rotate)
    return doc, page


def test_lowres_raster_is_upscaled_from_native_pixels():
    """Картинка 96 dpi на весь лист: рендер заменяется увеличенными исходными
    пикселями, заметка называет разрешение и кратность. Картинка 300 dpi и
    векторный лист — без изменений."""
    import numpy as np
    from ocrpdf.glyph_ocr import GlyphLayer, upscale_lowres_raster
    doc, page = _page_with_image(px=120)                     # 120 px на 380 pt ≈ 23 dpi
    layer = GlyphLayer(page, dpi=200)
    assert layer.lowres_note and "23 dpi" in layer.lowres_note and "120×120" in layer.lowres_note
    pix = page.get_pixmap(dpi=200, colorspace=fitz.csGRAY)
    plain = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
    assert layer.img.shape == plain.shape
    assert not np.array_equal(layer.img, plain)              # пиксели картинки пересчитаны
    # белое поле вне картинки не тронуто, чёрная рамка на месте
    assert layer.img[2, 2] == 255 and plain[2, 2] == 255
    z = 200 / 72.0
    y = int((10 + 380 / 8) * z)
    assert layer.img[y, int(200 * z)] < 128
    # картинка высокого разрешения — как отрендерил MuPDF
    doc2, page2 = _page_with_image(px=1600)                  # ≈ 300 dpi
    img2, note2 = upscale_lowres_raster(page2, plain.copy(), z)
    assert note2 == "" and np.array_equal(img2, plain)
    # повёрнутая страница — не трогаем
    doc3, page3 = _page_with_image(px=120, rotate=90)
    img3, note3 = upscale_lowres_raster(page3, plain.copy(), z)
    assert note3 == "" and np.array_equal(img3, plain)
    # векторный лист без картинок
    doc4 = fitz.open()
    page4 = doc4.new_page(width=400, height=400)
    page4.draw_line((10, 10), (390, 10))
    img4, note4 = upscale_lowres_raster(page4, plain.copy(), z)
    assert note4 == "" and np.array_equal(img4, plain)


def test_lowres_orientation_matches_render():
    """Исходная картинка в PDF может лежать перевёрнутой — ориентация подбирается
    по совпадению с рендером той же области."""
    import numpy as np
    from ocrpdf.glyph_ocr import _best_orientation
    native = np.full((40, 60), 255, np.uint8)
    native[5:15, 5:25] = 0                                    # чёрный блок в левом верхнем углу
    rendered = np.kron(native, np.ones((4, 4), np.uint8))     # рендер той же ориентации ×4
    assert np.array_equal(_best_orientation(native[::-1, ::-1].copy(), rendered), native)
    assert np.array_equal(_best_orientation(native[::-1, :].copy(), rendered), native)
    assert np.array_equal(_best_orientation(native.copy(), rendered), native)


def test_delta_thickness_units_tolerant():
    """«5=4 HH», «5=8 HM», «5=10 HX» — единицы «мм» растровый OCR читает как угодно."""
    from ocrpdf.normalizer import fix_sheet_thickness
    rows = _rows_in_group("Сталь листовая горячекатаная", [("5=4 HH", ""), ("5=8 HM", ""), ("5=10 HX", ""), ("0=6 MN", "")])
    assert fix_sheet_thickness(rows) == 4
    assert [r.cells["profile_size"].text for r in rows] == ["t4", "t8", "t10", "t6"]
