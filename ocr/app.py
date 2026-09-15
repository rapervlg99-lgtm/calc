# -*- coding: utf-8 -*-
"""CLI: извлечение таблиц из строительного PDF.

    python app.py input.pdf --output ./result

Всё выполняется локально. Никаких обращений к внешним сервисам нет.
"""
from __future__ import annotations

import argparse
import os
import sys

from ocrpdf.pipeline import Options, run


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="app.py",
        description="Локальное извлечение таблиц из проектных PDF "
                    "(спецификация металлопроката и подобные).")
    ap.add_argument("pdf", help="путь к входному PDF")
    ap.add_argument("--output", "-o", default="./result", help="каталог результатов")
    ap.add_argument("--pages", default="", help="страницы: '1', '1-3', '1,4' (по умолчанию все)")
    ap.add_argument("--dpi", type=int, default=350,
                    help="DPI рендера для распознавания глифов (по умолчанию 350)")
    ap.add_argument("--ocr", default="none",
                    choices=["none", "auto", "hybrid", "rapidocr", "tesseract"],
                    help="растровый OCR-резерв для сканов и чертёжных шрифтов "
                         "(по умолчанию отключён). hybrid — Tesseract на "
                         "наименованиях, RapidOCR на числах; auto берёт его, "
                         "если доступны оба движка")
    ap.add_argument("--low-conf", type=float, default=0.62,
                    help="порог confidence для пометки ячейки на ручную проверку")
    ap.add_argument("--tol-base", type=float, default=0.02,
                    help="базовый допуск арифметических проверок, т")
    ap.add_argument("--tol-per-term", type=float, default=0.006,
                    help="допуск на одно слагаемое (округление до 2 знаков), т")
    ap.add_argument("--all-glyphs", action="store_true",
                    help="писать посимвольную трассировку для всех ячеек, "
                         "а не только для спорных")
    ap.add_argument("--quiet", action="store_true", help="не печатать сводку")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.pdf):
        print("файл не найден: %s" % args.pdf, file=sys.stderr)
        return 2

    opts = Options(dpi=args.dpi, ocr_backend=args.ocr, low_conf=args.low_conf,
                   tolerance_base=args.tol_base, tolerance_per_term=args.tol_per_term,
                   pages=args.pages, all_glyphs=args.all_glyphs)
    report = run(args.pdf, args.output, opts)

    if not args.quiet:
        ac = report["arithmetic_checks"]
        print("Готово за %.1f с" % report["elapsed_sec"])
        for page in report["pages"]:
            print("  стр. %d: %s, текстовый слой: %s, линовка: %d, глифов: %d"
                  % (page["number"], page["content_kind"], page["text_layer"],
                     page["n_ruling_lines"], page["n_vector_glyphs"]))
            for note in page["notes"]:
                print("      - %s" % note)
        for q in report["table_quality"]:
            mark = "  <- не распознано" if q["kind"] == "unreadable" else ""
            print("    table_%d %-14s %-8s значений %3d, спорных %3d  %s%s"
                  % (q["table"], q["kind"], q["grid"], q["cells_non_empty"],
                     q["cells_flagged"], q["title"][:34], mark))
            for note in q["notes"]:
                if note not in ("начало", "окончание", "продолжение"):
                    print("        %s" % note)
        print("  таблиц: %d (нераспознано %d), ячеек: %d (непустых %d), на проверку: %d"
              % (report["tables_found"], report["tables_unreadable"],
                 report["cells_total"], report["cells_non_empty"],
                 report["cells_low_confidence"]))
        print("  источники значений: %s" % report["cells_by_source"])
        print("  арифметика: пройдено %d, не пройдено %d, пропущено %d"
              % (ac["passed"], ac["failed"], ac["skipped"]))
        for f in report["failed_checks"][:12]:
            print("      ! table_%d стр.%d %s: в PDF %s, пересчёт %s (разница %s)"
                  % (f["table"], f["row"], f["kind"], f["expected"],
                     f["calculated"], f["delta"]))
        print("  файлы в %s: %s" % (report["output_dir"], ", ".join(report["files"])))
    return 1 if report["arithmetic_checks"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
