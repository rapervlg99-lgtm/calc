# -*- coding: utf-8 -*-
"""Нормализация значений ячеек.

Принципы:
  * НИЧЕГО не додумывать. Если строка не разбирается как число — она остаётся
    строкой, `normalized_value = None`, а ячейка помечается на проверку.
  * Запятая — десятичный разделитель (`29,34` -> 29.34). Точка тоже
    принимается, но помечается как нетипичная для отечественных чертежей.
  * Пустая ячейка НИКОГДА не превращается в 0: `value_kind = "empty"`,
    `normalized_value = None`.
  * Обозначения профилей и марок стали не «исправляются» по словарю. Единственная
    правка — замена букв на цифры внутри числовых токенов (см. ниже), она
    детерминирована, обратима и всегда протоколируется в `notes`.
"""
from __future__ import annotations

import re

from .models import Cell

# Буквы, неотличимые по начертанию от цифр. Замена применяется ТОЛЬКО внутри
# токена, который и так является числовым (см. `_fix_digit_context`).
# Ради этого механизма из алфавита распознавания вынесены не все двойники:
# '3'/'З' различить по форме практически невозможно, что и подтвердилось на
# листе — 'ГОСТ 30245-2003' читалось как 'ГОСТ З0245-200З'.
# Буквы, НЕОТЛИЧИМЫЕ по начертанию от цифр. Список умышленно короткий.
# Раньше сюда входили 'В'->'8', 'Ч'->'4', 'Т'->'7', 'б'->'6' и другие, и на
# ведомости работ «Бетонирование фундаментов В25» превратилось в «825»: класс
# бетона был испорчен. Эти буквы от цифр отличимы, поэтому в карте оставлены
# только пары, которые в растре действительно не различить.
LETTER_TO_DIGIT = {
    "З": "3", "з": "3", "О": "0", "о": "0", "O": "0", "l": "1", "I": "1",
}

# В колонках, где кроме числа быть ничего не может (массы, площадь, № п.п.),
# буква — это всегда неверно прочитанная цифра. Здесь карта шире общей: «В»
# и «8» в текстовой колонке различимы (класс бетона В25), а в колонке масс
# «0,В2» — это только 0,82. Значение всё равно уходит на проверку.
NUMERIC_LETTER_TO_DIGIT = dict(LETTER_TO_DIGIT)
NUMERIC_LETTER_TO_DIGIT.update({
    "В": "8", "в": "8", "B": "8", "Ч": "4", "ч": "4", "б": "6", "Б": "6",
    "Т": "7", "T": "7", "|": "1", "S": "5", "s": "5", "g": "9", "q": "9",
    "D": "0", "d": "0",
})
_NUMERIC_TOKEN_RE = re.compile(
    r"^[+-]?[0-9%(L)]+(?:[.,][0-9%(L)]+)?$".replace(
        "(L)", re.escape("".join(NUMERIC_LETTER_TO_DIGIT))))


def _digits_only(text: str) -> tuple[str, bool]:
    """Для чисто числовой колонки: буквы-двойники -> цифры, если токен в
    остальном выглядит как число ('0,В2' -> '0,82'). Иначе текст не трогаем."""
    t = text.strip()
    if not t or not _NUMERIC_TOKEN_RE.match(t) or not any(c in NUMERIC_LETTER_TO_DIGIT for c in t):
        return text, False
    return "".join(NUMERIC_LETTER_TO_DIGIT.get(c, c) for c in t), True


# Правка применяется только к значениям, ПОЛУЧЕННЫМ РАСПОЗНАВАНИЕМ. Текст из
# текстового слоя PDF точен по построению, «исправлять» его нельзя.
RECOGNISED_SOURCES = {"vector_glyph", "ocr", "mixed"}

_NUM_RE = re.compile(r"^[+-]?\d+(?:[.,]\d+)?$")
# Пробел допускается ТОЛЬКО как разделитель тысяч (ровно по три цифры).
# Иначе '1 2' (лишний пробел от распознавателя) склеивалось бы в 12 —
# то есть выдумывалось бы значение, которого в документе нет.
_THOUSANDS_RE = re.compile(r"^[+-]?\d{1,3}(?:[\s\u00a0\u2009]\d{3})+(?:[.,]\d+)?$")
# RapidOCR читает десятичную запятую как пробел («23857,19» -> «23857 49»).
# Это не тысячи (после пробела 1–2 цифры) и не '1 2' (слева минимум две цифры).
_LOST_COMMA_RE = re.compile(r"^([+-]?\d{2,})[\s\u00a0\u2009]+(\d{1,2})$")
# OCR вставляет пробел ВНУТРИ дробной части («0.14 5», «2.4 05»). Разделитель
# уже есть, порядок цифр не меняется — склейка ничего не выдумывает, но ячейка
# всё равно идёт на проверку.
_SPLIT_DECIMAL_RE = re.compile(
    r"^([+-]?\d+[.,]\d*)[\s\u00a0\u2009]+(\d{1,3})$")
# Полноширинные цифры и знаки (U+FF10…) от RapidOCR: «５» вместо «5».
_FULLWIDTH = {0xFF10 + i: str(i) for i in range(10)}
_FULLWIDTH.update({0xFF0C: ",", 0xFF0E: ".", 0xFF0D: "-", 0xFF0B: "+"})
# «46.,9»: OCR ставит точку и запятую подряд — это один разделитель.
_DOUBLE_SEP_RE = re.compile(r"^([+-]?[0-9]+)[.,][.,]([0-9]+)$")
_INT_RE = re.compile(r"^\d{1,4}$")
_TOKEN_RE = re.compile(r"[^\s]+")
# «26Б1» на этом скане оба движка читают как «2651»/«2661». Букву не
# восстанавливаем (это уже словарь обозначений), но трёх- и четырёхзначное
# число без буквы в колонке размера — не нормальное обозначение, на проверку.
_BARE_PROFILE_DIGITS = re.compile(r"^\d{3,}$")

# Схематический значок сечения перед обозначением профиля («□ 140х5», «Ι 35К1»,
# «L 100х8», «[ 20П»). На чертеже он нарисован штрихами; OCR читает его как
# «口», «I», «|», «1», шаблоны глифов — как «I»/«L»/«?». В само обозначение он не
# входит (тип профиля известен из наименования группы), а прочитанный как «1»
# он склеивался с номером: «I35К1» -> «135К1». Поэтому значок снимается ДО
# остальных правок, а факт пишется в notes.
_GLYPH_SYMBOLS = "□口▢◻■⌶Ι∟⌐"       # настоящие символы (встречаются и в текстовом слое)
_GLYPH_OCR = "IІ|Ll[]Г"              # во что распознаватели превращают штрихи значка
_PROFILE_GLYPH_RE = re.compile(
    r"^\s*(?P<g>[%s%s]{1,2})\s*(?=[\dtTδ])" % (re.escape(_GLYPH_SYMBOLS), re.escape(_GLYPH_OCR)))
# В текстовом слое значок — либо настоящий символ, либо буква той же формы из
# чертёжного шрифта («L100х8», «Ι 35К1», «[20П»); «|» там не значок, а текст.
_PROFILE_GLYPH_TEXT_RE = re.compile(
    r"^\s*(?P<g>[%s]{1,2})\s*(?=[\dtTδ])" % re.escape(_GLYPH_SYMBOLS + "IІL["))
# «1 35К1» / «? 35К1»: значок прочитан как единица либо не прочитан вовсе.
# Только через пробел — «116» (t16) трогать нельзя.
_PROFILE_GLYPH_ONE_RE = re.compile(r"^\s*(?P<g>[1?])\s+(?=\d)")
# «+40» в колонке размеров — это толщина листа t40: у чертёжного «t» перекладина
# ровно посередине, и RapidOCR видит плюс.
_PLUS_THICKNESS_RE = re.compile(r"^\+\s*(\d+(?:[.,]\d+)?)$")


def strip_profile_glyph(text: str, recognised: bool) -> tuple[str, str]:
    """(текст без значка типа профиля, снятый значок или ''). Для текстового
    слоя снимаются только настоящие символы (□, ∟, ⌶): «|» и «I» там — текст."""
    out: list[str] = []
    removed = ""
    for line in text.split("\n"):
        m = _PROFILE_GLYPH_RE.match(line) if recognised else _PROFILE_GLYPH_TEXT_RE.match(line)
        if m is None and recognised:
            m = _PROFILE_GLYPH_ONE_RE.match(line)
        if m is not None:
            removed = removed or m.group("g")
            line = line[m.end():]
        out.append(line)
    return "\n".join(out), removed


