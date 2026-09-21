# -*- coding: utf-8 -*-
"""Сборка конвейера: PDF -> структурированные таблицы -> файлы.

Порядок:
    открыть PDF
    -> оценить страницу (векторная / растровая, состояние текстового слоя)
    -> починить кодировку текстового слоя
    -> найти линовку и блоки таблиц (вектор; при отсутствии — растр)
    -> прочитать ячейки (текстовый слой > векторные глифы > OCR)
    -> определить роли колонок по шапке
    -> нормализовать значения
    -> разбить блок на логические таблицы
    -> проверить арифметику
    -> выгрузить JSON / XLSX / CSV / debug PNG / отчёт
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Callable, Optional


from .pdfbackend import fitz
from . import cv_grid, exporter
from .cell_reader import CellReader, build_text_lines, ocr_region
from .fontfix import build_font_repairs, looks_broken
from .glyph_ocr import GlyphLayer
from .models import PageInfo, Table
from .ocr_backends import pick_backend
from .normalizer import (apply_mass_unit, fill_positions, fix_profile_series, fix_sheet_thickness,
                         resolve_mass_unit)
from .structure import (Column, LogicalRow, assign_roles, build_rows, classify_table,
                        detect_header_rows, find_titles, group_context,
                        normalize_grid, refine_structure, split_sections)
from .validator import (Tolerance, check_by_grade, check_grand_total, check_group_totals, mass_decimals,
                        check_row_sums, mark_failed_cells, summarize)
from .vector_grid import extract_rulings, find_table_blocks, is_drawing_grid, looks_stamp_block

# Алфавит распознавания по роли колонки: семантическое ограничение резко
# снижает число ошибок (в числовых колонках буквы вообще невозможны).
CHARSET_BY_ROLE = {
    "profile_group": "text",
    "steel_grade": "code",
    "profile_size": "code",
    "position": "numeric",
    "element_mass": "numeric",
    "total_mass": "numeric",
    "unknown": "text",
}

# Гибридный OCR (`hybrid`) читает область обоими движками сразу и помечает
# слова. Здесь решаем, чей вариант брать в колонке: словесные колонки — за
# Tesseract с `rus` (RapidOCR без кириллицы в словаре пишет «ИТОГО» как
# «NTOFO»), обозначения и числа — за RapidOCR (Tesseract их дробит и теряет).
# Марка стали («С255 по ГОСТ 27772-2021») — словесная, несмотря на цифры.
ENGINE_BY_ROLE = {
    "profile_group": "tesseract",
    "steel_grade": "tesseract",
    "profile_size": "rapidocr",
    "position": "rapidocr",
    # Числа по умолчанию берёт RapidOCR (см. `_resolve_engine`), но выбор идёт
    # по содержимому: если он принял запятую за пробел, а Tesseract запятую
    # сохранил — уступаем.
    "element_mass": "auto",
    "total_mass": "auto",
    # Роли назначаются по тексту шапки, а на листах КМ шапка сама приходит из
    # OCR с искажениями, и колонка нередко остаётся `unknown`. Для неё движок
    # выбирается по содержимому ячейки (см. `_resolve_engine`).
    "unknown": "auto",
}
# Движок для шапки и подписей: они всегда словесные.
ENGINE_TEXT = "tesseract"
# Движок пробника первых строк: там и словесная шапка, и служебная строка
# номеров, и первые строки данных — решается по содержимому каждой ячейки.
ENGINE_PROBE = "auto"


# Доля спорных ячеек, после которой блок считается нераспознанным.
UNREADABLE_SHARE = 0.6


def grade_table(table: Table) -> None:
    """Помечает блок, содержимое которого распознать не удалось.

    Нужно потому, что после исключения рамки листа из группировки в блоки
    попадают штамп и боковые графы («ИНВ. № ПОДЛ.», «ПОДПИСЬ И ДАТА»). Там
    текст повёрнут на 90 градусов и набран чертёжным курсивом, которые
    распознаватель глифов не поддерживает. Выдавать такой результат за данные
    нельзя, а молча выбрасывать блок — значит скрыть от пользователя, что на
    листе есть нераспознанная таблица.
    """
    if table.kind not in ("generic", "unreadable"):
        return
    filled = [c for c in table.cells if not c.is_empty]
    if not filled:
        table.kind = "unreadable"
        table.notes.append("в блоке не найдено ни одного значения")
        return
    flagged = sum(1 for c in filled if c.requires_review)
    if flagged / len(filled) >= UNREADABLE_SHARE:
        table.kind = "unreadable"
        w = table.bbox[2] - table.bbox[0]
        h = table.bbox[3] - table.bbox[1]
        reason = ("узкая графа листа: текст, вероятно, повёрнут на 90 градусов "
                  "(не поддерживается)") if (h > 3 * w or w > 8 * h) else \
                 ("не удалось распознать содержимое: возможен неподдерживаемый "
                  "шрифт (курсив, чертёжный) или растровое содержимое")
        table.notes.append(reason)


@dataclass
class PageResult:
    info: PageInfo
    blocks: list = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    columns: dict[int, list[Column]] = field(default_factory=dict)
    rows: dict[int, list[LogicalRow]] = field(default_factory=dict)


class Cancelled(Exception):
    """Обработка остановлена пользователем (кнопка «Остановить» в вебе)."""


@dataclass
class Options:
    dpi: int = 350
    ocr_backend: str = "none"
    low_conf: float = 0.62
    tolerance_base: float = 0.02
    tolerance_per_term: float = 0.006
    pages: str = ""            # "1", "1-3", "" = все
    all_glyphs: bool = False   # писать глифы для ВСЕХ ячеек, не только спорных
    # доля спорных ячеек, после которой блок перечитывается растровым OCR
    retry_ocr_share: float = 0.5
    # Кооперативная отмена: поток в Python не убить, поэтому конвейер сам
    # спрашивает флаг перед каждой страницей, блоком и вызовом OCR.
    should_cancel: Optional[Callable[[], bool]] = None


def check_cancel(opts: "Options") -> None:
    if opts.should_cancel is not None and opts.should_cancel():
        raise Cancelled("остановлено пользователем")


def parse_pages(spec: str, n: int) -> list[int]:
    if not spec:
        return list(range(n))
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a) - 1, int(b)))
        else:
            out.add(int(part) - 1)
    return sorted(i for i in out if 0 <= i < n)


def classify_page(page: fitz.Page, n_rulings: int, n_glyphs: int,
                  text: str) -> tuple[str, str]:
    """(вид содержимого, состояние текстового слоя)."""
    images = page.get_images(full=True)
    has_vector = n_rulings > 0 or n_glyphs > 0
    big_image = False
    for info in page.get_image_info():
        r = fitz.Rect(info["bbox"])
        if r.get_area() > 0.5 * abs(page.rect.get_area()):
            big_image = True
    if big_image and not has_vector:
        kind = "raster"
    elif big_image and has_vector:
        kind = "mixed"
    elif has_vector:
        kind = "vector"
    else:
        kind = "raster" if images else "empty"

    if not text.strip():
        layer = "absent"
    elif any(looks_broken(ln) for ln in text.splitlines()):
        # Построчно: одиночные «δ» в разных строках листа — не сбой кодировки,
        # а обозначения толщины; целиком по тексту страницы они складывались
        # в ложную метку broken_encoding.
        layer = "broken_encoding"
    else:
        layer = "ok"
    return kind, layer


def process_page(doc: fitz.Document, index: int, opts: Options,
                 table_index: int = 0, backend=None) -> tuple[PageResult, int]:
    """Разбирает одну страницу. `table_index` — уже занятый номер таблицы
    в документе (чтобы файлы table_N с разных страниц не затирали друг друга).
    Возвращает результат и новый занятый номер.
    """
    t_page = time.time()
    page = doc[index]
    repairs = build_font_repairs(doc, page)
    raw_text = page.get_text("text")

    h, v = extract_rulings(page)
    blocks = find_table_blocks(h, v, page_rect=page.rect)
    grid_source = "vector" if blocks else "none"

    # Дополнительно ищем таблицы ВНУТРИ крупных вставленных картинок. Условия
    # «векторных блоков нет» недостаточно: на листе может быть векторный штамп
    # и при этом растровая таблица — тогда растровая ветка не запускалась вовсе.
    raster_regions = cv_grid.large_image_rects(page)
    for region in raster_regions:
        covered = any(fitz.Rect(b.bbox).intersects(region)
                      and abs((fitz.Rect(b.bbox) & region).get_area())
                      >= 0.5 * abs(region.get_area()) for b in blocks)
        if covered:
            continue
        found = cv_grid.blocks_from_raster(page, clip=region)
        if found:
            blocks = list(blocks) + found
            grid_source = "vector+raster" if grid_source == "vector" else "raster"
    if not blocks:
        blocks = cv_grid.blocks_from_raster(page)
        grid_source = "raster"
    blocks.sort(key=lambda b: (round(b.bbox[1] / 20), b.bbox[0]))

    layer = GlyphLayer(page, dpi=opts.dpi)
    kind, layer_state = classify_page(page, len(h) + len(v), len(layer.comps), raw_text)
    info = PageInfo(index + 1, page.rect.width, page.rect.height, kind, layer_state,
                    n_ruling_lines=len(h) + len(v), n_vector_glyphs=len(layer.comps),
                    n_text_chars=len(raw_text))
    info.notes.append("grid source: %s" % grid_source)
    if layer.lowres_note:
        info.notes.append(layer.lowres_note)
    for name, rep in repairs.items():
        if rep.ok:
            info.notes.append("font %s: encoding repaired via %s %s"
                              % (name, rep.source, rep.reason))
        elif rep.reason and "no repair needed" not in rep.reason:
            info.notes.append("font %s: NOT repaired (%s)" % (name, rep.reason))

    text_lines = build_text_lines(page, repairs)
    if backend is None:
        backend = pick_backend(opts.ocr_backend)
    for warn in getattr(backend, "warnings", []) or []:
        info.notes.append("OCR (%s): %s" % (backend.name, warn))
    if backend.available:
        info.notes.append("растровый OCR: %s" % backend.name)
    reader = CellReader(page, text_lines, layer, backend if backend.available else None,
                        low_conf=opts.low_conf)

    result = PageResult(info, blocks)
    tol = Tolerance(opts.tolerance_base, opts.tolerance_per_term)
    parts_for_grand: list[tuple[list[LogicalRow], list[Column]]] = []
    pending: list[tuple[Table, list[Column], list[LogicalRow]]] = []

    for blk in blocks:
        check_cancel(opts)
        if is_drawing_grid(blk, page.rect):
            info.notes.append(
                "блок %s (%dx%d) похож на линовку чертежа — пропущен, "
                "чтобы не принять оси и размеры за спецификацию металлопроката"
                % ([round(v) for v in blk.bbox], blk.n_rows, blk.n_cols))
            continue
        if blk.n_rows < 3 or blk.n_cols < 3:
            continue

        def read_header(prefer_ocr: bool = False, _blk=blk):
            # Пробник читает первые пять строк, среди них — служебная строка
            # номеров колонок и первые строки данных. Раньше движок был жёстко
            # Tesseract: чертёжным курсивом он читал «1 2 3 … 10» как
            # «ий 2 3 4 2 6 … I», строка номеров не находилась, шапка и роли
            # терялись, а таблица оставалась generic (file-14). Теперь движок
            # выбирается по содержимому ячейки (`_resolve_engine`): слова —
            # Tesseract, числа — RapidOCR. Для негибридного OCR разницы нет.
            probe = {}
            for cb in _blk.cells:
                if cb.row <= 4:
                    probe[(cb.row, cb.col)] = reader.read(
                        cb.bbox, cb.row, cb.col, "text", cb.row_span, cb.col_span,
                        index + 1, prefer_ocr, ENGINE_PROBE)
            return probe

        def read_block(prefer_ocr: bool = False, probe=None, _blk=blk):
            """Читает все ячейки блока -> (сетка, роли колонок, строки шапки)."""
            if probe is None:
                probe = read_header(prefer_ocr)
            hdr, numbering = detect_header_rows(probe, _blk.n_rows, _blk.n_cols)
            columns = assign_roles(probe, hdr, numbering, _blk.n_cols, _blk)
            cells: dict[tuple[int, int], object] = {}
            for n_cell, cb in enumerate(_blk.cells):
                if n_cell % 40 == 0:
                    check_cancel(opts)
                role = columns[cb.col].role if cb.col < len(columns) else "unknown"
                cs = CHARSET_BY_ROLE.get(role, "text")
                if (cb.row, cb.col) in probe:
                    cell = probe[(cb.row, cb.col)]
                    # Пробник читает первые строки «текстом»: если строка
                    # оказалась данными (шапка короче пяти строк), число в ней
                    # оставалось с буквами-двойниками — «0,В2» вместо «0,82»,
                    # «tВ» вместо «t8». Перечитываем алфавитом и движком роли.
                    if (cb.row not in hdr and cb.row != numbering and cs != "text"
                            and cell.source != "text_layer"):
                        cell = reader.read(cb.bbox, cb.row, cb.col, cs,
                                           cb.row_span, cb.col_span, index + 1,
                                           prefer_ocr, ENGINE_BY_ROLE.get(role, ENGINE_TEXT))
                else:
                    cell = reader.read(cb.bbox, cb.row, cb.col, cs,
                                       cb.row_span, cb.col_span, index + 1, prefer_ocr,
                                       ENGINE_BY_ROLE.get(role, ENGINE_TEXT))
                for rr in range(cb.row, cb.row + cb.row_span):
                    for cc in range(cb.col, cb.col + cb.col_span):
                        cells[(rr, cc)] = cell
            return cells, columns, hdr

        def flagged_share(cells) -> float:
            uniq = {id(c): c for c in cells.values()}.values()
            filled = [c for c in uniq if not c.is_empty]
            if not filled:
                return 1.0
            return sum(1 for c in filled if c.requires_review) / len(filled)

        def apply_ocr():
            check_cancel(opts)
            words = ocr_region(layer, backend, blk.bbox)
            if not words:
                return None
            tess = getattr(backend, "_tess", backend)
            slant = float(getattr(tess, "last_slant_deg", 0.0) or 0.0)
            if abs(slant) >= float(getattr(tess, "MIN_SLANT_DEG", 7.0)):
                info.notes.append("блок %s: наклон письма %.0f°, полосы для Tesseract выпрямлены"
                                  % ([round(v) for v in blk.bbox], slant))
            before = len(reader.ocr_words)
            reader.ocr_words.extend(words)
            grid2, cols2, hdr2 = read_block(prefer_ocr=True)
            return before, grid2, cols2, hdr2, flagged_share(grid2)

        # Чертёжный шрифт на шапке сразу даёт кашу. Тогда не читаем глифами
        # ещё 300 ячеек тела (на file-4 это минуты), а сразу OCR.
        # Узкий штамп гибридом не кормим: он всё равно нечитаемый.
        stamp = looks_stamp_block(blk)
        probe = read_header()
        share_probe = flagged_share(probe)
        box = [round(v) for v in blk.bbox]
        if stamp:
            grid, cols, header_rows = read_block(probe=probe)
            if backend.available and share_probe >= opts.retry_ocr_share:
                info.notes.append(
                    "блок %s: узкая графа/штамп — OCR пропущен" % box)
        elif backend.available and share_probe >= opts.retry_ocr_share:
            got = apply_ocr()
            if got and got[4] < opts.retry_ocr_share:
                _before, grid, cols, header_rows, share2 = got
                info.notes.append(
                    "блок %s: шапка спорная (%.0f%%), OCR (%s) дал %.0f%% — "
                    "глифы тела не читали"
                    % (box, 100 * share_probe, backend.name, 100 * share2))
            else:
                # OCR тоже спорен (или пуст) — раньше он брался безоговорочно,
                # и числа, которые OCR не увидел, пропадали. Теперь читаем
                # глифами и оставляем тот вариант, где спорных меньше.
                grid, cols, header_rows = read_block(probe=probe)
                share = flagged_share(grid)
                if got:
                    before, grid2, cols2, hdr2, share2 = got
                    take_ocr = share2 < share
                    info.notes.append(
                        "блок %s: шапка спорная (%.0f%%), OCR (%s) дал %.0f%%, "
                        "глифы %.0f%% — %s"
                        % (box, 100 * share_probe, backend.name, 100 * share2,
                           100 * share, "взят OCR" if take_ocr else "оставлено векторное"))
                    if take_ocr:
                        grid, cols, header_rows = grid2, cols2, hdr2
                    else:
                        del reader.ocr_words[before:]
        else:
            grid, cols, header_rows = read_block(probe=probe)
            share = flagged_share(grid)
            if share >= opts.retry_ocr_share and backend.available:
                got = apply_ocr()
                if got:
                    before, grid2, cols2, hdr2, share2 = got
                    info.notes.append(
                        "блок %s: векторное чтение спорно (%.0f%%), OCR (%s) "
                        "дал %.0f%% — %s"
                        % (box, 100 * share, backend.name, 100 * share2,
                           "взят OCR" if share2 < share else "оставлено векторное"))
                    if share2 < share:
                        grid, cols, header_rows = grid2, cols2, hdr2
                    else:
                        del reader.ocr_words[before:]

        # Шапка по ПОЛНОЙ сетке: probe не заполняет merged-ячейки, и на
        # file-4 служебная строка «1 2 3 4  6» не попадала в шапку.
        header_rows, cols = refine_structure(grid, blk.n_rows, blk.n_cols, blk)

        # Нормализация ДО сборки строк: разбор merged-ячейки с несколькими
        # номерами позиций опирается на уже разобранные значения.
        normalize_grid(grid, cols, header_rows)
        # «Общая масса, кг»: числа делим на 1000, чтобы в калькулятор ушли тонны;
        # при противоречивых подписях шапки единицу решает порядок чисел
        resolve_mass_unit(grid, cols, header_rows)
        kg_cells = apply_mass_unit(grid, cols, header_rows)
        rows = build_rows(grid, cols, header_rows, blk.n_rows)
        group_context(rows)
        # «116» / «10» в группе листов — это t16 / t10: у чертёжного «t» OCR теряет
        # или превращает в единицу перекладину. Контекст группы известен только здесь.
        fix_sheet_thickness(rows)
        # «3061» в двутаврах — это 30Б1, «1140х90х8» в уголках — L140х90х8:
        # RapidOCR без кириллицы. Вид группы известен только здесь.
        fix_profile_series(rows)
        # «m», «(-» в графе № п.п. — номер восстанавливается по соседним строкам
        fill_positions(rows)

        def _read_strip(bbox, _reader=reader, _page=index + 1):
            return _reader.read(bbox, -1, -1, "text", 1, 1, _page,
                                ocr_engine=ENGINE_TEXT).text

        title, part = find_titles(text_lines, blk.bbox, read_strip=_read_strip)
        table_kind = classify_table(cols)
        sections = split_sections(rows) if table_kind == "spec_main" \
            else [("generic", rows)]
        for sec_kind, sec_rows in sections:
            table_index += 1
            uniq: list = []
            seen: set[int] = set()
            for row in sec_rows:
                for cell in row.cells.values():
                    if id(cell) not in seen:
                        seen.add(id(cell))
                        uniq.append(cell)
            # Шапку кладём в таблицу и для generic: без неё сетка теряет
            # заголовки колонок и выгрузка «как на чертеже» неполна.
            if sec_kind in ("spec_main", "generic"):
                for r in header_rows:
                    for c in range(blk.n_cols):
                        cell = grid.get((r, c))
                        if cell is not None and id(cell) not in seen:
                            seen.add(id(cell))
                            uniq.append(cell)
            y0 = min((r.cells and min(c.bbox[1] for c in r.cells.values())) or blk.bbox[1]
                     for r in sec_rows) if sec_rows else blk.bbox[1]
            y1 = max((r.cells and max(c.bbox[3] for c in r.cells.values())) or blk.bbox[3]
                     for r in sec_rows) if sec_rows else blk.bbox[3]
            if sec_kind == "spec_main":
                sec_title = title or "Спецификация металлопроката"
            elif sec_kind == "mass_by_grade":
                sec_title = "В том числе по маркам или наименованиям"
            else:
                sec_title = title or "Таблица"
            table = Table(
                index=table_index,
                title=sec_title,
                kind=sec_kind, page=index + 1,
                bbox=(blk.bbox[0], min(y0, blk.bbox[1] if sec_kind == "spec_main" else y0),
                      blk.bbox[2], y1),
                n_rows=blk.n_rows, n_cols=blk.n_cols,
                cells=uniq,
                header_rows=header_rows if sec_kind == "spec_main" else [],
            )
            # пометка части относится только к самой спецификации
            if part and sec_kind == "spec_main":
                table.part = part
            if kg_cells and sec_kind != "generic":
                table.notes.append("массы на листе подписаны в кг — в результате переведены в т (%d ячеек)" % kg_cells)
            elif sec_kind == "spec_main" and not kg_cells:
                big = [r.cells["total_mass"].normalized_value for r in sec_rows
                       if "total_mass" in r.cells and isinstance(r.cells["total_mass"].normalized_value, (int, float))]
                if big and max(big) >= 2000:
                    # спецификация металлопроката на 2000+ т — редкость, а вот
                    # килограммы без единицы в шапке встречаются
                    table.notes.append("общая масса %.0f — возможно, массы на листе в кг, а единица в шапке "
                                       "не прочиталась; проверьте перед импортом" % max(big))
            # Арифметику проверяем только там, где известен смысл колонок.
            # допуск — под точность чисел на этом листе (одна десятая или сотые)
            sec_tol = tol.for_decimals(mass_decimals(sec_rows, cols))
            if sec_kind != "generic":
                table.checks = check_row_sums(sec_rows, cols, sec_tol)
            if sec_kind == "spec_main":
                table.checks += check_group_totals(sec_rows, cols, sec_tol)
                parts_for_grand.append((sec_rows, cols))
            pending.append((table, cols, sec_rows))

    # общий итог считается по ВСЕМ частям листа («Начало» + «Окончание»)
    grand_tol = tol
    if parts_for_grand:
        grand_tol = tol.for_decimals(min(mass_decimals(r, c) for r, c in parts_for_grand))
    grand_checks = check_grand_total(parts_for_grand, grand_tol)
    grand_total = next((c.expected for c in grand_checks
                        if c.column == "total_mass" and c.expected is not None),
                       None)
    for table, cols, rows in pending:
        if any(r.kind == "grand_total" for r in rows):
            table.checks += grand_checks
        if table.kind == "mass_by_grade":
            table.checks += check_by_grade(rows, cols, grand_total, grand_tol)
        mark_failed_cells(table)
        grade_table(table)
        result.tables.append(table)
        result.columns[table.index] = cols
        result.rows[table.index] = rows
    # ссылка «продолжение таблицы»
    mains = [t for t in result.tables if t.kind == "spec_main"]
    for prev, cur in zip(mains, mains[1:]):
        cur.continues_table = prev.index
    if getattr(layer, "_calibrated", False) and layer.variants:
        info.notes.append("glyph templates: " + ", ".join(
            "%s@%d" % (os.path.basename(x.font), x.size) for x in layer.variants[:6]))
    info.notes.append("время страницы: %.1f с" % (time.time() - t_page))
    return result, table_index


def run(pdf_path: str, out_dir: str, opts: Options | None = None) -> dict:
    opts = opts or Options()
    os.makedirs(out_dir, exist_ok=True)
    started = time.time()
    doc = fitz.open(pdf_path)
    indices = parse_pages(opts.pages, doc.page_count)

    report = {
        "input": os.path.abspath(pdf_path),
        "output_dir": os.path.abspath(out_dir),
        "pages_in_document": doc.page_count,
        "pages_processed": len(indices),
        "tables_found": 0,
        "cells_total": 0,
        "cells_non_empty": 0,
        "cells_low_confidence": 0,
        "cells_by_source": {},
        "tables_unreadable": 0,
        "table_quality": [],
        "arithmetic_checks": {"passed": 0, "failed": 0, "skipped": 0},
        "failed_checks": [],
        "pages": [],
        "files": [],
        "warnings": [],
    }
    files: list[str] = []
    table_index = 0
    prev_main: int | None = None
    backend = pick_backend(opts.ocr_backend)

    for idx in indices:
        check_cancel(opts)
        res, table_index = process_page(doc, idx, opts, table_index, backend)
        # «Начало» на стр. 1 и «Окончание» на стр. 2 — одна таблица, разнесённая
        # по листам. Внутри страницы ссылка уже проставлена; здесь — между ними.
        for t in res.tables:
            if t.kind != "spec_main":
                continue
            if t.continues_table is None and prev_main is not None:
                t.continues_table = prev_main
            prev_main = t.index
        report["pages"].append({
            **{k: v for k, v in res.info.__dict__.items()},
            "tables": [t.index for t in res.tables],
        })
        for table in res.tables:
            cols = res.columns[table.index]
            rows = res.rows[table.index]
            report["tables_found"] += 1
            for cell in table.cells:
                report["cells_total"] += 1
                if not cell.is_empty:
                    report["cells_non_empty"] += 1
                    report["cells_by_source"][cell.source] = \
                        report["cells_by_source"].get(cell.source, 0) + 1
                if cell.requires_review:
                    report["cells_low_confidence"] += 1
            filled = [c for c in table.cells if not c.is_empty]
            flagged = sum(1 for c in filled if c.requires_review)
            if table.kind == "unreadable":
                report["tables_unreadable"] += 1
            report["table_quality"].append({
                "table": table.index, "kind": table.kind, "title": table.title,
                "page": table.page, "grid": "%dx%d" % (table.n_rows, table.n_cols),
                "cells_non_empty": len(filled), "cells_flagged": flagged,
                "notes": table.notes,
            })
            stats = summarize(table.checks)
            for key in ("passed", "failed", "skipped"):
                report["arithmetic_checks"][key] += stats.get(key, 0)
            for chk in table.checks:
                if chk.status == "failed":
                    report["failed_checks"].append({
                        "table": table.index, "row": chk.row, "kind": chk.kind,
                        "expected": chk.expected, "calculated": chk.calculated,
                        "delta": chk.delta, "tolerance": chk.tolerance,
                        "reason": chk.reason,
                    })
            base = os.path.join(out_dir, "table_%d" % table.index)
            payload = exporter.table_to_dict(table, cols, rows,
                                             all_glyphs=opts.all_glyphs)
            payload["document"] = {"filename": os.path.basename(pdf_path),
                                   "page": table.page}
            exporter.write_json(base + ".json", payload)
            exporter.write_xlsx(base + ".xlsx", table, cols, rows)
            exporter.write_csv(base + ".csv", table)
            files += [base + ".json", base + ".xlsx", base + ".csv"]
        dbg = os.path.join(out_dir, "page_%d_debug.png" % (idx + 1))
        exporter.write_debug_png(dbg, doc[idx], res.blocks, res.tables)
        files.append(dbg)

    report["elapsed_sec"] = round(time.time() - started, 2)
    report["files"] = [os.path.basename(f) for f in files]
    exporter.write_report(os.path.join(out_dir, "processing_report.json"), report)
    doc.close()
    return report
