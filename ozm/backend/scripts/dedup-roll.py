# -*- coding: utf-8 -*-
"""Убирает дубликаты из словаря проката, сохраняя уникальные значения.

Запуск:
    python dedup-roll.py            # отчёт
    python dedup-roll.py --write    # записать (с копией roll.json.dedup.bak)

Ключ профиля — форма + марка + стандарт (при пустом стандарте добавляется подпись
размеров, иначе слиплись бы разные профили с одинаковой маркой). Остаётся одна
запись на ключ, по приоритету источника: calclab-metalloprokat (актуальный
каталог) → spravochnik-v5 (перенос из инженерного справочника) → legacy.

Массы при этом не теряются: разные стандарты одной марки (например, 50Ш4 по СТО
АСЧМ 20-93 и по ГОСТ 35087-2024) — это разные ключи, обе записи остаются.
"""
import collections
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROLL = os.path.normpath(os.path.join(HERE, '..', 'dicts', 'roll.json'))
PRIORITY = {'calclab-metalloprokat': 3, 'spravochnik-v5': 2}


def norm(text) -> str:
    s = str(text or '').strip().lower().replace('×', 'x').replace('х', 'x')
    return re.sub(r'\s+', '', s).replace(',', '.')


def sig(rec: dict) -> str:
    """Подпись размеров: у legacy-записей нет стандарта, их различаем по размерам."""
    dims = rec.get('dims') or {}
    parts = ['%s=%s' % (k, dims[k]) for k in sorted(dims)]
    return '|'.join(parts)


def key(rec: dict) -> str:
    # Истина — кальклаб (решение Олега 09.10): при расхождении массы у одной марки
    # и стандарта остаётся запись каталога, запись справочника v5 уходит. Поэтому
    # масса в ключ не входит — приоритет источника решает.
    k = '~'.join([norm(rec.get('shape')), norm(rec.get('label')), norm(rec.get('standard'))])
    if not norm(rec.get('standard')):
        k += '~' + sig(rec)
    return k


def main() -> int:
    write = '--write' in sys.argv
    roll = json.load(io.open(ROLL, encoding='utf-8'))
    best: dict[str, dict] = {}
    removed = collections.Counter()
    for rec in roll:
        k = key(rec)
        cur = best.get(k)
        if cur is None:
            best[k] = rec
            continue
        old_p = PRIORITY.get(cur.get('source'), 1)
        new_p = PRIORITY.get(rec.get('source'), 1)
        # при равном приоритете оставляем запись с размерами/площадью
        if new_p > old_p or (new_p == old_p and not cur.get('dims') and rec.get('dims')):
            removed[cur.get('source') or '(без источника)'] += 1
            best[k] = rec
        else:
            removed[rec.get('source') or '(без источника)'] += 1
    kept = list(best.values())

    # проверки: ничего уникального не потеряно
    before_pairs = {(norm(r.get('label')), norm(r.get('standard'))) for r in roll}
    after_pairs = {(norm(r.get('label')), norm(r.get('standard'))) for r in kept}
    before_masses = {round(float(r['massPerMeter']), 4) for r in roll if isinstance(r.get('massPerMeter'), (int, float))}
    after_masses = {round(float(r['massPerMeter']), 4) for r in kept if isinstance(r.get('massPerMeter'), (int, float))}
    lost_pairs = before_pairs - after_pairs
    lost_masses = before_masses - after_masses

    # расхождения: та же марка и стандарт, но другая масса — не дубликат
    pairs = collections.defaultdict(set)
    for r in roll:
        pairs[(norm(r.get('shape')), norm(r.get('label')), norm(r.get('standard')))].add(
            round(float(r['massPerMeter']), 4) if isinstance(r.get('massPerMeter'), (int, float)) else None)
    conflicts = {k: v for k, v in pairs.items() if len(v) > 1}
    print('расхождений по массе (побеждает кальклаб): %d' % len(conflicts))
    for k, v in list(conflicts.items())[:4]:
        print('    %s -> %s' % (k[1] or k[0], sorted(v)))
    print('было записей: %d, осталось: %d, удалено дубликатов: %d' % (len(roll), len(kept), len(roll) - len(kept)))
    print('удалено по источникам: %s' % dict(removed))
    print('уникальных пар (марка, стандарт): было %d, стало %d, потеряно %d'
          % (len(before_pairs), len(after_pairs), len(lost_pairs)))
    print('уникальных масс: было %d, стало %d, потеряно %d'
          % (len(before_masses), len(after_masses), len(lost_masses)))
    if lost_pairs:
        print('   ПОТЕРЯНЫ ПАРЫ:', list(lost_pairs)[:5])
    if lost_masses:
        print('   ПОТЕРЯНЫ МАССЫ:', sorted(lost_masses)[:5])
    if not write:
        print('режим отчёта: файл не изменён')
        return 0
    with io.open(ROLL, encoding='utf-8') as fh:
        original = fh.read()
    with io.open(ROLL + '.dedup.bak', 'w', encoding='utf-8') as fh:
        fh.write(original)
    with io.open(ROLL, 'w', encoding='utf-8') as fh:
        json.dump(kept, fh, ensure_ascii=False, indent=1)
    print('записано: %d записей, копия roll.json.dedup.bak' % len(kept))
    return 0


if __name__ == '__main__':
    sys.exit(main())
