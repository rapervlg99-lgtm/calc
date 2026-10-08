# -*- coding: utf-8 -*-
"""Детерминированная проверка арифметики таблицы.

Никаких моделей и эвристик: суммы пересчитываются обычным сложением и
сравниваются с распознанными итогами. Расхождение — сильный признак ошибки
распознавания, поэтому проверки служат ещё и метрикой качества.

Что проверяется в спецификации металлопроката:
  1. Строка:   сумма масс по элементам конструкции == «Общая масса, т».
  2. «Итого»:  по каждой колонке == сумма строк данных своей группы.
  3. «Всего профиля»: по каждой колонке == сумма «Итого» своего блока профиля.
  4. «Масса металла» (общий итог) == сумма «Всего профиля» по ВСЕМ частям
     таблицы (лист разбит на «Начало» и «Окончание»).
  5. Таблица «В том числе по маркам»: сумма по маркам == общий итог.

Допуск. Значения на чертеже округлены до двух знаков, поэтому сумма n слагаемых
может расходиться с напечатанным итогом на величину порядка n * 0.005. Допуск
берётся как max(base, per_term * n), это не «подгонка», а учёт округления.
"""
from __future__ import annotations

from dataclasses import dataclass

from .models import RowCheck, Table
from .structure import Column, LogicalRow, column_key


@dataclass
class Tolerance:
    """Допуск арифметических проверок. Значения по умолчанию рассчитаны на массы
    с двумя знаками после запятой (округление каждого слагаемого до 0,005 т)."""
    base: float = 0.02
    per_term: float = 0.006
    decimals: int = 2

    def for_terms(self, n: int) -> float:
        return max(self.base, self.per_term * max(1, n))

    def for_decimals(self, decimals: int) -> "Tolerance":
        """Тот же допуск, пересчитанный под точность чисел на листе.

        На листе с массами в одну десятую («23,2», «81,9») каждое слагаемое
        округлено уже до 0,05 т, и сумма честно расходится с итогом на 0,1:
        с допуском для двух знаков такие строки краснели без причины."""
        d = max(0, min(int(decimals), 3))
        if d >= self.decimals:
            return self
        k = 10 ** (self.decimals - d)
        return Tolerance(self.base * k, self.per_term * k, d)


def mass_decimals(rows: list[LogicalRow], cols: list[Column], default: int = 2) -> int:
    """Число знаков после запятой у масс на листе: максимум по числовым ячейкам
    колонок масс. Нет чисел — `default`."""
    keys = _element_keys(cols) + ["total_mass"]
    # массы в килограммах переведены в тонны: у «13634» три знака после запятой
    extra = 3 if any(c.unit == "кг" for c in cols if c.role in ("element_mass", "total_mass")) else 0
    best = -1
    for row in rows:
        for key in keys:
            cell = row.cells.get(key)
            if cell is None or cell.is_empty or not isinstance(cell.normalized_value, (int, float)):
                continue
            t = str(cell.text).strip().replace(",", ".")
            frac = t.split(".", 1)[1] if "." in t else ""
            digits = len("".join(ch for ch in frac if ch.isdigit())) + extra
            best = max(best, digits)
    return best if best >= 0 else default


def _num(cell) -> float | None:
    if cell is None or cell.is_empty:
        return None
    v = cell.normalized_value
    return float(v) if isinstance(v, (int, float)) else None


def _element_keys(cols: list[Column]) -> list[str]:
    return [column_key(c) for c in cols if c.role == "element_mass"]


def check_row_sums(rows: list[LogicalRow], cols: list[Column],
                   tol: Tolerance) -> list[RowCheck]:
    """Сумма масс по элементам против «Общей массы» — по каждой строке."""
    keys = _element_keys(cols)
    eff = _effective_cells(rows, keys + ["total_mass"], keys)
    out: list[RowCheck] = []
    for row in rows:
        if row.kind in ("empty", "section_header"):
            continue
        total_cell = row.cells.get("total_mass")
        total = _num(total_cell)
        # У строки-итога пустая графа значит «значение есть в данных группы»:
        # берём его, иначе напечатанный итог не сойдётся с собственной строкой
        # (file-3: 1,563 против 1,375 — терялись 0,188 «Рамы вентилятора»).
        terms = []
        for key in keys:
            v = _num(row.cells.get(key))
            if v is None and row.kind != "data":
                v = eff.get((row.row, key))
            if v is not None:
                terms.append(v)
        if total is None and not terms:
            continue
        if total is None:
            out.append(RowCheck(row.row, "row_sum", None, round(sum(terms), 6), None,
                                0.0, "skipped", "total_mass",
                                "no total in the row", terms))
            continue
        if not terms:
            out.append(RowCheck(row.row, "row_sum", total, None, None, 0.0,
                                "skipped", "total_mass",
                                "no element masses in the row", []))
            continue
        calc = round(sum(terms), 6)
        t = tol.for_terms(len(terms))
        delta = round(calc - total, 6)
        status = "ok" if abs(delta) <= t else "failed"
        out.append(RowCheck(row.row, "row_sum", total, calc, delta, t, status,
                            "total_mass",
                            "" if status == "ok" else "row total mismatch", terms))
    return out


