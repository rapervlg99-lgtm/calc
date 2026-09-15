# -*- coding: utf-8 -*-
"""Ремонт текстового слоя PDF с Identity-H шрифтами без /ToUnicode.

ПОЧЕМУ ПОРТИТСЯ КИРИЛЛИЦА
-------------------------
В тестовом PDF три шрифта объявлены как Type0 / Encoding = Identity-H с
CIDToGIDMap = /Identity и БЕЗ словаря /ToUnicode. Коды в потоке содержимого —
это не Unicode и не WinAnsi, а прямые glyph id исходного шрифта. Встроенные
сабсеты при этом лишены таблицы cmap (обратного отображения нет) и имеют
таблицу post формата 3.0 (имён глифов тоже нет).

Значит, в самом документе информации о Unicode физически не осталось.
Любой экстрактор (pdftotext, PyMuPDF, pdfplumber) вынужден догадываться;
PyMuPDF трактует CID как codepoint — отсюда 'ȼɫɟɝɨ' вместо 'Всего'.

КАК ЧИНИМ ДЕТЕРМИНИРОВАННО
--------------------------
Сабсет сохраняет нумерацию глифов ИСХОДНОГО шрифта (nglyphs 4548 ~ полный
ArialMT, CIDToGIDMap /Identity). Достаточно взять оригинальный шрифт
(системный arial.ttf, isocpeur.ttf, GOST Common Italic.ttf), построить по его
cmap отображение unicode -> gid и обратить его.

Догадка проверяется независимо: PDF хранит массив /W (ширины по CID). Если для
каждого CID ширина из PDF совпадает с шириной глифа в системном шрифте —
соответствие glyph order подтверждено. Мэппинг принимается только при
достаточном совпадении, иначе шрифт помечается как невосстановимый и текст
такого шрифта уходит в векторный распознаватель / OCR.
"""
from __future__ import annotations

import io
import os
import re
from dataclasses import dataclass, field

from fontTools.ttLib import TTFont

from .pdfbackend import fitz

# Кандидаты исходных шрифтов: нормализованное имя из PDF -> файлы в системе.
FONT_CANDIDATES: dict[str, list[str]] = {
    "arialmt": ["arial.ttf"],
    "arial": ["arial.ttf"],
    "arialboldmt": ["arialbd.ttf"],
    "arialbold": ["arialbd.ttf"],
    "arialitalicmt": ["ariali.ttf"],
    "timesnewromanpsmt": ["times.ttf"],
    "isocpeur": ["isocpeur.ttf"],
    "isocpeuritalic": ["isocpeui.ttf", "isocpeur.ttf"],
    "isocp": ["isocp___.ttf"],
    "gostcommon": ["GOST Common.ttf"],
    "gostcommonitalic": ["GOST Common Italic.ttf", "GOST Common.ttf"],
    "gosttypea": ["GOST type A.ttf"],
    "gosttypeb": ["GOST type B.ttf"],
}

FONT_DIRS = [
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts"),
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    os.path.expanduser("~/.fonts"),
]


def _find_font_file(filename: str) -> str | None:
    low = filename.lower()
    for d in FONT_DIRS:
        if not d or not os.path.isdir(d):
            continue
        p = os.path.join(d, filename)
        if os.path.isfile(p):
            return p
        try:
            for f in os.listdir(d):
                if f.lower() == low:
                    return os.path.join(d, f)
        except OSError:
            pass
    return None


@dataclass
class FontRepair:
    basefont: str
    family: str
    ok: bool
    gid2uni: dict[int, str] = field(default_factory=dict)
    source: str = ""
    width_match: float = 0.0
    width_checked: int = 0
    reason: str = ""


