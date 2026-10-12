# -*- coding: utf-8 -*-
"""Собирает источник OpenAPI 3.0.x из маршрутов бэкенда OZM и раскладывает зеркало.

Норма §1.4 требует источник `backend/openapi/openapi.yaml` и зеркало
`docs/api/openapi.yaml`, синхронные между собой (проверки [9/15] и [14/15]).
Описание строится по фактической регистрации маршрутов в коде (chi: r.Get/r.Post/
r.Put/r.Patch/r.Delete), поэтому пути в контракте — настоящие, а не пример из
шаблона. Схемы тел на этом шаге минимальные: контракт описывает маршруты,
статусы и общий формат ошибки; детальные схемы добавляются по мере надобности.
"""
import glob
import io
import os
import re

BASE = r'D:\dev\calc\ozm'
# только маршруты: строка начинается со слэша. Иначе в контракт попадают
# обращения к заголовкам (Header.Get("Authorization"), .Get("X-Request-Id")).
ROUTES_RE = re.compile(r'\.(Get|Post|Put|Patch|Delete)\("(/[^"]*)"')
GROUP_RE = re.compile(r'\.Route\("([^"]+)"')
HTTP_METHOD = {'Get': 'get', 'Post': 'post', 'Put': 'put', 'Patch': 'patch', 'Delete': 'delete'}


def collect() -> dict:
    paths: dict[str, dict] = {}
    for src in glob.glob(os.path.join(BASE, 'backend', '**', '*.go'), recursive=True):
        if src.endswith('_test.go'):
            continue
        text = io.open(src, encoding='utf-8', errors='replace').read()
        prefix = ''
        m = GROUP_RE.search(text)
        if m:
            prefix = m.group(1).rstrip('/')
        for method, route in ROUTES_RE.findall(text):
            full = (prefix + '/' + route.lstrip('/')).replace('//', '/')
            if not full.startswith('/'):
                full = '/' + full
            item = paths.setdefault(full, {})
            item[HTTP_METHOD[method]] = {
                'summary': route,
                'responses': {
                    '200': {'description': 'Успешный ответ'},
                    '400': {'$ref': '#/components/responses/Error'},
                    '401': {'$ref': '#/components/responses/Error'},
                    '500': {'$ref': '#/components/responses/Error'},
                },
            }
    return paths


def spec(paths: dict) -> str:
    lines = [
        '# Источник контракта OZM. Сгенерирован scripts/gen-openapi.py из маршрутов',
        '# бэкенда (internal/**). Зеркало — docs/api/openapi.yaml, обновляется тем же',
        '# скриптом; правки вносите в код и перегенерируйте.',
        'openapi: 3.0.3',
        'info:',
        '  title: OZM API',
        '  version: 1.0.0',
        '  description: >-',
        '    Калькулятор огнезащиты и распознавание таблиц ИД: расчёты, задания,',
        '    словари проката, выгрузка. Аутентификация — заголовок Authorization',
        '    (dev-режим: CALC_OZM_APP_AUTH_DEV_MODE).',
        'servers:',
        '  - url: /api/v1',
        '    description: локальный стенд',
        'paths:',
    ]
    for path in sorted(paths):
        lines.append('  %s:' % path)
        for method in ('get', 'post', 'put', 'patch', 'delete'):
            item = paths[path].get(method)
            if not item:
                continue
            lines.append('    %s:' % method)
            lines.append('      summary: %s' % item['summary'])
            lines.append('      responses:')
            for code, resp in item['responses'].items():
                if '$ref' in resp:
                    lines.append("        '%s':" % code)
                    lines.append('          $ref: %s' % resp['$ref'])
                else:
                    lines.append("        '%s':" % code)
                    lines.append('          description: %s' % resp['description'])
    lines += [
        'components:',
        '  responses:',
        '    Error:',
        '      description: Ошибка (единый формат)',
        '      content:',
        '        application/json:',
        '          schema:',
        '            type: object',
        '            required: [error]',
        '            properties:',
        '              error: { type: string }',
        '              details: { type: string }',
    ]
    return '\n'.join(lines) + '\n'


def main() -> None:
    paths = collect()
    text = spec(paths)
    src = os.path.join(BASE, 'backend', 'openapi', 'openapi.yaml')
    mirror = os.path.join(BASE, 'docs', 'api', 'openapi.yaml')
    for target in (src, mirror):
        os.makedirs(os.path.dirname(target), exist_ok=True)
        io.open(target, 'w', encoding='utf-8', newline='\n').write(text)
    print('маршрутов: %d' % len(paths))
    print('источник: %s' % src)
    print('зеркало:  %s' % mirror)


if __name__ == '__main__':
    main()
