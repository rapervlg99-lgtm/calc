# -*- coding: utf-8 -*-
"""Семантика таблицы: шапка -> роли колонок, строки -> логические записи.

Геометрия (`vector_grid`) даёт сетку и merged cells; здесь она превращается в
предметную модель спецификации металлопроката:

  * распознаётся шапка (сколько строк занимает, что в каких колонках);
  * колонкам присваиваются РОЛИ по тексту шапки, а не по номеру, чтобы модуль
    выдерживал перестановку и разное число колонок «по элементам конструкции»;
  * ruled-блок разбивается на логические таблицы: собственно спецификация,
    итоговая строка «Масса металла» и таблица «В том числе по маркам или
    наименованиям» — на листе они нарисованы одной рамкой, но это разные
    сущности;
  * строки-итоги («Итого», «Всего профиля») помечаются, а не выбрасываются;
  * merged-ячейка с несколькими номерами позиций разворачивается в несколько
    логических строк.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .models import Cell, Table
from .normalizer import extract_standards, normalize_cell, row_marker, strip_standards
from .vector_grid import TableBlock

# Ключевые слова шапки -> роль колонки. Сопоставление по «скелету» строки
# (нижний регистр, только буквы и цифры), поэтому переносы и запятые не мешают.
ROLE_PATTERNS: list[tuple[str, str]] = [
    ("наименованиепрофиля", "profile_group"),
    ("наименованиепрофил", "profile_group"),
    ("науменованиепрофил", "profile_group"),   # OCR «Наименование»
    ("наименованиеилимаркаметалла", "steel_grade"),
    ("маркаметалл", "steel_grade"),
    ("номеринразмерыпрофиля", "profile_size"),
    ("номеринлиразмерыпрофиля", "profile_size"),
    ("номерилиразмерыпрофиля", "profile_size"),
    ("номерилиразмер", "profile_size"),       # OCR без «профиля, мм»
    ("размерыпрофил", "profile_size"),
    ("пп", "position"),
    ("поз", "position"),
    ("общаямасса", "total_mass"),
    ("общаямасс", "total_mass"),
    ("площадь", "area"),                 # «Площадь окрашиваемой поверхности, м2»
    ("массаметаллапоэлементамконструкции", "element_group"),
    ("массаметаллапоэлемент", "element_group"),
]

SPEC_TITLE_RE = re.compile(r"спецификац\w*\s+металлопрокат\w*", re.I)
PART_RE = re.compile(r"\b(начало|окончание|продолжение)\b", re.I)

# Закрытый словарь шапки спецификации. Чертёжный ISOCPEUR даёт
# «Науменование» / «Macca» / «UNU» вместо «или» — это те же подписи,
# а не данные; подменяем только при высоком совпадении скелета.
HEADER_CANON = [
    "Наименование профиля, ГОСТ, ТУ",
    "Наименование или марка металла, ГОСТ, ТУ",
    "Номер или размеры профиля, мм",
    "Масса металла по элементам конструкций, т",
    "Общая масса, т",
    "Площадь окрашиваемой поверхности, м2",
    "№ п.п.",
]
HEADER_MIN_RATIO = 0.78
HEADER_MIN_SKEL = 8

# Типовые наименования групп профиля в спецификациях КМ/КР.
# Обозначения размера («26Б1») сюда не входят — их по словарю не чиним.
PROFILE_GROUP_CANON = [
    "Профили стальные гнутые замкнутые сварные квадратные и прямоугольные для строительных конструкций",
    "Профили стальные гнутые замкнутые сварные квадратные",
    "Профили стальные гнутые замкнутые сварные прямоугольные",
    "Двутавры стальные горячекатаные с параллельными гранями полок",
    "Двутавры стальные горячекатаные",
    "Швеллеры стальные горячекатаные",
    "Уголки стальные горячекатаные равнополочные",
    "Уголки стальные горячекатаные неравнополочные",
    "Прокат листовой горячекатаный",
    "Прокат листовой холоднокатаный",
    "Прокат горячекатаный",
    "Сталь листовая горячекатаная",
    "Листы стальные",
    "Листы стальные просечно-вытяжные",
    "Профили стальные листовые гнутые с трапецеидальными гофрами для строительства",
    "Профили стальные листовые гнутые для строительства",
    "Трубы стальные электросварные прямошовные",
    "Трубы электросварные прямошовные", "Трубы стальные электросварные",
    "Труба квадратная", "Трубы квадратные", "Трубы стальные квадратные",
    "Труба прямоугольная", "Трубы стальные прямоугольные",
    "Трубы стальные бесшовные горячедеформированные",
    "Трубы стальные прямоугольного сечения",
    "Трубы стальные квадратного сечения",
    "Круг стальной горячекатаный",
    "Арматура стержневая",
    "Рельсы крановые",
    "Профнастил",
]
PROFILE_MIN_RATIO = 0.68
PROFILE_MIN_SKEL = 15
# Служебные строки колонки «наименование» словарём не трогаем.
_SKIP_PROFILE_CANON = (
    "итого", "всего", "примечан", "втомчисле", "массаметалла",
    "марком", "маркам",
)
# ГОСТ/ТУ, прилипшие к скелету («ост850993» из «ОСТ 8509-93»).
_SKEL_STD = re.compile(r"(гост|ту|сто|ост|foct|toct)\d+")

# Типовые подписи колонок «по элементам конструкций». Растровый OCR читает
# чертёжный курсив как латино-греческую кашу («ΦepMbl», «5αAKU»,
# «nodcmponunbuble фермы»), а иногда просто путает буквы («Траберсы»).
# Имя элемента идёт в ключи масс и в калькулятор ОЗМ, поэтому подгоняем его
# к словарю; исходный текст ячейки шапки не меняется (см. Column.title).
ELEMENT_CANON = [
    "Колонны", "Стойки", "Колонны, стойки", "Колонны/Стойки", "Колонны, базы колонн",
    "Базы колонн", "Надколонники", "Надколонник", "Стойки фахверка", "Фахверк",
    "Балки", "Балки покрытия", "Балки перекрытия", "Балки площадок",
    "Подкрановые балки", "Тормозные балки", "Ригели", "Прогоны", "Траверсы",
    "Фермы", "Стропильные фермы", "Подстропильные фермы", "Фермы стропильные",
    "Фермы подстропильные", "Фонари", "Рамы", "Рамы под люки дымоудаления",
    "Балочные клетки", "Профлист", "Профлист по фермам", "Профнастил по фермам",
    "Связи", "Распорки", "Связи, распорки", "Распорки по колоннам",
    "Связи покрытия", "Связи по покрытию", "Связи по колоннам и покрытию",
    "Связи вертикальные", "Связи горизонтальные", "Связи, стойки фахверка",
    "Связи по колоннам", "Связи по фермам", "Вертикальные связи", "Горизонтальные связи",
    "Площадки", "Лестницы", "Ограждения", "Настил", "Профнастил",
    "Профнастил покрытия", "Кронштейны", "Опоры", "Подвески", "Эстакада",
]
ELEMENT_MIN_RATIO = 0.75
ELEMENT_MIN_SKEL = 4
_CYR_LETTER = re.compile(r"[а-яё]", re.I)
_OTHER_LETTER = re.compile(r"[a-zα-ωΑ-Ω]")

# Пометка части таблицы — ЗАКРЫТЫЙ словарь из трёх слов. На листе она взорвана
# в векторы и читается с ошибками («Окпнчвнив»), поэтому допускается неточное
# совпадение. Это структурный маркер, а не данные: подмена значения невозможна,
# а факт нечёткого сопоставления протоколируется.
PART_WORDS = ("начало", "окончание", "продолжение")
PART_MAX_MISMATCH = 0.40


def _fuzzy_part(text: str) -> str:
    """Ближайшее слово из PART_WORDS или '' — по доле несовпавших символов."""
    for token in re.findall(r"[А-Яа-яЁё]{5,}", text):
        low = token.lower()
        for word in PART_WORDS:
            if abs(len(low) - len(word)) > 1:
                continue
            n = min(len(low), len(word))
            bad = sum(1 for a, b in zip(low[:n], word[:n]) if a != b)
            bad += abs(len(low) - len(word))
            if bad / max(len(word), 1) <= PART_MAX_MISMATCH:
                return word
    return ""


# Латинские двойники в шапке (RapidOCR: «Macca» вместо «Масса», «KOHC» и т.п.).
# Только для сопоставления ролей — значение ячейки не меняем.
_SKEL_HOMO = str.maketrans({
    "a": "а", "b": "в", "c": "с", "e": "е", "h": "н", "k": "к", "m": "м",
    "o": "о", "p": "р", "t": "т", "x": "х", "y": "у",
})


def skeleton(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).lower().translate(_SKEL_HOMO)
    return "".join(c for c in t if c.isalnum())


# Чертёжный курсив (ISOCPEUR Italic) растровый OCR читает системно неверно:
# «Прокат горячекатаный» -> «nроkаm 20рАНеКОmаНblU», «Двутавры стальные» ->
# «Аbуmаbрbl сМα/bНblе», «Всего профиля» -> «Все20 nроΦu/9». Подмены устойчивые,
# поэтому для СОПОСТАВЛЕНИЯ со словарём (и только для него — текст ячейки не
# меняется) текст предварительно сворачивается этой картой. Порядок важен:
# сначала пары символов, потом одиночные.
_DRAWING_PAIRS = (
    ("bl", "ы"), ("/b", "ль"), ("|b", "ль"), ("20", "го"), ("2о", "го"), ("2а", "га"),
    ("Φu", "фи"), ("中u", "фи"), ("qU", "чи"), ("Nb", "нь"), ("zо", "го"), ("zo", "го"),
)
_DRAWING_CHARS = str.maketrans({
    "n": "п", "∩": "п", "u": "и", "U": "и", "k": "к", "m": "т", "b": "в",
    "l": "л", "/": "л", "N": "н", "Φ": "ф", "φ": "ф", "中": "ф", "α": "а", "Q": "а",
    "q": "ч", "g": "я", "9": "я", "3": "з", "6": "б", "5": "б", "0": "о", "4": "ч", "z": "г",
    "2": "г", "d": "д", "A": "а", "a": "а", "c": "с", "e": "е", "o": "о",
    "p": "р", "x": "х", "y": "у", "M": "м", "H": "н", "K": "к", "C": "с",
    "E": "е", "O": "о", "P": "р", "T": "т", "X": "х", "Y": "у", "B": "в",
})


def drawing_fold(text: str) -> str:
    """Каша OCR по чертёжному курсиву -> правдоподобная кириллица (для матчинга)."""
    t = text
    for a, b in _DRAWING_PAIRS:
        t = t.replace(a, b)
    return t.translate(_DRAWING_CHARS)


# Ссылки на стандарты в сыром тексте («ГОСТ 19903-2015», «FОСТ 27772-2021»,
# «ТУ 14-1-…»): в сопоставлении наименований не участвуют, а после свёртки
# курсива их цифры превращались бы в буквы и портили скелет.
_RAW_STD = re.compile(r"(?i)(?<![а-яa-z])(?:[гfg]ост|ост|ту|сто|foct|toct)\s*р?\s*\d[\d.\-–\s]*")


def skeletons(text: str) -> tuple[str, str]:
    """Обычный скелет и скелет после свёртки чертёжного курсива (без ГОСТ/ТУ)."""
    bare = _RAW_STD.sub(" ", text)
    return skeleton(text), skeleton(drawing_fold(bare))


_SIZE_TOKEN_RE = re.compile(r"(?<![\wА-Яа-я])\d{1,3}(?:[.,]\d)?\s*[хx×*]\s*\d{1,3}(?:\s*[хx×*]\s*\d{1,3}(?:[.,]\d)?)?(?![\w])")
# Классы похожих букв определены ниже (см. canonical_element), но нужны здесь;
# Python разрешает ссылку на имя модуля во время вызова, а не объявления.


def _best_canon(text: str, catalog: list[str], min_ratio: float,
                min_skel: int) -> tuple[str, float]:
    """Ближайшая каноническая фраза или ('', 0). Стандарты в сравнении не участвуют."""
    # размеры внутри наименования («Труба квадратная 120х120х6») в сравнении
    # не участвуют — иначе цифры размывают сходство со словарной фразой
    text = _SIZE_TOKEN_RE.sub(" ", text)
    variants = [_SKEL_STD.sub("", sk) for sk in skeletons(text)]
    variants = [v for v in variants if len(v) >= min_skel]
    if not variants:
        return "", 0.0
    best, best_r = "", 0.0
    for cand in catalog:
        csk = skeleton(cand)
        for sk in variants:
            r = SequenceMatcher(None, sk, csk).ratio()
            if r > best_r:
                best, best_r = cand, r
    if best_r < min_ratio:
        # второй проход по классам похожих букв курсива (о↔а, б↔в, л↔н):
        # «трубаквоаротноа» и «трубаквадратная» сходятся только так
        for cand in catalog:
            csk = skeleton(cand).translate(_CYR_CONFUSION)
            for sk in variants:
                r = SequenceMatcher(None, sk.translate(_CYR_CONFUSION), csk).ratio()
                if r > best_r:
                    best, best_r = cand, r
    return (best, best_r) if best_r >= min_ratio else ("", 0.0)


def canonical_header(text: str) -> tuple[str, float]:
    """Каноническая подпись колонки шапки, если OCR достаточно близок."""
    return _best_canon(text, HEADER_CANON, HEADER_MIN_RATIO, HEADER_MIN_SKEL)


def is_service_profile_text(text: str) -> bool:
    """Служебная строка колонки наименования («Итого», «Примечания…», «Масса
    металла по маркам») — словарь групп и подсказки по стандарту её не трогают."""
    return any(m in sk for sk in skeletons(text) for m in _SKIP_PROFILE_CANON)


def canonical_profile_group(text: str) -> tuple[str, float]:
    """Каноническое наименование группы профиля, если OCR достаточно близок."""
    if is_service_profile_text(text):
        return "", 0.0
    return _best_canon(text, PROFILE_GROUP_CANON, PROFILE_MIN_RATIO, PROFILE_MIN_SKEL)


# Устойчивые подмены кириллицы у Tesseract на выпрямленном чертёжном курсиве:
# «Ванки» вместо «Балки», «бертикольные» вместо «вертикальные». Для сравнения с
# коротким словарным именем обе стороны сводятся к классам похожих букв.
_CYR_CONFUSION = str.maketrans({"в": "б", "н": "л", "а": "о", "й": "и", "ё": "е", "ь": "", "ъ": ""})


def _confusion_key(text: str) -> str:
    return skeleton(text).translate(_CYR_CONFUSION)


def canonical_element(text: str) -> tuple[str, float]:
    """Каноническое наименование элемента конструкции, если OCR достаточно близок."""
    canon, ratio = _best_canon(text, ELEMENT_CANON, ELEMENT_MIN_RATIO, ELEMENT_MIN_SKEL)
    if canon:
        return canon, ratio
    # короткая подпись с типовой подменой букв: совпадение по классам букв
    for variant in (text, drawing_fold(text)):
        key = _confusion_key(variant)
        if len(key) < ELEMENT_MIN_SKEL:
            continue
        for cand in ELEMENT_CANON:
            if _confusion_key(cand) == key:
                return cand, ELEMENT_MIN_RATIO
    return "", 0.0


def element_name(raw: str) -> str:
    """Имя элемента конструкции из ячейки шапки.

    1) переносы сшиваются; 2) словарь типовых подписей через свёртку курсива
    («ΦepMbl» -> «Фермы», «Траберсы» -> «Траверсы»); 3) вне словаря, но с
    латиницей/греческим внутри — оставляем свёрнутый вариант, если он стал
    кириллицей («nodcmponunbuble фермы» -> «подстропипвиые фермы» хуже, чем
    словарное «Подстропильные фермы», но лучше исходной каши); 4) иначе как есть.
    """
    text = _dehyphenate(raw.replace("\n", " "))
    if not text:
        return ""
    text = fix_paren_s(text)
    canon, _ = canonical_element(text)
    if canon:
        return canon
    if _OTHER_LETTER.search(text):
        folded = drawing_fold(text)
        if not _OTHER_LETTER.search(folded) and _CYR_LETTER.search(folded):
            folded = re.sub(r"\s+", " ", folded).strip(" ,;")
            return folded[:1].upper() + folded[1:]
    return text


def dedupe_elements(cols: list["Column"], raw: dict[int, str]) -> None:
    """Два столбца сошлись к одному словарному имени — возвращаем им сырые
    подписи: имя элемента служит ключом масс, и слияние потеряло бы столбец."""
    seen: dict[str, list[Column]] = {}
    for c in cols:
        if c.role == "element_mass" and c.element:
            seen.setdefault(c.element, []).append(c)
    for name, group in seen.items():
        if len(group) > 1:
            for c in group:
                c.element = _dehyphenate(raw.get(c.index, name).replace("\n", " ")) or name


def refine_structure(grid: dict[tuple[int, int], Cell], n_rows: int, n_cols: int,
                     block: TableBlock) -> tuple[list[int], list[Column]]:
    """Шапка и роли по полной сетке (со span), не по неполному probe.

    Probe хранит merged-ячейки только в якоре, и служебная строка номеров
    колонок на file-4 не попадала в шапку: «1 2 3 4  6» уходили в данные,
    а «Фахверк»/«Связи» считались массами. После заполнения span строка
    номеров находится, подписи шапки приводятся к канону, роли пересчитываются.
    """
    header_rows, numbering = detect_header_rows(grid, n_rows, n_cols)
    unit = header_mass_unit(grid, header_rows, numbering, n_cols)
    seen: set[int] = set()
    for r in header_rows:
        if numbering is not None and r == numbering:
            continue
        for c in range(n_cols):
            cell = grid.get((r, c))
            if cell is None or id(cell) in seen or not cell.text.strip():
                continue
            seen.add(id(cell))
            if cell.source not in ("ocr", "vector_glyph", "mixed"):
                continue
            fixed = fix_paren_s(cell.text)
            if fixed != cell.text:
                cell.notes.append("скобка перед словом прочитана вместо «С»; raw=%r" % cell.text)
                cell.text = fixed
            canon, ratio = canonical_header(cell.text)
            if not canon:
                continue
            compact = " ".join(cell.text.replace("\n", " ").split())
            if compact == canon:
                continue
            cell.notes.append(
                "шапка приведена к каноническому виду (%.2f); raw=%r" % (ratio, cell.text))
            cell.text = canon
            if ratio >= 0.88:
                cell.requires_review = False
    cols = assign_roles(grid, header_rows, numbering, n_cols, block)
    for col in cols:
        if col.role in ("element_mass", "total_mass"):
            col.unit = unit
    return header_rows, cols


# Единица массы в подписи шапки: «Общая масса, т» / «…, кг». Килограммы OCR
# читает как «кг», «Ке», «K2», «kg», «кz». Проверяется ДО канонизации подписей:
# словарь шапки сворачивает всё в «Общая масса, т» и след единицы пропадает.
_UNIT_KG_RE = re.compile(r"масс\w*(кг|ке|kg|кz|к2|k2|kz|кr|kr)$")
_UNIT_T_RE = re.compile(r"масс\w*(т|m|t)$")


def header_mass_unit(grid: dict[tuple[int, int], Cell], header_rows: list[int],
                     numbering: int | None, n_cols: int) -> str:
    """«кг», если хоть одна подпись масс в шапке заканчивается килограммами и ни
    одна — тоннами; «кг?», если подписи противоречат друг другу (Obshchaga_KM:
    «…по элементам конструкций, т» и «Общая масса, кг» на одном листе — решает
    порядок чисел, см. resolve_mass_unit); иначе «т»."""
    kg = tonnes = 0
    seen: set[int] = set()
    for r in header_rows:
        if numbering is not None and r == numbering:
            continue
        for c in range(n_cols):
            cell = grid.get((r, c))
            if cell is None or id(cell) in seen or not cell.text.strip():
                continue
            seen.add(id(cell))
            for sk in skeletons(cell.text):
                if "масс" not in sk:
                    continue
                if _UNIT_KG_RE.search(sk):
                    kg += 1
                elif _UNIT_T_RE.search(sk):
                    tonnes += 1
                break
    if kg and tonnes:
        return "кг?"
    return "кг" if kg else "т"


@dataclass
class Column:
    index: int
    role: str
    title: str
    letter: str = ""          # номер колонки из служебной строки листа
    bbox: tuple = (0, 0, 0, 0)
    element: str = ""         # для element_mass — название элемента конструкции
    unit: str = ""            # для масс: «т» (по умолчанию) или «кг», как подписано в шапке


@dataclass
class LogicalRow:
    row: int
    kind: str                 # data|group_total|profile_total|grand_total|section_header|empty
    position: int | None = None
    cells: dict[str, Cell] = field(default_factory=dict)   # role/element -> Cell
    notes: list[str] = field(default_factory=list)


def detect_header_rows(grid: dict[tuple[int, int], Cell], n_rows: int,
                       n_cols: int) -> tuple[list[int], int | None]:
    """(индексы строк шапки, индекс служебной строки нумерации колонок).

    Служебная строка — это та, где почти каждая ячейка содержит одно небольшое
    целое (1, 2, 3, ... 14). В отечественных спецификациях она есть почти всегда
    и служит надёжной границей шапки.
    """
    numbering = None
    for r in range(min(n_rows, 6)):
        ints: list[int] = []
        for c in range(n_cols):
            cell = grid.get((r, c))
            if cell is None:
                continue
            t = cell.text.strip()
            if t.isdigit() and len(t) <= 2:
                n = int(t)
                if 1 <= n <= n_cols + 1:
                    ints.append(n)
        # Не требуем 70% заполнения: при объединённых ячейках шапки часть
        # номеров пропадает («1 2» было в одной клетке, после шва колонок
        # остаётся «1;2;3;4;;6»). Достаточно трёх номеров начиная с 1.
        # «1» в первой клетке нередко не читается (растр низкого разрешения),
        # тогда строка начинается с 2: достаточно трёх подряд идущих номеров
        uniq = sorted(set(ints))
        starts_at_two = len(uniq) >= 3 and uniq[0] == 2 and uniq[1] == 3 and uniq[2] == 4
        if len(ints) >= 3 and len(uniq) >= 3 and (uniq[0] == 1 or starts_at_two):
            numbering = r
            break
    if numbering is None:
        # запасной вариант: строка 0 плюс подшапка многоуровневой шапки
        return _extend_header_fallback(grid, n_rows, n_cols), None
    return list(range(numbering + 1)), numbering


_NUMERIC_TEXT_RE = re.compile(r"^[\d\s.,;:\-–]+$")


def _looks_numeric(text: str) -> bool:
    t = text.strip()
    return bool(t) and any(ch.isdigit() for ch in t) and bool(_NUMERIC_TEXT_RE.fullmatch(t))


def _covering_header_cell(grid: dict[tuple[int, int], Cell], r: int, c: int,
                          header_rows: list[int]) -> Cell | None:
    """Ячейка шапки из строки выше, накрывающая (r, c) своим row_span.

    В полной сетке merged-ячейка лежит копией в каждой накрытой клетке, а в
    probe (`read_header`) — только в якоре, поэтому проверяются оба варианта.
    """
    cell = grid.get((r, c))
    if cell is not None:
        return cell if (cell.row < r and cell.row in header_rows) else None
    for hr in header_rows:
        for cc in range(c, -1, -1):
            anchor = grid.get((hr, cc))
            if anchor is None or anchor.row != hr or anchor.col != cc:
                continue
            if anchor.col + anchor.col_span > c and anchor.row + anchor.row_span > r:
                return anchor
            break
    return None


def _extend_header_fallback(grid: dict[tuple[int, int], Cell], n_rows: int,
                            n_cols: int) -> list[int]:
    """Шапка без служебной строки номеров: строка 0 и подшапки под ней.

    На file-13 шапка двухуровневая: «Масса металла по элементам конструкции»
    объединяет пять колонок, а названия элементов («Колонны», «Балки», «Связи
    вертикальные»…) стоят строкой ниже, повёрнутые на 90°. Служебной строки
    номеров на листе нет, шапкой считалась только строка 0, названия элементов
    уходили в данные, и массы получали безымянные колонки «col4»…«col8» — в
    калькуляторе у всех строк пустой «Элемент конструкции».

    Строка r присоединяется к шапке, если (1) хотя бы одну её клетку накрывает
    row_span ячейки шапки сверху — признак многоуровневой шапки, (2) в ней есть
    собственный нечисловой текст (подписи подколонок) и (3) нет ни одной
    числовой клетки — строка данных или «Всего профиля» с номером позиции
    шапкой не станет. Не больше четырёх строк и всегда остаётся строка данных.
    """
    header = [0]
    r = 1
    while r < min(n_rows - 1, 4):
        covered = 0
        own_text = 0
        for c in range(n_cols):
            cell = grid.get((r, c))
            if cell is not None and cell.row == r:
                t = cell.text.strip()
                if not t:
                    continue
                if _looks_numeric(t):
                    return header
                own_text += 1
            elif _covering_header_cell(grid, r, c, header) is not None:
                covered += 1
        if covered == 0 or own_text == 0:
            return header
        header.append(r)
        r += 1
    return header


def assign_roles(grid: dict[tuple[int, int], Cell], header_rows: list[int],
                 numbering_row: int | None, n_cols: int,
                 block: TableBlock) -> list[Column]:
    """Присваивает роли колонкам по тексту шапки, с позиционным запасным вариантом."""
    cols: list[Column] = []
    raw_elements: dict[int, str] = {}
    # Заголовок каждой колонки — конкатенация текстов её ячеек шапки.
    titles: list[str] = []
    for c in range(n_cols):
        parts: list[str] = []
        for r in header_rows:
            if numbering_row is not None and r == numbering_row:
                continue
            cell = grid.get((r, c))
            if cell is not None and cell.text.strip():
                # ячейка «Масса металла по элементам конструкции» объединяет
                # много колонок — её текст не должен попасть в каждую
                if cell.col_span > 1 and cell.col != c:
                    continue
                # span-заполненная копия: текст принадлежит якорной строке,
                # иначе «Наименование профиля» дублировалось из строк 0 и 1
                if cell.row != r:
                    continue
                parts.append(cell.text.replace("\n", " "))
        titles.append(" ".join(parts).strip())

    # Групповая ячейка «Масса металла по элементам конструкции, т» задаёт
    # диапазон колонок с массами по элементам.
    element_range: tuple[int, int] | None = None
    for r in header_rows:
        for c in range(n_cols):
            cell = grid.get((r, c))
            if cell is None or cell.col != c or cell.col_span < 2:
                continue
            sks = skeletons(cell.text)
            # Полная подпись — «Масса металла по элементам конструкций»; чертёжным
            # шрифтом OCR оставляет от неё «по элементам п» или «Macca no
            # 3neMeHmaM». Объединённая ячейка шапки шириной в несколько колонок с
            # таким остатком — это она. Курсивом растровый OCR даёт и «Масса
            # металла по зиементам, т» — сравниваем начало скелета нечётко.
            if any("массаметаллапоэлемент" in sk or "поэлемент" in sk or "элементамконстр" in sk
                   or _close_prefix(sk, "массаметаллапоэлементам") for sk in sks):
                element_range = (cell.col, cell.col + cell.col_span - 1)
    for c in range(n_cols):
        role = ""
        sk = skeleton(titles[c])
        for pat, rl in ROLE_PATTERNS:
            if pat in sk:
                role = rl
                break
        if element_range and element_range[0] <= c <= element_range[1]:
            role = "element_mass"
        elif role in ("", "element_group"):
            # СТРОГО по объединённой ячейке шапки. Раньше роль «масса элемента»
            # распространялась на все колонки правее её начала, и на листе КМ1
            # в суммы попадала «Площадь окрашиваемой поверхности, м2»: сумма по
            # строке выходила 16,79 вместо 0,61.
            role = "unknown"
        letter = ""
        if numbering_row is not None:
            nc = grid.get((numbering_row, c))
            if nc is not None:
                letter = nc.text.strip()
        cb = block.cell_at(header_rows[-1] if header_rows else 0, c)
        element = ""
        if role == "element_mass":
            # Название элемента — из самой нижней СОДЕРЖАТЕЛЬНОЙ строки шапки.
            # Служебную строку нумерации колонок пропускаем, иначе вместо
            # «Фермы»/«Надколонник» в имена элементов попадают «5», «6», «7».
            for r in reversed([x for x in header_rows if x != numbering_row]):
                cell = grid.get((r, c))
                if cell is not None and cell.col == c and cell.col_span == 1 and cell.text.strip():
                    element = cell.text
                    break
            raw_elements[c] = element
            element = element_name(element)
        cols.append(Column(c, role, " ".join(titles[c].split()), letter,
                           cb.bbox if cb else (0, 0, 0, 0), element))

    # Шапка блока масс не прочиталась вовсе, но есть служебная строка номеров,
    # слева стоят «№ п.п.» (или размер профиля), а справа — колонка с «масс»:
    # всё между ними — массы по элементам конструкций.
    if element_range is None and numbering_row is not None and n_cols >= 6:
        left = next((c.index for c in cols if c.role == "position"), None)
        from_size = left is None
        if left is None:
            left = next((c.index for c in cols if c.role == "profile_size"), None)
        last = n_cols - 1
        # «№ п.п.» не прочиталась (подпись повёрнута на 90°), а роль
        # определяется по размеру профиля: колонка сразу за размером без
        # словесной подписи — это номера позиций, а не первая масса. Иначе на
        # file-14 в массы по элементам попадали номера 1…37, и таблица не
        # становилась спецификацией.
        if (from_size and left is not None and last - left >= 4
                and cols[left + 1].role in ("", "unknown")
                and not skeleton(cols[left + 1].title).isalpha()):
            cols[left + 1].role = "position"
            cols[left + 1].title = "№ п.п."
            left += 1
        if (left is not None and last - left >= 3
                and any("масс" in sk for sk in skeletons(cols[last].title))
                and all(cols[c].role in ("", "unknown") for c in range(left + 1, last))):
            element_range = (left + 1, last - 1)
            for c in range(left + 1, last):
                cols[c].role = "element_mass"
                if not cols[c].element:
                    for r in reversed([x for x in header_rows if x != numbering_row]):
                        cell = grid.get((r, c))
                        if cell is not None and cell.col == c and cell.col_span == 1 and cell.text.strip():
                            raw_elements[c] = cell.text
                            cols[c].element = element_name(cell.text)
                            break
    dedupe_elements(cols, raw_elements)

    # Первая колонка перед «маркой металла» и «размером профиля» — наименование
    # профиля, даже если её подпись прочиталась как «Нацменование rосt».
    if (n_cols >= 3 and cols[0].role in ("", "unknown")
            and cols[1].role == "steel_grade" and cols[2].role == "profile_size"):
        cols[0].role = "profile_group"

    # Колонка сразу справа от «массы по элементам» — общая масса.
    # На file-3 OCR съел «Общая» и прочитал «т» как «Ш» («масса, Ш»),
    # без этой подстановки таблица не становилась спецификацией.
    if element_range:
        after = element_range[1] + 1
        last = n_cols - 1
        # общая масса — сразу за блоком масс: последняя колонка либо
        # предпоследняя, когда за ней «Площадь окрашиваемой поверхности»
        total_at = after if (after == last or (after == last - 1 and cols[last].role == "area")) else None
        if total_at is not None and cols[total_at].role in ("", "unknown"):
            sks = skeletons(cols[total_at].title)
            sk = sks[0]
            if ((not sk) or any("масс" in x for x in sks) or sk in ("т", "m", "ш", "п")
                    or _fuzzy_mass_title(sks)):
                cols[total_at].role = "total_mass"
                if not any("общая" in x for x in sks):
                    cols[total_at].title = "Общая масса, т"
        # «№ п.п.» — единственная колонка между размером профиля и массами по
        # элементам; её подпись чертёжным шрифтом OCR читает как «0?,,?».
        first = element_range[0]
        if (first >= 2 and cols[first - 1].role in ("", "unknown")
                and cols[first - 2].role == "profile_size"):
            cols[first - 1].role = "position"
            if not skeleton(cols[first - 1].title).isalpha():
                cols[first - 1].title = "№ п.п."

    # Позиционный запасной вариант — ТОЛЬКО для листов, где шапка не прочиталась
    # вовсе, но геометрия совпадает со спецификацией металлопроката (14 колонок:
    # 4 описательных + элементы + общая масса). Раньше условие было слабее, и
    # ведомости объёмов работ навязывались роли спецификации, после чего
    # запускались бессмысленные проверки «Цена против Стоимости».
    # Обязательное условие — распознанная СЛУЖЕБНАЯ СТРОКА нумерации колонок
    # (1, 2, 3, ... N). Без неё штамп листа (10 колонок, шапка не читается)
    # получал роли спецификации и выдавался за «Спецификацию металлопроката».
    if (numbering_row is not None and n_cols >= 10
            and all(col.role == "unknown" for col in cols)):
        default = ["profile_group", "steel_grade", "profile_size", "position"]
        for i, r in enumerate(default[:n_cols]):
            cols[i].role = r
        for i in range(len(default), n_cols - 1):
            cols[i].role = "element_mass"
        cols[-1].role = "total_mass"
    return cols


def classify_table(cols: list[Column]) -> str:
    """Вид таблицы по набору распознанных ролей колонок.

    `spec_main` — спецификация металлопроката (есть № п.п., массы по элементам
    и общая масса); для неё имеет смысл семантика строк и арифметические
    проверки. Всё остальное — `generic`: сетка и текст ячеек извлекаются как
    есть, но роли не выдумываются и итоги не пересчитываются.
    """
    roles = {c.role for c in cols}
    if {"position", "element_mass", "total_mass"} <= roles:
        return "spec_main"
    return "generic"


# Скобка в начале слова перед кириллицей — это «С» чертёжного курсива:
# «(Вязи покрытия» -> «Связи покрытия», «(редняя» -> «Средняя». Настоящая
# открывающая скобка сопровождается закрывающей — такой текст не трогаем.
_PAREN_S_RE = re.compile(r"(?<![\wА-Яа-яЁё])\((?=[А-Яа-яЁё]{2,})")
_PAREN_S_UPPER_RE = re.compile(r"(?<![\wА-Яа-яЁё])\(([А-ЯЁ])(?=[а-яё])")


def fix_paren_s(text: str) -> str:
    if "(" not in text or ")" in text:
        return text
    # «(Вязи» -> «Связи»: OCR поднял регистр первой видимой буквы слова
    out = _PAREN_S_UPPER_RE.sub(lambda m: "С" + m.group(1).lower(), text)
    return _PAREN_S_RE.sub("С", out)


# Типовые подписи основной надписи (штампа) листа по ГОСТ 21.101 — курсивом
# OCR читает их как «Проберил», «И3М.», «Аlаmа»; подтягиваем к канону.
STAMP_LABELS = [
    "Изм.", "Кол.уч.", "Лист", "№док.", "Подпись", "Дата", "Разработал",
    "Проверил", "Н.контр.", "Т.контр.", "ГИП", "Утвердил", "Стадия", "Листов",
    "Зам.", "Нов.", "Формат", "Согласовано", "Инв. № подл.", "Подпись и дата",
    "Взам. инв. №",
]
_STAMP_MIN_RATIO = 0.8


def canonical_stamp_label(text: str) -> str:
    """Подпись штампа в каноническом виде или '' (для коротких/чужих текстов)."""
    from difflib import SequenceMatcher
    compact = " ".join(text.replace("\n", " ").split())
    if not compact or len(compact) > 24:
        return ""
    # цифры после свёртки («09-25», «22.08.25») — это данные, не подпись
    if any(ch.isdigit() for ch in drawing_fold(compact)):
        return ""
    variants = {skeleton(compact), skeleton(drawing_fold(compact))}
    variants.discard("")
    best, best_r, best_len = "", 0.0, 0
    for label in STAMP_LABELS:
        lsk = skeleton(label)
        if len(lsk) < 3:
            continue
        for v in variants:
            if abs(len(v) - len(lsk)) > 2:
                continue
            r = SequenceMatcher(None, v, lsk).ratio()
            if r > best_r:
                best, best_r, best_len = label, r, len(lsk)
    # длинной подписи («нодписв» -> «Подпись») хватает 0.7: случайное слово
    # такой длины к ней не подойдёт, а коротким («Изм.», «Дата») нужен 0.8
    need = 0.7 if best_len >= 6 else _STAMP_MIN_RATIO
    return best if best_r >= need else ""


# Смешанное письмо внутри одного слова/ячейки («Осmроbсkuu», «Общеоброзоbательная»)
# — всегда ошибка OCR по курсиву: латиницы в русских подписях не бывает.
_LATIN_RUN = re.compile(r"[A-Za-z]")


def fold_mixed_script(text: str) -> str:
    """Свёртка курсива, если в тексте латиница вперемешку с кириллицей и после
    свёртки латиницы не остаётся. Иначе текст возвращается как есть."""
    if len(_LATIN_RUN.findall(text)) < 3 or not _CYR_LETTER.search(text):
        return text
    folded = drawing_fold(text)
    if _OTHER_LETTER.search(folded) or _LATIN_RUN.search(folded):
        return text
    return folded


def _fuzzy_mass_title(sks) -> bool:
    """Подпись «Общая масса, т», прочитанная с ошибками внутри слова
    («Maced, т» → «масеdт»): сравнивается с эталонами нечётко."""
    from difflib import SequenceMatcher
    for sk in sks:
        if not (4 <= len(sk) <= 14):
            continue
        for ref in ("массат", "общаямассат", "массакг"):
            if SequenceMatcher(None, sk, ref).ratio() >= 0.66:
                return True
    return False


def _close_prefix(sk: str, key: str, min_ratio: float = 0.8) -> bool:
    """Начало скелета `sk` длиной с `key` похоже на `key` (OCR-ошибки внутри слов)."""
    from difflib import SequenceMatcher
    if len(sk) < len(key) - 2:
        return False
    head = sk[:len(key) + 1]
    return SequenceMatcher(None, head, key).ratio() >= min_ratio


def _dehyphenate(text: str) -> str:
    """Сшивает слово, разорванное переносом при вёрстке шапки.

    'Надколон-\nник' -> 'Надколонник', 'Распорки\nпо\nколоннам' ->
    'Распорки по колоннам'. Строки склеиваются ПРОБЕЛОМ, и только висячий
    дефис убирается вместе с ним, иначе получалось 'Распоркипоколоннам'.
    """
    t = re.sub(r"-\s+", "", text)
    return " ".join(t.split())


def build_rows(grid: dict[tuple[int, int], Cell], cols: list[Column],
               header_rows: list[int], n_rows: int) -> list[LogicalRow]:
    """Строит логические строки, разворачивая merged-ячейки номеров позиций."""
    out: list[LogicalRow] = []
    first_data = (max(header_rows) + 1) if header_rows else 0

    for r in range(first_data, n_rows):
        cells: dict[str, Cell] = {}
        for c in range(len(cols)):
            cell = grid.get((r, c))
            if cell is None:
                continue
            # ВАЖНО: merged-ячейка принадлежит только своей «якорной» строке.
            # Иначе одно значение попадает в несколько строк и учитывается в
            # суммах дважды: на листе так слиты строки поз. 26 и 27, и «Итого»
            # получалось 17,0 вместо 8,5. Групповые колонки протягиваются
            # отдельно, в `group_context` — они не суммируются.
            if cell.row != r:
                continue
            cells[column_key(cols[c])] = cell

        kind = "data"
        for key in ("profile_group", "steel_grade", "profile_size"):
            cell = cells.get(key)
            if cell is None:
                continue
            marker = row_marker(cell.text)
            if marker:
                kind = marker
                break
        # «Всего профиля» по геометрии: в форме спецификации эта подпись
        # занимает одну ячейку на три графы (наименование, марка, размер) и
        # стоит в строке с массами. Курсивом OCR читает её и как «ый» или
        # «Sеер» — тогда строка уходила в данные и удваивала суммы группы.
        pg = cells.get("profile_group")
        if (kind == "data" and pg is not None and pg.row == r and pg.col_span >= 3
                and cells.get("position") is not None
                and pg.source in ("ocr", "vector_glyph", "mixed")
                and len((pg.text or "").split()) <= 3):
            kind = "profile_total"
            pg.notes.append("строка «Всего профиля» опознана по объединённой ячейке "
                            "на три графы; raw=%r" % pg.text)
            pg.text = "Всего профиля"
            # нормализация уже прошла — иначе в выгрузке остаётся сырое «сrееr еее»
            pg.normalized_value = pg.text
            pg.value_kind = "text"
            pg.requires_review = True
        if not cells or all(c.is_empty for c in cells.values()):
            kind = "empty"

        positions: list[int] = []
        pcell = cells.get("position")
        if pcell is not None:
            if isinstance(pcell.normalized_value, list):
                positions = pcell.normalized_value
            elif isinstance(pcell.normalized_value, int):
                positions = [pcell.normalized_value]

        if len(positions) <= 1:
            out.append(LogicalRow(r, kind, positions[0] if positions else None, cells))
        else:
            # Строки не разделены линией (так слиты поз. 26 и 27). Значения
            # относятся к merged-области целиком, поэтому дублировать их по
            # позициям нельзя: они остаются в первой строке, остальные получают
            # только номер позиции и пометку.
            for i, pos in enumerate(positions):
                sub = LogicalRow(r, kind, pos, cells if i == 0 else {"position": pcell})
                sub.notes.append(
                    "row not separated by a ruling line; %d positions share one cell"
                    % len(positions))
                out.append(sub)
    return out


def split_sections(rows: list[LogicalRow]) -> list[tuple[str, list[LogicalRow]]]:
    """Делит строки ruled-блока на логические таблицы.

    На листе спецификация, итоговая строка «Масса металла» и таблица
    «В том числе по маркам или наименованиям» нарисованы одной рамкой,
    но представляют разные сущности.
    """
    sections: list[tuple[str, list[LogicalRow]]] = []
    current: list[LogicalRow] = []
    kind = "spec_main"
    for row in rows:
        if row.kind == "section_header":
            if current:
                sections.append((kind, current))
            current, kind = [], "mass_by_grade"
            continue
        current.append(row)
    if current:
        sections.append((kind, current))
    return sections


def find_titles(text_lines, block_bbox, band: float = 34.0,
                read_strip=None) -> tuple[str, str]:
    """Заголовок таблицы и пометка «Начало»/«Окончание» — из полосы НАД рамкой.

    На тестовом листе заголовок лежит в текстовом слое, а пометка части
    («Начало», «Окончание») взорвана в векторы, поэтому дополнительно
    просматривается та же полоса через распознаватель глифов (`read_strip`).
    """
    x0, y0, x1, _ = block_bbox
    title, part = "", ""
    for tl in text_lines:
        bx0, by0, bx1, by1 = tl.bbox
        if by1 > y0 + 2 or by1 < y0 - band:
            continue
        if bx1 < x0 - 40 or bx0 > x1 + 40:
            continue
        if SPEC_TITLE_RE.search(tl.text):
            title = " ".join(tl.text.split())
        m = PART_RE.search(tl.text)
        if m:
            part = m.group(1).lower()
    if (not part or not title) and read_strip is not None:
        strip = read_strip((x0, max(0.0, y0 - band), x1, y0 - 1.0)) or ""
        if not title:
            mt = SPEC_TITLE_RE.search(strip)
            # берём именно найденную подстроку: иначе в заголовок попадала
            # пометка части («... металлопроката Окпнчвнив»)
            if mt:
                title = " ".join(mt.group(0).split())
        if not part:
            m = PART_RE.search(strip)
            part = m.group(1).lower() if m else _fuzzy_part(strip)
    return title, part


def column_key(col: Column) -> str:
    """Ключ колонки в логической строке.

    Колонки «по элементам конструкции» адресуются ИНДЕКСОМ, а не названием.
    Название берётся из шапки и может быть распознано с ошибкой; лист же
    разбит на «Начало» и «Окончание» с одинаковой сеткой, и общий итог
    считается по обеим частям. При ключе-названии одна опечатка в шапке
    («покрытия» -> «покрьы+и») ломала сведение колонок между частями.
    """
    if col.role == "element_mass":
        return "element:%d" % col.index
    return col.role if col.role != "unknown" else "col%d" % col.index


def normalize_grid(grid: dict[tuple[int, int], Cell], cols: list[Column],
                   header_rows: list[int]) -> None:
    """Нормализует значения ВСЕХ ячеек сетки по роли их колонки.

    Вызывается ДО `build_rows`: разбор merged-ячейки с несколькими номерами
    позиций опирается на уже разобранное `normalized_value`.
    """
    seen: set[int] = set()
    for (r, c), cell in grid.items():
        if id(cell) in seen or c >= len(cols):
            continue
        seen.add(id(cell))
        normalize_cell(cell, "text" if r in header_rows else cols[c].role)


def group_context(rows: list[LogicalRow]) -> None:
    """Протягивает значения merged-ячеек (группа профиля, марка стали) в строки.

    Геометрически merged-ячейка принадлежит только своей верхней строке.
    Для табличного вывода удобнее, чтобы у каждой строки была её группа,
    поэтому ссылка на ту же ячейку добавляется во все накрытые строки.
    """
    carry: dict[str, Cell] = {}
    for row in rows:
        for key in ("profile_group", "steel_grade", "profile_size"):
            cell = row.cells.get(key)
            if cell is not None and cell.row == row.row:
                carry[key] = cell
            elif cell is None and key in carry:
                c = carry[key]
                if c.row + c.row_span > row.row:
                    row.cells[key] = c


def standards_of(cell: Cell | None, bare: bool = False) -> tuple[str, list[str]]:
    """Разделяет ячейку вида 'С355-5 / ГОСТ 27772-2015' на марку и стандарты.

    `bare=True` — для наименования профиля: голый номер «30245-2003» тоже ГОСТ.
    """
    if cell is None or cell.is_empty:
        return "", []
    text = cell.text.replace("\n", " ")
    return strip_standards(text, bare), extract_standards(text, bare)
