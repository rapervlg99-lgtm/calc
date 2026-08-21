#!/usr/bin/env python3
"""Extract OZM dicts from DC/t500/x500/roll XML (parity with cmd/dcextract)."""
from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DC_DIR = ROOT / "testdata" / "dc"
OUT = ROOT / "dicts"


def atof(s: str) -> float:
    try:
        return float(str(s).strip().replace(",", "."))
    except Exception:
        return 0.0


def parse_t500(path: Path) -> list[dict]:
    root = ET.parse(path).getroot()
    rows = []
    for tr in root.iter("tr"):
        tds = [t.text or "" for t in tr.findall("td")]
        if len(tds) < 4:
            continue
        rows.append(
            {
                "baseDelta": atof(tds[0]),
                "a": atof(tds[1]),
                "b": atof(tds[2]),
                "thickness": atof(tds[3]),
            }
        )
    return rows


def parse_x500(path: Path) -> list[dict]:
    root = ET.parse(path).getroot()
    coats = []
    for i, coat_el in enumerate(root.findall("coat"), start=1):
        coat = {"index": i, "columns": []}
        for r in coat_el.findall("R"):
            col = {"min": atof(r.attrib.get("min", "0")), "rows": []}
            heat = r.find("heat")
            if heat is not None:
                col["heat"] = {
                    "dpr": 0,
                    "delta": atof(heat.attrib.get("δ") or heat.attrib.get("delta", "0")),
                    "rate": atof(heat.attrib.get("rate", "0")),
                }
            for row in r.findall("row"):
                col["rows"].append(
                    {
                        "dpr": atof((row.text or "").strip()),
                        "delta": atof(row.attrib.get("δ") or row.attrib.get("delta", "0")),
                        "rate": atof(row.attrib.get("rate", "0")),
                    }
                )
            for t in r.findall("taikor"):
                heat = t.find("heat")
                if heat is not None and "heat" not in col:
                    col["heat"] = {
                        "dpr": 0,
                        "delta": atof(heat.attrib.get("δ") or heat.attrib.get("delta", "0")),
                        "rate": atof(heat.attrib.get("rate", "0")),
                    }
                for row in t.findall("row"):
                    col["rows"].append(
                        {
                            "dpr": atof((row.text or "").strip()),
                            "delta": atof(row.attrib.get("δ") or row.attrib.get("delta", "0")),
                            "rate": atof(row.attrib.get("rate", "0")),
                        }
                    )
            coat["columns"].append(col)
        coats.append(coat)
    return coats


def load_shape_by_select_id(dc_path: Path) -> dict[str, str]:
    """Map roll <select id> → calc shape id via DC.xml picture/code."""
    if not dc_path.exists():
        return {}
    text = dc_path.read_text(encoding="utf-8", errors="ignore")
    code_to_pic: dict[str, str] = {}
    for m in re.finditer(r'picture="([^"]+)"[^>]*\bcode="(\d+)"', text):
        code_to_pic[m.group(2)] = m.group(1)
    for m in re.finditer(r'\bcode="(\d+)"[^>]*picture="([^"]+)"', text):
        code_to_pic.setdefault(m.group(1), m.group(2))
    return code_to_pic


