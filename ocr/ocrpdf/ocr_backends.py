# -*- coding: utf-8 -*-
"""Растровый OCR — РЕЗЕРВНЫЙ путь для страниц-сканов.

Для тестового файла он не нужен: значения либо лежат в текстовом слое, либо
восстанавливаются из векторов (`glyph_ocr`) точно. Модуль существует, чтобы
конвейер работал и со сканированными листами.

Замеры на этом документе (важно для выбора):
  * `rapidocr-onnxruntime` (PP-OCRv4, CPU, ONNX) — ставится одной командой,
    но БАЗОВАЯ МОДЕЛЬ НЕ ЗНАЕТ КИРИЛЛИЦЫ: «Итого» -> «MTOrO»,
    «Рельсы крановые» -> «PenbCbl KpaHOBble». Цифры читает верно ('13,04').
    Пригодна только для числовых колонок.
  * `pytesseract` с traineddata `rus` кириллицу знает: наименования профилей
    читает верно, но обозначения и массы разбирает заметно хуже RapidOCR и
    теряет строки. Требует внешнего бинарника Tesseract.
  * `hybrid` — оба сразу: наименования берём у Tesseract, числовые колонки у
    RapidOCR. Это режим по умолчанию для `auto`, когда доступны оба движка.

Ни один бэкенд не обращается в сеть во время работы: модели лежат локально.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import numpy as np


@dataclass
class OcrWord:
    text: str
    bbox: tuple[float, float, float, float]     # в координатах переданного кропа
    confidence: float
    engine: str = ""        # каким движком прочитано (нужно гибриду)


class OcrBackend:
    name = "none"
    available = False

    def read(self, img: np.ndarray, numeric: bool = False,
             mode: str = "block") -> list[OcrWord]:
        """`mode`: 'block' — область таблицы, 'line' — одна строка/ячейка."""
        raise NotImplementedError


_RAPID_ENGINE = None
_RAPID_ERROR: Exception | None = None
_RAPID_TRIED = False
_PICKED: dict[str, OcrBackend] = {}


def rapidocr_importable() -> bool:
    """Движок установлен? Без загрузки ONNX-моделей (это несколько секунд)."""
    try:
        import rapidocr_onnxruntime  # noqa: F401
        return True
    except Exception:
        return False


def _shared_rapidocr():
    """Один экземпляр RapidOCR на процесс: модели грузятся ~несколько секунд."""
    global _RAPID_ENGINE, _RAPID_ERROR, _RAPID_TRIED
    if _RAPID_TRIED:
        return _RAPID_ENGINE
    _RAPID_TRIED = True
    try:
        from rapidocr_onnxruntime import RapidOCR
        # Классификатор поворота на 180° отключён: на листах КМ текста «вверх
        # ногами» не бывает (поворот на 90° конвейер делает сам), а на коротких
        # обозначениях он ошибался — «-40» переворачивался и читался «07-».
        _RAPID_ENGINE = RapidOCR(use_cls=False)
    except Exception as exc:                        # pragma: no cover
        _RAPID_ERROR = exc
        _RAPID_ENGINE = None
    return _RAPID_ENGINE


@dataclass
class RapidOcrBackend(OcrBackend):
    """PP-OCRv4 через onnxruntime. CPU, офлайн."""
    name: str = "rapidocr"
    available: bool = False
    _engine: object = None
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._engine = _shared_rapidocr()
        if self._engine is not None:
            self.available = True
            self.warnings.append(
                "базовая модель RapidOCR не поддерживает кириллицу; "
                "использовать только для числовых колонок")
        elif _RAPID_ERROR is not None:              # pragma: no cover
            self.warnings.append("rapidocr недоступен: %s" % _RAPID_ERROR)
        else:
            self.warnings.append("rapidocr недоступен")

    def read(self, img: np.ndarray, numeric: bool = False,
             mode: str = "block") -> list[OcrWord]:
        if not self.available:
            return []
        if img.ndim == 2:
            img = np.stack([img] * 3, axis=2)
        res, _ = self._engine(img)
        out: list[OcrWord] = []
        for box, text, conf in (res or []):
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            out.append(OcrWord(text, (min(xs), min(ys), max(xs), max(ys)), float(conf)))
        return out


_EXE = "tesseract.exe"
TESSERACT_PATHS = [
    os.path.join(r"C:\Program Files\Tesseract-OCR", _EXE),
    os.path.join(r"D:\dev\Tesseract-OCR", _EXE),
    os.path.join(r"C:\Program Files (x86)\Tesseract-OCR", _EXE),
    "/usr/bin/tesseract", "/usr/local/bin/tesseract", "/opt/homebrew/bin/tesseract",
]


def _project_tessdata() -> str:
    """Локальная папка tessdata в корне проекта, если она есть.

    Языковые файлы держим рядом с кодом, а не в Program Files: не нужны права
    администратора, проект остаётся переносимым и целиком уезжает в Docker-образ.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "tessdata")
    return path if os.path.isdir(path) else ""