def _column_sum(rows: list[LogicalRow], key: str) -> tuple[float, int]:
    vals = [v for v in (_num(r.cells.get(key)) for r in rows) if v is not None]
    return round(sum(vals), 6), len(vals)


def _effective_cells(rows: list[LogicalRow], keys: list[str],
                     elem_keys: list[str]) -> dict[tuple[int, str], float]:
    """Числа, которых нет в ячейках, но которые входят в напечатанные итоги.

    Два случая, оба встретились на листах корпуса:

    1. В строке-итоге пуста графа, значение которой есть в данных группы, а
       напечатанный итог его учитывает (KD.163_8 — 3,46 т в «Опоры», file-3 —
       0,188 т в «Раме для вентилятора»). Для строки-итога берём сумму данных.
    2. В строке данных пуста «Общая масса», хотя массы по элементам прочитаны
       (file-14, поз. 9: 0,43 т). Для колонки общей массы берём сумму элементов.

    Саму пустую графу проверка по-прежнему помечает замечанием: сравнивать её с
    напечатанным нельзя. Но дальше по цепочке («Итого» → «Всего профиля» →
    «Общая масса») суммы сходятся, и производных расхождений не возникает.
    """
    out: dict[tuple[int, str], float] = {}
    bucket: list[LogicalRow] = []
    for row in rows:
        if row.kind == "data":
            bucket.append(row)
            if _num(row.cells.get("total_mass")) is None:
                vals = [v for v in (_num(row.cells.get(k)) for k in elem_keys)
                        if v is not None]
                if vals:
                    out[(row.row, "total_mass")] = round(sum(vals), 6)
            continue
        if row.kind in ("group_total", "profile_total", "grand_total"):
            for key in keys:
                if key == "total_mass" or _num(row.cells.get(key)) is not None:
                    continue
                calc, n = _column_sum(bucket, key)
                if not (n and calc):
                    continue
                # Подставляем, только если напечатанный итог строки это
                # подтверждает: у file-3 «Итого» 1,563 = 1,375 + 0,188, а у
                # KD.163_8 напечатанные 79,62 наоборот НЕ включают 3,46 — там
                # подстановка ломала сходившуюся проверку (178+5 → 177+6).
                total = _num(row.cells.get("total_mass"))
                if total is not None:
                    own = [v for k2, v in ((k2, _num(row.cells.get(k2))) for k2 in keys
                                           if k2 not in (key, "total_mass")) if v is not None]
                    if abs(round(sum(own), 6) + calc - total) > 0.05:
                        continue
                out[(row.row, key)] = calc
        bucket = []
    return out


def _sum_with(rows: list[LogicalRow], key: str,
              eff: dict[tuple[int, str], float]) -> tuple[float, int]:
    """Сумма колонки с подстановкой эффективных значений."""
    vals = []
    for r in rows:
        v = _num(r.cells.get(key))
        if v is None:
            v = eff.get((r.row, key))
        if v is not None:
            vals.append(v)
    return round(sum(vals), 6), len(vals)


def _continued_group(bucket: list[LogicalRow], rows: list[LogicalRow]) -> bool:
    """Первая группа блока, чьё наименование — обрывок с маленькой буквы."""
    if not bucket:
        return False
    # первая строка данных С НОМЕРОМ позиции во всём блоке (пустые строки под
    # шапкой позиции не имеют) должна принадлежать этой группе
    positioned = [r for r in rows if r.kind == "data" and isinstance(r.position, int)]
    if not positioned or not any(r is positioned[0] for r in bucket):
        return False
    first = positioned[0]
    cell = first.cells.get("profile_group")
    text = (cell.text if cell is not None else "").strip()
    # только обрывок наименования с маленькой буквы: номер первой позиции не
    # годится — на file-45 второй блок начинается с поз. 62, но группы там целые
    return bool(text) and text[0].isalpha() and text[0].islower()


