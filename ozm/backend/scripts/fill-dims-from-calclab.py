# -*- coding: utf-8 -*-
"""Подставляет размеры сечений в позиции справочника v5 из каталога кальклаба.

Запуск:
    python fill-dims-from-calclab.py            # только отчёт
    python fill-dims-from-calclab.py --write    # записать в dicts/roll.json

Правило сопоставления: та же марка (section_designation) и **совпавшая масса** с
точностью 0,5 %. Масса — самый надёжный признак того, что сечение из той же
редакции стандарта: у 40Ш1 по ГОСТ 35087-2024 масса 88,6 кг/м, а по ГОСТ
26020-83 — 96,1 кг/м, это разные сечения, поэтому привязка по одной марке
подставила бы чужие размеры.

Площадь берётся из A_gross (см²) → мм²; размеры — из sec_h/sec_b/t_w/t_f/r_root
в те же ключи h/b/s/t/R, что у записей кальклаба (проверено на 50Ш4).
"""
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROLL = os.path.normpath(os.path.join(HERE, '..', 'dicts', 'roll.json'))
CATALOG = r'D:\dev\calclab.pro\data\fire-protection\profile-catalog.json'
SOURCE = 'spravochnik-v5'
# формы, у которых ключи h/b/s/t/R совпадают с записями кальклаба
SHAPES = {'I-beam_sm', 'I-beam_sl', 'channel_', 'channel_sl'}


def key(text: str) -> str:
    s = str(text or '').strip().lower().replace('×', 'x').replace('х', 'x')
    return re.sub(r'\s+', '', s).replace(',', '.')


def main() -> int:
    write = '--write' in sys.argv
    roll = json.load(io.open(ROLL, encoding='utf-8'))
    cat = json.load(io.open(CATALOG, encoding='utf-8'))['rows']
    by_mark = {}
    for row in cat:
        by_mark.setdefault(key(row.get('section_designation')), []).append(row)

    filled = no_candidates = mass_mismatch = skipped_shape = 0
    examples, problems = [], []
    for rec in roll:
        if rec.get('source') != SOURCE:
            continue
        if rec.get('dims'):
            continue
        if rec.get('shape') not in SHAPES:
            skipped_shape += 1
            continue
        cands = by_mark.get(key(rec.get('label')), [])
        if not cands:
            no_candidates += 1
            continue
        mass = float(rec.get('massPerMeter') or 0)
        same = [c for c in cands if c.get('mass_kg_per_m')
                and abs(float(c['mass_kg_per_m']) - mass) <= 0.005 * mass]
        if not same:
            mass_mismatch += 1
            closest = min(cands, key=lambda c: abs(float(c.get('mass_kg_per_m') or 0) - mass))
            problems.append('%s: в словаре %.3f, в кальклабе %.3f — размеры не взяты'
                            % (rec['label'], mass, float(closest.get('mass_kg_per_m') or 0)))
            continue
        row = same[0]
        dims = {}
        for src, dst in (('sec_h', 'h'), ('sec_b', 'b'), ('t_w', 's'), ('t_f', 't'), ('r_root', 'R')):
            if isinstance(row.get(src), (int, float)) and row[src] > 0:
                dims[dst] = row[src]
        area = row.get('A_gross')
        if not dims or not isinstance(area, (int, float)) or area <= 0:
            no_candidates += 1
            continue
        rec['dims'] = dims
        # A_gross в каталоге уже в мм² (10Б1 → 1032 мм² = 10,32 см²), поэтому без пересчёта
        rec['areaMm2'] = round(float(area))
        filled += 1
        if len(examples) < 4:
            examples.append('%s: %s, площадь %s мм² (%s)'
                            % (rec['label'], json.dumps(dims, ensure_ascii=False), rec['areaMm2'],
                               row.get('section_catalog_standard')))

    print('дозаполнено размеров: %d' % filled)
    print('нет марки в каталоге: %d, масса не совпала: %d, форма без правила: %d'
          % (no_candidates, mass_mismatch, skipped_shape))
    for e in examples:
        print('   ', e)
    for p in problems[:8]:
        print('    !', p)
    if not write:
        print('режим отчёта: roll.json не изменён')
        return 0
    with io.open(ROLL, encoding='utf-8') as fh:
        original = fh.read()
    with io.open(ROLL + '.dims.bak', 'w', encoding='utf-8') as fh:
        fh.write(original)
    with io.open(ROLL, 'w', encoding='utf-8') as fh:
        json.dump(roll, fh, ensure_ascii=False, indent=1)
    print('записано, копия roll.json.dims.bak')
    return 0


if __name__ == '__main__':
    sys.exit(main())