def _find_tesseract_exe() -> str:
    """Путь к бинарнику, если его нет в PATH текущего процесса."""
    for path in TESSERACT_PATHS:
        if os.path.isfile(path):
            return path
    local = os.environ.get("LOCALAPPDATA")
    if local:
        cand = os.path.join(local, "Programs", "Tesseract-OCR", "tesseract.exe")
        if os.path.isfile(cand):
            return cand
    return ""


@dataclass
class TesseractBackend(OcrBackend):
    """Tesseract с языками rus+eng. Требует внешний бинарник."""
    name: str = "tesseract"
    available: bool = False
    lang: str = "rus+eng"
    exe: str = ""
    tessdata: str = ""          # своя папка с языковыми файлами
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        try:
            import pytesseract
        except Exception as exc:                        # pragma: no cover
            self.warnings.append("нет модуля pytesseract: %s" % exc)
            return
        self._pt = pytesseract
        try:
            pytesseract.get_tesseract_version()
            self.available = True
        except Exception:
            # Установщик дописывает PATH, но уже запущенные процессы его не
            # видят — без этого поиска пришлось бы перезапускать терминал.
            found = _find_tesseract_exe()
            if not found:
                self.warnings.append(
                    "tesseract не найден: установите его "
                    "(winget install UB-Mannheim.TesseractOCR)")
                return
            pytesseract.pytesseract.tesseract_cmd = found
            try:
                pytesseract.get_tesseract_version()
                self.available = True
                self.exe = found
            except Exception as exc:                    # pragma: no cover
                self.warnings.append("tesseract не запускается (%s): %s" % (found, exc))
                return
        # Наличие бинарника ещё не значит, что установлен РУССКИЙ язык.
        # Без tessdata `rus` кириллица получится такой же латинской кашей, как
        # у RapidOCR, поэтому проверяем явно и переключаемся на английский,
        # громко предупреждая.
        # Путь к языковым файлам передаём ПЕРЕМЕННОЙ ОКРУЖЕНИЯ, а не флагом
        # --tessdata-dir: pytesseract разбивает config по пробелам, и путь с
        # пробелами (тем более с кириллицей) разваливается на части.
        self.tessdata = _project_tessdata()
        if self.tessdata:
            os.environ["TESSDATA_PREFIX"] = self.tessdata
        try:
            langs = set(self._pt.get_languages(config=""))
        except Exception:                               # pragma: no cover
            langs = set()
        if langs and "rus" not in langs:
            self.lang = "eng"
            self.warnings.append(
                "не установлен языковой файл rus.traineddata — кириллица будет "
                "распознана неверно; доустановите русский язык Tesseract")
        elif langs:
            self.warnings.append("языки: %s" % "+".join(
                sorted(l for l in langs if l in ("rus", "eng"))))

    def read(self, img: np.ndarray, numeric: bool = False,
             mode: str = "block") -> list[OcrWord]:
        if not self.available:
            return []
        # psm 6 — однородный блок текста (область таблицы), psm 7 — одна строка.
        # Раньше psm 7 стоял всегда, и на области таблицы Tesseract возвращал
        # мусор: он пытался прочитать её как одну строку.
        cfg = "--psm 6" if mode == "block" else "--psm 7"
        if numeric:
            # важно: не давать OCR «улучшать» инженерные обозначения
            cfg += " -c tessedit_char_whitelist=0123456789,.-"
        # Кроп ячейки/подписи чертёжным курсивом (в т.ч. повёрнутый на 90°)
        # читается и как есть, и выпрямленным — берётся вариант, которому
        # Tesseract верит больше: так «Байки» становится «Балки», «ndDHOO» —
        # «Прогоны», а прямой шрифт ничего не теряет. На кропе таблицы с
        # линовкой оценка наклона даёт ~0°, второго чтения нет.
        def run(image, shear, off):
            try:
                data = self._pt.image_to_data(image, lang=self.lang, config=cfg,
                                              output_type=self._pt.Output.DICT)
            except Exception as exc:
                # Сообщения Tesseract на Windows приходят в кодировке консоли, и
                # pytesseract сам падает при их декодировании — поэтому текст
                # ошибки приводим к безопасному виду и продолжаем без OCR.
                self.warnings.append("сбой tesseract: %s" % type(exc).__name__)
                return None
            words: list[OcrWord] = []
            for i, text in enumerate(data["text"]):
                if not text.strip():
                    continue
                conf = float(data["conf"][i])
                left, top = data["left"][i], data["top"][i]
                if shear:
                    left = left - shear * (top + data["height"][i] / 2.0) - off
                words.append(OcrWord(
                    text, (left, top, left + data["width"][i], top + data["height"][i]),
                    max(0.0, conf / 100.0)))
            return words

        out = run(img, 0.0, 0.0)
        if out is None:
            return []
        if mode == "block" and img.ndim == 2 and img.shape[0] >= 40:
            slant = _estimate_slant([img[2:-2, 2:-2]])
            if abs(slant) >= self.MIN_SLANT_DEG:
                shear = float(np.tan(np.radians(slant)))
                straight = run(_deslant(img, shear), shear, max(0.0, -shear * img.shape[0]))
                if straight is not None and _words_score(straight) > _words_score(out):
                    out = straight
        return out

    # Монтаж строк: высота строки и белый зазор между ними, px.
    STRIP_H = 64
    STRIP_PAD = 26
    # Наклон чертёжного курсива (ISOCPEUR Italic ~15°), начиная с которого
    # полосы выпрямляются перед чтением. Прямой шрифт (оценка около 0°) не трогаем.
    MIN_SLANT_DEG = 7.0
    last_slant_deg: float = 0.0

    def read_strips(self, img: np.ndarray,
                    boxes: list[tuple[float, float, float, float]]) -> list[OcrWord]:
        """Читает ЗАРАНЕЕ НАЙДЕННЫЕ строки одним вызовом tesseract.

        На кропе таблицы Tesseract половину строк просто не находит: «ИТОГО:»
        в узкой ячейке он пропускает при любом psm, хотя ту же строку отдельным
        кропом читает без единой ошибки. Поэтому строки ищет детектор RapidOCR,
        а мы собираем их в одну картинку — по строке в ряд, с белыми зазорами.
        Для Tesseract это уже однородный блок текста, и psm 6 разбирает его
        целиком.

        Один вызов вместо сотни: на тестовом листе 0,9 с против 12,6 с —
        процесс tesseract стартует дольше, чем читает строку.
        """
        import cv2

        if not self.available or not boxes:
            return []
        H, PAD = self.STRIP_H, self.STRIP_PAD
        strips: list[tuple[np.ndarray, float, tuple[float, float, float, float]]] = []
        for bx in boxes:
            x0 = max(0, int(bx[0]) - 4); y0 = max(0, int(bx[1]) - 4)
            x1 = min(img.shape[1], int(bx[2]) + 4); y1 = min(img.shape[0], int(bx[3]) + 4)
            if x1 - x0 < 4 or y1 - y0 < 4:
                continue
            sub = img[y0:y1, x0:x1]
            if sub.ndim == 3:
                sub = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY)
            k = H / sub.shape[0]
            strips.append((cv2.resize(sub, (max(8, int(sub.shape[1] * k)), H),
                                      interpolation=cv2.INTER_AREA),
                           k, (x0, y0, x1, y1)))
        if not strips:
            return []
        # Чертёжный курсив Tesseract читает в кашу («Итого» -> «Мm020»,
        # «стальные» -> «CMO/bHbIE»): модель обучена на прямых шрифтах. Наклон
        # оценивается по самим полосам (линовки таблицы в них нет); если он
        # заметный, полосы читаются ещё раз выпрямленными, и для каждой строки
        # берётся вариант, которому Tesseract верит больше. На листе с
        # растровой таблицей курсивом (file-14) это даёт «Уголки стальные
        # горячекатаные неравнополочные» вместо «Y20/KU CMO/bHbIE», а прямой
        # шрифт и штамп ничего не теряют.
        slant = _estimate_slant([st for st, _, _ in strips])
        self.last_slant_deg = slant

        def run(variant, shear, off):
            width = max(st.shape[1] for st, _, _ in variant) + 20
            canvas = np.full((len(variant) * (H + PAD) + PAD, width), 255, np.uint8)
            offsets: list[int] = []
            y = PAD
            for st, _, _ in variant:
                canvas[y:y + H, 10:10 + st.shape[1]] = st
                offsets.append(y)
                y += H + PAD
            try:
                data = self._pt.image_to_data(canvas, lang=self.lang, config="--psm 6",
                                              output_type=self._pt.Output.DICT)
            except Exception as exc:
                self.warnings.append("сбой tesseract: %s" % type(exc).__name__)
                return None
            got: dict[int, list[OcrWord]] = {}
            for i, text in enumerate(data["text"]):
                if not text.strip():
                    continue
                top, height = data["top"][i], data["height"][i]
                cy = top + height / 2.0
                j = min(range(len(offsets)), key=lambda n: abs(cy - (offsets[n] + H / 2.0)))
                if abs(cy - (offsets[j] + H / 2.0)) > (H + PAD) / 2.0:
                    continue                       # слово не легло ни на одну полосу
                _, k, (bx0, by0, _, by1) = variant[j]
                # Полоса — точная копия кропа, уменьшенная в k раз: координаты
                # возвращаются обратным пересчётом, без потери привязки к ячейке.
                # После выпрямления точка (x, y) стоит в x + shear*y + off.
                dx = (shear * (cy - offsets[j]) + off) if shear else 0.0
                x0 = bx0 + (data["left"][i] - 10 - dx) / k
                x1 = x0 + data["width"][i] / k
                y0 = by0 + (top - offsets[j]) / k
                y1 = y0 + height / k
                got.setdefault(j, []).append(
                    OcrWord(text, (x0, max(by0, y0), x1, min(by1, y1)),
                            max(0.0, float(data["conf"][i]) / 100.0)))
            return got

        plain = run(strips, 0.0, 0.0)
        if plain is None:
            return []
        chosen = plain
        if abs(slant) >= self.MIN_SLANT_DEG:
            shear = float(np.tan(np.radians(slant)))
            off = max(0.0, -shear * H)
            straight = run([(_deslant(st, shear), k, box) for st, k, box in strips], shear, off)
            if straight is not None:
                chosen = {}
                for j in range(len(strips)):
                    a, b = plain.get(j, []), straight.get(j, [])
                    chosen[j] = b if _words_score(b) > _words_score(a) else a
        return [w for j in sorted(chosen) for w in chosen[j]]


