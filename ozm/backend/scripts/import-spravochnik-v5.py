# -*- coding: utf-8 -*-
"""Переносит позиции из «Инженерного справочника масс металла v5.0» в словарь проката.

Запуск:
    python import-spravochnik-v5.py <книга.xlsx>            # только отчёт, файл не меняется
    python import-spravochnik-v5.py <книга.xlsx> --write    # дописать в dicts/roll.json

Что делает:
* читает листы книги (Профиль | ГОСТ | Масса, кг/м | Источник | Примечание);
* приводит подпись к формату словаря (в словаре «□40×40×2», «L20×3», «Тр. 10×1»,
  а в книге «250x6», «20×20×3», «10×1»), десятичную точку — к запятой;
* пропускает позиции, которые уже есть (марка + стандарт), и лист «Листовой
  прокат» (там масса на м², а не на метр профиля);
* пишет новые записи с source=spravochnik-v5, areaMm2 = масса / 0,00785 (та же
  плотность 7850, что и в записях calclab);
* в режиме --write делает резервную копию roll.json и дописывает записи в конец.
"""
import io
import json
import os
import re
import sys

from openpyxl import load_workbook

HERE = os.path.dirname(os.path.abspath(__file__))
ROLL = os.path.normpath(os.path.join(HERE, '..', 'dicts', 'roll.json'))
SOURCE = 'spravochnik-v5'

# лист книги -> (shape в словаре, семейство, как привести подпись, статус стандарта)
SHEETS = {
    '1. Двутавры': ('I-beam_sm', 'Двутавры', 'plain', None),
    '2. Швеллеры': ('channel_', 'Швеллеры', 'plain', None),
    '4. Уголки равнополочные': ('corner_e', 'Равнополочные', 'corner_eq', None),
    '5. Уголки неравнополочные': ('corner_ue', 'Неравнополочные', 'corner_uneq', None),
    '6. Уголок гнутый': ('corner_bent', 'Гнутые уголки', 'corner_bent', None),
    '7. Трубы проф. кв.': ('tube_sq', 'Квадратные', 'tube_sq', None),
    '8. Трубы проф. прямоугольные': ('profile_sm', 'Прямоугольные', 'tube_rect', None),
    '9. Трубы эл-св круглые': ('tube_sm', 'Круглые', 'tube_round', None),
    '10. Листовой прокат': ('', 'Листовой прокат', 'skip', None),
}

# действующие редакции: всё остальное из книги — заменённые
CURRENT = {'ГОСТ 30245-2003', 'ГОСТ 10704-91', 'ГОСТ 19903-2015', 'ГОСТ 8510-86',
           'ГОСТ 8239-89', 'ГОСТ 5267.1-90', 'ГОСТ 19425-74'}


def key(text: str) -> str:
    """Канонический ключ подписи: без значков вида профиля, × → x, запятая → точка."""
    s = str(text or '').strip().lower()
    s = s.replace('×', 'x').replace('х', 'x').replace(' ', '')
    s = re.sub(r'^(□|l|тр\.?|гн\.?)', '', s)
    return s.replace(',', '.')


def num(v) -> str:
    """Число из подписи: 2.5 → «2,5», 6 → «6»."""
    f = float(str(v).replace(',', '.'))
    return ('%g' % f).replace('.', ',')


