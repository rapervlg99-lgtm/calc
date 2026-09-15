# -*- coding: utf-8 -*-
"""Геометрическое распознавание таблиц по ВЕКТОРНОЙ графике PDF.

Почему так, а не Hough/морфология по растру
-------------------------------------------
В проектных PDF из AutoCAD/Revit линовка таблицы — это настоящие векторные
объекты (`l`-сегменты и тонкие залитые `re`). Их координаты известны точно,
поэтому:
  * не нужен подбор порогов бинаризации и длины линии;
  * тонкие линии (0.6 pt) не теряются;
  * merged cells восстанавливаются строго — по ОТСУТСТВИЮ разделителя
    на конкретном участке, а не по эвристике «пустая ячейка справа».

`ocrpdf.cv_grid` остаётся резервом для страниц-сканов.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .pdfbackend import fitz, map_drawing_arrays, page_drawings


@dataclass
class Ruling:
    """Отрезок линовки: const — фиксированная координата, [a, b] — протяжённость."""
    const: float
    a: float
    b: float
    width: float = 0.0


@dataclass
class CellBox:
    """Логическая ячейка сетки (после склейки merged-областей)."""
    row: int
    col: int
    row_span: int
    col_span: int
    bbox: tuple[float, float, float, float]


@dataclass
class TableBlock:
    """Прямоугольный блок линовки: сетка разделителей + логические ячейки."""
    bbox: tuple[float, float, float, float]
    xs: list[float] = field(default_factory=list)      # x-разделители, len = n_cols + 1
    ys: list[float] = field(default_factory=list)      # y-разделители, len = n_rows + 1
    cells: list[CellBox] = field(default_factory=list)
    n_rows: int = 0
    n_cols: int = 0

    def cell_at(self, r: int, c: int) -> CellBox | None:
        for cb in self.cells:
            if cb.row <= r < cb.row + cb.row_span and cb.col <= c < cb.col + cb.col_span:
                return cb
        return None


# --------------------------------------------------------------------------- #
#  1. извлечение линовки
# --------------------------------------------------------------------------- #
def extract_rulings(page: fitz.Page, min_len: float = 8.0, tol: float = 0.6,
                    max_thickness: float = 3.5) -> tuple[list[Ruling], list[Ruling]]:
    """Возвращает (горизонтальные, вертикальные) линии, склеенные по коллинеарности.

    Координаты приводятся к `page.rect`: у листов с `/Rotate` 90/270
    `get_drawings()` отдаёт mediabox, и без перевода сетка встаёт боком.
    Перевод делается одной матричной операцией на все точки страницы
    (`map_drawing_arrays`), а не по точке через `fitz.Point`; порядок обхода
    примитивов сохранён, числа те же.
    """
    raw_h: list[Ruling] = []
    raw_v: list[Ruling] = []

    def add(kind: str, const: float, a: float, b: float, w: float) -> None:
        if b - a >= min_len:
            (raw_h if kind == "h" else raw_v).append(Ruling(const, a, b, w))

    lines: list[tuple[float, float, float, float, float]] = []       # x1, y1, x2, y2, w
    rects: list[tuple[float, float, float, float, float, bool]] = []  # углы, w, без заливки
    order: list[tuple[int, int]] = []
    for d in page_drawings(page):
        w = float(d.get("width") or 0.0)
        nofill = d.get("fill") is None
        for it in d["items"]:
            if it[0] == "l":
                order.append((0, len(lines)))
                lines.append((it[1].x, it[1].y, it[2].x, it[2].y, w))
            elif it[0] in ("re", "qu"):
                raw = fitz.Rect(it[1]) if it[0] == "re" else fitz.Quad(it[1]).rect
                order.append((1, len(rects)))
                rects.append((raw.x0, raw.y0, raw.x1, raw.y1, w, nofill))

    L = np.asarray([ln[:4] for ln in lines], dtype=np.float64).reshape(-1, 4)
    lx1, ly1 = map_drawing_arrays(page, L[:, 0], L[:, 1])
    lx2, ly2 = map_drawing_arrays(page, L[:, 2], L[:, 3])
    lx1, ly1, lx2, ly2 = lx1.tolist(), ly1.tolist(), lx2.tolist(), ly2.tolist()

    # get_drawings() — mediabox; после /Rotate углы надо перенести в page.rect,
    # иначе тонкий прямоугольник «ложится на бок».
    R = np.asarray([rc[:4] for rc in rects], dtype=np.float64).reshape(-1, 4)
    rax, ray = map_drawing_arrays(page, R[:, 0], R[:, 1])
    rbx, rby = map_drawing_arrays(page, R[:, 2], R[:, 3])
    rx0, ry0 = np.minimum(rax, rbx).tolist(), np.minimum(ray, rby).tolist()
    rx1, ry1 = np.maximum(rax, rbx).tolist(), np.maximum(ray, rby).tolist()

    for kind, i in order:
        if kind == 0:
            x1, y1, x2, y2, w = lx1[i], ly1[i], lx2[i], ly2[i], lines[i][4]
            dx, dy = abs(x2 - x1), abs(y2 - y1)
            if dy <= 0.2 and dx > dy:
                add("h", (y1 + y2) / 2, min(x1, x2), max(x1, x2), w)
            elif dx <= 0.2 and dy > dx:
                add("v", (x1 + x2) / 2, min(y1, y2), max(y1, y2), w)
        else:
            x0, y0, x1, y1 = rx0[i], ry0[i], rx1[i], ry1[i]
            w, nofill = rects[i][4], rects[i][5]
            width, height = x1 - x0, y1 - y0
            # тонкий залитый прямоугольник = линия
            if height <= max_thickness and width > height:
                add("h", (y0 + y1) / 2, x0, x1, height)
            elif width <= max_thickness and height > width:
                add("v", (x0 + x1) / 2, y0, y1, width)
            elif width > max_thickness and height > max_thickness:
                # рамка, нарисованная как незалитый прямоугольник
                if nofill:
                    add("h", y0, x0, x1, w); add("h", y1, x0, x1, w)
                    add("v", x0, y0, y1, w); add("v", x1, y0, y1, w)

    return _merge_collinear(raw_h, tol), _merge_collinear(raw_v, tol)


def _merge_collinear(rl: list[Ruling], tol: float) -> list[Ruling]:
    """Склеивает отрезки с почти одинаковым const и пересекающимися интервалами."""
    rl.sort(key=lambda r: (r.const, r.a))
    out: list[Ruling] = []
    for r in rl:
        merged = False
        for o in reversed(out):
            if abs(o.const - r.const) > tol:
                break
            if r.a <= o.b + tol and r.b >= o.a - tol:
                o.a = min(o.a, r.a); o.b = max(o.b, r.b)
                o.width = max(o.width, r.width)
                merged = True
                break
        if not merged:
            out.append(Ruling(r.const, r.a, r.b, r.width))
    return out


# --------------------------------------------------------------------------- #
#  2. деление на блоки таблиц
# --------------------------------------------------------------------------- #
def find_table_blocks(h: list[Ruling], v: list[Ruling], *, min_rows: int = 3,
                      min_cols: int = 2, tol: float = 1.5,
                      page_rect: fitz.Rect | None = None,
                      frame_ratio: float = 0.92, frame_margin: float = 72.0,
                      inside_ratio: float = 0.5) -> list[TableBlock]:
    """Группирует линии в связные компоненты по пересечениям -> блоки таблиц.

    Компонента связности = набор линий, образующих одну рамку с линовкой. Так
    лист автоматически делится на «Начало», «Окончание» и т. п.

    Две поправки, без которых реальные листы разбираются неверно:

    1) РАМКА ЛИСТА исключается из группировки. Линовка таблицы почти всегда
       касается рамки (у КМ1 вертикаль рамки x=56.693 пересекает горизонтали
       таблицы, начинающиеся с x=57). Тогда рамка и таблица попадают в одну
       компоненту, её габарит становится размером со страницу, и вся таблица
       отбрасывалась как «рамка». Пропавшие внешние границы восстанавливает
       `_implied_bounds`, поэтому потери нет.

       Одной длины линии для этого мало. У листа-скана «Спецификация металла
       образец» таблица занимает почти весь лист: её собственные вертикали
       длиной 778 pt при высоте листа 842 pt (0.92) отбрасывались вместе с
       рамкой, и из 10 колонок оставалось 6 — марка стали, номер профиля,
       № п.п. и «Колонны/Стойки» слипались в одну. Поэтому длина проверяется
       вместе с положением: рамка идёт вдоль края листа (по ГОСТ 2.301 — 20 мм
       слева и 5 мм с прочих сторон), разделитель внутри таблицы — нет.

    2) Блоки, лежащие ВНЕ страницы, отбрасываются. В том же файле половина
       векторных сегментов — копия таблицы с x от -1219 до -312; она невидима
       (обрезается), но геометрически образует полноценную сетку 83 x 17 и
       раньше выдавалась за настоящую таблицу.
    """
    if page_rect is not None:
        # рамка листа: линия почти во всю страницу И вдоль её края
        margin_x = max(frame_margin, 0.05 * page_rect.width)
        margin_y = max(frame_margin, 0.05 * page_rect.height)

        def is_frame_h(r: Ruling) -> bool:
            return ((r.b - r.a) >= frame_ratio * page_rect.width
                    and (r.const - page_rect.y0 <= margin_y
                         or page_rect.y1 - r.const <= margin_y))

        def is_frame_v(r: Ruling) -> bool:
            return ((r.b - r.a) >= frame_ratio * page_rect.height
                    and (r.const - page_rect.x0 <= margin_x
                         or page_rect.x1 - r.const <= margin_x))

        h = [r for r in h if not is_frame_h(r)]
        v = [r for r in v if not is_frame_v(r)]

    lines = [("h", i, r) for i, r in enumerate(h)] + [("v", i, r) for i, r in enumerate(v)]
    n = len(lines)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    for i in range(n):
        ki, _, ri = lines[i]
        for j in range(i + 1, n):
            kj, _, rj = lines[j]
            if ki == kj:
                continue
            hh, vv = (ri, rj) if ki == "h" else (rj, ri)
            if (vv.a - tol <= hh.const <= vv.b + tol) and (hh.a - tol <= vv.const <= hh.b + tol):
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    blocks: list[TableBlock] = []
    for idxs in groups.values():
        gh = [lines[i][2] for i in idxs if lines[i][0] == "h"]
        gv = [lines[i][2] for i in idxs if lines[i][0] == "v"]
        if len(gh) < min_rows + 1 or len(gv) < min_cols + 1:
            continue
        x0 = min(r.const for r in gv); x1 = max(r.const for r in gv)
        y0 = min(r.const for r in gh); y1 = max(r.const for r in gh)
        if page_rect is not None:
            box = fitz.Rect(x0, y0, x1, y1)
            area = abs(box.get_area())
            if area <= 0:
                continue
            visible = fitz.Rect(box) & page_rect
            if abs(visible.get_area()) < inside_ratio * area:
                continue                      # блок за пределами листа
        blk = _build_grid(gh, gv, (x0, y0, x1, y1))
        if blk.n_rows >= min_rows and blk.n_cols >= min_cols:
            blocks.append(blk)

    blocks.sort(key=lambda b: (round(b.bbox[1] / 20), b.bbox[0]))
    return blocks


def _gap_cv(vals: list[float]) -> float:
    """Коэффициент вариации зазоров; 0 если точек мало."""
    if len(vals) < 3:
        return 0.0
    gaps = [vals[i + 1] - vals[i] for i in range(len(vals) - 1)]
    mean = sum(gaps) / len(gaps)
    if mean <= 0:
        return 0.0
    var = sum((g - mean) ** 2 for g in gaps) / len(gaps)
    return (var ** 0.5) / mean


def is_drawing_grid(block: TableBlock, page_rect: fitz.Rect | None = None) -> bool:
    """Линовка чертежа (оси, размеры, штриховка), а не таблица спецификации.

    На листе, где спецификация стоит РЯДОМ с чертежом, осевые и размерные
    линии образуют полноценную «сетку» на десятки колонок. Если отдать её
    в OCR, он читает подписи осей и выноски, а не металлопрокат.

    Настоящая спецификация КМ/КР — 8…18 колонок при шаге строк ~20 pt
    (проверено на КМ1 83×17 и на file-4 40×9). Отсекаем только то, чего
    у спеки не бывает: слишком много колонок, засечки по 4 pt, рваный
    шаг широкой сетки, короткая полоса размерных чисел.
    """
    n_rows, n_cols = block.n_rows, block.n_cols
    if n_cols >= 20:
        return True
    if n_rows <= 6 and n_cols >= 15:
        return True
    if n_rows >= 20 and n_cols >= 8 and len(block.ys) >= 3:
        gaps = sorted(block.ys[i + 1] - block.ys[i] for i in range(len(block.ys) - 1))
        med = gaps[len(gaps) // 2]
        if med < 8.0:
            return True
    if n_cols >= 15 and _gap_cv(block.xs) >= 0.8:
        return True
    return False


def looks_stamp_block(block: TableBlock) -> bool:
    """Узкая боковая графа или широкая полоса штампа — не спецификация.

    Гибридный OCR на таком блоке дорог и почти ничего не даёт: текст повёрнут,
    блок всё равно помечается нечитаемым. На file-4 это полоса 42×425 pt
    слева от таблицы (7×5), на которую уходило столько же, сколько на спеку.
    """
    w = block.bbox[2] - block.bbox[0]
    h = block.bbox[3] - block.bbox[1]
    if w <= 0 or h <= 0:
        return False
    return h > 3.0 * w or w > 8.0 * h


def _cluster(vals: list[float], tol: float) -> list[float]:
    vals = sorted(vals)
    out: list[float] = []
    grp = [vals[0]]
    for v in vals[1:]:
        if v - grp[-1] <= tol:
            grp.append(v)
        else:
            out.append(sum(grp) / len(grp)); grp = [v]
    out.append(sum(grp) / len(grp))
    return out


def _coverage(rl: list[Ruling], pos: float, a: float, b: float, tol: float) -> float:
    """Доля интервала [a, b], покрытая линиями с const ≈ pos."""
    if b <= a:
        return 1.0
    segs = [(max(a, r.a), min(b, r.b)) for r in rl
            if abs(r.const - pos) <= tol and r.b > a + tol and r.a < b - tol]
    if not segs:
        return 0.0
    segs.sort()
    total = 0.0
    cur_a, cur_b = segs[0]
    for s, e in segs[1:]:
        if s <= cur_b:
            cur_b = max(cur_b, e)
        else:
            total += cur_b - cur_a; cur_a, cur_b = s, e
    total += cur_b - cur_a
    return total / (b - a)


def _implied_bounds(perp: list[Ruling], lo: float, hi: float, tol: float,
                    min_frac: float = 0.25) -> tuple[float | None, float | None]:
    """Границы блока, не нарисованные линией, но подтверждённые концами
    перпендикулярных линий.

    В тестовом PDF у левой таблицы ФИЗИЧЕСКИ НЕТ левой границы: все
    горизонтальные линии начинаются с x=144, а самая левая вертикаль — x=228.8.
    Без этой поправки первая колонка («Наименование профиля ГОСТ, ТУ») теряется.
    """
    if not perp:
        return None, None
    need = max(2, int(min_frac * len(perp)))

    def modal(vals: list[float]) -> float | None:
        if not vals:
            return None
        best, best_n = None, 0
        for c in _cluster(vals, tol):
            n = sum(1 for v in vals if abs(v - c) <= tol)
            if n > best_n:
                best, best_n = c, n
        return best if best_n >= need else None

    left = modal([r.a for r in perp if r.a < lo - tol])
    right = modal([r.b for r in perp if r.b > hi + tol])
    return left, right


def _regularize_pitch(ys: list[float], tol: float = 2.0) -> list[float]:
    """Достраивает пропущенные разделители там, где зазор кратеншагу строки.

    Строки спецификаций имеют постоянную высоту (здесь 22.68 pt). Если между
    двумя линиями зазор ~= k*шаг (k >= 2), значит линия не нарисована из-за
    merged-области. Индексация строк должна это учитывать, иначе позиции
    «съезжают»: в тестовом листе так слиты строки поз. 26 и 27.
    Вставленные разделители «виртуальны» — линии там нет, поэтому склейка
    merged cells ниже всё равно объединит эти ячейки.
    """
    if len(ys) < 4:
        return ys
    gaps = [round(ys[i + 1] - ys[i], 1) for i in range(len(ys) - 1)]
    counts: dict[float, int] = {}
    for g in gaps:
        counts[g] = counts.get(g, 0) + 1
    pitch, n = max(counts.items(), key=lambda kv: (kv[1], -kv[0]))
    if n < 4 or pitch <= 0:
        return ys
    out = [ys[0]]
    for i in range(len(ys) - 1):
        gap = ys[i + 1] - ys[i]
        k = int(round(gap / pitch))
        if k >= 2 and abs(gap - k * pitch) <= tol:
            for j in range(1, k):
                out.append(ys[i] + j * gap / k)
        out.append(ys[i + 1])
    return out


def _covered_length(rl: list[Ruling], const: float, tol: float) -> float:
    """Суммарная длина отрезков с const ≈ заданной, без двойного счёта дыр."""
    segs = sorted((r.a, r.b) for r in rl if abs(r.const - const) <= tol)
    if not segs:
        return 0.0
    total = 0.0
    cur_a, cur_b = segs[0]
    for s, e in segs[1:]:
        if s <= cur_b + tol:
            cur_b = max(cur_b, e)
        else:
            total += cur_b - cur_a
            cur_a, cur_b = s, e
    return total + (cur_b - cur_a)


def _separator_consts(rl: list[Ruling], span_min: float, tol: float) -> list[float]:
    """Положения разделителей, даже если линия нарисована кусками.

    Вертикаль между «наименованием профиля» и «маркой металла» на строках
    «Итого»/«Всего профиля» прерывается (там ячейка объединена). Каждый кусок
    короче 0.3 высоты таблицы — и колонка пропадала, имя с маркой слипались.
    """
    if not rl:
        return []
    out = []
    for c in _cluster([r.const for r in rl], tol):
        if _covered_length(rl, c, tol) >= span_min:
            out.append(c)
    return out


def _build_grid(gh: list[Ruling], gv: list[Ruling],
                bbox: tuple[float, float, float, float], tol: float = 1.5,
                span_ratio: float = 0.30, edge_ratio: float = 0.70) -> TableBlock:
    """Строит сетку разделителей и склеивает merged cells."""
    x0, y0, x1, y1 = bbox
    W, H = x1 - x0, y1 - y0

    # Разделителем считаем линию, протянувшуюся хотя бы на span_ratio габарита.
    # Длина — суммарная по кускам, не по самому длинному отрезку (см. выше).
    long_v = [r for r in gv if (r.b - r.a) >= span_ratio * H]
    long_h = [r for r in gh if (r.b - r.a) >= span_ratio * W]
    xs = _separator_consts(gv, span_ratio * H, tol)
    ys = _separator_consts(gh, span_ratio * W, tol)
    if len(xs) < 2 or len(ys) < 2:
        return TableBlock(bbox, xs, ys, [], 0, 0)

    # ненарисованные внешние границы
    lx, rx = _implied_bounds(long_h, xs[0], xs[-1], tol)
    if lx is not None:
        xs.insert(0, lx)
    if rx is not None:
        xs.append(rx)
    ty, by = _implied_bounds(long_v, ys[0], ys[-1], tol)
    if ty is not None:
        ys.insert(0, ty)
    if by is not None:
        ys.append(by)

    ys = _regularize_pitch(ys)
    n_rows, n_cols = len(ys) - 1, len(xs) - 1

    # Наличие рёбер между соседними атомарными ячейками.
    # v_edge[r][c] — есть ли вертикальный разделитель xs[c] на высоте строки r.
    v_edge = [[_coverage(gv, xs[c], ys[r], ys[r + 1], tol) >= edge_ratio
               for c in range(len(xs))] for r in range(n_rows)]
    h_edge = [[_coverage(gh, ys[r], xs[c], xs[c + 1], tol) >= edge_ratio
               for c in range(n_cols)] for r in range(len(ys))]

    # Union-find по атомарным ячейкам: сливаем там, где разделителя нет.
    parent = list(range(n_rows * n_cols))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[max(ri, rj)] = min(ri, rj)

    for r in range(n_rows):
        for c in range(n_cols):
            i = r * n_cols + c
            if c + 1 < n_cols and not v_edge[r][c + 1]:
                union(i, i + 1)
            if r + 1 < n_rows and not h_edge[r + 1][c]:
                union(i, i + n_cols)

    regions: dict[int, list[tuple[int, int]]] = {}
    for r in range(n_rows):
        for c in range(n_cols):
            regions.setdefault(find(r * n_cols + c), []).append((r, c))

    cells: list[CellBox] = []
    for members in regions.values():
        rr = [m[0] for m in members]; cc = [m[1] for m in members]
        r0, r1_, c0, c1_ = min(rr), max(rr), min(cc), max(cc)
        # Область объединяется в одну ячейку ТОЛЬКО если она прямоугольная.
        # На шумной сетке (растровая линовка скана) связная область бывает
        # Г-образной, и её габаритный прямоугольник перекрывается с соседним —
        # сетка становилась противоречивой, а запись XLSX падала на MergedCell.
        if len(members) == (r1_ - r0 + 1) * (c1_ - c0 + 1):
            cells.append(CellBox(r0, c0, r1_ - r0 + 1, c1_ - c0 + 1,
                                 (xs[c0], ys[r0], xs[c1_ + 1], ys[r1_ + 1])))
        else:
            for r, c in members:
                cells.append(CellBox(r, c, 1, 1,
                                     (xs[c], ys[r], xs[c + 1], ys[r + 1])))
    cells.sort(key=lambda c: (c.row, c.col))
    return TableBlock((xs[0], ys[0], xs[-1], ys[-1]), xs, ys, cells, n_rows, n_cols)
