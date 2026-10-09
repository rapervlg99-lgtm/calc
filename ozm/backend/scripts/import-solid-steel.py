# -*- coding: utf-8 -*-
"""Переносит сортовой прокат из кальклаба (data/references/solid-steel-catalog.json).

Запуск:
    python import-solid-steel.py            # только отчёт
    python import-solid-steel.py --write    # дописать в dicts/roll.json (с копией)

Что переносится (771 позиция):
* ГОСТ 103-2006  — полосы горячекатаные   (thickness, width, масса из таблицы);
* ГОСТ 2590-2006 — круги горячекатаные    (диаметр, площадь см², масса из таблицы);
* ГОСТ 2591-2006 — квадраты горячекатаные (только сторона: площадь и масса
  считаются аналитически при плотности 7850 кг/м³, как и сказано в шапке файла).

Марки: «4×12» у полосы, «Ø5» у круга, «6×6» у квадрата. Источник помечается
calclab-solid-steel — скрипт синхронизации профилей такие записи сохраняет.
"""
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROLL = os.path.normpath(os.path.join(HERE, '..', 'dicts', 'roll.json'))
CATALOG = r'D:\dev\calclab.pro\data\references\solid-steel-catalog.json'
SOURCE = 'calclab-solid-steel'
DENSITY = 0.00785  # кг/м на мм²


def num(v) -> str:
    return ('%g' % float(v)).replace('.', ',')


def main() -> int:
    write = '--write' in sys.argv
    roll = json.load(io.open(ROLL, encoding='utf-8'))
    cat = json.load(io.open(CATALOG, encoding='utf-8'))
    have = {(r.get('label'), r.get('standard')) for r in roll if r.get('source') == SOURCE}
    added = []
    for std in cat['standards']:
        cols = list(std.get('columns') or [])
        code, shape, family = std['code'], std['shape'], std.get('label') or ''
        n = 0
        for row in std.get('sizes') or []:
            vals = dict(zip(cols, row))
            label, dims, mass = '', {}, None
            if shape == 'solid_rectangle':
                t, b = vals.get('thickness_mm'), vals.get('width_mm')
                label = '%s×%s' % (num(t), num(b))
                dims = {'t': t, 'b': b}
                mass = vals.get('table_mass_kg_per_m') or (t * b * DENSITY)
            elif shape == 'solid_circle':
                d = vals.get('diameter_mm')
                label = 'Ø%s' % num(d)
                dims = {'d': d}
                mass = vals.get('table_mass_kg_per_m') or (3.141592653589793 * (d / 2) ** 2 * DENSITY)
            elif shape == 'solid_square':
                a = vals.get('side_mm')
                label = '%s×%s' % (num(a), num(a))
                dims = {'a': a}
                mass = a * a * DENSITY
            if not label or not mass:
                continue
            if (label, code) in have:
                continue
            area = vals.get('table_area_cm2')
            area_mm2 = round(area * 100) if isinstance(area, (int, float)) else round(mass / DENSITY)
            added.append({
                'id': '%s:%d' % (SOURCE, len(added) + 1),
                'shape': shape, 'label': label, 'dims': dims,
                'standard': code, 'standardLabel': '%s — действующий' % code,
                'standardStatus': 'current', 'familyLabel': family,
                'source': SOURCE, 'sourceRowId': '%s:%s:%s' % (SOURCE, code.split()[-1], label),
                'areaMm2': area_mm2, 'massPerMeter': round(float(mass), 4),
            })
            n += 1
        print('%-16s %-18s %-26s добавлено %d' % (code, shape, family[:26], n))
    print('всего новых записей: %d' % len(added))
    print('примеры:', json.dumps(added[:3], ensure_ascii=False))
    if not write:
        print('режим отчёта: файл не изменён')
        return 0
    with io.open(ROLL, encoding='utf-8') as fh:
        original = fh.read()
    with io.open(ROLL + '.solid.bak', 'w', encoding='utf-8') as fh:
        fh.write(original)
    out = json.loads(original) + added
    with io.open(ROLL, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print('записано: было %d, стало %d, копия roll.json.solid.bak' % (len(roll), len(out)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
