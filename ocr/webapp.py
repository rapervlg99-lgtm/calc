# -*- coding: utf-8 -*-
"""Запуск локального веб-интерфейса.

    python webapp.py                      # http://127.0.0.1:8000
    python webapp.py --port 9000 --open

Сервер слушает только localhost: документ не покидает машину.
"""
from __future__ import annotations

import argparse
import os

from ocrpdf.webapp import DEFAULT_PORT, serve


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="webapp.py",
        description="Локальный веб-интерфейс для извлечения таблиц из проектных PDF.")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT,
                    help="порт (по умолчанию %d); если занят, будет выбран "
                         "следующий свободный" % DEFAULT_PORT)
    ap.add_argument("--host", default="127.0.0.1",
                    help="адрес; по умолчанию только localhost. Менять только "
                         "осознанно: сервер не имеет аутентификации")
    ap.add_argument("--base-path", default=os.environ.get("OCRPDF_BASE_PATH", ""),
                    help="публичный префикс, если интерфейс отдаётся за reverse "
                         "proxy (например /ocr). Без слэша на конце")
    ap.add_argument("--open", action="store_true", help="открыть браузер")
    args = ap.parse_args(argv)
    serve(args.host, args.port, args.open, args.base_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