_CYR_LETTERS = __import__("re").compile(r"[А-Яа-яЁё]")


def _words_score(words: list) -> float:
    """Насколько верить набору слов одной строки/кропа: средняя уверенность
    Tesseract, взвешенная длиной слова, плюс небольшая премия за кириллицу
    (латинская каша на русском листе — признак ошибки)."""
    if not words:
        return -1.0
    total = sum(len(w.text) for w in words) or 1
    conf = sum(w.confidence * len(w.text) for w in words) / total
    letters = sum(1 for w in words for ch in w.text if ch.isalpha()) or 1
    cyr = sum(len(_CYR_LETTERS.findall(w.text)) for w in words) / letters
    return conf + 0.1 * cyr


def _estimate_slant(strips: list[np.ndarray], max_strips: int = 48,
                    max_abs_deg: float = 32.0) -> float:
    """Угол наклона письма по полосам строк, градусы (положительный — вправо).

    У прямого шрифта стойки букв вертикальны, у курсива наклонены на общий
    угол. Направление штриха перпендикулярно градиенту яркости на его кромке,
    поэтому гистограмма углов градиента (с весом по его величине) в окне
    ±32° от горизонтали имеет пик ровно на угле наклона стоек. Горизонтальные
    перекладины (градиент вертикальный) в окно не попадают, кривые размазаны
    по всему окну и пик не сдвигают. Прямой текст даёт около 0°.
    """
    import cv2

    bins = np.zeros(int(2 * max_abs_deg) + 1, np.float64)   # шаг 1°
    used = 0
    for st in strips[:max_strips]:
        if st.ndim == 3:
            st = cv2.cvtColor(st, cv2.COLOR_BGR2GRAY)
        if st.shape[0] < 8 or st.shape[1] < 8:
            continue
        g = cv2.GaussianBlur(st, (3, 3), 0).astype(np.float32)
        gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
        mag = np.hypot(gx, gy)
        if not np.isfinite(mag).all() or mag.max() <= 0:
            continue
        # Линовка таблицы в кропе (вертикальные линии длиной от половины
        # высоты) вертикальна всегда и перетянула бы пик к 0°: такие штрихи
        # из оценки исключаются вместе с их кромками, а порог силы градиента
        # считается уже без них — иначе тонкие штрихи букв до него не дотягивали.
        _, ink = cv2.threshold(st, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
        vk = max(8, int(st.shape[0] * 0.5))
        rul = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, vk)))
        keep = np.ones(mag.shape, bool)
        if rul.any():
            rul = cv2.dilate(rul, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3)))
            keep = rul == 0
        if not keep.any() or mag[keep].max() <= 0:
            continue
        strong = keep & (mag > 0.25 * mag[keep].max())
        if strong.sum() < 40:
            continue
        # угол градиента, сложенный в (-90, 90]: штрих, наклонённый вправо на
        # θ, даёт градиент под углом θ к горизонтали
        ang = np.degrees(np.arctan2(gy[strong], gx[strong]))
        ang = np.where(ang > 90.0, ang - 180.0, ang)
        ang = np.where(ang <= -90.0, ang + 180.0, ang)
        sel = np.abs(ang) <= max_abs_deg
        if not sel.any():
            continue
        idx = np.rint(ang[sel] + max_abs_deg).astype(int)
        np.add.at(bins, idx, mag[strong][sel])
        used += 1
    if used < 1 or bins.sum() <= 0:
        return 0.0
    # сглаживание ±2° и параболическое уточнение пика
    k = np.array([1.0, 2.0, 3.0, 2.0, 1.0]); k /= k.sum()
    sm = np.convolve(bins, k, mode="same")
    p = int(np.argmax(sm))
    peak = float(p)
    if 0 < p < len(sm) - 1:
        a, b, c = sm[p - 1], sm[p], sm[p + 1]
        den = a - 2 * b + c
        if den < 0:
            peak += 0.5 * (a - c) / den
    return round(peak - max_abs_deg, 1)