def _pdf_widths(doc: fitz.Document, font_xref: int) -> dict[int, float]:
    """Ширины по CID из /W (CIDFontType2) либо /Widths+/FirstChar (простой TrueType)."""
    try:
        obj = doc.xref_object(font_xref)
    except Exception:
        return {}
    m = re.search(r"/DescendantFonts\s*\[\s*(\d+)\s+0\s+R", obj)
    if m:
        try:
            obj = doc.xref_object(int(m.group(1)))
        except Exception:
            return {}
    widths: dict[int, float] = {}
    wm = re.search(r"/W\s*\[(.*?)\]\s*(?:/|>>)", obj, re.S)
    if wm:
        toks = re.findall(r"\[[^\]]*\]|-?\d+\.?\d*", wm.group(1), re.S)
        i = 0
        while i < len(toks):
            if toks[i].startswith("["):
                i += 1
                continue
            start = int(float(toks[i]))
            if i + 1 < len(toks) and toks[i + 1].startswith("["):
                vals = [float(v) for v in re.findall(r"-?\d+\.?\d*", toks[i + 1])]
                for k, v in enumerate(vals):
                    widths[start + k] = v
                i += 2
            elif i + 2 < len(toks):
                end = int(float(toks[i + 1]))
                v = float(toks[i + 2])
                if 0 <= start <= end <= start + 65535:
                    for c in range(start, end + 1):
                        widths[c] = v
                i += 3
            else:
                break
        return widths
    fm = re.search(r"/FirstChar\s+(\d+)", obj)
    wm2 = re.search(r"/Widths\s*\[(.*?)\]", obj, re.S)
    if fm and wm2:
        first = int(fm.group(1))
        for k, v in enumerate(float(x) for x in re.findall(r"-?\d+\.?\d*", wm2.group(1))):
            widths[first + k] = v
    return widths


def _build_from_system_font(family: str):
    """-> (gid2uni, gid2width_1000, path) либо None."""
    for fn in FONT_CANDIDATES.get(family, []):
        path = _find_font_file(fn)
        if not path:
            continue
        try:
            tt = TTFont(path, lazy=True, fontNumber=0)
            n_glyphs = int(tt["maxp"].numGlyphs)
            cmap = tt.getBestCmap()
            order = tt.getGlyphOrder()
            g2i = {g: i for i, g in enumerate(order)}
            gid2uni: dict[int, str] = {}
            for uni, gname in cmap.items():
                gid = g2i.get(gname)
                if gid is not None and gid not in gid2uni:
                    gid2uni[gid] = chr(uni)
            upem = tt["head"].unitsPerEm
            metrics = tt["hmtx"].metrics
            gid2w = {g2i[g]: metrics[g][0] * 1000.0 / upem for g in order if g in metrics}
            tt.close()
            return gid2uni, gid2w, path, n_glyphs
        except Exception:
            continue
    return None


def _embedded_glyph_count(doc: fitz.Document, xref: int) -> int:
    """Число глифов встроенного сабсета. При Identity-сабсетинге оно совпадает с
    исходным шрифтом — второй независимый признак совпадения glyph order."""
    try:
        buf = doc.extract_font(xref)[3]
        if not buf:
            return -1
        tt = TTFont(io.BytesIO(buf), lazy=True, fontNumber=0, checkChecksums=0)
        n = tt["maxp"].numGlyphs
        tt.close()
        return int(n)
    except Exception:
        return -1


def _build_from_embedded(doc: fitz.Document, xref: int) -> dict[int, str]:
    """Если сабсет всё же сохранил cmap или имена глифов — это самый надёжный источник."""
    out: dict[int, str] = {}
    try:
        info = doc.extract_font(xref)
        buf = info[3]
        if not buf:
            return out
        tt = TTFont(io.BytesIO(buf), lazy=True, fontNumber=0, checkChecksums=0)
        order = tt.getGlyphOrder()
        try:
            cmap = tt.getBestCmap()
            g2i = {g: i for i, g in enumerate(order)}
            for uni, gname in cmap.items():
                gid = g2i.get(gname)
                if gid is not None:
                    out.setdefault(gid, chr(uni))
        except Exception:
            pass
        for gid, gname in enumerate(order):
            if gid in out:
                continue
            m = re.fullmatch(r"uni([0-9A-Fa-f]{4,6})|u([0-9A-Fa-f]{4,6})", gname or "")
            if m:
                code = int(m.group(1) or m.group(2), 16)
                if 0xF000 <= code <= 0xF0FF:      # symbol-диапазон PUA -> ASCII
                    code -= 0xF000
                out[gid] = chr(code)
        tt.close()
    except Exception:
        pass
    return out


