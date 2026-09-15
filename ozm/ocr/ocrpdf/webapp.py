# -*- coding: utf-8 -*-
"""Локальный веб-интерфейс: положил PDF — получил распознанные таблицы.

Реализован на стандартной библиотеке (`http.server`), поэтому не требует ни
одной дополнительной зависимости и не тянет ничего из сети: страница целиком
самодостаточна, внешних CSS/JS/шрифтов нет.

Сервер слушает ТОЛЬКО 127.0.0.1: загруженный документ не покидает машину.

    python webapp.py                 # http://127.0.0.1:8000
    python webapp.py --port 9000 --open
    python webapp.py --port 8090 --base-path /ocr   # за reverse proxy calclab.pro/ocr

Для встраивания в backend тот же результат доступен как JSON:

    POST /api/extract   multipart/form-data, поле `file`  -> 202 {job, status}
    GET  /api/job/<job>                                   -> 202 пока считается, затем JSON с результатом
    GET  /api/recent                                      -> последние задания на диске
    GET  /api/file/<job>/<имя файла>                      -> выгрузка XLSX/JSON/CSV/PNG
"""
from __future__ import annotations

import gzip
import html
import json
import mimetypes
import os
import re
import shutil
import tempfile
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

from .ocr_backends import TesseractBackend, rapidocr_importable
from .pdfbackend import fitz
from .pipeline import Cancelled, Options, parse_pages, run

MAX_UPLOAD = 200 * 1024 * 1024          # 200 МБ
JOB_TTL_SEC = 6 * 3600                  # через сколько убирать временные каталоги

# Пределы на одно задание. Конвейер выполняет задания строго по одному, поэтому
# один альбом на сорок листов или лист А0 остановил бы очередь для всех. Лист А1
# с «взорванным» текстом читается 1–2,5 мин, скан курсивом — до 1,5 мин; лимит
# времени взят с двукратным запасом и не меньше MIN_JOB_SEC на задание. Всё
# переопределяется переменными окружения (OCRPDF_MAX_PAGES и т. д.).
MAX_PAGES = int(os.environ.get("OCRPDF_MAX_PAGES", "") or 10)
MAX_SEC_PER_PAGE = float(os.environ.get("OCRPDF_MAX_SEC_PER_PAGE", "") or 300)
MIN_JOB_SEC = float(os.environ.get("OCRPDF_MIN_JOB_SEC", "") or 600)
SAFE_NAME = re.compile(r"^[A-Za-z0-9_.\-]+$")
JOB_ID = re.compile(r"^[0-9a-f]{32}$")


def normalize_base_path(path: str) -> str:
    """'/ocr/' → '/ocr'; '/' или пустая строка → ''."""
    path = (path or "").strip()
    if not path or path == "/":
        return ""
    if not path.startswith("/"):
        path = "/" + path
    return path.rstrip("/")


def forwarded_prefix(headers) -> str:
    """Префикс, под которым нас отдаёт reverse proxy (nginx калькулятора ОЗМ
    проксирует /ocr/ -> корень этого сервера и шлёт X-Forwarded-Prefix: /ocr).
    Без флага --base-path сервер сам живёт в корне, а страница строит ссылки
    от этого префикса — тогда один и тот же процесс работает и напрямую на
    :8000, и внутри калькулятора."""
    try:
        raw = headers.get("X-Forwarded-Prefix", "") if headers is not None else ""
    except Exception:
        raw = ""
    raw = (raw or "").split(",")[0].strip()
    if not re.fullmatch(r"/[A-Za-z0-9_./-]{0,80}", raw):
        return ""
    return normalize_base_path(raw)


def page_html(base_path: str) -> str:
    """HTML страницы с подставленным префиксом ссылок."""
    return PAGE.replace("__BASE_PATH__", normalize_base_path(base_path))


def app_path(request_path: str, base_path: str) -> str | None:
    """Путь внутри приложения (префикс снят). None — запрос не к этому сервису.

    Пустая строка значит «нужен редирект на base + /» (зашли на /ocr или на /).
    """
    path = request_path.split("?")[0] or "/"
    base = normalize_base_path(base_path)
    if not base:
        return path
    if path in ("/", base):
        return ""
    if path.startswith(base + "/"):
        stripped = path[len(base):]
        return stripped if stripped else "/"
    return None

_jobs_root = os.path.join(tempfile.gettempdir(), "ocrpdf-jobs")
_lock = threading.Lock()
# Флаги отмены выполняющихся заданий: job -> Event. Выставляется по
# POST /api/job/<job>/cancel, конвейер проверяет его между этапами.
_cancel_flags: dict[str, threading.Event] = {}


# Очередь заданий в порядке поступления: первое — выполняется, остальные ждут
# `_run_gate`. По ней интерфейс показывает «перед вами N заданий».
_queue: list[str] = []


def queue_ahead(job: str) -> int | None:
    """Сколько заданий перед данным (0 — выполняется сейчас); None — не в очереди."""
    with _lock:
        return _queue.index(job) if job in _queue else None


def count_pages(data: bytes) -> int:
    """Число страниц PDF; 0, если файл не открывается (повреждён, пароль)."""
    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            return int(doc.page_count)
    except Exception:  # noqa: BLE001
        return 0


def page_limit_error(n_pages: int, pages_spec: str) -> tuple[int, str]:
    """(сколько страниц пойдёт в обработку, текст ошибки или '')."""
    if n_pages <= 0:
        return 0, "не удалось открыть PDF: файл повреждён или защищён паролем"
    try:
        selected = len(parse_pages(pages_spec, n_pages))
    except ValueError:
        return 0, "поле «Страницы» должно выглядеть как 1-3 или 2,5"
    if not selected:
        return 0, "в поле «Страницы» нет ни одной страницы из %d" % n_pages
    if selected > MAX_PAGES:
        if pages_spec.strip():
            msg = ("выбрано %d страниц, за одно задание обрабатывается не больше %d"
                   % (selected, MAX_PAGES))
        else:
            msg = ("в документе %d страниц, за одно задание обрабатывается не больше %d — "
                   "укажите нужные листы в поле «Страницы», например 1-%d"
                   % (n_pages, MAX_PAGES, MAX_PAGES))
        return selected, msg
    return selected, ""


def job_budget_sec(n_pages: int) -> float:
    return max(MIN_JOB_SEC, MAX_SEC_PER_PAGE * max(1, n_pages))


def request_cancel(job: str) -> str:
    """'cancelling' — задание выполняется и получило сигнал; 'finished' — уже
    завершено (отменять нечего); 'unknown' — такого задания нет."""
    with _lock:
        ev = _cancel_flags.get(job)
    if ev is not None:
        ev.set()
        st_path = os.path.join(_jobs_root, job, "status.json")
        filename = ""
        try:
            with open(st_path, encoding="utf-8") as fh:
                filename = json.load(fh).get("filename", "")
        except Exception:
            pass
        _write_status(job, {"status": "cancelling", "filename": filename})
        return "cancelling"
    job_dir = os.path.join(_jobs_root, job)
    return "finished" if os.path.isdir(job_dir) else "unknown"


