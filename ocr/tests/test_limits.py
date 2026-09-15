# -*- coding: utf-8 -*-
"""Пределы веб-сервиса: страницы на задание, время на задание, очередь.

Зачем: сервис выполняет задания по одному, и без пределов один альбом на сорок
листов остановил бы очередь для всех пользователей сайта. Второе задание раньше
показывало «Считаем…», хотя просто ждало первого.
"""
from __future__ import annotations

import json
import threading
import time

from ocrpdf import webapp
from ocrpdf.pdfbackend import fitz
from ocrpdf.pipeline import Cancelled


def _pdf(n_pages: int) -> bytes:
    doc = fitz.open()
    for _ in range(n_pages):
        doc.new_page()
    return doc.tobytes()


def test_count_pages_and_garbage():
    assert webapp.count_pages(_pdf(12)) == 12
    assert webapp.count_pages(b"%PDF-1.4 garbage") == 0


def test_page_limit(monkeypatch):
    monkeypatch.setattr(webapp, "MAX_PAGES", 10)
    n, err = webapp.page_limit_error(12, "")
    assert n == 12 and "не больше 10" in err and "Страницы" in err
    n, err = webapp.page_limit_error(12, "1-3")
    assert (n, err) == (3, "")
    n, err = webapp.page_limit_error(12, "1-11")
    assert n == 11 and "выбрано 11" in err
    n, err = webapp.page_limit_error(0, "")
    assert n == 0 and "не удалось открыть" in err
    n, err = webapp.page_limit_error(5, "abc")
    assert n == 0 and "Страницы" in err
    n, err = webapp.page_limit_error(5, "9-12")
    assert n == 0 and "нет ни одной" in err


def test_budget_scales_with_pages(monkeypatch):
    monkeypatch.setattr(webapp, "MAX_SEC_PER_PAGE", 300.0)
    monkeypatch.setattr(webapp, "MIN_JOB_SEC", 600.0)
    assert webapp.job_budget_sec(1) == 600.0
    assert webapp.job_budget_sec(4) == 1200.0


def _fake_envelope(job, filename, report, out_dir):
    return {"job": job, "report": report}


def test_time_limit_marks_error(monkeypatch, tmp_path):
    monkeypatch.setattr(webapp, "_jobs_root", str(tmp_path))
    monkeypatch.setattr(webapp, "MAX_SEC_PER_PAGE", 0.2)
    monkeypatch.setattr(webapp, "MIN_JOB_SEC", 0.2)
    monkeypatch.setattr(webapp, "_build_envelope", _fake_envelope)

    def slow_run(src, out_dir, opts):
        # конвейер: проверяет флаг между этапами
        for _ in range(500):
            if opts.should_cancel():
                raise Cancelled("остановлено")
            time.sleep(0.01)
        return {"tables_found": 0}

    monkeypatch.setattr(webapp, "run", slow_run)
    job = webapp._prepare_job("a.pdf", b"%PDF-1.4")
    assert webapp._run_job(job, "a.pdf", webapp.Options(), n_pages=1) is None
    st = json.loads((tmp_path / job / "status.json").read_text(encoding="utf-8"))
    assert st["status"] == "error" and "лимит времени" in st["error"]
    assert webapp.queue_ahead(job) is None


def test_user_cancel_is_not_a_timeout(monkeypatch, tmp_path):
    monkeypatch.setattr(webapp, "_jobs_root", str(tmp_path))
    monkeypatch.setattr(webapp, "_build_envelope", _fake_envelope)

    def run_then_cancel(src, out_dir, opts):
        webapp.request_cancel(job)
        if opts.should_cancel():
            raise Cancelled("остановлено")
        return {"tables_found": 0}

    monkeypatch.setattr(webapp, "run", run_then_cancel)
    job = webapp._prepare_job("a.pdf", b"%PDF-1.4")
    assert webapp._run_job(job, "a.pdf", webapp.Options()) is None
    st = json.loads((tmp_path / job / "status.json").read_text(encoding="utf-8"))
    assert st["status"] == "cancelled"


def test_queue_position_visible(monkeypatch, tmp_path):
    monkeypatch.setattr(webapp, "_jobs_root", str(tmp_path))
    monkeypatch.setattr(webapp, "_build_envelope", _fake_envelope)
    release = threading.Event()

    def blocking_run(src, out_dir, opts):
        release.wait(5)
        return {"tables_found": 0}

    monkeypatch.setattr(webapp, "run", blocking_run)
    first = webapp._prepare_job("a.pdf", b"%PDF-1.4")
    second = webapp._prepare_job("b.pdf", b"%PDF-1.4")
    t1 = threading.Thread(target=webapp._run_job, args=(first, "a.pdf", webapp.Options()))
    t1.start()
    time.sleep(0.1)
    t2 = threading.Thread(target=webapp._run_job, args=(second, "b.pdf", webapp.Options()))
    t2.start()
    time.sleep(0.2)
    assert webapp.queue_ahead(first) == 0
    assert webapp.queue_ahead(second) == 1
    st1 = json.loads((tmp_path / first / "status.json").read_text(encoding="utf-8"))
    st2 = json.loads((tmp_path / second / "status.json").read_text(encoding="utf-8"))
    assert st1["phase"] == "processing" and st2["phase"] == "queued"
    recent = {r["job"]: r for r in webapp._recent_jobs()}
    assert recent[second]["phase"] == "queued" and recent[first]["phase"] == "processing"
    release.set()
    t1.join(5)
    t2.join(5)
    assert webapp.queue_ahead(first) is None and webapp.queue_ahead(second) is None
    for j in (first, second):
        assert '"done"' in (tmp_path / j / "status.json").read_text(encoding="utf-8")