def _deslant(strip: np.ndarray, shear: float) -> np.ndarray:
    """Сдвигает полосу так, что наклонные штрихи становятся вертикальными.

    x' = x + shear*y (+ смещение, если shear < 0, чтобы ничего не ушло за левый
    край); ширина растёт на |shear|*H. Для письма вправо shear > 0: верх стоит,
    низ уезжает вправо.
    """
    import cv2

    h, w = strip.shape[:2]
    pad = int(abs(shear) * h) + 1
    M = np.float32([[1.0, shear, (-shear * h if shear < 0 else 0.0)], [0.0, 1.0, 0.0]])
    return cv2.warpAffine(strip, M, (w + pad, h), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=255)


@dataclass
class HybridOcrBackend(OcrBackend):
    """RapidOCR и Tesseract по одному кропу: числа от первого, кириллица от второго.

    На листах КМ каждый движок силён ровно в своей половине таблицы. RapidOCR
    точно читает обозначения и массы ('180×140x5', '5112,01'), но его базовый
    словарь без кириллицы превращает «ИТОГО» в «NTOFO». Tesseract с `rus`
    читает наименования, но на колонках размеров и масс выдаёт обрывки и
    теряет строки.

    Выбирать между ними по виду самого текста ненадёжно: «С255 по ГОСТ
    27772-2021» на две трети состоит из цифр, а «180×140x5» — не только из них.
    Поэтому здесь мы лишь помечаем каждое слово движком, а решение принимает
    конвейер по РОЛИ КОЛОНКИ, которую он и так определяет (см. `ENGINE_BY_ROLE`).
    """
    name: str = "hybrid"
    available: bool = False
    warnings: list[str] = field(default_factory=list)
    _rapid: object = None
    _tess: object = None

    def __post_init__(self) -> None:
        self._rapid = RapidOcrBackend()
        self._tess = TesseractBackend()
        self.available = bool(self._rapid.available and self._tess.available)
        for be in (self._rapid, self._tess):
            for w in be.warnings:
                # предупреждение RapidOCR про кириллицу здесь не к месту:
                # кириллицу в гибриде читает не он.
                if "кириллиц" in w and be is self._rapid:
                    continue
                self.warnings.append("%s: %s" % (be.name, w))
        if not self.available:
            missing = [be.name for be in (self._rapid, self._tess) if not be.available]
            self.warnings.append("гибрид недоступен, нет: %s" % ", ".join(missing))

    def read(self, img: np.ndarray, numeric: bool = False,
             mode: str = "block") -> list[OcrWord]:
        if not self.available:
            return []
        rapid = self._rapid.read(img, numeric=numeric, mode=mode)
        if not rapid:
            return [OcrWord(w.text, w.bbox, w.confidence, self._tess.name)
                    for w in self._tess.read(img, numeric=numeric, mode=mode)]
        out = [OcrWord(w.text, w.bbox, w.confidence, self._rapid.name) for w in rapid]
        # Строки ищет детектор RapidOCR — он находит и то, что Tesseract на
        # таблице пропускает; Tesseract перечитывает ИХ ЖЕ рамки. Побочная
        # выгода: у обоих движков одна и та же геометрия, и слова гарантированно
        # попадают в одну и ту же ячейку.
        for w in self._tess.read_strips(img, [w.bbox for w in rapid]):
            out.append(OcrWord(w.text, w.bbox, w.confidence, self._tess.name))
        return out


def pick_backend(prefer: str = "auto") -> OcrBackend:
    """Возвращает доступный бэкенд. `prefer`: auto|hybrid|rapidocr|tesseract|none.

    Экземпляр кэшируется: RapidOCR не должен заново грузить ONNX на каждой
    странице, а веб при опросе capabilities — не создавать третий движок.
    """
    if prefer == "none":
        return OcrBackend()
    cached = _PICKED.get(prefer)
    if cached is not None:
        return cached
    order = {"auto": ["hybrid", "tesseract", "rapidocr"],
             "hybrid": ["hybrid"],
             "rapidocr": ["rapidocr"], "tesseract": ["tesseract"]}.get(prefer, [])
    ctor = {"hybrid": HybridOcrBackend, "tesseract": TesseractBackend,
            "rapidocr": RapidOcrBackend}
    picked: OcrBackend = OcrBackend()
    for name in order:
        be = ctor[name]()
        if be.available:
            picked = be
            break
    _PICKED[prefer] = picked
    return picked