# --------------------------------------------------------------------------- #
#  разбор multipart/form-data (минимальный, на один файл)
# --------------------------------------------------------------------------- #
def parse_multipart(body: bytes, content_type: str) -> dict[str, tuple[str, bytes]]:
    """-> {имя поля: (имя файла, содержимое)}. Пустой dict, если разбор не удался."""
    m = re.search(r'boundary=(?:"([^"]+)"|([^;]+))', content_type)
    if not m:
        return {}
    boundary = (m.group(1) or m.group(2)).strip().encode()
    sep = b"--" + boundary
    out: dict[str, tuple[str, bytes]] = {}
    for part in body.split(sep):
        if not part or part in (b"--\r\n", b"--"):
            continue
        part = part.lstrip(b"\r\n")
        if part.startswith(b"--"):
            continue
        head, _, data = part.partition(b"\r\n\r\n")
        if not _:
            continue
        disp = ""
        for line in head.split(b"\r\n"):
            if line.lower().startswith(b"content-disposition:"):
                disp = line.decode("utf-8", "replace")
        name = re.search(r'name="([^"]*)"', disp)
        if not name:
            continue
        fname = re.search(r'filename="([^"]*)"', disp)
        out[name.group(1)] = (fname.group(1) if fname else "",
                              data[:-2] if data.endswith(b"\r\n") else data)
    return out


# --------------------------------------------------------------------------- #
#  задания
# --------------------------------------------------------------------------- #
_OCR_CAPS: dict[str, dict] | None = None


def ocr_capabilities() -> dict[str, dict]:
    """Какие растровые OCR-движки реально доступны в этом окружении.

    RapidOCR не создаём: загрузка ONNX на каждый GET /api/capabilities
    занимала несколько секунд и ещё раз повторялась при обработке PDF.
    """
    global _OCR_CAPS
    if _OCR_CAPS is not None:
        return _OCR_CAPS
    tess = TesseractBackend()
    rapid_ok = rapidocr_importable()
    tess_warn = list(tess.warnings or [])
    _OCR_CAPS = {
        "tesseract": {"available": bool(tess.available), "warnings": tess_warn},
        "rapidocr": {
            "available": rapid_ok,
            "warnings": [] if rapid_ok else ["rapidocr-onnxruntime не установлен"],
        },
        "hybrid": {
            "available": bool(rapid_ok and tess.available),
            "warnings": tess_warn if tess.available else (
                tess_warn or ["нужны RapidOCR и Tesseract"]),
        },
    }
    return _OCR_CAPS


def _cleanup_old_jobs() -> None:
    if not os.path.isdir(_jobs_root):
        return
    now = time.time()
    for name in os.listdir(_jobs_root):
        path = os.path.join(_jobs_root, name)
        try:
            if now - os.path.getmtime(path) > JOB_TTL_SEC:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass


def _mark_orphaned_jobs() -> int:
    """Задания со статусом running/cancelling при СТАРТЕ сервера — сироты.

    Их поток погиб вместе с прошлым процессом (перезапуск контейнера, OOM),
    а status.json на томе остался. Без этого в списке «недавних» такое задание
    вечно висит «running», а открывший его интерфейс ждёт 15 минут до тайм-аута.
    """
    if not os.path.isdir(_jobs_root):
        return 0
    n = 0
    for name in os.listdir(_jobs_root):
        st_path = os.path.join(_jobs_root, name, "status.json")
        try:
            with open(st_path, encoding="utf-8") as fh:
                st = json.load(fh)
        except (OSError, ValueError):
            continue
        if st.get("status") in ("running", "cancelling"):
            _write_status(name, {
                "status": "error", "filename": st.get("filename", ""),
                "error": "обработка прервана перезапуском сервера — загрузите файл ещё раз"})
            n += 1
    return n


def _recent_jobs(limit: int = 8) -> list[dict]:
    """Готовые задания ещё лежат на диске — чтобы не грузить PDF повторно."""
    if not os.path.isdir(_jobs_root):
        return []
    items: list[dict] = []
    for name in os.listdir(_jobs_root):
        if not JOB_ID.fullmatch(name):
            continue
        job_dir = os.path.join(_jobs_root, name)
        env_path = os.path.join(job_dir, "envelope.json")
        st_path = os.path.join(job_dir, "status.json")
        status = "unknown"
        filename = ""
        phase = ""
        if os.path.isfile(st_path):
            try:
                with open(st_path, encoding="utf-8") as fh:
                    payload = json.load(fh)
                status = payload.get("status") or status
                filename = payload.get("filename") or ""
                phase = payload.get("phase") or ""
            except Exception:
                pass
        if os.path.isfile(env_path):
            status = "done"
            if not filename:
                try:
                    with open(env_path, encoding="utf-8") as fh:
                        chunk = fh.read(2048)
                    m = re.search(r'"filename"\s*:\s*"([^"]*)"', chunk)
                    filename = m.group(1) if m else ""
                except Exception:
                    pass
        try:
            mtime = os.path.getmtime(job_dir)
        except OSError:
            continue
        if status == "running":
            pos = queue_ahead(name)
            phase = "queued" if pos else ("processing" if pos == 0 else phase)
        items.append({
            "job": name,
            "filename": filename,
            "status": status,
            "phase": phase,
            "mtime": int(mtime),
        })
    items.sort(key=lambda x: -x["mtime"])
    return items[:limit]