# Значок типа профиля из текстового слоя, оказавшийся ПОСЛЕ обозначения:
# на file-45 «⌶ 25Б1» приходит как «25Б1 т», «∟ 25х3» — «25х3 □», «⊏ 8П» — «8П С»,
# «⌶ 45М» — «45М 7», а в другом окружении тот же значок — «1» («25Б1 1»).
# Хвост снимается, только если остаток — обозначение.
_TRAILING_GLYPH_RE = re.compile(r"^(?P<m>[\s\S]+?\S)\s+(?P<g>[тТLlСC71IΙ□口▢◻■⌶∟⌐D\[])$")
_DESIGNATION_RE = re.compile(
    r"^(?:\d{2,3}[БШКДМ]\d?|(?:Гн\.?\s?□?\s?)?\d{1,3}(?:[.,]\d)?[хx×]\d{1,3}(?:[хx×]\d{1,2}(?:[.,]\d)?)?"
    r"|\d{1,3}[Пп]а?|t\s?\d{1,3}(?:[хx×]\d{1,3})?|RD\d{1,3}|Ø\d{1,3}|\d{2,3}[Сс]\d?)$")


def strip_trailing_glyph(text: str) -> tuple[str, str]:
    """(обозначение без хвостового значка, снятый значок или '')."""
    m = _TRAILING_GLYPH_RE.fullmatch(text.strip())
    if m and _DESIGNATION_RE.fullmatch(m.group("m").strip()):
        return m.group("m").strip(), m.group("g")
    return text, ""


_SHEET_GROUP_RE = re.compile(r"лист", re.IGNORECASE)
_THICKNESS_MARK_RE = re.compile(r"^[tTδ]\s?\d{1,3}(?:[.,]\d)?$")
_BARE_NUMBER_RE = re.compile(r"^\d{1,3}(?:[.,]\d)?$")
MAX_SHEET_THICKNESS_MM = 60.0


def _thickness_from_bare(text: str) -> str | None:
    """«16» -> «16», «116» -> «16» (t прочитано как 1), «250» -> None."""
    t = text.strip()
    if not _BARE_NUMBER_RE.fullmatch(t):
        return None
    val = float(t.replace(",", "."))
    if 0 < val <= MAX_SHEET_THICKNESS_MM:
        return t.replace(".", ",")
    # «116» / «110»: первая единица — прочитанное как цифра «t»
    if len(t) == 3 and t[0] == "1" and t[1:].isdigit():
        rest = t[1:]
        if 0 < float(rest) <= MAX_SHEET_THICKNESS_MM:
            return rest
    return None


def fix_sheet_thickness(rows) -> int:
    """В группах листового проката обозначение — только толщина «t16». Чертёжное
    «t» RapidOCR читает как «1» или теряет: «116», «10», «14». Одинокое число в
    такой группе восстанавливаем как толщину (с пометкой на проверку).

    Группа считается листовой, если в её наименовании есть «лист» ЛИБО не меньше
    половины (и минимум двух) обозначений в ней — толщины «tNN»: наименование
    чертёжным курсивом OCR нередко читает в кашу («nроkаm 20рАНеКОmаНblU»).
    Возвращает число исправленных ячеек."""
    groups: dict[int, list] = {}
    order: list[int] = []
    for row in rows:
        if getattr(row, "kind", "") != "data":
            continue
        group = row.cells.get("profile_group")
        size = row.cells.get("profile_size")
        if group is None or size is None:
            continue
        key = id(group)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append((group, size))

    fixed = 0
    for key in order:
        items = groups[key]
        group = items[0][0]
        sizes = [s for _, s in items if (s.text or "").strip()]
        n_thick = sum(1 for s in sizes if _THICKNESS_MARK_RE.fullmatch(s.text.strip()))
        by_name = bool(_SHEET_GROUP_RE.search(group.text or ""))
        by_content = n_thick >= 2 and n_thick * 2 >= len(sizes)
        if not (by_name or by_content):
            continue
        seen: set[int] = set()
        for _, size in items:
            if id(size) in seen or size.source not in RECOGNISED_SOURCES:
                continue
            seen.add(id(size))
            raw = size.text
            bare = _SHEET_DASH_RE.sub("", (raw or "").strip())
            md = _DELTA_THICKNESS_RE.fullmatch(bare)
            if md and not _THICKNESS_MARK_RE.fullmatch(bare):
                # «5=4ММ» → t4: дельта прочитана цифрой, «мм» — заглавными
                size.text = "t" + md.group("v").replace(".", ",")
                size.normalized_value = size.text
                size.value_kind = "code"
                size.requires_review = True
                size.notes.append("толщина листа через «δ=»: дельта и «мм» прочитаны с ошибками; raw=%r" % raw)
                fixed += 1
                continue
            if _THICKNESS_MARK_RE.fullmatch(bare) and bare != raw.strip():
                # «—t16»: значок листа перед готовой толщиной — снимаем без пометки
                size.text = "t" + bare[1:].strip()
                size.normalized_value = size.text
                size.value_kind = "code"
                size.notes.append("снят значок листа «—» перед толщиной; raw=%r" % raw)
                fixed += 1
                continue
            thickness = _thickness_from_bare(bare)
            if thickness is None:
                continue
            size.text = "t" + thickness
            size.normalized_value = size.text
            size.value_kind = "code"
            if bare != raw.strip() and thickness == bare.replace(".", ","):
                # «—14»: значок листа и число целиком — толщина без догадок
                size.notes.append("значок листа «—» и число — толщина; raw=%r" % raw)
            else:
                size.requires_review = True
                size.notes.append("в группе листового проката одинокое число — толщина; raw=%r" % raw)
            fixed += 1
    return fixed


# Ширины полок уголков по ГОСТ 8509-93 (равнополочные) и ГОСТ 8510-86
# (неравнополочные, большая полка). Нужны, чтобы отличить «L», прочитанное
# RapidOCR как «1» («1140х90х8»), от настоящей единицы в размере («125х8»).
ANGLE_WIDTHS_MM = {20, 25, 28, 32, 36, 40, 45, 50, 56, 63, 70, 75, 80, 90, 100, 110,
                   120, 125, 130, 140, 150, 160, 180, 200, 220, 250}