def check_group_totals(rows: list[LogicalRow], cols: list[Column],
                       tol: Tolerance) -> list[RowCheck]:
    """«Итого» против суммы строк данных своей группы (по каждой колонке)."""
    keys = _element_keys(cols) + ["total_mass"]
    eff = _effective_cells(rows, keys, _element_keys(cols))
    out: list[RowCheck] = []
    bucket: list[LogicalRow] = []
    totals_bucket: list[LogicalRow] = []
    for row in rows:
        if row.kind == "data":
            bucket.append(row)
            continue
        if row.kind == "group_total":
            # Группа начата в другом блоке спецификации (file-37: «…квадратные и
            # прямоугольные ГОСТ 30245-2003» продолжается во втором столбце листа):
            # у неё в этом блоке только хвост строк, и сумма заведомо не сойдётся.
            if _continued_group(bucket, rows):
                for key in keys:
                    expected = _num(row.cells.get(key))
                    if expected is not None:
                        out.append(RowCheck(row.row, "group_total", expected, None, None, 0.0,
                                            "skipped", key, "группа начата в другом блоке"))
                totals_bucket.append(row)
                bucket = []
                continue
            for key in keys:
                expected = _num(row.cells.get(key))
                calc, n = _sum_with(bucket, key, eff)
                if expected is None and n == 0:
                    continue
                if expected is None:
                    # Итог в этой колонке не заполнен, а данные есть. Это не
                    # ошибка распознавания (проверить не с чем), но и не «всё
                    # хорошо»: на KD.163_8 так теряется 3,46 т в колонке
                    # «Опоры». Отдельный статус `note` — замечание для
                    # человека, оно идёт в отчёт отдельным списком и не портит
                    # счётчик расхождений.
                    out.append(RowCheck(row.row, "group_total", None, calc,
                                        None, 0.0, "note", key,
                                        "итог в этой колонке не заполнен, "
                                        "а в данных есть значения — сверить с чертежом"))
                    continue
                t = tol.for_terms(max(n, 1))
                delta = round(calc - expected, 6)
                out.append(RowCheck(row.row, "group_total", expected, calc, delta, t,
                                    "ok" if abs(delta) <= t else "failed", key,
                                    "" if abs(delta) <= t else "group total mismatch"))
            totals_bucket.append(row)
            bucket = []
        elif row.kind == "profile_total":
            # «Всего профиля» = сумма «Итого» подгрупп плюс строки данных, у
            # которых своего «Итого» не было (на многих листах подгрупп нет
            # вовсе, и «Всего профиля» стоит сразу под строками данных).
            for key in keys:
                expected = _num(row.cells.get(key))
                calc_t, n_t = _sum_with(totals_bucket, key, eff)
                calc_d, n_d = _sum_with(bucket, key, eff)
                calc, n = round(calc_t + calc_d, 6), n_t + n_d
                if expected is None and n == 0:
                    continue
                if expected is None:
                    continue
                t = tol.for_terms(max(n, 1))
                delta = round(calc - expected, 6)
                out.append(RowCheck(row.row, "profile_total", expected, calc, delta, t,
                                    "ok" if abs(delta) <= t else "failed", key,
                                    "" if abs(delta) <= t else "profile total mismatch"))
            bucket, totals_bucket = [], []
    return out


