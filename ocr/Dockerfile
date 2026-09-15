# syntax=docker/dockerfile:1.7
# OCR-сервис ocrpdf: страница и API распознавания таблиц ИД (порт 8000).
# nginx фронтенда ОЗМ проксирует /ocr/ -> ocr:8000/ (см. frontend/nginx.conf).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# tesseract-ocr — бинарник (языковые файлы rus/eng/osd лежат в ./tessdata и
# подхватываются кодом через TESSDATA_PREFIX); libgl1/libglib2.0 — для opencv;
# fonts-liberation/dejavu — запасные референсные шрифты для шаблонов глифов
# (чертёжные ISOCPEUR/GOST монтируются с хоста, см. docker-compose.local.yml).
RUN apt-get update && apt-get install -y --no-install-recommends \
      tesseract-ocr libgl1 libglib2.0-0 libgomp1 \
      fonts-liberation fonts-dejavu-core curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
# Растровый OCR обязателен в контейнере: листы без текстового слоя иначе не читаются.
RUN pip install -r requirements.txt \
      "rapidocr-onnxruntime>=1.4,<2" \
      "pytesseract>=0.3.10"

COPY . .

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=5 --start-period=30s \
  CMD curl -fsS http://127.0.0.1:8000/api/capabilities >/dev/null || exit 1

# --host 0.0.0.0: сервер виден только внутри сети compose; наружу порт
# публикуется как 127.0.0.1:8000 (аутентификации у сервиса нет).
CMD ["python", "webapp.py", "--host", "0.0.0.0", "--port", "8000"]