_ANGLE_ONE_RE = re.compile(r"^[1lLΙ|](?P<w>\d{2,3})(?P<rest>[хx×]\d{1,3}(?:[хx×]\d{1,2})?(?:[.,]\d)?)$")
# Двутавр «30Б1»/«20Б1»: RapidOCR без кириллицы читает «Б» как «6» («3061»).
_IBEAM_SIX_RE = re.compile(r"^(?P<h>\d{2,3})6(?P<n>\d)$")
# «2011»: серия прочитана единицей — это и «20Б1», и «20Ш1»; решает второй движок.
_IBEAM_ONE_RE = re.compile(r"^(?P<h>\d{2,3})1(?P<n>\d)$")
# «301», «352»: буква серии выпала вовсе — кандидаты по всем сериям ГОСТ 26020.
_IBEAM_BARE_RE = re.compile(r"^(?P<h>\d{2,3})(?P<n>\d)$")
_IBEAM_SERIES = ("Б", "Ш", "К")
# Высоты двутавров (см) по ГОСТ 26020-83 / СТО АСЧМ 20-93 / ГОСТ Р 57837-2017.
# Нужны, чтобы «2051» разобрать как 20Б1 (серия «Б» прочитана пятёркой),
# а не как двутавр высотой 205 с потерянной буквой.
IBEAM_HEIGHTS_CM = {10, 12, 14, 16, 18, 20, 23, 25, 26, 30, 35, 40, 45, 50, 55, 60, 70, 80, 90, 100}
# «2051», «1651»: RapidOCR в чертёжном курсиве читает «Б» и как «5» (не только «6»).
_IBEAM_FIVE_RE = re.compile(r"^(?P<h>\d{2,3})5(?P<n>\d)$")
# Швеллер «22П»/«16П»: «П» прочитана как «7» («227», «167»). Высоты — ГОСТ 8240-97.
CHANNEL_HEIGHTS_CM = {5, 6.5, 8, 10, 12, 14, 16, 18, 20, 22, 24, 27, 30, 33, 36, 40}
_CHANNEL_SEVEN_RE = re.compile(r"^[?\[]?\s*(?P<h>\d{1,2})7$")
# Чтение швеллера вторым движком: «[16П», «?27n» — значок и буква серии.
_CHANNEL_ALT_RE = re.compile(r"^[?\[|IΙL]?\s*(?P<h>\d{1,2})\s*[ПпnNPp](?P<a>[аaУуYy]?)$")
# Швеллер без буквы серии («16», «24»): второй движок нередко видит букву
# («c16n», «[ 16nl», «|[2%П») — ищем «высота + П» в его чтении.
_CHANNEL_BARE_RE = re.compile(r"^\d{1,2}(?:[.,]5)?$")
_CHANNEL_ALT_ANY_RE = re.compile(r"(?<!\d)(?P<h>\d{1,2}(?:[.,]5)?)\s*[ПпnNPp](?P<a>[аaУуYy]?)")
# Значок двутавра прилип к марке без пробела: «I23Ш1» → «123Ш1». Высоты 123
# нет, 23 есть — единица лишняя.
_IBEAM_GLUED_ONE_RE = re.compile(r"^1(?P<h>\d{2})(?P<s>[БШКДМ])(?P<n>\d)$")
# Гнутый профиль «Гн.100х5»: «Г» теряется, «н» читается латинской «H». Только
# перед размером «сторона х толщина»: профнастил «Н75-750-0,8» в группе
# «…гнутые с трапецеидальными гофрами» — настоящая «Н» марки.
_BENT_PREFIX_RE = re.compile(r"^[HНhн]\.?\s*(?=\d{2,3}\s?[хx×]\s?\d)")
# Пробел внутри целого («4 72», «4 12.00»): одна цифра слева — не «потерянная
# запятая» (там слева минимум две). Склеиваем только с подтверждением второго движка.
_SPLIT_INT_RE = re.compile(r"^\d[\s\u00a0\u2009]+\d{2,}(?:[.,]\d+)?$")
_TRAILING_SEP_RE = re.compile(r"^([+-]?\d+)[.,]$")
# Толщина листа через дельту: «δ=4 мм» растровый OCR читает «5=4ММ», «d=6 мм», «6=8 НМ».
_DELTA_THICKNESS_RE = re.compile(r"^[δбдd5б6S0O]\s*[=:]\s*(?P<v>\d{1,3}(?:[.,]\d)?)\s*[мМmMнНhHxXхХnN]{0,2}\.?$")
# Гнутые замкнутые профили ГОСТ 30245 и трубы ГОСТ 8639/8645: ширина стороны.
TUBE_SIDES_MM = {40, 50, 60, 70, 80, 90, 100, 110, 120, 140, 150, 160, 180, 200, 250, 300, 350, 400}
# Значок «□» перед размером на растре низкого разрешения: «/20х5», «080х5», «060х5».
_TUBE_JUNK_RE = re.compile(r"^(?P<j>(?:[/\\|]+|0+|[DО口□▢]|0\s)\s*)(?=\d{2,3}[хx×]\d)")
_TUBE_SIZE_RE = re.compile(r"^(?P<a>\d{2,3})[хx×](?P<b>\d{1,2}(?:[.,]\d)?)$")
# Лист просечно-вытяжной «ПВ-506»: «П» уходит в латинскую N/H («NВ-506», «HB-506»).
_PV_SHEET_RE = re.compile(r"^[NНПnHh]?\s?[ВB]\s?[-–—]?\s?(?P<n>\d{3})$")
# Значок листа «—» перед толщиной («—t16», «—14», «—+20»): на чертеже это
# условное обозначение полосы/листа по ЕСКД, в само обозначение не входит.
_SHEET_DASH_RE = re.compile(r"^[-–—]\s*(?=\S)")
_SHEET_DASH_T_RE = re.compile(r"^[-–—]\s*(?=[tTδ+]\s?\d)")
# Скобка линовки перед наименованием группы: «[Прокат листовой». Только перед
# буквой: «[120х60х4» в графе размера — значок швеллера, его не трогаем.
_GROUP_LEADING_JUNK_RE = re.compile(r"^[\[\]|]\s*(?=[А-Яа-яЁёA-Za-z])", re.M)
# Строка-артефакт из одной буквы под маркой стали («5245⏎ГОСТ 27772-88⏎э»).
_JUNK_LINE_RE = re.compile(r"^[а-яёa-z]$")
# Углеродистая сталь «Ст20», «Ст3сп5»: чертёжное «т» OCR читает латинской «m».
_STEEL_ST_RE = re.compile(r"^[СC][mt](?=\d)")
_IBEAM_ALT_RE = re.compile(r"(?P<h>\d{2,3})\s*(?P<s>[БШКДМBWKDM])\s*(?P<n>\d)")
_SERIES_LATIN = str.maketrans("BWKDM", "БШКДМ")
# Лишний знак между серией и номером из шаблонов глифов: «20Кз1» (з → 3 после
# правки цифр: «20К31»), «Ш35Кх1». Номер после серии всегда одна цифра.
_IBEAM_EXTRA_RE = re.compile(r"^(?P<pre>[ТTШIΙ|]?\+?\s*\d{2,3}[БШКДМ])[а-яa-z38](?P<n>\d)$")
# Швеллер «[30П», где значок «[» стал «?», а «3» — «++».
_CHANNEL_PLUS_RE = re.compile(r"^[?\[]?\s*\+\+(?P<d>\d)\s*[ПпnNP]$")
# Крановый рельс «КР70» с лишней буквой из глифов: «КхР70».
_RAIL_RE = re.compile(r"^К[хx]?Р\s?(?P<n>\d{2,3})$")
# Размер трубы в наименовании группы («Труба квадратная 120х120х6. ГОСТ 8639-82»).
_TUBE_IN_GROUP_RE = re.compile(r"(?<!\d)(\d{2,3})\s*[хx×]\s*(\d{2,3})\s*[хx×]\s*(\d{1,2}(?:[.,]\d)?)(?![\dх×x])")
# Значок двутавра перед маркой прочитан буквой: «Т+30Ш2», «Ш35Ш1», «I 25Ш2».
_IBEAM_GLYPH_RE = re.compile(r"^[ТTШIΙ|]\+?\s*(?=\d{2,3}[БШКДМ]\d)")
# Швеллер «27П»: буква серии латиницей/строчной («27n», «27п»), значок «[» как «?».
_CHANNEL_RE = re.compile(r"^\??\s*(?P<h>\d{2,3}(?:[.,]\d)?)\s*(?P<s>[ПпnNPp])(?P<a>[аaУуYy]?)$")
# Битый глиф «3» в текстовом слое чертёжного шрифта: «+э5Ш1», «t+э0», «100х6+эх8».
_BROKEN_THREE_RE = re.compile(r"[+?][эз]")

# Марки стали по ГОСТ 27772: трёхзначный номер и необязательный индекс
# («С255», «С345-6», «С355Б»). OCR читает «С» как «(», «6» или «[», «Б» как «6».
STEEL_GRADES = {"235", "245", "255", "275", "285", "345", "355", "375", "390", "440", "550", "590"}
_GRADE_TOKEN_RE = re.compile(
    r"^(?P<pre>[\(\[\{€56бБCcСс]?)\s?(?P<num>[2-5]\d\d)(?P<suf>[6бБ]|[-–]\s?\d)?(?P<tail>[,;.:]?)$")


def fix_steel_grade(text: str) -> str:
    """«6255» -> «С255», «5245» -> «С245», «(3556» -> «С355Б», «(245-4» -> «С245-4» —
    только для известных номеров марок; остальное не трогается."""
    parts = text.replace("\n", " ").split(" ", 1)
    if not parts or not parts[0]:
        return text
    m = _GRADE_TOKEN_RE.fullmatch(parts[0])
    if not m or m.group("num") not in STEEL_GRADES:
        return text
    suf = m.group("suf") or ""
    if suf in ("6", "б", "Б"):
        suf = "Б"
    elif suf:
        suf = "-" + suf[-1]
    canon = "С" + m.group("num") + suf + (m.group("tail") or "")
    if canon == parts[0]:
        return text
    return canon + ((" " + parts[1]) if len(parts) > 1 else "")


def _group_folded(group_cell) -> str:
    from .structure import drawing_fold
    return drawing_fold(group_cell.text or "").lower()


