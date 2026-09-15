# -*- coding: utf-8 -*-
"""Интеграционный тест на реальном листе КР.

Эталонные значения сверены с чертежом ГЛАЗАМИ. Тест защищает от регрессий в
распознавании: любая правка алгоритма, ломающая эти значения, будет видна.

Путь к PDF задаётся переменной окружения OCRPDF_SAMPLE либо ищется рядом с
проектом. Если файла нет — тест пропускается.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ocrpdf.pipeline import Options, run

SAMPLE_CANDIDATES = [
    os.environ.get("OCRPDF_SAMPLE", ""),
    os.path.expanduser(r"~\Desktop\4_PIR2815_25_KR-37 (1)-1.pdf"),
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "samples", "4_PIR2815_25_KR-37 (1)-1.pdf"),
]
SAMPLE = next((p for p in SAMPLE_CANDIDATES if p and os.path.isfile(p)), None)

pytestmark = pytest.mark.skipif(SAMPLE is None,
                                reason="нет тестового PDF (задайте OCRPDF_SAMPLE)")


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    out = tmp_path_factory.mktemp("result")
    report = run(SAMPLE, str(out), Options(dpi=350))
    tables = {}
    for i in range(1, report["tables_found"] + 1):
        with open(os.path.join(str(out), "table_%d.json" % i), encoding="utf-8") as fh:
            tables[i] = json.load(fh)
    return report, tables, str(out)


def test_page_is_recognised_as_vector_with_broken_text_layer(result):
    report, _, _ = result
    page = report["pages"][0]
    assert page["content_kind"] == "vector"
    assert page["text_layer"] == "broken_encoding"
    assert page["n_ruling_lines"] > 100
    assert page["n_vector_glyphs"] > 3000


def test_font_encoding_is_repaired(result):
    report, _, _ = result
    notes = " ".join(report["pages"][0]["notes"])
    assert "ArialMT: encoding repaired" in notes
    assert "NOT repaired" not in notes


def test_three_logical_tables(result):
    """Три содержательные таблицы плюс штамп и боковая графа листа.

    Штамп и графы «ИНВ. № ПОДЛ.» / «ПОДПИСЬ И ДАТА» — тоже разлинованные блоки.
    Они распознаются плохо (повёрнутый текст, чертёжный курсив) и обязаны быть
    помечены `unreadable`, а не выданы за данные.
    """
    _, tables, _ = result
    assert tables[1]["kind"] == "spec_main" and tables[1]["part"] == "начало"
    assert tables[2]["kind"] == "spec_main" and tables[2]["part"] == "окончание"
    assert tables[2]["continues_table"] == 1
    assert tables[3]["kind"] == "mass_by_grade"
    extra = [t for i, t in tables.items() if i > 3]
    assert all(t["kind"] == "unreadable" for t in extra),         [t["kind"] for t in extra]


def test_report_grades_every_table(result):
    report, tables, _ = result
    quality = {q["table"]: q for q in report["table_quality"]}
    assert set(quality) == set(tables)
    assert quality[1]["kind"] == "spec_main"
    assert quality[1]["cells_flagged"] < 0.1 * quality[1]["cells_non_empty"]
    assert report["tables_unreadable"] == sum(
        1 for q in quality.values() if q["kind"] == "unreadable")


def test_grid_geometry(result):
    _, tables, _ = result
    for i in (1, 2):
        assert tables[i]["n_cols"] == 14, "14 колонок по служебной строке листа"
    letters = [c["letter"] for c in tables[1]["columns"]]
    assert letters[:4] == ["1", "2", "3", "4"]


def test_column_roles_and_element_names(result):
    _, tables, _ = result
    roles = [c["role"] for c in tables[1]["columns"]]
    assert roles[:4] == ["profile_group", "steel_grade", "profile_size", "position"]
    assert roles[13] == "total_mass"
    assert roles[4:13] == ["element_mass"] * 9
    elements = [c["element"] for c in tables[1]["columns"] if c["role"] == "element_mass"]
    assert elements[0] == "Фермы"
    assert elements[1] == "Надколонник"
    assert elements[2] == "Распорки по колоннам"
    assert elements[8] == "Профнастил покрытия"


def _row_by_position(table, position):
    for row in table["rows"]:
        if row["position"] == position:
            return row
    raise AssertionError("нет строки с позицией %s" % position)


# (позиция, размер профиля, общая масса) — сверено с чертежом
EXPECTED = [
    (1, "Гн.□160х6", 13.04), (2, "Гн.□160х5", 9.6), (3, "Гн.□120х5", 3.1),
    (4, "Гн.□100х4,5", 3.6), (7, "Гн.□80х5", 0.55), (8, "Гн.□100х5", 16.6),
    (11, "Гн.□100х4,5", 16.8), (12, "Гн.□100х5", 2.9), (14, "Гн.□140х60х6", 6.3),
    (19, "35К1", 3.44), (22, "35Б1", 0.1), (30, "16П", 0.02), (31, "20П", 0.61),
    (33, "24П", 4.0), (37, "L 100х7", 0.26),
]


@pytest.mark.parametrize("position,size,total", EXPECTED)
def test_data_rows_of_first_part(result, position, size, total):
    _, tables, _ = result
    row = _row_by_position(tables[1], position)
    assert row["profile_size"] == size
    assert row["total_mass_t"] == pytest.approx(total)


def test_totals_of_first_part(result):
    _, tables, _ = result
    assert _row_by_position(tables[1], 6)["row_kind"] == "group_total"
    assert _row_by_position(tables[1], 6)["total_mass_t"] == pytest.approx(29.34)
    assert _row_by_position(tables[1], 18)["row_kind"] == "profile_total"
    assert _row_by_position(tables[1], 18)["total_mass_t"] == pytest.approx(75.84)


def test_merged_position_cell_is_expanded(result):
    """Строки поз. 26 и 27 на листе не разделены линией."""
    _, tables, _ = result
    r26 = _row_by_position(tables[1], 26)
    r27 = _row_by_position(tables[1], 27)
    assert r26["total_mass_t"] == pytest.approx(8.5)
    assert any("not separated by a ruling line" in n for n in r26["notes"])
    # значение не дублируется во вторую позицию, иначе итоги удвоятся
    assert r27["total_mass_t"] is None


def test_empty_cell_differs_from_zero(result):
    _, tables, _ = result
    row = _row_by_position(tables[1], 1)
    element = row["elements"]["Надколонник"]
    assert element["value_kind"] == "empty"
    assert element["normalized_value"] is None


def test_steel_grades_and_standards(result):
    _, tables, _ = result
    row = _row_by_position(tables[1], 1)
    assert row["steel_grade"] == "С355-5"
    assert row["steel_grade_standards"] == ["ГОСТ 27772-2015"]
    rails = _row_by_position(tables[1], 26)
    assert rails["steel_grade"] == "Сталь марки 63"
    assert rails["profile_size"].startswith("Крановый рельс")


def test_second_part_sheet_thicknesses(result):
    _, tables, _ = result
    for position, size, total in [(42, "t6", 0.23), (43, "t8", 0.97),
                                  (45, "t12", 6.88), (46, "t14", 9.15),
                                  (70, "Н114-750-0,9", 37.91)]:
        row = _row_by_position(tables[2], position)
        assert row["profile_size"] == size
        assert row["total_mass_t"] == pytest.approx(total)


def test_grand_total_row(result):
    _, tables, _ = result
    grand = [r for r in tables[2]["rows"] if r["row_kind"] == "grand_total"]
    assert len(grand) == 1
    assert grand[0]["total_mass_t"] == pytest.approx(164.96)
    assert grand[0]["elements"]["Фермы"]["normalized_value"] == pytest.approx(35.86)


def test_mass_by_grade_table(result):
    _, tables, _ = result
    grades = {r["profile_group"]: r["total_mass_t"] for r in tables[3]["rows"]}
    assert grades["С245-4"] == pytest.approx(42.19)
    assert grades["С255-4"] == pytest.approx(20.57)
    assert grades["С345-5"] == pytest.approx(21.77)
    assert grades["С355-5"] == pytest.approx(30.49)
    assert grades["С255Б"] == pytest.approx(0.1)
    assert grades["С345Б"] == pytest.approx(3.44)
    assert grades["Сталь марки 63"] == pytest.approx(8.5)
    assert grades["Сталь марки 250"] == pytest.approx(37.91)
    by_grade = [c for c in tables[3]["checks"] if c["kind"] == "by_grade_total"]
    assert by_grade and by_grade[0]["status"] == "ok"


def test_arithmetic_mostly_passes_and_finds_the_drawing_error(result):
    """В самом чертеже поз. 32 «Итого» = 4,63 при 0,02 + 0,61 = 0,63.

    Это ошибка ИСХОДНОГО документа, а не распознавания. Проверка обязана её
    найти, а прочие 140+ проверок — пройти.
    """
    report, _, _ = result
    ac = report["arithmetic_checks"]
    assert ac["passed"] > 130
    assert ac["failed"] == 3
    rows = {f["row"] for f in report["failed_checks"]}
    assert rows == {34, 38}
    row_sum = [f for f in report["failed_checks"] if f["kind"] == "row_sum"][0]
    assert row_sum["expected"] == pytest.approx(4.63)
    assert row_sum["calculated"] == pytest.approx(0.63)


def test_values_carry_coordinates_and_source(result):
    _, tables, _ = result
    row = _row_by_position(tables[1], 1)
    cell = row["elements"]["Фермы"]
    assert cell["normalized_value"] == pytest.approx(13.04)
    assert cell["source"] == "vector_glyph"
    assert len(cell["bbox"]) == 4 and cell["bbox"][2] > cell["bbox"][0]
    assert cell["page"] == 1
    positions = row["source_cells"]["position"]
    assert positions["source"] == "text_layer"


def test_outputs_written(result):
    _, _, out = result
    for name in ("page_1_debug.png", "processing_report.json",
                 "table_1.json", "table_1.xlsx", "table_1.csv"):
        path = os.path.join(out, name)
        assert os.path.isfile(path) and os.path.getsize(path) > 0
