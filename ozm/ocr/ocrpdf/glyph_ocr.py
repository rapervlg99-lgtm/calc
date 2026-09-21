# -*- coding: utf-8 -*-
"""Детерминированное распознавание «взорванного» векторного текста.

ЧТО ЭТО ЗА ТЕКСТ
----------------
В тестовом PDF значения масс и обозначения профилей НЕ являются текстом: они
разложены в ~325 000 микро-отрезков (`l`-items) плюс мелкие залитые `re`
(точки и дефисы) — типичный результат экспорта из AutoCAD/Revit, когда шрифт
«взрывается» в геометрию. Текстового слоя для них нет.

ПОЧЕМУ ШАБЛОНЫ, А НЕ НЕЙРОСЕТЕВОЙ OCR
-------------------------------------
Растр здесь синтетический: он получается рендером векторов, то есть без шума,
перекосов и JPEG-артефактов, с любым нужным DPI. Начертание — обычный Arial.
В такой постановке сопоставление с шаблонами, отрендеренными ИЗ ТОГО ЖЕ шрифта
и в том же кегле, точнее общего OCR и вдобавок:
  * полностью офлайн, без загрузки моделей;
  * честный confidence (IoU + отрыв от второго кандидата);
  * точные координаты каждого символа;
  * никакого «умного» автокорректа, ломающего `C255-4` или `Гн.□100x4,5`.

Проверено на этом файле: RapidOCR/PP-OCR базовой модели не знает кириллицы
(`Итого` -> `MTOrO`), поэтому для русских проектных таблиц он непригоден.
Растровый OCR остаётся резервом для настоящих сканов (см. `ocr_backends`).

АЛГОРИТМ
--------
1. Векторные объекты, не являющиеся линовкой, растеризуются в маску ->
   connected components = кандидаты в части символов.
2. Склейка внутренних контуров ('0', '4', 'О' дают 2 компоненты) и диакритики
   ('й', 'ё').
3. Группировка в строки, оценка базовой линии.
4. Калибровка кегля шаблонов по странице (иначе IoU выигрывает не тот размер).
5. ДП по последовательности компонент: символ = 1..3 подряд идущих компоненты,
   причём склейка разрешена только для символов, реально состоящих из частей.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from functools import lru_cache

import cv2
import numpy as np
from numpy.lib.stride_tricks import as_strided
from PIL import Image, ImageDraw, ImageFont, features as pil_features
from PIL import __version__ as pil_version

from .pdfbackend import fitz, map_drawing_arrays, page_drawings

# --------------------------------------------------------------------------- #
#  наборы символов (семантическое ограничение алфавита по роли колонки)
# --------------------------------------------------------------------------- #
CYR_UP = "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
CYR_LO = "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
DIGITS = "0123456789"

# ЛАТИНИЦА УМЫШЛЕННО ПОЧТИ ИСКЛЮЧЕНА. В русских строительных спецификациях
# латинских букв практически нет, зато 'C/С', 'P/Р', 'O/О', 'x/х', 'e/е',
# 'a/а' начертаниями не отличаются вовсе. Пока латиница была в алфавите,
# 'С255-4' читалось как 'G255-4', а 'ГОСТ' как 'ГОGТ'.
# Оставлены только реально нужные: 'L' — уголок (L 100x7), 't' — толщина
# листа (t8, t12). Разделитель размеров всегда нормализуется в кириллическое
# 'х' — из растра отличить его от латинского 'x' невозможно в принципе.
LAT_KEEP = "Lt"

CHARSET_NUMERIC = DIGITS + ",.-"
# Обозначения профилей / марок стали / ГОСТ. 'З' исключена: в марках стали и
# номерах ГОСТ она не встречается, а с '3' путается постоянно ('З5К1').
CHARSET_CODE = (DIGITS + ",.-+/х□" + CYR_UP.replace("З", "") + CYR_LO + LAT_KEEP)
# Свободный текст (наименования профилей, «Итого», примечания).
# ':' и ';' исключены умышленно: в спецификациях они не встречаются, а
# вторая часть 'ы' (вертикальный штрих) уверенно матчилась в ':', и 'ы'
# стабильно распадалась на 'ь' + ':' («покрытия» -> «покрь:тия»).
CHARSET_TEXT = DIGITS + ",.-+/()№%х□" + CYR_UP + CYR_LO + LAT_KEEP
# Компактный набор для КАЛИБРОВКИ гарнитуры и кегля. Полный алфавит здесь не
# нужен: калибровка перебирает десятки (гарнитура, кегль), и рендер 140 глифов
# на каждый набор занимал большую часть времени обработки страницы. Одними
# цифрами обойтись нельзя — у Arial и Arial Narrow они почти совпадают, поэтому
# набор включает буквы с характерно разной шириной.
CHARSET_PROBE = DIGITS + ",.-" + "оаеинтсмлкрувыдгпзбч" + "ГОСТНАВЕКМР"

CHARSETS = {"numeric": CHARSET_NUMERIC, "code": CHARSET_CODE,
            "text": CHARSET_TEXT, "any": CHARSET_TEXT}

# Символы, реально состоящие из нескольких несвязных частей. Только их ДП
# разрешено собирать из нескольких компонент — иначе соседние символы
# склеиваются ('□' + '1' уверенно распознавалось как 'Ы').
MULTIPART = set("ыЫ%")

# Спецсимволы строительных чертежей, которых нет в обычных шрифтах.
SPECIAL_HOLLOW_RECT = "□"

# Референсные гарнитуры для шаблонов. На разных листах «взорванный» текст
# набран по-разному: у КР-37 тело таблицы — Arial, шапка колонок — Arial Narrow;
# у листов КМ из AutoCAD — чертёжный одноштриховый ISOCPEUR / ГОСТ тип A.
#
# Гарнитура подбирается автоматически (см. `_calibrate`). Список расширяем
# осторожно: чем больше близких по форме вариантов, тем выше риск, что верный
# проиграет по метрике. Поэтому подбор двухэтапный — гарнитура фиксируется один
# раз на страницу, а не соревнуется построчно.
REFERENCE_FONTS = [
    "arial.ttf", "arialn.ttf",
    "isocpeur.ttf", "isocpeui.ttf",
    "GOST type A.ttf", "GOST type B.ttf", "GOST Common.ttf",
    "LiberationSans-Regular.ttf", "LiberationSansNarrow-Regular.ttf",
    "DejaVuSans.ttf",
]
FONT_DIRS = [
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
    # в контейнере сюда монтируется папка шрифтов хоста (docker-compose.local.yml):
    # чертёжные ISOCPEUR / GOST в дистрибутивах Linux не бывают
    "/usr/share/fonts/windows",
    "/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/truetype/liberation",
    "/usr/share/fonts",
]
if os.environ.get("OCRPDF_FONT_DIR"):
    FONT_DIRS.insert(0, os.environ["OCRPDF_FONT_DIR"])

CAP_RATIO = 0.716        # Arial: высота прописных / em


# Имя шрифта из PDF (/BaseFont без префикса сабсета, в нижнем регистре) →
# файл референсного шрифта. Проверяется подстрокой, курсив отдельно.
_FONT_HINTS = [
    ("isocpeui.ttf", ("isocpeuritalic", "isocpeur-italic", "isocpeur,italic")),
    ("isocpeur.ttf", ("isocpeur",)),
    ("arialn.ttf", ("arialnarrow", "arial-narrow", "arialnarrowmt")),
    ("arial.ttf", ("arial",)),
    ("gost type a.ttf", ("gosttypea", "gost type a")),
    ("gost type b.ttf", ("gosttypeb", "gost type b")),
    ("gost common.ttf", ("gostcommon", "gost common")),
    ("liberationsans-regular.ttf", ("liberationsans",)),
    ("liberationsansnarrow-regular.ttf", ("liberationsansnarrow",)),
    ("dejavusans.ttf", ("dejavusans",)),
]


def _font_matches(font_file: str, pdf_name: str) -> bool:
    """Подходит ли файл шаблонов под имя шрифта из PDF («isocpeuritalic» → isocpeui.ttf)."""
    name = pdf_name.replace(" ", "").lower()
    italic = "italic" in name or "oblique" in name
    for file, keys in _FONT_HINTS:
        if font_file != file:
            continue
        if file == "isocpeur.ttf" and italic:
            return False
        if file == "arialn.ttf":
            return any(k in name for k in keys)
        if file == "arial.ttf":
            return "arial" in name and "narrow" not in name
        return any(k.replace(" ", "") in name for k in keys)
    return False


def available_fonts() -> list[str]:
    """Полные пути установленных референсных шрифтов (в порядке приоритета)."""
    out: list[str] = []
    for fn in REFERENCE_FONTS:
        low = fn.lower()
        for dd in FONT_DIRS:
            if not os.path.isdir(dd):
                continue
            hit = None
            p_direct = os.path.join(dd, fn)
            if os.path.isfile(p_direct):
                hit = p_direct
            else:
                try:
                    for f in os.listdir(dd):
                        if f.lower() == low:
                            hit = os.path.join(dd, f)
                            break
                except OSError:
                    pass
            if hit:
                out.append(hit)
                break
    if not out:
        raise RuntimeError("не найден ни один референсный TTF для шаблонов глифов")
    return out


def _render(f: ImageFont.FreeTypeFont, ch: str) -> tuple[np.ndarray, int, int]:
    """Растр символа на ТЕСНОМ холсте -> (маска чернил, ox, oy).

    (ox, oy) — точка вывода текста внутри холста; координаты относительно неё
    те же, что при рисовании на большом холсте, поэтому lsb/bot шаблонов не
    меняются. Раньше каждый символ рендерился на холст (3·кегль + 2·отступ)²:
    при кегле 100–240 px это 0,3–1 Мпикс на символ, перевод в numpy и поиск
    чернил занимали ~1 мс, а за лист таких рендеров набиралось под сотню
    тысяч (калибровка перебирает 14 кеглей на гарнитуру и кластер высот).
    На листе АП 2502-19 это было 3 минуты из 5. Вдобавок обрезанная маска
    шаблона оставалась ПРЕДСТАВЛЕНИЕМ большого холста, и кэш шаблонов держал
    в памяти гигабайты пустых пикселей.
    """
    try:
        l, t, r, b = f.getbbox(ch)
    except Exception:  # noqa: BLE001 — символ без контура в этом шрифте
        l, t, r, b = 0, 0, f.size * 3, f.size * 3
    pad = 3
    ox, oy = pad - l, pad - t
    im = Image.new("L", (max(1, r - l) + 2 * pad, max(1, b - t) + 2 * pad), 0)
    ImageDraw.Draw(im).text((ox, oy), ch, font=f, fill=255)
    return np.asarray(im) > 110, ox, oy


@lru_cache(maxsize=1024)
def _font_metrics(font_path: str, size_px: int) -> tuple[float, float]:
    """(высота прописных, высота строчных) в пикселях для данного кегля."""
    f = ImageFont.truetype(font_path, size_px)
    res = []
    for probe in ("Н", "х"):
        ys, _ = np.nonzero(_render(f, probe)[0])
        res.append(float(ys.max() - ys.min() + 1) if len(ys) else 1.0)
    return res[0], res[1]


# Верхняя граница кегля шаблонов, px. Текст таблиц — 2–7 мм (35–100 px при
# 350 dpi), заголовки листа — до ~10 мм. Кластеры выше — это элементы чертежа,
# а не буквы: под них рендерились шаблоны 2000×2000 на каждый символ, кэш из
# 512 таких наборов съедал всю память, и разбор листа падал с MemoryError.
MAX_TEMPLATE_PX = 240
MAX_GLYPH_PX = 170


def _size_for(font_path: str, target_px: float, kind: str) -> int:
    """Кегль, при котором высота прописных (или строчных) равна target_px."""
    lo, hi = 6, MAX_TEMPLATE_PX
    while lo < hi:
        mid = (lo + hi) // 2
        cap, xh = _font_metrics(font_path, mid)
        cur = cap if kind == "cap" else xh
        if cur < target_px:
            lo = mid + 1
        else:
            hi = mid
    return max(6, lo)


# --------------------------------------------------------------------------- #
#  шаблоны
# --------------------------------------------------------------------------- #
@dataclass
class Template:
    ch: str
    bm: np.ndarray          # tight-crop бинарная маска
    h: int
    w: int
    bot: float              # низ глифа относительно базовой линии, px
    adv: float = 0.0        # ширина пера (advance), px
    lsb: float = 0.0        # левая отбивка, px
    bmd: np.ndarray = None  # маска, расширенная на 1 px (считается один раз)


@dataclass(frozen=True)
class Variant:
    """Гарнитура + кегль шаблонов, фактически встреченные на странице."""
    font: str
    size: int
    cap: float                 # высота прописных этой гарнитуры/кегля, px
    xh: float                  # высота строчных, px
    obs: float = 0.0           # НАБЛЮДАЕМАЯ высота кластера, к которому подобран
    score: float = 0.0


# --------------------------------------------------------------------------- #
#  кэш шаблонов: в памяти (по объёму) и на диске (переживает перезапуск)
# --------------------------------------------------------------------------- #
# Раньше здесь стоял lru_cache(maxsize=160). Калибровка кегля на листе АП
# 2502-19 запрашивает ~1100 разных наборов (гарнитура × кегль × алфавит), они
# вытесняли друг друга, и одни и те же наборы рендерились повторно — 76 тысяч
# рендеров за лист. После перехода на тесный холст набор весит десятки–сотни
# килобайт, поэтому кэш ограничен ОБЪЁМОМ, а не числом записей, и дополнен
# дисковым слоем: свежий процесс (перезапуск контейнера) не начинает с нуля.
# Всё настраивается переменными окружения (см. README, «Кэш шаблонов»).
# 512 МБ: полный набор шаблонов тяжёлого листа (АП 2502-19: 932 набора) — 366 МБ,
# при меньшем лимите он вытесняется ещё по ходу листа (повторных рендеров при
# этом нет — калибровка идёт последовательно, но между заданиями кэш пустеет).
TEMPLATE_CACHE_MB = float(os.environ.get("OCRPDF_TEMPLATE_CACHE_MB", "512"))
TEMPLATE_DISK_MB = float(os.environ.get("OCRPDF_TEMPLATE_DISK_MB", "512"))
TEMPLATE_CACHE_DIR = os.environ.get(
    "OCRPDF_TEMPLATE_CACHE_DIR", os.path.join(tempfile.gettempdir(), "ocrpdf-templates"))
_TEMPLATE_FORMAT = 1        # менять при любой правке _render / Template


class _TemplateCache:
    """LRU по суммарному объёму масок + необязательный дисковый слой (.npz).

    Дисковый ключ учитывает файл шрифта (имя, размер, mtime), кегль, алфавит,
    версии Pillow и FreeType и формат записи: другой растеризатор даёт другие
    маски, и подсовывать ему чужой кэш нельзя. Запись атомарная (tmp + replace),
    любая ошибка диска молча отключает только дисковый слой.
    """

    def __init__(self, limit_mb: float, disk_dir: str | None, disk_mb: float) -> None:
        self.limit = int(limit_mb * 1024 * 1024)
        self.disk_dir = disk_dir or None
        self.disk_limit = int(disk_mb * 1024 * 1024)
        self._data: OrderedDict[tuple, tuple[tuple[Template, ...], int]] = OrderedDict()
        self._size = 0
        self._lock = threading.Lock()
        self._writes = 0
        self.hits = self.misses = self.disk_hits = 0

    # ---- память ----
    def get(self, key: tuple) -> tuple[Template, ...] | None:
        with self._lock:
            hit = self._data.get(key)
            if hit is None:
                self.misses += 1
                return None
            self._data.move_to_end(key)
            self.hits += 1
            return hit[0]

    def put(self, key: tuple, tpl: tuple[Template, ...]) -> None:
        nbytes = sum(t.bm.nbytes + t.bmd.nbytes + 256 for t in tpl) + 256
        with self._lock:
            if key in self._data:
                return
            self._data[key] = (tpl, nbytes)
            self._size += nbytes
            while self._size > self.limit and len(self._data) > 1:
                _, (_, old) = self._data.popitem(last=False)
                self._size -= old

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._size = 0
            self.hits = self.misses = self.disk_hits = 0

    def info(self) -> dict:
        with self._lock:
            return {"entries": len(self._data), "bytes": self._size, "limit": self.limit,
                    "hits": self.hits, "misses": self.misses, "disk_hits": self.disk_hits}

    # ---- диск ----
    @staticmethod
    def disk_key(font_path: str, size_px: int, charset: str) -> str:
        st = os.stat(font_path)
        raw = "|".join((str(_TEMPLATE_FORMAT), str(pil_features.version("freetype2")), pil_version,
                        os.path.basename(font_path).lower(), str(st.st_size), str(int(st.st_mtime)),
                        str(size_px), charset))
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def _disk_path(self, font_path: str, size_px: int, charset: str) -> str | None:
        if not self.disk_dir:
            return None
        try:
            return os.path.join(self.disk_dir, self.disk_key(font_path, size_px, charset) + ".tpl")
        except OSError:
            return None

    # Формат файла: magic, 4 байта длины заголовка (LE), JSON-заголовок, затем
    # подряд маски, упакованные по битам. Один файл читается одним вызовом:
    # вариант на np.savez (zip со 140 членами) грузился МЕДЛЕННЕЕ рендера
    # (17 мс против 8 на набор пробного алфавита), то есть был бесполезен.
    _MAGIC = b"OCRTPL1\n"

    def load_disk(self, font_path: str, size_px: int, charset: str) -> tuple[Template, ...] | None:
        path = self._disk_path(font_path, size_px, charset)
        if not path or not os.path.isfile(path):
            return None
        try:
            with open(path, "rb") as fh:
                data = fh.read()
            if not data.startswith(self._MAGIC):
                raise ValueError("не файл шаблонов")
            n = int.from_bytes(data[8:12], "little")
            meta = json.loads(data[12:12 + n].decode("utf-8"))
            body = np.frombuffer(data, dtype=np.uint8, offset=12 + n)
            if meta["charset"] != charset or meta["size"] != size_px:
                raise ValueError("ключ не совпал")
            out: list[Template] = []
            pos = 0
            for ch, h, w, bot, adv, lsb in meta["items"]:
                nbytes = (h * w + 7) // 8
                bm = np.unpackbits(body[pos:pos + nbytes], count=h * w).reshape(h, w).astype(bool)
                pos += nbytes
                out.append(Template(ch=ch, bm=bm, h=int(h), w=int(w), bot=float(bot),
                                    adv=float(adv), lsb=float(lsb), bmd=dilate1(bm)))
            if pos != len(body):
                raise ValueError("длина не совпала")
        except Exception:  # noqa: BLE001 — битый/чужой файл: просто рендерим заново
            try:
                os.remove(path)
            except OSError:
                pass
            return None
        with self._lock:
            self.disk_hits += 1
        return tuple(out)

    def save_disk(self, font_path: str, size_px: int, charset: str, tpl: tuple[Template, ...]) -> None:
        path = self._disk_path(font_path, size_px, charset)
        if not path:
            return
        try:
            os.makedirs(self.disk_dir, exist_ok=True)
            meta = {"size": size_px, "charset": charset,
                    "items": [(t.ch, t.h, t.w, t.bot, t.adv, t.lsb) for t in tpl]}
            head = json.dumps(meta, ensure_ascii=False).encode("utf-8")
            body = b"".join(np.packbits(t.bm, axis=None).tobytes() for t in tpl)
            tmp = "%s.%d.tmp" % (path, os.getpid())
            with open(tmp, "wb") as fh:
                fh.write(self._MAGIC + len(head).to_bytes(4, "little") + head + body)
            os.replace(tmp, path)
            self._writes += 1
            if self._writes == 1 or self._writes % 500 == 0:
                self._trim_disk()
        except Exception:  # noqa: BLE001 — диск только ускоряет, падать из-за него нельзя
            pass

    def _trim_disk(self) -> None:
        """Держит папку в пределах TEMPLATE_DISK_MB, удаляя самые старые файлы."""
        try:
            files = []
            with os.scandir(self.disk_dir) as it:
                for e in it:
                    if e.is_file() and e.name.endswith(".tpl"):
                        st = e.stat()
                        files.append((st.st_mtime, st.st_size, e.path))
            total = sum(f[1] for f in files)
            if total <= self.disk_limit:
                return
            files.sort()
            for _, size, path in files:
                if total <= 0.8 * self.disk_limit:
                    break
                try:
                    os.remove(path)
                    total -= size
                except OSError:
                    pass
        except OSError:
            pass


_TEMPLATE_CACHE = _TemplateCache(TEMPLATE_CACHE_MB, TEMPLATE_CACHE_DIR, TEMPLATE_DISK_MB)


def _render_templates(font_path: str, size_px: int, charset: str) -> tuple[Template, ...]:
    """Рендер набора шаблонов без кэша (то, что раньше делал `_templates`)."""
    f = ImageFont.truetype(font_path, size_px)
    ascent, _ = f.getmetrics()
    out: list[Template] = []
    for ch in charset:
        a, ox, oy = _render(f, ch)
        ys, xs = np.nonzero(a)
        if len(xs) == 0:
            continue
        baseline = oy + ascent
        # копия, а не срез: иначе кэш держит весь холст ради маленькой маски
        bm = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1].copy()
        out.append(Template(
            ch=ch, bm=bm,
            h=int(ys.max() - ys.min() + 1), w=int(xs.max() - xs.min() + 1),
            bot=float(ys.max() - baseline),
            adv=float(f.getlength(ch)), lsb=float(xs.min() - ox),
            bmd=dilate1(bm),
        ))
    return tuple(out)


def _templates(font_path: str, size_px: int, charset: str) -> tuple[Template, ...]:
    """Шаблоны всех символов charset в кегле size_px (память -> диск -> рендер)."""
    size_px = int(min(max(6, size_px), MAX_TEMPLATE_PX))
    key = (font_path, size_px, charset)
    tpl = _TEMPLATE_CACHE.get(key)
    if tpl is None:
        tpl = _TEMPLATE_CACHE.load_disk(font_path, size_px, charset)
        if tpl is None:
            tpl = _render_templates(font_path, size_px, charset)
            _TEMPLATE_CACHE.save_disk(font_path, size_px, charset, tpl)
        _TEMPLATE_CACHE.put(key, tpl)
    return tpl


_templates.cache_clear = _TEMPLATE_CACHE.clear      # совместимость с lru_cache
_templates.cache_info = _TEMPLATE_CACHE.info


@lru_cache(maxsize=512)
def _space_advance(font_path: str, size_px: int) -> float:
    return float(ImageFont.truetype(font_path, size_px).getlength(" "))


_K3 = np.ones((3, 3), np.uint8)


def dilate1(m: np.ndarray) -> np.ndarray:
    """Маска, расширенная на 1 px во все стороны (с полем 1 px по краям).

    Индекс i расширенной маски соответствует координате i-1 исходной.
    """
    pad = np.zeros((m.shape[0] + 2, m.shape[1] + 2), np.uint8)
    pad[1:-1, 1:-1] = m
    return cv2.dilate(pad, _K3).astype(bool)


def _shift_counts(x: np.ndarray, y: np.ndarray, off: int, span: int) -> np.ndarray:
    """Совпадения x с y сразу для span×span сдвигов, одной операцией numpy.

    counts[r, c] — число пикселей, где x[i, j] и y[i - (off - r), j - (off - c)]
    оба истинны (то есть y сдвинута на (off - r, off - c) в координатах x).
    y укладывается на нулевой холст размером x плюс поля, а все сдвиги
    берутся как окна этого холста через `as_strided`: вне холста нулей нет,
    поэтому счёт совпадает с прямым пересечением отрезков индексов до бита.
    """
    hx, wx = x.shape
    canvas = np.zeros((hx + span - 1, wx + span - 1), bool)
    r0, c0 = max(off, 0), max(off, 0)
    r1 = min(off + y.shape[0], canvas.shape[0])
    c1 = min(off + y.shape[1], canvas.shape[1])
    if r1 > r0 and c1 > c0:
        canvas[r0:r1, c0:c1] = y[r0 - off:r1 - off, c0 - off:c1 - off]
    s0, s1 = canvas.strides
    win = as_strided(canvas, shape=(span, span, hx, wx), strides=(s0, s1, s0, s1), writeable=False)
    return np.count_nonzero(win & x, axis=(2, 3))


def _match_score(a: np.ndarray, b: np.ndarray, ad: np.ndarray | None = None,
                 bd: np.ndarray | None = None, max_shift: int = 1) -> float:
    """Схожесть двух tight-crop масок, устойчивая к смещению в 1 px.

    Обычный IoU для этой задачи не годится: штрих толщиной 3-4 px при сдвиге на
    пиксель теряет треть площади. На реальном примере «Рельсы» правильная 'с'
    набирала IoU 0.664, а неверная 'о' — 0.689, и побеждала ошибка.

    Здесь считается СИММЕТРИЧНОЕ взаимное покрытие с допуском 1 px:
        c1 = доля чернил A, у которых есть чернила B не далее 1 px;
        c2 = то же в обратную сторону;
        score = min(c1, c2).
    Малые смещения перестают влиять, а структурная разница — нет: у 'о' правая
    сторона замкнута, поэтому c2 падает до отношения площадей.

    Расширенные маски (`ad`, `bd`) можно передать заранее: для шаблонов они
    считаются один раз при построении, а не на каждое сравнение. Раньше здесь
    вызывался cv2.dilate до девяти раз за сравнение — 245 тысяч вызовов на
    страницу, около 4 с чистых накладных расходов.

    Все девять сдвигов считаются двумя операциями numpy (`_shift_counts`), а не
    циклом по сдвигам с четырьмя срезами на каждый: функция вызывается 1,4 млн
    раз на тяжёлом листе, и накладные расходы Python здесь были заметнее самой
    арифметики. Результат тот же до бита: те же счётчики, те же деления.
    """
    a = np.asarray(a, dtype=bool)
    b = np.asarray(b, dtype=bool)
    na = int(np.count_nonzero(a))
    nb = int(np.count_nonzero(b))
    if na == 0 or nb == 0:
        return 0.0
    if ad is None:
        ad = dilate1(a)
    if bd is None:
        bd = dilate1(b)
    span = 2 * max_shift + 1
    # c1: расширенная B над A, сдвиг (dy - 1, dx - 1); c2: B над расширенной A,
    # сдвиг (dy + 1, dx + 1). В обоих случаях элемент [S - dy, S - dx] отвечает
    # сдвигу (dy, dx), поэтому min берётся поэлементно.
    c1 = _shift_counts(a, np.asarray(bd, dtype=bool), max_shift - 1, span) / na
    c2 = _shift_counts(np.asarray(ad, dtype=bool), b, max_shift + 1, span) / nb
    best = float(np.minimum(c1, c2).max())
    return best if best > 0.0 else 0.0


def _hollow_rect_score(m: np.ndarray) -> float:
    """Насколько маска похожа на полый прямоугольник (символ '□' — гнутый профиль).

    В Arial нет U+25A1 нужных пропорций, поэтому шаблон синтезируется под
    фактические габариты компоненты и толщину штриха.
    """
    h, w = m.shape
    if h < 6 or w < 6:
        return 0.0
    if not (0.70 <= w / h <= 1.55):        # '□' профиля примерно квадратный
        return 0.0
    ink = int(m.sum())
    if ink == 0:
        return 0.0
    t0 = max(1, min(4, int(round(ink / (2.0 * (h + w))))))
    # Все ЧЕТЫРЕ стороны обязаны быть закрашены, иначе 'П' (нет низа) и 'О'
    # выдают себя за квадрат: '16П' читалось как '16□'. Берём НАИЛУЧШУЮ строку
    # (столбец) внутри полосы — оценка толщины штриха и сглаживание при
    # растеризации иначе дают ложные отказы на идентичных по виду глифах.
    band = t0 + 1
    sides = (
        max(float(m[i, :].mean()) for i in range(min(band, h))),
        max(float(m[h - 1 - i, :].mean()) for i in range(min(band, h))),
        max(float(m[:, i].mean()) for i in range(min(band, w))),
        max(float(m[:, w - 1 - i].mean()) for i in range(min(band, w))),
    )
    if min(sides) < 0.80:
        return 0.0
    # Внутренность обязана быть ПУСТОЙ. Без этой проверки 'в' (две чаши,
    # закрашенные края со всех сторон) уверенно выдавала себя за '□':
    # «сварные» -> «с□арные», «Двутавры» -> «Д□утавры».
    inner = m[band:h - band, band:w - band]
    if inner.size and float(inner.mean()) > 0.14:
        return 0.0
    best = 0.0
    for t in {max(1, t0 - 1), t0, t0 + 1}:
        if 2 * t >= min(h, w):
            continue
        tpl = np.zeros((h, w), bool)
        tpl[:t, :] = True
        tpl[-t:, :] = True
        tpl[:, :t] = True
        tpl[:, -t:] = True
        union = int(np.count_nonzero(m | tpl))
        if union:
            best = max(best, int(np.count_nonzero(m & tpl)) / union)
    return best


# --------------------------------------------------------------------------- #
#  слой векторных глифов страницы
# --------------------------------------------------------------------------- #
def _bezier_samples(ctrl: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """9 точек каждой кубической кривой Безье (t = 0, 1/8, …, 1) -> (xs, ys) формы (n, 9).

    `ctrl` — (n, 8): x0, y0, x1, y1, x2, y2, x3, y3. Порядок арифметики повторяет
    прежний скалярный цикл по одной кривой, поэтому числа получаются те же.
    """
    ctrl = np.asarray(ctrl, dtype=np.float64).reshape(-1, 8)
    xs = np.empty((len(ctrl), 9))
    ys = np.empty((len(ctrl), 9))
    for i8 in range(9):
        t = i8 / 8.0
        u = 1.0 - t
        w0, w1, w2, w3 = u*u*u, 3*u*u*t, 3*u*t*t, t*t*t
        xs[:, i8] = w0*ctrl[:, 0] + w1*ctrl[:, 2] + w2*ctrl[:, 4] + w3*ctrl[:, 6]
        ys[:, i8] = w0*ctrl[:, 1] + w1*ctrl[:, 3] + w2*ctrl[:, 5] + w3*ctrl[:, 7]
    return xs, ys


def _collect_primitives(page: fitz.Page, eps: float = 0.05, glyph_max: float = 12.0
                        ) -> tuple[list[tuple[float, float, float, float]], list[tuple[tuple, ...]]]:
    """Примитивы страницы, годные в контуры глифов: (габариты, «концы») в порядке обхода.

    Два прохода. Первый собирает сырые координаты в списки, второй переводит их
    в систему страницы ОДНОЙ матричной операцией (`map_drawing_arrays`) и
    считает габариты векторно. Раньше каждая из ~90 тысяч точек листа шла через
    `fitz.Point` по отдельности — 5–7 с на векторных листах. Порядок примитивов
    сохраняется: от него зависит нумерация контуров, а с ней — стабильные
    сортировки дальше по конвейеру.
    """
    q = 1.0 / eps
    lines: list[tuple[float, float, float, float, float]] = []   # x1, y1, x2, y2, pad
    curves: list[tuple[float, ...]] = []                          # 4 опорные точки + pad
    rects: list[tuple[float, float, float, float]] = []
    order: list[tuple[int, int]] = []                             # (тип, индекс в своём списке)
    for d in page_drawings(page):
        # ТОЛЩИНА ПЕРА. У чертёжных (одноштриховых) шрифтов буква нарисована
        # ОСЕВЫМИ линиями с заданной толщиной пера: габарит вертикальной
        # стойки 'Н' имеет ширину 0.03 pt при высоте 7 pt. Без учёта пера
        # вырез из растра не попадал на чернила вовсе, и весь лист читался
        # мусором. У листов с залитыми контурами глифов (KR-37) перо равно
        # нулю, поэтому поправка там ничего не меняет.
        pen = float(d.get("width") or 0.0)
        pad = pen / 2.0 if (d.get("fill") is None and pen > 0) else 0.0
        for it in d["items"]:
            kind = it[0]
            if kind == "l":
                order.append((0, len(lines)))
                lines.append((it[1].x, it[1].y, it[2].x, it[2].y, pad))
            elif kind == "c":
                p0, p1, p2, p3 = it[1], it[2], it[3], it[4]
                order.append((1, len(curves)))
                curves.append((p0.x, p0.y, p1.x, p1.y, p2.x, p2.y, p3.x, p3.y, pad))
            elif kind in ("re", "qu"):
                raw = fitz.Rect(it[1]) if kind == "re" else fitz.Quad(it[1]).rect
                order.append((2, len(rects)))
                rects.append((raw.x0, raw.y0, raw.x1, raw.y1))

    def keys_of(x: np.ndarray, y: np.ndarray) -> list[list[int]]:
        return np.stack([np.rint(x * q), np.rint(y * q)], axis=1).astype(np.int64).tolist()

    # отрезки: линовку исключаем — длинные строго осевые отрезки
    L = np.asarray(lines, dtype=np.float64).reshape(-1, 5)
    lx1, ly1 = map_drawing_arrays(page, L[:, 0], L[:, 1])
    lx2, ly2 = map_drawing_arrays(page, L[:, 2], L[:, 3])
    ldx, ldy = np.abs(lx2 - lx1), np.abs(ly2 - ly1)
    l_ok = (~(((ldy <= 0.2) & (ldx >= 15)) | ((ldx <= 0.2) & (ldy >= 15)))).tolist()
    lpad = L[:, 4]
    l_box = np.stack([np.minimum(lx1, lx2) - lpad, np.minimum(ly1, ly2) - lpad,
                      np.maximum(lx1, lx2) + lpad, np.maximum(ly1, ly2) + lpad], axis=1).tolist()
    l_k1, l_k2 = keys_of(lx1, ly1), keys_of(lx2, ly2)

    # кривые: габарит считаем по САМОЙ кривой, а не по опорным точкам:
    # выпуклая оболочка опорных точек заметно шире кривой, из-за чего в вырез
    # попадали чернила соседнего символа и разрыв замыкался — 'с' читалось
    # как 'о', 'С' как 'О', '8' как 'В'.
    C = np.asarray(curves, dtype=np.float64).reshape(-1, 9)
    bx, by = _bezier_samples(C[:, :8])
    sx, sy = map_drawing_arrays(page, bx.ravel(), by.ravel())
    sx, sy = sx.reshape(-1, 9), sy.reshape(-1, 9)
    cpad = C[:, 8]
    c_box = np.stack([sx.min(axis=1) - cpad, sy.min(axis=1) - cpad,
                      sx.max(axis=1) + cpad, sy.max(axis=1) + cpad], axis=1).tolist()
    e0x, e0y = map_drawing_arrays(page, C[:, 0], C[:, 1])
    e3x, e3y = map_drawing_arrays(page, C[:, 6], C[:, 7])
    c_k1, c_k2 = keys_of(e0x, e0y), keys_of(e3x, e3y)

    # мелкие залитые прямоугольники — это ТОЧКИ и ДЕФИСЫ.
    # Без них 'Гн.' читалось как 'Гн ', а 'С355-5' как 'С355 5'.
    R = np.asarray(rects, dtype=np.float64).reshape(-1, 4)
    rax, ray = map_drawing_arrays(page, R[:, 0], R[:, 1])
    rbx, rby = map_drawing_arrays(page, R[:, 2], R[:, 3])
    rx0, ry0 = np.minimum(rax, rbx), np.minimum(ray, rby)
    rx1, ry1 = np.maximum(rax, rbx), np.maximum(ray, rby)
    r_ok = (np.maximum(rx1 - rx0, ry1 - ry0) <= glyph_max).tolist()
    r_box = np.stack([rx0, ry0, rx1, ry1], axis=1).tolist()

    pts: list[tuple[float, float, float, float]] = []
    keys: list[tuple[tuple, ...]] = []
    for kind, i in order:
        if kind == 0:
            if not l_ok[i]:
                continue
            pts.append(tuple(l_box[i]))
            keys.append((tuple(l_k1[i]), tuple(l_k2[i])))
        elif kind == 1:
            pts.append(tuple(c_box[i]))
            keys.append((tuple(c_k1[i]), tuple(c_k2[i])))
        else:
            if not r_ok[i]:
                continue
            pts.append(tuple(r_box[i]))
            keys.append(())                    # самостоятельный примитив
    return pts, keys


# На листах А0/А1 350 DPI даёт десятки мегапикселей: рендер и OCR занимают
# минуты, а для чтения ячеек хватает ~150 DPI. Ограничиваем длинную сторону.
MAX_PIXMAP_SIDE = 7200

# Картинка листа с разрешением ниже этого — скриншот, вставленный в Word
# («Рама для вентилятора»: 689×660 px на А4, 96 dpi, текст 7 px). MuPDF при
# рендере растягивает её билинейно в мыло; бикубическое увеличение исходных
# пикселей с нерезкой маской читается RapidOCR заметно лучше: «1400» → «1.400»,
# «L NOx8» → «L100x8», номера позиций и марки стали появляются.
LOWRES_MAX_DPI = 200.0
# Картинка занимает не весь лист: на Obshchaga_KM таблица-скриншот — 43 % площади А4.
LOWRES_MIN_AREA = 0.3
# «интерполяция_постобработка»: cubic|lanczos + unsharp|otsu|none. По умолчанию —
# чистый Lanczos без резкости и бинаризации: на «Раме для вентилятора» все 12
# размеров, 49 проверок из 52 и 27 спорных ячеек против 9/12, 41/46 и 48 у
# рендера MuPDF; нерезкая маска и Otsu портят мелкий курсив шапки
# («Прогоны» пропадает). Сравнение вариантов — WORKLOG 2026-09-21.
LOWRES_MODE = os.environ.get("OCRPDF_LOWRES_MODE", "lanczos_none")


def _unsharp(img: np.ndarray, amount: float = 1.0, sigma: float = 1.5) -> np.ndarray:
    import cv2
    blur = cv2.GaussianBlur(img, (0, 0), sigma)
    return cv2.addWeighted(img, 1 + amount, blur, -amount, 0)


def _best_orientation(native: np.ndarray, rendered: np.ndarray) -> np.ndarray:
    """Исходная картинка может лежать в PDF перевёрнутой (матрица размещения);
    ориентация подбирается по совпадению с рендером той же области."""
    import cv2
    small = cv2.resize(rendered, (native.shape[1], native.shape[0]), interpolation=cv2.INTER_AREA).astype(np.float32)
    small -= small.mean()
    best, best_score = native, -2.0
    for cand in (native, native[::-1, :], native[:, ::-1], native[::-1, ::-1]):
        a = cand.astype(np.float32); a -= a.mean()
        denom = float(np.sqrt((a * a).sum() * (small * small).sum())) or 1.0
        score = float((a * small).sum()) / denom
        if score > best_score:
            best, best_score = cand, score
    return np.ascontiguousarray(best)


def upscale_lowres_raster(page: fitz.Page, img: np.ndarray, zoom: float) -> tuple[np.ndarray, str]:
    """Если лист — одна большая картинка низкого разрешения, её пиксели
    увеличиваются до масштаба рендера (бикубически, с нерезкой маской) и
    кладутся на место рендера. Возвращает (изображение, заметка или '')."""
    import cv2
    if page.rotation:
        return img, ""
    best = None
    for info in page.get_image_info(xrefs=True):
        r = fitz.Rect(info["bbox"])
        if r.get_area() < LOWRES_MIN_AREA * abs(page.rect.get_area()) or not info.get("xref"):
            continue
        tr = info.get("transform") or (1, 0, 0, 1, 0, 0)
        if abs(tr[1]) > 1e-3 or abs(tr[2]) > 1e-3:      # повёрнутое размещение — не трогаем
            continue
        eff = info["width"] / (r.width / 72.0)
        if best is None or r.get_area() > best[1].get_area():
            best = (info["xref"], r, info["width"], info["height"], eff)
    if best is None:
        return img, ""
    xref, r, w, h, eff = best
    if eff >= LOWRES_MAX_DPI or w < 50 or h < 50:
        return img, ""
    try:
        pix = fitz.Pixmap(page.parent, xref)
        if pix.n - pix.alpha >= 3:
            pix = fitz.Pixmap(fitz.csGRAY, pix)
        if pix.alpha:
            pix = fitz.Pixmap(pix, 0)
        native = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width).copy()
    except Exception:
        return img, ""
    x0, y0 = max(0, int(round(r.x0 * zoom))), max(0, int(round(r.y0 * zoom)))
    x1, y1 = min(img.shape[1], int(round(r.x1 * zoom))), min(img.shape[0], int(round(r.y1 * zoom)))
    W, H = x1 - x0, y1 - y0
    if W < 50 or H < 50:
        return img, ""
    native = _best_orientation(native, img[y0:y1, x0:x1])
    interp, _, post = LOWRES_MODE.partition("_")
    up = cv2.resize(native, (W, H),
                    interpolation=cv2.INTER_LANCZOS4 if interp == "lanczos" else cv2.INTER_CUBIC)
    if post == "otsu":
        _, up = cv2.threshold(up, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    elif post == "unsharp":
        up = _unsharp(up)
    out = img.copy()
    out[y0:y1, x0:x1] = up
    note = ("растр низкого разрешения (%d dpi, %d×%d px): картинка листа увеличена ×%.1f "
            "(%s) вместо рендера" % (round(eff), w, h, W / w, LOWRES_MODE))
    return out, note


@dataclass
class GlyphLayer:
    page: fitz.Page
    dpi: int = 350
    img: np.ndarray = field(default=None, repr=False)
    comps: np.ndarray = field(default=None, repr=False)   # (n, 4) в PDF-точках
    zoom: float = 1.0
    fonts: list[str] = field(default_factory=list)
    variants: list[Variant] = field(default_factory=list)
    _calibrated: bool = field(default=False, repr=False)
    lowres_note: str = ""     # растр низкого разрешения заменён увеличенной картинкой

    def __post_init__(self) -> None:
        side = max(float(self.page.rect.width), float(self.page.rect.height))
        if side > 0 and self.dpi / 72.0 * side > MAX_PIXMAP_SIDE:
            self.dpi = max(120, int(MAX_PIXMAP_SIDE / side * 72))
        self.zoom = self.dpi / 72.0
        self.fonts = available_fonts()
        pix = self.page.get_pixmap(dpi=self.dpi, colorspace=fitz.csGRAY)
        self.img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width).copy()
        self.img, self.lowres_note = upscale_lowres_raster(self.page, self.img, self.zoom)
        self.comps = self._components()
        self.variants = []
        self._calibrated = False

    def ensure_calibrated(self) -> list[Variant]:
        """Калибровка шаблонов — только если реально читаем векторные глифы."""
        if not self._calibrated:
            self.variants = self._calibrate()
            self._calibrated = True
        return self.variants

    # ---- контуры глифов: union-find по общим концам полилиний ----
    def _components(self, eps: float = 0.05, glyph_max: float = 12.0) -> np.ndarray:
        """Группирует векторные примитивы в контуры БЕЗ растеризации.

        Контур глифа — непрерывная полилиния, её звенья имеют строго общие
        концы. Поэтому объединение по совпадению концов даёт контуры точно и
        не зависит от разрешения. Предыдущая версия строила маску 8 px/pt с
        дилатацией — и склеивала соседние символы: `□` + `1` -> `Ы`,
        `Гн.□160x6` -> `Гн.□60х6` (первая цифра пропадала).

        Сбор примитивов (перевод координат, габариты, ключи концов) вынесен в
        `_collect_primitives` и считается векторно.
        """
        pts, keys = _collect_primitives(self.page, eps, glyph_max)
        n = len(pts)
        if n == 0:
            return np.zeros((0, 4))

        parent = list(range(n))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        first: dict[tuple, int] = {}
        for i, ks in enumerate(keys):
            for key in ks:
                j = first.get(key)
                if j is None:
                    first[key] = i
                else:
                    ri, rj = find(i), find(j)
                    if ri != rj:
                        parent[max(ri, rj)] = min(ri, rj)

        arr = np.asarray(pts)
        roots = np.fromiter((find(i) for i in range(n)), dtype=np.int64, count=n)
        order = np.argsort(roots, kind="stable")
        out: list[tuple[float, float, float, float]] = []
        i = 0
        while i < n:
            j = i
            while j + 1 < n and roots[order[j + 1]] == roots[order[i]]:
                j += 1
            g = arr[order[i:j + 1]]
            out.append((float(g[:, 0].min()), float(g[:, 1].min()),
                        float(g[:, 2].max()), float(g[:, 3].max())))
            i = j + 1
        return np.asarray(out)

    # ---- калибровка: гарнитура + кегль шаблонов ----
    def _calibrate(self, sample_lines: int = 26) -> list[Variant]:
        """Подбирает пары (гарнитура, кегль), фактически встречающиеся на странице.

        Зачем: IoU слабо чувствителен к масштабу для простых форм, поэтому
        «арифметический» кегль (cap/0.716) выигрывал не тем символам. Плюс на
        одном листе бывает несколько гарнитур: тело таблицы — Arial,
        заголовки колонок — Arial Narrow. Без подбора гарнитуры «Надколон-»
        читалось как «Ьздксясн».
        """
        if len(self.comps) == 0:
            return []
        merged = merge_strokes(merge_counters([tuple(c) for c in self.comps]))
        lines = [L for L in group_lines(merged) if len(L) >= 3]
        if not lines:
            return []
        step = max(1, len(lines) // sample_lines)
        sample = lines[::step][:sample_lines]

        groups: dict[int, list[tuple]] = {}
        for L in sample:
            groups.setdefault(int(round(_cap_height_px(L, self.zoom) / 2.0)), []).extend(L)

        # ЭТАП 1. Гарнитура выбирается ОДИН РАЗ на страницу — по самому
        # представительному кластеру высот. Перебирать все гарнитуры на каждом
        # кластере и дорого, и опасно: близкие по форме варианты периодически
        # выигрывают и портят уверенно читаемый текст ('С' -> 'G', 'в' -> '□').
        fonts = self._pick_fonts(groups)

        # ЭТАП 2. Кегль подбирается по каждому кластеру, но только среди
        # выбранных гарнитур.
        out: list[Variant] = []
        for key, comps in sorted(groups.items()):
            h = key * 2.0
            if h > MAX_GLYPH_PX:
                continue
            tall = [c for c in comps if (c[3] - c[1]) * self.zoom >= 0.85 * h]
            probe = (tall + [c for c in comps if c not in tall])[:18]
            if not probe:
                continue
            ranked = [r for r in (self._best_size(probe, font, h) for font in fonts)
                      if r is not None]
            if not ranked:
                continue
            ranked.sort(reverse=True)
            sc, font, size = ranked[0]
            cap, xh = _font_metrics(font, size)
            out.append(Variant(font, size, cap, xh, h, round(sc, 3)))
        if not out:
            font = self.fonts[0]
            h = (max(groups) * 2.0) if groups else 20.0
            size = _size_for(font, h, "cap")
            cap, xh = _font_metrics(font, size)
            out.append(Variant(font, size, cap, xh, h, 0.0))
        out.sort(key=lambda v: (v.obs, -v.score))
        return out

    def _best_size(self, probe: list[tuple], font: str, h: float):
        """(счёт, гарнитура, кегль) — лучший кегль данной гарнитуры под высоту h.

        Наблюдаемая высота h может быть высотой прописных ИЛИ строчных: строка
        вида «стальные» вообще не содержит высоких букв. Проверяются оба
        толкования.
        """
        seeds = {_size_for(font, h, "cap"), _size_for(font, h, "xh")}
        best_s, best_v = -1.0, None
        masks = self._probe_masks(probe)
        for seed in seeds:
            for size in range(max(6, seed - 3), seed + 4):
                sc = self._mean_best_iou(probe, font, size, CHARSET_PROBE, masks)
                if sc > best_s:
                    best_s, best_v = sc, size
        return None if best_v is None else (best_s, font, int(best_v))

    def hinted_fonts(self) -> list[str]:
        """Референсные шрифты, которые сам PDF объявляет на странице.

        «Взорванный» текст сохраняет имена исходных шрифтов в словаре страницы
        (ISOCPEUR, ISOCPEURItalic, Arial-BoldMT…). Если такой шрифт установлен,
        его шаблоны почти наверняка подойдут лучше любого угаданного по метрике:
        на file-7 метрика выбрала Arial Narrow при объявленном ISOCPEUR, вся
        спецификация читалась «спорно» и уходила в растровый OCR, а курсивные
        наименования групп превращались в кашу.
        """
        try:
            names = {str(f[3]).split("+")[-1].lower() for f in self.page.get_fonts(full=True)}
        except Exception:
            return []
        out: list[str] = []
        for path in self.fonts:
            base = os.path.basename(path).lower()
            for name in names:
                if _font_matches(base, name) and path not in out:
                    out.append(path)
        return out

    def _pick_fonts(self, groups: dict[int, list[tuple]], keep: int = 2) -> list[str]:
        """Гарнитуры страницы: объявленные в PDF (если установлены) плюс лучшие
        по метрике на самом представительном кластере.

        Считать по ЦИФРАМ нельзя — у Arial и Arial Narrow при подходящих кеглях
        они почти совпадают (счёт 0.388 против 0.389, выбор переворачивался
        случайно). Ширины БУКВ различаются заметно, поэтому используется
        буквенный набор `CHARSET_PROBE`.
        """
        hinted = self.hinted_fonts()
        if len(self.fonts) <= keep:
            return list(self.fonts)
        key = max(groups, key=lambda k: len(groups[k]))
        comps = groups[key]
        h = key * 2.0
        tall = [c for c in comps if (c[3] - c[1]) * self.zoom >= 0.85 * h]
        probe = (tall + [c for c in comps if c not in tall])[:18]
        if not probe:
            return hinted or self.fonts[:keep]
        ranked = [r for r in (self._best_size(probe, f, h) for f in self.fonts)
                  if r is not None]
        if not ranked:
            return hinted or self.fonts[:keep]
        ranked.sort(reverse=True)
        picked = [f for _, f, _ in ranked[:keep]]
        # объявленные шрифты — всегда в наборе, метрика лишь добирает остальное
        return hinted + [f for f in picked if f not in hinted]

    def _probe_masks(self, comps: list[tuple]) -> list[tuple[np.ndarray, np.ndarray, int, int]]:
        """(маска, расширенная маска, h, w) по каждому непустому контуру.

        Считается один раз на набор контуров: подбор кегля сравнивает те же
        контуры с 14 наборами шаблонов на гарнитуру, и вырезать/расширять
        маски заново для каждого — лишняя треть времени калибровки.
        """
        out = []
        for b in comps:
            m = self.crop_mask(b)
            if m.size == 0 or not m.any():
                continue
            ys, xs = np.nonzero(m)
            m = m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
            out.append((m, dilate1(m), int(m.shape[0]), int(m.shape[1])))
        return out

    def _mean_best_iou(self, comps: list[tuple], font: str, size_px: int,
                       charset: str, masks=None) -> float:
        tpl = _templates(font, size_px, charset)
        if masks is None:
            masks = self._probe_masks(comps)
        tot, n = 0.0, 0
        for m, md, h, w in masks:
            best = 0.0
            for t in tpl:
                if abs(t.h - h) > max(1.5, 0.10 * max(t.h, h)):
                    continue
                if abs(t.w - w) > max(1.5, 0.18 * max(t.w, w)):
                    continue
                best = max(best, _match_score(m, t.bm, md, t.bmd))
            tot += best
            n += 1
        return tot / n if n else 0.0

    def variants_for(self, h_px: float, tol: float = 0.22) -> list[Variant]:
        """Варианты, совместимые с наблюдаемой высотой самых высоких глифов.

        Высота может быть высотой прописных ИЛИ строчных — проверяются оба
        толкования, иначе строки без заглавных букв и цифр («стальные»)
        получали кегль в два раза меньше нужного.
        """
        self.ensure_calibrated()
        if not self.variants:
            return []
        # Ключ — НАБЛЮДАЕМАЯ высота кластера, а не метрика шрифта: у Arial и
        # Arial Narrow при одинаковом визуальном размере метрические высоты
        # прописных почти совпадают, и по ним гарнитуры не различить.
        d = [(abs(v.obs - h_px) / max(h_px, 1e-6), v) for v in self.variants]
        best = min(x[0] for x in d)
        out = [v for dist, v in d if dist <= max(best, 0.0) + 0.05]
        if out and best <= tol:
            return out
        near = min(self.variants, key=lambda v: abs(v.obs - h_px))
        size = min(MAX_TEMPLATE_PX,
                   max(6, int(round(near.size * h_px / max(near.obs, 1e-6)))))
        cap, xh = _font_metrics(near.font, size)
        return [Variant(near.font, size, cap, xh, h_px, 0.0)]

    def fallback_variants(self, h_px: float, exclude: set[str]) -> list[Variant]:
        """Варианты на прочих гарнитурах — для повторной попытки на плохих строках."""
        out: list[Variant] = []
        for font in self.fonts:
            if font in exclude:
                continue
            for kind in ("cap", "xh"):
                size = _size_for(font, h_px, kind)
                for d in (-2, 0, 2):
                    sz = max(6, size + d)
                    cap, xh = _font_metrics(font, sz)
                    out.append(Variant(font, sz, cap, xh, h_px, 0.0))
        return out

    def components_in(self, bbox: tuple[float, float, float, float],
                      pad: float = 0.4) -> list[tuple[float, float, float, float]]:
        if len(self.comps) == 0:
            return []
        x0, y0, x1, y1 = bbox
        c = self.comps
        m = ((c[:, 0] >= x0 - pad) & (c[:, 2] <= x1 + pad) &
             (c[:, 1] >= y0 - pad) & (c[:, 3] <= y1 + pad))
        return [tuple(v) for v in c[m]]

    def crop_mask(self, bbox: tuple[float, float, float, float]) -> np.ndarray:
        """Маска чернил внутри bbox контура. БЕЗ запаса по краям.

        Запас в 1 px «дотягивал» чернила соседнего символа и замыкал разрывы:
        'с' читалось как 'о', 'С' как 'О', '8' как 'В'. Габарит контура и так
        получен из точной векторной геометрии, поэтому расширять его не нужно.
        """
        z = self.zoom
        x0 = max(0, int(np.floor(bbox[0] * z)))
        y0 = max(0, int(np.floor(bbox[1] * z)))
        x1 = min(self.img.shape[1], int(np.ceil(bbox[2] * z)))
        y1 = min(self.img.shape[0], int(np.ceil(bbox[3] * z)))
        if x1 <= x0 or y1 <= y0:
            return np.zeros((0, 0), bool)
        return self.img[y0:y1, x0:x1] < 128


def baseline_px(line: list[tuple], zoom: float) -> float:
    """Базовая линия строки — МОДА низов глифов.

    Медиана низов «самых высоких» глифов не годится: в строке «сварные» выше
    всех оказывается 'р' с выносом вниз, базовая линия уезжает на линию
    выносных элементов, и 'р' начинает выглядеть как 'Р', 'у' как '7'.
    На базовой линии стоит большинство глифов, поэтому берём самый крупный
    кластер низов.
    """
    bots = sorted(b[3] * zoom for b in line)
    if not bots:
        return 0.0
    tol = max(1.5, 0.08 * max((b[3] - b[1]) * zoom for b in line))
    best, best_n = bots[0], 0
    i = 0
    while i < len(bots):
        j = i
        while j + 1 < len(bots) and bots[j + 1] - bots[i] <= tol:
            j += 1
        if j - i + 1 > best_n:
            best_n = j - i + 1
            best = float(np.mean(bots[i:j + 1]))
        i = j + 1
    return best


def _cap_height_px(line: list[tuple], zoom: float) -> float:
    """Высота самых высоких глифов ОТ базовой линии (без выносных элементов)."""
    base = baseline_px(line, zoom)
    ups = sorted(max(0.0, base - b[1] * zoom) for b in line)
    if not ups:
        return 1.0
    top = ups[-1]
    tall = [u for u in ups if u >= 0.85 * top]
    return float(np.median(tall)) or 1.0


# --------------------------------------------------------------------------- #
#  склейка компонент и группировка в строки
# --------------------------------------------------------------------------- #
def merge_strokes(bs: list[tuple], frac: float = 0.55) -> list[tuple]:
    """Склеивает штрихи одной буквы, стыкующиеся НЕ концами.

    В одноштриховом чертёжном шрифте перекладина 'Н' упирается в СЕРЕДИНУ
    стойки, а не в её конец. Объединение примитивов по совпадающим концам
    (`GlyphLayer._components`) такие стыки не видит, и 'Н' распадается на три
    компоненты — читалось как два '?'. Здесь компоненты объединяются, если их
    габариты перекрываются по ОБЕИМ осям на существенную долю меньшего из них.
    Соседние буквы так не склеиваются: между ними есть просвет.
    """
    boxes = [list(b) for b in bs]
    n = len(boxes)
    if n < 2:
        return [tuple(b) for b in boxes]
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    order = sorted(range(n), key=lambda i: boxes[i][0])
    for ai in range(n):
        a = boxes[order[ai]]
        for bi in range(ai + 1, n):
            b = boxes[order[bi]]
            if b[0] > a[2]:                     # дальше только правее — выходим
                break
            ox = min(a[2], b[2]) - max(a[0], b[0])
            oy = min(a[3], b[3]) - max(a[1], b[1])
            if ox <= 0 or oy <= 0:
                continue
            if (ox >= frac * min(a[2] - a[0], b[2] - b[0])
                    and oy >= frac * min(a[3] - a[1], b[3] - b[1])):
                ra, rb = find(order[ai]), find(order[bi])
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)

    groups: dict[int, list[float]] = {}
    for i in range(n):
        r = find(i)
        g = groups.get(r)
        if g is None:
            groups[r] = list(boxes[i])
        else:
            g[0] = min(g[0], boxes[i][0]); g[1] = min(g[1], boxes[i][1])
            g[2] = max(g[2], boxes[i][2]); g[3] = max(g[3], boxes[i][3])
    return [tuple(g) for g in groups.values()]


def merge_counters(bs: list[tuple], contain: float = 0.92,
                   bucket: float = 12.0) -> list[tuple]:
    """Склеивает внутренние контуры глифов ('0', '4', 'О', 'П' дают 2+ части).

    Условие — почти полная вложенность по ОБЕИМ осям. Более слабое условие
    (перекрытие 75 %) склеивало соседние символы: '□1' превращалось в 'Ы'.

    Кандидаты ищутся через сетку бакетов, а не полным перебором: вложенный
    контур целиком лежит внутри охватывающего, поэтому достаточно проверить
    контуры из бакета его центра. Полный перебор давал O(n^2) — на 3738
    контурах страницы это около 5 с чистого перебора.
    """
    bs = sorted(bs, key=lambda b: -((b[2] - b[0]) * (b[3] - b[1])))
    out: list[list[float]] = []
    index: dict[tuple[int, int], list[int]] = {}

    def cells_of(box) -> list[tuple[int, int]]:
        gx0, gx1 = int(box[0] // bucket), int(box[2] // bucket)
        gy0, gy1 = int(box[1] // bucket), int(box[3] // bucket)
        return [(gx, gy) for gx in range(gx0, gx1 + 1) for gy in range(gy0, gy1 + 1)]

    for b in bs:
        bw, bh = max(b[2] - b[0], 1e-6), max(b[3] - b[1], 1e-6)
        key = (int(((b[0] + b[2]) / 2) // bucket), int(((b[1] + b[3]) / 2) // bucket))
        merged = False
        for i in index.get(key, ()):
            o = out[i]
            ox = min(b[2], o[2]) - max(b[0], o[0])
            oy = min(b[3], o[3]) - max(b[1], o[1])
            if ox >= contain * bw and oy >= contain * bh:
                grew = (b[0] < o[0] or b[1] < o[1] or b[2] > o[2] or b[3] > o[3])
                o[0] = min(o[0], b[0]); o[1] = min(o[1], b[1])
                o[2] = max(o[2], b[2]); o[3] = max(o[3], b[3])
                if grew:                      # габарит изменился — переиндексируем
                    for c in cells_of(o):
                        lst = index.setdefault(c, [])
                        if i not in lst:
                            lst.append(i)
                merged = True
                break
        if not merged:
            out.append(list(b))
            i = len(out) - 1
            for c in cells_of(b):
                index.setdefault(c, []).append(i)
    return [tuple(o) for o in out]


def merge_diacritics(bs: list[tuple], x_overlap: float = 0.60,
                     max_h_ratio: float = 0.45, max_gap: float = 0.30) -> list[tuple]:
    """Приклеивает надстрочные элементы: 'й' = и + бреве, 'ё' = е + умляут.

    Обязательна вертикальная СМЕЖНОСТЬ: без неё дефис верхней строки
    («С355-5») приклеивался к цифре нижней («ГОСТ 27772-2015»), обе строки
    сливались в одну и вся ячейка читалась как мусор.
    """
    bs = sorted(bs, key=lambda b: (b[3] - b[1]))
    out: list[list[float]] = [list(b) for b in bs]
    used = [False] * len(out)
    for i, small in enumerate(out):
        if used[i]:
            continue
        sh = small[3] - small[1]
        sw = max(small[2] - small[0], 1e-6)
        best, best_ov = None, 0.0
        for j, big in enumerate(out):
            if i == j or used[j]:
                continue
            bh = big[3] - big[1]
            if sh > max_h_ratio * bh:
                continue
            if small[3] > big[1] + 0.35 * bh:      # должен стоять СВЕРХУ
                continue
            if big[1] - small[3] > max_gap * bh:   # и почти касаться базы
                continue
            # надстрочный знак узкий и вписан в габарит базового глифа
            if small[0] < big[0] - 0.25 * bh or small[2] > big[2] + 0.25 * bh:
                continue
            ov = min(small[2], big[2]) - max(small[0], big[0])
            if ov >= x_overlap * min(sw, big[2] - big[0]) and ov > best_ov:
                best, best_ov = j, ov
        if best is not None:
            big = out[best]
            big[0] = min(big[0], small[0]); big[1] = min(big[1], small[1])
            big[2] = max(big[2], small[2]); big[3] = max(big[3], small[3])
            used[i] = True
    return [tuple(o) for o, u in zip(out, used) if not u]


def group_lines(bs: list[tuple], overlap: float = 0.40) -> list[list[tuple]]:
    """Разбивает компоненты на строки текста.

    Два прохода. Сначала строки формируются из «крупных» компонент, затем к ним
    прикрепляются мелкие (запятые, точки, дефисы). Одного прохода не хватало:
    запятая стоит на базовой линии и перекрывается со строкой лишь на ~40 %
    своей высоты, поэтому периодически становилась отдельной строкой —
    '2,12' превращалось в '212' + '1' на двух строках.
    """
    if not bs:
        return []
    hmax = max(b[3] - b[1] for b in bs)
    big = [b for b in bs if (b[3] - b[1]) > 0.5 * hmax]
    small = [b for b in bs if (b[3] - b[1]) <= 0.5 * hmax]

    lines: list[list[tuple]] = []
    for b in sorted(big, key=lambda b: b[1]):
        for L in lines:
            ly0 = min(x[1] for x in L); ly1 = max(x[3] for x in L)
            ov = min(b[3], ly1) - max(b[1], ly0)
            if ov >= overlap * min(b[3] - b[1], ly1 - ly0):
                L.append(b)
                break
        else:
            lines.append([b])

    for b in sorted(small, key=lambda b: b[1]):
        best, best_ov = None, -1e9
        for L in lines:
            ly0 = min(x[1] for x in L); ly1 = max(x[3] for x in L)
            ov = min(b[3], ly1) - max(b[1], ly0)
            if ov > best_ov:
                best, best_ov = L, ov
        # мелкая компонента прикрепляется даже при небольшом перекрытии;
        # если не пересекается ни с чем — становится собственной строкой
        if best is not None and best_ov > -0.4 * (b[3] - b[1]):
            best.append(b)
        else:
            lines.append([b])

    for L in lines:
        L.sort(key=lambda b: b[0])
    lines.sort(key=lambda L: min(b[1] for b in L))
    return lines


# --------------------------------------------------------------------------- #
#  распознавание
# --------------------------------------------------------------------------- #
@dataclass
class GlyphResult:
    char: str
    bbox: tuple[float, float, float, float]
    confidence: float
    alternatives: list[tuple[str, float]] = field(default_factory=list)


def _classify(layer: GlyphLayer, bbox: tuple, variant: Variant, baseline_px: float,
              charset: str) -> tuple[str, float, list[tuple[str, float]]]:
    m = layer.crop_mask(bbox)
    if m.size == 0 or not m.any():
        return "", 0.0, []
    ys, xs = np.nonzero(m)
    m = m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = m.shape
    md = dilate1(m)
    bot = (bbox[3] * layer.zoom) - baseline_px
    scored: list[tuple[float, str]] = []
    for t in _templates(variant.font, variant.size, charset):
        if abs(t.h - h) > max(1.5, 0.11 * max(t.h, h)):
            continue
        if abs(t.w - w) > max(1.5, 0.18 * max(t.w, w)):
            continue
        s = _match_score(m, t.bm, md, t.bmd)
        if s <= 0.0:
            continue
        # согласие по базовой линии отличает 'о'/'О', ','/'.', '-'/'_'
        s -= 0.035 * min(abs(t.bot - bot), 12.0)
        scored.append((s, t.ch))
    if charset in (CHARSET_CODE, CHARSET_TEXT):
        s = _hollow_rect_score(m)
        # структурный тест на полый прямоугольник специфичнее, чем IoU по
        # шаблону: при уверенном срабатывании даём бонус, иначе 'Ш'/'О'
        # отбирали '□' у обозначений гнутых профилей.
        if s > 0.30:
            scored.append((s + (0.15 if s >= 0.70 else 0.0), SPECIAL_HOLLOW_RECT))
    if not scored:
        return "?", 0.0, []
    scored.sort(reverse=True)
    best_s, best_c = scored[0]
    runner = next((s for s, c in scored if c != best_c), 0.0)
    conf = max(0.0, min(1.0, best_s)) * min(1.0, 0.60 + 4.0 * max(0.0, best_s - runner))
    alts, seen = [], {best_c}
    for s, c in scored[1:]:
        if c not in seen:
            alts.append((c, round(max(0.0, min(1.0, s)), 3)))
            seen.add(c)
        if len(alts) >= 3:
            break
    return best_c, conf, alts


def _read_line(layer: GlyphLayer, comps: list[tuple], charset: str,
               variants: list[Variant] | None = None
               ) -> tuple[str, list[GlyphResult]]:
    """ДП-сегментация строки: символ = 1..3 подряд идущих компоненты."""
    z = layer.zoom
    h_px = _cap_height_px(comps, z)
    base_px = baseline_px(comps, z)

    cands = list(variants) if variants else layer.variants_for(h_px)
    best_total, best = _dp_over(layer, comps, charset, cands, base_px, h_px)

    # ВТОРОЙ ПРОХОД. Гарнитура выбирается по странице, но на одном листе их
    # может быть несколько (здесь: тело — Arial, шапка колонок — Arial Narrow).
    # Пробовать все гарнитуры сразу нельзя: близкие по форме варианты
    # выигрывают по IoU и портят уверенно читаемый текст. Поэтому прочие
    # гарнитуры пробуются ТОЛЬКО если первый проход дал плохой результат.
    if variants is None and (best_total < 0.20 or "?" in best[0]):
        used = {v.font for v in cands}
        extra = layer.fallback_variants(h_px, used)
        if extra:
            probe = comps[:12]
            masks = layer._probe_masks(probe)
            extra = sorted(
                extra,
                key=lambda v: -layer._mean_best_iou(probe, v.font, v.size, charset, masks))[:3]
            t2, b2 = _dp_over(layer, comps, charset, extra, base_px, h_px)
            if t2 > best_total:
                best_total, best = t2, b2
    return best


def _dp_over(layer: GlyphLayer, comps: list[tuple], charset: str,
             cands: list[Variant], base_px: float, h_px: float
             ) -> tuple[float, tuple[str, list[GlyphResult]]]:
    z = layer.zoom
    best_total, best = -1e9, ("", [])
    for variant in cands:
        n = len(comps)
        dp: list[tuple[float, tuple | None]] = [(-1e9, None)] * (n + 1)
        dp[0] = (0.0, None)
        for i in range(1, n + 1):
            for k in (1, 2, 3):
                j = i - k
                if j < 0 or dp[j][0] <= -1e8:
                    continue
                grp = comps[j:i]
                bb = (min(g[0] for g in grp), min(g[1] for g in grp),
                      max(g[2] for g in grp), max(g[3] for g in grp))
                ch, conf, alts = _classify(layer, bb, variant, base_px, charset)
                if not ch:
                    continue
                # склейка нескольких компонент — только для составных символов
                if k > 1 and ch not in MULTIPART:
                    continue
                # ВАЖНО: цель — сумма (conf - PRIOR), а не сумма conf.
                # При сумме conf ДП всегда выгоднее раздробить символ на части
                # (два слабых совпадения дают больше одного сильного), из-за
                # чего 'ы' стабильно распадалось на 'ь' + ':'.
                val = dp[j][0] + (conf - 0.40) - (0.40 if ch == "?" else 0.0)
                if k > 1:
                    val += 0.10        # верное составное совпадение — сильный признак
                if val > dp[i][0]:
                    dp[i] = (val, (j, ch, conf, bb, alts))
        if dp[n][0] <= -1e8:
            continue
        seq: list[GlyphResult] = []
        i = n
        while i > 0:
            step = dp[i][1]
            if step is None:
                break
            j, ch, conf, bb, alts = step
            seq.append(GlyphResult(ch, bb, round(conf, 3), alts))
            i = j
        seq.reverse()
        score = dp[n][0] / max(1, len(seq))
        if score > best_total:
            best_total, best = score, (_join(seq, variant, charset, z), seq)
    return best_total, best


def _join(seq: list[GlyphResult], variant: Variant, charset: str, zoom: float) -> str:
    """Склеивает символы, вставляя пробелы по МЕТРИКАМ шрифта.

    Порог «доля кегля» здесь не работает: у узких глифов боковые отбивки велики,
    и зазор между двумя '1' сравним с пробелом. Из-за этого 'Н114-750-0,9'
    читалось как 'Н1 14-750-0,9', а '11' в шапке — как '1 1'.

    Ожидаемый зазор между соседними символами — это правая отбивка левого плюс
    левая отбивка правого; они берутся из того же шрифта, что и шаблоны. Пробел
    добавляется, только если фактический зазор превышает ожидаемый примерно на
    половину ширины пробела.
    """
    if not seq:
        return ""
    tpl = {t.ch: t for t in _templates(variant.font, variant.size, charset)}
    space = _space_advance(variant.font, variant.size)
    out = [seq[0].char]
    for prev, cur in zip(seq, seq[1:]):
        gap = (cur.bbox[0] - prev.bbox[2]) * zoom
        tp, tc = tpl.get(prev.char), tpl.get(cur.char)
        if tp is not None and tc is not None:
            expected = max(0.0, tp.adv - tp.lsb - tp.w) + max(0.0, tc.lsb)
        else:
            expected = 0.10 * variant.size
        if gap > expected + 0.5 * space:
            out.append(" ")
        out.append(cur.char)
    # Серии нераспознанных глифов сворачиваем в один знак. Символ типа профиля
    # («Ι» у двутавра, «[» у швеллера) нарисован отдельными штрихами и даёт
    # столько же '?', сколько штрихов: «25Ш1 ? ? ?» вместо «Ι 25Ш1».
    return re.sub(r"\?(?:[ ]*\?)+", "?", "".join(out))


def read_cell(layer: GlyphLayer, bbox: tuple[float, float, float, float],
              charset: str = "any") -> tuple[str, float, list[GlyphResult]]:
    """Читает векторный текст внутри bbox. -> (текст, min confidence, глифы)."""
    cs = CHARSETS.get(charset, CHARSET_TEXT)
    comps = layer.components_in(bbox)
    if not comps:
        return "", 1.0, []
    comps = merge_diacritics(merge_counters(comps))
    texts: list[str] = []
    glyphs: list[GlyphResult] = []
    for L in group_lines(comps):
        t, gs = _read_line(layer, L, cs)
        if t.strip():
            texts.append(t.strip())
            glyphs.extend(gs)
    conf = min((g.confidence for g in glyphs), default=1.0)
    return "\n".join(texts), conf, glyphs