def fix_profile_series(rows) -> int:
    """Правки обозначений по виду группы профиля (RapidOCR без кириллицы).

    * двутавры: «3061» -> «30Б1», «2061» -> «20Б1» — буква серии «Б» прочитана
      как «6» (а «Ш» как «W» уже сворачивается двойниками);
    * уголки: «1140х90х8» -> «140х90х8», «163х5» -> «63х5» — значок «L» перед
      размером прочитан как единица. Снимается только если получившаяся полка
      есть в сортаменте, а с единицей — нет («125х8» не трогаем).
    Возвращает число исправленных ячеек; каждая помечается на проверку.
    """
    fixed = 0
    seen: set[int] = set()
    for row in rows:
        if getattr(row, "kind", "") != "data":
            continue
        group = row.cells.get("profile_group")
        size = row.cells.get("profile_size")
        if group is None or size is None or id(size) in seen:
            continue
        seen.add(id(size))
        if not (size.text or "").strip():
            # размер трубы указан в наименовании группы, а графа пуста
            gf = _group_folded(group)
            m = _TUBE_IN_GROUP_RE.search(group.text or "")
            if m and "труб" in gf and not (row.cells.get("profile_size") is None):
                size.text = "%sх%sх%s" % m.groups()
                size.normalized_value = size.text
                size.value_kind = "code"
                size.requires_review = True
                size.notes.append("размер взят из наименования группы; raw=%r" % (group.text or ""))
                fixed += 1
            continue
        # битый глиф «3» текстового слоя — независимо от источника
        if _BROKEN_THREE_RE.search(size.text):
            raw3 = size.text
            size.text = _BROKEN_THREE_RE.sub("3", size.text)
            size.normalized_value = " ".join(size.text.split())
            size.notes.append("глиф «3» пришёл как «+э»; raw=%r" % raw3)
            size.requires_review = True
            fixed += 1
        folded = _group_folded(group)
        text = size.text.strip()
        # значок двутавра буквой встречается и в текстовом слое («Т+30Ш2» на
        # file-37 — битый шрифт), поэтому проверяется до фильтра по источнику
        if "двутавр" in folded and _IBEAM_EXTRA_RE.fullmatch(text):
            # «Т20Кз1» / «Ш35Кх1»: между серией и номером лишний знак из шаблонов глифов
            raw_x = size.text
            mx = _IBEAM_EXTRA_RE.fullmatch(text)
            size.text = mx.group("pre") + mx.group("n")
            size.normalized_value = " ".join(size.text.split())
            size.notes.append("лишний знак между серией и номером двутавра; raw=%r" % raw_x)
            size.requires_review = True
            fixed += 1
            text = size.text.strip()
        if "двутавр" in folded and _IBEAM_GLYPH_RE.match(text):
            raw_g = size.text
            size.text = _IBEAM_GLYPH_RE.sub("", text)
            size.normalized_value = " ".join(size.text.split())
            size.notes.append("значок двутавра прочитан буквой; raw=%r" % raw_g)
            size.requires_review = True
            fixed += 1
            text = size.text.strip()
        if size.source not in RECOGNISED_SOURCES:
            continue
        new = None
        if "двутавр" in folded and _IBEAM_GLUED_ONE_RE.fullmatch(text):
            mg = _IBEAM_GLUED_ONE_RE.fullmatch(text)
            if int(mg.group("h")) in IBEAM_HEIGHTS_CM and int("1" + mg.group("h")) not in IBEAM_HEIGHTS_CM:
                new = mg.group("h") + mg.group("s") + mg.group("n")
                why = "значок двутавра прилип к марке единицей"
        elif "двутавр" in folded:
            m = _IBEAM_SIX_RE.fullmatch(text)
            m5 = _IBEAM_FIVE_RE.fullmatch(text)
            m1 = _IBEAM_ONE_RE.fullmatch(text)
            alt = _IBEAM_ALT_RE.search(size.alt_text or "") if _BARE_PROFILE_DIGITS.fullmatch(text) else None
            if (alt and text.startswith(alt.group("h")) and text.endswith(alt.group("n"))
                    and len(text) - len(alt.group("h")) - len(alt.group("n")) <= 1):
                # второй движок видел букву серии — верим ему («I20Ш1» → 20Ш1,
                # «Т20Б1» при «2051» → 20Б1); между высотой и номером не больше
                # одного знака (цифра вместо буквы или ничего)
                new = alt.group("h") + alt.group("s").translate(_SERIES_LATIN) + alt.group("n")
                why = "серия двутавра взята из чтения вторым движком (%r)" % size.alt_text
            elif m:
                new = m.group("h") + "Б" + m.group("n")
                why = "серия двутавра «Б» прочитана цифрой"
            elif (m5 and int(m5.group("h")) in IBEAM_HEIGHTS_CM
                    and int(m5.group("h") + "5") not in IBEAM_HEIGHTS_CM):
                # «2051» → 20Б1: высота 20 есть в сортаменте, 205 — нет
                new = m5.group("h") + "Б" + m5.group("n")
                why = "серия двутавра «Б» прочитана цифрой «5»"
            elif m1:
                size.requires_review = True
                size.candidates = [m1.group("h") + s + m1.group("n") for s in _IBEAM_SERIES]
                size.notes.append("серия двутавра не распознана (цифра вместо буквы): возможны "
                                  "%sБ%s / %sШ%s" % (m1.group("h"), m1.group("n"), m1.group("h"), m1.group("n")))
            elif _BARE_PROFILE_DIGITS.fullmatch(text) and _IBEAM_BARE_RE.fullmatch(text):
                # буква серии выпала целиком: сами не выбираем, отдаём варианты
                mb = _IBEAM_BARE_RE.fullmatch(text)
                size.requires_review = True
                size.candidates = [mb.group("h") + s + mb.group("n") for s in _IBEAM_SERIES]
                size.notes.append("серия двутавра не прочиталась: возможны " + " / ".join(size.candidates))
        elif "швеллер" in folded:
            m = _CHANNEL_RE.fullmatch(text)
            mp = _CHANNEL_PLUS_RE.fullmatch(text)
            m7 = _CHANNEL_SEVEN_RE.fullmatch(text)
            alt7 = _CHANNEL_ALT_RE.fullmatch((size.alt_text or "").strip()) if m7 else None
            if m:
                new = m.group("h") + "П" + ("а" if m.group("a") else "")
                why = "серия швеллера «П» прочитана латиницей/значок «[» как «?»"
            elif mp:
                new = "3" + mp.group("d") + "П"
                why = "глиф «3» пришёл как «++», значок «[» — как «?»"
            elif m7 and alt7 and alt7.group("h") == m7.group("h"):
                # «167» при «[16П» у второго движка → 16П
                new = m7.group("h") + "П" + ("а" if alt7.group("a") else "")
                why = "серия швеллера «П» прочитана цифрой «7», буква взята из чтения вторым движком (%r)" % size.alt_text
            elif m7 and float(m7.group("h")) in CHANNEL_HEIGHTS_CM:
                # «227» → 22П: высота 22 есть в ГОСТ 8240, швеллера «227» не бывает
                new = m7.group("h") + "П"
                why = "серия швеллера «П» прочитана цифрой «7»"
            elif _CHANNEL_BARE_RE.fullmatch(text):
                # «16» при «c16n» / «[ 16nl» у второго движка → 16П; без
                # подтверждения голое число остаётся — это допустимое обозначение
                for am in _CHANNEL_ALT_ANY_RE.finditer(size.alt_text or ""):
                    if am.group("h").replace(",", ".") == text.replace(",", "."):
                        new = text + "П" + ("а" if am.group("a") else "")
                        why = "буква серии швеллера взята из чтения вторым движком (%r)" % size.alt_text
                        break
        elif ("гнут" in folded or "замкнут" in folded
              or ("труб" in folded and ("квадрат" in folded or "прямоуг" in folded))):
            mj = _TUBE_JUNK_RE.match(text)
            if _BENT_PREFIX_RE.match(text):
                # «H.100x5» → «Гн.100х5»: калькулятор знает префикс гнутого профиля
                new = _BENT_PREFIX_RE.sub("Гн.", text)
                why = "префикс гнутого профиля «Гн.» прочитан латиницей"
            elif mj and mj.group("j").strip() in ("D", "口", "□", "▢", "О"):
                # «D40х40х4»: значок «□» пришёл латинской D — снимаем без пометки,
                # это однозначный двойник (калькулятор тоже его снимает)
                size.notes.append("снят значок «□» перед размером, прочитанный как %r; raw=%r" % (mj.group("j"), size.text))
                size.text = text[mj.end():]
                size.normalized_value = size.text
                text = size.text
            elif mj:
                # «/20х5», «080х5»: значок «□» на растре стал чертой или нулём
                new = text[mj.end():]
                why = "значок «□» перед размером прочитан как %r" % mj.group("j")
            ms = _TUBE_SIZE_RE.fullmatch((new or text).replace("Гн.", ""))
            if ms and int(ms.group("a")) not in TUBE_SIDES_MM:
                # «700х5», «20х5» — такой стороны в сортаменте нет: значок «□» слился с цифрами
                size.requires_review = True
                size.notes.append("сторона %s мм не встречается в ГОСТ 30245/8639 — возможно, значок «□» "
                                  "слился с размером" % ms.group("a"))
        elif "лист" in folded or "просечн" in folded:
            mv = _PV_SHEET_RE.fullmatch(text)
            if mv and text != "ПВ-" + mv.group("n"):
                # «NВ-506» / «HB-506»: просечно-вытяжной лист, «П» прочитана латиницей
                new = "ПВ-" + mv.group("n")
                why = "просечно-вытяжной лист «ПВ»: буква «П» прочитана латиницей"
        elif "рельс" in folded:
            m = _RAIL_RE.fullmatch(text)
            if m and text != "КР" + m.group("n"):
                new = "КР" + m.group("n")
                why = "лишняя буква в марке рельса"
        elif "уголк" in folded or "угольник" in folded:
            m = _ANGLE_ONE_RE.fullmatch(text)
            parts = re.split(r"[хx×]", text)
            equal_flanges = len(parts) == 3 and parts[0] == parts[1]
            if m and not equal_flanges:
                w = int(m.group("w"))
                with_one = int(text[0] + m.group("w")) if text[0] == "1" else None
                if w in ANGLE_WIDTHS_MM and with_one not in ANGLE_WIDTHS_MM:
                    new = m.group("w") + m.group("rest")
                    why = "значок уголка «L» прочитан как «1»"
        if new is None or new == text:
            continue
        size.notes.append("%s; raw=%r" % (why, size.text))
        size.text = new
        size.normalized_value = new
        size.value_kind = "code"
        size.requires_review = True
        fixed += 1
    return fixed


# Спецификация металлопроката на 2000 т и больше — редкость; итог такого порядка
# при спорной единице в шапке означает килограммы.
KG_THRESHOLD = 2000.0


