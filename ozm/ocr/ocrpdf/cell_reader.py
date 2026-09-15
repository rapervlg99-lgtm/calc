# -*- coding: utf-8 -*-
"""Чтение содержимого ячеек: приоритет источников.

Порядок предпочтения (от точного к приблизительному):
  1. `text_layer`   — настоящий текстовый слой PDF после ремонта кодировки.
                      Точность 100 %, координаты из PDF, confidence = 1.0.
  2. `vector_glyph` — распознавание «взорванного» векторного текста шаблонами.
  3. `ocr`          — растровый OCR (только для сканов, см. `ocr_backends`).

Важное наблюдение по тестовому файлу: ОДНА ячейка может быть частично текстом,
частично векторами. Например «Профили стальные гнутые замкнутые сварные
квадратные ГОСТ 30245-2003»: первые две строки лежат в текстовом слое,
остальные четыре — взорваны в геометрию. Поэтому объединение источников
делается на уровне СТРОК ячейки, а не ячейки целиком.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


from .pdfbackend import fitz
from .fontfix import FontRepair, decode_span, looks_broken
from .glyph_ocr import (CHARSET_TEXT, CHARSETS, GlyphLayer, GlyphResult, _cap_height_px,
                        _read_line, group_lines, merge_counters, merge_diacritics,
                        merge_strokes)
from .models import Cell, Glyph

BBox = tuple[float, float, float, float]


@dataclass
class TextLine:
    """Строка текстового слоя: уже исправленный текст + координаты."""
    text: str
    bbox: BBox
    horizontal: bool = True
    repaired: bool = False
    size: float = 0.0
    direction: tuple[float, float] = (1.0, 0.0)   # направление письма из PDF
    engine: str = ""        # для строк растрового OCR: каким движком прочитано


def build_text_lines(page: fitz.Page, repairs: dict[str, FontRepair]) -> list[TextLine]:
    """Собирает строки текстового слоя, склеивая span'ы одной строки."""
    out: list[TextLine] = []
    # PyMuPDF отдаёт текст (как и get_drawings) в координатах НЕповёрнутой
    # страницы, а сетка ячеек, растр и page.rect живут в повёрнутой системе.
    # На листе с /Rotate 270 ни одна строка текстового слоя не попадала в
    # ячейку, и таблица целиком уходила в растровый OCR — с потерей точек в
    # числах («22.010» -> «22010») и кашей в наименованиях.
    rot = getattr(page, "rotation", 0) or 0
    mat = page.rotation_matrix if rot else None
    lin = fitz.Matrix(mat.a, mat.b, mat.c, mat.d, 0.0, 0.0) if mat is not None else None
    for block in page.get_text("rawdict")["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            dx, dy = line.get("dir", (1.0, 0.0))
            bbox = tuple(line["bbox"])
            if mat is not None:
                r = fitz.Rect(bbox) * mat
                bbox = (r.x0, r.y0, r.x1, r.y1)
                d = fitz.Point(float(dx), float(dy)) * lin
                dx, dy = d.x, d.y
            horizontal = abs(dx) >= abs(dy)
            parts: list[str] = []
            repaired = False
            size = 0.0
            for sp in line["spans"]:
                txt, fixed = decode_span(sp["chars"], sp["font"].split("+")[-1], repairs)
                repaired = repaired or fixed
                size = max(size, sp["size"])
                parts.append(txt)
            text = "".join(parts).strip()
            if not text:
                continue
            out.append(TextLine(text, bbox, horizontal, repaired,
                                size, (float(dx), float(dy))))
    return out


# строка целиком из нераспознанных знаков / серия таких знаков
_ONLY_MARKS = re.compile(r"[?\s]+")
_MARK_RUN = re.compile(r"\?(?:\s*\?)+")


def _inside(inner: BBox, outer: BBox, tol: float = 1.0) -> bool:
    return (inner[0] >= outer[0] - tol and inner[2] <= outer[2] + tol
            and inner[1] >= outer[1] - tol and inner[3] <= outer[3] + tol)


def _overlaps(a: BBox, b: BBox) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _overlap_frac(inner: BBox, outer: BBox) -> float:
    """Доля площади inner, лежащая внутри outer."""
    x0 = max(inner[0], outer[0]); y0 = max(inner[1], outer[1])
    x1 = min(inner[2], outer[2]); y1 = min(inner[3], outer[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    area = (inner[2] - inner[0]) * (inner[3] - inner[1])
    return ((x1 - x0) * (y1 - y0) / area) if area > 0 else 0.0


def should_try_rotation(bbox: BBox, row_span: int, min_ratio: float = 1.2) -> bool:
    """Вертикальная подпись шапки: одна строка сетки и заметно выше, чем шире.

    Порог 1.2, а не 1.5: на file-4 «Фахверк»/«Связи» имеют отношение 1.47 и
    читались как «Φaxbepk» / «CB93U». Merged-ячейки наименования профиля
    (row_span ≥ 2) не крутим — там обычный перенос строк, не вертикаль.
    """
    if row_span != 1:
        return False
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    return w > 0 and h >= min_ratio * w


def _group_words(words: list[TextLine], overlap: float = 0.45) -> list[list[TextLine]]:
    """Группирует распознанные слова в строки по вертикальному перекрытию."""
    lines: list[list[TextLine]] = []
    for w in sorted(words, key=lambda w: w.bbox[1]):
        wh = w.bbox[3] - w.bbox[1]
        for L in lines:
            ly0 = min(x.bbox[1] for x in L); ly1 = max(x.bbox[3] for x in L)
            ov = min(w.bbox[3], ly1) - max(w.bbox[1], ly0)
            if ov >= overlap * min(wh, ly1 - ly0):
                L.append(w)
                break
        else:
            lines.append([w])
    for L in lines:
        L.sort(key=lambda w: w.bbox[0])
    lines.sort(key=lambda L: min(w.bbox[1] for w in L))
    return lines


def ocr_region(layer: GlyphLayer, backend, bbox: BBox, min_line_px: int = 26,
               numeric: bool = False) -> list[TextLine]:
    """Один вызов OCR на область; слова возвращаются в координатах страницы.

    Растр берём уже отрендеренный в `GlyphLayer`. RapidOCR сам поднимает
    короткую сторону до ~736 и режет длинную до 2000 — заранее раздувать
    кроп не нужно.
    """
    import numpy as np

    if backend is None or not getattr(backend, "available", False):
        return []
    z = layer.zoom
    x0 = max(0, int(bbox[0] * z)); y0 = max(0, int(bbox[1] * z))
    x1 = min(layer.img.shape[1], int(np.ceil(bbox[2] * z)))
    y1 = min(layer.img.shape[0], int(np.ceil(bbox[3] * z)))
    if x1 - x0 < 20 or y1 - y0 < 20:
        return []
    crop = layer.img[y0:y1, x0:x1]
    words = backend.read(crop, numeric=numeric, mode="block")
    out: list[TextLine] = []
    for w in words:
        text = w.text.strip()
        if not text:
            continue
        wb = (bbox[0] + w.bbox[0] / z, bbox[1] + w.bbox[1] / z,
              bbox[0] + w.bbox[2] / z, bbox[1] + w.bbox[3] / z)
        out.append(TextLine(text, wb, True, False, round(float(w.confidence), 3),
                            engine=getattr(w, "engine", "")))
    return out


_LETTERS = re.compile(r"[A-Za-zА-Яа-яЁё]")
_PLAIN_NUMBER = re.compile(r"[\d\s.,'`\-–—]+")
_CYRILLIC = re.compile(r"[А-Яа-яЁё]")
# RapidOCR часто читает десятичную запятую как пробел: «23857,19» -> «23857 49».
# Это не разделитель тысяч (после пробела 1–2 цифры, не три).
_LOST_COMMA = re.compile(r"^[+-]?\d{2,}[\s\u00a0\u2009]+\d{1,2}$")
_HAS_DECIMAL = re.compile(r"^[+-]?\d+[.,]\d+$")
_DIGITS_ONLY = re.compile(r"\D")


def _legibility(text: str) -> int:
    """Буквы кириллицы минус нераспознанные знаки: чем больше, тем читаемее."""
    return len(_CYRILLIC.findall(text)) - 2 * text.count("?") - text.count("№") - text.count("%")


def _worth_rotation(text: str) -> bool:
    """Поворот имеет смысл, только если горизонтальное чтение не дало кириллицы.

    «Наименование профиля» уже прочитано — крутить незачем. «poroHbl» /
    «5 а 8 a}» — крутим.
    """
    letters = len(_CYRILLIC.findall(text))
    if letters < 3:
        return True
    # «ж ?Ф % К% № ?№»: кириллица есть, но знаков вопроса и мусора больше
    junk = text.count("?") + text.count("№") + text.count("%")
    return junk >= 2 and junk >= letters


def _lost_decimal_comma(text: str) -> bool:
    return bool(_LOST_COMMA.fullmatch(text.strip()))


_GRADE_TOKEN = re.compile(r"(?<![\w])[СCсc(\[]\s?(\d{3})(?:[-–](\d))?(?![\d])")


def _borrow_grade_digits(tess: list[TextLine], rapid: list[TextLine]) -> list[TextLine]:
    """В марке стали подставляет Tesseract цифры, прочитанные RapidOCR.

    Слова («С», «ГОСТ») у Tesseract вернее, цифры — у RapidOCR («C245-4»
    против «С215-4»). Меняются только три цифры марки и её индекс, и только
    если у обоих движков марка найдена ровно одна.
    """
    from dataclasses import replace
    if not rapid:
        return tess
    r = _GRADE_TOKEN.findall(" ".join(w.text for w in rapid))
    if len(r) != 1:
        return tess
    digits, idx = r[0]
    out: list[TextLine] = []
    done = False
    for w in tess:
        m = _GRADE_TOKEN.search(w.text)
        if m and not done:
            done = True
            new = w.text[:m.start(1)] + digits + w.text[m.end(1):]
            if idx and m.group(2) and m.group(2) != idx:
                pos = m.start(2) + (len(digits) - len(m.group(1)))
                new = new[:pos] + idx + new[pos + 1:]
            if new != w.text:
                w = replace(w, text=new)
        out.append(w)
    return out


def _strip_cell_border(img, max_frac: float = 0.12, pad: int = 24):
    """Срезает с краёв кропа строки/столбцы, занятые линовкой, и обводит белым.

    Кромка считается линовкой, если больше половины её пикселей — чернила
    (текст такой плотности не даёт). Проверяется не глубже `max_frac` размера
    с каждой стороны, чтобы не откусить буквы.
    """
    import cv2
    import numpy as np

    if img.ndim != 2 or img.shape[0] < 12 or img.shape[1] < 12:
        return img
    ink = img < 128
    h, w = ink.shape
    top, bottom, left, right = 0, h, 0, w
    lim_h, lim_w = int(h * max_frac), int(w * max_frac)
    while top < lim_h and ink[top].mean() > 0.5:
        top += 1
    while bottom > h - lim_h and ink[bottom - 1].mean() > 0.5:
        bottom -= 1
    while left < lim_w and ink[:, left].mean() > 0.5:
        left += 1
    while right > w - lim_w and ink[:, right - 1].mean() > 0.5:
        right -= 1
    # линия толщиной в пару пикселей после первой срезки оставляет «тень»:
    # снимаем ещё по 3 px там, где что-то срезали
    if top: top = min(top + 3, h)
    if bottom < h: bottom = max(bottom - 3, 0)
    if left: left = min(left + 3, w)
    if right < w: right = max(right - 3, 0)
    if bottom - top < 8 or right - left < 8:
        return img
    out = img[top:bottom, left:right]
    return cv2.copyMakeBorder(out, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)


def _resolve_engine(words: list[TextLine]) -> str:
    """Какому движку верить в ячейке, роль колонки которой не определена.

    Роли назначаются по тексту шапки, а на листах КМ шапка сама приходит из OCR
    с искажениями («Наименование» -> «Науменобание»), и колонка остаётся
    `unknown`. Отдать такие ячейки одному движку нельзя: у Tesseract массы
    теряют запятую («23212,8» -> «232128»), у RapidOCR любое слово превращается
    в латиницу.

    Считаем по варианту RapidOCR — сам текст у него недостоверен, но СТРУКТУРА
    достоверна: каждой букве оригинала он подбирает латинскую замену, каждой
    цифре — верную цифру.
      * три буквы и больше — это слова, читает Tesseract;
      * иначе перед нами число или обозначение размера («□140x5,5», «L 125x8»,
        «H60-845-0,8») — читает RapidOCR. Уступаем Tesseract, когда
        RapidOCR выдал не число, а Tesseract — чистое число: так '3869,3',
        прочитанное RapidOCR как «E'698E», не теряется. Ещё один случай:
        RapidOCR принял десятичную запятую за пробел, а Tesseract запятую
        сохранил («23857 49» vs «23857,19»).
    """
    rapid = " ".join(w.text for w in words if w.engine == "rapidocr").strip()
    if not rapid:
        return "tesseract"
    if len(_LETTERS.findall(rapid)) >= 3:
        return "tesseract"
    # Короткое слово без единой цифры («т», «шт», «№») — тоже слово, а не
    # обозначение: у RapidOCR оно выйдет латиницей («m»).
    if _LETTERS.search(rapid) and not any(ch.isdigit() for ch in rapid):
        return "tesseract"
    tess = " ".join(w.text for w in words if w.engine == "tesseract").strip()
    if not _PLAIN_NUMBER.fullmatch(rapid) and tess and _PLAIN_NUMBER.fullmatch(tess):
        return "tesseract"
    if _lost_decimal_comma(rapid) and tess and _HAS_DECIMAL.fullmatch(tess):
        return "tesseract"
    # RapidOCR потерял часть цифр («0,34» -> «'0»), а Tesseract прочитал
    # полное число с десятичным знаком: у Tesseract цифр больше — верим ему.
    if (tess and _HAS_DECIMAL.fullmatch(tess) and not _HAS_DECIMAL.fullmatch(rapid)
            and len(_DIGITS_ONLY.sub("", rapid)) < len(_DIGITS_ONLY.sub("", tess))):
        return "tesseract"
    return "rapidocr"


@dataclass
class CellReader:
    """Читает ячейки одной страницы из всех доступных источников."""
    page: fitz.Page
    text_lines: list[TextLine]
    layer: GlyphLayer | None = None
    ocr_backend: object | None = None
    # слова из растрового OCR по области; `size` используется как confidence
    ocr_words: list[TextLine] = field(default_factory=list)
    low_conf: float = 0.62
    stats: dict[str, int] = field(default_factory=dict)

    def _read_rotated(self, bbox: BBox, engine: str) -> tuple[str, float] | None:
        """Повторное чтение ячейки на кропе, повёрнутом на 90° по часовой.

        Подписи колонок «по элементам конструкций» («Колонны/Стойки», «Балки»,
        «Связи», «Прогоны») набраны снизу вверх. Общий вызов OCR на область
        таблицы разбирает их на одиночные знаки («Балки» -> «5 а 8 a}»), а тот
        же кроп, повёрнутый по часовой стрелке, Tesseract читает верно.
        Против часовой не пробуем: так подпись встаёт вверх ногами
        («Балки» -> «ихциеа») — направление письма в чертёжных шапках одно.
        """
        import cv2
        import numpy as np

        layer = self.layer
        if layer is None or self.ocr_backend is None:
            return None
        z = layer.zoom
        x0 = max(0, int(bbox[0] * z)); y0 = max(0, int(bbox[1] * z))
        x1 = min(layer.img.shape[1], int(np.ceil(bbox[2] * z)))
        y1 = min(layer.img.shape[0], int(np.ceil(bbox[3] * z)))
        if x1 - x0 < 12 or y1 - y0 < 24:
            return None
        crop = cv2.rotate(layer.img[y0:y1, x0:x1], cv2.ROTATE_90_CLOCKWISE)
        # Линии границ ячейки, попавшие в кроп, для Tesseract — «буквы» во всю
        # высоту, и он не отдаёт ни слова («Фонари» читалось пустым). Срезаем
        # кромки с линовкой и добавляем белое поле.
        crop = _strip_cell_border(crop)
        # Гибрид на кропе ячейки гоняет RapidOCR зря: кириллицу читает Tesseract.
        tess = getattr(self.ocr_backend, "_tess", None)
        backend = tess if (tess is not None and getattr(tess, "available", False)) \
            else self.ocr_backend
        words = [w for w in backend.read(crop, mode="block") if w.text.strip()]
        if engine:
            own = [w for w in words if getattr(w, "engine", "") in (engine, "")]
            words = own or words
        if not words:
            return None
        # Подпись из двух строк («Связи,» / «распорки») после поворота лежит
        # двумя горизонтальными строками. Сортировка всех слов только по x
        # перемешивала их («распорки Связи,», «базы Колонны, колонн»):
        # короткая первая строка отцентрована и начинается правее второй.
        # Собираем построчно, строки — сверху вниз (= слева направо в исходнике).
        lines = _group_words(words)
        text = "\n".join(" ".join(w.text.strip() for w in L) for L in lines)
        return (text, min(w.confidence for w in words)) if text.strip() else None

    def read(self, bbox: BBox, row: int, col: int, charset: str = "any",
             row_span: int = 1, col_span: int = 1, page_no: int = 1,
             prefer_ocr: bool = False, ocr_engine: str = "") -> Cell:
        """`prefer_ocr` — не доверять векторному распознавателю в этом блоке.

        Нужен для листов, где текст «взорван» в геометрию чертёжным
        одноштриховым шрифтом: глифы есть, но шаблонами читаются плохо, и
        результат растрового OCR оказывается лучше.

        `ocr_engine` — какому движку верить в этой ячейке, когда OCR был
        гибридным и слова помечены (`hybrid`, см. `ocr_backends`): 'tesseract',
        'rapidocr' либо 'auto' — решить по содержимому. Пусто — берём всё.
        """
        # Строка текстового слоя принадлежит ячейке, если лежит в ней целиком
        # или большей частью (> 60%, чтобы одна строка не досталась двум
        # ячейкам). На file-45 первая строка «В том числе по маркам» в
        # объединённой ячейке чуть заходила на линовку сверху и терялась —
        # оставалось «или наименованиям:», и разбивка по маркам не находилась.
        tl = [t for t in self.text_lines
              if _inside(t.bbox, bbox) or _overlap_frac(t.bbox, bbox) > 0.6]
        vec_lines: list[tuple[BBox, str, float, list[GlyphResult]]] = []

        def read_vector() -> None:
            comps = self.layer.components_in(bbox)
            # компоненты, накрытые строкой текстового слоя, не распознаём заново
            if tl and comps:
                comps = [c for c in comps if not any(_overlaps(c, t.bbox) for t in tl)]
            if comps:
                cs = CHARSETS.get(charset, CHARSET_TEXT)
                comps = merge_strokes(merge_counters(comps))
                for L in group_lines(merge_diacritics(comps)):
                    txt, glyphs = _read_line(self.layer, L, cs)
                    if not txt.strip():
                        continue
                    lb = (min(b[0] for b in L), min(b[1] for b in L),
                          max(b[2] for b in L), max(b[3] for b in L))
                    conf = min((g.confidence for g in glyphs), default=0.0)
                    vec_lines.append((lb, txt.strip(), conf, glyphs))

        if self.layer is not None and not prefer_ocr:
            read_vector()

        # РАСТРОВАЯ ВЕТКА. Слова, распознанные ОДНИМ вызовом OCR на всю область
        # таблицы (см. `ocr_region`), раскладываются по ячейкам по координатам.
        # Вызывать OCR на каждую ячейку нельзя: на листе-скане это 192 вызова и
        # 265 с против нескольких секунд, и распознаётся хуже — движку нужен
        # контекст строки.
        ocr_lines: list[tuple[BBox, str, float]] = []
        engine, ocr_ready = ocr_engine, False
        alt_text = ""
        if (prefer_ocr or (not tl and not vec_lines)) and self.ocr_words:
            # Слово принадлежит ячейке, если лежит в ней целиком ИЛИ большей
            # частью. Раньше перекрытие проверялось только когда строго внутри
            # не было ничего: рамка RapidOCR выступала за линовку на доли
            # пункта и отбрасывалась, а рамка Tesseract по той же строке
            # (обрезанная по полосе) оставалась — и в гибриде ячейка получала
            # «OHO» вместо «0,340», «TT» вместо «37,12» (file-14).
            inside = [w for w in self.ocr_words
                      if _inside(w.bbox, bbox, tol=0.5) or _overlap_frac(w.bbox, bbox) >= 0.5]
            # Тонкая служебная строка номеров (~11 pt): бокс OCR чуть вылезает
            # за ячейку, и при строгом _inside она оставалась пустой.
            if not inside:
                inside = [w for w in self.ocr_words
                          if _overlap_frac(w.bbox, bbox) >= 0.45]
            if ocr_engine:
                engine = (_resolve_engine(inside) if ocr_engine == "auto"
                          else ocr_engine)
                ocr_ready = True
                # Слова «своего» движка плюс непомеченные (обычный, негибридный
                # OCR). Если свой в этой ячейке не прочитал ничего, берём чужой
                # вариант: пустая ячейка хуже спорной.
                own = [w for w in inside if w.engine in (engine, "")]
                alt_text = " ".join(w.text for w in inside if w.engine and w.engine != engine).strip()
                if engine == "tesseract" and own:
                    # Марку стали читает Tesseract (слова), но цифры в ней
                    # точнее у RapidOCR: «С215-4» против «C245-4».
                    own = _borrow_grade_digits(own, [w for w in inside if w.engine == "rapidocr"])
                inside = own or inside
            for line in _group_words(inside):
                lb = (min(w.bbox[0] for w in line), min(w.bbox[1] for w in line),
                      max(w.bbox[2] for w in line), max(w.bbox[3] for w in line))
                ocr_lines.append((lb, " ".join(w.text for w in line),
                                  min(w.size for w in line)))

        # OCR по области не дал в этой ячейке ни слова, а векторные глифы в ней
        # есть — читаем их шаблонами. Пустая ячейка хуже спорной: раньше в
        # блоке «шапка спорная -> OCR» такие числа молча пропадали.
        if prefer_ocr and not ocr_lines and not tl and self.layer is not None:
            read_vector()

        items: list[tuple[float, float, str, float, str, list[GlyphResult]]] = []
        for t in tl:
            if t.horizontal:
                key = (t.bbox[1], t.bbox[0])
            else:
                # Вертикальная надпись шапки: строки идут перпендикулярно
                # направлению письма. При dir=(0,-1) (текст читается снизу
                # вверх) следующая строка правее, поэтому порядок по возрастанию
                # x. Иначе «Профнастил покрытия» собиралось как
                # «покрытия Профнастил».
                key = ((t.bbox[0], t.bbox[1]) if t.direction[1] <= 0
                       else (-t.bbox[0], t.bbox[1]))
            items.append((key[0], key[1], t.text, 1.0, "text_layer", []))
        for lb, txt, conf, glyphs in vec_lines:
            items.append((lb[1], lb[0], txt, conf, "vector_glyph", glyphs))
        for lb, txt, conf in ocr_lines:
            items.append((lb[1], lb[0], txt, conf, "ocr", []))
        items.sort(key=lambda it: (round(it[0], 1), it[1]))

        # Строки, целиком состоящие из нераспознанных знаков, убираем: символ
        # типа профиля («Ι» у двутавра, «[» у швеллера) нарисован отдельными
        # штрихами, расположенными друг над другом, и давал три строки «?»
        # («25Ш1 ? ? ?» вместо «Ι 25Ш1»). Сам факт фиксируется в notes, а
        # ячейка помечается на проверку — молча терять содержимое нельзя.
        unreadable = sum(1 for it in items if _ONLY_MARKS.fullmatch(it[2]))
        if unreadable and unreadable < len(items):
            items = [it for it in items if not _ONLY_MARKS.fullmatch(it[2])]

        rot_note = ""
        if (not items and prefer_ocr and self.ocr_words and self.ocr_backend is not None
                and should_try_rotation(bbox, row_span)):
            # Высокая ячейка, в которой OCR по области не нашёл ни слова:
            # подпись набрана снизу вверх («Прогоны», «Связи покрытия»), и
            # детектор строк её не видит. Читаем сразу с поворотом — раньше
            # такие ячейки оставались пустыми, а имена элементов терялись.
            alt = self._read_rotated(bbox, engine)
            if alt and _CYRILLIC.search(alt[0]):
                rot_note = "прочитано с поворотом на 90°; без поворота пусто"
                items = [(0.0, 0.0, alt[0], alt[1], "ocr", [])]
        if not items:
            self.stats["empty"] = self.stats.get("empty", 0) + 1
            return Cell(row=row, col=col, row_span=row_span, col_span=col_span,
                        text="", bbox=bbox, page=page_no, confidence=1.0,
                        source="none", value_kind="empty")

        text = "\n".join(it[2] for it in items)
        conf = min(it[3] for it in items)
        srcs = {it[4] for it in items}
        source = "mixed" if len(srcs) > 1 else next(iter(srcs))
        rotated_note = rot_note

        # ВЕРТИКАЛЬНАЯ ПОДПИСЬ. Ячейка заметно выше, чем шире, — вероятно,
        # надпись набрана снизу вверх. Читаем её ещё раз с поворотом и берём
        # тот вариант, где кириллицы больше: горизонтальное чтение вертикальной
        # подписи даёт либо одиночные знаки («Балки» -> «5 а 8 a}»), либо
        # латинскую кальку RapidOCR («Прогоны» -> «poroHbl»). Обычную ячейку
        # правило не трогает: там поворот кириллицы не прибавит.
        # Та же подпись на векторном листе, где OCR по области ничего не дал,
        # читалась шаблонами глифов и превращалась в «?+ ?ж», «ж ?Ф % К%»
        # (Estakada, file-4, file-7): вертикальные штрихи букв в шаблоны
        # не ложатся. Кашу из глифов тоже перечитываем с поворотом.
        glyph_garbage = (srcs == {"vector_glyph"} and self.ocr_backend is not None
                         and (text.count("?") >= 2 or conf < self.low_conf))
        if (((ocr_ready and srcs == {"ocr"} and _worth_rotation(text)) or glyph_garbage)
                and should_try_rotation(bbox, row_span)):
            alt = self._read_rotated(bbox, engine)
            # Сравниваем «читаемость»: буквы кириллицы минус знаки вопроса.
            # Глифовая каша «?л ? №ж ?ф ?У %» набирает буквы, но и вопросов
            # столько же; «Связи, распорки» без единого вопроса выигрывает.
            if alt and _legibility(alt[0]) > _legibility(text) and "?" not in alt[0]:
                rotated_note = "прочитано с поворотом на 90°; без поворота: %r" % text
                text, conf = alt[0], alt[1]
                items = [(0.0, 0.0, text, conf, "ocr", [])]
        glyphs = [Glyph(g.char, tuple(round(v, 2) for v in g.bbox), g.confidence,
                        g.alternatives)
                  for it in items for g in it[5]]
        self.stats[source] = self.stats.get(source, 0) + 1
        cell = Cell(row=row, col=col, row_span=row_span, col_span=col_span,
                    text=text, bbox=bbox, page=page_no, confidence=round(conf, 3),
                    source=source, glyphs=glyphs, alt_text=alt_text)
        if rotated_note:
            cell.notes.append(rotated_note)
        if conf < self.low_conf:
            cell.requires_review = True
            cell.notes.append("low OCR confidence")
        if "?" in text or unreadable:
            cell.requires_review = True
            cell.notes.append(
                "нераспознанных элементов: %d (возможен символ типа профиля)"
                % max(unreadable, text.count("?")))
        if looks_broken(text):
            cell.requires_review = True
            cell.notes.append("text layer encoding not repaired")
        return cell