def label(kind: str, raw: str) -> str:
    s = str(raw or '').strip().replace('х', 'x').replace('×', 'x')
    parts = [p for p in re.split(r'[xX]', s) if p != '']
    if kind == 'plain':
        return s.replace('x', '×')
    if kind == 'corner_eq':                      # 20×20×3 -> L20×3
        return 'L%s×%s' % (num(parts[0]), num(parts[2]))
    if kind == 'corner_uneq':                    # 25×16×3 -> L25×16×3
        return 'L%s×%s×%s' % (num(parts[0]), num(parts[1]), num(parts[2]))
    if kind == 'tube_sq':                        # 250x6 -> □250×250×6
        return '□%s×%s×%s' % (num(parts[0]), num(parts[0]), num(parts[1]))
    if kind == 'tube_rect':                      # 50x25x2 -> □50×25×2
        return '□%s×%s×%s' % (num(parts[0]), num(parts[1]), num(parts[2]))
    if kind == 'tube_round':                     # 10×1 -> Тр. 10×1
        return 'Тр. %s×%s' % (num(parts[0]), num(parts[1]))
    if kind == 'corner_bent':                    # книга уже даёт 32×25×2 -> L32×25×2
        if len(parts) >= 3:
            return 'L%s×%s×%s' % (num(parts[0]), num(parts[1]), num(parts[2]))
        return 'L%s' % num(parts[0])
    return s


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    book, write = sys.argv[1], '--write' in sys.argv
    roll = json.load(io.open(ROLL, encoding='utf-8'))
    have = {(key(e.get('label')), str(e.get('standard') or '')) for e in roll}
    have_keys = {key(e.get('label')) for e in roll}
    status_of = {}
    for e in roll:
        if e.get('standard'):
            status_of.setdefault(str(e['standard']), e.get('standardStatus') or 'current')

    wb = load_workbook(book, data_only=True, read_only=True)
    added, skipped, report = [], 0, []
    for ws in wb.worksheets:
        conf = None
        for name, cfg in SHEETS.items():          # имя листа в книге обрезано (31 знак)
            if ws.title.strip().startswith(name.split('.')[0] + '.'):
                conf = cfg
                break
        if not conf:
            report.append('лист %r пропущен: нет правила' % ws.title)
            continue
        shape, family, kind, _ = conf
        if kind == 'skip':
            report.append('лист %r пропущен: масса на м², не на метр профиля' % ws.title)
            continue
        n_add = n_dup = n_bad = 0
        for i, r in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            if not r or not r[0] or not r[1] or r[2] in (None, ''):
                continue
            raw, std, mass = str(r[0]).strip(), str(r[1]).strip(), r[2]
            std = re.sub(r'\s+', ' ', std)
            lab = label(kind, raw)
            try:
                mpm = float(str(mass).replace(',', '.'))
            except ValueError:
                n_bad += 1
                continue
            if (key(lab), std) in have:
                n_dup += 1
                continue
            status = status_of.get(std) or ('current' if std in CURRENT else 'deprecated')
            added.append({
                'id': '%s:%d' % (SOURCE, len(added) + 1),
                'shape': shape,
                'label': lab,
                'dims': {},
                'standard': std,
                'standardLabel': '%s — %s' % (std, 'действующий' if status == 'current' else 'заменён'),
                'standardStatus': status,
                'familyLabel': family,
                'source': SOURCE,
                'sourceRowId': '%s:%s:%d' % (SOURCE, ws.title.split('.')[0], i),
                'areaMm2': round(mpm / 0.00785),
                'massPerMeter': round(mpm, 4),
            })
            n_add += 1
        skipped += n_dup
        report.append('%-30s добавлено %-4d уже было %-4d без массы %d' % (ws.title, n_add, n_dup, n_bad))

    print('\n'.join(report))
    stds = sorted({e['standard'] for e in added})
    print('всего новых записей: %d, дубликатов пропущено: %d' % (len(added), skipped))
    print('стандарты новых записей: %s' % ', '.join(stds))
    print('примеры: %s' % json.dumps(added[:3], ensure_ascii=False))
    if not write:
        print('режим отчёта: roll.json не изменён (для записи добавьте --write)')
        return 0
    backup = ROLL + '.bak'
    with io.open(ROLL, encoding='utf-8') as fh:
        original = fh.read()
    with io.open(backup, 'w', encoding='utf-8') as fh:
        fh.write(original)
    out = json.loads(original) + added
    with io.open(ROLL, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print('записано: было %d, стало %d, копия %s' % (len(roll), len(out), backup))
    return 0


if __name__ == '__main__':
    sys.exit(main())