def resolve_mass_unit(grid, cols, header_rows) -> str:
    """Снимает «кг?» (подписи шапки противоречат друг другу) по порядку чисел в
    колонке общей массы: максимум ≥ KG_THRESHOLD — килограммы. Возвращает
    итоговую единицу колонок масс."""
    mass_cols = [c for c in cols if c.role in ("element_mass", "total_mass")]
    if not any(c.unit == "кг?" for c in mass_cols):
        return next((c.unit for c in mass_cols), "т") or "т"
    total_idx = {c.index for c in cols if c.role == "total_mass"} or {c.index for c in mass_cols}
    biggest = 0.0
    for (r, c), cell in grid.items():
        if r in header_rows or c not in total_idx:
            continue
        if isinstance(cell.normalized_value, (int, float)) and cell.value_kind == "number":
            biggest = max(biggest, float(cell.normalized_value))
    unit = "кг" if biggest >= KG_THRESHOLD else "т"
    for c in mass_cols:
        c.unit = unit
    return unit


def apply_mass_unit(grid, cols, header_rows) -> int:
    """Массы, подписанные в шапке килограммами, переводятся в тонны: числовое
    значение делится на 1000, текст ячейки остаётся как на чертеже. Возвращает
    число переведённых ячеек."""
    kg_cols = {c.index for c in cols if c.role in ("element_mass", "total_mass") and c.unit == "кг"}
    if not kg_cols:
        return 0
    done = 0
    seen: set[int] = set()
    for (r, c), cell in grid.items():
        if r in header_rows or c not in kg_cols or id(cell) in seen:
            continue
        seen.add(id(cell))
        if isinstance(cell.normalized_value, (int, float)) and cell.value_kind == "number":
            cell.normalized_value = round(cell.normalized_value / 1000.0, 6)
            cell.notes.append("масса в шапке подписана в кг — переведена в т")
            done += 1
    return done


def fill_positions(rows) -> int:
    """Восстанавливает номера позиций, прочитанные кашей («m», «(-», «О Ж ?Д Ё»).

    В спецификации номера идут подряд; если у строки данных номера нет, а у
    соседних он есть и разница между ними ровно 2, пропущенный — среднее.
    Ячейка помечается на проверку. Возвращает число восстановленных."""
    data = [r for r in rows if getattr(r, "kind", "") in ("data", "group_total", "profile_total")]
    fixed = 0
    i = 0
    while i < len(data):
        if isinstance(data[i].position, int) or data[i].cells.get("position") is None:
            i += 1
            continue
        # серия подряд идущих строк без номера
        j = i
        while j < len(data) and not isinstance(data[j].position, int) and data[j].cells.get("position") is not None:
            j += 1
        prev = data[i - 1].position if i > 0 else None
        nxt = data[j].position if j < len(data) else None
        if isinstance(prev, int) and isinstance(nxt, int) and nxt - prev == (j - i) + 1:
            for k in range(i, j):
                pos = prev + (k - i) + 1
                cell = data[k].cells["position"]
                cell.notes.append("номер позиции восстановлен по соседним; raw=%r" % cell.text)
                cell.text = str(pos)
                cell.normalized_value = pos
                cell.value_kind = "int"
                cell.requires_review = True
                data[k].position = pos
                fixed += 1
        i = j
    return fixed


# Признаки строк-итогов и служебных строк спецификации
ROW_MARKERS = {
    "итого": "group_total",
    "итог": "group_total",                         # OCR: «Итог:» без последней буквы
    "всего металла": "grand_total",
    "всего профиля": "profile_total",
    "всего масса металла": "grand_total",
    "масса металла": "grand_total",
    "в том числе по маркам или наименованиям": "section_header",
    "в том числе по марк": "section_header",     # OCR: «В том числе nо марком:»
    "в том числе по наимен": "section_header",
}

# Мусор, который растровый OCR приписывает слева от слова: обрывок соседней
# линовки читается как '|', '"', ''' («Итого:» -> «|Итого:»). Для
# СОПОСТАВЛЕНИЯ с маркером он отбрасывается; с краёв OCR-текста тот же мусор
# снимается отдельно (см. `_strip_ruling_junk`), чтобы в выгрузке не торчал '|'.
_LEAD_JUNK = re.compile(r"^[^0-9A-Za-zА-Яа-яЁё]+")
# '[' не входит: это обозначение швеллера. '-' не входит: толщина листа («-12»).
_RULING_CHARS = "|\"'`"

# Латинские двойники кириллицы. RapidOCR не знает кириллицы и подставляет их
# в русских словах («В том числе» -> «B том числе», «Итого» -> «Mтого»), из-за
# чего строка-итог считалась обычной строкой данных и попадала в суммы дважды.
# Свёртка применяется ТОЛЬКО при сопоставлении с маркерами.
_HOMOGLYPHS = str.maketrans({
    "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М",
    "O": "О", "P": "Р", "T": "Т", "X": "Х", "Y": "У",
    # серия широкополочных двутавров: «35W2» — это 35Ш2, латинской W в марках нет
    "W": "Ш",
    "a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у",
})


def _fix_digit_context(text: str) -> tuple[str, bool]:
    """Внутри числовых токенов заменяет буквы-двойники на цифры.

    Правило применяется к токену, только если он уже содержит цифры, а сама
    буква стоит рядом с цифрой. Так 'СЗ45-5' -> 'С345-5' и '6З' -> '63',
    но 'ГОСТ', '16П', '35К1', 't8' остаются нетронутыми.
    """
    changed = False
    out_tokens: list[str] = []
    pos = 0
    for m in _TOKEN_RE.finditer(text):
        out_tokens.append(text[pos:m.start()])
        tok = m.group(0)
        pos = m.end()
        if not any(c.isdigit() for c in tok):
            out_tokens.append(tok)
            continue
        chars = list(tok)
        for i, c in enumerate(chars):
            if c not in LETTER_TO_DIGIT:
                continue
            prev_d = i > 0 and chars[i - 1].isdigit()
            next_d = i + 1 < len(chars) and chars[i + 1].isdigit()
            if prev_d or next_d:
                chars[i] = LETTER_TO_DIGIT[c]
                changed = True
        out_tokens.append("".join(chars))
    out_tokens.append(text[pos:])
    return "".join(out_tokens), changed


# Марка двутавра «25Ш0»/«20Ш0»/«30Ш0» (ГОСТ Р 57837-2017): OCR читает нуль
# после буквы серии как букву «О» — «25ШО», «I25WO». Нуль в этой позиции
# бывает только цифрой: серия — одна буква, дальше идёт номер.
_SERIES_O_RE = re.compile(r"^(\d{2,3})([БШКДМ])([0-9ОоOo]{1,2})$")


def fix_series_zero(text: str) -> str:
    m = _SERIES_O_RE.match(text.strip())
    if not m or not re.search(r"[ОоOo]", m.group(3)):
        return text
    return m.group(1) + m.group(2) + re.sub(r"[ОоOo]", "0", m.group(3))


def canonical_size(text: str) -> str:
    """Приводит разделитель размеров к кириллическому 'х'.

    Латинская 'x', кириллическая 'х', '*' и '×' в растре неотличимы либо
    взаимозаменяемы. Единая форма делает вывод воспроизводимым.
    """
    # «140×x10»: OCR иногда даёт два знака умножения подряд — схлопываем в один
    return re.sub(r"(?<=\d)\s*[x×*х]+\s*(?=\d)", "х", text)


def parse_number(text: str) -> float | None:
    """'29,34' -> 29.34. None, если это не одиночное число.

    Внутренние пробелы НЕ убираются молча: '1 2' — это не 12, а признак
    того, что распознаватель вставил лишний пробел. Такая ячейка уходит на
    проверку; иначе мы выдумали бы значение, которого в документе нет.
    Пробел принимается только как разделитель тысяч (ровно по три цифры).
    """
    t = text.strip()
    if not t:
        return None
    if _THOUSANDS_RE.match(t):
        t = re.sub(r"[\s\u00a0\u2009]", "", t)
    if not _NUM_RE.match(t):
        return None
    try:
        return float(t.replace(",", "."))
    except ValueError:
        return None


_ITOGO_RE = re.compile(r"^[a-zа-я|]?[mт][оос0][2zг][0оo][:.,;]*$")


def row_marker(text: str) -> str | None:
    """Тип служебной строки по тексту ячейки ('Итого', 'Всего профиля', ...).

    Сопоставление ведётся по «очищенному» ключу: без мусора слева и со
    свёрнутыми латинскими двойниками. Иначе на листе-скане «|Итого:» и
    «B том числе по маркам» остаются строками данных, их значения попадают в
    суммы, и проверка арифметики краснеет на верных числах.
    """
    from difflib import SequenceMatcher
    from .structure import drawing_fold
    for variant in (text, drawing_fold(text)):
        key = variant.translate(_HOMOGLYPHS).lower()
        key = " ".join(_LEAD_JUNK.sub("", key).split())
        for marker, kind in ROW_MARKERS.items():
            if key.startswith(marker):
                return kind
    # «Итого:» чертёжным курсивом гибрид читает как «Vmс20:», «Мm020:», «Мmсz0:»:
    # пять знаков, где вторым всегда «m/т», а дальше о/с/0, 2/z/г, 0/о.
    compact0 = "".join(text.lower().split())
    if _ITOGO_RE.fullmatch(compact0):
        return "group_total"
    # Нечётко — по свёрнутому чертёжному курсиву: «Все20mассаМеmа//nа» -> «всего
    # масса металла» с двумя ошибками. Сравнивается только начало строки длиной
    # с маркер, без пробелов; маркеры короче 5 символов нечётко не ищем.
    folded = drawing_fold(text).translate(_HOMOGLYPHS).lower()
    compact = "".join(_LEAD_JUNK.sub("", folded).split())
    if len(compact) >= 5:
        for marker, kind in ROW_MARKERS.items():
            mk = marker.replace(" ", "")
            if len(mk) < 5:
                continue
            head = compact[:len(mk)]
            if len(head) >= len(mk) - 1 and SequenceMatcher(None, head, mk).ratio() >= 0.8:
                return kind
    return None