def _write_status(job: str, payload: dict) -> None:
    path = os.path.join(_jobs_root, job, "status.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)


def _prepare_job(filename: str, data: bytes) -> str:
    """Каталог задания + сохранённый PDF. Статус `running`."""
    with _lock:
        os.makedirs(_jobs_root, exist_ok=True)
        _cleanup_old_jobs()
    job = uuid.uuid4().hex
    job_dir = os.path.join(_jobs_root, job)
    os.makedirs(os.path.join(job_dir, "result"), exist_ok=True)
    with open(os.path.join(job_dir, "input.pdf"), "wb") as fh:
        fh.write(data)
    _write_status(job, {"status": "running", "phase": "queued",
                        "filename": filename or "input.pdf"})
    return job


# Задания выполняются СТРОГО по одному. Два конвейера параллельно — это два
# растра страницы, два набора шаблонов и два RapidOCR в одном процессе: на
# машине с 12 ГБ (VM Docker — 6 ГБ) память уходила в своп, лист, который один
# читается за минуты, «считался» больше пяти и не завершался, а повторно
# загруженное задание висло со статусом running. Очередь — обычный Lock:
# следующее задание ждёт, его статус уже running, интерфейс показывает
# «Считаем…»; отмена в очереди срабатывает сразу после получения очереди.
_run_gate = threading.Lock()


def _run_job(job: str, filename: str, opts: Options, n_pages: int = 1) -> dict | None:
    """Конвейер в фоне. Envelope пишется на диск; при ошибке — status.json.

    `n_pages` — сколько страниц пойдёт в обработку: от него считается лимит
    времени (`job_budget_sec`). Лимит проверяется тем же кооперативным флагом,
    что и отмена пользователем: конвейер спрашивает его перед каждой страницей,
    блоком и вызовом OCR, поэтому реальное превышение — до одного блока.
    """
    job_dir = os.path.join(_jobs_root, job)
    src = os.path.join(job_dir, "input.pdf")
    out_dir = os.path.join(job_dir, "result")
    cancel = threading.Event()
    with _lock:
        _cancel_flags[job] = cancel
        _queue.append(job)
    budget = job_budget_sec(n_pages)
    deadline = [float("inf")]           # выставляется, когда задание реально стартует
    opts.should_cancel = lambda: cancel.is_set() or time.time() > deadline[0]
    try:
        if not _run_gate.acquire(blocking=False):
            print("  задание %s ждёт завершения предыдущего" % job, flush=True)
            _run_gate.acquire()
        try:
            if cancel.is_set():
                raise Cancelled()
            deadline[0] = time.time() + budget
            _write_status(job, {"status": "running", "phase": "processing",
                                "filename": filename, "pages": n_pages,
                                "budget_sec": int(budget)})
            report = run(src, out_dir, opts)
        finally:
            _run_gate.release()
        envelope = _build_envelope(job, filename, report, out_dir)
        with open(os.path.join(job_dir, "envelope.json"), "w", encoding="utf-8") as fh:
            json.dump(envelope, fh, ensure_ascii=False)
        _write_status(job, {"status": "done", "filename": filename})
        return envelope
    except Cancelled:
        if not cancel.is_set() and time.time() > deadline[0]:
            print("  лимит времени: %s (%d с на %d стр.)" % (job, budget, n_pages), flush=True)
            _write_status(job, {
                "status": "error", "filename": filename,
                "error": ("обработка остановлена: превышен лимит времени — %d мин на %d стр. "
                          "Документ слишком тяжёлый для сервиса: выберите меньше страниц "
                          "в поле «Страницы» или снизьте DPI" % (budget // 60, n_pages))})
            return None
        print("  остановлено пользователем: %s" % job, flush=True)
        _write_status(job, {"status": "cancelled", "filename": filename})
        return None
    except Exception as exc:
        print("  ОШИБКА: %s" % exc, flush=True)
        _write_status(job, {"status": "error",
                            "error": "не удалось обработать документ: %s" % exc,
                            "trace": traceback.format_exc()})
        return None
    finally:
        with _lock:
            _cancel_flags.pop(job, None)
            if job in _queue:
                _queue.remove(job)


def process_upload(filename: str, data: bytes, opts: Options) -> dict:
    """Сохраняет загруженный PDF, прогоняет конвейер, собирает ответ для UI."""
    job = _prepare_job(filename, data)
    envelope = _run_job(job, filename, opts)
    if envelope is None:
        raise RuntimeError("обработка задания %s не удалась" % job)
    return envelope


def _build_envelope(job: str, filename: str, report: dict, out_dir: str) -> dict:

    tables = []
    # Берём все table_N.json с диска, а не 1..tables_found: раньше индекс
    # сбрасывался на каждой странице, и файл второй страницы затирал первую.
    numbered = []
    for name in os.listdir(out_dir):
        m = re.fullmatch(r"table_(\d+)\.json", name)
        if m:
            numbered.append((int(m.group(1)), name))
    for i, name in sorted(numbered):
        path = os.path.join(out_dir, name)
        with open(path, encoding="utf-8") as fh:
            t = json.load(fh)
        tables.append({
            "index": t["index"], "title": t["title"], "kind": t["kind"],
            "part": t["part"], "page": t["page"], "notes": t.get("notes", []),
            "continues_table": t["continues_table"],
            "n_rows": t["n_rows"], "n_cols": t["n_cols"],
            "header_rows": t["header_rows"],
            "columns": [{"index": c["index"], "role": c["role"],
                         "element": c["element"], "letter": c["letter"],
                         "title": c["title"]} for c in t["columns"]],
            # для отрисовки сетки как на чертеже нужны только эти поля
            "cells": [{"r": c["row"], "c": c["col"],
                       "rs": c["row_span"], "cs": c["col_span"],
                       "t": c["text"], "v": c["normalized_value"],
                       "k": c["value_kind"], "conf": c["confidence"],
                       "src": c["source"], "rev": c["requires_review"],
                       "notes": c["notes"]} for c in t["cells"]],
            "rows": [{"row": r["row"], "kind": r["row_kind"],
                      "position": r["position"],
                      "profile_group": r["profile_group"],
                      "steel_grade": r["steel_grade"],
                      "standards": r["steel_grade_standards"] or r["profile_group_standards"],
                      # раздельно: ГОСТ сортамента (колонка 1) и ГОСТ стали (колонка 2)
                      "profile_standards": r["profile_group_standards"],
                      "steel_standards": r["steel_grade_standards"],
                      "profile_size": r["profile_size"],
                      # варианты марки, когда буква серии не разобрана («2011» → 20Б1/20Ш1/20К1)
                      "profile_size_candidates": r.get("profile_size_candidates") or [],
                      "elements": {k: v["normalized_value"]
                                   for k, v in r["elements"].items()},
                      "total": r["total_mass_t"],
                      "validation": r["validation"]} for r in t["rows"]],
            "checks": t["checks"],
            "files": ["table_%d.%s" % (i, ext) for ext in ("xlsx", "json", "csv")],
        })

    debug_images = sorted(f for f in os.listdir(out_dir) if f.endswith("_debug.png"))
    return {"job": job, "filename": filename, "report": report,
            "tables": tables, "debug_images": debug_images}


# --------------------------------------------------------------------------- #
#  страница (всё встроено: ни одного внешнего ресурса)
# --------------------------------------------------------------------------- #
PAGE = r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Распознавание таблиц из проектных PDF</title>
<style>
  /* Палитра калькулятора ОЗМ (frontend/src/styles/tn/tokens.css): фон neutral-15,
     текст neutral-100, вторичный neutral-60, линии neutral-25, акцент red-60
     с hover red-65 и pressed red-70. Шрифт Proxima Nova берётся, если установлен:
     страница самодостаточна и внешние шрифты не грузит (CSP). */
  :root{
    --bg:#f3f5f7; --panel:#fff; --ink:#1e2228; --muted:#667387; --line:#d7dae1;
    --accent:#e11b11; --accent-hover:#ae1603; --accent-pressed:#961500;
    --accent-soft:#fdedee; --warn:#fff4d6; --warn-line:#e3b341; --bad:#fdedee;
    --bad-line:#e11b11; --head:#f3f5f7; --ok:#009c37; --soft:#e6e8ed; --soft-hover:#d7dae1;
  }
  @media (prefers-color-scheme: dark){
    :root:not([data-theme="light"]){
      --bg:#0f1116; --panel:#171a21; --ink:#e6e8eb; --muted:#9aa4b2; --line:#2b303b;
      --accent:#f2564c; --accent-hover:#ff7a70; --accent-pressed:#d9463c;
      --accent-soft:#3b1e1e; --warn:#3a2f10; --warn-line:#8a6d1f; --bad:#3b1e1e;
      --bad-line:#f2564c; --head:#1f2430; --ok:#4ac26b; --soft:#232833; --soft-hover:#2b303b;
    }
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
       font:14px/1.5 "Proxima Nova","Segoe UI",Roboto,Helvetica,Arial,sans-serif}
  .wrap{max-width:1400px;margin:0 auto;padding:24px 18px 60px}
  h1{font-size:20px;margin:0 0 4px;font-weight:600}
  .sub{color:var(--muted);margin:0 0 20px}
  .panel{background:var(--panel);border:1px solid var(--line);border-radius:16px;
         padding:16px;margin-bottom:18px}
  #drop{border:2px dashed var(--line);border-radius:12px;padding:34px 18px;
        text-align:center;cursor:pointer;transition:.15s;background:var(--panel)}
  #drop:hover{border-color:var(--accent)}
  #drop.hot{border-color:var(--accent);background:var(--accent-soft)}
  #drop b{color:var(--accent)}
  .opts{display:flex;gap:18px;flex-wrap:wrap;align-items:center;margin-top:14px;
        color:var(--muted);font-size:13px}
  .opts input[type=number]{width:76px}
  .opts input,.opts select{background:var(--panel);color:var(--ink);
        border:1px solid var(--line);border-radius:8px;padding:4px 8px;font:inherit}
  .opts input:focus,.opts select:focus{outline:none;border-color:var(--accent)}
  .cards{display:flex;gap:10px;flex-wrap:wrap;margin:0 0 6px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:12px;
        padding:10px 14px;min-width:120px}
  .card .n{font-size:20px;font-weight:600}
  .card .l{color:var(--muted);font-size:12px}
  .card.bad .n{color:var(--bad-line)} .card.good .n{color:var(--ok)}
  .tabs{display:flex;gap:6px;flex-wrap:wrap;margin:4px 0 14px}
  .tab{padding:6px 12px;border:1px solid var(--line);border-radius:999px;
       background:var(--panel);cursor:pointer;font-size:13px}
  .tab:hover{border-color:var(--accent);color:var(--accent)}
  .tab.on{background:var(--accent);border-color:var(--accent);color:#fff}
  .tab.muted{opacity:.7;border-style:dashed}
  .warnbox{background:var(--warn);border:1px solid var(--warn-line);border-radius:8px;
           padding:12px;margin-bottom:14px;font-size:13px}
  .scroll{overflow:auto;max-height:72vh;min-height:300px;
          border:1px solid var(--line);border-radius:8px}
  table{border-collapse:collapse;font-size:12px;background:var(--panel)}
  td,th{border:1px solid var(--line);padding:4px 7px;vertical-align:middle;
        text-align:center;max-width:230px;white-space:nowrap}
  td.txt{white-space:normal;min-width:90px}
  td.num{text-align:right;font-variant-numeric:tabular-nums}
  td.txt{text-align:left}
  tr.hrow td{background:var(--head);font-weight:600}
  td.rev{background:var(--warn);outline:1px solid var(--warn-line)}
  tr.failed td{background:var(--bad)}
  .legend{display:flex;gap:16px;flex-wrap:wrap;color:var(--muted);font-size:12px;margin:8px 0}
  .sw{display:inline-block;width:11px;height:11px;border-radius:2px;margin-right:5px;
      vertical-align:-1px;border:1px solid var(--line)}
  .dl a{display:inline-block;margin:0 8px 8px 0;padding:6px 12px;border-radius:8px;font-weight:600;
        border:1px solid var(--line);text-decoration:none;color:var(--ink);
        background:var(--panel);font-size:13px}
  .dl a:hover{border-color:var(--accent);color:var(--accent)}
  .chk{width:100%;font-size:12px}
  .chk td,.chk th{text-align:left}
  .st-ok{color:var(--ok)} .st-failed{color:var(--bad-line);font-weight:600}
  #picked{display:none;align-items:center;gap:12px;flex-wrap:wrap;margin-top:14px;
          padding:10px 12px;border:1px solid var(--accent);border-radius:12px;color:var(--ink)}
  #picked .fname{font-weight:600;word-break:break-all}
  /* кнопки — как .btn-primary / .btn-ghost калькулятора (base.css) */
  #go,.handoff button{background:var(--accent);color:#fff;border:0;border-radius:12px;
      height:40px;padding:8px 16px;font:inherit;font-size:16px;line-height:22px;font-weight:600;
      cursor:pointer;transition:background-color .1s linear}
  #go:hover,.handoff button:hover{background:var(--accent-hover)}
  #go:active,.handoff button:active{background:var(--accent-pressed)}
  #go:disabled,.handoff button:disabled{background:var(--soft);color:var(--muted);cursor:default}
  #swap,#stop{background:var(--soft);color:var(--ink);border:0;border-radius:8px;height:32px;
        padding:6px 12px;font:inherit;font-size:14px;font-weight:600;cursor:pointer;
        transition:background-color .1s linear}
  #swap:hover,#stop:hover{background:var(--soft-hover)}
  #stop{color:var(--bad-line)}
  #busy{display:none;align-items:center;gap:12px}
  #stop:disabled{opacity:.5;cursor:default}
  .spin{width:18px;height:18px;border:2px solid var(--line);border-top-color:var(--accent);
        border-radius:50%;animation:sp .8s linear infinite}
  @keyframes sp{to{transform:rotate(360deg)}}
  .err{background:var(--bad);border:1px solid var(--bad-line);border-radius:8px;padding:12px;
       white-space:pre-wrap;font-family:ui-monospace,Consolas,monospace;font-size:12px}
  .note{color:var(--muted);font-size:12px;margin-top:6px}
  .handoff{display:flex;gap:14px;align-items:center;flex-wrap:wrap;
           border-color:var(--accent)}
  body.embed .sub{display:none}
  img.dbg{width:100%;border:1px solid var(--line);border-radius:8px;background:#fff}
  details summary{cursor:pointer;color:var(--accent);font-size:13px}
</style></head><body><div class="wrap">
<h1>Распознавание таблиц из проектных PDF</h1>
<p class="sub">Всё считается на этой машине. Файл никуда не отправляется.</p>

<div class="panel">
  <div id="drop">
    <div id="droptext" style="font-size:15px">Перетащите PDF сюда или <b>выберите файл</b></div>
    <div class="note">Спецификация металлопроката и подобные таблицы проектной документации.
      Распознавание начнётся только после нажатия «Распознать».</div>
    <input type="file" id="file" accept="application/pdf,.pdf" hidden>
  </div>
  <div id="picked">
    <span>Выбран файл: <span class="fname" id="fname"></span> <span id="fsize" class="note"></span></span>
    <button id="go" type="button" title="Начать распознавание выбранного файла">Распознать</button>
    <button id="swap" type="button" title="Выбрать другой файл вместо этого">Заменить файл</button>
    <span class="note">Проверьте файл и настройки ниже, затем нажмите «Распознать»</span>
  </div>
  <div class="opts">
    <label>Страницы <input id="pages" type="text" placeholder="все" size="8"></label>
    <label>DPI <input id="dpi" type="number" value="350" min="150" max="600" step="50"></label>
    <label>Порог проверки <input id="lowconf" type="number" value="0.62" min="0" max="1" step="0.02"></label>
    <label>OCR для сканов <select id="ocr">
      <option value="auto" selected>Авто — лучший доступный</option>
      <option value="hybrid">Гибрид (текст Tesseract + числа RapidOCR)</option>
      <option value="rapidocr">RapidOCR (без кириллицы)</option>
      <option value="tesseract">Tesseract</option>
      <option value="none">не использовать</option>
    </select></label>
    <span id="ocrhint" class="note"></span>
    <label><input id="allglyphs" type="checkbox"> трассировка по символам</label>
  </div>
  <div id="busy" class="opts"><div class="spin"></div><span id="busytext">Обработка…</span>
    <button id="stop" type="button" title="Прервать распознавание этого файла">Остановить</button></div>
  <div id="recent" class="note" style="margin-top:10px"></div>
</div>

<div id="out"></div>
</div>
<script>
const $ = s => document.querySelector(s);
const BASE = "__BASE_PATH__";
// Режим встраивания: страница открыта во фрейме калькулятора огнезащиты
// (или в окне, открытом из него). Результат передаётся туда postMessage'ом
// по явному нажатию кнопки — сама страница ничего никуда не шлёт.
const EMBED = new URLSearchParams(location.search).has("embed")
  || (window.parent && window.parent !== window) || !!window.opener;
if (EMBED) {
  document.body.classList.add("embed");
  // во фрейме калькулятора страница светлая, как и сам калькулятор
  document.documentElement.setAttribute("data-theme", "light");
}
function handoff(d){
  const target = (window.parent && window.parent !== window) ? window.parent : window.opener;
  if (!target) return;
  const payload = {
    type: "ocrpdf:result", job: d.job, filename: d.filename,
    report: {tables_found: d.report.tables_found, cells_non_empty: d.report.cells_non_empty,
             cells_low_confidence: d.report.cells_low_confidence,
             arithmetic_checks: d.report.arithmetic_checks, elapsed_sec: d.report.elapsed_sec},
    tables: d.tables.map(t => ({
      index: t.index, title: t.title, kind: t.kind, part: t.part, page: t.page,
      columns: t.columns, header_rows: t.header_rows, rows: t.rows, cells: t.cells,
      checks: t.checks,
    })),
  };
  target.postMessage(payload, "*");
}
const drop = $("#drop"), file = $("#file"), out = $("#out"), busy = $("#busy");

// какие OCR-движки установлены: недоступные помечаем и не даём выбрать
fetch(BASE + "/api/capabilities").then(r => r.json()).then(c => {
  const ocr = c.ocr || {};
  for (const [name, info] of Object.entries(ocr)) {
    const opt = document.querySelector(`#ocr option[value="${name}"]`);
    if (!opt) continue;
    if (!info.available) { opt.disabled = true; opt.textContent += " — не установлен"; }
  }
  // «Авто» берёт первый доступный в этом порядке — покажем, во что он развернётся
  const resolved = ["hybrid", "tesseract", "rapidocr"].find(n => (ocr[n] || {}).available);
  const label = {hybrid: "гибрид", tesseract: "Tesseract", rapidocr: "RapidOCR"}[resolved];
  let hint = resolved
    ? "авто = " + label + "; включается только для блоков, которые не удалось прочитать по векторам"
    : "ни один OCR-движок не установлен — авто равносильно «не использовать»";
  if (resolved === "rapidocr") hint += " (внимание: кириллицу не читает)";
  $("#ocrhint").textContent = hint;
});

drop.onclick = () => file.click();
drop.ondragover = e => { e.preventDefault(); drop.classList.add("hot"); };
drop.ondragleave = () => drop.classList.remove("hot");
drop.ondrop = e => {
  e.preventDefault(); drop.classList.remove("hot");
  if (e.dataTransfer.files.length) pick(e.dataTransfer.files[0]);
};
file.onchange = () => {
  if (file.files.length) pick(file.files[0]);
  file.value = "";              // иначе повторный выбор того же файла не даст события
};

// Двухшаговый сценарий: выбранный файл сначала показывается (имя, размер), а
// распознавание начинается только по кнопке «Распознать». Так ошибочно
// подгруженный файл можно заменить, не занимая очередь и не дожидаясь отмены.
const DROP_TEXT = $("#droptext").innerHTML;
let pending = null;
function fmtSize(n){
  return n < 1024 * 1024 ? Math.max(1, Math.round(n / 1024)) + " КБ" : (n / 1024 / 1024).toFixed(1) + " МБ";
}
function pick(f){
  if (!/\.pdf$/i.test(f.name)) { out.innerHTML = '<div class="err">Нужен файл PDF.</div>'; return; }
  pending = f;
  out.innerHTML = "";
  $("#fname").textContent = f.name;
  $("#fsize").textContent = "(" + fmtSize(f.size) + ")";
  $("#picked").style.display = "flex";
  $("#go").disabled = false;
  $("#droptext").innerHTML = 'Чтобы заменить файл, перетащите другой PDF сюда или <b>выберите файл</b>';
}
function clearPick(){
  pending = null;
  $("#picked").style.display = "none";
  $("#droptext").innerHTML = DROP_TEXT;
}
$("#go").onclick = () => { if (pending) send(pending); };
$("#swap").onclick = e => { e.stopPropagation(); file.click(); };

function send(f){
  if (!/\.pdf$/i.test(f.name)) { out.innerHTML = '<div class="err">Нужен файл PDF.</div>'; return; }
  clearPick();
  const fd = new FormData();
  fd.append("file", f);
  fd.append("pages", $("#pages").value);
  fd.append("dpi", $("#dpi").value);
  fd.append("low_conf", $("#lowconf").value);
  fd.append("all_glyphs", $("#allglyphs").checked ? "1" : "0");
  fd.append("ocr", $("#ocr").value);
  out.innerHTML = "";
  busy.style.display = "flex";
  $("#busytext").textContent = "Обработка «" + f.name + "» — от 10 с до 2–3 минут на страницу…";
  const t0 = Date.now();
  api("/api/extract", fd)
    .then(({ok, j}) => {
      if (j.job && !j.report) return pollJob(j.job, t0);
      return finish(ok, j, t0);
    })
    .catch(e => fail(e));
}

const JOB_KEY = "ocrpdf_job";
function delay(ms){ return new Promise(r => setTimeout(r, ms)); }

// Остановка: сервер выставляет флаг, конвейер прерывается на ближайшей
// границе этапа (страница / блок / вызов OCR), статус становится cancelled.
let currentJob = null, stopping = false;
$("#stop").onclick = () => {
  if (!currentJob || stopping) return;
  stopping = true;
  $("#stop").disabled = true;
  $("#busytext").textContent = "Останавливаю…";
  api("/api/job/" + currentJob + "/cancel", new FormData()).catch(() => {});
};
function setJob(job){
  currentJob = job; stopping = false;
  $("#stop").disabled = !job;
}
function api(url, body){
  const opts = {credentials: "include", cache: "no-store",
                headers: {"X-Pinggy-No-Screen": "true"}};
  if (body !== undefined) { opts.method = "POST"; opts.body = body; }
  return fetch(BASE + url, opts).then(parseJson);
}

function parseJson(r){
  return r.text().then(t => {
    let j;
    try { j = JSON.parse(t); }
    catch {
      throw new Error("туннель вернул не JSON — откройте ссылку заново, "
        + "нажмите Enter site на странице pinggy и повторите");
    }
    return {ok: r.ok, status: r.status, j};
  });
}

function pollJob(job, t0){
  try { sessionStorage.setItem(JOB_KEY, job); } catch (e) {}
  setJob(job);
  let fails = 0, queued = 0;
  const tick = () => {
    const sec = Math.round((Date.now() - t0) / 1000);
    $("#busytext").textContent = stopping
      ? "Останавливаю… " + sec + " с"
      : fails
        ? "Туннель моргнул, забираю результат… " + sec + " с"
        : queued
          ? "В очереди: перед вами " + queued + (queued === 1 ? " задание" : " задания")
            + " — сервис считает их по одному… " + sec + " с"
          : "Считаем… " + sec + " с";
    return api("/api/job/" + job).then(({ok, j}) => {
      fails = 0;
      if (j.status === "running" || j.status === "cancelling"
          || (j.status === "done" && !j.report)) {
        queued = (j.status === "running" && j.queue_ahead) || 0;
        // Лимит времени держит сервер (см. OCRPDF_MAX_SEC_PER_PAGE); здесь
        // только страховка от вечного опроса.
        if (sec > 5400) return fail(new Error("обработка дольше полутора часов"), job);
        return delay(1500).then(tick);
      }
      try { sessionStorage.removeItem(JOB_KEY); } catch (e) {}
      return finish(ok, j, t0);
    }).catch(e => {
      fails++;
      if (fails <= 30 && sec < 5400) return delay(2000).then(tick);
      return recover(job, t0, e);
    });
  };
  return tick();
}

function recover(job, t0, e){
  $("#busytext").textContent = "Проверяю, не готов ли уже результат…";
  return api("/api/job/" + job).then(({ok, j}) => {
    if (j && j.report) {
      try { sessionStorage.removeItem(JOB_KEY); } catch (ex) {}
      return finish(true, j, t0);
    }
    return fail(e, job);
  }).catch(() => fail(e, job));
}

function finish(ok, j, t0){
  busy.style.display = "none";
  setJob(null);
  if (j && j.status === "cancelled") {
    out.innerHTML = '<div class="warnbox"><b>Распознавание остановлено.</b> '
      + 'Результат не сохранён; файл можно загрузить снова.</div>';
    loadRecent();
    return;
  }
  if (!ok || j.error) {
    out.innerHTML = '<div class="err">' + esc(j.error || "Ошибка")
      + (j.trace ? "\n\n" + esc(j.trace) : "") + '</div>';
    return;
  }
  render(j, (Date.now() - t0) / 1000);
}

function fail(e, job){
  busy.style.display = "none";
  setJob(null);
  const msg = String(e && e.message || e);
  let hint = /fetch|network|Failed/i.test(msg)
    ? "Связь с туннелем оборвалась, но файл мог уже посчитаться. Обновите страницу (Ctrl+F5) и откройте задание из списка ниже — повторно загружать PDF не нужно."
    : msg;
  if (job) hint += "\nзадание: " + job;
  out.innerHTML = '<div class="err">' + esc(hint) + '</div>';
}

function loadRecent(){
  api("/api/recent").then(({j}) => {
    const jobs = (j && j.jobs) || [];
    if (!jobs.length) { $("#recent").innerHTML = ""; return; }
    $("#recent").innerHTML = "Последние задания (лежат 6 часов, повторно грузить не нужно): "
      + jobs.map(x => {
          const name = esc(x.filename || x.job.slice(0, 8));
          const st = x.status === "done" ? "готово"
            : x.status === "running" ? (x.phase === "queued" ? "в очереди" : "считается")
            : x.status === "cancelling" ? "останавливается"
            : x.status === "cancelled" ? "остановлено"
            : x.status === "error" ? "ошибка" : esc(x.status);
          return '<a href="#" data-job="'+x.job+'">'+name+"</a> ("+st+")";
        }).join(" · ");
  }).catch(() => {});
}
$("#recent").onclick = e => {
  const a = e.target.closest && e.target.closest("a[data-job]");
  if (!a) return;
  e.preventDefault();
  out.innerHTML = "";
  busy.style.display = "flex";
  $("#busytext").textContent = "Открываю задание…";
  pollJob(a.getAttribute("data-job"), Date.now());
};
loadRecent();

try {
  const pending = sessionStorage.getItem(JOB_KEY);
  if (pending && /^[0-9a-f]{32}$/.test(pending)) {
    busy.style.display = "flex";
    $("#busytext").textContent = "Забираю предыдущее задание…";
    pollJob(pending, Date.now());
  }
} catch (e) {}

const esc = s => String(s == null ? "" : s)
  .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
const nl = s => esc(s).replace(/\n/g,"<br>");

function render(d, secs){
  const rep = d.report, ac = rep.arithmetic_checks;
  const cards = [
    ["Таблиц", rep.tables_found, ""],
    ["Ячеек с данными", rep.cells_non_empty, ""],
    ["Проверок пройдено", ac.passed, "good"],
    ["Проверок не пройдено", ac.failed, ac.failed ? "bad" : "good"],
    ["На ручную проверку", rep.cells_low_confidence, rep.cells_low_confidence ? "" : "good"],
    ["Время, с", rep.elapsed_sec, ""],
  ].map(([l,n,c]) => `<div class="card ${c}"><div class="n">${esc(n)}</div><div class="l">${esc(l)}</div></div>`).join("");

  const pages = rep.pages.map(p => `<div class="note">стр. ${p.number}: ${esc(p.content_kind)},
      текстовый слой: ${esc(p.text_layer)}, линий линовки: ${p.n_ruling_lines},
      векторных глифов: ${p.n_vector_glyphs}</div>`).join("");
  const notes = rep.pages.flatMap(p => p.notes).map(n => `<div class="note">— ${esc(n)}</div>`).join("");

  // читаемые таблицы первыми, нераспознанные блоки — в конец
  const order = d.tables.map((t,i) => i)
    .sort((a,b) => (d.tables[a].kind==="unreadable") - (d.tables[b].kind==="unreadable"));
  const tabs = order.map((i,k) => {
    const t = d.tables[i];
    const bad = t.kind === "unreadable";
    return `<div class="tab ${k?"":"on"}${bad?" muted":""}" data-i="${i}">`
      + esc(t.title)
      + (t.part ? " · " + esc(t.part) : "")
      + (t.page ? " · стр. " + t.page : "")
      + (bad ? ' <b style="opacity:.75">· не распознано</b>' : "") + "</div>";
  }).join("");

  const dl = ['<div class="dl">'].concat(
    d.tables.flatMap(t => t.files.map(f =>
      `<a href="${BASE}/api/file/${d.job}/${f}" download>${esc(f)}</a>`)),
    [`<a href="${BASE}/api/file/${d.job}/processing_report.json" download>processing_report.json</a>`],
    d.debug_images.map(f => `<a href="${BASE}/api/file/${d.job}/${f}" download>${esc(f)}</a>`),
    ["</div>"]).join("");

  const readable = d.tables.filter(t => t.kind !== "unreadable").length;
  const hand = !EMBED ? "" : `<div class="panel handoff">
      <button id="handoff" ${readable ? "" : "disabled"}>Передать в калькулятор огнезащиты</button>
      <span class="note">${readable
        ? `Таблиц для импорта: ${readable}. Спорные значения останутся помеченными — их можно проверить в форме.`
        : "Распознанных таблиц нет — передавать нечего."}</span></div>`;
  out.innerHTML = hand + `<div class="cards">${cards}</div><div class="panel">${pages}
      <details><summary>Как разобран документ</summary>${notes}</details></div>
    <div class="panel">${dl}</div>
    <div class="tabs">${tabs}</div><div id="tv"></div>
    <div class="panel"><div class="note">Отладочное изображение страницы: рамки таблиц, ячейки,
      объединённые ячейки, спорные значения и строки с расхождением в арифметике</div>
      ${d.debug_images.map(f=>`<img class="dbg" src="${BASE}/api/file/${d.job}/${f}">`).join("")}</div>`;

  const show = i => {
    document.querySelectorAll(".tab").forEach(el =>
      el.classList.toggle("on", +el.dataset.i === i));
    $("#tv").innerHTML = tableView(d.tables[i]);
  };
  document.querySelectorAll(".tab").forEach(el => el.onclick = () => show(+el.dataset.i));
  show(order[0]);
  const hb = $("#handoff");
  if (hb) hb.onclick = () => { handoff(d); hb.textContent = "Передано ✓"; };
}

function tableView(t){
  const failed = new Set(t.checks.filter(c=>c.status==="failed").map(c=>c.row));
  // сетка как на чертеже: rowspan/colspan из объединённых ячеек
  const skip = new Set(), at = new Map();
  for (const c of t.cells){
    at.set(c.r+":"+c.c, c);
    for (let r=c.r; r<c.r+c.rs; r++)
      for (let k=c.c; k<c.c+c.cs; k++)
        if (r!==c.r || k!==c.c) skip.add(r+":"+k);
  }
  let body = "";
  for (let r=0; r<t.n_rows; r++){
    const cls = [t.header_rows.includes(r)?"hrow":"", failed.has(r)?"failed":""].join(" ").trim();
    let tds = "";
    for (let c=0; c<t.n_cols; c++){
      if (skip.has(r+":"+c)) continue;
      const cell = at.get(r+":"+c);
      if (!cell){ tds += "<td></td>"; continue; }
      const span = (cell.rs>1?` rowspan="${cell.rs}"`:"") + (cell.cs>1?` colspan="${cell.cs}"`:"");
      const kind = cell.k==="number"||cell.k==="int" ? "num" : "txt";
      const title = [`строка ${cell.r}, колонка ${cell.c}`,
        `источник: ${cell.src}`, `confidence: ${cell.conf}`]
        .concat(cell.notes||[]).join("\n");
      tds += `<td${span} class="${kind}${cell.rev?" rev":""}" title="${esc(title)}">${nl(cell.t)}</td>`;
    }
    body += `<tr class="${cls}">${tds}</tr>`;
  }
  const checks = t.checks.filter(c=>c.status!=="skipped").map(c=>
    `<tr><td>${c.row<0?"—":c.row}</td><td>${esc(c.kind)}</td><td>${esc(c.column)}</td>
      <td class="num">${c.expected==null?"":c.expected}</td>
      <td class="num">${c.calculated==null?"":c.calculated}</td>
      <td class="num">${c.delta==null?"":c.delta}</td>
      <td class="num">${c.tolerance}</td>
      <td class="st-${c.status}">${esc(c.status)}</td><td>${esc(c.reason)}</td></tr>`).join("");

  const notice = t.kind !== "unreadable" ? "" : `<div class="warnbox">
      <b>Содержимое этого блока распознать не удалось.</b>
      Сетка ${t.n_rows} x ${t.n_cols} найдена, но значений в ней нет или почти нет.
      ${(t.notes||[]).map(n=>"<div>— "+esc(n)+"</div>").join("")}
      <div style="margin-top:6px">Что делать: если таблица вставлена в PDF как
      картинка (скан), включите OCR в настройках выше и загрузите файл снова.
      Если это штамп или боковая графа листа с повёрнутым текстом — так и должно
      быть, данных там нет.</div></div>`;
  return `<div class="panel">${notice}
    <div class="legend">
      <span><i class="sw" style="background:var(--head)"></i>шапка</span>
      <span><i class="sw" style="background:var(--warn);border-color:var(--warn-line)"></i>на ручную проверку</span>
      <span><i class="sw" style="background:var(--bad);border-color:var(--bad-line)"></i>расхождение в арифметике</span>
      <span>наведите курсор на ячейку — источник, confidence, замечания</span>
    </div>
    <div class="scroll"><table>${body}</table></div>
    <details style="margin-top:14px"><summary>Арифметические проверки (${t.checks.length})</summary>
      <div class="scroll" style="max-height:40vh;margin-top:8px"><table class="chk">
      <tr><th>строка</th><th>проверка</th><th>колонка</th><th>в PDF</th><th>пересчёт</th>
          <th>разница</th><th>допуск</th><th>статус</th><th>причина</th></tr>
      ${checks}</table></div></details>
  </div>`;
}
</script></body></html>
"""


# --------------------------------------------------------------------------- #
#  HTTP
# --------------------------------------------------------------------------- #
class Server(ThreadingHTTPServer):
    """HTTP-сервер: на Windows не переиспользуем адрес, на Linux — да.

    В `socketserver` по умолчанию стоит `allow_reuse_address = 1`. На Windows
    это работает как SO_REUSEPORT: второй экземпляр молча занимает тот же порт,
    а запросы начинают уходить к последнему забиндившемуся. Поэтому на NT
    лучше падать с явной ошибкой «порт занят».

    На Linux SO_REUSEADDR только даёт занять сокет в TIME_WAIT после падения
    (OOM-kill). Без этого процесс уходит на запасной порт, а nginx продолжает
    стучаться в старый → 502.
    """
    allow_reuse_address = os.name != "nt"
    daemon_threads = True


class Handler(BaseHTTPRequestHandler):
    server_version = "ocrpdf-webapp"
    protocol_version = "HTTP/1.1"
    base_path = ""

    def log_message(self, fmt, *args):          # компактный лог
        print("  %s - %s" % (self.address_string(), fmt % args), flush=True)

    def _route(self) -> str | None:
        return app_path(unquote(self.path.split("?")[0]), self.base_path)

    def _redirect(self, location: str) -> None:
        self.send_response(301)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        self.end_headers()

    def _page(self) -> bytes:
        return page_html(self.base_path or forwarded_prefix(self.headers)).encode("utf-8")

    def _send(self, code: int, body: bytes, ctype: str,
              extra: dict[str, str] | None = None) -> None:
        extra = dict(extra or {})
        accept = (self.headers.get("Accept-Encoding") or "").lower()
        if "gzip" in accept and len(body) > 512:
            body = gzip.compress(body, 6)
            extra["Content-Encoding"] = "gzip"
        extra.setdefault("Cache-Control", "no-store")
        extra.setdefault("X-Robots-Tag", "noindex, nofollow")
        origin = self.headers.get("Origin") if self.headers is not None else None
        if origin:
            extra.setdefault("Access-Control-Allow-Origin", origin)
            extra.setdefault("Vary", "Origin")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if ctype.startswith("text/html"):
            extra.setdefault("Cache-Control", "no-store")
        # страница самодостаточна: запрещаем любые внешние ресурсы
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; img-src 'self' data:; "
                         "style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                         "connect-src 'self'")
        for k, v in extra.items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, OSError):
            pass

    def _json(self, code: int, payload: dict) -> None:
        self._send(code, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin") or "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers",
                         "X-Pinggy-No-Screen, Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_HEAD(self) -> None:
        path = self._route()
        if path is None:
            self.send_error(404)
            return
        if path == "":
            self._redirect((self.base_path or "") + "/")
            return
        if path in ("/", "/index.html", "/healthz"):
            self._send(200, b"", "text/html; charset=utf-8" if path != "/healthz"
                       else "application/json; charset=utf-8")
            return
        self.send_error(404)

    def do_GET(self) -> None:
        path = self._route()
        if path is None:
            self._json(404, {"error": "не найдено"})
            return
        if path == "":
            self._redirect((self.base_path or "") + "/")
            return
        if path in ("/", "/index.html"):
            self._send(200, self._page(), "text/html; charset=utf-8")
            return
        if path == "/healthz":
            self._json(200, {"status": "ok"})
            return
        m = re.fullmatch(r"/api/file/([0-9a-f]{32})/(.+)", path)
        if m:
            self._serve_file(m.group(1), m.group(2))
            return
        if path == "/api/capabilities":
            self._json(200, {"ocr": ocr_capabilities()})
            return
        if path == "/api/recent":
            self._json(200, {"jobs": _recent_jobs()})
            return
        m = re.fullmatch(r"/api/job/([0-9a-f]{32})", path)
        if m:
            self._serve_envelope(m.group(1))
            return
        self._json(404, {"error": "не найдено"})

    def _serve_envelope(self, job: str) -> None:
        """Статус задания: running / готовый envelope / ошибка."""
        if not JOB_ID.fullmatch(job):
            self._json(400, {"error": "недопустимый идентификатор задания"})
            return
        job_dir = os.path.join(_jobs_root, job)
        env_path = os.path.join(job_dir, "envelope.json")
        if os.path.isfile(env_path):
            with open(env_path, "rb") as fh:
                self._send(200, fh.read(), "application/json; charset=utf-8")
            return
        st_path = os.path.join(job_dir, "status.json")
        if os.path.isfile(st_path):
            with open(st_path, encoding="utf-8") as fh:
                payload = json.load(fh)
            payload["job"] = job
            status = payload.get("status")
            if status == "running":
                pos = queue_ahead(job)
                payload["queue_ahead"] = pos or 0
                if pos:
                    payload["phase"] = "queued"
            # cancelled — окончательное состояние (200), cancelling/running — ждём (202)
            code = 500 if status == "error" else (200 if status == "cancelled" else 202)
            self._json(code, payload)
            return
        self._json(404, {"error": "задание не найдено или уже удалено"})

    def _serve_file(self, job: str, name: str) -> None:
        # защита от выхода за каталог задания
        if not JOB_ID.fullmatch(job) or not SAFE_NAME.fullmatch(name):
            self._json(400, {"error": "недопустимое имя"})
            return
        path = os.path.join(_jobs_root, job, "result", name)
        if not os.path.isfile(path):
            self._json(404, {"error": "файл не найден"})
            return
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        with open(path, "rb") as fh:
            data = fh.read()
        inline = name.lower().endswith(".png")
        self._send(200, data, ctype,
                   {"Content-Disposition": "%s; filename=\"%s\""
                    % ("inline" if inline else "attachment", name)})

    def do_POST(self) -> None:
        route = self._route() or ""
        m = re.fullmatch(r"/api/job/([0-9a-f]{32})/cancel", route)
        if m:
            state = request_cancel(m.group(1))
            if state == "cancelling":
                self._json(202, {"job": m.group(1), "status": "cancelling"})
            elif state == "finished":
                self._json(409, {"job": m.group(1), "error": "задание уже завершено"})
            else:
                self._json(404, {"error": "задание не найдено"})
            return
        if route != "/api/extract":
            self._json(404, {"error": "не найдено"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            self._json(400, {"error": "пустой запрос"})
            return
        if length > MAX_UPLOAD:
            self._json(413, {"error": "файл больше %d МБ" % (MAX_UPLOAD // 1024 // 1024)})
            return

        body = b""
        while len(body) < length:
            chunk = self.rfile.read(min(1 << 20, length - len(body)))
            if not chunk:
                break
            body += chunk

        fields = parse_multipart(body, self.headers.get("Content-Type", ""))
        if "file" not in fields or not fields["file"][1]:
            self._json(400, {"error": "не передан файл в поле 'file'"})
            return
        fname, data = fields["file"]
        if not data.startswith(b"%PDF"):
            self._json(400, {"error": "это не PDF (нет подписи %PDF)"})
            return

        def text(key: str, default: str = "") -> str:
            v = fields.get(key)
            return v[1].decode("utf-8", "replace").strip() if v else default

        try:
            ocr = text("ocr", "none") or "none"
            if ocr not in ("none", "auto", "hybrid", "rapidocr", "tesseract"):
                ocr = "none"
            opts = Options(
                dpi=max(150, min(600, int(text("dpi", "350") or 350))),
                low_conf=max(0.0, min(1.0, float(text("low_conf", "0.62") or 0.62))),
                pages=text("pages"),
                all_glyphs=text("all_glyphs") == "1",
                ocr_backend=ocr,
            )
        except ValueError:
            self._json(400, {"error": "некорректные параметры обработки"})
            return

        n_pages = count_pages(data)
        n_sel, limit_err = page_limit_error(n_pages, opts.pages)
        if limit_err:
            self._json(413 if n_sel > MAX_PAGES else 400,
                       {"error": limit_err, "pages_in_document": n_pages,
                        "max_pages": MAX_PAGES})
            return

        started = time.time()
        job = _prepare_job(fname or "input.pdf", data)
        print("  задание %s: %r (%.1f МБ, %d стр. из %d)"
              % (job, fname, len(data) / 1048576, n_sel, n_pages), flush=True)

        def worker(_job=job, _fname=fname, _opts=opts, _t0=started, _n=n_sel):
            env = _run_job(_job, _fname or "input.pdf", _opts, _n)
            if env is not None:
                print("  готово %s за %.1f с, таблиц: %d"
                      % (_job, time.time() - _t0, env["report"]["tables_found"]),
                      flush=True)

        threading.Thread(target=worker, daemon=True).start()
        self._json(202, {"job": job, "status": "running"})


DEFAULT_PORT = 8000
# Запасные порты. На Windows часть диапазонов зарезервирована Hyper-V/WSL
# (`netsh interface ipv4 show excludedportrange protocol=tcp`), и bind падает
# с WinError 10013 — «запрещено правами доступа», хотя порт свободен.
FALLBACK_PORTS = (8000, 7860, 3000, 8010, 8181, 5055, 4321)


def serve(host: str = "127.0.0.1", port: int = DEFAULT_PORT,
          open_browser: bool = False, base_path: str = "") -> None:
    Handler.base_path = normalize_base_path(base_path)
    # За reverse proxy порт фиксирован (nginx → 8090). Запасные 7860/8000
    # делают процесс «живым», пока сайт отдаёт 502.
    if Handler.base_path:
        candidates = [port]
    else:
        candidates = [port] + [p for p in FALLBACK_PORTS if p != port]
    httpd = None
    for candidate in candidates:
        try:
            httpd = Server((host, candidate), Handler)
        except OSError as exc:
            if Handler.base_path:
                print("порт %d недоступен (%s) — за reverse proxy запасной порт не берём"
                      % (candidate, exc.errno), flush=True)
            else:
                print("порт %d недоступен (%s), пробую следующий" % (candidate, exc.errno),
                      flush=True)
            continue
        port = candidate
        break
    if httpd is None:
        raise SystemExit("не удалось занять ни один порт из %s" % (candidates,))
    prefix = Handler.base_path or ""
    url = "http://%s:%d%s/" % (host, port, prefix)
    orphans = _mark_orphaned_jobs()
    if orphans:
        print("незавершённых заданий с прошлого запуска: %d — помечены ошибкой" % orphans,
              flush=True)
    print("Интерфейс: %s   (Ctrl+C — остановить)" % url, flush=True)
    print("Задания хранятся в %s и удаляются через %d ч"
          % (_jobs_root, JOB_TTL_SEC // 3600), flush=True)
    if open_browser:
        import webbrowser
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nостановлено")
    finally:
        httpd.server_close()
