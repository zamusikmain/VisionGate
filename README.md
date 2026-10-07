# VisionGate — Barcode Quality Gate

**[Русский](#русский)** · **[English](#english)**

---

# Русский

**VisionGate — система проверки качества фотографий штрихкодов.** Детерминированный CV-конвейер на OpenCV и
ZXing-C++, веб-интерфейс на React, API, история и офлайн-калибровка порогов. В репозитории также есть
экспериментальный профиль для фотографий коробок устройств с наклейками (OCR на ONNX-моделях, пакетная проверка,
выгрузка XLSX).

> Начальные пороги требуют калибровки на реальных фото целевой предметной области. Синтетические проверки не
> доказывают качество на настоящих наклейках.

## 1. Что это и зачем

Оператор фотографирует наклейку со штрихкодом (камерой или загрузкой файла). Система находит и декодирует штрихкод,
измеряет резкость, освещённость, контраст, размер и ориентацию области кода и отвечает **ACCEPT** или **RETAKE** с
понятной инструкцией на RU/EN, что исправить.

## 2. Возможности

- Анализ одного фото: валидация входа → детекция и декодирование → метрики области кода → решение.
- Форматы штрихкодов (ZXing-C++): Code 128, Code 39, EAN-13/8, UPC-A/E, ITF, QR, Data Matrix.
- Решения ACCEPT / RETAKE с инструкциями на русском и английском.
- Камера с подсказками кадрирования, загрузка JPEG/PNG/WEBP (с нормализацией EXIF); HEIC/HEIF и анимация — понятный
  отказ.
- Админ-панель порогов (по `ADMIN_TOKEN`): описание параметров, редактирование, сброс, аудит.
- История анализов (только метрики, версии и время, без оригиналов и декодированных значений).
- Офлайн-калибровка порогов по набору фото, отчёты JSON/CSV/HTML.
- Экспериментальный профиль для фото коробок устройств: OCR, штрихкоды, пакетная проверка, выгрузка XLSX.
- Ограничение параллельных анализов (`MAX_CONCURRENT_ANALYSES`), перегрузка → 503 BUSY.

## 3. Стек технологий

| Слой | Технологии |
| --- | --- |
| Backend | Python 3.13, FastAPI, Uvicorn, Pydantic + pydantic-settings, python-multipart |
| CV | OpenCV 5 (headless), Pillow, ZXing-C++ 3.1 |
| OCR (экспериментальный профиль) | ONNX Runtime, публичные модели PP-OCRv5, pyclipper |
| Экспорт | openpyxl (XLSX) |
| Frontend | React 19, TypeScript, Vite; Vitest + Testing Library |
| Хранилище | SQLite (история), JSON-конфигурация порогов |
| Инфраструктура | Docker Compose (backend + Nginx), Render (`render.yaml`, `Dockerfile.render`) |
| Тесты | pytest, Vitest |

## 4. Архитектура

```text
Image Input → Validation → Detection/Decode → ROI Metrics → Decision Engine → Typed Result
```

- Метрики — в `backend/gate/metrics`. Decision Engine принимает типизированные объекты и не зависит от OpenCV.
- `BarcodeDecoder` заменяемый. Кандидат без успешного декодирования никогда не принимается.
- Frontend собирается в статику и обслуживается непривилегированным Nginx; backend — Uvicorn без reload.

## 5. Структура проекта

```text
backend/main.py, render_app.py   FastAPI-приложение и единый origin для Render
backend/gate/                    конвейер, декодер, метрики, решения, конфигурация, OCR, хранилище
frontend/src/                    интерфейс, камера, загрузка, i18n, API
tools/                           demo, calibrate, dataset_audit, barcode_stress, release_check и утилиты профиля коробок
experiments/                     прототип Barcode Integrity
config/                          thresholds.json и настройки моделей
deploy/                          start.sh, уведомление о лицензиях моделей
tests/                           pytest
docs/                            алгоритм, калибровка, API, деплой, мобильная камера, проверки
```

## 6. API

| Метод и путь | Назначение |
| --- | --- |
| `GET /api/v1/health` | Проверка здоровья |
| `GET /api/v1/capabilities` | Возможности сборки |
| `POST /api/v1/analyze` | Анализ фото штрихкода → ACCEPT / RETAKE |
| `GET /api/v1/config`, `PUT /api/v1/config` | Пороги (изменение — по `ADMIN_TOKEN`) |
| `GET /api/v1/history` | История анализов (по `ADMIN_TOKEN`) |

OpenAPI: `/docs`. Подробно: [docs/api.md](docs/api.md).

## 7. Конфигурация

| Переменная | По умолчанию | Назначение |
| --- | --- | --- |
| `ADMIN_TOKEN` | — | Ключ для изменения порогов и истории |
| `GATE_CONFIG`, `HISTORY_DB` | `data/thresholds.json`, `data/history.sqlite3` | Пороги и история |
| `MAX_UPLOAD_BYTES`, `MAX_IMAGE_PIXELS`, `MAX_ANALYSIS_SIDE` | 12 MiB, 24 МП, 2400 | Лимиты входа |
| `MAX_CONCURRENT_ANALYSES` | `2` | Параллельные анализы на процесс |
| `STORE_ANALYSIS_IMAGES`, `PRIVATE_IMAGE_DIR`, `IMAGE_RETENTION_DAYS` | `false`, —, 7 | Хранение оригиналов (по умолчанию нет) |

Пороги типизированы в `backend/gate/config.py`; сохранение атомарное и пишется в аудит.

## 8. Запуск

```powershell
docker compose up --build -d
```

http://localhost:8080, API docs http://localhost:8080/docs. Compose слушает только loopback; для телефона нужен
HTTPS reverse proxy (камера требует HTTPS или localhost).

Локальная разработка (Windows):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
# второй терминал
cd frontend
npm ci
npm run dev
```

Render: один Web Service на `Dockerfile.render` + `render.yaml`, см. [docs/deployment.md](docs/deployment.md).

## 9. Проверки, демо и калибровка

```powershell
python -m pytest -q --basetemp=.test-tmp
cd frontend
npm test
npm run build
# из корня
python -m tools.demo
python -m tools.calibrate demo/synthetic --output reports/synthetic --debug
python -m tools.release_check
```

Фото в `demo/synthetic` создаются локально и явно синтетические.

## 10. Приватность

- Оригиналы фото по умолчанию не сохраняются.
- Декодированное значение возвращается вызывающему, но не пишется в историю и логи.
- Реальные фотографии и датасеты в Git не хранятся.

## 11. Ветки и статус

`main` — актуальный код; `codex/*` — промежуточные этапы. Barcode Gate 1.0.1: проверки на Windows и в Docker
проходят, пороги ещё не откалиброваны на реальных данных.

## 12. Планы

- [ ] Откалибровать пороги на реальных фото.
- [ ] Проверить на физических Android и iPhone.
- [ ] HTTPS, SSO и лимиты перед корпоративным внедрением.

Документация: [алгоритм](docs/algorithm.md) · [калибровка](docs/calibration.md) · [API](docs/api.md) ·
[проверки](docs/verification.md) · [деплой](docs/deployment.md) · [мобильная камера](docs/mobile-camera.md)

---

# English

**VisionGate is a quality gate for barcode photos.** A deterministic CV pipeline on OpenCV and ZXing-C++, a React web
UI, an API, history and offline threshold calibration. The repository also contains an experimental profile for
photos of device boxes with labels (OCR on ONNX models, batch checks, XLSX export).

> Initial thresholds need calibration on real photos from the target domain. Synthetic checks do not prove quality on
> real labels.

## 1. What it is and why

An operator photographs a barcode label (camera or file upload). The system finds and decodes the barcode, measures
sharpness, lighting, contrast, size and orientation of the code area, and answers **ACCEPT** or **RETAKE** with a
clear RU/EN instruction on what to fix.

## 2. Features

- Single-photo analysis: input validation → detection and decoding → code-area metrics → decision.
- Barcode formats (ZXing-C++): Code 128, Code 39, EAN-13/8, UPC-A/E, ITF, QR, Data Matrix.
- ACCEPT / RETAKE decisions with Russian and English instructions.
- Camera with framing guidance, JPEG/PNG/WEBP uploads (EXIF normalized); HEIC/HEIF and animations get a clear
  refusal.
- Threshold admin panel (via `ADMIN_TOKEN`): parameter descriptions, editing, reset, audit.
- Analysis history (metrics, versions and time only — no originals or decoded values).
- Offline threshold calibration on a photo set, JSON/CSV/HTML reports.
- Experimental profile for device box photos: OCR, barcodes, batch checks, XLSX export.
- Concurrency limit (`MAX_CONCURRENT_ANALYSES`), overload → 503 BUSY.

## 3. Tech stack

| Layer | Technologies |
| --- | --- |
| Backend | Python 3.13, FastAPI, Uvicorn, Pydantic + pydantic-settings, python-multipart |
| CV | OpenCV 5 (headless), Pillow, ZXing-C++ 3.1 |
| OCR (experimental profile) | ONNX Runtime, public PP-OCRv5 models, pyclipper |
| Export | openpyxl (XLSX) |
| Frontend | React 19, TypeScript, Vite; Vitest + Testing Library |
| Storage | SQLite (history), JSON threshold config |
| Infrastructure | Docker Compose (backend + Nginx), Render (`render.yaml`, `Dockerfile.render`) |
| Tests | pytest, Vitest |

## 4. Architecture

```text
Image Input → Validation → Detection/Decode → ROI Metrics → Decision Engine → Typed Result
```

- Metrics live in `backend/gate/metrics`. The Decision Engine takes typed objects and does not depend on OpenCV.
- `BarcodeDecoder` is replaceable. A candidate without a successful decode is never accepted.
- The frontend is built into static files served by an unprivileged Nginx; the backend runs Uvicorn without reload.

## 5. Project structure

```text
backend/main.py, render_app.py   FastAPI app and single origin for Render
backend/gate/                    pipeline, decoder, metrics, decisions, config, OCR, storage
frontend/src/                    UI, camera, upload, i18n, API
tools/                           demo, calibrate, dataset_audit, barcode_stress, release_check and box-profile utilities
experiments/                     Barcode Integrity prototype
config/                          thresholds.json and model settings
deploy/                          start.sh, model license notice
tests/                           pytest
docs/                            algorithm, calibration, API, deployment, mobile camera, verification
```

## 6. API

| Method and path | Purpose |
| --- | --- |
| `GET /api/v1/health` | Health check |
| `GET /api/v1/capabilities` | Build capabilities |
| `POST /api/v1/analyze` | Barcode photo analysis → ACCEPT / RETAKE |
| `GET /api/v1/config`, `PUT /api/v1/config` | Thresholds (changes need `ADMIN_TOKEN`) |
| `GET /api/v1/history` | Analysis history (needs `ADMIN_TOKEN`) |

OpenAPI: `/docs`. Details: [docs/api.md](docs/api.md).

## 7. Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `ADMIN_TOKEN` | — | Key for threshold changes and history |
| `GATE_CONFIG`, `HISTORY_DB` | `data/thresholds.json`, `data/history.sqlite3` | Thresholds and history |
| `MAX_UPLOAD_BYTES`, `MAX_IMAGE_PIXELS`, `MAX_ANALYSIS_SIDE` | 12 MiB, 24 MP, 2400 | Input limits |
| `MAX_CONCURRENT_ANALYSES` | `2` | Concurrent analyses per process |
| `STORE_ANALYSIS_IMAGES`, `PRIVATE_IMAGE_DIR`, `IMAGE_RETENTION_DAYS` | `false`, —, 7 | Storing originals (off by default) |

Thresholds are typed in `backend/gate/config.py`; saves are atomic and audited.

## 8. Running

```powershell
docker compose up --build -d
```

http://localhost:8080, API docs http://localhost:8080/docs. Compose listens on loopback only; a phone needs an HTTPS
reverse proxy (the camera needs HTTPS or localhost).

Local development (Windows):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
# second terminal
cd frontend
npm ci
npm run dev
```

Render: one Web Service on `Dockerfile.render` + `render.yaml`, see [docs/deployment.md](docs/deployment.md).

## 9. Checks, demo and calibration

```powershell
python -m pytest -q --basetemp=.test-tmp
cd frontend
npm test
npm run build
# from the root
python -m tools.demo
python -m tools.calibrate demo/synthetic --output reports/synthetic --debug
python -m tools.release_check
```

Photos in `demo/synthetic` are generated locally and are clearly synthetic.

## 10. Privacy

- Original photos are not stored by default.
- The decoded value is returned to the caller but never written to history or logs.
- No real photos or datasets are stored in Git.

## 11. Branches and status

`main` is the current code; `codex/*` are intermediate stages. Barcode Gate 1.0.1: checks pass on Windows and in
Docker; thresholds are not yet calibrated on real data.

## 12. Roadmap

- [ ] Calibrate thresholds on real photos.
- [ ] Test on physical Android and iPhone devices.
- [ ] HTTPS, SSO and rate limits before a corporate rollout.

Documentation: [algorithm](docs/algorithm.md) · [calibration](docs/calibration.md) · [API](docs/api.md) ·
[verification](docs/verification.md) · [deployment](docs/deployment.md) · [mobile camera](docs/mobile-camera.md)