def _strip_ruling_junk(text: str) -> tuple[str, bool]:
    """Снимает с краёв строк символы, которыми OCR рисует линовку таблицы.

    Содержимое не переписывается: '|2651' -> '2651', '[120х60х4' остаётся
    со скобкой. Применяется только к распознанному тексту, не к текстовому слою.
    """
    changed = False
    out: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip().strip(_RULING_CHARS).strip()
        if stripped != line.strip():
            changed = True
        out.append(stripped)
    return "\n".join(out), changed


# Служебная строка, прочитанная чертёжным курсивом в кашу («Мm020:», «Вге20
# прафиия:», «Всеzо mеmаnnа»), после опознания получает нормальную подпись.
# Подпись строки — не значение, а её вид; смысл строки (итог группы, итог
# профиля, общая масса) уже определён `row_marker`.
_MARKER_LABELS = {
    "group_total": "Итого",
    "profile_total": "Всего профиля",
}
_GARBLED_RE = re.compile(r"[A-Za-z0-9]")
# Кавычки, обрывки линовки и прочий мусор по краям служебной подписи.
_EDGE_JUNK_RE = re.compile(r"^[^0-9A-Za-zА-Яа-яЁё]+|[^0-9A-Za-zА-Яа-яЁё:]+$")


def _marker_label(kind: str, text: str) -> str | None:
    if kind in _MARKER_LABELS:
        return _MARKER_LABELS[kind]
    from .structure import drawing_fold
    folded = " ".join(drawing_fold(text).lower().split())
    if kind == "grand_total":
        if "масс" in folded:
            return "Всего масса металла" if folded.startswith("все") else "Масса металла"
        return "Всего металла"
    if kind == "section_header":
        # Свёртка курсива не восстанавливает слово точно («В mоm числе» ->
        # «В тот числе»), поэтому подпись выбирается по смыслу.
        has_grade = "марк" in folded
        has_name = "наимен" in folded
        if has_grade and has_name:
            return "В том числе по маркам или наименованиям"
        if has_name:
            return "В том числе по наименованиям"
        return "В том числе по маркам стали"
    return None


def canon_service_row(cell: Cell) -> bool:
    """Подменяет кашу OCR в служебной строке на её подпись. True, если менял.

    «Мm020:» -> «Итого:», «Вге20 профиия:» -> «Всего профиля:», «„Итого“» ->
    «Итого». Точная подпись (с двоеточием или без) не трогается.
    """
    kind = row_marker(cell.text)
    if not kind:
        return False
    raw = cell.text.strip()
    label = _marker_label(kind, raw)
    if not label:
        return False
    if raw in (label, label + ":"):
        return False
    body = _EDGE_JUNK_RE.sub("", raw)
    tail = ":" if body.endswith(":") else ""
    core = body.rstrip(":;.,").strip()
    if core.lower() == label.lower():
        note = "снят мусор по краям служебной подписи; raw=%r"
    else:
        note = "служебная строка приведена к подписи; raw=%r"
    new = label + tail
    if new == raw:
        return False
    cell.notes.append(note % cell.text)
    cell.text = new
    return True


# Марка стали: OCR читает «С» чертёжного курсива как скобку — «(245-4», «[255».
_PAREN_GRADE_RE = re.compile(r"(?<![\wА-Яа-яЁё])[\(\[\{]\s?(?=[2-4]\d\d(?:[-–]\d)?(?![\dх×x]))")
# Мусор линовки/скобка перед словом стандарта: «[ОСТ», «(ГОСТ», «|ГОСТ».
_STD_JUNK_RE = re.compile(r"(?<!\S)[\[\(\|]\s?(?=(?:ГОСТ|ТУ|СТО)\b)")


def canon_grades_and_standards(text: str) -> str:
    """«(245-4 [ОСТ 27772-2021» -> «С245-4 ГОСТ 27772-2021».

    Скобка перед трёхзначным числом марки становится «С»; упоминания
    стандартов приводятся к каноническому виду (`_canon_standard`), мусор
    перед ними снимается. Номера и годы не трогаются.
    """
    t = _PAREN_GRADE_RE.sub("С", text)
    t = GOST_RE.sub(_canon_standard, t)
    t = _STD_JUNK_RE.sub("", t)
    return t


def _fold_homoglyphs(text: str) -> tuple[str, bool]:
    """Латинские двойники кириллицы -> кириллица ('C255' -> 'С255', 'Tp' -> 'Тр').

    Не выдумывает символы: это те же начертания в другом алфавите. 'L' и 't'
    в карте нет — уголок и толщина листа остаются латиницей.
    """
    folded = text.translate(_HOMOGLYPHS)
    return folded, folded != text


# Стандарт сортамента однозначно задаёт вид профиля, а его номер — цифры,
# которые OCR читает надёжнее слов. Если словарное имя расходится со
# стандартом («Трубы квадратные» при ГОСТ 10704 — трубы электросварные
# круглые; «равнополочные» при ГОСТ 8510 — неравнополочные), верим номеру.
# Значение: (каноническое имя; подстроки, хотя бы одна из которых есть в
# согласном имени; регулярные выражения слов, которые стандарту ПРОТИВОРЕЧАТ).
# Имя без нужных слов, но и без противоречащих («Прокат горячекатаный» при
# ГОСТ 19903) — просто менее точное: уточняется без пометки на проверку.
# Противоречие («Трубы квадратные» при ГОСТ 10704) — замена с пометкой.
_TUBE_SHAPES = (r"квадратн", r"прямоугольн", r"гнут", r"замкнут")
_STD_GROUP_HINT = {
    "ГОСТ 8509": ("Уголки стальные горячекатаные равнополочные", ("равнополочн",), (r"неравнополочн",)),
    "ГОСТ 8510": ("Уголки стальные горячекатаные неравнополочные", ("неравнополочн",), (r"(?<!не)равнополочн",)),
    "ГОСТ 8240": ("Швеллеры стальные горячекатаные", ("швеллер",), (r"двутавр", r"уголк", r"труб", r"лист")),
    "ГОСТ 8239": ("Двутавры стальные горячекатаные", ("двутавр",), (r"швеллер", r"уголк", r"труб", r"лист")),
    "ГОСТ 26020": ("Двутавры стальные горячекатаные с параллельными гранями полок", ("двутавр",),
                   (r"швеллер", r"уголк", r"труб", r"лист")),
    "ГОСТ 57837": ("Двутавры стальные горячекатаные с параллельными гранями полок", ("двутавр",),
                   (r"швеллер", r"уголк", r"труб", r"лист")),
    "ГОСТ 10704": ("Трубы стальные электросварные прямошовные", ("электросварн",), _TUBE_SHAPES + (r"бесшовн",)),
    "ГОСТ 10705": ("Трубы стальные электросварные прямошовные", ("электросварн",), _TUBE_SHAPES + (r"бесшовн",)),
    "ГОСТ 8732": ("Трубы стальные бесшовные горячедеформированные", ("бесшовн",), _TUBE_SHAPES + (r"электросварн",)),
    "ГОСТ 8731": ("Трубы стальные бесшовные горячедеформированные", ("бесшовн",), _TUBE_SHAPES + (r"электросварн",)),
    "ГОСТ 8639": ("Трубы стальные квадратные", ("квадратн",), (r"прямоугольн", r"электросварн", r"бесшовн")),
    "ГОСТ 8645": ("Трубы стальные прямоугольные", ("прямоугольн",), (r"квадратн", r"электросварн", r"бесшовн")),
    "ГОСТ 30245": ("Профили стальные гнутые замкнутые сварные квадратные и прямоугольные для строительных конструкций",
                   ("квадратн", "прямоугольн", "гнут", "замкнут"), (r"электросварн", r"бесшовн", r"уголк", r"швеллер")),
    "ГОСТ 19903": ("Прокат листовой горячекатаный", ("лист",), (r"холоднокатан", r"просечно", r"гнут", r"профил")),
    "ГОСТ 19904": ("Прокат листовой холоднокатаный", ("лист",), (r"горячекатан", r"просечно", r"гнут", r"профил")),
    "ТУ 36.26.11": ("Листы стальные просечно-вытяжные", ("просечно",), (r"прокат", r"гнут", r"профил")),
}