def build_font_repairs(doc: fitz.Document, page: fitz.Page) -> dict[str, FontRepair]:
    """Для каждого шрифта страницы строит GID -> Unicode и валидирует его ширинами."""
    repairs: dict[str, FontRepair] = {}
    for f in page.get_fonts(full=True):
        xref, basefont, encoding = f[0], f[3], f[5]
        family_raw = basefont.split("+")[-1]
        family = re.sub(r"[^a-z0-9]", "", family_raw.lower())
        def put(rep: FontRepair) -> None:
            # Одно и то же имя шрифта может встречаться дважды (Type0 + простой
            # TrueType). Пригодный для ремонта вариант не затираем.
            old = repairs.get(family_raw)
            if old is None or (rep.ok and not old.ok):
                repairs[family_raw] = rep

        try:
            has_tounicode = "/ToUnicode" in doc.xref_object(xref)
        except Exception:
            has_tounicode = False
        # Шрифты с нормальной кодировкой чинить не нужно.
        if (encoding and encoding != "Identity-H") or has_tounicode:
            put(FontRepair(basefont, family_raw, ok=False,
                           reason="encoding is sane, no repair needed"))
            continue

        emb = _build_from_embedded(doc, xref)
        if len(emb) > 32:
            put(FontRepair(basefont, family_raw, True, emb,
                           source="embedded subset cmap/post"))
            continue

        built = _build_from_system_font(family)
        if built is None:
            put(FontRepair(basefont, family_raw, False, emb,
                           reason="original font for '%s' not installed" % family_raw))
            continue
        gid2uni, gid2w, path, n_sys = built

        # Проверка 1 (основная): ширины глифов из /W против системного шрифта.
        pdfw = _pdf_widths(doc, xref)
        hit = tot = 0
        for cid, w in pdfw.items():
            if cid in gid2w:
                tot += 1
                if abs(gid2w[cid] - w) <= 2.0:
                    hit += 1
        ratio = hit / tot if tot else 0.0
        ok = tot >= 5 and ratio >= 0.90

        # Проверка 2 (когда /W отсутствует): совпадение числа глифов сабсета.
        note = ""
        if not ok and tot < 5:
            n_emb = _embedded_glyph_count(doc, xref)
            if n_emb > 0 and n_emb == n_sys:
                ok = True
                note = "verified by glyph count %d" % n_emb
            else:
                note = "no /W and glyph count mismatch (%s vs %s)" % (n_emb, n_sys)

        put(FontRepair(
            basefont, family_raw, ok, gid2uni if ok else emb,
            source="system font " + os.path.basename(path),
            width_match=ratio, width_checked=tot,
            reason=note if ok else (note or "width check failed (%d/%d)" % (hit, tot)),
        ))
    return repairs


def decode_span(chars: list[dict], family_raw: str,
                repairs: dict[str, FontRepair]) -> tuple[str, bool]:
    """(текст, применён_ли_ремонт) для одного span из rawdict."""
    rep = repairs.get(family_raw)
    raw = "".join(c["c"] for c in chars)
    # Ремонт применяем только если текст действительно выглядит битым: под одним
    # именем шрифта в PDF могут жить и корректный, и повреждённый вариант.
    if rep is None or not rep.ok or not looks_broken(raw):
        return raw, False
    out = []
    for c in chars:
        gid = ord(c["c"])          # PyMuPDF положил CID как codepoint
        out.append(rep.gid2uni.get(gid, c["c"]))
    return "".join(out), True


# Диапазоны, куда попадают glyph id, ошибочно истолкованные как codepoint:
# Latin Extended-B, IPA Extensions, Spacing Modifiers, Greek/Coptic, Private Use,
# плюс управляющие символы (пробел с gid 3 приходит как ).
# Диапазоны, куда попадают glyph id, ошибочно истолкованные как codepoint:
# Latin Extended-B, IPA Extensions, Spacing Modifiers, Greek/Coptic, Private Use,
# а также управляющие символы (пробел с gid 3 приходит как код 0x03).
_BROKEN_RANGES = (
    (0x0180, 0x02FF),   # Latin Extended-B + IPA Extensions + Spacing Modifiers
    (0x0370, 0x03FF),   # Greek and Coptic
    (0xE000, 0xF8FF),   # Private Use Area
    (0x0000, 0x0008),   # управляющие
    (0x000B, 0x001F),
)


def looks_broken(text: str) -> bool:
    """Эвристика: похоже ли, что текст декодирован неверно.

    Одиночная греческая буква — нормальное обозначение на чертеже («δ=4 мм»,
    «α», «Ø»), а не сбой кодировки; битый текст даёт греческие знаки серией.
    """
    greek = 0
    for ch in text:
        o = ord(ch)
        if 0x0370 <= o <= 0x03FF:
            greek += 1
            continue
        for lo, hi in _BROKEN_RANGES:
            if lo <= o <= hi:
                return True
    return greek >= 2