def check_grand_total(parts: list[tuple[list[LogicalRow], list[Column]]],
                      tol: Tolerance) -> list[RowCheck]:
    """«Масса металла» против суммы всех «Всего профиля» по всем частям листа.

    Строк «Всего профиля» на листе может не быть вовсе: в «Технической
    спецификации металла» общий итог подводится сразу под строками «Итого» по
    группам профилей. Тогда слагаемые берутся из них — иначе пересчёт давал 0 и
    верный итог помечался расхождением.
    """
    grand: LogicalRow | None = None
    grand_cols: list[Column] = []
    profile_rows: list[LogicalRow] = []
    group_rows: list[LogicalRow] = []
    for rows, cols in parts:
        for row in rows:
            if row.kind == "grand_total":
                grand, grand_cols = row, cols
            elif row.kind == "profile_total":
                profile_rows.append(row)
            elif row.kind == "group_total":
                group_rows.append(row)
    if grand is None:
        return []
    # «Всего профиля» уже включает свои «Итого» — складывать оба нельзя.
    terms = profile_rows or group_rows
    out: list[RowCheck] = []
    for key in _element_keys(grand_cols) + ["total_mass"]:
        expected = _num(grand.cells.get(key))
        calc, n = _column_sum(terms, key)
        if expected is None:
            continue
        if n == 0:
            # складывать нечего — сравнивать не с чем, молча «пройдено» ставить
            # тоже нельзя
            out.append(RowCheck(grand.row, "grand_total", expected, None, None,
                                0.0, "skipped", key,
                                "нет строк-слагаемых для общего итога"))
            continue
        t = tol.for_terms(max(n, 1))
        delta = round(calc - expected, 6)
        out.append(RowCheck(grand.row, "grand_total", expected, calc, delta, t,
                            "ok" if abs(delta) <= t else "failed", key,
                            "" if abs(delta) <= t else "grand total mismatch"))
    return out


def _is_service_row(row: LogicalRow) -> bool:
    """Служебная строка таблицы марок, а не марка стали.

    Последней строкой в «В том числе по маркам или наименованиям» идёт «масса
    наплавленного металла 1%». Это не марка: её масса в сумму по маркам не
    входит, и без исключения проверка объявляла расхождение на верных числах —
    на Estakada 397,08 (с наплавленным металлом 3,93) против напечатанных 393,15.

    Сравнение терпимо к ошибкам OCR: живой прогон читает подпись и как
    «масса. наплавленного металла. 1%», и как «масса. наплабленного металла»
    (в→б). Поэтому смотрим на начало слова «масс…», на знак процента и на
    основу «напла», а не на точную подпись.
    """
    for cell in row.cells.values():
        if cell is None or cell.is_empty:
            continue
        text = "".join(str(cell.text or "").lower().split())
        if not text:
            continue
        if "%" in text or text.startswith("масс") or "напла" in text:
            return True
    return False


def check_by_grade(grade_rows: list[LogicalRow], cols: list[Column],
                   grand_total: float | None, tol: Tolerance) -> list[RowCheck]:
    """Таблица «В том числе по маркам»: сумма по маркам == общий итог."""
    if grand_total is None:
        return []
    kept = [r for r in grade_rows if not _is_service_row(r)]
    skipped = len(grade_rows) - len(kept)
    grade_rows = kept
    vals = [v for v in (_num(r.cells.get("total_mass")) for r in grade_rows)
            if v is not None]
    if not vals:
        return []
    calc = round(sum(vals), 6)
    t = tol.for_terms(len(vals))
    delta = round(calc - grand_total, 6)
    ok = abs(delta) <= t
    reason = ""
    if not ok:
        reason = "sum over grades != total metal mass"
    elif skipped:
        reason = ("строка «масса наплавленного металла» в сумму по маркам "
                  "не входит (%d стр.)" % skipped)
    return [RowCheck(-1, "by_grade_total", grand_total, calc, delta, t,
                     "ok" if ok else "failed", "total_mass", reason, vals)]


_STATUS_TO_REPORT = {"ok": "passed", "failed": "failed", "skipped": "skipped"}


def summarize(checks: list[RowCheck]) -> dict[str, int]:
    """Сводка по статусам. RowCheck.status = ok|failed|skipped|note, в отчёте —
    passed/failed/skipped/note (note — замечание для человека, не расхождение)."""
    out = {"passed": 0, "failed": 0, "skipped": 0, "note": 0}
    for c in checks:
        key = _STATUS_TO_REPORT.get(c.status, c.status)
        out[key] = out.get(key, 0) + 1
    return out


def mark_failed_cells(table: Table) -> None:
    """Ячейки строк с расхождением и со замечанием помечаются на ручную проверку."""
    bad = {c.row for c in table.checks if c.status == "failed"}
    note = {c.row for c in table.checks if c.status == "note"} - bad
    if not bad and not note:
        return
    for cell in table.cells:
        if cell.is_empty:
            continue
        if cell.row in bad:
            cell.requires_review = True
            if "arithmetic check failed in this row" not in cell.notes:
                cell.notes.append("arithmetic check failed in this row")
        elif cell.row in note:
            cell.requires_review = True
            if "итог в чертеже не заполнен — проверить вручную" not in cell.notes:
                cell.notes.append("итог в чертеже не заполнен — проверить вручную")