def _std_key(std: str) -> str:
    """«ГОСТ 10704-91» → «ГОСТ 10704», «ГОСТ Р 57837-2017» → «ГОСТ 57837»,
    «ТУ 36.26.11-5-89» → «ТУ 36.26.11»."""
    parts = std.split()
    if len(parts) < 2:
        return ""
    kind, num = parts[0], parts[-1]
    if kind == "ТУ":
        return "ТУ " + num.split("-")[0]
    m = re.match(r"\d+", num)
    return (kind + " " + m.group(0)) if m else ""


def group_by_standard(stds: list[str]) -> tuple[str, tuple[str, ...], tuple[str, ...]] | None:
    """Подсказка по стандартам ячейки; None, если стандартов нет, они неизвестны
    или указывают на разные виды профиля."""
    hints = {_STD_GROUP_HINT[k] for k in (_std_key(s) for s in stds) if k in _STD_GROUP_HINT}
    if len(hints) != 1:
        return None
    return hints.pop()


# Наименование группы — несколько слов и стандарты; примечание к таблице —
# длинный текст с двоеточиями и предложениями.
_MAX_GROUP_NAME_WORDS = 10


def _looks_like_group_name(text: str) -> bool:
    from .structure import is_service_profile_text
    if is_service_profile_text(text):
        return False
    words = strip_standards(text.replace("\n", " "), bare=True).split()
    return 0 < len(words) <= _MAX_GROUP_NAME_WORDS


def _canon_profile_group(cell: Cell) -> None:
    """Подтягивает OCR-кашу наименования профиля к закрытому словарю групп.

    «Мроdunu стцльные еНУМbIЕ замкнутые сбарные...» — это то же
    «Профили стальные гнутые замкнутые сварные...», а не новое значение.
    ГОСТ/ТУ из исходной ячейки сохраняем. Служебные строки («Итого»)
    словарь не трогает. Если словарное имя противоречит стандарту сортамента
    в той же ячейке, вид профиля берётся по стандарту (см. _STD_GROUP_HINT).
    """
    if row_marker(cell.text):
        return
    from .structure import canonical_profile_group
    canon, ratio = canonical_profile_group(cell.text)
    if not canon and getattr(cell, "alt_text", ""):
        # основной движок дал кашу («Теуеа_КеggраТНаn»), а второй — латинскую
        # кальку («TpY6Q KBOAPOTHOA»), которая сворачивается в «труба квадратная»
        canon, ratio = canonical_profile_group(cell.alt_text)
        if canon:
            cell.notes.append("наименование группы взято по чтению второго движка (%r)" % cell.alt_text)
    stds = extract_standards(cell.text, bare=True)
    # подсказка по стандарту — только для наименования группы: примечания к
    # таблице тоже ссылаются на ГОСТ («…по ГОСТ 19903-2015»), но это не группа
    hint = group_by_standard(stds) if _looks_like_group_name(cell.text) else None
    conflict = False
    if hint is not None:
        name, need, forbid = hint
        low = canon.lower()
        contradicts = bool(canon) and any(re.search(w, low) for w in forbid)
        agrees = bool(canon) and not contradicts and any(w in low for w in need)
        if contradicts:
            # слова расходятся со стандартом — вид профиля по стандарту, на проверку
            conflict = True
            cell.notes.append("наименование группы «%s» расходится со стандартом %s — "
                              "принято «%s»" % (canon, ", ".join(stds), name))
            canon = name
        elif not agrees and canon:
            # имя не противоречит стандарту, но менее точное («Прокат горячекатаный»)
            cell.notes.append("наименование группы «%s» уточнено по стандарту %s" % (canon, ", ".join(stds)))
            canon = name
        elif not canon:
            cell.notes.append("наименование группы восстановлено по стандарту %s" % ", ".join(stds))
            canon, ratio = name, 0.0
    if not canon:
        return
    # размер профиля внутри наименования («Труба квадратная 120х120х6») сохраняем:
    # его заберёт графа размера, если она пуста
    size = _TUBE_IN_GROUP_RE.search(cell.text)
    if size:
        canon = canon + " " + "%sх%sх%s" % size.groups()
    if ratio > 0:
        cell.notes.append(
            "наименование профиля приведено к каноническому виду (%.2f); raw=%r"
            % (ratio, cell.text))
    else:
        cell.notes.append("raw=%r" % cell.text)
    cell.text = canon if not stds else canon + "\n" + " ".join(stds)
    if ratio >= 0.80:
        cell.requires_review = False
    if conflict:
        cell.requires_review = True


def normalize_cell(cell: Cell, role: str) -> Cell:
    """Заполняет `normalized_value` / `value_kind` в соответствии с ролью колонки."""
    raw = cell.text
    if not raw.strip():
        cell.value_kind = "empty"
        cell.normalized_value = None
        return cell

    if role == "profile_size":
        stripped, glyph = strip_profile_glyph(raw, cell.source in RECOGNISED_SOURCES)
        if glyph:
            cell.notes.append("снят значок типа профиля %r; raw=%r" % (glyph, raw))
            cell.text = raw = stripped.strip()
            if not raw:
                cell.value_kind = "empty"
                cell.normalized_value = None
                return cell
        stripped, glyph = strip_trailing_glyph(raw)
        if glyph:
            cell.notes.append("снят значок типа профиля после обозначения %r; raw=%r" % (glyph, raw))
            cell.text = raw = stripped

    if cell.source in RECOGNISED_SOURCES:
        narrow = raw.translate(_FULLWIDTH)
        if narrow != raw:
            cell.notes.append("полноширинные знаки приведены к обычным; raw=%r" % raw)
            cell.text = raw = narrow
        cleaned, junked = _strip_ruling_junk(raw)
        if junked:
            cell.notes.append("снят артефакт линовки; raw=%r" % cell.text)
            cell.text = cleaned
        if role not in ("element_mass", "total_mass", "area", "position"):
            folded, folded_ok = _fold_homoglyphs(cell.text)
            if folded_ok:
                cell.notes.append("latin->cyrillic homoglyphs; raw=%r" % cell.text)
                cell.text = folded
        if role in ("profile_group", "steel_grade", "unknown", ""):
            from .structure import canonical_stamp_label, fix_paren_s, fold_mixed_script
            fixed = fix_paren_s(cell.text)
            if fixed != cell.text:
                cell.notes.append("скобка перед словом прочитана вместо «С»; raw=%r" % cell.text)
                cell.text = fixed
            if role == "profile_group":
                cleaned = _GROUP_LEADING_JUNK_RE.sub("", cell.text)
                if cleaned != cell.text:
                    cell.notes.append("снят артефакт линовки перед наименованием; raw=%r" % cell.text)
                    cell.text = cleaned
            if role == "steel_grade":
                lines = cell.text.split("\n")
                kept = [ln for ln in lines if not _JUNK_LINE_RE.fullmatch(ln.strip())]
                if kept and len(kept) < len(lines):
                    cell.notes.append("снята строка-артефакт из одной буквы; raw=%r" % cell.text)
                    cell.text = "\n".join(kept)
                if _STEEL_ST_RE.match(cell.text.strip()):
                    cell.notes.append("«т» в марке «Ст» прочитана латиницей; raw=%r" % cell.text)
                    cell.text = _STEEL_ST_RE.sub("Ст", cell.text.strip())
            if role in ("unknown", ""):
                # Ячейки без роли — штамп и подписи листа: курсив сворачивается в
                # кириллицу, типовые подписи штампа приводятся к канону.
                label = canonical_stamp_label(cell.text)
                if label and " ".join(cell.text.split()) != label:
                    cell.notes.append("подпись штампа приведена к канону; raw=%r" % cell.text)
                    cell.text = label
                else:
                    fixed = fold_mixed_script(cell.text)
                    if fixed != cell.text:
                        cell.notes.append("смешанное письмо свёрнуто в кириллицу; raw=%r" % cell.text)
                        cell.text = fixed
                        cell.requires_review = True
        fixed, changed = _fix_digit_context(cell.text)
        if changed:
            cell.notes.append("letter->digit fix inside numeric token; raw=%r" % cell.text)
            cell.text = fixed
        if role in ("profile_group", "steel_grade", "profile_size"):
            if not canon_service_row(cell) and role in ("profile_group", "steel_grade"):
                canon = canon_grades_and_standards(cell.text)
                if role == "steel_grade":
                    canon = fix_steel_grade(canon)
                if canon != cell.text:
                    cell.notes.append("марка/стандарт приведены к каноническому виду; raw=%r"
                                      % cell.text)
                    cell.text = canon
        if role == "profile_group":
            _canon_profile_group(cell)

    if role in ("element_mass", "total_mass", "area"):
        # В числовых колонках допускается только число. Всё прочее — на проверку.
        if cell.source in RECOGNISED_SOURCES:
            digits, relettered = _digits_only(cell.text)
            if relettered:
                cell.notes.append("буквы-двойники -> цифры в числовой колонке; raw=%r"
                                  % cell.text)
                cell.text = digits
                cell.requires_review = True
            lost = _LOST_COMMA_RE.fullmatch(cell.text.strip())
            if lost:
                cell.notes.append("пробел вместо десятичной запятой; raw=%r" % cell.text)
                cell.text = "%s,%s" % (lost.group(1), lost.group(2))
                cell.requires_review = True
            split = _SPLIT_DECIMAL_RE.fullmatch(cell.text.strip())
            if split:
                cell.notes.append("лишний пробел внутри дробной части; raw=%r" % cell.text)
                cell.text = split.group(1) + split.group(2)
                cell.requires_review = True
            trail = _TRAILING_SEP_RE.fullmatch(cell.text.strip())
            if trail:
                # «9.» — на чертеже так и напечатано (KM_GARAZH); это 9
                cell.notes.append("разделитель без дробной части; raw=%r" % cell.text)
                cell.text = trail.group(1)
            if _SPLIT_INT_RE.fullmatch(cell.text.strip()):
                compact = re.sub(r"[\s\u00a0\u2009]+", "", cell.text.strip())
                alt = re.sub(r"[\s\u00a0\u2009]+", "", (getattr(cell, "alt_text", "") or "").strip())
                if alt and alt == compact:
                    cell.notes.append("пробел внутри числа, второй движок прочитал без него; raw=%r" % cell.text)
                    cell.text = compact
                    cell.requires_review = True
            dbl = _DOUBLE_SEP_RE.fullmatch(cell.text.strip())
            if dbl:
                cell.notes.append("двойной десятичный разделитель; raw=%r" % cell.text)
                cell.text = dbl.group(1) + "," + dbl.group(2)
                cell.requires_review = True
        val = parse_number(cell.text)
        if val is None:
            cell.value_kind = "text"
            cell.normalized_value = None
            cell.requires_review = True
            cell.notes.append("numeric column holds non-numeric text")
        else:
            cell.value_kind = "number"
            cell.normalized_value = val
            if "." in cell.text and "," not in cell.text:
                cell.notes.append("decimal point instead of comma")
        return cell

    if role == "position":
        if cell.source in RECOGNISED_SOURCES:
            digits, relettered = _digits_only(cell.text)
            if relettered and _INT_RE.match(digits):
                cell.notes.append("буквы-двойники -> цифры в № п.п.; raw=%r" % cell.text)
                cell.text = digits
                cell.requires_review = True
        parts = [p.strip() for p in cell.text.split("\n") if p.strip()]
        ints = [int(p) for p in parts if _INT_RE.match(p)]
        if len(ints) == 1:
            cell.value_kind = "int"
            cell.normalized_value = ints[0]
        elif len(ints) > 1:
            # merged-ячейка без разделительной линии содержит несколько позиций
            cell.value_kind = "int_list"
            cell.normalized_value = ints
        else:
            cell.value_kind = "text"
            cell.normalized_value = None
            cell.requires_review = True
            cell.notes.append("position is not an integer")
        return cell

    if role == "profile_size":
        if cell.source in RECOGNISED_SOURCES:
            if _SHEET_DASH_T_RE.match(cell.text.strip()):
                cell.notes.append("снят значок листа «—» перед толщиной; raw=%r" % cell.text)
                cell.text = _SHEET_DASH_T_RE.sub("", cell.text.strip())
            plus = _PLUS_THICKNESS_RE.fullmatch(cell.text.strip())
            if plus:
                cell.notes.append("«+» перед толщиной листа прочитано вместо «t»; raw=%r" % cell.text)
                cell.text = "t" + plus.group(1)
            fixed = fix_series_zero(cell.text)
            if fixed != cell.text:
                cell.notes.append("буква «О» после серии двутавра прочитана вместо нуля; raw=%r" % cell.text)
                cell.text = fixed
        cell.text = canonical_size(cell.text)
        cell.value_kind = "code"
        cell.normalized_value = " ".join(cell.text.split())
        if (cell.source in RECOGNISED_SOURCES
                and _BARE_PROFILE_DIGITS.fullmatch(cell.normalized_value or "")):
            cell.requires_review = True
            cell.notes.append(
                "обозначение профиля из одних цифр; возможна потеря буквы типа (Б/Ш/К)")
        return cell

    cell.value_kind = "text"
    cell.normalized_value = " ".join(cell.text.replace("\n", " ").split())
    return cell