def parse_roll(path: Path, dc_path: Path | None = None) -> list[dict]:
    """Parse roll.xml: label is <o> text content; shape from DC picture/code."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    shape_by_id = load_shape_by_select_id(dc_path or (path.parent / "DC.xml"))
    marks: list[dict] = []
    current_select_id = ""
    current_shape = ""

    # Track <select ...> openings.
    for m in re.finditer(r"<select\b([^>]*)>", text, flags=re.I):
        pass  # handled in combined loop below

    # Combined scan: select opens + o with body text.
    token_re = re.compile(
        r"<select\b([^>]*)>|</select>|<o\b([^>]*)>([^<]*)</o>|<o\b([^>]*)\s*/>",
        re.I,
    )
    for m in token_re.finditer(text):
        if m.group(0).lower().startswith("<select"):
            attrs = dict(re.findall(r"""([\w-]+)=['"]([^'"]*)['"]""", m.group(1) or ""))
            current_select_id = attrs.get("id") or ""
            current_shape = shape_by_id.get(current_select_id) or attrs.get("name") or current_shape
            continue
        if m.group(0).lower().startswith("</select"):
            current_select_id = ""
            continue

        attrs_s = m.group(2) if m.group(2) is not None else (m.group(4) or "")
        label = (m.group(3) or "").strip()
        attrs = dict(re.findall(r"""([\w-]+)=['"]([^'"]*)['"]""", attrs_s))
        if not label:
            label = attrs.get("title") or attrs.get("name") or ""
        rid = attrs.get("id") or attrs.get("name") or label
        if not rid and not label:
            continue
        dims: dict[str, float] = {}
        for k, v in attrs.items():
            if k in ("name", "title", "id"):
                continue
            try:
                dims[k] = float(str(v).replace(",", "."))
            except Exception:
                pass
        marks.append(
            {
                "id": str(rid),
                "shape": current_shape,
                "label": label or str(rid),
                "dims": dims,
            }
        )
    return marks


def default_profiles():
    return [
        {
            "id": "I-beam",
            "label": "двутавр",
            "hard": 0,
            "shapes": [
                {"id": "I-beam_", "label": "двутавр", "picture": "I-beam_"},
                {"id": "I-beam_sm", "label": "двутавр простой", "picture": "I-beam_sm"},
                {"id": "I-beam_sl", "label": "двутавр с уклоном полок", "picture": "I-beam_sl"},
            ],
        },
        {
            "id": "channel",
            "label": "швеллер",
            "hard": 0,
            "shapes": [
                {"id": "channel_", "label": "швеллер", "picture": "channel_"},
                {"id": "channel_sl", "label": "швеллер с уклоном полок", "picture": "channel_sl"},
            ],
        },
        {
            "id": "brands",
            "label": "тавр",
            "hard": 1,
            "shapes": [
                {"id": "brands_", "label": "тавр", "picture": "brands_"},
                {"id": "brands_sm", "label": "тавр простой", "picture": "brands_sm"},
            ],
        },
        {
            "id": "corner",
            "label": "уголок",
            "hard": 1,
            "shapes": [
                {"id": "corner_", "label": "уголок", "picture": "corner_"},
                {"id": "corner_e", "label": "уголок равнополочный", "picture": "corner_e"},
                {"id": "corner_ue", "label": "уголок неравнополочный", "picture": "corner_ue"},
            ],
        },
        {
            "id": "profile",
            "label": "профиль",
            "hard": 2,
            "shapes": [
                {"id": "profile_", "label": "профиль", "picture": "profile_"},
                {"id": "profile_sm", "label": "профиль простой", "picture": "profile_sm"},
            ],
        },
        {
            "id": "tube",
            "label": "труба",
            "hard": 2,
            "shapes": [
                {"id": "tube_", "label": "труба", "picture": "tube_"},
                {"id": "tube_sm", "label": "труба круглая", "picture": "tube_sm"},
                {"id": "tube_sq", "label": "труба квадратная", "picture": "tube_sq"},
            ],
        },
    ]


def default_selects():
    return {
        "fr_durability": [{"value": str(i), "label": l} for i, l in enumerate(["I", "II", "III", "IV", "V"], 1)],
        "fr_type": [
            {"value": "1", "label": "несущая конструкция"},
            {"value": "0", "label": "самонесущая конструкция"},
        ],
        "ht_level": [{"value": str(v), "label": f"R{v}"} for v in (15, 30, 45, 60, 90, 120, 150, 180, 210, 240)],
        "fr_coat": [
            {"value": "1", "label": "ТЕХНО ОЗМ"},
            {"value": "2", "label": "TAIKOR FP Epoxy"},
            {"value": "3", "label": "TAIKOR FP Graphite"},
            {"value": "4", "label": "TAIKOR FP Extra + TAIKOR FP Graphite"},
            {"value": "1.5", "label": "АКЗ"},
        ],
        "fr_method": [
            {"value": "1", "label": "огнезащита по коробу"},
            {"value": "0", "label": "огнезащита по контуру"},
        ],
        "fr_side": [
            {"value": "left", "label": "левая"},
            {"value": "top", "label": "верх"},
            {"value": "right", "label": "правая"},
            {"value": "bottom", "label": "низ"},
        ],
    }


def default_materials():
    return [
        {"id": "OZM", "title": "ТЕХНО ОЗМ", "unit": "м³", "q": 1.25},
        {"id": "OZB", "title": "ТЕХНО ОЗБ", "unit": "м³", "q": 1.03},
        {"id": "KCer", "title": "Клей Ceresit CT 190", "unit": "кг", "rate": 1.2},
        {"id": "KVer", "title": "Штукатурка Ceresit", "unit": "кг", "rate": 3.2},
        {"id": "KAnk", "title": "Металлический анкер с шайбой", "unit": "шт", "rate": 7},
        {"id": "T150p", "title": "TAIKOR Primer 150", "unit": "кг", "rate": 0.230},
        {"id": "Taikor", "title": "TAIKOR FP", "unit": "кг"},
        {"id": "T425t", "title": "TAIKOR Top 425", "unit": "кг", "rate": 0.170},
    ]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    t500 = parse_t500(DC_DIR / "t500.xml")
    x500 = parse_x500(DC_DIR / "x500.xml")
    roll = parse_roll(DC_DIR / "roll.xml", DC_DIR / "DC.xml")
    profiles = default_profiles()
    selects = default_selects()
    materials = default_materials()
    cfg = {
        "taikorQ": 1.43,
        "ozmQ": 1.25,
        "ozbQ": 1.03,
        "steelDensity": 7850,
        "ozbByR": {"180": 50, "240": 40},
    }
    for name, data in [
        ("t500.json", t500),
        ("x500.json", x500),
        ("roll.json", roll),
        ("profiles.json", profiles),
        ("selects.json", selects),
        ("materials_rt.json", materials),
        ("calculation_config.json", cfg),
    ]:
        (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    report = (
        f"# DC extract report\n\n"
        f"- t500 rows: {len(t500)}\n"
        f"- x500 coats: {len(x500)}\n"
        f"- roll marks: {len(roll)}\n"
        f"- profile families: {len(profiles)}\n"
        f"- materials: {len(materials)}\n"
    )
    report_path = ROOT.parent / "dev" / "docs" / "extract_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