# «ГОСТ Р 57837-2017», «ГОСТ. 27772-2021» (точка и перенос после ГОСТ), «FОСТ
# 19903-2015» и «ГOCT» (латиница вместо Г/О/С/Т у OCR) — всё это ГОСТ. Префикс
# ловится с двойниками, номер — от первой цифры до последней.
GOST_RE = re.compile(
    r"(?<![А-Яа-яA-Za-z])"
    r"(?P<kind>[ГFfTТrг]?[ОO][СC][ТTГ]|ГОД(?=\s*\d{4,5}[-–])|ТУ|TY|СТО|CTO)"
    r"\s*\.?\s*(?P<r>[РP](?=[\s.\d]))?\s*\.?\s*"
    r"(?P<num>[0-9][0-9\-.–]*[0-9])")


def _canon_standard(m) -> str:
    kind = m.group("kind").upper().translate(str.maketrans("FOCTYR", "ГОСТУГ"))
    if kind.endswith("ОСГ"):                      # «ГОСГ Р 52246-2004»: Т прочитана как Г
        kind = kind[:-3] + "ОСТ"
    if kind == "ГОД":                             # «ГОД 27772-2021»: СТ прочитаны как Д
        kind = "ГОСТ"
    if kind.endswith("ОСТ") and len(kind) == 4:
        kind = "ГОСТ"
    if kind == "TY":
        kind = "ТУ"
    if kind == "CTO":
        kind = "СТО"
    # «ОСТ 8510-86» — это ГОСТ с потерянной «Г»: у отраслевых ОСТ номера вида
    # «36-72-82», а у ГОСТ сортамента — 4–5 цифр и год.
    if kind == "ОСТ" and re.fullmatch(r"[0-9]{4,5}-[0-9]{2,4}", m.group("num").replace("–", "-")):
        kind = "ГОСТ"
    num = _fix_standard_year(m.group("num").replace("–", "-"))
    return kind + (" Р" if m.group("r") else "") + " " + num


# Годы редакций часто встречающихся стандартов: OCR читает «27772-2021» как
# «27772-20861». Если номер известен, а год к нему не подходит, берётся ближайший
# по правке год из списка (не дальше двух правок).
KNOWN_STANDARD_YEARS = {
    "27772": ("2021", "2015", "88"), "8509": ("93",), "8510": ("86", "93"),
    "19903": ("2015", "74"), "19904": ("90",), "57837": ("2017",), "30245": ("2003", "2012"),
    "8240": ("97", "89"), "8639": ("82",), "53866": ("2010",), "24045": ("2016", "2010", "94"),
    "14918": ("80", "2020"), "103": ("2006", "76"), "8568": ("77",), "26020": ("83",),
    "8278": ("83",), "10704": ("91",), "10705": ("80",), "52246": ("2004", "2016"),
    "32931": ("2015",), "535": ("2005",), "380": ("2005",), "27751": ("2014",),
}


def _lev(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _fix_standard_year(num: str) -> str:
    m = re.fullmatch(r"(\d{3,5})-(\d{2,5})", num)
    if not m or m.group(1) not in KNOWN_STANDARD_YEARS:
        return num
    years = KNOWN_STANDARD_YEARS[m.group(1)]
    if m.group(2) in years:
        return num
    best = min(years, key=lambda y: _lev(m.group(2), y))
    if _lev(m.group(2), best) <= 2:
        return m.group(1) + "-" + best
    return num


# Голый номер стандарта без слова «ГОСТ»: OCR по чертёжному курсиву теряет
# слово целиком («Профили ... прямоугольные\n30245-2003»). Формат — 4–5 цифр
# номера, дефис, год из двух или четырёх цифр. Размеры профилей («160х160х5»,
# «140х5») и марки стали («С255-5») под него не подходят.
BARE_STD_RE = re.compile(r"(?<![\d\wх×*.,\-])(?P<num>\d{4,5}-(?:\d{4}|\d{2}))(?![\dх×x])")


def extract_standards(text: str, bare: bool = False) -> list[str]:
    """Все упоминания ГОСТ/ТУ в тексте, в каноническом виде («ГОСТ Р 57837-2017»).

    `bare=True` — ячейка наименования профиля: там номер вида «30245-2003»
    без слова «ГОСТ» тоже считается ГОСТом (для марки стали так делать нельзя:
    «27772-2021» рядом с маркой — это стандарт стали, но контекст другой).
    """
    out = [_canon_standard(m) for m in GOST_RE.finditer(text)]
    if bare:
        rest = GOST_RE.sub(" ", text)
        out += ["ГОСТ " + m.group("num") for m in BARE_STD_RE.finditer(rest)]
    return out


def strip_standards(text: str, bare: bool = False) -> str:
    """Текст без упоминаний ГОСТ/ТУ — остаётся наименование/марка."""
    t = GOST_RE.sub(" ", text)
    if bare:
        t = BARE_STD_RE.sub(" ", t)
    return " ".join(t.replace("\n", " ").split())
